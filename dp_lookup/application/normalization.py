"""Pure normalization of ArcGIS evidence into application-stage contracts."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Sequence

from dp_lookup.application.contracts import NeighbourContext, PlanningContext, RoadContext
from dp_lookup.clients.responses import usable_json
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.models import EvidenceState, SourceEvidence
from dp_lookup.core.planning_status import crz_flag_from, derive_status, select_road


class PlanningEvidenceError(RuntimeError):
    """Required planning evidence was unavailable or unusable."""


def _mapping_items(value: Any) -> List[Dict[str, Any]]:
    """Return only mapping-shaped ArcGIS collection members."""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_percent(value: Any) -> tuple[float, bool]:
    """Normalize an untrusted percentage to a finite 0..100 value."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0, False
    if not math.isfinite(number):
        return 0.0, False
    return min(100.0, max(0.0, number)), 0.0 <= number <= 100.0


def _road_attributes(attributes: Dict[str, Any]) -> tuple:
    name = (
        attributes.get("ROAD_NAME")
        or attributes.get("Roadname")
        or attributes.get("NAME")
        or attributes.get("Name")
        or attributes.get("TYPE_")
        or attributes.get("Type")
    )
    width = attributes.get("WIDTH_RL") or attributes.get("WIDTH") or attributes.get("Width")
    return name, width


def parse_road_responses(responses: Any, expected_count: int) -> RoadContext:
    """Normalize repeated road probes and retain source-quality state."""
    road_map: Dict[str, Dict[str, Any]] = {}
    geometries: List[List[List[float]]] = []
    failures = 0
    if isinstance(responses, Exception):
        failures = expected_count
        response_items: Iterable[Any] = ()
    elif not isinstance(responses, (list, tuple)):
        failures = expected_count
        response_items = ()
    else:
        response_items = responses

    for response in response_items:
        payload = usable_json(response)
        if payload is None:
            failures += 1
            continue
        raw_features = payload.get("features", [])
        raw_results = payload.get("results", [])
        if not isinstance(raw_features, (list, tuple)) or not isinstance(raw_results, (list, tuple)):
            failures += 1
            continue
        for item in _mapping_items(raw_features) + _mapping_items(raw_results):
            attributes = item.get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
            name, width = _road_attributes(attributes)
            if name or width:
                road_map[f"{name}|{width}"] = {"name": name or "Road", "width": width or "N/A"}
            geometry = item.get("geometry")
            if not isinstance(geometry, dict):
                continue
            raw_parts = geometry.get("paths") or geometry.get("rings") or []
            if not isinstance(raw_parts, (list, tuple)):
                continue
            for part in raw_parts:
                if not isinstance(part, (list, tuple)) or len(part) < 2:
                    continue
                try:
                    geometries.append([mercator_to_wgs84(point[0], point[1]) for point in part])
                except (IndexError, TypeError, ValueError):
                    continue

    warnings = []
    if failures:
        warnings.append(f"{failures} of {expected_count} road probes failed; abutting road may be incomplete")
    selected = select_road(road_map)
    name = selected["name"]
    if failures == expected_count:
        state = EvidenceState.FAILED.value
    elif name == "Unnamed / existing road" or name == "None":
        state = EvidenceState.UNKNOWN.value
    else:
        state = EvidenceState.CONFIRMED.value
    return RoadContext(
        name=name,
        width=selected["width"],
        geometries=geometries,
        warnings=warnings,
        evidence_state=state,
    )


def parse_neighbour_responses(
    responses: Any,
    expected_count: int,
    parcel_cts: str,
    parcel_village: str,
) -> NeighbourContext:
    """Normalize adjoining-parcel probes without leaking ArcGIS field casing."""
    neighbours: Dict[str, Dict[str, Any]] = {}
    failures = 0
    if isinstance(responses, Exception):
        failures = expected_count
        response_items: Iterable[Any] = ()
    elif not isinstance(responses, (list, tuple)):
        failures = expected_count
        response_items = ()
    else:
        response_items = responses

    for response in response_items:
        payload = usable_json(response)
        if payload is None:
            failures += 1
            continue
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, (list, tuple)):
            failures += 1
            continue
        for item in _mapping_items(raw_results):
            attributes = item.get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
            cts_no = attributes.get("cts_cs_no") or attributes.get("CTS_CS_NO")
            if not cts_no or str(cts_no).strip() == str(parcel_cts).strip():
                continue
            area = attributes.get("area_app_sq_mtrs") or attributes.get("AREA_APP_SQ_MTRS")
            village = attributes.get("village") or attributes.get("VILLAGE")
            geometry = item.get("geometry")
            rings = geometry.get("rings") if isinstance(geometry, dict) else []
            if not isinstance(rings, (list, tuple)):
                rings = []
            wgs_rings = []
            for ring in rings:
                if not isinstance(ring, (list, tuple)):
                    continue
                try:
                    wgs_rings.append([mercator_to_wgs84(point[0], point[1]) for point in ring])
                except (IndexError, TypeError, ValueError):
                    continue
            neighbours[str(cts_no)] = {
                "cts_no": str(cts_no),
                "village": str(village or parcel_village),
                "area_sqm": str(area) if area is not None else "N/A",
                "rings": wgs_rings,
            }

    warnings = []
    if failures:
        warnings.append(
            f"{failures} of {expected_count} neighbour probes failed; adjoining plots list may be incomplete"
        )
    state = EvidenceState.FAILED.value if failures == expected_count else EvidenceState.CONFIRMED.value
    return NeighbourContext(plots=list(neighbours.values()), warnings=warnings, evidence_state=state)


