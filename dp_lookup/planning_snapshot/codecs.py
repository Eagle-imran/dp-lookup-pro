"""Lossless JSON and bounding-box codecs for planning feature rows."""

from __future__ import annotations

import json
import math
from typing import Any, List, Mapping, Optional, Tuple

from dp_lookup.planning_snapshot.models import canonical_json


def json_value(value: Any, field: str) -> str:
    if isinstance(value, str):
        try:
            json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is not valid JSON") from exc
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as JSON") from exc


def canonical_value(value: Any, field: str) -> str:
    try:
        return canonical_json(value).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as canonical JSON") from exc


def bbox(geometry: Any) -> Optional[Tuple[float, float, float, float]]:
    if geometry is None or isinstance(geometry, (str, bytes)):
        return None
    if isinstance(geometry, Mapping):
        if "x" in geometry and "y" in geometry:
            geometry = [[geometry["x"], geometry["y"]]]
        elif "point" in geometry:
            point = geometry["point"]
            geometry = [[point["x"], point["y"]]] if isinstance(point, Mapping) and "x" in point and "y" in point else point
        if isinstance(geometry, Mapping) and "rings" in geometry:
            geometry = geometry["rings"]
        elif isinstance(geometry, Mapping) and "coordinates" in geometry:
            geometry = geometry["coordinates"]
        elif isinstance(geometry, Mapping) and "paths" in geometry:
            geometry = geometry["paths"]
        elif isinstance(geometry, Mapping) and "points" in geometry:
            geometry = geometry["points"]
        elif isinstance(geometry, Mapping):
            return None
    points: List[Tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and not isinstance(value[0], (list, tuple, Mapping)):
                try:
                    x, y = float(value[0]), float(value[1])
                except (TypeError, ValueError, OverflowError):
                    return
                if math.isfinite(x) and math.isfinite(y):
                    points.append((x, y))
                return
            for child in value:
                walk(child)

    walk(geometry)
    if not points:
        return None
    xs, ys = zip(*points, strict=False)
    return min(xs), max(xs), min(ys), max(ys)


__all__ = ["bbox", "canonical_value", "json_value"]
