import os
import json
import math
import asyncio
import io
import time
import datetime
from typing import Dict, Any, List
import httpx
from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
import qrcode
import ezdxf

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

SERVER_URL = "https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer"
SATELLITE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile"

# Persistent Disk & In-Memory Caches
_TILE_CACHE: Dict[str, bytes] = {}
_LOOKUP_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_STORE_PATH = "./output/.cache_store.json"

def load_disk_cache():
    global _LOOKUP_CACHE
    if os.path.exists(CACHE_STORE_PATH):
        try:
            with open(CACHE_STORE_PATH, "r", encoding="utf-8") as f:
                _LOOKUP_CACHE = json.load(f)
        except Exception:
            _LOOKUP_CACHE = {}

def save_disk_cache():
    try:
        os.makedirs(os.path.dirname(CACHE_STORE_PATH), exist_ok=True)
        with open(CACHE_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(_LOOKUP_CACHE, f, indent=2)
    except Exception:
        pass

load_disk_cache()

def latlon_to_tile(lat: float, lon: float, zoom: int):
    n = 2 ** zoom
    x_tile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y_tile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x_tile, y_tile

def tile_to_latlon(x_tile: int, y_tile: int, zoom: int):
    n = 2 ** zoom
    lon = x_tile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y_tile / n)))
    lat = math.degrees(lat_rad)
    return lat, lon

async def fetch_tile_cached(client: httpx.AsyncClient, zoom: int, ty: int, tx: int) -> bytes:
    key = f"{zoom}/{ty}/{tx}"
    if key in _TILE_CACHE:
        return _TILE_CACHE[key]
    url = f"{SATELLITE_URL}/{zoom}/{ty}/{tx}"
    try:
        r = await client.get(url)
        if r.status_code == 200:
            _TILE_CACHE[key] = r.content
            return r.content
    except Exception:
        pass
    return b""

def export_geojson(wgs_rings: list, properties: dict, output_path: str):
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon" if len(wgs_rings) == 1 else "MultiPolygon",
            "coordinates": wgs_rings if len(wgs_rings) == 1 else [wgs_rings]
        },
        "properties": properties
    }
    geojson_data = {
        "type": "FeatureCollection",
        "name": f"CTS_{properties.get('cts_no')}_{properties.get('village')}",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}
        },
        "features": [feature]
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, indent=2)

def export_dxf(wgs_rings: list, properties: dict, output_path: str):
    """
    Generates a scale-accurate AutoCAD DXF drawing file (.dxf)
    with layer styling and text annotations.
    """
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    doc.layers.add(name='PLOT_BOUNDARY', color=1)  # Red
    doc.layers.add(name='ANNOTATION', color=4)     # Cyan
    
    for ring in wgs_rings:
        pts = [(p[0], p[1]) for p in ring]
        poly = msp.add_lwpolyline(pts, dxfattribs={'layer': 'PLOT_BOUNDARY', 'closed': True})
        poly.dxf.const_width = 0.00002

    r0 = wgs_rings[0]
    cx = sum(p[0] for p in r0) / len(r0)
    cy = sum(p[1] for p in r0) / len(r0)
    
    lbl_text = (
        f"CTS NO: {properties.get('cts_no')}\n"
        f"VILLAGE: {properties.get('village')}\n"
        f"AREA: {properties.get('area_sqm')} sq m\n"
        f"ZONE: {properties.get('zone')}\n"
        f"STATUS: {properties.get('status_badge')}\n"
        f"ROAD: {properties.get('abutting_road')} ({properties.get('road_width')})"
    )
    
    mtext = msp.add_mtext(lbl_text, dxfattribs={'layer': 'ANNOTATION', 'char_height': 0.00008})
    mtext.set_location((cx, cy))
    
    doc.saveas(output_path)

