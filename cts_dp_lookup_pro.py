import os
import re
import sys
import json
import math
import asyncio
import io
import time
import datetime
from xml.sax.saxutils import escape as _xml_escape
from typing import Dict, Any, List, Optional
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

CACHE_FILENAME = ".cache_store.json"

# 30 days.
#
# Chosen to match how slowly this data actually moves rather than as a generic
# "safe" default. Layer 13 (parcel geometry and area) carries LAST_EDITED_DATE
# 2019-01-23 on every parcel checked - the boundaries are a frozen snapshot.
# Zones, reservations and CRZ tiers are statutory and change only by gazetted
# order. The one genuinely moving part is DP modifications (layer 192), which
# appear sporadically - Byculla 1605 gained one dated 22.08.2024.
#
# The trade: a newly gazetted modification can go unseen for up to 30 days.
# Mitigated by reporting cache age on every hit (see metadata.cache_age_days)
# and by --no-cache for same-day certainty.
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

# In-memory tile cache is process-scoped and safe to share across lookups.
_TILE_CACHE: Dict[str, bytes] = {}

# One lookup store per output directory. The store used to be a single module
# global bound to a hardcoded './output/.cache_store.json', which ignored the
# caller's output_dir and wrote relative to the process CWD.
_STORES: Dict[str, Dict[str, Any]] = {}


def cache_path_for(output_dir: str) -> str:
    """Cache store lives beside the bundles it describes, not beside the CWD."""
    return os.path.join(output_dir, CACHE_FILENAME)


def load_disk_cache(output_dir: str) -> Dict[str, Any]:
    path = cache_path_for(output_dir)
    if path in _STORES:
        return _STORES[path]
    store: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                store = loaded
        except (OSError, ValueError):
            store = {}
    _STORES[path] = store
    return store


def save_disk_cache(output_dir: str) -> None:
    path = cache_path_for(output_dir)
    store = _STORES.get(path, {})
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
    except OSError as exc:
        # Surface rather than swallow: a read-only or full disk silently
        # disabling the cache used to be invisible.
        print(f"[dp-lookup-pro] WARNING: could not write cache store {path}: {exc}")


def bundle_is_intact(result: Dict[str, Any]) -> bool:
    """
    True when every file the cached result promises still exists on disk.

    A cache hit used to hand back paths without checking them, so deleting an
    output folder produced a confident "success" pointing at seven missing files.
    The Excel register is excluded: it is shared, regenerated on demand, and its
    absence does not invalidate the plot bundle.
    """
    files = result.get("export_files")
    if not isinstance(files, dict):
        return False
    for key, path in files.items():
        if key == "master_excel_register" or not isinstance(path, str):
            continue
        if not os.path.exists(path):
            return False
    return True


def read_cache_entry(output_dir: str, key: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    """
    Return a cached result, or None when it is absent, expired, in the legacy
    format, or no longer backed by files on disk.
    """
    entry = load_disk_cache(output_dir).get(key)
    if not isinstance(entry, dict):
        return None
    # Legacy entries were the bare result dict with no timestamp. They predate
    # the CRZ and road fixes, so treat them as expired rather than trusting them.
    cached_at = entry.get("cached_at")
    result = entry.get("result")
    if not isinstance(cached_at, (int, float)) or not isinstance(result, dict):
        return None
    if ttl_seconds >= 0 and (time.time() - cached_at) > ttl_seconds:
        return None
    if not bundle_is_intact(result):
        return None

    result = json.loads(json.dumps(result))
    age = max(0.0, time.time() - cached_at)
    meta = result.setdefault("metadata", {})
    meta["cached_at"] = datetime.datetime.fromtimestamp(cached_at).strftime("%Y-%m-%d %H:%M:%S")
    meta["cache_age_days"] = round(age / 86400.0, 2)
    meta["cache_expires_in_days"] = (
        None if ttl_seconds < 0 else round(max(0.0, ttl_seconds - age) / 86400.0, 2)
    )
    return result


def write_cache_entry(output_dir: str, key: str, result: Dict[str, Any]) -> None:
    store = load_disk_cache(output_dir)
    store[key] = {"cached_at": time.time(), "result": result}
    save_disk_cache(output_dir)


# --- Input validation -------------------------------------------------------
# village and cts_number are interpolated into an ArcGIS WHERE clause. Restrict
# them to the characters real MCGM values actually use, then double any quote
# that survives, so a value like  1' OR '1'='1  cannot alter the query.
_VILLAGE_RE = re.compile(r"^[A-Za-z0-9 ()./-]{1,64}$")
_CTS_RE = re.compile(r"^[A-Za-z0-9 ()./-]{1,32}$")


def sanitize_query_value(value: Any, pattern: "re.Pattern[str]", label: str, max_len: int) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if len(text) > max_len:
        raise ValueError(f"{label} is too long (max {max_len} characters)")
    if not pattern.match(text):
        raise ValueError(
            f"{label} contains unsupported characters. "
            f"Allowed: letters, digits, space, and ( ) . / -"
        )
    return text.replace("'", "''")


def _esc(value: Any) -> str:
    """Escape a data value for embedding in XML/KML or ReportLab markup."""
    return _xml_escape("" if value is None else str(value))


def usable_json(resp: Any) -> Optional[Dict[str, Any]]:
    """
    Parsed JSON body, or None when the response is unusable.

    ArcGIS reports failures as HTTP 200 carrying {"error": {...}}. Reading
    .get("features", []) on such a body yields an empty list that is
    indistinguishable from a genuine no-match, which is how three separate
    silent failures reached production. Every parse goes through here.
    """
    if isinstance(resp, Exception) or resp is None:
        return None
    if getattr(resp, "status_code", None) != 200:
        return None
    try:
        body = resp.json()
    except (ValueError, AttributeError):
        return None
    if not isinstance(body, dict) or "error" in body:
        return None
    return body

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

def wgs84_to_utm43n(lon: float, lat: float) -> tuple:
    """
    Converts WGS84 (lon, lat) in degrees to UTM Zone 43N (Easting, Northing) in meters.
    WGS84 Ellipsoid: a = 6378137.0 m, f = 1/298.257223563
    Central Meridian = 75.0° E (UTM Zone 43N covers Mumbai 72.8° E).
    """
    a = 6378137.0
    f = 1.0 / 298.257223563
    b = a * (1.0 - f)
    e2 = (a**2 - b**2) / (a**2)
    ep2 = (a**2 - b**2) / (b**2)
    
    k0 = 0.9996
    lon0 = 75.0
    
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    lon0_rad = math.radians(lon0)
    
    N = a / math.sqrt(1.0 - e2 * math.sin(lat_rad)**2)
    T = math.tan(lat_rad)**2
    C = ep2 * math.cos(lat_rad)**2
    A = (lon_rad - lon0_rad) * math.cos(lat_rad)
    
    M = a * (
        (1.0 - e2/4.0 - 3.0*e2**2/64.0 - 5.0*e2**3/256.0) * lat_rad
        - (3.0*e2/8.0 + 3.0*e2**2/32.0 + 45.0*e2**3/1024.0) * math.sin(2.0 * lat_rad)
        + (15.0*e2**2/256.0 + 45.0*e2**3/1024.0) * math.sin(4.0 * lat_rad)
        - (35.0*e2**3/3072.0) * math.sin(6.0 * lat_rad)
    )
    
    x = k0 * N * (
        A
        + (1.0 - T + C) * A**3 / 6.0
        + (5.0 - 18.0*T + T**2 + 72.0*C - 58.0*ep2) * A**5 / 120.0
    ) + 500000.0
    
    y = k0 * (
        M + N * math.tan(lat_rad) * (
            A**2 / 2.0
            + (5.0 - T + 9.0*C + 4.0*C**2) * A**4 / 24.0
            + (61.0 - 58.0*T + T**2 + 600.0*C - 330.0*ep2) * A**6 / 720.0
        )
    )
    return x, y

def polygon_signed_area(ring: list) -> float:
    """Shoelace. Positive = counter-clockwise winding."""
    n = len(ring)
    return sum(
        ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1]
        for i in range(n)
    ) / 2.0


