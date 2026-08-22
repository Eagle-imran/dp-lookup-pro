"""Input codecs and geometry validation for parcel snapshot rows."""

from __future__ import annotations

import json
import math
from typing import Any, List, Mapping, Optional, Tuple, cast

from dp_lookup.core.topology import arcgis_rings_to_geometry


def json_value(value: Any, *, field: str) -> str:
    if isinstance(value, str):
        try:
            json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is not valid JSON") from exc
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as JSON") from exc


def canonical_json_value(value: Any, *, field: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as canonical JSON") from exc


def number(value: Any, *, field: str) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def identity_text(value: Any, *, uppercase: bool = False) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.upper() if uppercase else normalized


def polygon_validation_error(geometry: Any) -> Optional[str]:
    """Return a reason when an ArcGIS polygon cannot be used safely."""
    rings = geometry.get("rings", geometry.get("coordinates")) if isinstance(geometry, Mapping) else geometry
    if not isinstance(rings, list) or not rings:
        return "polygon has no rings"
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            return "polygon contains a ring with fewer than four coordinates"
        distinct: set[Tuple[float, float]] = set()
        for point in ring:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return "polygon contains an invalid coordinate"
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError, OverflowError):
                return "polygon contains a non-numeric coordinate"
            if not math.isfinite(x) or not math.isfinite(y):
                return "polygon contains a non-finite coordinate"
            distinct.add((x, y))
        if len(distinct) < 3:
            return "polygon ring has fewer than three distinct coordinates"
    try:
        normalized = arcgis_rings_to_geometry(rings)
    except Exception as exc:
        return f"polygon topology could not be interpreted ({exc})"
    if normalized.is_empty or normalized.area <= 0:
        return "polygon is empty or has no area"
    if not normalized.is_valid:
        return "polygon remains topologically invalid after normalization"
    return None


def bbox_from_geometry(geometry: Any) -> Optional[Tuple[float, float, float, float]]:
    if geometry is None:
        return None
    if isinstance(geometry, Mapping):
        if "rings" in geometry:
            geometry = geometry["rings"]
        elif "coordinates" in geometry:
            geometry = geometry["coordinates"]
        elif "wkb" in geometry:
            return None
    points: List[Tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and not isinstance(value[0], (list, tuple, Mapping)):
                try:
                    x, y = float(value[0]), float(value[1])
                except (TypeError, ValueError):
                    return
                if math.isfinite(x) and math.isfinite(y):
                    points.append((x, y))
                return
            for child in value:
                walk(child)

    walk(geometry)
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), max(xs), min(ys), max(ys)


def record_geometry(record: Mapping[str, Any]) -> Tuple[Any, str, Optional[Tuple[float, float, float, float]]]:
    geometry = record.get("geometry", record.get("rings", record.get("geometry_rings", record.get("geometry_json"))))
    geom_format = record.get("geom_format")
    if isinstance(geometry, Mapping) and "wkb" in geometry:
        geometry, geom_format = geometry["wkb"], geom_format or "wkb"
    if geom_format is None:
        geom_format = "rings_json" if geometry is not None else "none"
    if geom_format not in {"rings_json", "wkb", "none"}:
        raise ValueError(f"unsupported geom_format: {geom_format}")
    bbox = record.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError("bbox must contain min_x, max_x, min_y, max_y")
        values = [number(value, field="bbox") for value in bbox]
        if any(value is None for value in values):
            raise ValueError("bbox values cannot be null")
        bbox = tuple(cast(List[float], values))
    else:
        bbox = bbox_from_geometry(geometry) if geom_format == "rings_json" else None
    if geometry is not None and geom_format != "wkb":
        geometry_value: Any = json_value(geometry, field="geometry")
    elif geometry is None:
        geometry_value = None
    elif isinstance(geometry, bytes):
        geometry_value = geometry
    else:
        geometry_value = str(geometry)
    return geometry_value, geom_format, bbox


__all__ = ["bbox_from_geometry", "canonical_json_value", "identity_text", "json_value", "number", "polygon_validation_error", "record_geometry"]
