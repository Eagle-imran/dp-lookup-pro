"""Copy unchanged source layers without downloading or rewriting their payloads."""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Tuple

from dp_lookup.planning_snapshot.models import PlanningSnapshotStateError


def copy_layers(
    connection: sqlite3.Connection,
    source_snapshot_id: int,
    target_snapshot_id: int,
    layer_ids: Iterable[int],
    *,
    rtree_available: bool,
) -> Tuple[int, ...]:
    """Run inside the store transaction; preserve every archived JSON byte."""
    copied = []
    for layer_id in sorted(set(layer_ids)):
        source = connection.execute(
            "SELECT * FROM planning_layers WHERE snapshot_id=? AND canonical_layer_id=?",
            (source_snapshot_id, layer_id),
        ).fetchone()
        if source is None or not source["complete"]:
            raise PlanningSnapshotStateError(f"source layer {layer_id} is absent or incomplete")
        existing = connection.execute(
            "SELECT metadata_json FROM planning_layers WHERE snapshot_id=? AND canonical_layer_id=?",
            (target_snapshot_id, layer_id),
        ).fetchone()
        if existing is not None:
            metadata = json.loads(existing["metadata_json"])
            if metadata.get("inherited_from_snapshot_id") != source_snapshot_id:
                raise PlanningSnapshotStateError(f"target layer {layer_id} was not inherited from this source")
            continue
        metadata = json.loads(source["metadata_json"])
        metadata["inherited_from_snapshot_id"] = source_snapshot_id
        connection.execute(
            "INSERT INTO planning_layers(snapshot_id,layer_id,canonical_layer_id,name,geometry_type,"
            "object_id_field,metadata_json,expected_count,received_count) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                target_snapshot_id,
                source["layer_id"],
                layer_id,
                source["name"],
                source["geometry_type"],
                source["object_id_field"],
                json.dumps(metadata, sort_keys=True),
                source["expected_count"],
                source["received_count"],
            ),
        )
        connection.execute(
            "INSERT INTO planning_layer_inventory(snapshot_id,canonical_layer_id,object_id) "
            "SELECT ?,canonical_layer_id,object_id FROM planning_layer_inventory "
            "WHERE snapshot_id=? AND canonical_layer_id=?",
            (target_snapshot_id, source_snapshot_id, layer_id),
        )
        connection.execute(
            "INSERT INTO planning_features(snapshot_id,canonical_layer_id,object_id,attributes_json,"
            "geometry_json,raw_feature_json,bbox_min_x,bbox_max_x,bbox_min_y,bbox_max_y) "
            "SELECT ?,canonical_layer_id,object_id,attributes_json,geometry_json,raw_feature_json,"
            "bbox_min_x,bbox_max_x,bbox_min_y,bbox_max_y FROM planning_features "
            "WHERE snapshot_id=? AND canonical_layer_id=?",
            (target_snapshot_id, source_snapshot_id, layer_id),
        )
        if rtree_available:
            connection.execute(
                "INSERT INTO planning_feature_rtree_map(snapshot_id,canonical_layer_id,object_id) "
                "SELECT snapshot_id,canonical_layer_id,object_id FROM planning_features "
                "WHERE snapshot_id=? AND canonical_layer_id=? AND bbox_min_x IS NOT NULL",
                (target_snapshot_id, layer_id),
            )
            connection.execute(
                "INSERT INTO planning_feature_rtree(id,min_x,max_x,min_y,max_y) "
                "SELECT m.id,f.bbox_min_x,f.bbox_max_x,f.bbox_min_y,f.bbox_max_y "
                "FROM planning_feature_rtree_map m JOIN planning_features f "
                "ON f.snapshot_id=m.snapshot_id AND f.canonical_layer_id=m.canonical_layer_id "
                "AND f.object_id=m.object_id WHERE m.snapshot_id=? AND m.canonical_layer_id=?",
                (target_snapshot_id, layer_id),
            )
        copied.append(layer_id)
    return tuple(copied)