def offset_polygon_inward(ring: list, distance: float) -> list:
    """
    True parallel inward offset of a closed polygon. Returns a LIST of rings.

    This is what a building setback actually is: every point on the result is
    exactly `distance` from the nearest boundary edge.

    Two earlier approaches were wrong and both were caught by measurement:

      1. Pulling each vertex radially toward the centroid by
         min(distance, dist*0.3). Neither perpendicular nor the requested
         distance - on WORLI 733 the "3 m" line sat 1.15-3.00 m from the
         boundary.
      2. A hand-rolled miter offset. Exact on convex plots, but it
         self-intersects on concave ones, and real CTS parcels are concave
         (WORLI 733 has 6 reflex corners). It measured 0.68 m against a 3 m
         target.

    Shapely's buffer resolves self-intersection properly, which is the whole
    difficulty here. A setback can legitimately split a plot into more than one
    buildable island, so every resulting ring is returned.

    Returns [] when the plot cannot sustain the offset, so the caller omits the
    line rather than drawing a misleading one.
    """
    from shapely.geometry import Polygon
    from shapely.geometry.base import BaseMultipartGeometry

    pts = list(ring)
    if len(pts) > 1 and math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-9) \
            and math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-9):
        pts = pts[:-1]
    if len(pts) < 3 or distance <= 0:
        return []

    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)          # repair self-touching input
        shrunk = poly.buffer(-abs(distance), join_style=2)  # 2 = mitre
    except Exception:
        return []

    if shrunk.is_empty:
        return []

    parts = list(shrunk.geoms) if isinstance(shrunk, BaseMultipartGeometry) else [shrunk]
    out = []
    for part in parts:
        exterior = getattr(part, "exterior", None)
        if exterior is None:
            continue
        coords = [(x, y) for x, y in exterior.coords]
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) >= 3 and abs(polygon_signed_area(coords)) >= 1.0:
            out.append(coords)
    return out


