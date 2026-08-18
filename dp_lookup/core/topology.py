"""Topology-aware conversion of ArcGIS polygon rings into Shapely geometry."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry


def _clean_ring(ring: Iterable[Sequence[float]]) -> List[Tuple[float, float]]:
    points = [(float(point[0]), float(point[1])) for point in ring if len(point) >= 2]
    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


def arcgis_rings_to_geometry(rings: Sequence[Sequence[Sequence[float]]]) -> BaseGeometry:
    """Build a Polygon/MultiPolygon without assuming that ``rings[0]`` is all of it.

    ArcGIS normally communicates shell/hole semantics through winding order, but
    real services are not perfectly consistent.  Containment depth is therefore
    used instead: even-depth rings are shells and odd-depth rings are holes.
    """
    candidates = []
    for raw_ring in rings:
        points = _clean_ring(raw_ring)
        if len(points) < 4:
            continue
        polygon = Polygon(points)
        if polygon.is_empty or polygon.area <= 0:
            continue
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty:
            continue
        if isinstance(polygon, MultiPolygon):
            candidates.extend((part, list(part.exterior.coords)) for part in polygon.geoms)
        elif isinstance(polygon, Polygon):
            candidates.append((polygon, points))

    if not candidates:
        return Polygon()

    candidates.sort(key=lambda item: item[0].area, reverse=True)
    depths: List[int] = []
    for index, (polygon, _) in enumerate(candidates):
        marker = polygon.representative_point()
        depths.append(sum(1 for container, _ in candidates[:index] if container.contains(marker)))

    shells = []
    for index, (polygon, shell_points) in enumerate(candidates):
        if depths[index] % 2:
            continue
        holes = []
        for hole_index, (hole_polygon, hole_points) in enumerate(candidates):
            if depths[hole_index] != depths[index] + 1:
                continue
            if polygon.contains(hole_polygon.representative_point()):
                holes.append(hole_points)
        part = Polygon(shell_points, holes)
        if not part.is_valid:
            part = part.buffer(0)
        if isinstance(part, MultiPolygon):
            shells.extend(part.geoms)
        elif not part.is_empty:
            shells.append(part)

    if not shells:
        return Polygon()
    if len(shells) == 1:
        return shells[0]
    return MultiPolygon(shells)


def rings_to_geojson_geometry(rings: Sequence[Sequence[Sequence[float]]]) -> dict:
    """Return an RFC 7946-compatible Polygon or MultiPolygon geometry object."""
    geometry = arcgis_rings_to_geometry(rings)
    if geometry.is_empty:
        return {"type": "Polygon", "coordinates": []}
    return mapping(geometry)
