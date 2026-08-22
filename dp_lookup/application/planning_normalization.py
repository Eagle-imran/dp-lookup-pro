"""Reconcile local/live planning evidence into one application contract."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence

from dp_lookup.application.contracts import PlanningContext
from dp_lookup.clients.arcgis_models import ArcGISPayload, decode_arcgis_response
from dp_lookup.core.models import EvidenceState, SourceEvidence
from dp_lookup.core.planning_status import crz_flag_from, derive_status


class PlanningEvidenceError(RuntimeError):
    """Required planning evidence was unavailable or unusable."""


def _mapping_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _safe_percent(value: Any) -> tuple[float, bool]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0, False
    if not math.isfinite(number):
        return 0.0, False
    return min(100.0, max(0.0, number)), 0.0 <= number <= 100.0


def _fallback_item(
    attributes: Mapping[str, Any],
    area_sqm: float,
    wgs_rings: List[List[List[float]]],
    kind: str,
) -> Dict[str, Any]:
    copied_attributes = dict(attributes)
    if kind == "reservation":
        proposed_code = attributes.get("NEW_RES_CODE_31")
        final_code = attributes.get("FINAL_RES_CODE")
        proposed_type = attributes.get("NEW_RES_MAINTYPE_31")
        final_type = attributes.get("FINAL_RES_MAINTYPE")
        return {
            "code": str(final_code or proposed_code or "None"),
            "type": str(final_type or proposed_type or "None"),
            "proposed_code": str(proposed_code or "None"),
            "final_code": str(final_code or "None"),
            "proposed_type": str(proposed_type or "None"),
            "final_type": str(final_type or "None"),
            "description": str(attributes.get("DISCRIPTION") or "Reservation").strip(),
            "u_r_id": str(attributes.get("U_R_ID") or "N/A"),
            "overlap_sqm": area_sqm,
            "total_res_sqm": area_sqm,
            "overlap_percent": 100.0,
            "wgs_rings": wgs_rings,
            "raw_attributes": copied_attributes,
        }
    if kind == "designation":
        proposed_code = attributes.get("NEW_DES_CODE_31")
        final_code = attributes.get("FINAL_DES_CODE")
        proposed_type = attributes.get("NEW_DES_MAINTYPE_31")
        final_type = attributes.get("FINAL_DES_MAINTYPE")
        return {
            "code": str(final_code or proposed_code or "None"),
            "type": str(final_type or proposed_type or "None"),
            "proposed_code": str(proposed_code or "None"),
            "final_code": str(final_code or "None"),
            "proposed_type": str(proposed_type or "None"),
            "final_type": str(final_type or "None"),
            "description": str(attributes.get("DISCRIPTION") or "Designation").strip(),
            "u_d_id": str(attributes.get("U_D_ID") or "N/A"),
            "overlap_sqm": area_sqm,
            "total_des_sqm": area_sqm,
            "overlap_percent": 100.0,
            "wgs_rings": wgs_rings,
            "raw_attributes": copied_attributes,
        }
    return {
        "approval_no": str(attributes.get("APPROVAL_NO") or "DP Mod"),
        "details": str(attributes.get("LABEL") or attributes.get("LABEL to Display") or "Modified"),
        "document_link": str(
            attributes.get("APPROVAL_DOCUMENTS") or attributes.get("Approval Documents") or "None"
        ),
        "overlap_sqm": area_sqm,
        "overlap_percent": 100.0,
        "raw_attributes": copied_attributes,
    }


def _identified_by_layer(payload: Optional[ArcGISPayload]) -> Dict[int, Mapping[str, Any]]:
    if payload is None:
        return {}
    return {item.layer_id: item.attributes for item in payload.results if item.layer_id is not None}


def normalize_planning_evidence(
    spatial_result: Any,
    identify_response: Any,
    area_sqm: float,
    wgs_rings: List[List[List[float]]],
    crz_layer_ids: Sequence[int],
) -> PlanningContext:
    """Reconcile polygon queries with point identify while preserving failures."""
    identify_payload = decode_arcgis_response(identify_response)
    if isinstance(spatial_result, Exception) and identify_payload is None:
        raise PlanningEvidenceError(
            "Planning data could not be retrieved from the MCGM map server "
            "(the identify/spatial request failed or timed out)."
        )

    warnings: List[str] = []
    method = "spatial_polygon"
    planning_provenance: Dict[str, Any] = {}
    zones: List[Dict[str, Any]]
    reservations: List[Dict[str, Any]]
    designations: List[Dict[str, Any]]
    modifications: List[Dict[str, Any]]
    if isinstance(spatial_result, dict):
        raw_provenance = spatial_result.get("provenance")
        if isinstance(raw_provenance, Mapping):
            planning_provenance = dict(raw_provenance)
            method = str(planning_provenance.get("method") or method)
        reservations = deepcopy(_mapping_items(spatial_result.get("reservations")))
        designations = deepcopy(_mapping_items(spatial_result.get("designations")))
        modifications = deepcopy(_mapping_items(spatial_result.get("modifications")))
        zones = deepcopy(_mapping_items(spatial_result.get("zones")))
        zone = spatial_result.get("primary_zone", "Unknown")
        metro = spatial_result.get("metro_buffer", "NO")
        crz = spatial_result.get("crz_status", "NO (Outside CRZ Buffer)")
        encumbered_percent, valid_percent = _safe_percent(spatial_result.get("encumbered_percent", 0.0))
        if not valid_percent:
            warnings.append("MCGM returned an invalid encumbrance percentage; it was treated as unknown/zero")
        raw_warnings = spatial_result.get("warnings")
        if isinstance(raw_warnings, (list, tuple)):
            warnings.extend(str(warning) for warning in raw_warnings)
        queried_layers = spatial_result.get("queried_layers", [])
        successful_layers = spatial_result.get("successful_layers", [])
        queried_set = (
            {int(layer) for layer in queried_layers if isinstance(layer, (int, str)) and str(layer).isdigit()}
            if isinstance(queried_layers, (list, tuple))
            else set()
        )
        successful_set = (
            {int(layer) for layer in successful_layers if isinstance(layer, (int, str)) and str(layer).isdigit()}
            if isinstance(successful_layers, (list, tuple))
            else set()
        )
        planning_state = (
            EvidenceState.CONFIRMED
            if queried_set and queried_set == successful_set and not warnings
            else EvidenceState.UNKNOWN
        )
    else:
        method = "identify_fallback"
        planning_state = EvidenceState.UNKNOWN
        warnings.append(
            "Spatial planning polygon queries failed; point-identify fallback was used and overlap evidence is incomplete"
        )
        by_layer = _identified_by_layer(identify_payload)
        zone_attributes = by_layer.get(0, {})
        zone = zone_attributes.get("Zone_Code2") or zone_attributes.get("ZONE_CODE2") or "Unknown"
        zones = [{"zone": zone, "overlap_sqm": area_sqm, "overlap_percent": 100.0}] if zone != "Unknown" else []
        reservations = (
            [_fallback_item(by_layer[46], area_sqm, wgs_rings, "reservation")] if 46 in by_layer else []
        )
        designations = (
            [_fallback_item(by_layer[47], area_sqm, wgs_rings, "designation")] if 47 in by_layer else []
        )
        modifications = (
            [_fallback_item(by_layer[192], area_sqm, wgs_rings, "modification")] if 192 in by_layer else []
        )
        metro = "YES (Metro Buffer Zone)" if 1550 in by_layer else "NO"
        crz_item = next(
            (
                dict(item.raw)
                for item in (identify_payload.results if identify_payload is not None else ())
                if item.layer_id in crz_layer_ids
            ),
            None,
        )
        crz = crz_flag_from(crz_item)
        encumbered_percent = 100.0 if reservations or designations else 0.0

    for item in identify_payload.results if identify_payload is not None else ():
        layer_id = item.layer_id
        attributes = item.attributes
        if layer_id == 0 and str(zone).strip().casefold() in ("", "unknown", "none", "null"):
            zone = attributes.get("Zone_Code2") or attributes.get("ZONE_CODE2") or "Unknown"
        elif layer_id == 46 and not reservations:
            candidate = _fallback_item(attributes, area_sqm, wgs_rings, "reservation")
            if candidate["code"] != "None":
                reservations.append(candidate)
        elif layer_id == 47 and not designations:
            candidate = _fallback_item(attributes, area_sqm, wgs_rings, "designation")
            if candidate["code"] != "None":
                designations.append(candidate)
        elif layer_id == 192 and not modifications and attributes.get("APPROVAL_NO") not in (None, "None"):
            modifications.append(_fallback_item(attributes, area_sqm, wgs_rings, "modification"))

    if not zone or str(zone).strip().casefold() in ("", "unknown", "none", "null"):
        raise PlanningEvidenceError("MCGM returned the parcel but no usable zoning evidence from Layer 0.")
    if not zones:
        zones = [{"zone": zone, "overlap_sqm": area_sqm, "overlap_percent": 100.0}]

    encumbered_area = round(area_sqm * encumbered_percent / 100.0, 2) if encumbered_percent > 0.0 else 0.0
    net_area = max(0.0, round(area_sqm - encumbered_area, 2))
    net_percent = max(0.0, round(100.0 - encumbered_percent, 2))
    for planning_item in reservations + designations:
        overlap_percent, valid_overlap = _safe_percent(planning_item.get("overlap_percent", 0.0))
        if not valid_overlap:
            warnings.append("MCGM returned an invalid planning overlap percentage; it was treated as zero")
            planning_state = EvidenceState.UNKNOWN
        planning_item["overlap_percent"] = overlap_percent
        planning_item["overlap_sqm"] = round(area_sqm * overlap_percent / 100.0, 2)

    res_code = str(reservations[0].get("code", "None")) if reservations else "None"
    res_type = str(reservations[0].get("type", "None")) if reservations else "None"
    des_code = str(designations[0].get("code", "None")) if designations else "None"
    des_description = str(designations[0].get("description", "None")) if designations else "None"
    mod_approval = str(modifications[0].get("approval_no", "None")) if modifications else "None"
    status = derive_status(
        mod_item={"approval": mod_approval} if modifications else None,
        des_item={"code": des_code} if designations else None,
        rv_item={"code": res_code} if reservations else None,
        des_desc=des_description,
        des_code=des_code,
        res_code=res_code,
        res_type=res_type,
        mod_approval=mod_approval,
        reservations=reservations,
        designations=designations,
        modifications=modifications,
        encumbered_percent=encumbered_percent,
        encumbered_area_sqm=encumbered_area,
        total_area_sqm=area_sqm,
        net_unencumbered_sqm=net_area,
    )
    evidence = {
        "zoning": SourceEvidence(
            value=zone,
            state=EvidenceState.CONFIRMED,
            source="MCGM Development Plan 2034",
            method=method,
            layer_ids=(0,),
        ).to_dict(),
        "planning_constraints": SourceEvidence(
            value={
                "reservations": len(reservations),
                "designations": len(designations),
                "modifications": len(modifications),
            },
            state=planning_state,
            source="MCGM Development Plan 2034",
            method=method,
            layer_ids=(46, 47, 192, 14, 1264, 1548, 1550),
            warnings=tuple(warnings),
        ).to_dict(),
    }
    if planning_provenance:
        evidence["planning_source"] = SourceEvidence(
            value=planning_provenance,
            state=planning_state,
            source="MCGM Development Plan 2034",
            method=method,
            layer_ids=(0, 46, 47, 192, 1550, 14, 1264, 1548),
            retrieved_at=(
                str(planning_provenance.get("snapshot_finalized_at"))
                if planning_provenance.get("snapshot_finalized_at") is not None
                else None
            ),
            warnings=tuple(warnings),
        ).to_dict()
    return PlanningContext(
        zone=str(zone),
        zones=zones,
        reservations=reservations,
        designations=designations,
        modifications=modifications,
        metro_buffer=str(metro),
        crz_status=str(crz),
        encumbered_area_sqm=encumbered_area,
        encumbered_percent=encumbered_percent,
        net_unencumbered_sqm=net_area,
        net_unencumbered_percent=net_percent,
        status_badge=status["badge"],
        status_summary=status["summary"],
        warnings=warnings,
        evidence=evidence,
    )
