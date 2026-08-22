"""Read-only consistency checks for parcel snapshot databases."""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Dict, List

from dp_lookup.spatial_store.codecs import polygon_validation_error


def integrity_check(connection: sqlite3.Connection, *, rtree_available: bool, snapshot_id: int | None = None) -> Dict[str, Any]:
    errors: List[str] = []
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        errors.append(str(result))
    errors.extend("foreign key: " + repr(tuple(row)) for row in connection.execute("PRAGMA foreign_key_check"))
    if rtree_available:
        if snapshot_id is not None:
            missing = connection.execute(
                """SELECT p.objectid FROM parcels p LEFT JOIN parcel_bbox_map m ON m.snapshot_id=p.snapshot_id AND m.objectid=p.objectid
                   WHERE p.snapshot_id=? AND p.min_x IS NOT NULL AND m.bbox_id IS NULL""", (snapshot_id,)
            )
            errors.extend(f"missing bbox index for objectid {row[0]}" for row in missing)
        try:
            rtree_result = connection.execute("SELECT rtreecheck('parcel_bbox')").fetchone()[0]
            if rtree_result != "ok":
                errors.append("rtreecheck: " + str(rtree_result))
        except sqlite3.DatabaseError as exc:
            errors.append("rtreecheck failed: " + str(exc))
    return {"ok": not errors, "errors": errors}


def validate_snapshot(connection: sqlite3.Connection, snapshot_id: int, snapshot_row: Any, *, rtree_available: bool) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    count = int(connection.execute("SELECT COUNT(*) FROM parcels WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0])
    expected = snapshot_row["expected_count"]
    if expected is not None and count != expected:
        errors.append(f"expected {expected} parcels, received {count}")
    inventory_count = int(connection.execute("SELECT COUNT(*) FROM snapshot_inventory WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0])
    if inventory_count:
        missing = connection.execute("SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? EXCEPT SELECT objectid FROM parcels WHERE snapshot_id=? ORDER BY objectid LIMIT 20", (snapshot_id, snapshot_id)).fetchall()
        extra = connection.execute("SELECT objectid FROM parcels WHERE snapshot_id=? EXCEPT SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? ORDER BY objectid LIMIT 20", (snapshot_id, snapshot_id)).fetchall()
        if expected is not None and inventory_count != expected:
            errors.append(f"persisted inventory contains {inventory_count} IDs; expected {expected}")
        if missing:
            errors.append("inventory IDs missing from parcels: " + ", ".join(str(row[0]) for row in missing))
        if extra:
            errors.append("parcel IDs absent from inventory: " + ", ".join(str(row[0]) for row in extra))
    for issue in connection.execute("SELECT severity,message FROM ingestion_issues WHERE snapshot_id=?", (snapshot_id,)):
        (errors if issue[0] == "error" else warnings).append(issue[1])
    for parcel in connection.execute("SELECT objectid,raw_attrs_json,raw_feature_json,geometry_json,geom_format,min_x,max_x,min_y,max_y FROM parcels WHERE snapshot_id=?", (snapshot_id,)):
        try:
            json.loads(parcel["raw_attrs_json"])
            json.loads(parcel["raw_feature_json"])
            if parcel["geom_format"] == "rings_json" and parcel["geometry_json"] is not None:
                geometry_error = polygon_validation_error(json.loads(parcel["geometry_json"]))
                if geometry_error:
                    errors.append(f"objectid {parcel['objectid']}: {geometry_error}")
            elif parcel["geom_format"] == "rings_json":
                errors.append(f"objectid {parcel['objectid']}: polygon geometry is missing")
        except (TypeError, ValueError) as exc:
            errors.append(f"objectid {parcel['objectid']}: invalid JSON ({exc})")
        if any(value is not None and not math.isfinite(float(value)) for value in (parcel["min_x"], parcel["max_x"], parcel["min_y"], parcel["max_y"])):
            errors.append(f"objectid {parcel['objectid']}: invalid bbox")
    integrity = integrity_check(connection, rtree_available=rtree_available, snapshot_id=snapshot_id)
    if not integrity["ok"]:
        errors.extend(integrity["errors"])
    return {"ok": not errors, "snapshot_id": snapshot_id, "count": count, "expected_count": expected, "errors": errors, "warnings": warnings}


__all__ = ["integrity_check", "validate_snapshot"]