def _fallback_item(
    attributes: Dict[str, Any],
    area_sqm: float,
    wgs_rings: List[List[List[float]]],
    kind: str,
) -> Dict[str, Any]:
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
            "raw_attributes": attributes,
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
            "raw_attributes": attributes,
        }
    return {
        "approval_no": str(attributes.get("APPROVAL_NO") or "DP Mod"),
        "details": str(attributes.get("LABEL") or attributes.get("LABEL to Display") or "Modified"),
        "document_link": str(
            attributes.get("APPROVAL_DOCUMENTS") or attributes.get("Approval Documents") or "None"
        ),
        "overlap_sqm": area_sqm,
        "overlap_percent": 100.0,
        "raw_attributes": attributes,
    }


def normalize_planning_evidence(
    spatial_result: Any,
    identify_response: Any,
    area_sqm: float,
    wgs_rings: List[List[List[float]]],
    crz_layer_ids: Sequence[int],
) -> PlanningContext:
    """Reconcile polygon queries with point identify while preserving failures."""
    identify_json = usable_json(identify_response)
    if isinstance(spatial_result, Exception) and identify_json is None:
        raise PlanningEvidenceError(
            "Planning data could not be retrieved from the MCGM map server "
            "(the identify/spatial request failed or timed out)."
        )

    warnings: List[str] = []
    method = "spatial_polygon"
    if isinstance(spatial_result, dict):
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
        results = _mapping_items(identify_json.get("results")) if identify_json else []
        by_layer = {item.get("layerId"): item for item in results}
        zone_item = by_layer.get(0)
        zone = (
            (
                zone_item.get("attributes", {}).get("Zone_Code2")
                or zone_item.get("attributes", {}).get("ZONE_CODE2")
                or "Unknown"
            )
            if zone_item
            else "Unknown"
        )
        zones = [{"zone": zone, "overlap_sqm": area_sqm, "overlap_percent": 100.0}] if zone != "Unknown" else []
        reservations = (
            [_fallback_item(by_layer[46].get("attributes", {}), area_sqm, wgs_rings, "reservation")]
            if 46 in by_layer
            else []
        )
        designations = (
            [_fallback_item(by_layer[47].get("attributes", {}), area_sqm, wgs_rings, "designation")]
            if 47 in by_layer
            else []
        )
        modifications = (
            [_fallback_item(by_layer[192].get("attributes", {}), area_sqm, wgs_rings, "modification")]
            if 192 in by_layer
            else []
        )
        metro = "YES (Metro Buffer Zone)" if 1550 in by_layer else "NO"
        crz_item = next((item for item in results if item.get("layerId") in crz_layer_ids), None)
        crz = crz_flag_from(crz_item)
        encumbered_percent = 100.0 if reservations or designations else 0.0

    results = _mapping_items(identify_json.get("results")) if identify_json else []
    for item in results:
        layer_id = item.get("layerId")
        attributes = item.get("attributes", {}) or {}
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

    if encumbered_percent <= 0.0:
        encumbered_area = 0.0
        net_area = area_sqm
        net_percent = 100.0
    else:
        encumbered_area = round(area_sqm * encumbered_percent / 100.0, 2)
        net_area = max(0.0, round(area_sqm - encumbered_area, 2))
        net_percent = max(0.0, round(100.0 - encumbered_percent, 2))
    for item in reservations + designations:
        overlap_percent, valid_overlap = _safe_percent(item.get("overlap_percent", 0.0))
        if not valid_overlap:
            warnings.append("MCGM returned an invalid planning overlap percentage; it was treated as zero")
            planning_state = EvidenceState.UNKNOWN
        item["overlap_percent"] = overlap_percent
        item["overlap_sqm"] = round(area_sqm * overlap_percent / 100.0, 2)

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
