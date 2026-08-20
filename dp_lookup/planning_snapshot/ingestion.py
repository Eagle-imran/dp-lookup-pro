"""Offline ingestion helpers for already-captured ArcGIS planning payloads.

Network acquisition is intentionally outside this module.  A caller may feed
captured feature arrays from a file, test fixture, or a future bounded client;
this helper only validates, batches, and publishes them through the durable
planning snapshot store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from dp_lookup.planning_snapshot.models import PlanningSnapshot, utc_now
from dp_lookup.planning_snapshot.store import PlanningSnapshotStore


@dataclass(frozen=True)
class PlanningLayerInput:
    layer_id: int
    features: Iterable[Any]
    name: str = ""
    geometry_type: Optional[str] = None
    object_id_field: str = "OBJECTID"
    expected_count: Optional[int] = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]
    inventory: Optional[Sequence[int]] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


def ingest_planning_snapshot(
    store: PlanningSnapshotStore,
    layers: Union[Mapping[int, Iterable[Any]], Iterable[PlanningLayerInput]],
    *,
    source_url: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    version: Optional[int] = None,
    batch_size: int = 1000,
) -> PlanningSnapshot:
    """Persist and finalize one captured planning-layer snapshot.

    Every call starts a new immutable version.  Each batch is one SQLite
    transaction, while feature preparation happens before that transaction so
    a malformed or conflicting batch cannot partially commit.
    """

    if isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("batch_size must be positive")
    if isinstance(layers, Mapping):
        inputs = tuple(PlanningLayerInput(layer_id=int(layer_id), features=features) for layer_id, features in layers.items())
    else:
        inputs = tuple(layers)
    snapshot_id = store.begin_snapshot(source_url=source_url, metadata=metadata, version=version)
    try:
        for layer in inputs:
            # Materialise once so generators can provide an authoritative count
            # and can be split into bounded, atomic batches.
            captured = tuple(layer.features)
            expected = layer.expected_count if layer.expected_count is not None else len(captured)
            store.register_layer(
                snapshot_id,
                layer.layer_id,
                name=layer.name,
                geometry_type=layer.geometry_type,
                object_id_field=layer.object_id_field,
                expected_count=expected,
                metadata=layer.metadata,
            )
            if layer.inventory is not None:
                store.set_layer_inventory(snapshot_id, layer.layer_id, layer.inventory)
            for offset in range(0, len(captured), batch_size):
                store.insert_batch(snapshot_id, layer.layer_id, captured[offset : offset + batch_size])
        return store.finalize(snapshot_id)
    except Exception as exc:
        # Keep the failed version and its diagnostics; do not delete evidence
        # or accidentally make a partial snapshot eligible for activation.
        try:
            store.connection.execute(
                "UPDATE planning_snapshots SET state='failed',finalized_at=?,validation_json=? WHERE snapshot_id=? AND state='building'",
                (utc_now(), json.dumps({"ok": False, "errors": [str(exc)]}), snapshot_id),
            )
            store.connection.commit()
        except Exception:
            store.connection.rollback()
        raise


build_planning_snapshot = ingest_planning_snapshot

__all__ = ["PlanningLayerInput", "build_planning_snapshot", "ingest_planning_snapshot"]