def export_dxf(wgs_rings: list, properties: dict, output_path: str, neighbors: list = None,
               roads: list = None):
    """
    Generates a scale-accurate Multi-Layered AutoCAD DXF CAD drawing file (.dxf)
    centered around Local Origin (0, 0) in Real-World Metric Meters (1 CAD Unit = 1 Meter).
    Configures active modelspace viewport & extents for instant framing in AutoCAD 2024.
    
    Layers:
    - 0_GRID_AXIS: Metric Axis Grid & Axis Labels
    - C-PLOT-BDY: Primary CTS Plot Boundary Polyline (Closed, Red)
    - C-PROP-HATCH: Solid Plot Fill Pattern
    - C-SETBACK-3M: 3.0m Concept Setback Line for Massing (Dashed Green)
    - C-SETBACK-6M: 6.0m Tower Setback Line (Dashed Dark Green)
    - C-ADJN-PLOTS: Adjoining CTS Plot Boundaries & CTS Labels (Yellow)
    - C-ROAD-ALIGN: Abutting Road Alignment Vector (Cyan)
    - C-RESTRICT-ZONE: Metro Rail / CRZ Restriction Zone (Phantom Magenta)
    - C-ANNO-TEXT: Plot Centroid Attribute Block & Parcel Metadata
    - C-ANNO-DIMS: Automated Boundary Segment Dimensions in Meters
    - C-TITLE-BLOCK: Architectural Sheet Border Frame & Title Block Box
    """
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6     # Units = Meters
    doc.header['$MEASUREMENT'] = 1  # ISO Metric
    
    msp = doc.modelspace()
    
    # Try adding linetypes
    try:
        doc.linetypes.add('DASHED', pattern='A, 1.0, -0.5')
        doc.linetypes.add('PHANTOM', pattern='A, 2.0, -0.5, 0.5, -0.5, 0.5, -0.5')
    except Exception:
        pass

    # Add Architectural Layers
    doc.layers.add(name='0_GRID_AXIS', color=8, linetype='DASHED')
    doc.layers.add(name='C-PLOT-BDY', color=1)
    doc.layers.add(name='C-PROP-HATCH', color=252)
    doc.layers.add(name='C-SETBACK-3M', color=3, linetype='DASHED')
    doc.layers.add(name='C-SETBACK-6M', color=70, linetype='DASHED')
    doc.layers.add(name='C-ADJN-PLOTS', color=2)
    doc.layers.add(name='C-ROAD-ALIGN', color=4, linetype='DASHED')
    doc.layers.add(name='C-RESTRICT-ZONE', color=6, linetype='PHANTOM')
    doc.layers.add(name='C-ANNO-TEXT', color=7)
    doc.layers.add(name='C-ANNO-DIMS', color=5)
    doc.layers.add(name='C-NORTH-ARROW', color=7)
    doc.layers.add(name='C-TITLE-BLOCK', color=4)
    
    # 1. Fast Scale-Accurate Metric Projection around Local Origin (0, 0)
    r0 = wgs_rings[0]
    lons = [p[0] for p in r0]
    lats = [p[1] for p in r0]
    
    lon0 = sum(lons) / len(lons)
    lat0 = sum(lats) / len(lats)
    
    lat_rad = math.radians(lat0)
    cos_lat = math.cos(lat_rad)
    
    # Degree-to-Meter conversion constants for Mumbai latitude (~18.9° N)
    meters_per_deg_lon = 111319.5 * cos_lat
    meters_per_deg_lat = 111132.0
    
    local_rings = []
    for ring in wgs_rings:
        loc_ring = [
            ((p[0] - lon0) * meters_per_deg_lon, (p[1] - lat0) * meters_per_deg_lat)
            for p in ring
        ]
        local_rings.append(loc_ring)
        
    lr0 = local_rings[0]
    all_x = [p[0] for p in lr0]
    all_y = [p[1] for p in lr0]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    
    # Calculate real-world UTM Zone 43N centroid for title block metadata
    utm_cx, utm_cy = wgs84_to_utm43n(lon0, lat0)
    
    cx, cy = 0.0, 0.0
    width = max_x - min_x
    height = max_y - min_y
    scale = max(width, height, 30.0)
    char_h = max(1.2, scale * 0.035)
    dim_char_h = max(0.9, scale * 0.025)
    
    # 2. 0_GRID_AXIS: Metric Axis Grid around (0, 0)
    grid_step = 50.0 if scale > 80 else 25.0
    g_min_x = math.floor((min_x - scale * 0.4) / grid_step) * grid_step
    g_max_x = math.ceil((max_x + scale * 0.4) / grid_step) * grid_step
    g_min_y = math.floor((min_y - scale * 0.4) / grid_step) * grid_step
    g_max_y = math.ceil((max_y + scale * 0.4) / grid_step) * grid_step
    
    gx = g_min_x
    while gx <= g_max_x:
        msp.add_line((gx, g_min_y), (gx, g_max_y), dxfattribs={'layer': '0_GRID_AXIS'})
        msp.add_text(f"{int(gx)}m", dxfattribs={'layer': '0_GRID_AXIS', 'height': dim_char_h * 0.8}).set_placement((gx + 0.5, g_min_y + 0.5))
        gx += grid_step
        
    gy = g_min_y
    while gy <= g_max_y:
        msp.add_line((g_min_x, gy), (g_max_x, gy), dxfattribs={'layer': '0_GRID_AXIS'})
        msp.add_text(f"{int(gy)}m", dxfattribs={'layer': '0_GRID_AXIS', 'height': dim_char_h * 0.8}).set_placement((g_min_x + 0.5, gy + 0.5))
        gy += grid_step

    # 3. C-PLOT-BDY: Primary Plot Boundary (Closed Polyline)
    for loc_ring in local_rings:
        poly = msp.add_lwpolyline(loc_ring, dxfattribs={'layer': 'C-PLOT-BDY', 'closed': True})
        poly.dxf.const_width = max(0.15, scale * 0.005)
        
        # Solid Hatch inside plot boundary
        try:
            hatch = msp.add_hatch(color=252, dxfattribs={'layer': 'C-PROP-HATCH'})
            hatch.paths.add_polyline_path(loc_ring, is_closed=True)
        except Exception:
            pass

    # 4. C-SETBACK-3M & C-SETBACK-6M: true parallel setback lines.
    #
    # Each is a genuine perpendicular offset from every boundary edge (miter
    # joins at the corners), so an architect can build massing directly to these
    # lines. If the plot is too small to sustain an offset the line is omitted
    # rather than drawn wrong, and that is recorded for the legend.
    setback_status = {}
    for spec_layer, spec_dist in (('C-SETBACK-3M', 3.0), ('C-SETBACK-6M', 6.0)):
        drawn = 0
        for loc_ring in local_rings:
            for offset_ring in offset_polygon_inward(loc_ring, spec_dist):
                msp.add_lwpolyline(offset_ring, dxfattribs={'layer': spec_layer, 'closed': True})
                drawn += 1
        setback_status[spec_dist] = drawn > 0
        if not drawn:
            msp.add_text(
                f"{spec_dist:.1f}m SETBACK NOT VIABLE - PLOT TOO NARROW",
                dxfattribs={'layer': spec_layer, 'height': dim_char_h}
            ).set_placement((min_x, min_y - dim_char_h * (2.5 if spec_dist == 3.0 else 4.0)))

    # 5. C-ANNO-DIMS: Automated Boundary Side Dimension Lines in Meters
    for loc_ring in local_rings:
        n_pts = len(loc_ring)
        for i in range(n_pts):
            p1 = loc_ring[i]
            p2 = loc_ring[(i + 1) % n_pts]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            seg_len = math.sqrt(dx*dx + dy*dy)
            if seg_len > 0.5:
                mx = (p1[0] + p2[0]) / 2.0
                my = (p1[1] + p2[1]) / 2.0
                # Outward normal
                nx = -dy / seg_len
                ny = dx / seg_len
                if (mx + nx - cx)**2 + (my + ny - cy)**2 < (mx - cx)**2 + (my - cy)**2:
                    nx = -nx
                    ny = -ny
                tx = mx + nx * (dim_char_h * 1.8)
                ty = my + ny * (dim_char_h * 1.8)
                angle_deg = math.degrees(math.atan2(dy, dx))
                if angle_deg > 90 or angle_deg < -90:
                    angle_deg += 180
                
                txt_elem = msp.add_text(f"{seg_len:.2f}m", dxfattribs={
                    'layer': 'C-ANNO-DIMS',
                    'height': dim_char_h,
                    'rotation': angle_deg
                })
                txt_elem.set_placement((tx, ty))

    # 6. C-ADJN-PLOTS: Adjoining CTS Plot Boundaries
    if neighbors:
        for n in neighbors:
            n_rings = n.get('rings', [])
            n_cts = n.get('cts_no', 'N/A')
            for n_ring in n_rings:
                n_loc_ring = [((pt[0] - lon0) * meters_per_deg_lon, (pt[1] - lat0) * meters_per_deg_lat) for pt in n_ring]
                msp.add_lwpolyline(n_loc_ring, dxfattribs={'layer': 'C-ADJN-PLOTS', 'closed': True})
                if n_loc_ring:
                    ncx = sum(p[0] for p in n_loc_ring) / len(n_loc_ring)
                    ncy = sum(p[1] for p in n_loc_ring) / len(n_loc_ring)
                    msp.add_text(f"CTS {n_cts}", dxfattribs={
                        'layer': 'C-ADJN-PLOTS',
                        'height': dim_char_h * 0.9
                    }).set_placement((ncx, ncy))

    # 6b. C-ROAD-ALIGN: abutting road centreline(s).
    # This layer was declared but never populated - an architect had no idea
    # which edge was the frontage, which is what governs the front setback.
    # MCGM returns whole road networks - one polyline came back 3.8 km long with
    # 2472 vertices. Clip to the plot's vicinity so the sheet stays legible and
    # the drawing extents stay sane.
    clip = scale * 0.9
    cx_lo, cx_hi = min_x - clip, max_x + clip
    cy_lo, cy_hi = min_y - clip, max_y + clip

    def _inside(p):
        return cx_lo <= p[0] <= cx_hi and cy_lo <= p[1] <= cy_hi

    road_drawn = 0
    for road_ring in (roads or []):
        loc = [((pt[0] - lon0) * meters_per_deg_lon, (pt[1] - lat0) * meters_per_deg_lat)
               for pt in road_ring]
        # keep contiguous runs that fall inside the sheet, plus one point either
        # side of each crossing so the line reaches the sheet edge
        run, runs = [], []
        for i, p in enumerate(loc):
            if _inside(p):
                if not run and i > 0:
                    run.append(loc[i - 1])
                run.append(p)
            elif run:
                run.append(p)
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        for seg in runs:
            if len(seg) >= 2:
                msp.add_lwpolyline(seg, dxfattribs={'layer': 'C-ROAD-ALIGN'})
                road_drawn += 1

    if road_drawn:
        msp.add_text(
            f"ABUTTING ROAD: {properties.get('abutting_road')} ({properties.get('road_width')})",
            dxfattribs={'layer': 'C-ROAD-ALIGN', 'height': dim_char_h}
        ).set_placement((min_x, min_y - dim_char_h * 1.2))

    # 7. C-RESTRICT-ZONE: CRZ and Metro development restrictions.
    restrict_notes = []
    crz_flag = str(properties.get("crz_buffer_flag") or "")
    if crz_flag.upper().startswith("YES"):
        restrict_notes.append(f"COASTAL REGULATION ZONE: {crz_flag}")
        restrict_notes.append("Development restricted under CRZ Notification - verify with MCGM/MCZMA")
    if properties.get("metro_buffer_flag") == "YES":
        msp.add_circle((cx, cy), radius=scale * 0.6, dxfattribs={'layer': 'C-RESTRICT-ZONE'})
        restrict_notes.append("METRO RAIL INFLUENCE BUFFER")
    for i, note in enumerate(restrict_notes):
        msp.add_text(note, dxfattribs={
            'layer': 'C-RESTRICT-ZONE', 'height': dim_char_h
        }).set_placement((min_x, max_y + dim_char_h * (2.2 + i * 1.4)))

    # 8. C-ANNO-TEXT: Centroid Metadata Title Block
    lbl_text = (
        f"CTS NO: {properties.get('cts_no')}\n"
        f"VILLAGE: {properties.get('village')}\n"
        f"WARD: {properties.get('ward')}\n"
        f"AREA: {properties.get('area_sqm')} SQ M\n"
        f"ZONE: {properties.get('zone')}\n"
        f"STATUS: {properties.get('status_badge')}\n"
        f"ABUTTING ROAD: {properties.get('abutting_road')} ({properties.get('road_width')})\n"
        f"UTM CENTROID: E {utm_cx:.2f} m | N {utm_cy:.2f} m (UTM 43N)"
    )
    mtext = msp.add_mtext(lbl_text, dxfattribs={'layer': 'C-ANNO-TEXT', 'char_height': char_h})
    mtext.set_location((cx - width * 0.4, cy + height * 0.2))

    # 8b. C-NORTH-ARROW: orientation. Local +Y is true north because the metric
    # projection maps latitude straight onto Y.
    na_x = max_x + scale * 0.16
    na_y = max_y - scale * 0.06
    na_r = scale * 0.07
    msp.add_circle((na_x, na_y), radius=na_r, dxfattribs={'layer': 'C-NORTH-ARROW'})
    msp.add_lwpolyline(
        [(na_x, na_y + na_r * 1.5), (na_x - na_r * 0.5, na_y - na_r * 0.7), (na_x + na_r * 0.5, na_y - na_r * 0.7)],
        dxfattribs={'layer': 'C-NORTH-ARROW', 'closed': True})
    msp.add_text("N", dxfattribs={'layer': 'C-NORTH-ARROW', 'height': char_h}) \
        .set_placement((na_x - char_h * 0.35, na_y + na_r * 1.8))

    # 9. C-TITLE-BLOCK: sheet border, legend panel and title block.
    b_min_x = min_x - scale * 0.35
    b_min_y = min_y - scale * 0.45
    b_max_y = max_y + scale * 0.45
    plot_right = max_x + scale * 0.35

    # Legend panel sits to the right of the drawing so it never covers geometry.
    lg_w = max(scale * 0.95, 26.0)
    lg_x0 = plot_right + scale * 0.06
    b_max_x = lg_x0 + lg_w + scale * 0.06

    msp.add_lwpolyline(
        [(b_min_x, b_min_y), (b_max_x, b_min_y), (b_max_x, b_max_y), (b_min_x, b_max_y)],
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'closed': True})

    # ---- LEGEND ----------------------------------------------------------
    lg_row = max(char_h * 1.9, 2.2)
    legend_rows = [
        ('C-PLOT-BDY',      'PLOT BOUNDARY - gross plot area'),
        ('C-PROP-HATCH',    'Gross plot area (fill)'),
        ('C-ROAD-ALIGN',    'Abutting road alignment / frontage'),
        ('C-SETBACK-3M',    '3.0 m setback line (true parallel offset)'),
        ('C-SETBACK-6M',    '6.0 m setback line (true parallel offset)'),
        ('C-RESTRICT-ZONE', 'CRZ / Metro development restriction'),
        ('C-ADJN-PLOTS',    'Adjoining CTS plots'),
        ('C-ANNO-DIMS',     'Boundary segment dimensions (m)'),
        ('C-ANNO-TEXT',     'Plot metadata'),
        ('C-NORTH-ARROW',   'True north'),
        ('0_GRID_AXIS',     'Metric grid, 0,0 at plot centroid'),
        ('C-TITLE-BLOCK',   'Sheet border, legend, title block'),
    ]
    lg_h = lg_row * (len(legend_rows) + 9.5)
    lg_y1 = b_max_y - scale * 0.05
    lg_y0 = lg_y1 - lg_h
    msp.add_lwpolyline(
        [(lg_x0, lg_y0), (lg_x0 + lg_w, lg_y0), (lg_x0 + lg_w, lg_y1), (lg_x0, lg_y1)],
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'closed': True})

    y = lg_y1 - lg_row * 1.2
    msp.add_text("LAYER LEGEND", dxfattribs={'layer': 'C-TITLE-BLOCK', 'height': char_h * 0.95}) \
        .set_placement((lg_x0 + lg_row * 0.4, y))
    y -= lg_row * 1.3

    swatch_w = lg_row * 1.5
    for layer_name, meaning in legend_rows:
        # sample line drawn ON its own layer, so it carries that layer's colour
        # and linetype - the swatch is the layer, not a picture of it.
        msp.add_line((lg_x0 + lg_row * 0.4, y + lg_row * 0.22),
                     (lg_x0 + lg_row * 0.4 + swatch_w, y + lg_row * 0.22),
                     dxfattribs={'layer': layer_name})
        msp.add_text(f"{layer_name}  -  {meaning}",
                     dxfattribs={'layer': 'C-TITLE-BLOCK', 'height': dim_char_h * 0.92}) \
            .set_placement((lg_x0 + lg_row * 0.4 + swatch_w + lg_row * 0.5, y))
        y -= lg_row

    # ---- PLOT DATA (what an architect needs before massing) --------------
    y -= lg_row * 0.6
    msp.add_text("PLOT DATA", dxfattribs={'layer': 'C-TITLE-BLOCK', 'height': char_h * 0.95}) \
        .set_placement((lg_x0 + lg_row * 0.4, y))
    y -= lg_row * 1.25

    sb3 = "drawn" if setback_status.get(3.0) else "NOT VIABLE - plot too narrow"
    sb6 = "drawn" if setback_status.get(6.0) else "NOT VIABLE - plot too narrow"
    area_note = properties.get('area_source') or ''
    data_rows = [
        f"GROSS PLOT AREA : {properties.get('area_sqm')} sq m",
        f"AREA SOURCE     : {'DERIVED from boundary' if 'derived' in area_note else 'MCGM approved record'}",
        f"CTS / VILLAGE   : {properties.get('cts_no')} / {properties.get('village')}",
        f"WARD / ZONE     : {properties.get('ward')} / {properties.get('zone')}",
        f"ABUTTING ROAD   : {properties.get('abutting_road')} ({properties.get('road_width')})",
        f"CRZ STATUS      : {properties.get('crz_buffer_flag')}",
        f"METRO BUFFER    : {properties.get('metro_buffer_flag')}",
        f"3.0 m SETBACK   : {sb3}",
        f"6.0 m SETBACK   : {sb6}",
    ]
    for row in data_rows:
        msp.add_text(row, dxfattribs={'layer': 'C-TITLE-BLOCK', 'height': dim_char_h * 0.92}) \
            .set_placement((lg_x0 + lg_row * 0.4, y))
        y -= lg_row

    # ---- TITLE BLOCK (bottom of the legend column) -----------------------
    tb_h = lg_row * 7.2
    tb_y0 = b_min_y + scale * 0.05
    msp.add_lwpolyline(
        [(lg_x0, tb_y0), (lg_x0 + lg_w, tb_y0), (lg_x0 + lg_w, tb_y0 + tb_h), (lg_x0, tb_y0 + tb_h)],
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'closed': True})
    title_meta = (
        f"MCGM DEVELOPMENT PLAN 2034 - CAD BASE\n"
        f"PLOT: CTS {properties.get('cts_no')} ({properties.get('village')})\n"
        f"PURPOSE: Architectural concept & massing base\n"
        f"SCALE: 1:1 METRIC (1 CAD unit = 1 metre)\n"
        f"ORIGIN: Plot centroid (0.00, 0.00)\n"
        f"UTM 43N CENTROID: E {utm_cx:.2f} / N {utm_cy:.2f}\n"
        f"SETBACKS ARE INDICATIVE - confirm against DCPR 2034"
    )
    msp.add_mtext(title_meta, dxfattribs={'layer': 'C-TITLE-BLOCK', 'char_height': dim_char_h * 0.92}) \
        .set_location((lg_x0 + lg_row * 0.4, tb_y0 + tb_h - lg_row * 0.5))

    # Set Header Extents & Active Modelspace Viewport Zoom Framing for AutoCAD 2024
    doc.header['$EXTMIN'] = (b_min_x, b_min_y, 0)
    doc.header['$EXTMAX'] = (b_max_x, b_max_y, 0)
    doc.header['$LIMMIN'] = (b_min_x, b_min_y)
    doc.header['$LIMMAX'] = (b_max_x, b_max_y)
    
    try:
        doc.set_modelspace_vport(
            height=(b_max_y - b_min_y) * 1.08,
            center=((b_min_x + b_max_x) / 2.0, (b_min_y + b_max_y) / 2.0),
        )
    except Exception:
        pass
        
    doc.saveas(output_path)

