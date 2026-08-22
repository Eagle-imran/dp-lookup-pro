"""Geometry and clipping algorithms used by the DXF renderer."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Polygon  # type: ignore[import-untyped]
from shapely.geometry.base import BaseMultipartGeometry  # type: ignore[import-untyped]

METRES_PER_DEG_LAT = 111132.0
METRES_PER_DEG_LON_EQUATOR = 111319.5
Point = Tuple[float, float]
Ring = Sequence[Sequence[float]]


def polygon_signed_area(ring: Ring) -> float:
    """Shoelace formula. Positive means counter-clockwise winding."""
    n = len(ring)
    return sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n)) / 2.0


def offset_polygon_inward(ring: Ring, distance: float) -> List[List[Point]]:
    """Return the viable parts of a true parallel inward polygon offset."""
    pts = list(ring)
    if (
        len(pts) > 1
        and math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-9)
        and math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-9)
    ):
        pts = pts[:-1]
    if len(pts) < 3 or distance <= 0:
        return []

    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        shrunk = poly.buffer(-abs(distance), join_style=2)
    except Exception:
        return []
    if shrunk.is_empty:
        return []

    parts = list(shrunk.geoms) if isinstance(shrunk, BaseMultipartGeometry) else [shrunk]
    out: List[List[Point]] = []
    for part in parts:
        exterior = getattr(part, "exterior", None)
        if exterior is None:
            continue
        coords = [(x, y) for x, y in exterior.coords]
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) >= 3 and abs(polygon_signed_area(coords)) >= 1.0:
            out.append(coords)
    return out


def project_rings_to_local_metres(wgs_rings: Sequence[Ring]) -> Dict[str, Any]:
    """Project WGS84 degrees into a local metric frame at the plot centroid."""
    r0 = wgs_rings[0]
    lon0 = sum(p[0] for p in r0) / len(r0)
    lat0 = sum(p[1] for p in r0) / len(r0)
    mpd_lon = METRES_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))
    mpd_lat = METRES_PER_DEG_LAT
    return {
        "lon0": lon0,
        "lat0": lat0,
        "mpd_lon": mpd_lon,
        "mpd_lat": mpd_lat,
        "local_rings": [[((p[0] - lon0) * mpd_lon, (p[1] - lat0) * mpd_lat) for p in ring] for ring in wgs_rings],
    }


def to_local_metres(
    points: Ring,
    lon0: float,
    lat0: float,
    mpd_lon: float,
    mpd_lat: float,
) -> List[Point]:
    """Project a WGS84 path into an existing local metric frame."""
    return [((p[0] - lon0) * mpd_lon, (p[1] - lat0) * mpd_lat) for p in points]


def clip_segment_to_box(
    p1: Sequence[float],
    p2: Sequence[float],
    x_lo: float,
    y_lo: float,
    x_hi: float,
    y_hi: float,
) -> Optional[Tuple[Point, Point]]:
    """Clip a segment to a bounding box with the Liang-Barsky algorithm."""
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - x_lo), (dx, x_hi - x1), (-dy, y1 - y_lo), (dy, y_hi - y1)):
        if p == 0:
            if q < 0:
                return None
        else:
            ratio = q / p
            if p < 0:
                if ratio > t1:
                    return None
                t0 = max(t0, ratio)
            else:
                if ratio < t0:
                    return None
                t1 = min(t1, ratio)
    return ((x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy))


def clip_path_to_window(
    path: Sequence[Point],
    x_lo: float,
    y_lo: float,
    x_hi: float,
    y_hi: float,
) -> List[List[Point]]:
    """Return contiguous runs of a path clipped to the window."""
    runs: List[List[Point]] = []
    run: List[Point] = []
    for index in range(len(path) - 1):
        segment = clip_segment_to_box(path[index], path[index + 1], x_lo, y_lo, x_hi, y_hi)
        if segment is None:
            if run:
                runs.append(run)
                run = []
            continue
        start, end = segment
        if run and abs(run[-1][0] - start[0]) < 1e-9 and abs(run[-1][1] - start[1]) < 1e-9:
            run.append(end)
        else:
            if run:
                runs.append(run)
            run = [start, end]
    if run:
        runs.append(run)
    return runs
