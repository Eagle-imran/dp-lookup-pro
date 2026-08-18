"""
ArcGIS Server REST Client & Spatial Planning Layer Queries.
"""
import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from shapely.geometry import Polygon
from shapely.ops import unary_union

from dp_lookup.clients.cache import _TILE_CACHE, usable_json
from dp_lookup.core.constants import (
    CRZ_LAYER_IDS,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
    PLANNING_LAYER_IDS,
    SERVER_URL,
    SLIVER_AREA_THRESHOLD_SQM,
    SLIVER_PERCENT_THRESHOLD,
)
from dp_lookup.core.geometry import mercator_to_wgs84


def identify_payload(
    x: float,
    y: float,
    layers: str,
    mcx: float,
    mcy: float,
    d: float,
    tolerance: int,
    return_geometry: bool,
) -> Dict[str, str]:
    """One ArcGIS /identify POST body."""
    return {
        "geometry": f"{x},{y}",
        "geometryType": "esriGeometryPoint",
        "sr": "102100",
        "layers": layers,
        "tolerance": str(tolerance),
        "mapExtent": f"{mcx - d},{mcy - d},{mcx + d},{mcy + d}",
        "imageDisplay": "1000,1000,96",
        "returnGeometry": "true" if return_geometry else "false",
        "f": "json",
    }


def spatial_query_payload(bbox_str: str, out_sr: str = "102100") -> Dict[str, str]:
    """Payload for ArcGIS Server /query spatial bounding-box envelope queries."""
    return {
        "geometry": bbox_str,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": out_sr,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": out_sr,
        "f": "json",
    }


def planning_layers(crz_layer_ids: list) -> str:
    """Format planning layer visibility string."""
    ids = ",".join(str(i) for i in PLANNING_LAYER_IDS + list(crz_layer_ids))
    return f"visible:{ids}"


def map_export_params(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: int = 1000,
    height: int = 1000,
    dpi: int = 144,
) -> Dict[str, str]:
    """Parameters for ArcGIS /export dynamic map rendering."""
    return {
        "bbox": f"{x0},{y0},{x1},{y1}",
        "bboxSR": "102100",
        "imageSR": "102100",
        "size": f"{width},{height}",
        "format": "png",
        "transparent": "false",
        "dpi": str(dpi),
        "layers": "show:0,44,45,46,47,192,193,194,2224",
        "f": "image",
    }


async def fetch_tile_cached(
    client: httpx.AsyncClient,
    zoom: int,
    ytile: int,
    xtile: int,
    tile_dir: str = "/tmp/dp_tile_cache",
) -> Optional[bytes]:
    """Fetch Esri World Imagery satellite tile with memory and local disk caching."""
    k = f"{zoom}/{ytile}/{xtile}"
    if k in _TILE_CACHE:
        return _TILE_CACHE[k]

    os.makedirs(tile_dir, exist_ok=True)
    cache_f = os.path.join(tile_dir, f"esri_tile_{zoom}_{ytile}_{xtile}.jpg")
    if os.path.exists(cache_f):
        try:
            with open(cache_f, "rb") as f:
                blob = f.read()
                _TILE_CACHE[k] = blob
                return blob
        except Exception:
            pass

    tile_url = (
        f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/"
        f"tile/{zoom}/{ytile}/{xtile}"
    )
    try:
        r = await client.get(tile_url, timeout=6.0)
        if r.status_code == 200 and r.content:
            _TILE_CACHE[k] = r.content
            try:
                with open(cache_f, "wb") as f:
                    f.write(r.content)
            except Exception:
                pass
            return r.content
    except Exception:
        pass
    return None