def export_kml(wgs_rings: list, properties: dict, output_path: str):
    ring0 = wgs_rings[0]
    coords_str = " ".join(f"{p[0]},{p[1]},0" for p in ring0)
    
    # Every interpolated value is XML-escaped. An unescaped & or < in a village or
    # road name produced a KML that Google Earth refused to parse.
    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>CTS {_esc(properties.get('cts_no'))} ({_esc(properties.get('village'))}) DP Remark</name>
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
      <name>CTS {_esc(properties.get('cts_no'))} - {_esc(properties.get('village'))}</name>
      <styleUrl>#plotStyle</styleUrl>
      <ExtendedData>
        <Data name="Ward"><value>{_esc(properties.get('ward'))}</value></Data>
        <Data name="Zone"><value>{_esc(properties.get('zone'))}</value></Data>
        <Data name="Area_sqm"><value>{_esc(properties.get('area_sqm'))}</value></Data>
        <Data name="Status"><value>{_esc(properties.get('status_badge'))}</value></Data>
        <Data name="CRZ_Status"><value>{_esc(properties.get('crz_buffer_flag'))}</value></Data>
        <Data name="Metro_Buffer"><value>{_esc(properties.get('metro_buffer_flag'))}</value></Data>
        <Data name="Abutting_Road"><value>{_esc(properties.get('abutting_road'))} ({_esc(properties.get('road_width'))})</value></Data>
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

