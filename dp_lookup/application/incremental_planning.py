"""Verified planning refreshes that download only explicitly selected layers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, Mapping, Tuple, cast

from dp_lookup.application.planning_database_services import _atomic_json_write, _manifest_summary
from dp_lookup.application.planning_snapshot import (
    PlanningFeature,
    PlanningIngestionConfig,
    PlanningSnapshotError,
    canonical_planning_specs,
    planning_registry_hash,
)
from dp_lookup.planning_evidence.models import LayerSpec
from dp_lookup.planning_evidence.registry import SERVER_URL, canonical_layer_id
from dp_lookup.planning_snapshot import PlanningSnapshotStore

if TYPE_CHECKING:
    from dp_lookup.application.planning_database_services import LocalPlanningDatabaseServices


def _fingerprints(
    report: Mapping[str, Any], base_id: int, layer_ids: set[int], refresh_ids: set[int]
) -> Dict[str, Any]:
    planning = report.get("planning")
    if not isinstance(planning, Mapping):
        raise PlanningSnapshotError("incremental refresh requires a complete upstream planning check")
    rows = {int(row["canonical_layer_id"]): row for row in planning.get("layers", ())}
    if set(rows) != layer_ids:
        raise PlanningSnapshotError("upstream check does not cover the complete planning registry")
    result = {}
    for layer_id, row in rows.items():
        if row.get("local", {}).get("snapshot_id") != base_id:
            raise PlanningSnapshotError("active planning snapshot changed during incremental refresh")
        if row.get("status") not in {"unchanged", "changed"}:
            raise PlanningSnapshotError(f"upstream state for layer {layer_id} is unknown; retry the check")
        if layer_id not in refresh_ids and row["status"] != "unchanged":
            raise PlanningSnapshotError(f"layer {layer_id} also changed; include it in --layers")
        remote = row.get("upstream", {})
        result[str(layer_id)] = {
            key: remote.get(key) for key in ("record_count", "inventory_hash", "metadata_hash", "max_last_edited_date")
        }
    return result


async def build_incremental_planning(
    services: LocalPlanningDatabaseServices, database: Path, options: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Stage a complete immutable snapshot; never change an active pointer."""
    if not database.is_file():
        raise PlanningSnapshotError("incremental refresh requires an existing active planning database")
    specs = canonical_planning_specs()
    registry_ids = {spec.layer_id for spec in specs}
    refresh_ids = {canonical_layer_id(int(value)) for value in options["layer_ids"]}
    if not refresh_ids or not refresh_ids.issubset(registry_ids):
        raise PlanningSnapshotError("--layers must select canonical planning layers from the audited registry")
    copied_ids = registry_ids - refresh_ids
    selected_specs = tuple(spec for spec in specs if spec.layer_id in refresh_ids)
    base_config = options.get("config")
    if not isinstance(base_config, PlanningIngestionConfig):
        base_config = PlanningIngestionConfig()
    config = replace(
        base_config,
        all_fields=True,
        fetch_layer_metadata=True,
        request_delay_seconds=max(0.25, base_config.request_delay_seconds),
    )
    manifest_path = Path(options.get("manifest") or database.with_suffix(".planning-incremental.manifest.json"))
    checkpoint_path = database.with_suffix(".planning-incremental.checkpoint.json")
    registry_hash = planning_registry_hash(specs)
    with PlanningSnapshotStore.open(database) as store:
        base_id = store.active_snapshot_id()
        if base_id is None:
            raise PlanningSnapshotError("incremental refresh requires an active planning snapshot")
        base = store.snapshot(base_id)
        if not base.complete or {layer.canonical_layer_id for layer in base.layers} != registry_ids:
            raise PlanningSnapshotError("active planning snapshot does not contain the complete current registry")
        async with services.client_factory() as client:
            before = await services.upstream_checker(client, database)
            fingerprints = _fingerprints(before, base_id, registry_ids, refresh_ids)
            snapshot_id = store.find_resumable_snapshot(
                registry_hash, base_snapshot_id=base_id, refresh_layer_ids=sorted(refresh_ids)
            )
            resumed = snapshot_id is not None
            if snapshot_id is None:
                snapshot_id = store.begin_snapshot(
                    source_url=SERVER_URL,
                    metadata={
                        "dataset": "MCGM Development Plan 2034 canonical planning layers",
                        "registry_hash": registry_hash,
                        "registry_layer_ids": sorted(registry_ids),
                        "all_source_fields": True,
                        "refresh_mode": "incremental",
                        "base_snapshot_id": base_id,
                        "base_finalized_at": base.finalized_at,
                        "refresh_layer_ids": sorted(refresh_ids),
                        "copied_layer_ids": sorted(copied_ids),
                        "upstream_fingerprints": fingerprints,
                        "upstream_checked_at": before.get("checked_at"),
                        "verification_limit": "Copied layers retain their archived payloads; matching inventories and "
                        "edit signals cannot prove every coordinate under an existing ObjectID is unchanged.",
                    },
                )
            elif store.snapshot(snapshot_id).metadata.get("upstream_fingerprints") != fingerprints:
                store.fail_snapshot(snapshot_id, "upstream changed since the incremental build started")
                raise PlanningSnapshotError("upstream changed since the incremental build started; rerun to stage anew")
            store.copy_layers(base_id, snapshot_id, copied_ids)
            fetched_count = 0

            async def accept_inventory(
                spec: LayerSpec, expected_ids: Tuple[int, ...], context: Mapping[str, Any]
            ) -> Iterable[int]:
                store.register_layer(
                    snapshot_id,
                    spec.layer_id,
                    name=spec.name,
                    geometry_type=str(context.get("geometry_type") or spec.geometry_type),
                    object_id_field=str(context.get("object_id_field") or spec.object_id_field),
                    expected_count=len(expected_ids),
                    metadata={
                        "evidence_class": spec.evidence_class.value,
                        "query_policy": spec.query_policy.value,
                        "role": spec.role,
                        "audit_note": spec.audit_note,
                        "source_context": dict(context),
                    },
                )
                store.set_layer_inventory(snapshot_id, spec.layer_id, expected_ids)
                return cast(Iterable[int], store.object_ids(snapshot_id, spec.layer_id))

            async def accept_batch(spec: LayerSpec, features: Tuple[PlanningFeature, ...]) -> None:
                nonlocal fetched_count
                store.insert_batch(snapshot_id, spec.layer_id, features)
                fetched_count += len(features)

            try:
                result = await services.importer(
                    client,
                    specs=selected_specs,
                    config=config,
                    checkpoint=None,
                    on_inventory=accept_inventory,
                    on_batch=accept_batch,
                    retain_features=False,
                )
            except Exception as exc:
                if "different inventory" in str(exc) or "differs from its persisted inventory" in str(exc):
                    store.fail_snapshot(snapshot_id, str(exc))
                raise
            _atomic_json_write(checkpoint_path, result.checkpoint.to_dict())
            _atomic_json_write(manifest_path, result.manifest.to_dict())
            metadata = dict(store.snapshot(snapshot_id).metadata)
            metadata.update(
                {
                    "manifest_path": str(manifest_path),
                    "checkpoint_path": str(checkpoint_path),
                    "manifest_summary": dict(_manifest_summary(result)),
                }
            )
            store.update_snapshot_metadata(snapshot_id, metadata)
            if not result.complete:
                raise PlanningSnapshotError("incremental planning refresh is incomplete and remains resumable")
            try:
                after = await services.upstream_checker(client, database)
                if _fingerprints(after, base_id, registry_ids, refresh_ids) != fingerprints:
                    raise PlanningSnapshotError("upstream changed during incremental refresh; rerun to stage anew")
                if store.active_snapshot_id() != base_id:
                    raise PlanningSnapshotError("active planning snapshot changed during incremental refresh")
            except Exception as exc:
                store.fail_snapshot(snapshot_id, str(exc))
                raise
            metadata["upstream_verified_at"] = after.get("checked_at")
            store.update_snapshot_metadata(snapshot_id, metadata)
            store.copy_layers(base_id, snapshot_id, copied_ids)
            snapshot = store.finalize(snapshot_id)
            return {
                "snapshot_id": snapshot_id,
                "state": snapshot.state,
                "refresh_mode": "incremental",
                "base_snapshot_id": base_id,
                "layers": len(snapshot.layers),
                "records": sum(layer.received_count for layer in snapshot.layers),
                "refreshed_layer_ids": sorted(refresh_ids),
                "copied_layer_ids": sorted(copied_ids),
                "fetched_records": fetched_count,
                "resumed": resumed,
                "content_hash": snapshot.content_hash,
                "manifest": str(manifest_path),
                "checkpoint": str(checkpoint_path),
                "note": "ready but not active; verify, then activate-planning",
            }
