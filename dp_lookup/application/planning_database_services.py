"""Application services for complete local planning-layer snapshots."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional, Protocol, Tuple, cast

from dp_lookup.application.planning_snapshot import (
    PlanningFeature,
    PlanningIngestionConfig,
    PlanningSnapshotCheckpoint,
    PlanningSnapshotError,
    PlanningSnapshotResult,
    canonical_planning_specs,
    ingest_planning_snapshot,
    planning_registry_hash,
)
from dp_lookup.application.upstream_check import check_database_upstream
from dp_lookup.clients.transport import ArcGISClient, RetryPolicy
from dp_lookup.core.constants import SERVER_URL
from dp_lookup.planning_evidence.models import LayerSpec
from dp_lookup.planning_snapshot import PlanningSnapshotStore


class AsyncClientContext(Protocol):
    async def __aenter__(self) -> Any: ...

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


PlanningImporter = Callable[..., Awaitable[PlanningSnapshotResult]]


def _default_client_factory() -> AsyncClientContext:
    return cast(
        AsyncClientContext,
        ArcGISClient(timeout_seconds=120.0, retry_policy=RetryPolicy(max_attempts=1)),
    )


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _checkpoint_path(database: Path, configured: Any) -> Path:
    if configured:
        return Path(configured)
    return database.with_suffix(database.suffix + ".planning.checkpoint.json")


def _manifest_path(database: Path, configured: Any) -> Path:
    if configured:
        return Path(configured)
    return database.with_suffix(database.suffix + ".planning.manifest.json")


def _load_checkpoint(path: Path) -> Optional[PlanningSnapshotCheckpoint]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanningSnapshotError(f"planning checkpoint is unreadable: {path} ({exc})") from exc
    if not isinstance(payload, Mapping):
        raise PlanningSnapshotError(f"planning checkpoint is not a JSON object: {path}")
    return PlanningSnapshotCheckpoint.from_dict(payload)


def _manifest_summary(result: PlanningSnapshotResult) -> Mapping[str, Any]:
    return {
        "complete": result.complete,
        "registry_hash": result.manifest.registry_hash,
        "content_hash": result.manifest.content_hash,
        "retrieved_at": result.manifest.retrieved_at,
        "layer_count": len(result.manifest.layers),
        "expected_feature_count": sum(len(layer.expected_ids) for layer in result.manifest.layers),
        "received_feature_count": sum(len(layer.received_ids) for layer in result.manifest.layers),
        "incomplete_layer_count": sum(1 for layer in result.manifest.layers if not layer.complete),
        "warnings": list(result.manifest.warnings),
    }


@dataclass
class LocalPlanningDatabaseServices:
    """Build and administer planning snapshots inside the main SQLite file."""

    importer: PlanningImporter = ingest_planning_snapshot
    client_factory: Callable[[], AsyncClientContext] = _default_client_factory
    upstream_checker: Callable[[Any, Path], Awaitable[Mapping[str, Any]]] = check_database_upstream

    def build_planning(self, database: Path, options: Mapping[str, Any]) -> Mapping[str, Any]:
        return asyncio.run(self._build(database, options))

    async def _build(self, database: Path, options: Mapping[str, Any]) -> Mapping[str, Any]:
        if options.get("layer_ids") is not None:
            from dp_lookup.application.incremental_planning import build_incremental_planning

            return await build_incremental_planning(self, database, options)
        selected_specs = canonical_planning_specs()
        registry_hash = planning_registry_hash(selected_specs)
        configured = options.get("config")
        base_config = configured if isinstance(configured, PlanningIngestionConfig) else PlanningIngestionConfig()
        config = replace(
            base_config,
            all_fields=True,
            fetch_layer_metadata=True,
            # A small inter-batch pause is respectful of the public service;
            # metadata and inventory requests are already sequential.
            request_delay_seconds=max(0.25, base_config.request_delay_seconds),
        )
        checkpoint_path = _checkpoint_path(database, options.get("resume"))
        manifest_path = _manifest_path(database, options.get("manifest"))

        with PlanningSnapshotStore.open(database) as store:
            snapshot_id = store.find_resumable_snapshot(registry_hash)
            resumed = snapshot_id is not None
            if snapshot_id is None:
                snapshot_id = store.begin_snapshot(
                    source_url=SERVER_URL,
                    metadata={
                        "dataset": "MCGM Development Plan 2034 canonical planning layers",
                        "registry_hash": registry_hash,
                        "registry_layer_ids": [spec.layer_id for spec in selected_specs],
                        "all_source_fields": True,
                    },
                )
                checkpoint = None
            else:
                # The SQLite inventory and stored ObjectIDs are the primary
                # resume proof. An external checkpoint is consulted only when
                # the caller explicitly supplied one, avoiding reuse of a
                # stale checkpoint from an older completed snapshot.
                checkpoint = _load_checkpoint(Path(options["resume"])) if options.get("resume") else None

            async def accept_inventory(
                spec: LayerSpec,
                expected_ids: Tuple[int, ...],
                source_context: Mapping[str, Any],
            ) -> Iterable[int]:
                store.register_layer(
                    snapshot_id,
                    spec.layer_id,
                    name=spec.name,
                    geometry_type=str(source_context.get("geometry_type") or spec.geometry_type),
                    object_id_field=str(source_context.get("object_id_field") or spec.object_id_field),
                    expected_count=len(expected_ids),
                    metadata={
                        "evidence_class": spec.evidence_class.value,
                        "query_policy": spec.query_policy.value,
                        "role": spec.role,
                        "audit_note": spec.audit_note,
                        "source_context": dict(source_context),
                    },
                )
                store.set_layer_inventory(snapshot_id, spec.layer_id, expected_ids)
                return cast(Iterable[int], store.object_ids(snapshot_id, spec.layer_id))

            async def accept_batch(spec: LayerSpec, features: Tuple[PlanningFeature, ...]) -> None:
                store.insert_batch(snapshot_id, spec.layer_id, features)

            try:
                async with self.client_factory() as client:
                    result = await self.importer(
                        client,
                        specs=selected_specs,
                        config=config,
                        checkpoint=checkpoint,
                        on_inventory=accept_inventory,
                        on_batch=accept_batch,
                        retain_features=False,
                    )
            except Exception as exc:
                # Source-inventory drift makes the partial snapshot unsafe to
                # resume. Other failures retain the building snapshot so a
                # later command can continue from its durable feature IDs.
                if "different inventory" in str(exc):
                    store.fail_snapshot(snapshot_id, str(exc))
                raise

            _atomic_json_write(checkpoint_path, result.checkpoint.to_dict())
            _atomic_json_write(manifest_path, result.manifest.to_dict())
            summary = _manifest_summary(result)
            store.update_snapshot_metadata(
                snapshot_id,
                {
                    "dataset": "MCGM Development Plan 2034 canonical planning layers",
                    "registry_hash": registry_hash,
                    "registry_layer_ids": [spec.layer_id for spec in selected_specs],
                    "all_source_fields": True,
                    "manifest_path": str(manifest_path),
                    "checkpoint_path": str(checkpoint_path),
                    "manifest_summary": dict(summary),
                },
            )
            if not result.complete:
                raise PlanningSnapshotError(
                    "planning snapshot is incomplete and remains resumable: "
                    f"incomplete_layers={summary['incomplete_layer_count']}; rerun the same command"
                )
            snapshot = store.finalize(snapshot_id)
            return {
                "snapshot_id": snapshot.snapshot_id,
                "version": snapshot.version,
                "state": snapshot.state,
                "layers": len(snapshot.layers),
                "records": sum(layer.received_count for layer in snapshot.layers),
                "content_hash": snapshot.content_hash,
                "resumed": resumed,
                "manifest": str(manifest_path),
                "checkpoint": str(checkpoint_path),
                "note": "planning snapshot is ready but not active; verify, then activate-planning",
            }

    def status_planning(self, database: Path, options: Mapping[str, Any]) -> Mapping[str, Any]:
        del options
        if not database.is_file():
            return {"path": str(database), "exists": False, "active_snapshot_id": None, "snapshots": []}
        with PlanningSnapshotStore.open(database) as store:
            return {**store.status(), "exists": True}

    def verify_planning(self, database: Path, options: Mapping[str, Any]) -> Mapping[str, Any]:
        del options
        if not database.is_file():
            raise RuntimeError(f"database does not exist: {database}")
        with PlanningSnapshotStore.open(database) as store:
            status = store.status()
            ready = [item for item in status["snapshots"] if item["state"] == "ready"]
            snapshot_id = int(ready[-1]["snapshot_id"]) if ready else store.active_snapshot_id()
            if snapshot_id is None:
                raise RuntimeError("database has no active or ready planning snapshot")
            report = store.validate(snapshot_id)
            report["content_hash"] = store.content_hash(snapshot_id)
            return cast(Mapping[str, Any], report)

    def activate_planning(self, database: Path, options: Mapping[str, Any]) -> Mapping[str, Any]:
        del options
        with PlanningSnapshotStore.open(database) as store:
            status = store.status()
            ready = [item for item in status["snapshots"] if item["state"] == "ready"]
            if not ready:
                active = store.active_snapshot_id()
                if active is not None:
                    return {"snapshot_id": active, "state": "active", "changed": False}
                raise RuntimeError("database has no ready planning snapshot")
            snapshot = store.activate(int(ready[-1]["snapshot_id"]))
            return {
                "snapshot_id": snapshot.snapshot_id,
                "version": snapshot.version,
                "state": snapshot.state,
                "changed": True,
            }

    def rollback_planning(self, database: Path, options: Mapping[str, Any]) -> Mapping[str, Any]:
        del options
        with PlanningSnapshotStore.open(database) as store:
            snapshot = store.rollback()
            return {"snapshot_id": snapshot.snapshot_id, "version": snapshot.version, "state": snapshot.state}


__all__ = ["LocalPlanningDatabaseServices"]
