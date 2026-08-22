"""Read-only planning snapshot completeness checks."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any, Dict, List

from dp_lookup.planning_snapshot.codecs import bbox


def validate_snapshot(connection: sqlite3.Connection, snapshot_id: int, layer_hash: Callable[[int, int], str]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    layers: List[Dict[str, Any]] = []
    for layer in connection.execute("SELECT * FROM planning_layers WHERE snapshot_id=? ORDER BY canonical_layer_id", (snapshot_id,)):
        layer_id = int(layer["canonical_layer_id"])
        count = int(connection.execute("SELECT COUNT(*) FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, layer_id)).fetchone()[0])
        expected = layer["expected_count"]
        inventory = int(connection.execute("SELECT COUNT(*) FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, layer_id)).fetchone()[0])
        layer_errors: List[str] = []
        layer_warnings: List[str] = []
        if expected is not None and count != int(expected):
            layer_errors.append(f"expected {expected} features, received {count}")
        if inventory:
            missing = connection.execute("SELECT object_id FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=? EXCEPT SELECT object_id FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? LIMIT 20", (snapshot_id, layer_id, snapshot_id, layer_id)).fetchall()
            extra = connection.execute("SELECT object_id FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? EXCEPT SELECT object_id FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=? LIMIT 20", (snapshot_id, layer_id, snapshot_id, layer_id)).fetchall()
            if missing:
                layer_errors.append("inventory IDs missing: " + ", ".join(str(row[0]) for row in missing))
            if extra:
                layer_errors.append("feature IDs absent from inventory: " + ", ".join(str(row[0]) for row in extra))
        for feature in connection.execute("SELECT object_id,attributes_json,geometry_json FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, layer_id)):
            try:
                json.loads(feature["attributes_json"])
                if feature["geometry_json"] is None:
                    layer_warnings.append(f"object ID {feature['object_id']}: source geometry is missing")
                elif bbox(json.loads(feature["geometry_json"])) is None:
                    layer_warnings.append(f"object ID {feature['object_id']}: source geometry has no finite coordinates")
            except (TypeError, ValueError) as exc:
                layer_errors.append(f"object ID {feature['object_id']}: invalid JSON ({exc})")
        errors.extend(f"layer {layer_id}: {error}" for error in layer_errors)
        warnings.extend(f"layer {layer_id}: {warning}" for warning in layer_warnings)
        layers.append({"layer_id": layer_id, "count": count, "expected_count": expected, "content_hash": layer_hash(snapshot_id, layer_id), "complete": not layer_errors, "errors": layer_errors, "warnings": layer_warnings})
    return {"ok": not errors, "snapshot_id": snapshot_id, "layers": layers, "errors": errors, "warnings": warnings}


__all__ = ["validate_snapshot"]