async def query_spatial_planning_layers(
    client: httpx.AsyncClient,
    rings: list,
) -> Dict[str, Any]:
    """
    Performs real spatial polygon intersection queries against MCGM DP 2034 layers:
      - Layer 0: Zoning (Residential, Commercial, Industrial, No Development Zone, etc.)
      - Layer 46: Reservations (ROS, RSA, RT, RE, RM, etc.)
      - Layer 47: Designations (EOS, EH, EE, EPU, EO, etc.)
      - Layer 192: DP Modifications (Sanctions, Excluded Parts / EP Orders)
      - Layer 1550: Metro Rail Influence Buffer
      - Layers 14, 1264, 1548: Coastal Regulation Zone (CRZ I, II, III, IV)
    """
    parcel_poly = Polygon(rings[0])
    min_x, min_y, max_x, max_y = parcel_poly.bounds
    bbox_str = f"{min_x},{min_y},{max_x},{max_y}"

    all_query_layers = [LAYER_ZONE, LAYER_RESERVATION, LAYER_DESIGNATION, LAYER_MODIFICATION, LAYER_METRO, *CRZ_LAYER_IDS]
    tasks = [
        client.post(f"{SERVER_URL}/{lid}/query", data=spatial_query_payload(bbox_str))
        for lid in all_query_layers
    ]

    responses = await asyncio.gather(*tasks, return_exceptions=True)
    res_by_layer: Dict[int, List[Dict[str, Any]]] = {}
    warnings: List[str] = []

    for lid, resp in zip(all_query_layers, responses):
        if isinstance(resp, Exception):
            res_by_layer[lid] = []
            warnings.append(f"Layer {lid} query failed: {resp}")
            continue
        j = usable_json(resp)
        if j is None:
            res_by_layer[lid] = []
            warnings.append(f"Layer {lid} returned invalid or error JSON")
            continue
        res_by_layer[lid] = j.get("features", [])

    min_area_thresh = min(SLIVER_AREA_THRESHOLD_SQM, parcel_poly.area * SLIVER_PERCENT_THRESHOLD)

    # 1. Process Reservations (Layer 46)
    reservations = []
    res_polys = []
    for f in res_by_layer.get(LAYER_RESERVATION, []):
        geom = f.get("geometry")
        if not geom or "rings" not in geom:
            continue
        try:
            r_poly = Polygon(geom["rings"][0])
            if parcel_poly.intersects(r_poly):
                inter = parcel_poly.intersection(r_poly)
                if inter.area > min_area_thresh:
                    attrs = f.get("attributes", {})
                    code = attrs.get("NEW_RES_CODE_31") or attrs.get("FINAL_RES_CODE") or "Unknown"
                    rtype = attrs.get("NEW_RES_MAINTYPE_31") or attrs.get("FINAL_RES_MAINTYPE") or "None"
                    desc = (attrs.get("DISCRIPTION") or "").strip() or "Reservation"
                    u_r_id = attrs.get("U_R_ID") or "N/A"
                    res_polys.append(inter)
                    reservations.append({
                        "code": str(code),
                        "type": str(rtype),
                        "description": str(desc),
                        "u_r_id": str(u_r_id),
                        "overlap_sqm": round(inter.area, 2),
                        "total_res_sqm": round(r_poly.area, 2),
                        "overlap_percent": round((inter.area / parcel_poly.area) * 100, 2),
                        "wgs_rings": [[mercator_to_wgs84(p[0], p[1]) for p in r] for r in geom["rings"]],
                        "raw_attributes": attrs,
                    })
        except Exception:
            continue

    # 2. Process Designations (Layer 47)
    designations = []
    des_polys = []
    for f in res_by_layer.get(LAYER_DESIGNATION, []):
        geom = f.get("geometry")
        if not geom or "rings" not in geom:
            continue
        try:
            d_poly = Polygon(geom["rings"][0])
            if parcel_poly.intersects(d_poly):
                inter = parcel_poly.intersection(d_poly)
                if inter.area > min_area_thresh:
                    attrs = f.get("attributes", {})
                    code = attrs.get("NEW_DES_CODE_31") or attrs.get("FINAL_DES_CODE") or "Unknown"
                    dtype = attrs.get("NEW_DES_MAINTYPE_31") or attrs.get("FINAL_DES_MAINTYPE") or "None"
                    desc = (attrs.get("DISCRIPTION") or "").strip() or "Designation"
                    u_d_id = attrs.get("U_D_ID") or "N/A"
                    des_polys.append(inter)
                    designations.append({
                        "code": str(code),
                        "type": str(dtype),
                        "description": str(desc),
                        "u_d_id": str(u_d_id),
                        "overlap_sqm": round(inter.area, 2),
                        "total_des_sqm": round(d_poly.area, 2),
                        "overlap_percent": round((inter.area / parcel_poly.area) * 100, 2),
                        "wgs_rings": [[mercator_to_wgs84(p[0], p[1]) for p in r] for r in geom["rings"]],
                        "raw_attributes": attrs,
                    })
        except Exception:
            continue

    # 3. Process DP Modifications (Layer 192)
    modifications = []
    for f in res_by_layer.get(LAYER_MODIFICATION, []):
        geom = f.get("geometry")
        if not geom or "rings" not in geom:
            continue
        try:
            m_poly = Polygon(geom["rings"][0])
            if parcel_poly.intersects(m_poly):
                inter = parcel_poly.intersection(m_poly)
                if inter.area > min_area_thresh:
                    attrs = f.get("attributes", {})
                    modifications.append({
                        "approval_no": str(attrs.get("APPROVAL_NO") or "DP Mod"),
                        "details": str(attrs.get("LABEL to Display") or "Modified"),
                        "document_link": str(attrs.get("Approval Documents") or "None"),
                        "overlap_sqm": round(inter.area, 2),
                        "overlap_percent": round((inter.area / parcel_poly.area) * 100, 2),
                        "raw_attributes": attrs,
                    })
        except Exception:
            continue

    # 4. Process Zones (Layer 0)
    zones = []
    for f in res_by_layer.get(LAYER_ZONE, []):
        geom = f.get("geometry")
        if not geom or "rings" not in geom:
            continue
        try:
            z_poly = Polygon(geom["rings"][0])
            if parcel_poly.intersects(z_poly):
                inter = parcel_poly.intersection(z_poly)
                if inter.area > min_area_thresh:
                    attrs = f.get("attributes", {})
                    zcode = attrs.get("ZONE_CODE2") or attrs.get("Zone_Code2") or "Unknown"
                    zones.append({
                        "zone": str(zcode),
                        "overlap_sqm": round(inter.area, 2),
                        "overlap_percent": round((inter.area / parcel_poly.area) * 100, 2),
                    })
        except Exception:
            continue
    zones.sort(key=lambda z: z["overlap_sqm"], reverse=True)
    primary_zone = zones[0]["zone"] if zones else "Unknown"

    # 5. Process Metro Buffer (Layer 1550)
    metro_buffer = "NO"
    for f in res_by_layer.get(LAYER_METRO, []):
        geom = f.get("geometry")
        if not geom or "rings" not in geom:
            continue
        try:
            mb_poly = Polygon(geom["rings"][0])
            if parcel_poly.intersects(mb_poly):
                metro_buffer = "YES (Metro Buffer Zone)"
                break
        except Exception:
            continue

    # 6. Process CRZ (Layers 14, 1264, 1548)
    crz_status = "NO (Outside CRZ Buffer)"
    for crz_lid in CRZ_LAYER_IDS:
        for f in res_by_layer.get(crz_lid, []):
            geom = f.get("geometry")
            if not geom or "rings" not in geom:
                continue
            try:
                crz_poly = Polygon(geom["rings"][0])
                if parcel_poly.intersects(crz_poly):
                    cat = f.get("attributes", {}).get("CATEGORY") or f.get("attributes", {}).get("CLASS") or ""
                    tier = str(cat).replace("CRZ", "").replace("ZONE", "").strip() or "YES"
                    label = tier if tier.upper().startswith("CRZ") else f"CRZ {tier}"
                    crz_status = f"YES ({label})"
                    break
            except Exception:
                continue
        if crz_status.startswith("YES"):
            break

    all_encumbered_polys = res_polys + des_polys
    if all_encumbered_polys:
        union_encumbered = unary_union(all_encumbered_polys)
        encumbered_area_sqm = round(union_encumbered.area, 2)
        encumbered_percent = round((union_encumbered.area / parcel_poly.area) * 100, 2)
    else:
        encumbered_area_sqm = 0.0
        encumbered_percent = 0.0

    net_unencumbered_sqm = max(0.0, round(parcel_poly.area - encumbered_area_sqm, 2))
    net_unencumbered_percent = max(0.0, round(100.0 - encumbered_percent, 2))

    return {
        "primary_zone": primary_zone,
        "zones": zones,
        "reservations": reservations,
        "designations": designations,
        "modifications": modifications,
        "metro_buffer": metro_buffer,
        "crz_status": crz_status,
        "encumbered_area_sqm": encumbered_area_sqm,
        "encumbered_percent": encumbered_percent,
        "net_unencumbered_sqm": net_unencumbered_sqm,
        "net_unencumbered_percent": net_unencumbered_percent,
        "warnings": warnings,
    }
