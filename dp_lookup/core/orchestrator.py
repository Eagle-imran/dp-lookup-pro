"""
High-Speed Async Plot Lookup Orchestrator.
"""
import asyncio
import io
import math
import os
import sys
import time
from typing import Any, Callable, Dict, Optional

import httpx
import qrcode

from dp_lookup.clients.arcgis import (
    fetch_tile_cached,
    identify_payload,
    map_export_params,
    planning_layers,
    query_spatial_planning_layers,
)
from dp_lookup.clients.cache import (
    read_cache_entry,
    sanitize_query_value,
    usable_json,
    write_cache_entry,
)
from dp_lookup.core.constants import (
    _CTS_RE,
    _VILLAGE_RE,
    CRZ_LAYER_IDS,
    DEFAULT_CACHE_TTL_SECONDS,
    MCGM_VILLAGES,
    NEIGHBOUR_LAYERS,
    ROAD_LAYERS,
    SERVER_URL,
    WEB_MERCATOR_R,
)
from dp_lookup.core.geometry import (
    latlon_to_tile,
    nearest_road_geoms,
    neighbour_probe_points,
    prepare_geometry,
    resolve_plot_area,
    road_probe_points,
    tile_to_latlon,
)
from dp_lookup.core.planning_status import (
    bundle_folder_name,
    crz_flag_from,
    derive_status,
    select_road,
)
from dp_lookup.exporters.dxf import export_dxf
from dp_lookup.exporters.excel import update_excel_register
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.html_map import export_html_map
from dp_lookup.exporters.kml import export_kml
from dp_lookup.exporters.pdf import build_pdf_doc
from dp_lookup.renderers.map_overlay import render_dp_map
from dp_lookup.renderers.satellite import stitch_satellite