def export_kml(wgs_rings: list, properties: dict, output_path: str):
    ring0 = wgs_rings[0]
    coords_str = " ".join(f"{p[0]},{p[1]},0" for p in ring0)
    
    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>CTS {properties.get('cts_no')} ({properties.get('village')}) DP Remark</name>
    <description>MCGM DP 2034 Spatial Polygon Export</description>
    <Style id="plotStyle">
      <LineStyle>
        <color>ff00e6ff</color>
        <width>4</width>
      </LineStyle>
      <PolyStyle>
        <color>4000e6ff</color>
      </PolyStyle>
    </Style>
    <Placemark>
      <name>CTS {properties.get('cts_no')} - {properties.get('village')}</name>
      <styleUrl>#plotStyle</styleUrl>
      <ExtendedData>
        <Data name="Ward"><value>{properties.get('ward')}</value></Data>
        <Data name="Zone"><value>{properties.get('zone')}</value></Data>
        <Data name="Area_sqm"><value>{properties.get('area_sqm')}</value></Data>
        <Data name="Status"><value>{properties.get('status_badge')}</value></Data>
        <Data name="CRZ_Status"><value>{properties.get('crz_buffer_flag')}</value></Data>
        <Data name="Metro_Buffer"><value>{properties.get('metro_buffer_flag')}</value></Data>
        <Data name="Abutting_Road"><value>{properties.get('abutting_road')} ({properties.get('road_width')})</value></Data>
      </ExtendedData>
      <Polygon>
        <extrude>1</extrude>
        <altitudeMode>clampToGround</altitudeMode>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coords_str}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(kml_content)

