"""Pure deterministic geometry service for experimental plot assembly."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, Iterable, List, Sequence, Set, Tuple, cast

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from dp_lookup.core.geometry import mercator_to_wgs84, wgs84_to_utm43n
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.experimental.assemblies.models import (
    ArcGISRings,
    AssemblyAnalysis,
    AssemblySuitabilityStatus,
    AssemblyWarning,
    PairwiseParcelRelation,
    ParcelAssemblyInput,
    ParcelRelationKind,
)

ANALYSIS_CRS = "WGS 84 / UTM zone 43N (EPSG:32643)"
_AREA_EPSILON_SQM = 1e-6
_LENGTH_EPSILON_M = 1e-6


def _project_rings_to_utm43n(rings: ArcGISRings) -> List[List[List[float]]]:
    """Project immutable Web Mercator source coordinates to local ground metres."""
    projected: List[List[List[float]]] = []
    for ring in rings:
        projected_ring: List[List[float]] = []
        for x, y in ring:
            longitude, latitude = mercator_to_wgs84(x, y, precision=10)
            easting, northing = wgs84_to_utm43n(longitude, latitude, precision=None)
            projected_ring.append([easting, northing])
        projected.append(projected_ring)
    return projected


def _geometry_for(parcel: ParcelAssemblyInput) -> BaseGeometry:
    # ParcelAssemblyInput normalises this field to ArcGISRings in __post_init__.
    raw_rings = cast(ArcGISRings, parcel.raw_arcgis_rings)
    geometry = arcgis_rings_to_geometry(_project_rings_to_utm43n(raw_rings))
    if geometry.is_empty or geometry.area <= _AREA_EPSILON_SQM:
        raise ValueError(f"{parcel.identity_key} has no usable source boundary for assembly analysis.")
    return geometry


def _raw_geometry_requires_repair(parcel: ParcelAssemblyInput) -> bool:
    """Detect source-ring invalidity without ever replacing archived coordinates."""
    raw_rings = cast(ArcGISRings, parcel.raw_arcgis_rings)
    for ring in raw_rings:
        candidate = Polygon(ring)
        if candidate.is_empty or candidate.area <= 0 or not candidate.is_valid:
            return True
    return False


def _identity_duplicates(parcels: Sequence[ParcelAssemblyInput]) -> Tuple[str, ...]:
    seen = set()
    duplicates = []
    for parcel in parcels:
        key = (parcel.village.casefold(), parcel.cts_no.casefold())
        if key in seen:
            duplicates.append(parcel.identity_key)
        seen.add(key)
    return tuple(duplicates)


def _objectid_duplicates(parcels: Iterable[ParcelAssemblyInput]) -> Tuple[int, ...]:
    seen = set()
    duplicates = set()
    for parcel in parcels:
        for objectid in parcel.objectids:
            if objectid in seen:
                duplicates.add(objectid)
            seen.add(objectid)
    return tuple(sorted(duplicates))


def _relation(
    first: ParcelAssemblyInput,
    first_geometry: BaseGeometry,
    second: ParcelAssemblyInput,
    second_geometry: BaseGeometry,
    gap_tolerance_m: float,
) -> PairwiseParcelRelation:
    overlap_area = max(0.0, float(first_geometry.intersection(second_geometry).area))
    shared_boundary = max(0.0, float(first_geometry.boundary.intersection(second_geometry.boundary).length))
    gap_distance = max(0.0, float(first_geometry.distance(second_geometry)))
    within_tolerance = 0.0 < gap_distance <= gap_tolerance_m

    if overlap_area > _AREA_EPSILON_SQM:
        kind = ParcelRelationKind.OVERLAP
    elif shared_boundary > _LENGTH_EPSILON_M:
        kind = ParcelRelationKind.SHARED_BOUNDARY
    elif gap_distance <= _LENGTH_EPSILON_M:
        kind = ParcelRelationKind.POINT_CONTACT
    elif within_tolerance:
        kind = ParcelRelationKind.TOLERANCE_GAP
    else:
        kind = ParcelRelationKind.DISCONNECTED
    return PairwiseParcelRelation(
        first_identity=first.identity_key,
        second_identity=second.identity_key,
        relation=kind,
        shared_boundary_length_m=round(shared_boundary, 3),
        gap_distance_m=round(gap_distance, 3),
        overlap_area_sqm=round(overlap_area, 3),
        within_gap_tolerance=within_tolerance,
    )


def _graph_is_connected(count: int, relations: Sequence[PairwiseParcelRelation], *, tolerance: bool) -> bool:
    """Check graph connectivity without confusing point contact with usable adjacency."""
    if count < 2:
        return False
    linked: Dict[int, Set[int]] = {index: set() for index in range(count)}
    identity_indexes: Dict[str, int] = {}
    for index, identity in enumerate(
        sorted({relation.first_identity for relation in relations} | {relation.second_identity for relation in relations})
    ):
        identity_indexes[identity] = index
    for relation in relations:
        connects = relation.relation in {ParcelRelationKind.SHARED_BOUNDARY, ParcelRelationKind.OVERLAP}
        if tolerance and relation.relation is ParcelRelationKind.TOLERANCE_GAP:
            connects = True
        if connects:
            left = identity_indexes[relation.first_identity]
            right = identity_indexes[relation.second_identity]
            linked[left].add(right)
            linked[right].add(left)
    visited = {0}
    frontier = [0]
    while frontier:
        current = frontier.pop()
        for neighbour in linked[current] - visited:
            visited.add(neighbour)
            frontier.append(neighbour)
    return len(visited) == count


def _status_and_warnings(
    *,
    strictly_connected: bool,
    connected_with_tolerance: bool,
    relations: Sequence[PairwiseParcelRelation],
    missing_recorded_area: bool,
    repaired_source_identities: Sequence[str],
) -> Tuple[AssemblySuitabilityStatus, Tuple[AssemblyWarning, ...]]:
    warnings = [
        AssemblyWarning(
            code="experimental_screening_only",
            severity="warning",
            message=(
                "This is deterministic geometry screening only. It does not establish ownership, access, "
                "title, municipal approval, or legal amalgamation."
            ),
        )
    ]
    has_overlap = any(relation.relation is ParcelRelationKind.OVERLAP for relation in relations)
    has_tolerance_gap = any(relation.relation is ParcelRelationKind.TOLERANCE_GAP for relation in relations)
    if missing_recorded_area:
        warnings.append(
            AssemblyWarning(
                code="recorded_area_incomplete",
                severity="warning",
                message="One or more selected CTS identities lack a recorded parcel area; no complete gross recorded area is shown.",
            )
        )
    if repaired_source_identities:
        identities = ", ".join(repaired_source_identities)
        warnings.append(
            AssemblyWarning(
                code="source_geometry_repaired_for_analysis",
                severity="warning",
                message=(
                    f"Source geometry for {identities} required topology repair for analysis only; "
                    "the archived ArcGIS coordinates remain unchanged."
                ),
            )
        )
    if has_overlap:
        warnings.append(
            AssemblyWarning(
                code="source_boundary_overlap",
                severity="critical",
                message="Selected source boundaries overlap. Reconcile cadastral evidence before treating this as an assembly.",
            )
        )
    if has_tolerance_gap:
        warnings.append(
            AssemblyWarning(
                code="tolerance_gap_requires_review",
                severity="warning",
                message="Selected boundaries connect only within the configured gap tolerance; verify them against certified survey evidence.",
            )
        )
    if not connected_with_tolerance:
        warnings.append(
            AssemblyWarning(
                code="non_contiguous_selection",
                severity="critical",
                message="Selected plots do not form one connected site, even within the configured tolerance.",
            )
        )

    if has_overlap:
        status = AssemblySuitabilityStatus.REVIEW_OVERLAPS
    elif not connected_with_tolerance:
        status = AssemblySuitabilityStatus.NOT_CONTIGUOUS
    elif repaired_source_identities:
        status = AssemblySuitabilityStatus.REVIEW_SOURCE_GEOMETRY
    elif strictly_connected:
        status = AssemblySuitabilityStatus.GEOMETRY_SCREENING_READY
    elif connected_with_tolerance:
        status = AssemblySuitabilityStatus.REVIEW_TOLERANCE_GAPS
    else:
        status = AssemblySuitabilityStatus.NOT_CONTIGUOUS
    return status, tuple(warnings)


def analyze_plot_assembly(
    parcels: Sequence[ParcelAssemblyInput],
    *,
    gap_tolerance_m: float = 0.2,
) -> AssemblyAnalysis:
    """Analyse a selection of two or more CTS inputs without altering source data.

    All measurements use UTM 43N ground metres, not raw Web Mercator square
    units.  The caller owns planning overlays and authority evidence: this
    isolated extension only determines whether source parcel geometry could
    form one feasibility-study site.
    """
    selected = tuple(parcels)
    if len(selected) < 2:
        raise ValueError("Plot assembly analysis requires at least two selected CTS identities.")
    if not math.isfinite(gap_tolerance_m) or gap_tolerance_m < 0:
        raise ValueError("Gap tolerance must be a finite non-negative number of metres.")
    duplicate_identities = _identity_duplicates(selected)
    if duplicate_identities:
        raise ValueError(f"Each CTS identity may appear only once: {', '.join(duplicate_identities)}")
    duplicate_objectids = _objectid_duplicates(selected)
    if duplicate_objectids:
        values = ", ".join(str(value) for value in duplicate_objectids)
        raise ValueError(f"Source ObjectIDs may not be selected more than once: {values}")

    geometries = tuple(_geometry_for(parcel) for parcel in selected)
    repaired_sources = tuple(parcel.identity_key for parcel in selected if _raw_geometry_requires_repair(parcel))
    relations = tuple(
        _relation(selected[first_index], geometries[first_index], selected[second_index], geometries[second_index], gap_tolerance_m)
        for first_index, second_index in combinations(range(len(selected)), 2)
    )
    combined = unary_union(geometries)
    if combined.is_empty:
        raise ValueError("Selected source boundaries could not be unioned for assembly analysis.")
    individual_area = sum(float(geometry.area) for geometry in geometries)
    combined_area = float(combined.area)
    external_perimeter = float(combined.length)
    # This is deliberately not inferred from perimeter reduction. That shortcut
    # is valid only for clean edge-adjacent polygons and would wrongly treat an
    # overlap as a removed internal edge. The relation classifier has already
    # established the actual source edges shared by distinct selected parcels.
    removed_internal = sum(
        relation.shared_boundary_length_m
        for relation in relations
        if relation.relation is ParcelRelationKind.SHARED_BOUNDARY
    )
    overlap_or_duplicate = max(0.0, individual_area - combined_area)
    strictly_connected = _graph_is_connected(len(selected), relations, tolerance=False)
    connected_with_tolerance = _graph_is_connected(len(selected), relations, tolerance=True)

    known_recorded = sum(parcel.recorded_area_sqm or 0.0 for parcel in selected)
    recorded_complete = all(parcel.recorded_area_sqm is not None for parcel in selected)
    status, warnings = _status_and_warnings(
        strictly_connected=strictly_connected,
        connected_with_tolerance=connected_with_tolerance,
        relations=relations,
        missing_recorded_area=not recorded_complete,
        repaired_source_identities=repaired_sources,
    )
    return AssemblyAnalysis(
        selected_parcels=selected,
        analysis_crs=ANALYSIS_CRS,
        gap_tolerance_m=gap_tolerance_m,
        gross_recorded_area_sqm=round(known_recorded, 2) if recorded_complete else None,
        known_recorded_area_sqm=round(known_recorded, 2),
        recorded_area_complete=recorded_complete,
        calculated_input_boundary_area_sqm=round(individual_area, 2),
        calculated_combined_boundary_area_sqm=round(combined_area, 2),
        external_perimeter_m=round(external_perimeter, 3),
        removed_internal_boundary_length_m=round(removed_internal, 3),
        overlap_or_duplicate_area_sqm=round(overlap_or_duplicate, 2),
        is_strictly_connected=strictly_connected,
        is_connected_within_tolerance=connected_with_tolerance,
        pairwise_relations=relations,
        suitability_status=status,
        warnings=warnings,
        combined_boundary_wkt=str(combined.wkt),
    )