async def lookup_plot_pro(
    village: str,
    cts_number: str,
    output_dir: str = "./output",
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    timeout_seconds: float = 20.0,
    on_data: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    Ultra-Fast Enterprise DP Plot Lookup Pro Tool (AutoCAD DXF + GeoJSON + KML Exports).
    """
    t_start = time.perf_counter()
    from dp_lookup.cli import suggest_villages

    try:
        safe_village = sanitize_query_value(village, _VILLAGE_RE, "village", 64)
        safe_cts = sanitize_query_value(cts_number, _CTS_RE, "cts_number", 32)
    except ValueError as exc:
        return {"error": str(exc), "suggestions": suggest_villages(village)}

    village_upper = safe_village.upper()
    cache_key = f"{village_upper}:{safe_cts}"
    warnings: list = []
    notes: list = []

    os.makedirs(output_dir, exist_ok=True)

    if use_cache:
        cached = read_cache_entry(output_dir, cache_key, ttl_seconds=cache_ttl_seconds)
        if cached is not None:
            if on_data is not None:
                try:
                    on_data(cached)
                except Exception:
                    pass
            return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer",
        "Origin": "https://agsmaps.mcgm.gov.in"
    }

    limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
    register_path = os.path.join(output_dir, "dp-lookups.xlsx")

    async with httpx.AsyncClient(headers=headers, limits=limits, http2=True, timeout=timeout_seconds, verify=False) as client:
        # Step 1: Base Cadastral Query
        query_params = {
            "where": f"VILLAGE='{village_upper}' AND CTS_CS_NO='{safe_cts}'",
            "outFields": "WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS,SHAPE.AREA",
            "returnGeometry": "true",
            "outSR": "102100",
            "f": "json",
        }

        try:
            r = await client.get(f"{SERVER_URL}/13/query", params=query_params)
        except httpx.HTTPError as exc:
            detail = str(exc).strip() or type(exc).__name__
            return {"error": f"MCGM server error while querying Layer 13 ({detail})."}

        data = usable_json(r)
        if data is None:
            return {
                "error": (
                    f"Cadastral query to MCGM Layer 13 failed (status {getattr(r, 'status_code', 'unknown')}). "
                    "The server may be down or rejecting requests. Please retry."
                )
            }

        if not data.get("features"):
            alt_sql = f"VILLAGE='{village_upper}' AND CTS_CS_NO LIKE '{safe_cts}%'"
            try:
                r_alt = await client.get(f"{SERVER_URL}/13/query", params={**query_params, "where": alt_sql})
                data_alt = usable_json(r_alt)
                if data_alt and data_alt.get("features"):
                    data = data_alt
            except Exception:
                pass

        if not data.get("features"):
            if village_upper in MCGM_VILLAGES:
                msg = (
                    f"Village '{village_upper}' is valid, but it has no plot "
                    f"numbered '{safe_cts}'. Check the CTS number - suffixes and "
                    "slashes matter ('748A' and '748' are different plots, as are "
                    "'16/738' and '16-738')."
                )
            else:
                msg = f"'{village_upper}' is not a valid MCGM village name."
            return {"error": msg, "suggestions": suggest_villages(village_upper)}

        feature = data["features"][0]
        attrs = feature["attributes"]
        rings = feature["geometry"]["rings"]

        area = resolve_plot_area(attrs)
        area_sqm, area_source = area["area_sqm"], area["area_source"]
        if area["note"]:
            notes.append(area["note"])
        attrs["AREA_APP_SQ_MTRS"] = area_sqm

        geom = prepare_geometry(rings)
        cx, cy = geom["cx"], geom["cy"]
        mcx, mcy = geom["mcx"], geom["mcy"]
        xs, ys, d = geom["xs"], geom["ys"], geom["d"]
        lat, lon = geom["lat"], geom["lon"]
        wgs_rings = geom["wgs_rings"]
        R = WEB_MERCATOR_R

        query_dir = os.path.join(output_dir, bundle_folder_name(safe_village, safe_cts))
        os.makedirs(query_dir, exist_ok=True)

        crz_restriction_layer_ids = list(CRZ_LAYER_IDS)

        ident_task = client.post(
            f"{SERVER_URL}/identify",
            data=identify_payload(cx, cy, planning_layers(crz_restriction_layer_ids),
                                  mcx, mcy, d, tolerance=30, return_geometry=False),
        )

        half = max(70, max(max(xs) - min(xs), max(ys) - min(ys)) * 0.9)
        W, H = 1000, 1000
        x0, x1 = mcx - half, mcx + half
        y0, y1 = mcy - half, mcy + half

        dp_snap_task = client.get(
            f"{SERVER_URL}/export",
            params=map_export_params(x0, y0, x1, y1, W, H),
        )

        sem = asyncio.Semaphore(6)

        async def _post_sem(url: str, data: dict):
            async with sem:
                return await client.post(url, data=data)

        road_sample_pts = road_probe_points(rings[0], mcx, mcy, xs, ys)
        road_tasks = [
            _post_sem(f"{SERVER_URL}/identify",
                      identify_payload(px, py, ROAD_LAYERS, mcx, mcy, d,
                                       tolerance=50, return_geometry=True))
            for px, py in road_sample_pts
        ]

        neighbor_sample_pts = neighbour_probe_points(mcx, mcy, d)
        neighbor_tasks = [
            _post_sem(f"{SERVER_URL}/identify",
                      identify_payload(px, py, NEIGHBOUR_LAYERS, mcx, mcy, d,
                                       tolerance=30, return_geometry=True))
            for px, py in neighbor_sample_pts
        ]

        zoom = 18
        xtile, ytile = latlon_to_tile(lat, lon, zoom)
        grid_dim = 3
        half_dim = grid_dim // 2
        sat_tile_tasks = []
        sat_coords = []
        for dy in range(-half_dim, half_dim + 1):
            for dx in range(-half_dim, half_dim + 1):
                tx, ty = xtile + dx, ytile + dy
                sat_tile_tasks.append(fetch_tile_cached(client, zoom, ty, tx))
                sat_coords.append((dx + half_dim, dy + half_dim))

        slow_group = asyncio.gather(
            dp_snap_task,
            asyncio.gather(*sat_tile_tasks, return_exceptions=True),
        )

        spatial_plan_task = query_spatial_planning_layers(client, rings)

        fast_results = await asyncio.gather(
            ident_task,
            spatial_plan_task,
            asyncio.gather(*road_tasks, return_exceptions=True),
            asyncio.gather(*neighbor_tasks, return_exceptions=True),
            return_exceptions=True
        )

        ident_resp = fast_results[0]
        spatial_plan = fast_results[1]
        road_resps = fast_results[2]
        neighbor_resps = fast_results[3]

        # Parse Roads
        road_map = {}
        road_geoms = []
        road_failures = 0
        if isinstance(road_resps, Exception):
            road_failures = len(road_sample_pts)
        else:
            for r in road_resps:
                j = usable_json(r)
                if j is None:
                    road_failures += 1
                    continue
                for f in j.get('features', []):
                    r_attrs = f.get('attributes', {})
                    r_name = r_attrs.get('ROAD_NAME') or r_attrs.get('Roadname') or r_attrs.get('NAME') or r_attrs.get('Name') or r_attrs.get('TYPE_') or r_attrs.get('Type')
                    r_w = r_attrs.get('WIDTH_RL') or r_attrs.get('WIDTH') or r_attrs.get('Width')
                    if r_name or r_w:
                        road_map[f"{r_name}|{r_w}"] = {'name': r_name or 'Road', 'width': r_w or 'N/A'}
                for item in j.get('results', []):
                    r_attrs = item.get('attributes', {})
                    r_name = r_attrs.get('ROAD_NAME') or r_attrs.get('Roadname') or r_attrs.get('NAME') or r_attrs.get('Name') or r_attrs.get('TYPE_') or r_attrs.get('Type')
                    r_w = r_attrs.get('WIDTH_RL') or r_attrs.get('WIDTH') or r_attrs.get('Width')
                    if r_name or r_w:
                        road_map[f"{r_name}|{r_w}"] = {'name': r_name or 'Road', 'width': r_w or 'N/A'}
                    r_geom = item.get('geometry', {}) or {}
                    for part in (r_geom.get('paths') or []) + (r_geom.get('rings') or []):
                        if len(part) >= 2:
                            road_geoms.append([
                                [round((pt[0] / R) * 180, 7),
                                 round((math.atan(math.exp(pt[1] / R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi, 7)]
                                for pt in part
                            ])

        if road_failures:
            warnings.append(f"{road_failures} of {len(road_sample_pts)} road probes failed; abutting road may be incomplete")

        chosen_road = select_road(road_map)
        road_name, road_width = chosen_road["name"], chosen_road["width"]

        # Parse Neighbors
        neighbors_map = {}
        neighbor_failures = 0
        if isinstance(neighbor_resps, Exception):
            neighbor_failures = len(neighbor_sample_pts)
        else:
            for r in neighbor_resps:
                nj = usable_json(r)
                if nj is None:
                    neighbor_failures += 1
                    continue
                for item in nj.get('results', []):
                    n_attrs = item.get('attributes', {})
                    c_no = n_attrs.get('cts_cs_no') or n_attrs.get('CTS_CS_NO')
                    n_area = n_attrs.get('area_app_sq_mtrs') or n_attrs.get('AREA_APP_SQ_MTRS')
                    v_name = n_attrs.get('village') or n_attrs.get('VILLAGE')
                    n_geom = item.get('geometry', {}) or {}
                    n_rings_raw = n_geom.get('rings') or []
                    n_wgs_rings = [[[round((pt[0] / R) * 180, 7),
                                     round((math.atan(math.exp(pt[1] / R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi, 7)]
                                    for pt in ring]
                                   for ring in n_rings_raw]
                    if c_no and str(c_no).strip() != str(safe_cts).strip():
                        neighbors_map[str(c_no)] = {
                            "cts_no": str(c_no),
                            "village": str(v_name or safe_village),
                            "area_sqm": str(n_area) if n_area is not None else "N/A",
                            "rings": n_wgs_rings,
                        }

        if neighbor_failures:
            warnings.append(f"{neighbor_failures} of {len(neighbor_sample_pts)} neighbour probes failed; adjoining plots list may be incomplete")

        neighbors = list(neighbors_map.values())

        # Parse Planning Data
        ident_json = usable_json(ident_resp)
        if isinstance(spatial_plan, Exception) and ident_json is None:
            return {
                "error": (
                    "Planning data could not be retrieved from the MCGM map server "
                    "(the identify/spatial request failed or timed out). No report was generated, "
                    "because a partial one would understate zoning, reservations and CRZ status. "
                    "Please retry."
                ),
                "partial_data": {
                    "village": village_upper,
                    "cts_no": str(safe_cts),
                    "ward": str(attrs.get("WARD")),
                    "area_sqm": attrs.get("AREA_APP_SQ_MTRS"),
                },
            }

        if isinstance(spatial_plan, dict):
            reservations = spatial_plan.get("reservations", [])
            designations = spatial_plan.get("designations", [])
            modifications = spatial_plan.get("modifications", [])
            zones = spatial_plan.get("zones", [])
            zone = spatial_plan.get("primary_zone", "Unknown")
            metro_buffer_flag = spatial_plan.get("metro_buffer", "NO")
            crz_buffer_flag = spatial_plan.get("crz_status", "NO (Outside CRZ Buffer)")
            encumbered_percent = spatial_plan.get("encumbered_percent", 0.0)

            if encumbered_percent <= 0.0:
                encumbered_area_sqm = 0.0
                net_unencumbered_sqm = float(area_sqm)
                net_unencumbered_percent = 100.0
            else:
                encumbered_area_sqm = round(float(area_sqm) * (encumbered_percent / 100.0), 2)
                net_unencumbered_sqm = max(0.0, round(float(area_sqm) - encumbered_area_sqm, 2))
                net_unencumbered_percent = max(0.0, round(100.0 - encumbered_percent, 2))

            for res_item in reservations:
                res_item["overlap_sqm"] = round(float(area_sqm) * (res_item.get("overlap_percent", 0.0) / 100.0), 2)
            for des_item in designations:
                des_item["overlap_sqm"] = round(float(area_sqm) * (des_item.get("overlap_percent", 0.0) / 100.0), 2)

            for w in spatial_plan.get("warnings", []):
                warnings.append(w)
        else:
            results = ident_json.get("results", []) if ident_json else []
            z_item = next((r for r in results if r.get("layerId") == 0), None)
            rv_item = next((r for r in results if r.get("layerId") == 46), None)
            des_item = next((r for r in results if r.get("layerId") == 47), None)
            mod_item = next((r for r in results if r.get("layerId") == 192), None)
            metro_item = next((r for r in results if r.get("layerId") == 1550), None)
            crz_item = next((r for r in results if r.get("layerId") in crz_restriction_layer_ids), None)

            zone = z_item["attributes"]["Zone_Code2"] if z_item else "Unknown"
            zones = [{"zone": zone, "overlap_sqm": area_sqm, "overlap_percent": 100.0}] if zone != "Unknown" else []
            reservations = []
            if rv_item:
                r_attrs = rv_item.get("attributes", {})
                reservations.append({
                    "code": str(r_attrs.get("NEW_RES_CODE_31") or "None"),
                    "type": str(r_attrs.get("NEW_RES_MAINTYPE_31") or "None"),
                    "description": str(r_attrs.get("DISCRIPTION") or "Reservation").strip(),
                    "u_r_id": str(r_attrs.get("U_R_ID") or "N/A"),
                    "overlap_sqm": area_sqm or 0.0,
                    "total_res_sqm": area_sqm or 0.0,
                    "overlap_percent": 100.0,
                    "wgs_rings": wgs_rings,
                    "raw_attributes": r_attrs,
                })

            designations = []
            if des_item:
                d_attrs = des_item.get("attributes", {})
                designations.append({
                    "code": str(d_attrs.get("NEW_DES_CODE_31") or "None"),
                    "type": str(d_attrs.get("NEW_DES_MAINTYPE_31") or "None"),
                    "description": str(d_attrs.get("DISCRIPTION") or "Designation").strip(),
                    "u_d_id": str(d_attrs.get("U_D_ID") or "N/A"),
                    "overlap_sqm": area_sqm or 0.0,
                    "total_des_sqm": area_sqm or 0.0,
                    "overlap_percent": 100.0,
                    "wgs_rings": wgs_rings,
                    "raw_attributes": d_attrs,
                })

            modifications = []
            if mod_item:
                m_attrs = mod_item.get("attributes", {})
                modifications.append({
                    "approval_no": str(m_attrs.get("APPROVAL_NO") or "DP Mod"),
                    "details": str(m_attrs.get("LABEL to Display") or "Modified"),
                    "document_link": str(m_attrs.get("Approval Documents") or "None"),
                    "overlap_sqm": area_sqm or 0.0,
                    "overlap_percent": 100.0,
                    "raw_attributes": m_attrs,
                })

            metro_buffer_flag = "YES (Metro Buffer Zone)" if metro_item else "NO"
            crz_buffer_flag = crz_flag_from(crz_item)
            encumbered_percent = 100.0 if (reservations or designations) else 0.0
            encumbered_area_sqm = area_sqm if (reservations or designations) else 0.0
            net_unencumbered_sqm = 0.0 if (reservations or designations) else (area_sqm or 0.0)
            net_unencumbered_percent = 0.0 if (reservations or designations) else 100.0

        if ident_json:
            for r in ident_json.get("results", []):
                lid = r.get("layerId")
                r_attrs = r.get("attributes", {})
                if lid == 0 and zone == "Unknown":
                    zone = r_attrs.get("Zone_Code2") or r_attrs.get("ZONE_CODE2") or "Unknown"
                elif lid == 46 and not reservations:
                    rcode = r_attrs.get("NEW_RES_CODE_31") or r_attrs.get("FINAL_RES_CODE")
                    if rcode and rcode != "None":
                        reservations.append({
                            "code": str(rcode),
                            "type": str(r_attrs.get("NEW_RES_MAINTYPE_31") or "None"),
                            "description": str(r_attrs.get("DISCRIPTION") or "Reservation").strip(),
                            "u_r_id": str(r_attrs.get("U_R_ID") or "N/A"),
                            "overlap_sqm": area_sqm or 0.0,
                            "total_res_sqm": area_sqm or 0.0,
                            "overlap_percent": 100.0,
                            "wgs_rings": wgs_rings,
                            "raw_attributes": r_attrs,
                        })
                elif lid == 47 and not designations:
                    dcode = r_attrs.get("NEW_DES_CODE_31") or r_attrs.get("FINAL_DES_CODE")
                    if dcode and dcode != "None":
                        designations.append({
                            "code": str(dcode),
                            "type": str(r_attrs.get("NEW_DES_MAINTYPE_31") or "None"),
                            "description": str(r_attrs.get("DISCRIPTION") or "Designation").strip(),
                            "u_d_id": str(r_attrs.get("U_D_ID") or "N/A"),
                            "overlap_sqm": area_sqm or 0.0,
                            "total_des_sqm": area_sqm or 0.0,
                            "overlap_percent": 100.0,
                            "wgs_rings": wgs_rings,
                            "raw_attributes": r_attrs,
                        })
                elif lid == 192 and not modifications:
                    appr = r_attrs.get("APPROVAL_NO")
                    if appr and appr != "None":
                        modifications.append({
                            "approval_no": str(appr),
                            "details": str(r_attrs.get("LABEL to Display") or "Modified"),
                            "document_link": str(r_attrs.get("Approval Documents") or "None"),
                            "overlap_sqm": area_sqm or 0.0,
                            "overlap_percent": 100.0,
                            "raw_attributes": r_attrs,
                        })

        res_code = reservations[0]["code"] if reservations else "None"
        res_type = reservations[0]["type"] if reservations else "None"
        des_code = designations[0]["code"] if designations else "None"
        des_desc = designations[0]["description"] if designations else "None"
        mod_approval = modifications[0]["approval_no"] if modifications else "None"
        mod_label = modifications[0]["details"] if modifications else "None"
        mod_doc = modifications[0]["document_link"] if modifications else "None"

        status = derive_status(
            mod_item={"approval": mod_approval} if modifications else None,
            des_item={"code": des_code} if designations else None,
            rv_item={"code": res_code} if reservations else None,
            des_desc=des_desc,
            des_code=des_code,
            res_code=res_code,
            res_type=res_type,
            mod_approval=mod_approval,
            reservations=reservations,
            designations=designations,
            modifications=modifications,
            encumbered_percent=encumbered_percent,
            encumbered_area_sqm=encumbered_area_sqm,
            total_area_sqm=area_sqm,
            net_unencumbered_sqm=net_unencumbered_sqm,
        )
        status_badge, status_summary = status["badge"], status["summary"]

        ward_clean = str(attrs['WARD']).replace('/', '-').replace('\\', '-')
        cts_clean = str(safe_cts).replace('/', '-').replace('\\', '-')
        village_clean = safe_village.lower().strip().replace('/', '-').replace('\\', '-').replace(' ', '_')

        map_link = (
            f"https://mcgm.maps.arcgis.com/apps/webappviewer/index.html?"
            f"id=67118c3502fd492e94680d10e77ec112&marker={lon},{lat},4326,{safe_cts}%20{safe_village}"
            f"&center={lon},{lat}&level=19"
        )

        geojson_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}.geojson"
        geojson_path = os.path.join(query_dir, geojson_fname)
        dxf_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}.dxf"
        dxf_path = os.path.join(query_dir, dxf_fname)
        kml_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}.kml"
        kml_path = os.path.join(query_dir, kml_fname)
        dp_snapshot_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}_hd.png"
        dp_snapshot_path = os.path.join(query_dir, dp_snapshot_fname)
        sat_snapshot_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}_satellite.png"
        sat_snapshot_path = os.path.join(query_dir, sat_snapshot_fname)
        pdf_fname = f"dp_report_{ward_clean}_{cts_clean}_{village_clean}.pdf"
        pdf_path = os.path.join(query_dir, pdf_fname)
        html_map_fname = f"plot_map_{ward_clean}_{cts_clean}_{village_clean}.html"
        html_map_path = os.path.join(query_dir, html_map_fname)

        export_props = {
            "village": safe_village.upper(),
            "cts_no": str(safe_cts),
            "ward": str(attrs['WARD']),
            "type": str(attrs['TYPE']),
            "area_sqm": attrs['AREA_APP_SQ_MTRS'],
            "zone": zone,
            "status_badge": status_badge,
            "reservation_code": res_code,
            "reservation_type": res_type,
            "designation_description": des_desc,
            "modification_approval": mod_approval,
            "crz_buffer_flag": crz_buffer_flag,
            "metro_buffer_flag": metro_buffer_flag,
            "abutting_road": road_name,
            "road_width": road_width,
            "area_source": area_source,
            "adjoining_cts_plots_count": len(neighbors),
            "map_link": map_link,
            "reservations": reservations,
            "designations": designations,
            "encumbered_area_sqm": encumbered_area_sqm,
            "encumbered_percent": encumbered_percent,
            "net_unencumbered_sqm": net_unencumbered_sqm,
            "net_unencumbered_percent": net_unencumbered_percent,
        }

        export_geojson(wgs_rings, export_props, geojson_path)
        export_dxf(wgs_rings, export_props, dxf_path, neighbors=neighbors,
                   roads=nearest_road_geoms(road_geoms, wgs_rings),
                   reservations=reservations, designations=designations)
        export_kml(wgs_rings, export_props, kml_path)
        export_html_map(wgs_rings, export_props, html_map_path, neighbors=neighbors,
                        roads=nearest_road_geoms(road_geoms, wgs_rings),
                        reservations=reservations, designations=designations)

        def _compose_result(exec_ms: float, pending: bool) -> Dict[str, Any]:
            return {
                "plot_identity": {
                    "village": safe_village.upper(), "cts_no": str(safe_cts),
                    "ward": str(attrs["WARD"]), "type": str(attrs["TYPE"]),
                    "area_sqm": area_sqm, "area_source": area_source,
                    "coordinates_wgs84": {"latitude": lat, "longitude": lon},
                },
                "planning_remarks": {
                    "status_badge": status_badge, "status_summary": status_summary, "zone": zone,
                    "zones": zones,
                    "reservation": {"code": res_code, "type": res_type},
                    "reservations": reservations,
                    "designation": {"code": des_code, "description": des_desc},
                    "designations": designations,
                    "dp_modification": {"approval_no": mod_approval, "details": mod_label,
                                        "document_link": mod_doc},
                    "dp_modifications": modifications,
                    "encumbrance": {
                        "encumbered_area_sqm": encumbered_area_sqm,
                        "encumbered_percent": encumbered_percent,
                        "net_unencumbered_sqm": net_unencumbered_sqm,
                        "net_unencumbered_percent": net_unencumbered_percent,
                    },
                },
                "regulatory_and_infrastructure": {
                    "crz_status": crz_buffer_flag, "metro_buffer": metro_buffer_flag,
                    "abutting_road": {"name": road_name, "width": road_width},
                },
                "spatial_cluster": {
                    "adjoining_plots_count": len(neighbors),
                    "adjoining_cts_plots": [{k: v for k, v in n.items() if k != 'rings'}
                                            for n in neighbors],
                },
                "export_files": {
                    "bundle_folder": query_dir, "pdf_report": pdf_path,
                    "hd_dp_map": dp_snapshot_path, "satellite_view": sat_snapshot_path,
                    "autocad_dxf": dxf_path, "autocad_geojson": geojson_path,
                    "google_earth_kml": kml_path, "interactive_html_map": html_map_path,
                    "master_excel_register": register_path,
                },
                "metadata": {
                    "source": "MCGM SDP 2014-34",
                    "lookup_datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "execution_time_ms": exec_ms,
                    "cached_result": False,
                    "complete": not warnings,
                    "documents_pending": pending,
                    "warnings": list(warnings),
                    "notes": list(notes),
                    "interactive_web_map": map_link,
                },
            }

        if on_data is not None:
            fast_ms = round((time.perf_counter() - t_start) * 1000, 1)
            try:
                on_data(_compose_result(fast_ms, pending=True))
            except Exception as exc:
                print(f"[dp-lookup-pro] on_data callback raised: {exc}", file=sys.stderr)

        slow_results = await slow_group
        dp_snap_resp = slow_results[0]
        sat_tile_bytes = slow_results[1]

        dp_map_ok = (
            not isinstance(dp_snap_resp, Exception)
            and getattr(dp_snap_resp, "status_code", None) == 200
            and dp_snap_resp.headers.get("content-type", "").startswith("image")
        )
        if not dp_map_ok:
            warnings.append("DP base map could not be fetched; the map image is a blank placeholder")

        final_dp_img = render_dp_map(
            dp_snap_resp.content if dp_map_ok else None,
            rings,
            bbox=(x0, y0, x1, y1),
            size=(W, H),
            labels={"cts": safe_cts, "village": safe_village.upper(), "ward": attrs["WARD"],
                    "zone": zone, "area": attrs["AREA_APP_SQ_MTRS"],
                    "status": status_badge[:30]},
        )

        tiles = [] if isinstance(sat_tile_bytes, Exception) else list(sat_tile_bytes)
        missing_tiles = (len(sat_coords) if isinstance(sat_tile_bytes, Exception)
                         else sum(1 for b in tiles if isinstance(b, Exception) or not b))
        if missing_tiles:
            warnings.append(f"{missing_tiles} of {len(sat_coords)} satellite tiles failed to load")

        top_lat, left_lon = tile_to_latlon(xtile - half_dim, ytile - half_dim, zoom)
        bot_lat, right_lon = tile_to_latlon(xtile + half_dim + 1, ytile + half_dim + 1, zoom)

        final_sat = stitch_satellite(
            tiles or [None] * len(sat_coords),
            sat_coords,
            grid_dim,
            wgs_rings,
            bounds=(top_lat, left_lon, bot_lat, right_lon),
            labels={"cts": safe_cts, "village": safe_village.upper(), "ward": attrs["WARD"],
                    "lat": lat, "lon": lon, "neighbours": len(neighbors)},
        )

        def save_images():
            final_dp_img.convert("RGB").save(dp_snapshot_path, "PNG", compress_level=1)
            final_sat.convert("RGB").save(sat_snapshot_path, "PNG", compress_level=1)

        await asyncio.to_thread(save_images)

        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(map_link)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_bytes = io.BytesIO()
        qr_img.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)

        await asyncio.to_thread(
            build_pdf_doc,
            pdf_path, status_badge, status_summary, safe_village, attrs, safe_cts, zone, des_desc, des_code, mod_approval, mod_label, crz_buffer_flag, metro_buffer_flag, road_name, road_width, dp_snapshot_path, qr_bytes, map_link, sat_snapshot_path, neighbors,
            ("Approved cadastral area (MCGM record)"
             if area_source.startswith("approved")
             else "DERIVED from plot boundary - no approved area on MCGM record"),
            res_code=res_code,
            res_type=res_type,
            reservations=reservations,
            designations=designations,
            encumbered_percent=encumbered_percent,
            encumbered_area_sqm=encumbered_area_sqm,
            net_unencumbered_sqm=net_unencumbered_sqm,
        )

        update_excel_register(
            register_path=register_path,
            attrs=attrs,
            village=safe_village,
            cts_number=safe_cts,
            zone=zone,
            status_badge=status_badge,
            res_code=res_code,
            res_type=res_type,
            des_code=des_code,
            des_desc=des_desc,
            mod_approval=mod_approval,
            mod_label=mod_label,
            mod_doc=mod_doc,
            crz_buffer_flag=crz_buffer_flag,
            metro_buffer_flag=metro_buffer_flag,
            road_name=road_name,
            road_width=road_width,
            neighbors=neighbors,
            dp_snapshot_fname=dp_snapshot_fname,
            sat_snapshot_fname=sat_snapshot_fname,
            pdf_fname=pdf_fname,
            dxf_fname=dxf_fname,
            geojson_fname=geojson_fname,
            kml_fname=kml_fname,
            map_link=map_link,
            reservations=reservations,
            designations=designations,
        )

        t_end = time.perf_counter()
        exec_ms = round((t_end - t_start) * 1000, 1)

        result_dict = _compose_result(exec_ms, pending=False)

        if warnings:
            print(f"[dp-lookup-pro] WARNING: result incomplete, not cached - {'; '.join(warnings)}", file=sys.stderr)
        else:
            write_cache_entry(output_dir, cache_key, result_dict)

        return result_dict
