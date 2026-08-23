"""Focused read repository for spatial planning features."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, Dict, List, Mapping, Optional

from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.planning_evidence.registry import canonical_layer_id

_RUNTIME_GEOMETRY_KEY = "_dp_runtime_geometry"


def feature_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Decode one archived feature row without losing the raw payload."""
    result = dict(row)
    result["attributes"] = json.loads(result["attributes_json"])
    result["geometry"] = None if result["geometry_json"] is None else json.loads(result["geometry_json"])
    result["raw_feature"] = json.loads(result["raw_feature_json"])
    return result


class PlanningFeatureQuery:
    """Spatial read model independent from snapshot lifecycle mutations."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        rtree_available: bool,
        active_snapshot_id: Callable[[], Optional[int]],
    ) -> None:
        self.connection = connection
        self.rtree_available = rtree_available
        self.active_snapshot_id = active_snapshot_id

    def features_in_bbox(
        self,
        layer_id: int,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
        *,
        snapshot_id: Optional[int],
        include_archive_payload: bool,
    ) -> List[Dict[str, Any]]:
        sid = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if sid is None:
            return []
        canonical_id = canonical_layer_id(layer_id)
        selection = "f.*" if include_archive_payload else "f.object_id,f.attributes_json,f.geometry_json"
        if self.rtree_available:
            rows = self.connection.execute(
                f"SELECT {selection} FROM planning_feature_rtree r "
                "CROSS JOIN planning_feature_rtree_map m "
                "CROSS JOIN planning_features f "
                "WHERE r.id=m.id "
                "AND m.snapshot_id=f.snapshot_id "
                "AND m.canonical_layer_id=f.canonical_layer_id "
                "AND m.object_id=f.object_id "
                "AND m.snapshot_id=? AND m.canonical_layer_id=? "
                "AND r.max_x>=? AND r.min_x<=? AND r.max_y>=? AND r.min_y<=? "
                "ORDER BY f.object_id",
                (sid, canonical_id, min_x, max_x, min_y, max_y),
            )
        else:
            rows = self.connection.execute(
                f"SELECT {selection.replace('f.', '')} FROM planning_features "
                "WHERE snapshot_id=? AND canonical_layer_id=? AND bbox_max_x>=? AND bbox_min_x<=? "
                "AND bbox_max_y>=? AND bbox_min_y<=? ORDER BY object_id",
                (sid, canonical_id, min_x, max_x, min_y, max_y),
            )
        if include_archive_payload:
            return [feature_dict(row) for row in rows]
        return [
            {
                "object_id": int(row["object_id"]),
                "attributes": json.loads(row["attributes_json"]),
                "geometry": None if row["geometry_json"] is None else json.loads(row["geometry_json"]),
            }
            for row in rows
        ]

    def query_layer(self, snapshot_id: int, layer_id: int, parcel_geometry: Any) -> List[Dict[str, Any]]:
        """Return exact intersections after an indexed bounding-box query."""
        bounds = getattr(parcel_geometry, "bounds", None)
        if not bounds or len(bounds) != 4:
            raise ValueError("parcel_geometry must expose shapely bounds")
        candidates = self.features_in_bbox(
            layer_id,
            float(bounds[0]),
            float(bounds[2]),
            float(bounds[1]),
            float(bounds[3]),
            snapshot_id=snapshot_id,
            include_archive_payload=False,
        )
        result: List[Dict[str, Any]] = []
        for candidate in candidates:
            geometry = candidate.get("geometry") or {}
            rings = geometry.get("rings") if isinstance(geometry, Mapping) else None
            if not rings:
                continue
            polygon = arcgis_rings_to_geometry(rings)
            if not polygon.is_empty and parcel_geometry.intersects(polygon):
                # This object is an in-process acceleration only. The exact
                # source rings remain the archived geometry and are still
                # returned unchanged; downstream local policies can reuse the
                # already validated Shapely object instead of decoding very
                # large CRZ/Metro geometries twice during one lookup.
                candidate[_RUNTIME_GEOMETRY_KEY] = polygon
                result.append(candidate)
        return result


__all__ = ["PlanningFeatureQuery", "feature_dict"]
