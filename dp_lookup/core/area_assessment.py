"""Deterministic parcel-area assessment with explicit source separation."""

from __future__ import annotations

import math
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from shapely.geometry import MultiPolygon, Polygon

from dp_lookup.core.geometry import mercator_to_wgs84, wgs84_to_utm43n
from dp_lookup.core.models import AreaAssessment, AreaQualityFlag, ReliabilityStatus
from dp_lookup.core.topology import arcgis_rings_to_geometry

RECORDED_AREA_SOURCE = "MCGM cadastral parcel record"
GEOMETRY_SOURCE = "MCGM cadastral parcel boundary"
CALCULATION_METHOD = "WGS 84 / UTM zone 43N (EPSG:32643) polygon area"
AREA_DIFFERENCE_THRESHOLDS = (2, 5, 10)
UNUSUALLY_SMALL_AREA_SQM = 1.0


def _positive_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _recorded_area(attrs: Mapping[str, Any]) -> Optional[float]:
    for key in ("AREA_APP_SQ_MTRS", "Area_App_Sq_Mtrs", "area_app_sq_mtrs"):
        value = _positive_number(attrs.get(key))
        if value is not None:
            return value
    return None


def _raw_geometry_invalid(rings: Sequence[Sequence[Sequence[float]]]) -> bool:
    if not rings:
        return True
    for ring in rings:
        try:
            points = [(float(point[0]), float(point[1])) for point in ring if len(point) >= 2]
            if len(points) < 4:
                return True
            polygon = Polygon(points)
        except (IndexError, TypeError, ValueError):
            return True
        if polygon.is_empty or polygon.area <= 0 or not polygon.is_valid:
            return True
    return False


def _utm_rings(rings: Sequence[Sequence[Sequence[float]]]) -> List[List[List[float]]]:
    projected: List[List[List[float]]] = []
    for ring in rings:
        projected_ring = []
        for point in ring:
            lon, lat = mercator_to_wgs84(float(point[0]), float(point[1]), precision=10)
            easting, northing = wgs84_to_utm43n(lon, lat, precision=None)
            projected_ring.append([easting, northing])
        projected.append(projected_ring)
    return projected


def calculated_boundary_area_sqm(rings: Sequence[Sequence[Sequence[float]]]) -> Optional[float]:
    """Calculate ground area without treating raw Web Mercator square metres as ground area."""
    try:
        geometry = arcgis_rings_to_geometry(_utm_rings(rings))
    except (IndexError, OverflowError, TypeError, ValueError):
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    area = float(geometry.area)
    return area if math.isfinite(area) and area > 0 else None


def web_mercator_ground_area_scale(
    rings: Sequence[Sequence[Sequence[float]]],
    web_mercator_area_sqm: Optional[float] = None,
) -> Optional[float]:
    """Return the factor that converts local EPSG:3857 square units to UTM ground square metres."""
    try:
        source_geometry = arcgis_rings_to_geometry(rings)
        longitude, _latitude = mercator_to_wgs84(
            float(source_geometry.centroid.x),
            float(source_geometry.centroid.y),
            precision=10,
        )
    except (IndexError, TypeError, ValueError):
        return None
    # UTM zone 43N is the correct metric projection for Mumbai and spans
    # longitudes 72E-78E. Synthetic/non-Mumbai geometry keeps scale 1.0 at the
    # caller rather than being misleadingly projected far outside the zone.
    if source_geometry.is_empty or not 72.0 <= longitude <= 78.0:
        return None
    calculated = calculated_boundary_area_sqm(rings)
    if calculated is None:
        return None
    raw_area = web_mercator_area_sqm
    if raw_area is None:
        raw_area = float(source_geometry.area)
    if not math.isfinite(raw_area) or raw_area <= 0:
        return None
    return calculated / raw_area


