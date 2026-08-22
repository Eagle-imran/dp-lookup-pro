"""MCGM planning-layer fetch and deterministic polygon intersection policy."""

import asyncio
import math
from typing import Any, Dict, List, Optional, Tuple

import httpx
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from dp_lookup.clients.arcgis_payloads import spatial_query_payload
from dp_lookup.clients.responses import usable_json
from dp_lookup.core.area_assessment import web_mercator_ground_area_scale
from dp_lookup.core.constants import (
    CRZ_LAYER_IDS,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
    SERVER_URL,
    SLIVER_AREA_THRESHOLD_SQM,
    SLIVER_PERCENT_THRESHOLD,
)
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.topology import arcgis_rings_to_geometry


def _overlap(
    parcel: BaseGeometry,
    feature: Dict[str, Any],
    threshold: float,
) -> Tuple[Optional[BaseGeometry], Optional[BaseGeometry]]:
    geometry = feature.get("geometry") or {}
    rings = geometry.get("rings")
    if not rings:
        return None, None
    polygon = arcgis_rings_to_geometry(rings)
    if polygon.is_empty or not parcel.intersects(polygon):
        return None, polygon
    intersection = parcel.intersection(polygon)
    return (intersection if intersection.area > threshold else None), polygon


def _wgs_rings(feature: Dict[str, Any]) -> List[List[List[float]]]:
    rings = (feature.get("geometry") or {}).get("rings") or []
    return [[mercator_to_wgs84(point[0], point[1]) for point in ring] for ring in rings]


async def _fetch_layers(
    client: httpx.AsyncClient,
    bbox: str,
    layer_ids: List[int],
) -> Tuple[Dict[int, List[Dict[str, Any]]], List[str]]:
    responses = await asyncio.gather(
        *[client.post(f"{SERVER_URL}/{layer_id}/query", data=spatial_query_payload(bbox)) for layer_id in layer_ids],
        return_exceptions=True,
    )
    features_by_layer: Dict[int, List[Dict[str, Any]]] = {}
    warnings: List[str] = []
    for layer_id, response in zip(layer_ids, responses):
        if isinstance(response, Exception):
            features_by_layer[layer_id] = []
            warnings.append(f"Layer {layer_id} query failed: {response}")
            continue
        payload = usable_json(response)
        if payload is None:
            features_by_layer[layer_id] = []
            warnings.append(f"Layer {layer_id} returned invalid or error JSON")
            continue
        features = payload.get("features", [])
        if not isinstance(features, list):
            features_by_layer[layer_id] = []
            warnings.append(f"Layer {layer_id} returned a malformed features collection")
            continue
        features_by_layer[layer_id] = features
    return features_by_layer, warnings


