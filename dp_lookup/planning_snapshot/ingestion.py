"""Offline ingestion helpers for already-captured ArcGIS planning payloads.

Network acquisition is intentionally outside this module.  A caller may feed
captured feature arrays from a file, test fixture, or a future bounded client;
this helper only validates, batches, and publishes them through the durable
planning snapshot store.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dp_lookup.planning_snapshot.models import PlanningSnapshot, utc_now
from dp_lookup.planning_snapshot.store import PlanningSnapshotStore


@dataclass(frozen=True)
class PlanningLayerInput:
    layer_id: int
    features: Iterable[Any]
    name: str = ""
    geometry_type: str | None = None
    object_id_field: str = "OBJECTID"
    expected_count: int | None = None
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]
    inventory: Sequence[int] | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


def ingest_planning_snapshot(
    store: PlanningSnapshotStore,
    layers: Mapping[int, Iterable[Any]] | Iterable[PlanningLayerInput],
    *,
    source_url: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    version: int | None = None,
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
        inputs = tuple(
            PlanningLayerInput(layer_id=int(layer_id), features=features) for layer_id, features in layers.items()
        )
    else:
        inputs = tuple(layers)
    snapshot_id = store.begin_snapshot(source_url=source_url, metadata=metadata, version=version)
    try:
        for layer in inputs:
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
        try:
            store.connection.execute(
                "UPDATE planning_snapshots SET state='failed',finalized_at=?,validation_json=? WHERE snapshot_id=? AND state='building'",
                (utc_now(), json.dumps({"ok": False, "errors": [str(exc)]}), snapshot_id),
            )
            store.connection.commit()
        except sqlite3.Error:
            store.connection.rollback()
        raise


__all__ = ["PlanningLayerInput", "ingest_planning_snapshot"]