def _source_objectids(attrs: Mapping[str, Any]) -> Tuple[int, ...]:
    raw = attrs.get("SOURCE_OBJECTIDS")
    values: Sequence[Any]
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        values = (attrs.get("OBJECTID"),)
    result = []
    for value in values:
        try:
            if value is not None:
                result.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(set(result)))


def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _flag(code: str, severity: str, message: str) -> AreaQualityFlag:
    return AreaQualityFlag(code=code, severity=severity, message=message)


def assess_plot_area(
    attrs: Mapping[str, Any],
    rings: Sequence[Sequence[Sequence[float]]],
    *,
    requested_village: Optional[str] = None,
    requested_cts_no: Optional[str] = None,
) -> AreaAssessment:
    """Build one area decision from preserved source attributes and rings."""
    flags: List[AreaQualityFlag] = []
    recorded = _recorded_area(attrs)
    raw_invalid = _raw_geometry_invalid(rings)
    try:
        geometry = arcgis_rings_to_geometry(rings)
    except (IndexError, TypeError, ValueError):
        geometry = Polygon()
    calculated = calculated_boundary_area_sqm(rings)
    calculation_method = CALCULATION_METHOD

    if raw_invalid:
        flags.append(
            _flag(
                "source_geometry_invalid",
                "warning",
                "The source boundary required topology repair for analysis; archived coordinates remain unchanged.",
            )
        )
        if calculated is not None:
            calculation_method += "; topology repaired for analysis only"
    if calculated is None:
        flags.append(
            _flag(
                "boundary_area_unavailable",
                "critical",
                "A usable calculated boundary area could not be produced from the source coordinates.",
            )
        )
    elif calculated < UNUSUALLY_SMALL_AREA_SQM:
        flags.append(
            _flag(
                "unusually_small_geometry",
                "warning",
                f"The calculated boundary area is below {UNUSUALLY_SMALL_AREA_SQM:g} m².",
            )
        )
    if isinstance(geometry, MultiPolygon) and len(geometry.geoms) > 1:
        flags.append(
            _flag(
                "fragmented_boundary",
                "warning",
                "The parcel boundary contains multiple disconnected polygon parts.",
            )
        )

    conflict_values = attrs.get("_DP_AREA_CONFLICT_VALUES")
    if isinstance(conflict_values, (list, tuple)) and len(conflict_values) > 1:
        flags.append(
            _flag(
                "conflicting_recorded_areas",
                "critical",
                "Multiple source records for this village/CTS identity contain different recorded areas.",
            )
        )
        recorded = None
    if attrs.get("_DP_RECORDED_AREA_MISSING_PARTS"):
        flags.append(
            _flag(
                "partial_recorded_area_evidence",
                "warning",
                "Some source records for this village/CTS identity do not contain a recorded area.",
            )
        )
    if attrs.get("_DP_DUPLICATE_GEOMETRY_COUNT"):
        flags.append(
            _flag(
                "duplicate_geometry",
                "critical",
                "Duplicate source geometry exists for this village/CTS identity.",
            )
        )
    if attrs.get("_DP_UNMERGED_SOURCE_RECORDS"):
        flags.append(
            _flag(
                "multiple_live_source_records",
                "warning",
                "The live service returned multiple parcel records; the historical first-match geometry was retained.",
            )
        )
    if attrs.get("_DP_IDENTITY_AMBIGUOUS"):
        flags.append(
            _flag(
                "ambiguous_identity",
                "critical",
                "The source response did not uniquely match the requested village and CTS identity.",
            )
        )
    returned_village = str(attrs.get("VILLAGE") or "").strip().casefold()
    returned_cts = str(attrs.get("CTS_CS_NO") or "").strip().casefold()
    if (
        (requested_village and returned_village and returned_village != requested_village.strip().casefold())
        or (requested_cts_no and returned_cts and returned_cts != requested_cts_no.strip().casefold())
    ) and not any(flag.code == "ambiguous_identity" for flag in flags):
        flags.append(
            _flag(
                "ambiguous_identity",
                "critical",
                "The returned parcel identity differs from the requested village or CTS number.",
            )
        )
    if not returned_village or not returned_cts:
        flags.append(
            _flag(
                "incomplete_identity",
                "critical",
                "The source parcel is missing its village or CTS identity.",
            )
        )
    if attrs.get("_DP_SNAPSHOT_STALE"):
        flags.append(
            _flag(
                "stale_source_snapshot",
                "warning",
                "The local source snapshot is older than the configured freshness limit.",
            )
        )

    difference_sqm: Optional[float] = None
    difference_percent: Optional[float] = None
    thresholds_exceeded: Tuple[int, ...] = ()
    if recorded is not None and calculated is not None:
        difference_sqm = calculated - recorded
        difference_percent = abs(difference_sqm) / recorded * 100.0
        thresholds_exceeded = tuple(
            threshold for threshold in AREA_DIFFERENCE_THRESHOLDS if difference_percent > threshold
        )
        if thresholds_exceeded:
            highest = thresholds_exceeded[-1]
            severity = "critical" if highest == 10 else ("warning" if highest == 5 else "review")
            flags.append(
                _flag(
                    f"area_difference_over_{highest}_percent",
                    severity,
                    f"Recorded plot area and calculated boundary area differ by {difference_percent:.2f}%.",
                )
            )
    elif recorded is None:
        flags.append(
            _flag(
                "recorded_area_unavailable",
                "warning",
                "The MCGM cadastral parcel record does not provide one consistent recorded plot area.",
            )
        )

    selected = recorded if recorded is not None else calculated
    selected_basis = (
        "recorded_plot_area"
        if recorded is not None
        else ("calculated_boundary_area" if calculated is not None else "unavailable")
    )
    if flags:
        reliability = ReliabilityStatus.QUALIFIED_WITH_WARNINGS
    elif attrs.get("_DP_PARCEL_SOURCE") == "local_snapshot":
        reliability = ReliabilityStatus.VERIFIED_SOURCE
    else:
        reliability = ReliabilityStatus.SCREENING

    source_objectids = _source_objectids(attrs)
    part_count_raw = attrs.get("FEATURE_PART_COUNT")
    try:
        feature_part_count = (
            max(1, int(part_count_raw)) if part_count_raw is not None else max(1, len(source_objectids))
        )
    except (TypeError, ValueError):
        feature_part_count = max(1, len(source_objectids))

    return AreaAssessment(
        recorded_area_sqm=round(recorded, 2) if recorded is not None else None,
        calculated_boundary_area_sqm=round(calculated, 2) if calculated is not None else None,
        selected_area_sqm=round(selected, 2) if selected is not None else None,
        selected_area_basis=selected_basis,
        calculation_method=calculation_method,
        recorded_area_source=RECORDED_AREA_SOURCE,
        geometry_source=GEOMETRY_SOURCE,
        difference_sqm=round(difference_sqm, 2) if difference_sqm is not None else None,
        difference_percent=round(difference_percent, 3) if difference_percent is not None else None,
        thresholds_exceeded=thresholds_exceeded,
        reliability_status=reliability,
        flags=tuple(flags),
        source_objectids=source_objectids,
        feature_part_count=feature_part_count,
        source_snapshot_id=_optional_int(attrs.get("_DP_SNAPSHOT_ID")),
        source_snapshot_date=(
            str(attrs["_DP_SNAPSHOT_FINALIZED_AT_ISO"])
            if attrs.get("_DP_SNAPSHOT_FINALIZED_AT_ISO") is not None
            else None
        ),
    )


__all__ = [
    "AREA_DIFFERENCE_THRESHOLDS",
    "CALCULATION_METHOD",
    "GEOMETRY_SOURCE",
    "RECORDED_AREA_SOURCE",
    "AreaAssessment",
    "assess_plot_area",
    "calculated_boundary_area_sqm",
    "web_mercator_ground_area_scale",
]