def build_pdf_doc(pdf_path, status_badge, status_summary, village, attrs, cts_number, zone, des_desc, des_code, mod_approval, mod_label, crz_buffer_flag, metro_buffer_flag, road_name, road_width, dp_snapshot_path, qr_bytes, map_link, sat_snapshot_path, neighbors, area_source_label="Approved cadastral area (MCGM record)"):
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
    banner_text = f"<b>STATUS: {_esc(status_badge)}</b> — {_esc(status_summary)}"
    banner_table = Table([[Paragraph(banner_text, ParagraphStyle('BText', parent=body_style, fontSize=9.5, leading=12))]], colWidths=[540])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), banner_color),
        ('PADDING', (0,0), (-1,-1), 5),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#BDBDBD')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 6))

    # ReportLab Paragraph parses a mini-XML markup language, so every DATA value is
    # escaped while the intentional <b>/<a> tags in the templates are left alone.
    # An unescaped & or < in a road name or modification label previously raised
    # during doc.build(), crashing the run after all network work had succeeded.
    mod_label_trimmed = mod_label[:60] + ('...' if len(mod_label) > 60 else '')
    table_data = [
        [Paragraph("<b>Attribute</b>", bold_style), Paragraph("<b>Details</b>", bold_style), Paragraph("<b>Planning Remarks</b>", bold_style)],
        [Paragraph("Village / Ward", body_style), Paragraph(f"{_esc(village.upper())} (Ward {_esc(attrs['WARD'])})", body_style), Paragraph("MCGM Administrative Division", body_style)],
        [Paragraph("Plot CTS No.", body_style), Paragraph(f"CTS {_esc(cts_number)} ({_esc(attrs['TYPE'])})", body_style), Paragraph("City Survey Cadastral Parcel", body_style)],
        [Paragraph("Plot Area", body_style), Paragraph(f"{_esc(attrs['AREA_APP_SQ_MTRS'])} sq m" if attrs['AREA_APP_SQ_MTRS'] else "Not on record", body_style), Paragraph(_esc(area_source_label), body_style)],
        [Paragraph("Land-Use Zone", body_style), Paragraph(f"<b>Zone {_esc(zone)}</b>", body_style), Paragraph("Primary Zoning Classification", body_style)],
        [Paragraph("PLU Designation", body_style), Paragraph(f"{_esc(des_desc)} ({_esc(des_code)})", body_style), Paragraph("Existing Amenity Designation", body_style)],
        [Paragraph("DP Modification", body_style), Paragraph(f"Approval: {_esc(mod_approval)}", body_style), Paragraph(_esc(mod_label_trimmed), body_style)],
        [Paragraph("CRZ Status", body_style), Paragraph(f"<b>{_esc(crz_buffer_flag)}</b>", body_style), Paragraph("Coastal Regulation Zone Layer Query", body_style)],
        [Paragraph("Metro Buffer", body_style), Paragraph(_esc(metro_buffer_flag), body_style), Paragraph("Layer 1550 Metro Rail Influence", body_style)],
        [Paragraph("Abutting Road", body_style), Paragraph(f"<b>{_esc(road_name)}</b> ({_esc(road_width)})", body_style), Paragraph("DP 2034 Road Access &amp; Width", body_style)],
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
        Paragraph(f"<a href='{_esc(map_link)}'>Open ArcGIS Web Map</a>", ParagraphStyle('Link', parent=body_style, textColor=colors.blue, fontSize=8))
    ]
    
    media_table = Table([[dp_img_rl, qr_cell]], colWidths=[370, 170])
    media_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'CENTER'),
    ]))
    story.append(media_table)

    story.append(PageBreak())
    story.append(Paragraph("<b>HIGH-RESOLUTION SATELLITE & ADJOINING PLOT CLUSTER ANALYSIS</b>", title_style))
    story.append(Paragraph(f"Official Spatial Query Report | Page 2 of 2 | Plot CTS {_esc(cts_number)} ({_esc(village.upper())})", subtitle_style))
    story.append(Spacer(1, 8))

    sat_img_rl = RLImage(sat_snapshot_path, width=540, height=340)
    story.append(sat_img_rl)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Adjoining / Neighboring CTS Parcels (Spatial Cluster):</b>", ParagraphStyle('H2', parent=bold_style, fontSize=10, textColor=colors.HexColor('#1A237E'))))
    story.append(Spacer(1, 4))

    adj_table_data = [[Paragraph("<b>Adjoining CTS No.</b>", bold_style), Paragraph("<b>Village</b>", bold_style), Paragraph("<b>Plot Area (sq m)</b>", bold_style)]]
    for n in neighbors[:8]:
        adj_table_data.append([
            Paragraph(f"CTS {_esc(n['cts_no'])}", body_style),
            Paragraph(_esc(n['village'].upper()), body_style),
            Paragraph(f"{_esc(n['area_sqm'])} sq m" if n['area_sqm'] != 'N/A' else "N/A", body_style)
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

async def lookup_plot_pro(
    village: str,
    cts_number: str,
    output_dir: str = "./output",
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    timeout_seconds: float = 20.0,
) -> Dict[str, Any]:
    """
    Ultra-Fast Enterprise DP Plot Lookup Pro Tool (AutoCAD DXF + GeoJSON + KML Exports).

    use_cache          - set False to force a fresh network lookup.
    cache_ttl_seconds  - entries older than this are refetched. Negative disables expiry.
    timeout_seconds    - per-request timeout. The default was 10s, which the 24-request
                         batch regularly exceeded, producing silently degraded reports.
    """
    try:
        safe_village = sanitize_query_value(village, _VILLAGE_RE, "village", 64)
        safe_cts = sanitize_query_value(cts_number, _CTS_RE, "cts_number", 32)
    except ValueError as exc:
        return {"error": str(exc)}

    village_upper = safe_village.upper()
    cache_key = f"{village_upper}:{safe_cts}"

    os.makedirs(output_dir, exist_ok=True)

    if use_cache:
        t_cache = time.perf_counter()
        cached_res = read_cache_entry(output_dir, cache_key, cache_ttl_seconds)
        if cached_res is not None:
            # Report the real retrieval time. Previously this was hardcoded to 12.0,
            # and leaving it unset would replay the original cold run's duration -
            # either way the number would be fiction.
            cached_res["metadata"]["execution_time_ms"] = round((time.perf_counter() - t_cache) * 1000, 2)
            cached_res["metadata"]["cached_result"] = True
            age = cached_res["metadata"].get("cache_age_days", 0)
            print(
                f"[dp-lookup-pro] Serving cached report from "
                f"{cached_res['metadata'].get('cached_at')} ({age} days old). "
                f"Use --no-cache for a fresh check."
            )
            return cached_res

    t_start = time.perf_counter()
    register_path = os.path.join(output_dir, "dp-lookups.xlsx")

    # warnings = fetch failures. A run carrying any of these is never cached.
    # notes    = deterministic facts about the data itself (e.g. an area derived
    #            from geometry because MCGM has none on record). Informational
    #            only, and safe to cache.
    warnings: List[str] = []
    notes: List[str] = []

    limits = httpx.Limits(max_keepalive_connections=30, max_connections=50)
    async with httpx.AsyncClient(http2=True, timeout=timeout_seconds, limits=limits, follow_redirects=True) as client:
        query_params = {
            "where": f"VILLAGE='{village_upper}' AND CTS_CS_NO='{safe_cts}'",
            "outFields": "WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS,SHAPE.AREA",
            "returnGeometry": "true",
            "outSR": "102100",
            "f": "json",
        }
        try:
            resp = await client.get(f"{SERVER_URL}/13/query", params=query_params)
        except httpx.HTTPError as exc:
            # httpx timeout/connect errors often stringify to "", which tells the
            # user nothing. Always name the failure type.
            detail = str(exc).strip() or type(exc).__name__
            return {
                "error": (
                    f"Could not reach the MCGM map server ({detail}). "
                    "The server rate-limits sustained bursts - wait a few seconds and retry."
                )
            }

        data = usable_json(resp)
        if data is None:
            return {
                "error": (
                    "The MCGM map server rejected the parcel query "
                    f"(HTTP {getattr(resp, 'status_code', 'unknown')}). Try again shortly."
                )
            }

        if not data.get("features"):
            return {
                "error": (
                    f"Plot not found for CTS '{cts_number}' in village '{village}'. "
                    "Village must be one of the 128 exact MCGM names "
                    "(e.g. BANDRA-A, not BANDRA) - see START-HERE.md."
                )
            }

        feature = data["features"][0]
        attrs = feature["attributes"]
        rings = feature["geometry"]["rings"]

        # Plot area. MCGM leaves AREA_APP_SQ_MTRS null on a meaningful number of
        # parcels (MALABAR HILL 518, TARDEO 264, ...). SHAPE.AREA - the digitised
        # polygon's own area - is populated there and is already in true ground
        # square metres (verified: it matches AREA_APP_SQ_MTRS exactly on plots
        # where both exist). It is NOT the same authority though: it is the drawn
        # area, not the approved cadastral one, and the two can differ by several
        # percent. So fall back to it, but always say which one is being reported.
        approved_area = attrs.get("AREA_APP_SQ_MTRS")
        geometry_area = attrs.get("SHAPE.AREA")
        if approved_area not in (None, "", 0):
            area_sqm = approved_area
            area_source = "approved (MCGM AREA_APP_SQ_MTRS)"
        elif isinstance(geometry_area, (int, float)) and geometry_area > 0:
            area_sqm = round(float(geometry_area), 2)
            area_source = "derived from plot geometry - MCGM has no approved area on record"
            notes.append(
                "MCGM has no approved area for this plot; area is derived from the "
                "digitised boundary and is indicative only"
            )
        else:
            area_sqm = None
            area_source = "unavailable"
        # Keep attrs consistent for the downstream renderers.
        attrs["AREA_APP_SQ_MTRS"] = area_sqm
        
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

        cts_clean = str(cts_number).replace('/', '-').replace('\\', '-')
        village_clean = village.lower().strip().replace('/', '-').replace('\\', '-').replace(' ', '_')
        query_folder_name = f"{village_clean}_cts_{cts_clean}"
        query_dir = os.path.join(output_dir, query_folder_name)
        os.makedirs(query_dir, exist_ok=True)

        # CRZ *zone polygons* — not boundary lines.
        # Previously this list held only line features (High Tide Line, Low Tide Line,
        # CRZ Lines & Boundaries, etc). A point-identify at a plot centroid can never
        # intersect a line, so the check could only ever return NO — a silent false
        # negative on every CRZ-affected plot.
        # Layer 14 carries the sub-tier in its `category` attribute (I / II / III / IV);
        # 1264 and 1548 corroborate. Layer 2238 ("Coastal Districts having CRZ") stays
        # excluded: it is district-wide and flags every plot in Mumbai as CRZ.
        crz_restriction_layer_ids = [14, 1264, 1548]

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
                "f": "image",
            }
        )

        # Road sampling: probe just OUTSIDE each boundary edge, where roads actually run.
        #
        # Two things were wrong here before:
        #  1) Two /query calls against layers 193 & 194 sent a polygon geometry. Those
        #     layers have spatial querying disabled server-side and answer HTTP 200 with
        #     an {"error": {"code": 400}} body for EVERY geometry type, so they never
        #     returned a road. The parser reads .get("features", []) and saw an empty
        #     list, silently reporting "no road". Both calls are removed.
        #  2) The remaining probes were the centroid and two BOUNDING-BOX corners. On an
        #     irregular parcel those corners sit outside the polygon entirely, and the
        #     centroid can be far from any frontage, so abutting roads were missed.
        #
        # Now: the centroid plus the midpoints of the longest boundary edges, each nudged
        # ~6 units outward along the edge normal. Longest edges first, since frontage is
        # normally the long side of a plot.
        outer_ring = rings[0]
        edge_probes = []
        for i in range(len(outer_ring)):
            p1 = outer_ring[i]
            p2 = outer_ring[(i + 1) % len(outer_ring)]
            ex, ey = p2[0] - p1[0], p2[1] - p1[1]
            seg_len = math.hypot(ex, ey)
            if seg_len <= 0.01:
                continue
            emx, emy = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
            enx, eny = -ey / seg_len, ex / seg_len
            # flip the normal so it points away from the parcel centre
            if (emx + enx - mcx) ** 2 + (emy + eny - mcy) ** 2 < (emx - mcx) ** 2 + (emy - mcy) ** 2:
                enx, eny = -enx, -eny
            edge_probes.append((seg_len, (emx + enx * 6.0, emy + eny * 6.0)))

        edge_probes.sort(key=lambda e: e[0], reverse=True)
        # Keep the original centroid + bounding-box corner probes as well. They are
        # coarse, but on some parcels a corner lands nearer the frontage than any edge
        # midpoint does, so dropping them regressed named-road detection. Additive:
        # more probes can only widen coverage, and road_map de-duplicates the results.
        road_sample_pts = [
            (mcx, mcy),
            (min(xs), min(ys)),
            (max(xs), max(ys)),
        ] + [pt for _, pt in edge_probes[:6]]

        road_tasks = [
            client.post(f"{SERVER_URL}/identify", data={"geometry": f"{px},{py}", "geometryType": "esriGeometryPoint", "sr": "102100", "layers": "visible:193,194,44,45", "tolerance": "40", "mapExtent": f"{mcx-d},{mcy-d},{mcx+d},{mcy+d}", "imageDisplay": "1000,1000,96", "returnGeometry": "true", "f": "json"})
            for px, py in road_sample_pts
        ]

        # Optimize neighbor query sample points to 4 cardinal offset points around parcel
        off_d = max(15.0, d * 0.7)
        neighbor_sample_pts = [
            (mcx + off_d, mcy),
            (mcx - off_d, mcy),
            (mcx, mcy + off_d),
            (mcx, mcy - off_d)
        ]
        neighbor_tasks = [
            client.post(f"{SERVER_URL}/identify", data={"geometry": f"{px},{py}", "geometryType": "esriGeometryPoint", "sr": "102100", "layers": "visible:13", "tolerance": "30", "mapExtent": f"{mcx-d},{mcy-d},{mcx+d},{mcy+d}", "imageDisplay": "1000,1000,96", "returnGeometry": "true", "f": "json"})
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
        road_geoms = []          # polylines in WGS84, for the DXF road layer
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
                    r_name, r_w = r_attrs.get('ROAD_NAME'), r_attrs.get('WIDTH_RL')
                    if r_name or r_w:
                        road_map[f"{r_name}|{r_w}"] = {'name': r_name or 'Road', 'width': r_w or 'N/A'}
                for item in j.get('results', []):
                    r_attrs = item.get('attributes', {})
                    r_name = r_attrs.get('ROAD_NAME') or r_attrs.get('TYPE_')
                    r_w = r_attrs.get('WIDTH_RL') or r_attrs.get('WIDTH')
                    if r_name or r_w:
                        road_map[f"{r_name}|{r_w}"] = {'name': r_name or 'Road', 'width': r_w or 'N/A'}
                    # Road layers are mixed geometry: 193/194 are polylines and
                    # return 'paths'; 44/45 are road polygons and return 'rings'.
                    # Reading only 'paths' left C-ROAD-ALIGN empty on any plot
                    # whose frontage came from the polygon layers.
                    r_geom = item.get('geometry', {}) or {}
                    for part in (r_geom.get('paths') or []) + (r_geom.get('rings') or []):
                        if len(part) >= 2:
                            road_geoms.append([
                                [round((pt[0] / R) * 180, 7),
                                 round((math.atan(math.exp(pt[1] / R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi, 7)]
                                for pt in part
                            ])

        if road_failures:
            warnings.append(
                f"{road_failures} of {len(road_sample_pts)} road probes failed; "
                "abutting road may be incomplete"
            )

        named_roads = [r for r in road_map.values() if r['name'] != 'Exisiting Road' and r['width'] != 'N/A']
        roads = named_roads if named_roads else list(road_map.values())
        road_name = roads[0]["name"] if roads else "None"
        road_width = roads[0]["width"] if roads else "None"

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
                    # Identify returns Web Mercator (sr=102100). export_dxf expects
                    # WGS84 degrees like the main plot ring - without this the
                    # adjoining plots were drawn at ~8e11, far outside the sheet.
                    n_rings = [
                        [
                            [round((pt[0] / R) * 180, 7),
                             round((math.atan(math.exp(pt[1] / R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi, 7)]
                            for pt in nr
                        ]
                        for nr in (n_geom.get('rings', []) or [])
                    ]
                    if c_no and str(c_no) != str(cts_number):
                        neighbors_map[c_no] = {
                            'cts_no': str(c_no),
                            'village': str(v_name),
                            'area_sqm': str(n_area) if n_area else 'N/A',
                            'rings': n_rings
                        }
        if neighbor_failures:
            warnings.append(
                f"{neighbor_failures} of {len(neighbor_sample_pts)} neighbour probes failed; "
                "adjoining plot list may be incomplete"
            )

        neighbors = list(neighbors_map.values())

        # Parse Identify.
        #
        # This call carries zone, reservation, designation, DP modification, metro
        # and CRZ - i.e. every planning remark in the report. If it FAILED we must
        # not continue: the defaults (zone 'Unknown', CRZ 'NO', no reservation) are
        # indistinguishable from a genuinely clear plot, and a full PDF docket built
        # on them looks authoritative. Fail loudly instead.
        ident_json = usable_json(ident_resp)
        if ident_json is None:
            return {
                "error": (
                    "Planning data could not be retrieved from the MCGM map server "
                    "(the identify request failed or timed out). No report was generated, "
                    "because a partial one would understate zoning, reservations and CRZ status. "
                    "Please retry."
                ),
                "partial_data": {
                    "village": village_upper,
                    "cts_no": str(cts_number),
                    "ward": str(attrs.get("WARD")),
                    "area_sqm": attrs.get("AREA_APP_SQ_MTRS"),
                },
            }

        results = ident_json.get("results", [])
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

        # Report the CRZ sub-tier (CRZ I / II / III / IV) rather than a bare YES.
        # Attribute name varies by layer: 14 -> `category` ("II"), 1548 -> `Category`,
        # 1264 -> `CLASS` (already "CRZ II").
        crz_tier = None
        if crz_item:
            crz_attrs = crz_item.get("attributes", {})
            for key in ("category", "Category", "CATEGORY", "CLASS", "Class"):
                val = crz_attrs.get(key)
                if val and str(val).strip().lower() not in ("", "null", "none"):
                    crz_tier = str(val).strip()
                    break

        if not crz_item:
            crz_buffer_flag = "NO (Outside CRZ Buffer)"
        elif crz_tier:
            tier = crz_tier if crz_tier.upper().startswith("CRZ") else f"CRZ {crz_tier}"
            crz_buffer_flag = f"YES ({tier})"
        else:
            crz_buffer_flag = f"YES ({crz_item.get('layerName')})"

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
        dp_map_ok = (
            not isinstance(dp_snap_resp, Exception)
            and getattr(dp_snap_resp, "status_code", None) == 200
            and dp_snap_resp.headers.get("content-type", "").startswith("image")
        )
        if dp_map_ok:
            dp_img = Image.open(io.BytesIO(dp_snap_resp.content)).convert("RGBA")
        else:
            warnings.append("DP base map could not be fetched; the map image is a blank placeholder")
            dp_img = Image.new("RGBA", (W, H), (240, 240, 240, 255))
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
        missing_tiles = 0
        if isinstance(sat_tile_bytes, Exception):
            missing_tiles = len(sat_coords)
        else:
            missing_tiles = sum(1 for b in sat_tile_bytes if isinstance(b, Exception) or not b)
        if missing_tiles:
            warnings.append(f"{missing_tiles} of {len(sat_coords)} satellite tiles failed to load")
        if not isinstance(sat_tile_bytes, Exception):
            for (gx, gy), b in zip(sat_coords, sat_tile_bytes):
                if b and not isinstance(b, Exception):
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
            "area_source": area_source,
            "adjoining_cts_plots_count": len(neighbors),
            "map_link": map_link
        }

        export_geojson(wgs_rings, export_props, geojson_path)
        export_dxf(wgs_rings, export_props, dxf_path, neighbors=neighbors, roads=road_geoms[:6])
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
            pdf_path, status_badge, status_summary, village, attrs, cts_number, zone, des_desc, des_code, mod_approval, mod_label, crz_buffer_flag, metro_buffer_flag, road_name, road_width, dp_snapshot_path, qr_bytes, map_link, sat_snapshot_path, neighbors,
            ("Approved cadastral area (MCGM record)"
             if area_source.startswith("approved")
             else "DERIVED from plot boundary - no approved area on MCGM record")
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
                "area_sqm": area_sqm,
                "area_source": area_source,
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
                "adjoining_cts_plots": [
                    {k: v for k, v in n.items() if k != 'rings'} for n in neighbors
                ]
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
                "complete": not warnings,
                "warnings": warnings,
                "notes": notes,
                "interactive_web_map": map_link
            }
        }

        # Only a clean run earns a cache entry. Caching a degraded result used to
        # freeze a transient network failure into a permanent authoritative answer.
        if warnings:
            print(f"[dp-lookup-pro] WARNING: result incomplete, not cached - {'; '.join(warnings)}")
        else:
            write_cache_entry(output_dir, cache_key, result_dict)

        return result_dict


USAGE = """Usage: dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER> [OUTPUT_DIR] [--no-cache]

Examples:
  dp-lookup-pro WORLI 947
  dp-lookup-pro "MALABAR HILL" "16/738"
  dp-lookup-pro BANDRA-A 409 ./client-reports --no-cache

Village must be one of the 128 exact MCGM revenue village names
(e.g. BANDRA-A, not BANDRA). See START-HERE.md for the full list."""


def main(argv: Optional[List[str]] = None) -> int:
    """Console entry point. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)

    use_cache = True
    for flag in ("--no-cache", "--fresh"):
        if flag in args:
            args.remove(flag)
            use_cache = False

    # Tolerate the conversational form: "WORLI CTS 947"
    if len(args) >= 3 and args[1].upper() in ("CTS", "CS", "PLOT", "NO", "NO."):
        args = [args[0], args[2]] + args[3:]

    if len(args) < 2:
        print(USAGE)
        return 1

    village, cts_number = args[0], args[1]
    output_dir = args[2] if len(args) > 2 else "./output"

    print(
        f"[dp-lookup-pro] Looking up village '{village}', CTS '{cts_number}'"
        f"{' (cache bypassed)' if not use_cache else ''}..."
    )
    result = asyncio.run(
        lookup_plot_pro(
            village=village,
            cts_number=cts_number,
            output_dir=output_dir,
            use_cache=use_cache,
        )
    )
    print("\n" + json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