def build_spatial_planning_result(
    parcel: Any,
    by_layer: Dict[int, List[Dict[str, Any]]],
    warnings: List[str],
    *,
    provenance: Optional[Dict[str, Any]] = None,
    area_scale: float = 1.0,
) -> Dict[str, Any]:
    """Build the stable planning result from already spatially-selected records.

    Live ArcGIS and local snapshot adapters both use this function. Keeping
    intersection and output policy in one place prevents the local path from
    silently acquiring different reservation, CRZ, or sliver semantics.
    """
    layer_ids = [
        LAYER_ZONE,
        LAYER_RESERVATION,
        LAYER_DESIGNATION,
        LAYER_MODIFICATION,
        LAYER_METRO,
        *CRZ_LAYER_IDS,
    ]
    if not math.isfinite(area_scale) or area_scale <= 0:
        raise ValueError("area_scale must be finite and positive")
    threshold = max(SLIVER_AREA_THRESHOLD_SQM / area_scale, parcel.area * SLIVER_PERCENT_THRESHOLD)

    reservations = []
    reservation_polygons = []
    for feature in by_layer.get(LAYER_RESERVATION, []):
        try:
            intersection, polygon = _overlap(parcel, feature, threshold)
            if intersection is None or polygon is None:
                continue
            attributes = feature.get("attributes", {})
            reservation_polygons.append(intersection)
            proposed_code = attributes.get("NEW_RES_CODE_31")
            final_code = attributes.get("FINAL_RES_CODE")
            proposed_type = attributes.get("NEW_RES_MAINTYPE_31")
            final_type = attributes.get("FINAL_RES_MAINTYPE")
            reservations.append(
                {
                    "code": str(final_code or proposed_code or "Unknown"),
                    "type": str(final_type or proposed_type or "None"),
                    "proposed_code": str(proposed_code or "None"),
                    "final_code": str(final_code or "None"),
                    "proposed_type": str(proposed_type or "None"),
                    "final_type": str(final_type or "None"),
                    "description": str((attributes.get("DISCRIPTION") or "").strip() or "Reservation"),
                    "u_r_id": str(attributes.get("U_R_ID") or "N/A"),
                    "overlap_sqm": round(intersection.area * area_scale, 2),
                    "total_res_sqm": round(polygon.area * area_scale, 2),
                    "overlap_percent": round(intersection.area / parcel.area * 100, 2),
                    "wgs_rings": _wgs_rings(feature),
                    "raw_attributes": attributes,
                }
            )
        except Exception:
            continue

    designations = []
    designation_polygons = []
    for feature in by_layer.get(LAYER_DESIGNATION, []):
        try:
            intersection, polygon = _overlap(parcel, feature, threshold)
            if intersection is None or polygon is None:
                continue
            attributes = feature.get("attributes", {})
            designation_polygons.append(intersection)
            proposed_code = attributes.get("NEW_DES_CODE_31")
            final_code = attributes.get("FINAL_DES_CODE")
            proposed_type = attributes.get("NEW_DES_MAINTYPE_31")
            final_type = attributes.get("FINAL_DES_MAINTYPE")
            designations.append(
                {
                    "code": str(final_code or proposed_code or "Unknown"),
                    "type": str(final_type or proposed_type or "None"),
                    "proposed_code": str(proposed_code or "None"),
                    "final_code": str(final_code or "None"),
                    "proposed_type": str(proposed_type or "None"),
                    "final_type": str(final_type or "None"),
                    "description": str((attributes.get("DISCRIPTION") or "").strip() or "Designation"),
                    "u_d_id": str(attributes.get("U_D_ID") or "N/A"),
                    "overlap_sqm": round(intersection.area * area_scale, 2),
                    "total_des_sqm": round(polygon.area * area_scale, 2),
                    "overlap_percent": round(intersection.area / parcel.area * 100, 2),
                    "wgs_rings": _wgs_rings(feature),
                    "raw_attributes": attributes,
                }
            )
        except Exception:
            continue

    modifications = []
    for feature in by_layer.get(LAYER_MODIFICATION, []):
        try:
            intersection, _ = _overlap(parcel, feature, threshold)
            if intersection is None:
                continue
            attributes = feature.get("attributes", {})
            modifications.append(
                {
                    "approval_no": str(attributes.get("APPROVAL_NO") or "DP Mod"),
                    "details": str(attributes.get("LABEL") or attributes.get("LABEL to Display") or "Modified"),
                    "document_link": str(
                        attributes.get("APPROVAL_DOCUMENTS") or attributes.get("Approval Documents") or "None"
                    ),
                    "overlap_sqm": round(intersection.area * area_scale, 2),
                    "overlap_percent": round(intersection.area / parcel.area * 100, 2),
                    "raw_attributes": attributes,
                }
            )
        except Exception:
            continue

    zones = []
    for feature in by_layer.get(LAYER_ZONE, []):
        try:
            intersection, _ = _overlap(parcel, feature, threshold)
            if intersection is None:
                continue
            attributes = feature.get("attributes", {})
            zones.append(
                {
                    "zone": str(attributes.get("ZONE_CODE2") or attributes.get("Zone_Code2") or "Unknown"),
                    "overlap_sqm": round(intersection.area * area_scale, 2),
                    "overlap_percent": round(intersection.area / parcel.area * 100, 2),
                }
            )
        except Exception:
            continue
    zones.sort(key=lambda item: item["overlap_sqm"], reverse=True)

    metro = "NO"
    for feature in by_layer.get(LAYER_METRO, []):
        try:
            intersection, _ = _overlap(parcel, feature, 0.0)
            if intersection is not None:
                metro = "YES (Metro Buffer Zone)"
                break
        except Exception:
            continue

    crz = "NO (Outside CRZ Buffer)"
    crz_hits = []
    for layer_id in CRZ_LAYER_IDS:
        for feature in by_layer.get(layer_id, []):
            try:
                intersection, _ = _overlap(parcel, feature, 0.0)
                if intersection is None:
                    continue
                attributes = feature.get("attributes", {})
                category = attributes.get("CATEGORY") or attributes.get("CLASS") or ""
                tier = str(category).replace("CRZ", "").replace("ZONE", "").strip() or "YES"
                label = tier if tier.upper().startswith("CRZ") else f"CRZ {tier}"
                crz_hits.append(
                    {
                        "layer_id": layer_id,
                        "category": label,
                        "overlap_sqm": round(intersection.area * area_scale, 2),
                        "overlap_percent": round(intersection.area / parcel.area * 100, 3),
                    }
                )
            except Exception:
                continue
    crz_hits.sort(key=lambda item: (-item["overlap_sqm"], item["layer_id"], item["category"]))
    if crz_hits:
        crz = f"YES ({crz_hits[0]['category']})"

    encumbered_polygons = reservation_polygons + designation_polygons
    if encumbered_polygons:
        encumbered = unary_union(encumbered_polygons)
        encumbered_area = round(encumbered.area * area_scale, 2)
        encumbered_percent = round(encumbered.area / parcel.area * 100, 2)
    else:
        encumbered_area = 0.0
        encumbered_percent = 0.0

    result = {
        "primary_zone": zones[0]["zone"] if zones else "Unknown",
        "zones": zones,
        "reservations": reservations,
        "designations": designations,
        "modifications": modifications,
        "metro_buffer": metro,
        "crz_status": crz,
        "crz_categories": crz_hits,
        "encumbered_area_sqm": encumbered_area,
        "encumbered_percent": encumbered_percent,
        "net_unencumbered_sqm": max(0.0, round(parcel.area * area_scale - encumbered_area, 2)),
        "net_unencumbered_percent": max(0.0, round(100.0 - encumbered_percent, 2)),
        "warnings": warnings,
        "queried_layers": layer_ids,
        "successful_layers": [
            layer_id
            for layer_id in layer_ids
            if not any(warning.startswith(f"Layer {layer_id} ") for warning in warnings)
        ],
    }
    if provenance is not None:
        result["provenance"] = provenance
    return result


async def query_spatial_planning_layers(
    client: httpx.AsyncClient,
    rings: List[List[List[float]]],
) -> Dict[str, Any]:
    """Query all planning layers and compute exact parcel intersections."""
    parcel = arcgis_rings_to_geometry(rings)
    if parcel.is_empty or parcel.area <= 0:
        raise ValueError("Parcel geometry has no valid polygon rings")
    bbox = ",".join(str(value) for value in parcel.bounds)
    area_scale = web_mercator_ground_area_scale(rings, float(parcel.area)) or 1.0
    layer_ids = [
        LAYER_ZONE,
        LAYER_RESERVATION,
        LAYER_DESIGNATION,
        LAYER_MODIFICATION,
        LAYER_METRO,
        *CRZ_LAYER_IDS,
    ]
    by_layer, warnings = await _fetch_layers(client, bbox, layer_ids)
    return build_spatial_planning_result(parcel, by_layer, warnings, area_scale=area_scale)
