"""Application adapter for explicitly active authority sources."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.authority.selection import (
    AuthorityResolution,
    normalize_purpose,
    recommend_authority_sources,
    source_type_label,
)
from dp_lookup.core.area_assessment import AREA_DIFFERENCE_THRESHOLDS, calculated_boundary_area_sqm
from dp_lookup.core.geometry import prepare_geometry
from dp_lookup.core.models import AreaAssessment, AreaQualityFlag, ReliabilityStatus


def _value(record: Any, *names: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _active_records(store: Any, village: str, cts_no: str, purpose: str) -> Tuple[Any, ...]:
    """Read only the store's explicit active selection boundary.

    A store implementation may expose either ``active`` or
    ``active_selection``. We intentionally never fall back to ``list`` here:
    recommendations must not silently become operational inputs.
    """
    method = getattr(store, "active", None) or getattr(store, "active_selection", None)
    if not callable(method):
        return ()
    store_purpose = {
        "area_reconciliation": "area",
        "geometry_reconciliation": "geometry",
        "planning": "planning",
    }.get(purpose, purpose)
    attempts = (
        # Legacy stores used the policy names while the SQLite registry uses
        # the compact persisted values. Try the policy spelling first so
        # injected stores retain their existing contract, then the compact
        # spelling for the durable registry.
        {"village": village, "cts_no": cts_no, "purpose": purpose},
        {"village": village, "cts_no": cts_no, "purpose": store_purpose},
        {"village": village, "cts_no": cts_no, "selection_purpose": purpose},
        {"village": village, "cts_no": cts_no, "selection_purpose": store_purpose},
        {"village": village, "cts_no": cts_no},
    )
    result: Any = None
    for kwargs in attempts:
        try:
            result = method(**kwargs)
            break
        except TypeError:
            continue
    if result is None:
        return ()
    if isinstance(result, Mapping) and not any(key in result for key in ("source_type", "status", "record_id", "id")):
        selected = result.get(store_purpose)
        return (selected,) if selected is not None else ()
    if isinstance(result, Mapping) or isinstance(result, (str, bytes)):
        return (result,)
    try:
        return tuple(result)
    except TypeError:
        return (result,)


def _rings(record: Any) -> Optional[List[List[List[float]]]]:
    value = _value(
        record,
        "normalized_epsg3857_rings",
        "geometry",
        "rings",
        "geometry_rings",
        "boundary",
    )
    if isinstance(value, Mapping):
        value = value.get("rings", value.get("coordinates"))
    if not isinstance(value, (list, tuple)):
        return None
    try:
        return [
            [[float(point[0]), float(point[1])] for point in ring] for ring in value if isinstance(ring, (list, tuple))
        ]
    except (IndexError, TypeError, ValueError):
        return None


def _crs(record: Any) -> int:
    if _value(record, "normalized_epsg3857_rings") is not None:
        return 102100
    value = _value(record, "geometry_crs", "crs", "wkid", "spatial_reference", "original_crs", default=102100)
    if isinstance(value, Mapping):
        value = value.get("wkid", value.get("latestWkid", 102100))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 102100


def _to_mercator(rings: List[List[List[float]]], crs: int) -> List[List[List[float]]]:
    if crs not in {4326, 4269}:
        return rings
    # Keep this conversion local and dependency-free. Authority records are
    # allowed to carry WGS84 coordinates while the existing pipeline remains
    # EPSG:102100/Web Mercator internally.
    import math

    radius = 20037508.342789244
    converted: List[List[List[float]]] = []
    for ring in rings:
        converted.append(
            [
                [
                    float(point[0]) * radius / 180.0,
                    math.log(math.tan((90.0 + float(point[1])) * math.pi / 360.0)) / (math.pi / 180.0) * radius / 180.0,
                ]
                for point in ring
            ]
        )
    return converted


def _area(record: Any) -> Optional[float]:
    value = _value(record, "area_sqm", "recorded_area_sqm", "calculated_area_sqm", "area", "plot_area_sqm")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _label(record: Any) -> str:
    value = _value(record, "source_label", "display_name", "document_type")
    if value:
        return str(value)
    source_type = _value(record, "source_type", default="Active authority source")
    return source_type_label(source_type)


def _record_dict(record: Any) -> Dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return dict(value)
    try:
        return dict(vars(record))
    except TypeError:
        return {"value": str(record)}


def _working_assessment(
    baseline: Optional[AreaAssessment],
    calculated: Optional[float],
    selected: Optional[float],
    *,
    area_source: Optional[Any],
    geometry_source: Optional[Any],
    area_applied: bool,
    geometry_applied: bool,
) -> Optional[AreaAssessment]:
    """Recalculate the assessment while keeping MCGM recorded area intact."""
    if baseline is None:
        return None
    difference = None
    difference_percent = None
    thresholds: Tuple[int, ...] = ()
    flags = [flag for flag in baseline.flags if not flag.code.startswith("area_difference_over_")]
    if baseline.recorded_area_sqm is not None and calculated is not None:
        difference = calculated - baseline.recorded_area_sqm
        difference_percent = abs(difference) / baseline.recorded_area_sqm * 100.0
        thresholds = tuple(threshold for threshold in AREA_DIFFERENCE_THRESHOLDS if difference_percent > threshold)
        if thresholds:
            highest = thresholds[-1]
            severity = "critical" if highest == 10 else ("warning" if highest == 5 else "review")
            flags.append(
                AreaQualityFlag(
                    code=f"area_difference_over_{highest}_percent",
                    severity=severity,
                    message=(f"Recorded plot area and calculated boundary area differ by {difference_percent:.2f}%."),
                )
            )
    status = baseline.reliability_status
    if area_applied and geometry_applied and not flags:
        status = ReliabilityStatus.CERTIFIED
    return replace(
        baseline,
        calculated_boundary_area_sqm=round(calculated, 2) if calculated is not None else None,
        selected_area_sqm=round(selected, 2) if selected is not None else None,
        selected_area_basis="authority_area" if area_applied else baseline.selected_area_basis,
        geometry_source=(
            _label(geometry_source) if geometry_applied and geometry_source is not None else baseline.geometry_source
        ),
        difference_sqm=round(difference, 2) if difference is not None else None,
        difference_percent=round(difference_percent, 3) if difference_percent is not None else None,
        thresholds_exceeded=thresholds,
        reliability_status=status,
        flags=tuple(flags),
    )


def _apply(
    parcel: ParcelContext,
    area_resolution: AuthorityResolution,
    geometry_resolution: AuthorityResolution,
    planning_resolution: AuthorityResolution,
) -> ParcelContext:
    baseline_assessment = parcel.area_assessment.to_dict() if parcel.area_assessment is not None else None
    area_record = area_resolution.selected if area_resolution.has_selection and area_resolution.active else None
    geometry_record = (
        geometry_resolution.selected if geometry_resolution.has_selection and geometry_resolution.active else None
    )
    area_source = area_record.record if area_record is not None else None
    geometry_source = geometry_record.record if geometry_record is not None else None
    working_rings = deepcopy(parcel.rings)
    geometry_applied = False
    if geometry_source is not None:
        replacement = _rings(geometry_source)
        if replacement:
            working_rings = _to_mercator(replacement, _crs(geometry_source))
            geometry_applied = True
    working = parcel
    if geometry_applied:
        prepared = prepare_geometry(working_rings)
        working = replace(
            working,
            rings=working_rings,
            wgs_rings=prepared["wgs_rings"],
            latitude=prepared["lat"],
            longitude=prepared["lon"],
            cx=prepared["cx"],
            cy=prepared["cy"],
            mcx=prepared["mcx"],
            mcy=prepared["mcy"],
            xs=prepared["xs"],
            ys=prepared["ys"],
            window_radius=prepared["d"],
        )
    calculated = calculated_boundary_area_sqm(working.rings)
    selected_area = _area(area_source) if area_source is not None else working.area_sqm
    if selected_area is None:
        selected_area = calculated if calculated is not None else working.area_sqm
    if area_source is not None:
        working = replace(working, area_sqm=float(selected_area), area_source=_label(area_source))

    working_assessment = _working_assessment(
        parcel.area_assessment,
        calculated,
        selected_area,
        area_source=area_source,
        geometry_source=geometry_source,
        area_applied=area_source is not None,
        geometry_applied=geometry_applied,
    )
    if working_assessment is not None:
        working = replace(working, area_assessment=working_assessment)
    area_dict = area_resolution.to_dict()
    geometry_dict = geometry_resolution.to_dict()
    planning_dict = planning_resolution.to_dict()
    applied = bool(area_record or geometry_record)
    any_active = bool(area_record or geometry_record or planning_resolution.selected)
    resolution_payload = {
        "policy_version": area_resolution.policy_version,
        "mode": (
            "active"
            if any(
                item.active and item.selected is not None
                for item in (area_resolution, geometry_resolution, planning_resolution)
            )
            else "recommended"
        ),
        "village": parcel.village,
        "cts_no": parcel.cts_no,
        "status": (
            "conflict"
            if any(item.conflict for item in (area_resolution, geometry_resolution, planning_resolution))
            else ("applied" if applied else ("active_evidence" if any_active else "no_active_selection"))
        ),
        "area": area_dict.get("area"),
        "geometry": geometry_dict.get("geometry"),
        "planning": planning_dict.get("planning") or [],
        "active_record_ids": [
            record_id
            for item in (area_dict, geometry_dict, planning_dict)
            for record_id in item.get("active_record_ids", [])
        ],
        "evaluated_record_ids": sorted(
            {
                record_id
                for item in (area_dict, geometry_dict, planning_dict)
                for record_id in item.get("evaluated_record_ids", [])
            }
        ),
        "reasons": [reason for item in (area_dict, geometry_dict, planning_dict) for reason in item.get("reasons", [])],
        "conflicts": [
            conflict for item in (area_dict, geometry_dict, planning_dict) for conflict in item.get("conflicts", [])
        ],
        "baseline_area_assessment": baseline_assessment or {},
        "applied_to_working_result": applied,
        # The baseline/working block is intentionally additive diagnostic data;
        # the standardized fields above are the stable public authority shape.
        "baseline": {
            "area_sqm": parcel.area_sqm,
            "area_source": parcel.area_source,
            "rings": deepcopy(parcel.rings),
            "wgs_rings": deepcopy(parcel.wgs_rings),
            "area_assessment": baseline_assessment,
        },
        "working": {
            "area_sqm": working.area_sqm,
            "area_source": working.area_source,
            "calculated_boundary_area_sqm": calculated,
            "geometry_source": _label(geometry_source)
            if geometry_source is not None
            else "MCGM cadastral parcel boundary",
            "geometry_replaced": geometry_applied,
            "area_replaced": area_source is not None,
        },
    }
    attrs = dict(working.attrs)
    if working_assessment is not None:
        attrs["_DP_AREA_ASSESSMENT"] = working_assessment.to_dict()
    attrs["_DP_AUTHORITY_RESOLUTION"] = resolution_payload
    attrs["_DP_AUTHORITY_ACTIVE"] = any_active
    if area_record is not None:
        attrs["_DP_AUTHORITY_AREA_SOURCE"] = _label(area_source)
    if geometry_source is not None:
        attrs["_DP_AUTHORITY_GEOMETRY_SOURCE"] = _label(geometry_source)
    field_names = {item.name for item in fields(working)}
    if "authority_resolution" in field_names:
        return replace(working, attrs=attrs, authority_resolution=resolution_payload)
    return replace(working, attrs=attrs)


def apply_authority_selection(
    parcel: ParcelContext,
    *,
    area_resolution: Optional[AuthorityResolution] = None,
    geometry_resolution: Optional[AuthorityResolution] = None,
    planning_resolution: Optional[AuthorityResolution] = None,
) -> ParcelContext:
    """Apply only active selections; recommendations are deliberately ignored."""

    def empty(purpose: str) -> AuthorityResolution:
        return AuthorityResolution(purpose, "authority-policy/1.0", None)

    return _apply(
        parcel,
        area_resolution or empty("area_reconciliation"),
        geometry_resolution or empty("geometry_reconciliation"),
        planning_resolution or empty("planning"),
    )


class AuthorityResolver:
    """Resolve recommendations and apply only records explicitly active in a store."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def recommend(self, parcel: ParcelContext, purpose: Any) -> AuthorityResolution:
        purpose_value = normalize_purpose(purpose)
        list_method = getattr(self.store, "list", None) or getattr(self.store, "records", None)
        records: Iterable[Any] = ()
        if callable(list_method):
            try:
                records = list_method(village=parcel.village, cts_no=parcel.cts_no, purpose=purpose_value)
            except TypeError:
                try:
                    records = list_method(village=parcel.village, cts_no=parcel.cts_no)
                except TypeError:
                    records = list_method()
        return recommend_authority_sources(
            records,
            purpose_value,
            village=parcel.village,
            cts_no=parcel.cts_no,
        )

    def resolve(self, parcel: ParcelContext) -> ParcelContext:
        resolutions = []
        for purpose in ("area_reconciliation", "geometry_reconciliation", "planning"):
            active = _active_records(self.store, parcel.village, parcel.cts_no, purpose)
            resolutions.append(
                recommend_authority_sources(
                    active,
                    purpose,
                    village=parcel.village,
                    cts_no=parcel.cts_no,
                    active=True,
                )
            )
        return _apply(parcel, resolutions[0], resolutions[1], resolutions[2])

    def __call__(self, parcel: ParcelContext) -> ParcelContext:
        return self.resolve(parcel)


__all__ = ["AuthorityResolver", "apply_authority_selection"]
