"""Application services for building and administering local parcel snapshots."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Tuple, cast

from dp_lookup.application.snapshot_ingestion import (
    SnapshotIngestionConfig,
    ingest_layer13_snapshot,
)
from dp_lookup.clients.parcel_snapshot import (
    LAYER13_URL,
    SnapshotFeature,
    SnapshotIngestionError,
    SnapshotIngestionResult,
    sha256_json,
)
from dp_lookup.clients.transport import ArcGISClient, RetryPolicy
from dp_lookup.spatial_store import SnapshotStore


class AsyncClientContext(Protocol):
    async def __aenter__(self) -> Any: ...

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


SnapshotImporter = Callable[..., Awaitable[SnapshotIngestionResult]]


def _default_client_factory() -> AsyncClientContext:
    # The snapshot importer owns retry/backoff, so the shared HTTP facade gets
    # one transport attempt per importer attempt rather than multiplying both
    # retry loops into as many as nine requests.
    return cast(
        AsyncClientContext,
        ArcGISClient(timeout_seconds=120.0, retry_policy=RetryPolicy(max_attempts=1)),
    )


def _chunks(values: Sequence[SnapshotFeature], size: int) -> Iterable[Sequence[SnapshotFeature]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _store_record(feature: SnapshotFeature) -> Mapping[str, Any]:
    return {
        "objectid": feature.object_id,
        "attributes": dict(feature.attributes),
        "geometry": dict(feature.geometry),
        "raw_feature": dict(feature.raw_feature),
    }


def _manifest_metadata(result: SnapshotIngestionResult) -> Dict[str, Any]:
    """Keep full audit evidence while also exposing a compact status summary."""
    manifest = result.manifest.to_dict()
    return {
        "dataset": "MCGM Development Plan 2034 Layer 13",
        "manifest": manifest,
        "manifest_summary": {
            "expected_count": len(result.manifest.expected_ids),
            "received_count": len(result.manifest.received_ids),
            "missing_count": len(result.manifest.missing_ids),
            "duplicate_objectid_count": len(result.manifest.duplicate_ids),
            "rejected_count": len(result.manifest.rejected_ids),
            "invalid_feature_count": result.manifest.invalid_feature_count,
            "content_hash": result.manifest.content_hash,
            "fetched_at": result.manifest.fetched_at,
            "requested_out_sr": result.manifest.requested_out_sr,
        },
    }


@dataclass
class LocalDatabaseServices:
    """Concrete database CLI services using the official ArcGIS source."""

    importer: SnapshotImporter = ingest_layer13_snapshot
    client_factory: Callable[[], AsyncClientContext] = _default_client_factory
    ingestion_config: SnapshotIngestionConfig = field(
        default_factory=lambda: SnapshotIngestionConfig(
            batch_size=2000,
            max_attempts=3,
            base_delay_seconds=0.5,
            max_delay_seconds=8.0,
            # One sequential request every few seconds is intentionally gentle
            # for an official public service and still completes in minutes.
            request_delay_seconds=2.0,
            fetch_layer_metadata=True,
        )
    )
    store_batch_size: int = 2000

    def build(self, database: Path) -> Mapping[str, Any]:
        return asyncio.run(self._build(database))

    async def _build(self, database: Path) -> Mapping[str, Any]:
        store: Optional[SnapshotStore] = None
        snapshot_id: Optional[int] = None
        resumed_records = 0
        streamed = False

        async def accept_inventory(expected_ids: Tuple[int, ...], source_context: Mapping[str, Any]) -> Iterable[int]:
            nonlocal store, snapshot_id, resumed_records, streamed
            streamed = True
            if store is None:
                store = SnapshotStore.open(database)
            inventory_contract = {
                "source_url": LAYER13_URL,
                "layer_id": 13,
                "requested_out_sr": self.ingestion_config.out_sr,
                "object_id_field": source_context.get("object_id_field"),
                "schema_version": store.status()["schema_version"],
                "expected_ids": expected_ids,
            }
            inventory_hash = sha256_json(inventory_contract)
            snapshot_id = store.find_resumable_snapshot(
                source=LAYER13_URL,
                expected_count=len(expected_ids),
                inventory_hash=inventory_hash,
            )
            if snapshot_id is None:
                snapshot_id = store.begin_snapshot(
                    source=LAYER13_URL,
                    expected_count=len(expected_ids),
                    metadata={
                        "dataset": "MCGM Development Plan 2034 Layer 13",
                        "inventory_hash": inventory_hash,
                        "inventory_count": len(expected_ids),
                        "source_context": dict(source_context),
                    },
                )
                store.set_inventory(snapshot_id, expected_ids)
            else:
                store.set_inventory(snapshot_id, expected_ids)
            persisted: Tuple[int, ...] = store.object_ids(snapshot_id)
            resumed_records = len(persisted)
            return persisted

        async def accept_batch(features: Tuple[SnapshotFeature, ...]) -> None:
            if store is None or snapshot_id is None:
                raise RuntimeError("snapshot inventory was not initialized")
            store.insert_batch(snapshot_id, (_store_record(feature) for feature in features))

        try:
            async with self.client_factory() as client:
                result = await self.importer(
                    client,
                    config=self.ingestion_config,
                    on_inventory=accept_inventory,
                    on_batch=accept_batch,
                    retain_features=False,
                )
            if not result.complete:
                manifest = result.manifest
                if store is not None and snapshot_id is not None:
                    initial_metadata = store.snapshot_metadata(snapshot_id)
                    partial_metadata = _manifest_metadata(result)
                    partial_metadata.update(
                        {
                            "inventory_hash": initial_metadata.get("inventory_hash"),
                            "resumed_records": resumed_records,
                            "resumable": True,
                        }
                    )
                    store.update_snapshot_metadata(snapshot_id, partial_metadata)
                raise SnapshotIngestionError(
                    "Layer 13 snapshot is incomplete and was not written or finalized: "
                    f"missing={len(manifest.missing_ids)}, "
                    f"rejected={len(manifest.rejected_ids)}, "
                    f"extra={len(manifest.extra_ids)}, "
                    f"batch_errors={len(manifest.batch_errors)}; rerun the same command to resume"
                )

            # Test/custom importers may not implement the streaming callbacks;
            # preserve the original injected-importer contract for them.
            if store is None or snapshot_id is None:
                store = SnapshotStore.open(database)
                snapshot_id = store.begin_snapshot(
                    source=LAYER13_URL,
                    expected_count=len(result.manifest.expected_ids),
                    metadata=_manifest_metadata(result),
                )
                store.set_inventory(snapshot_id, result.manifest.expected_ids)
                for batch in _chunks(result.features, self.store_batch_size):
                    store.insert_batch(snapshot_id, (_store_record(feature) for feature in batch))

            if streamed:
                persisted_hash = store.content_hash(snapshot_id)
                result = replace(result, manifest=replace(result.manifest, content_hash=persisted_hash))
            metadata = _manifest_metadata(result)
            metadata["inventory_hash"] = store.snapshot_metadata(snapshot_id).get("inventory_hash")
            metadata["resumed_records"] = resumed_records
            store.update_snapshot_metadata(snapshot_id, metadata)
            if result.manifest.duplicate_ids:
                store.add_issue(
                    snapshot_id,
                    "duplicate_source_objectids",
                    f"source inventory/response repeated {len(result.manifest.duplicate_ids)} ObjectIDs",
                    severity="warning",
                    details={"objectids": list(result.manifest.duplicate_ids)},
                )
            snapshot = store.finalize_snapshot(snapshot_id)
            duplicate_groups = store.duplicate_identity_groups(snapshot_id=snapshot_id)
            return {
                "snapshot_id": snapshot.snapshot_id,
                "state": snapshot.state,
                "records": snapshot.received_count,
                "resumed_records": resumed_records,
                "content_hash": result.manifest.content_hash,
                "fetched_at": result.manifest.fetched_at,
                "duplicate_identity_groups": len(duplicate_groups),
                "note": "snapshot is ready but not active; run database activate after review",
            }
        finally:
            if store is not None:
                store.close()

    def status(self, database: Path) -> Mapping[str, Any]:
        if not database.exists():
            return {"path": str(database), "exists": False, "active_snapshot_id": None, "snapshots": []}
        with SnapshotStore.open(database) as store:
            status = store.status()
            status["exists"] = True
            return cast(Mapping[str, Any], status)

    def verify(self, database: Path) -> Mapping[str, Any]:
        if not database.is_file():
            raise RuntimeError(f"database does not exist: {database}")
        with SnapshotStore.open(database) as store:
            candidates = [item for item in store.status()["snapshots"] if item["state"] == "ready"]
            snapshot_id = int(candidates[-1]["snapshot_id"]) if candidates else store.active_snapshot_id()
            if snapshot_id is None:
                raise RuntimeError("database has no active or ready snapshot")
            report = store.validate_snapshot(snapshot_id)
            report["integrity"] = store.integrity_check(snapshot_id)
            return cast(Mapping[str, Any], report)

    def diff(self, database: Path) -> Mapping[str, Any]:
        with SnapshotStore.open(database) as store:
            candidates = [
                int(item["snapshot_id"])
                for item in store.status()["snapshots"]
                if item["state"] in {"ready", "active", "retired"}
            ]
            if len(candidates) < 2:
                raise RuntimeError("database needs at least two finalized snapshots to diff")
            return cast(Mapping[str, Any], store.diff_snapshots(candidates[-2], candidates[-1]))

    def activate(self, database: Path) -> Mapping[str, Any]:
        with SnapshotStore.open(database) as store:
            ready = [item for item in store.status()["snapshots"] if item["state"] == "ready"]
            if not ready:
                active = store.active_snapshot_id()
                if active is not None:
                    return {"snapshot_id": active, "state": "active", "changed": False}
                raise RuntimeError("database has no ready snapshot to activate")
            snapshot = store.activate(int(ready[-1]["snapshot_id"]))
            return {"snapshot_id": snapshot.snapshot_id, "state": snapshot.state, "changed": True}

    def rollback(self, database: Path) -> Mapping[str, Any]:
        with SnapshotStore.open(database) as store:
            snapshot = store.rollback()
            return {"snapshot_id": snapshot.snapshot_id, "state": snapshot.state}


__all__ = ["LocalDatabaseServices"]
