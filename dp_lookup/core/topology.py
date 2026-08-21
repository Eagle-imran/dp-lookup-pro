"""Topology-aware conversion of ArcGIS polygon rings into Shapely geometry."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree


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
    polygons = [candidate[0] for candidate in candidates]
    # A single CRZ feature can contain hundreds of independent rings. Testing
    # every ring against every larger ring made local evidence queries
    # quadratic. The spatial tree keeps the same containment-depth policy but
    # limits each test to geometrically plausible containers.
    tree = STRtree(polygons)
    containers_by_ring: List[List[int]] = []
    depths: List[int] = []
    for index, polygon in enumerate(polygons):
        marker = polygon.representative_point()
        containers = [
            int(candidate_index)
            for candidate_index in tree.query(marker, predicate="within")
            if int(candidate_index) != index and polygons[int(candidate_index)].area > polygon.area
        ]
        containers_by_ring.append(containers)
        depths.append(len(containers))

    holes_by_shell = {index: [] for index, depth in enumerate(depths) if depth % 2 == 0}
    for index, depth in enumerate(depths):
        if depth % 2 == 0:
            continue
        direct_shells = [
            container_index
            for container_index in containers_by_ring[index]
            if depths[container_index] == depth - 1 and depths[container_index] % 2 == 0
        ]
        if direct_shells:
            parent = min(direct_shells, key=lambda candidate_index: polygons[candidate_index].area)
            holes_by_shell[parent].append(candidates[index][1])

    shells = []
    for index, (_polygon, shell_points) in enumerate(candidates):
        if depths[index] % 2:
            continue
        part = Polygon(shell_points, holes_by_shell[index])
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