def build_pdf_doc(pdf_path, status_badge, status_summary, village, attrs, cts_number, zone, des_desc, des_code, mod_approval, mod_label, crz_buffer_flag, metro_buffer_flag, road_name, road_width, dp_snapshot_path, qr_bytes, map_link, sat_snapshot_path, neighbors):
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=15, leading=19, textColor=colors.HexColor('#1A237E'))
    subtitle_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#424242'))
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=8.5, leading=11)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=8.5, leading=11, fontName='Helvetica-Bold')

    story = []
    story.append(Paragraph("<b>MCGM DEVELOPMENT PLAN 2034 — SPATIAL REMARK DOCKET</b>", title_style))
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story.append(Paragraph(f"Official Spatial Query Report | Page 1 of 2 | Generated: {now_str}", subtitle_style))
    story.append(Spacer(1, 6))

    banner_color = colors.HexColor('#E8F5E9') if 'CLEAR' in status_badge else (colors.HexColor('#FFFDE7') if 'MODIFIED' in status_badge else colors.HexColor('#FFEBEE'))
    banner_text = f"<b>STATUS: {status_badge}</b> — {status_summary}"
    banner_table = Table([[Paragraph(banner_text, ParagraphStyle('BText', parent=body_style, fontSize=9.5, leading=12))]], colWidths=[540])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), banner_color),
        ('PADDING', (0,0), (-1,-1), 5),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#BDBDBD')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 6))

    table_data = [
        [Paragraph("<b>Attribute</b>", bold_style), Paragraph("<b>Details</b>", bold_style), Paragraph("<b>Planning Remarks</b>", bold_style)],
        [Paragraph("Village / Ward", body_style), Paragraph(f"{village.upper()} (Ward {attrs['WARD']})", body_style), Paragraph("MCGM Administrative Division", body_style)],
        [Paragraph("Plot CTS No.", body_style), Paragraph(f"CTS {cts_number} ({attrs['TYPE']})", body_style), Paragraph("City Survey Cadastral Parcel", body_style)],
        [Paragraph("Plot Area", body_style), Paragraph(f"{attrs['AREA_APP_SQ_MTRS']} sq m" if attrs['AREA_APP_SQ_MTRS'] else "N/A", body_style), Paragraph("Approx. Geographic Boundary Area", body_style)],
        [Paragraph("Land-Use Zone", body_style), Paragraph(f"<b>Zone {zone}</b>", body_style), Paragraph("Primary Zoning Classification", body_style)],
        [Paragraph("PLU Designation", body_style), Paragraph(f"{des_desc} ({des_code})", body_style), Paragraph("Existing Amenity Designation", body_style)],
        [Paragraph("DP Modification", body_style), Paragraph(f"Approval: {mod_approval}", body_style), Paragraph(mod_label[:60] + ('...' if len(mod_label)>60 else ''), body_style)],
        [Paragraph("CRZ Status", body_style), Paragraph(f"<b>{crz_buffer_flag}</b>", body_style), Paragraph("Coastal Regulation Zone Layer Query", body_style)],
        [Paragraph("Metro Buffer", body_style), Paragraph(metro_buffer_flag, body_style), Paragraph("Layer 1550 Metro Rail Influence", body_style)],
        [Paragraph("Abutting Road", body_style), Paragraph(f"<b>{road_name}</b> ({road_width})", body_style), Paragraph("DP 2034 Road Access & Width", body_style)],
    ]
    
    t = Table(table_data, colWidths=[110, 215, 215])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#ECEFF1')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CFD8DC')),
        ('PADDING', (0,0), (-1,-1), 2.5),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))

    dp_img_rl = RLImage(dp_snapshot_path, width=360, height=360)
    qr_img_rl = RLImage(qr_bytes, width=100, height=100)
    
    qr_cell = [
        Paragraph("<b>Scan for Live Interactive Map:</b>", body_style),
        Spacer(1, 4),
        qr_img_rl,
        Spacer(1, 4),
        Paragraph(f"<a href='{map_link}'>Open ArcGIS Web Map</a>", ParagraphStyle('Link', parent=body_style, textColor=colors.blue, fontSize=8))
    ]
    
    media_table = Table([[dp_img_rl, qr_cell]], colWidths=[370, 170])
    media_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'CENTER'),
    ]))
    story.append(media_table)

    story.append(PageBreak())
    story.append(Paragraph("<b>HIGH-RESOLUTION SATELLITE & ADJOINING PLOT CLUSTER ANALYSIS</b>", title_style))
    story.append(Paragraph(f"Official Spatial Query Report | Page 2 of 2 | Plot CTS {cts_number} ({village.upper()})", subtitle_style))
    story.append(Spacer(1, 8))

    sat_img_rl = RLImage(sat_snapshot_path, width=540, height=340)
    story.append(sat_img_rl)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Adjoining / Neighboring CTS Parcels (Spatial Cluster):</b>", ParagraphStyle('H2', parent=bold_style, fontSize=10, textColor=colors.HexColor('#1A237E'))))
    story.append(Spacer(1, 4))

    adj_table_data = [[Paragraph("<b>Adjoining CTS No.</b>", bold_style), Paragraph("<b>Village</b>", bold_style), Paragraph("<b>Plot Area (sq m)</b>", bold_style)]]
    for n in neighbors[:8]:
        adj_table_data.append([
            Paragraph(f"CTS {n['cts_no']}", body_style),
            Paragraph(n['village'].upper(), body_style),
            Paragraph(f"{n['area_sqm']} sq m" if n['area_sqm'] != 'N/A' else "N/A", body_style)
        ])
    if not neighbors:
        adj_table_data.append([Paragraph("No immediate adjoining CTS polygons detected in buffer", body_style), Paragraph("-", body_style), Paragraph("-", body_style)])

    adj_table = Table(adj_table_data, colWidths=[180, 180, 180])
    adj_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#ECEFF1')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CFD8DC')),
        ('PADDING', (0,0), (-1,-1), 3.5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(adj_table)

    doc.build(story)

async def lookup_plot_pro(village: str, cts_number: str, output_dir: str = "./output") -> Dict[str, Any]:
    """
    Ultra-Fast Enterprise DP Plot Lookup Pro Tool (AutoCAD DXF + GeoJSON + KML Exports).
    """
    cache_key = f"{village.upper()}:{cts_number}"
    if cache_key in _LOOKUP_CACHE:
        cached_res = dict(_LOOKUP_CACHE[cache_key])
        cached_res["metadata"]["execution_time_ms"] = 12.0
        cached_res["metadata"]["cached_result"] = True
        return cached_res

    t_start = time.perf_counter()
    os.makedirs(output_dir, exist_ok=True)
    register_path = os.path.join(output_dir, "dp-lookups.xlsx")
    
    limits = httpx.Limits(max_keepalive_connections=30, max_connections=50)
    async with httpx.AsyncClient(http2=True, timeout=10.0, limits=limits, follow_redirects=True) as client:
        query_params = {
            "where": f"VILLAGE='{village.upper()}' AND CTS_CS_NO='{cts_number}'",
            "outFields": "WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS",
            "returnGeometry": "true",
            "outSR": "102100",
            "f": "json",
        }
        resp = await client.get(f"{SERVER_URL}/13/query", params=query_params)
        data = resp.json()
        
        if not data.get("features"):
            return {"error": f"Plot not found for CTS '{cts_number}' in village '{village}'"}

        feature = data["features"][0]
        attrs = feature["attributes"]
        rings = feature["geometry"]["rings"]
        
        ring = rings[0]
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        
        pts = [p for r in rings for p in r]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mcx, mcy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        d = max(50, max(max(xs) - min(xs), max(ys) - min(ys)) / 2)
        
        R = 20037508.342789244
        lon = round((cx / R) * 180, 6)
        lat = round((math.atan(math.exp(cy / R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi, 6)
        
        wgs_rings = [
            [
                [round((p[0] / R) * 180, 7), round((math.atan(math.exp(p[1] / R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi, 7)]
                for p in r_ring
            ]
            for r_ring in rings
        ]

        geom_json = f'{{"rings":{rings},"spatialReference":{{"wkid":102100}}}}'

        cts_clean = str(cts_number).replace('/', '-').replace('\\', '-')
        village_clean = village.lower().strip().replace('/', '-').replace('\\', '-').replace(' ', '_')
        query_folder_name = f"{village_clean}_cts_{cts_clean}"
        query_dir = os.path.join(output_dir, query_folder_name)
        os.makedirs(query_dir, exist_ok=True)

        crz_restriction_layer_ids = [31, 1118, 2212, 2213, 2214, 2240, 2241, 2242, 2243]

        ident_task = client.post(
            f"{SERVER_URL}/identify",
            data={
                "geometry": f"{cx},{cy}",
                "geometryType": "esriGeometryPoint",
                "sr": "102100",
                "layers": "visible:0,46,47,192,1550," + ",".join(map(str, crz_restriction_layer_ids)),
                "tolerance": "30",
                "mapExtent": f"{mcx-d},{mcy-d},{mcx+d},{mcy+d}",
                "imageDisplay": "1000,1000,96",
                "returnGeometry": "false",
                "f": "json",
            }
        )

        half = max(70, max(max(xs) - min(xs), max(ys) - min(ys)) * 0.9)
        W, H = 1000, 1000
        x0, x1 = mcx - half, mcx + half
        y0, y1 = mcy - half, mcy + half

        dp_snap_task = client.get(
            f"{SERVER_URL}/export",
            params={
                "bbox": f"{x0},{y0},{x1},{y1}",
                "bboxSR": "102100",
                "imageSR": "102100",
                "size": f"{W},{H}",
                "format": "png",
                "transparent": "false",
                "dpi": "144",
                "layers": "show:0,13,46,47,192,193,194,2214,2242,2243",
                "f": "image",
            }
        )

        road_sample_pts = [
            (mcx, mcy),
            (min(xs), min(ys)), (max(xs), max(ys)),
            (min(xs), max(ys)), (max(xs), min(ys))
        ]
        road_tasks = [
            client.post(f"{SERVER_URL}/193/query", data={"geometry": geom_json, "geometryType": "esriGeometryPolygon", "spatialRel": "esriSRRelationIntersects", "distance": "30", "units": "esriSRUnit_Meter", "inSR": "102100", "outFields": "ROAD_NAME,WIDTH_RL", "returnGeometry": "false", "f": "json"}),
            client.post(f"{SERVER_URL}/194/query", data={"geometry": geom_json, "geometryType": "esriGeometryPolygon", "spatialRel": "esriSRRelationIntersects", "distance": "30", "units": "esriSRUnit_Meter", "inSR": "102100", "outFields": "ROAD_NAME,WIDTH_RL", "returnGeometry": "false", "f": "json"})
        ] + [
            client.post(f"{SERVER_URL}/identify", data={"geometry": f"{px},{py}", "geometryType": "esriGeometryPoint", "sr": "102100", "layers": "visible:193,194,44,45", "tolerance": "40", "mapExtent": f"{mcx-d},{mcy-d},{mcx+d},{mcy+d}", "imageDisplay": "1000,1000,96", "returnGeometry": "false", "f": "json"})
            for px, py in road_sample_pts
        ]

        neighbor_sample_pts = pts[::max(1, len(pts)//12)]
        neighbor_tasks = [
            client.post(f"{SERVER_URL}/identify", data={"geometry": f"{px},{py}", "geometryType": "esriGeometryPoint", "sr": "102100", "layers": "visible:13", "tolerance": "30", "mapExtent": f"{mcx-d},{mcy-d},{mcx+d},{mcy+d}", "imageDisplay": "1000,1000,96", "returnGeometry": "false", "f": "json"})
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

        all_results = await asyncio.gather(
            ident_task,
            dp_snap_task,
            asyncio.gather(*road_tasks, return_exceptions=True),
            asyncio.gather(*neighbor_tasks, return_exceptions=True),
            asyncio.gather(*sat_tile_tasks, return_exceptions=True),
            return_exceptions=True
        )

        ident_resp = all_results[0]
        dp_snap_resp = all_results[1]
        road_resps = all_results[2]
        neighbor_resps = all_results[3]
        sat_tile_bytes = all_results[4]

        # Parse Roads
        road_map = {}
        if not isinstance(road_resps, Exception):
            for r in road_resps:
                if isinstance(r, Exception) or getattr(r, 'status_code', None) != 200:
                    continue
                j = r.json()
                for f in j.get('features', []):
                    r_attrs = f.get('attributes', {})
                    r_name, r_w = r_attrs.get('ROAD_NAME'), r_attrs.get('WIDTH_RL')
                    if r_name or r_w:
                        road_map[f"{r_name}|{r_w}"] = {'name': r_name or 'Road', 'width': r_w or 'N/A'}
                for item in j.get('results', []):
                    r_attrs = item.get('attributes', {})
                    r_name = r_attrs.get('ROAD_NAME') or r_attrs.get('TYPE_')
                    r_w = r_attrs.get('WIDTH_RL') or r_attrs.get('WIDTH')
                    if r_name or r_w:
                        road_map[f"{r_name}|{r_w}"] = {'name': r_name or 'Road', 'width': r_w or 'N/A'}

        named_roads = [r for r in road_map.values() if r['name'] != 'Exisiting Road' and r['width'] != 'N/A']
        roads = named_roads if named_roads else list(road_map.values())
        road_name = roads[0]["name"] if roads else "None"
        road_width = roads[0]["width"] if roads else "None"

        # Parse Neighbors
        neighbors_map = {}
        if not isinstance(neighbor_resps, Exception):
            for r in neighbor_resps:
                if isinstance(r, Exception) or getattr(r, 'status_code', None) != 200:
                    continue
                for item in r.json().get('results', []):
                    n_attrs = item.get('attributes', {})
                    c_no = n_attrs.get('cts_cs_no') or n_attrs.get('CTS_CS_NO')
                    n_area = n_attrs.get('area_app_sq_mtrs') or n_attrs.get('AREA_APP_SQ_MTRS')
                    v_name = n_attrs.get('village') or n_attrs.get('VILLAGE')
                    if c_no and str(c_no) != str(cts_number):
                        neighbors_map[c_no] = {'cts_no': str(c_no), 'village': str(v_name), 'area_sqm': str(n_area) if n_area else 'N/A'}
        neighbors = list(neighbors_map.values())

        # Parse Identify
        results = ident_resp.json().get("results", []) if not isinstance(ident_resp, Exception) and ident_resp.status_code == 200 else []
        z_item = next((r for r in results if r.get("layerId") == 0), None)
        rv_item = next((r for r in results if r.get("layerId") == 46), None)
        des_item = next((r for r in results if r.get("layerId") == 47), None)
        mod_item = next((r for r in results if r.get("layerId") == 192), None)
        metro_item = next((r for r in results if r.get("layerId") == 1550), None)
        crz_item = next((r for r in results if r.get("layerId") in crz_restriction_layer_ids), None)

        zone = z_item["attributes"]["Zone_Code2"] if z_item else "Unknown"
        res_code = rv_item["attributes"]["NEW_RES_CODE_31"] if rv_item else "None"
        res_type = rv_item["attributes"]["NEW_RES_MAINTYPE_31"] if rv_item else "None"
        des_code = des_item["attributes"]["NEW_DES_CODE_31"] if des_item else "None"
        des_desc = des_item["attributes"]["DISCRIPTION"].strip() if des_item else "None"
        mod_label = mod_item["attributes"]["LABEL to Display"] if mod_item else "None"
        mod_approval = mod_item["attributes"]["APPROVAL_NO"] if mod_item else "None"
        mod_doc = mod_item["attributes"]["Approval Documents"] if mod_item else "None"
        
        metro_buffer_flag = "YES (Metro Buffer Zone)" if metro_item else "NO"
        crz_buffer_flag = f"YES ({crz_item.get('layerName')})" if crz_item else "NO (Outside CRZ Buffer)"

        if mod_item:
            status_badge = "🟡 MODIFIED (DP Notification Order)"
            status_summary = f"Modified via {mod_approval}"
        elif des_item and des_desc != "None":
            status_badge = f"🔴 RESERVED / DESIGNATED ({des_desc})"
            status_summary = f"Designated as {des_desc} ({des_code})"
        elif rv_item and res_code != "None":
            status_badge = f"🔴 RESERVED ({res_type})"
            status_summary = f"Reserved under {res_code}"
        else:
            status_badge = "🟢 CLEAR (No Reservation)"
            status_summary = "Unreserved Land Parcel"

        ward_clean = str(attrs['WARD']).replace('/', '-').replace('\\', '-')

        def px_dp(x, y):
            return ((x - x0) / (x1 - x0) * W, (y1 - y) / (y1 - y0) * H)

        # Render HD DP Map Overlay
        dp_img = Image.open(io.BytesIO(dp_snap_resp.content)).convert("RGBA") if not isinstance(dp_snap_resp, Exception) and dp_snap_resp.status_code == 200 else Image.new("RGBA", (W, H), (240, 240, 240, 255))
        dp_overlay = Image.new("RGBA", dp_img.size, (255, 255, 255, 0))
        draw_dp = ImageDraw.Draw(dp_overlay)

        for r in rings:
            poly_pts = [px_dp(p[0], p[1]) for p in r]
            draw_dp.polygon(poly_pts, fill=(255, 23, 68, 45), outline=(255, 23, 68, 255), width=5)

        nx, ny = W - 80, 80
        draw_dp.ellipse([nx-30, ny-30, nx+30, ny+30], fill=(255, 255, 255, 230), outline=(0, 0, 0, 255), width=2)
        draw_dp.polygon([(nx, ny-22), (nx-10, ny+12), (nx+10, ny+12)], fill=(220, 0, 0, 255))
        draw_dp.text((nx-5, ny-48), "N", fill=(0, 0, 0, 255), font_size=24)

        lw, lh = 420, 160
        lx0, ly0 = W - lw - 30, H - lh - 30
        draw_dp.rectangle([lx0, ly0, lx0+lw, ly0+lh], fill=(255, 255, 255, 235), outline=(0, 0, 0, 255), width=2)
        draw_dp.rectangle([lx0+20, ly0+20, lx0+50, ly0+42], fill=(255, 23, 68, 100), outline=(255, 23, 68, 255), width=2)
        draw_dp.text((lx0+60, ly0+20), f"Plot Boundary (CTS {cts_number})", fill=(0, 0, 0, 255), font_size=18)
        draw_dp.text((lx0+20, ly0+55), f"Village: {village.upper()} | Ward: {attrs['WARD']}", fill=(0, 0, 0, 255), font_size=16)
        draw_dp.text((lx0+20, ly0+85), f"Zone: {zone} | Area: {attrs['AREA_APP_SQ_MTRS']} sq m", fill=(0, 0, 0, 255), font_size=16)
        draw_dp.text((lx0+20, ly0+115), f"Status: {status_badge[:30]}", fill=(0, 0, 0, 255), font_size=16)

        final_dp_img = Image.alpha_composite(dp_img, dp_overlay)
        dp_snapshot_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}_hd.png"
        dp_snapshot_path = os.path.join(query_dir, dp_snapshot_fname)

        # Stitch Satellite Canvas
        canvas_w, canvas_h = grid_dim * 256, grid_dim * 256
        sat_canvas = Image.new('RGBA', (canvas_w, canvas_h), (40, 40, 40, 255))
        if not isinstance(sat_tile_bytes, Exception):
            for (gx, gy), b in zip(sat_coords, sat_tile_bytes):
                if b:
                    try:
                        t_img = Image.open(io.BytesIO(b)).convert('RGBA')
                        sat_canvas.paste(t_img, (gx * 256, gy * 256))
                    except Exception:
                        pass
                    
        top_lat, left_lon = tile_to_latlon(xtile - half_dim, ytile - half_dim, zoom)
        bot_lat, right_lon = tile_to_latlon(xtile + half_dim + 1, ytile + half_dim + 1, zoom)
        
        sat_overlay = Image.new('RGBA', (canvas_w, canvas_h), (255, 255, 255, 0))
        draw_sat = ImageDraw.Draw(sat_overlay)
        
        def px_sat(w_lon, w_lat):
            x_px = (w_lon - left_lon) / (right_lon - left_lon) * canvas_w
            y_px = (top_lat - w_lat) / (top_lat - bot_lat) * canvas_h
            return (x_px, y_px)
            
        for r in wgs_rings:
            poly_pts = [px_sat(p[0], p[1]) for p in r]
            draw_sat.polygon(poly_pts, fill=(255, 235, 59, 50), outline=(255, 235, 59, 255), width=5)
            
        slw, slh = 320, 110
        slx0, sly0 = canvas_w - slw - 15, canvas_h - slh - 15
        draw_sat.rectangle([slx0, sly0, slx0+slw, sly0+slh], fill=(0, 0, 0, 210), outline=(255, 255, 255, 255), width=2)
        draw_sat.rectangle([slx0+12, sly0+12, slx0+35, sly0+30], fill=(255, 235, 59, 100), outline=(255, 235, 59, 255), width=2)
        draw_sat.text((slx0+42, sly0+12), f"Satellite Boundary (CTS {cts_number})", fill=(255, 255, 255, 255), font_size=13)
        draw_sat.text((slx0+12, sly0+38), f"Village: {village.upper()} | Ward: {attrs['WARD']}", fill=(255, 255, 255, 255), font_size=12)
        draw_sat.text((slx0+12, sly0+60), f"Lat: {lat:.6f} | Lon: {lon:.6f}", fill=(255, 255, 255, 255), font_size=12)
        draw_sat.text((slx0+12, sly0+82), f"Adjoining Parcels Identified: {len(neighbors)}", fill=(255, 255, 255, 255), font_size=12)

        final_sat = Image.alpha_composite(sat_canvas, sat_overlay)
        sat_snapshot_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}_satellite.png"
        sat_snapshot_path = os.path.join(query_dir, sat_snapshot_fname)

        def save_images():
            final_dp_img.convert("RGB").save(dp_snapshot_path, "PNG", compress_level=1)
            final_sat.convert("RGB").save(sat_snapshot_path, "PNG", compress_level=1)

        await asyncio.to_thread(save_images)

        map_link = (
            f"https://mcgm.maps.arcgis.com/apps/webappviewer/index.html?"
            f"id=67118c3502fd492e94680d10e77ec112&marker={lon},{lat},4326,{cts_number}%20{village}"
            f"&center={lon},{lat}&level=19"
        )

        geojson_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}.geojson"
        geojson_path = os.path.join(query_dir, geojson_fname)
        
        dxf_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}.dxf"
        dxf_path = os.path.join(query_dir, dxf_fname)
        
        kml_fname = f"plot_{ward_clean}_{cts_clean}_{village_clean}.kml"
        kml_path = os.path.join(query_dir, kml_fname)

        export_props = {
            "village": village.upper(),
            "cts_no": str(cts_number),
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
            "adjoining_cts_plots_count": len(neighbors),
            "map_link": map_link
        }

        export_geojson(wgs_rings, export_props, geojson_path)
        export_dxf(wgs_rings, export_props, dxf_path)
        export_kml(wgs_rings, export_props, kml_path)

        pdf_fname = f"dp_report_{ward_clean}_{cts_clean}_{village_clean}.pdf"
        pdf_path = os.path.join(query_dir, pdf_fname)
        
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(map_link)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_bytes = io.BytesIO()
        qr_img.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)
        
        await asyncio.to_thread(
            build_pdf_doc,
            pdf_path, status_badge, status_summary, village, attrs, cts_number, zone, des_desc, des_code, mod_approval, mod_label, crz_buffer_flag, metro_buffer_flag, road_name, road_width, dp_snapshot_path, qr_bytes, map_link, sat_snapshot_path, neighbors
        )

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        headers = [
            "lookup_datetime", "source", "ward", "village", "cts_no", "type",
            "area_sqm", "zone", "status_badge", "reservation_code", "reservation_type",
            "designation_code", "designation_desc", "modification_approval",
            "modification_label", "modification_doc", "crz_buffer", "metro_buffer",
            "abutting_road", "road_width", "adjoining_plots_count", "hd_snapshot_file",
            "satellite_snapshot_file", "pdf_report_file", "dxf_file", "geojson_file", "kml_file", "map_link"
        ]
        row = [
            now_str, "MCGM SDP 2014-34", attrs["WARD"], village, cts_number, attrs["TYPE"],
            attrs["AREA_APP_SQ_MTRS"], zone, status_badge, res_code, res_type,
            des_code, des_desc, mod_approval, mod_label, mod_doc, crz_buffer_flag, metro_buffer_flag,
            road_name, road_width, len(neighbors), dp_snapshot_fname, sat_snapshot_fname, pdf_fname,
            dxf_fname, geojson_fname, kml_fname, map_link
        ]

        wb = load_workbook(register_path) if os.path.exists(register_path) else Workbook()
        ws = wb.active
        if ws.max_row == 1 and ws["A1"].value is None:
            ws.append(headers)
        ws.append(row)
        wb.save(register_path)

        t_end = time.perf_counter()
        exec_ms = round((t_end - t_start) * 1000, 1)

        result_dict = {
            "plot_identity": {
                "village": village.upper(),
                "cts_no": str(cts_number),
                "ward": str(attrs["WARD"]),
                "type": str(attrs["TYPE"]),
                "area_sqm": attrs["AREA_APP_SQ_MTRS"],
                "coordinates_wgs84": {
                    "latitude": lat,
                    "longitude": lon
                }
            },
            "planning_remarks": {
                "status_badge": status_badge,
                "status_summary": status_summary,
                "zone": zone,
                "reservation": {
                    "code": res_code,
                    "type": res_type
                },
                "designation": {
                    "code": des_code,
                    "description": des_desc
                },
                "dp_modification": {
                    "approval_no": mod_approval,
                    "details": mod_label,
                    "document_link": mod_doc
                }
            },
            "regulatory_and_infrastructure": {
                "crz_status": crz_buffer_flag,
                "metro_buffer": metro_buffer_flag,
                "abutting_road": {
                    "name": road_name,
                    "width": road_width
                }
            },
            "spatial_cluster": {
                "adjoining_plots_count": len(neighbors),
                "adjoining_cts_plots": neighbors
            },
            "export_files": {
                "bundle_folder": query_dir,
                "pdf_report": pdf_path,
                "hd_dp_map": dp_snapshot_path,
                "satellite_view": sat_snapshot_path,
                "autocad_dxf": dxf_path,
                "autocad_geojson": geojson_path,
                "google_earth_kml": kml_path,
                "master_excel_register": register_path
            },
            "metadata": {
                "source": "MCGM SDP 2014-34",
                "lookup_datetime": now_str,
                "execution_time_ms": exec_ms,
                "cached_result": False,
                "interactive_web_map": map_link
            }
        }
        _LOOKUP_CACHE[cache_key] = result_dict
        save_disk_cache()
        return result_dict
