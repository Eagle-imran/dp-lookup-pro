"""Application adapter for explicitly active authority sources."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.authority.models import AuthorityRecord, SelectionPurpose
from dp_lookup.authority.selection import (
    AuthorityRegistry,
    AuthorityResolution,
    recommend_authority_sources,
    source_type_label,
)
from dp_lookup.core.area_assessment import AREA_DIFFERENCE_THRESHOLDS, calculated_boundary_area_sqm
from dp_lookup.core.geometry import prepare_geometry
from dp_lookup.core.models import AreaAssessment, AreaQualityFlag, ReliabilityStatus


def _rings(record: AuthorityRecord) -> list[list[list[float]]]:
    return [[[x, y] for x, y in ring] for ring in record.normalized_epsg3857_rings]


def _area(record: AuthorityRecord) -> float | None:
    value = record.recorded_area_sqm if record.recorded_area_sqm is not None else record.calculated_area_sqm
    return value if value is not None and value > 0 else None


def _label(record: AuthorityRecord) -> str:
    return source_type_label(record.source_type)


def _working_assessment(
    baseline: AreaAssessment | None,
    calculated: float | None,
    selected: float | None,
    *,
    area_source: AuthorityRecord | None,
    geometry_source: AuthorityRecord | None,
    area_applied: bool,
    geometry_applied: bool,
) -> AreaAssessment | None:
    """Recalculate the assessment while keeping MCGM recorded area intact."""
    if baseline is None:
        return None
    difference = None
    difference_percent = None
    thresholds: tuple[int, ...] = ()
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
            working_rings = replacement
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
    if area_source is not None:
        attrs["_DP_AUTHORITY_AREA_SOURCE"] = _label(area_source)
    if geometry_source is not None:
        attrs["_DP_AUTHORITY_GEOMETRY_SOURCE"] = _label(geometry_source)
    field_names = {item.name for item in fields(working)}
    if "authority_resolution" in field_names:
        return replace(working, attrs=attrs, authority_resolution=resolution_payload)
    return replace(working, attrs=attrs)


class AuthorityResolver:
    """Resolve recommendations and apply only records explicitly active in a store."""

    def __init__(self, store: AuthorityRegistry) -> None:
        self.store = store

    def resolve(self, parcel: ParcelContext) -> ParcelContext:
        area, geometry, planning = (
            recommend_authority_sources(
                self.store.active(parcel.village, parcel.cts_no, purpose=purpose),
                purpose,
                village=parcel.village,
                cts_no=parcel.cts_no,
                active=True,
            )
            for purpose in (SelectionPurpose.AREA, SelectionPurpose.GEOMETRY, SelectionPurpose.PLANNING)
        )
        return _apply(parcel, area, geometry, planning)

    def __call__(self, parcel: ParcelContext) -> ParcelContext:
        return self.resolve(parcel)


__all__ = ["AuthorityResolver"]
