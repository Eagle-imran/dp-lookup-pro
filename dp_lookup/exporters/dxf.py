"""
AutoCAD DXF Exporter with Precision Scaling, Layer Weights, and Text Collision Prevention.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import Polygon
from shapely.geometry.base import BaseMultipartGeometry

from dp_lookup.core.geometry import wgs84_to_utm43n

# name, ACI colour, linetype, lineweight (1/100 mm).
DXF_LAYERS = (
    ("0_GRID_AXIS", 8, "DASHED", 9),
    ("C-PLOT-BDY", 1, None, 50),
    ("C-PROP-HATCH", 252, None, 9),
    ("C-SETBACK-3M", 3, "DASHED", 25),
    ("C-SETBACK-6M", 70, "DASHED", 25),
    ("C-ADJN-PLOTS", 2, None, 13),
    ("C-ROAD-ALIGN", 4, "DASHED", 35),
    ("C-RESTRICT-ZONE", 6, "PHANTOM", 35),
    ("C-ANNO-TEXT", 7, None, 13),
    ("C-ANNO-DIMS", 5, None, 13),
    ("C-NORTH-ARROW", 7, None, 18),
    ("C-TITLE-BLOCK", 4, None, 18),
)

METRES_PER_DEG_LAT = 111132.0
METRES_PER_DEG_LON_EQUATOR = 111319.5

DXF_LEGEND_ROWS = (
    ('C-PLOT-BDY',      'PLOT BOUNDARY - gross plot area'),
    ('C-PROP-HATCH',    'Gross plot area (fill)'),
    ('C-ROAD-ALIGN',    'Abutting road alignment / frontage'),
    ('C-SETBACK-3M',    '3.0 m setback line (true parallel offset)'),
    ('C-SETBACK-6M',    '6.0 m setback line (true parallel offset)'),
    ('C-RESTRICT-ZONE', 'CRZ / Metro restriction (advisory note)'),
    ('C-ADJN-PLOTS',    'Adjoining CTS plots'),
    ('C-ANNO-DIMS',     'Boundary segment dimensions (m)'),
    ('C-ANNO-TEXT',     'Plot metadata'),
    ('C-NORTH-ARROW',   'True north'),
    ('0_GRID_AXIS',     'Metric grid, 0,0 at plot centroid'),
    ('C-TITLE-BLOCK',   'Sheet border, legend, title block'),
)

LEGEND_PAD_ROWS = 4.15
LEGEND_VALUE_MAX_CHARS = 34


def polygon_signed_area(ring: list) -> float:
    """Shoelace formula. Positive = counter-clockwise winding."""
    n = len(ring)
    return sum(
        ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1]
        for i in range(n)
    ) / 2.0


def offset_polygon_inward(ring: list, distance: float) -> list:
    """True parallel inward offset of a closed polygon using Shapely."""
    pts = list(ring)
    if len(pts) > 1 and math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-9) and math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-9):
        pts = pts[:-1]
    if len(pts) < 3 or distance <= 0:
        return []

    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        shrunk = poly.buffer(-abs(distance), join_style=2)
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


def new_dxf_document(has_reservations: bool = False) -> ezdxf.document.Drawing:
    """R2010 document in metric units with the project's layer table."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    doc.header["$MEASUREMENT"] = 1
    try:
        doc.linetypes.add("DASHED", pattern="A, 1.0, -0.5")
        doc.linetypes.add("PHANTOM", pattern="A, 2.0, -0.5, 0.5, -0.5, 0.5, -0.5")
    except Exception:
        pass
    for name, colour, linetype, lineweight in DXF_LAYERS:
        attrs = {"name": name, "color": colour, "lineweight": lineweight}
        if linetype:
            attrs["linetype"] = linetype
        doc.layers.add(**attrs)
    if has_reservations:
        try:
            doc.layers.add(name="C-RESERVATIONS", color=6, linetype="DASHED", lineweight=25)
        except Exception:
            pass
    return doc


def project_rings_to_local_metres(wgs_rings: list) -> Dict[str, Any]:
    """WGS84 degrees to local metres with the plot centroid at (0, 0)."""
    r0 = wgs_rings[0]
    lon0 = sum(p[0] for p in r0) / len(r0)
    lat0 = sum(p[1] for p in r0) / len(r0)
    mpd_lon = METRES_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat0))
    mpd_lat = METRES_PER_DEG_LAT

    return {
        "lon0": lon0, "lat0": lat0,
        "mpd_lon": mpd_lon, "mpd_lat": mpd_lat,
        "local_rings": [[((p[0] - lon0) * mpd_lon, (p[1] - lat0) * mpd_lat) for p in ring]
                        for ring in wgs_rings],
    }


def to_local_metres(points: list, lon0: float, lat0: float, mpd_lon: float, mpd_lat: float) -> list:
    """Project an arbitrary WGS84 ring/path into the same local frame."""
    return [((p[0] - lon0) * mpd_lon, (p[1] - lat0) * mpd_lat) for p in points]


def clip_segment_to_box(p1: tuple, p2: tuple, x_lo: float, y_lo: float, x_hi: float, y_hi: float) -> Optional[tuple]:
    """Liang-Barsky segment clipping against bounding box."""
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - x_lo), (dx, x_hi - x1), (-dy, y1 - y_lo), (dy, y_hi - y1)):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                t0 = max(t0, r)
            else:
                if r < t0:
                    return None
                t1 = min(t1, r)
    return ((x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy))


def clip_path_to_window(path: list, x_lo: float, y_lo: float, x_hi: float, y_hi: float) -> List[list]:
    """Contiguous runs of path clipped to the window."""
    runs: List[list] = []
    run: list = []
    for i in range(len(path) - 1):
        seg = clip_segment_to_box(path[i], path[i + 1], x_lo, y_lo, x_hi, y_hi)
        if seg is None:
            if run:
                runs.append(run)
                run = []
            continue
        start, end = seg
        if run and abs(run[-1][0] - start[0]) < 1e-9 and abs(run[-1][1] - start[1]) < 1e-9:
            run.append(end)
        else:
            if run:
                runs.append(run)
            run = [start, end]
    if run:
        runs.append(run)
    return runs


def fit_label_to_width(template: str, value: str, max_width: float, char_h: float, min_value_chars: int = 8) -> str:
    """Fit text label inside bounding budget."""
    per_char = max(char_h, 1e-6) * 0.72
    budget = int(max_width / per_char) - len(template.format(""))
    if budget >= len(value):
        return template.format(value)
    keep = max(min_value_chars, budget - 3)
    return template.format(value[:keep].rstrip(" ,.") + "...")


def text_extents(entity: Any) -> Optional[Tuple[float, float, float, float]]:
    """(x0, y0, x1, y1) of a TEXT entity as it will actually render."""
    try:
        from ezdxf.tools.text_size import text_size
        size = text_size(entity)
        w, h = size.width, size.cap_height
    except Exception:
        try:
            h = float(entity.dxf.height)
            w = len(entity.dxf.text) * h * 0.72
        except Exception:
            return None

    halign = int(getattr(entity.dxf, "halign", 0) or 0)
    valign = int(getattr(entity.dxf, "valign", 0) or 0)
    try:
        if (halign or valign) and entity.dxf.hasattr("align_point"):
            anchor = entity.dxf.align_point
        else:
            anchor = entity.dxf.insert
        x, y = float(anchor[0]), float(anchor[1])
    except Exception:
        return None

    ox = -w * {1: 0.5, 2: 1.0, 4: 0.5}.get(halign, 0.0)
    oy = -h * (0.5 if halign == 4 else {2: 0.5, 3: 1.0}.get(valign, 0.0))

    rot = math.radians(float(getattr(entity.dxf, "rotation", 0.0) or 0.0))
    if not rot:
        return (x + ox, y + oy, x + ox + w, y + oy + h)
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    pts = [(x + dx * cos_r - dy * sin_r, y + dx * sin_r + dy * cos_r)
           for dx, dy in ((ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h))]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def boxes_overlap(a: Optional[tuple], b: Optional[tuple], slack: float = 0.0) -> bool:
    """True when two (x0, y0, x1, y1) boxes intersect."""
    if a is None or b is None:
        return False
    return not (a[2] + slack < b[0] or b[2] + slack < a[0] or a[3] + slack < b[1] or b[3] + slack < a[1])


def nudge_text_clear(entity: Any, obstacles: list, step: float, direction: tuple = (0.0, 1.0), limit: int = 10) -> bool:
    """Shift label along direction until it stops overlapping anything in obstacles."""
    if step <= 0:
        return True
    dx, dy = direction
    for _ in range(limit + 1):
        box = text_extents(entity)
        if box is None:
            return True
        if not any(boxes_overlap(box, other) for other in obstacles):
            return True
        ins = entity.dxf.insert
        entity.set_placement((float(ins[0]) + dx * step, float(ins[1]) + dy * step))
    return False


def dxf_title_block_lines(properties: Dict[str, Any], utm_cx: float, utm_cy: float) -> List[str]:
    """Title block metadata lines."""
    return [
        "MCGM DEVELOPMENT PLAN 2034 - CAD BASE",
        f"PLOT: CTS {properties.get('cts_no')} ({properties.get('village')})",
        "PURPOSE: Architectural concept & massing base",
        "SCALE: 1:1 METRIC (1 CAD unit = 1 metre)",
        "ORIGIN: Plot centroid (0.00, 0.00)",
        f"UTM 43N CENTROID: E {utm_cx:.2f} / N {utm_cy:.2f}",
        "SETBACKS ARE INDICATIVE - confirm against DCPR 2034",
        "PLOT AREA PER PROPERTY CARD MAY DIFFER FROM THE MCGM",
        "RECORD - reconcile both before any FSI calculation",
    ]


def title_block_height(lg_row: float, n_lines: int) -> float:
    return lg_row * (n_lines + 1.2)


def legend_column_height(lg_row: float, n_legend: int, n_data: int) -> float:
    return lg_row * (n_legend + n_data + LEGEND_PAD_ROWS)


def legend_data_row(label: str, value: Any) -> List[str]:
    text = str(value)
    if len(text) <= LEGEND_VALUE_MAX_CHARS:
        return [f"{label:<16}: {text}"]
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > LEGEND_VALUE_MAX_CHARS:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return [f"{label:<16}: {lines[0]}"] + [f"{'':<16}  {ln}" for ln in lines[1:]]


def legend_data_rows(
    properties: Dict[str, Any],
    setback_status: Dict[float, bool],
    measured_area_sqm: Optional[float] = None,
) -> List[str]:
    sb3 = "drawn" if setback_status.get(3.0) else "NOT VIABLE - plot too narrow"
    sb6 = "drawn" if setback_status.get(6.0) else "NOT VIABLE - plot too narrow"
    area_note = properties.get('area_source') or ''
    derived = 'derived' in area_note
    record_area = properties.get('area_sqm')

    rows = legend_data_row("GROSS PLOT AREA", f"{record_area} sq m")
    rows += legend_data_row(
        "AREA SOURCE", "DERIVED from boundary" if derived else "MCGM approved record")
    if measured_area_sqm:
        delta = ""
        if not derived and isinstance(record_area, (int, float)) and record_area:
            pct = (measured_area_sqm - record_area) / record_area * 100.0
            delta = f"  ({pct:+.2f}% vs record)"
        rows += legend_data_row("MEASURED (BDY)", f"{measured_area_sqm:.2f} sq m{delta}")
    rows += legend_data_row(
        "CTS / VILLAGE", f"{properties.get('cts_no')} / {properties.get('village')}")
    rows += legend_data_row(
        "WARD / ZONE", f"{properties.get('ward')} / {properties.get('zone')}")
    rows += legend_data_row(
        "ABUTTING ROAD",
        f"{properties.get('abutting_road')} ({properties.get('road_width')})")

    crz_value = properties.get('crz_buffer_flag')
    if str(crz_value or '').upper().startswith('YES'):
        crz_value = f"{crz_value} - verify with MCGM/MCZMA"
    rows += legend_data_row("CRZ STATUS", crz_value)
    rows += legend_data_row("METRO BUFFER", properties.get('metro_buffer_flag'))
    rows += legend_data_row("3.0 m SETBACK", sb3)
    rows += legend_data_row("6.0 m SETBACK", sb6)
    enc_pct = properties.get("encumbered_percent")
    if enc_pct is not None and enc_pct > 0:
        enc_sqm = properties.get("encumbered_area_sqm", 0.0)
        net_sqm = properties.get("net_unencumbered_sqm", 0.0)
        rows += legend_data_row("ENCUMBERED", f"{enc_pct:.1f}% ({enc_sqm:,.1f} sq m)")
        rows += legend_data_row("NET DEVELOPABLE", f"{net_sqm:,.1f} sq m")
    return rows


def draw_dxf_legend_column(
    msp: Any,
    properties: Dict[str, Any],
    setback_status: Dict[float, bool],
    utm_cx: float,
    utm_cy: float,
    lg_x0: float,
    lg_w: float,
    b_max_y: float,
    b_min_y: float,
    char_h: float,
    dim_char_h: float,
    scale: float,
    data_rows: Optional[List[str]] = None,
) -> float:
    if data_rows is None:
        data_rows = legend_data_rows(properties, setback_status)

    lg_row = max(char_h * 1.9, 2.2)
    left = lg_x0 + lg_row * 0.4
    lg_y1 = b_max_y - scale * 0.05
    right_edge = lg_x0 + lg_w
    emitted = []

    def place(text: str, height: float, x: float, y: float):
        entity = msp.add_text(
            text, dxfattribs={'layer': 'C-TITLE-BLOCK', 'height': height})
        entity.set_placement((x, y))
        emitted.append(entity)
        return entity

    # ---- LEGEND ----------------------------------------------------------
    y = lg_y1 - lg_row * 1.2
    place("LAYER LEGEND", char_h * 0.95, left, y)
    y -= lg_row * 1.3

    swatch_w = lg_row * 1.5
    for layer_name, meaning in DXF_LEGEND_ROWS:
        msp.add_line((left, y + lg_row * 0.22),
                     (left + swatch_w, y + lg_row * 0.22),
                     dxfattribs={'layer': layer_name})
        place(f"{layer_name}  -  {meaning}", dim_char_h * 0.92,
              left + swatch_w + lg_row * 0.5, y)
        y -= lg_row

    # ---- PLOT DATA -------------------------------------------------------
    y -= lg_row * 0.6
    place("PLOT DATA", char_h * 0.95, left, y)
    y -= lg_row * 1.25

    for row in data_rows:
        place(row, dim_char_h * 0.92, left, y)
        y -= lg_row

    measured_right = right_edge
    for entity in emitted:
        box = text_extents(entity)
        if box:
            measured_right = max(measured_right, box[2])
    lg_x1 = measured_right + lg_row * 0.4
    lg_y0 = min(y + lg_row - lg_row * 0.8,
                lg_y1 - legend_column_height(lg_row, len(DXF_LEGEND_ROWS), len(data_rows)))
    msp.add_lwpolyline(
        [(lg_x0, lg_y0), (lg_x1, lg_y0), (lg_x1, lg_y1), (lg_x0, lg_y1)],
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'closed': True})

    # ---- TITLE BLOCK -----------------------------------------------------
    title_lines = dxf_title_block_lines(properties, utm_cx, utm_cy)
    tb_char_h = dim_char_h * 0.92
    tb_h = title_block_height(lg_row, len(title_lines))
    tb_y0 = b_min_y + scale * 0.05
    tb_x1 = lg_x1
    mtext = msp.add_mtext(
        "\n".join(title_lines),
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'char_height': tb_char_h})
    mtext.set_location((left, tb_y0 + tb_h - lg_row * 0.5))
    msp.add_lwpolyline(
        [(lg_x0, tb_y0), (tb_x1, tb_y0), (tb_x1, tb_y0 + tb_h), (lg_x0, tb_y0 + tb_h)],
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'closed': True})

    return lg_x1


def export_dxf(
    wgs_rings: list,
    properties: dict,
    output_path: str,
    neighbors: Optional[list] = None,
    roads: Optional[list] = None,
    reservations: Optional[list] = None,
    designations: Optional[list] = None,
) -> None:
    """
    Generates a scale-accurate Multi-Layered AutoCAD DXF CAD drawing file (.dxf)
    centered around Local Origin (0, 0) in Real-World Metric Meters (1 CAD Unit = 1 Meter).
    """
    has_res = bool((reservations or []) + (designations or []))
    doc = new_dxf_document(has_reservations=has_res)
    msp = doc.modelspace()

    proj = project_rings_to_local_metres(wgs_rings)
    lon0, lat0 = proj["lon0"], proj["lat0"]
    meters_per_deg_lon, meters_per_deg_lat = proj["mpd_lon"], proj["mpd_lat"]
    local_rings = proj["local_rings"]

    lr0 = local_rings[0]
    all_x = [p[0] for p in lr0]
    all_y = [p[1] for p in lr0]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    utm_cx, utm_cy = wgs84_to_utm43n(lon0, lat0)

    cx, cy = 0.0, 0.0
    width = max_x - min_x
    height = max_y - min_y
    scale = max(width, height, 30.0)
    char_h = max(1.2, scale * 0.035)
    dim_char_h = max(0.9, scale * 0.025)

    # 2. 0_GRID_AXIS: Metric Axis Grid scaled to plot dimensions
    if scale > 1000:
        grid_step = 500.0
    elif scale > 400:
        grid_step = 200.0
    elif scale > 150:
        grid_step = 100.0
    elif scale > 60:
        grid_step = 50.0
    else:
        grid_step = 25.0
    g_min_x = math.floor((min_x - scale * 0.25) / grid_step) * grid_step
    g_max_x = math.ceil((max_x + scale * 0.25) / grid_step) * grid_step
    g_min_y = math.floor((min_y - scale * 0.25) / grid_step) * grid_step
    g_max_y = math.ceil((max_y + scale * 0.25) / grid_step) * grid_step

    placed_boxes = []

    gx = g_min_x
    while gx <= g_max_x:
        msp.add_line((gx, g_min_y), (gx, g_max_y), dxfattribs={'layer': '0_GRID_AXIS'})
        lbl = msp.add_text(f"{int(gx)}m", dxfattribs={'layer': '0_GRID_AXIS', 'height': dim_char_h * 0.8})
        lbl.set_placement((gx + 0.5, g_min_y + 0.5))
        box = text_extents(lbl)
        if box:
            placed_boxes.append(box)
        gx += grid_step

    gy = g_min_y
    while gy <= g_max_y:
        msp.add_line((g_min_x, gy), (g_max_x, gy), dxfattribs={'layer': '0_GRID_AXIS'})
        if gy > g_min_y:
            lbl = msp.add_text(f"{int(gy)}m", dxfattribs={'layer': '0_GRID_AXIS', 'height': dim_char_h * 0.8})
            lbl.set_placement((g_min_x + 0.5, gy + 0.5))
            box = text_extents(lbl)
            if box:
                placed_boxes.append(box)
        gy += grid_step

    # 3. C-PLOT-BDY
    for loc_ring in local_rings:
        poly = msp.add_lwpolyline(loc_ring, dxfattribs={'layer': 'C-PLOT-BDY', 'closed': True})
        poly.dxf.const_width = max(0.15, scale * 0.005)
        try:
            hatch = msp.add_hatch(color=252, dxfattribs={'layer': 'C-PROP-HATCH'})
            hatch.paths.add_polyline_path(loc_ring, is_closed=True)
            hatch.transparency = 0.65
        except Exception:
            pass

    cts_label = msp.add_text(
        f"CTS {properties.get('cts_no')}",
        dxfattribs={'layer': 'C-ANNO-TEXT', 'height': char_h})
    cts_label.set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
    cts_box = text_extents(cts_label)
    if cts_box:
        placed_boxes.append(cts_box)

    # 4. C-SETBACK-3M & C-SETBACK-6M
    setback_status = {}
    for spec_layer, spec_dist in (('C-SETBACK-3M', 3.0), ('C-SETBACK-6M', 6.0)):
        drawn = 0
        for loc_ring in local_rings:
            for offset_ring in offset_polygon_inward(loc_ring, spec_dist):
                msp.add_lwpolyline(offset_ring, dxfattribs={'layer': spec_layer, 'closed': True})
                drawn += 1
        setback_status[spec_dist] = drawn > 0
        if not drawn:
            marker = msp.add_text(
                f"{spec_dist:.1f}m SETBACK N/A",
                dxfattribs={'layer': spec_layer, 'height': dim_char_h})
            marker.set_placement((min_x, min_y - dim_char_h * (2.5 if spec_dist == 3.0 else 4.0)))
            nudge_text_clear(marker, placed_boxes, dim_char_h * 1.3, direction=(0.0, -1.0), limit=6)
            box = text_extents(marker)
            if box:
                placed_boxes.append(box)

    # 5. C-ANNO-DIMS
    segments = []
    for loc_ring in local_rings:
        n_pts = len(loc_ring)
        for i in range(n_pts):
            p1 = loc_ring[i]
            p2 = loc_ring[(i + 1) % n_pts]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len > 1.0:
                segments.append((seg_len, dx, dy, p1, p2))
    segments.sort(key=lambda s: -s[0])

    for seg_len, dx, dy, p1, p2 in segments:
        mx = (p1[0] + p2[0]) / 2.0
        my = (p1[1] + p2[1]) / 2.0
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
            'rotation': angle_deg,
        })
        txt_elem.set_placement((tx, ty))
        if nudge_text_clear(txt_elem, placed_boxes, dim_char_h * 1.2, direction=(nx, ny), limit=10):
            box = text_extents(txt_elem)
            if box:
                placed_boxes.append(box)
        else:
            msp.delete_entity(txt_elem)

    # 6b. C-ROAD-ALIGN (Placed before neighbours so road label claims priority)
    clip = scale * 0.9
    cx_lo, cx_hi = min_x - clip, max_x + clip
    cy_lo, cy_hi = min_y - clip, max_y + clip

    road_drawn = 0
    for road_ring in (roads or []):
        loc = [((pt[0] - lon0) * meters_per_deg_lon, (pt[1] - lat0) * meters_per_deg_lat)
               for pt in road_ring]
        for seg in clip_path_to_window(loc, cx_lo, cy_lo, cx_hi, cy_hi):
            if len(seg) >= 2:
                msp.add_lwpolyline(seg, dxfattribs={'layer': 'C-ROAD-ALIGN'})
                road_drawn += 1

    if road_drawn:
        road_text = msp.add_text(
            fit_label_to_width(
                "ABUTTING ROAD: {}",
                f"{properties.get('abutting_road') or 'N/A'} ({properties.get('road_width')})",
                max_width=max(width, height) * 1.2, char_h=dim_char_h),
            dxfattribs={'layer': 'C-ROAD-ALIGN', 'height': dim_char_h})
        road_text.set_placement((min_x, min_y - dim_char_h * 1.2))
        nudge_text_clear(road_text, placed_boxes, dim_char_h * 1.3, direction=(0.0, -1.0), limit=10)
        box = text_extents(road_text)
        if box:
            placed_boxes.append(box)

    # 6c. C-NORTH-ARROW (Placed before neighbours so north arrow claims clear area)
    na_x = max_x + scale * 0.16
    na_y = max_y - scale * 0.06
    na_r = scale * 0.07
    msp.add_circle((na_x, na_y), radius=na_r, dxfattribs={'layer': 'C-NORTH-ARROW'})
    msp.add_lwpolyline(
        [(na_x, na_y + na_r * 1.5), (na_x - na_r * 0.5, na_y - na_r * 0.7), (na_x + na_r * 0.5, na_y - na_r * 0.7)],
        dxfattribs={'layer': 'C-NORTH-ARROW', 'closed': True})
    na_lbl = msp.add_text("N", dxfattribs={'layer': 'C-NORTH-ARROW', 'height': char_h})
    na_lbl.set_placement((na_x - char_h * 0.35, na_y + na_r * 1.8))
    na_box = text_extents(na_lbl)
    if na_box:
        placed_boxes.append(na_box)

    # 6. C-ADJN-PLOTS
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
                    label = msp.add_text(f"CTS {n_cts}", dxfattribs={
                        'layer': 'C-ADJN-PLOTS',
                        'height': dim_char_h * 0.9,
                    })
                    label.set_placement((ncx, ncy))
                    if not nudge_text_clear(label, placed_boxes, dim_char_h * 1.2, limit=10):
                        msp.delete_entity(label)
                    else:
                        box = text_extents(label)
                        if box:
                            placed_boxes.append(box)

    # 7. C-RESTRICT-ZONE
    restrict_notes = []
    crz_flag = str(properties.get("crz_buffer_flag") or "")
    if crz_flag.upper().startswith("YES"):
        restrict_notes.append(f"CRZ: {crz_flag}")
        restrict_notes.append("DEVELOPMENT RESTRICTED")
    if str(properties.get("metro_buffer_flag") or "").upper().startswith("YES"):
        msp.add_circle((cx, cy), radius=scale * 0.6, dxfattribs={'layer': 'C-RESTRICT-ZONE'})
        restrict_notes.append("METRO RAIL BUFFER")

    note_y = max_y + dim_char_h * 4.4
    for note in restrict_notes:
        note_text = msp.add_text(note, dxfattribs={'layer': 'C-RESTRICT-ZONE', 'height': dim_char_h})
        note_text.set_placement((min_x, note_y))
        nudge_text_clear(note_text, placed_boxes, dim_char_h * 1.2, limit=14)
        box = text_extents(note_text)
        if box:
            placed_boxes.append(box)
            note_y = box[3] + dim_char_h * 1.1
        else:
            note_y += dim_char_h * 2.1

    # 7b. C-RESERVATIONS
    all_res_items = (reservations or []) + (designations or [])
    if all_res_items:
        for item in (reservations or []):
            ov_sqm = item.get("overlap_sqm", 0)
            for res_wgs_ring in item.get("wgs_rings", []):
                if len(res_wgs_ring) >= 3:
                    res_loc_ring = project_rings_to_local_metres([res_wgs_ring])["local_rings"][0]
                    msp.add_lwpolyline(res_loc_ring, dxfattribs={'layer': 'C-RESERVATIONS', 'closed': True})
                    if res_loc_ring and ov_sqm >= 100.0:
                        rcx = sum(p[0] for p in res_loc_ring) / len(res_loc_ring)
                        rcy = sum(p[1] for p in res_loc_ring) / len(res_loc_ring)
                        txt = msp.add_text(
                            f"RES: {item.get('code')} ({ov_sqm:.0f}m²)",
                            dxfattribs={'layer': 'C-RESERVATIONS', 'height': char_h * 0.75}
                        )
                        txt.set_placement((rcx, rcy), align=TextEntityAlignment.MIDDLE_CENTER)
                        if nudge_text_clear(txt, placed_boxes, char_h * 0.9, direction=(0.0, 1.0), limit=10):
                            box = text_extents(txt)
                            if box:
                                placed_boxes.append(box)
                        else:
                            msp.delete_entity(txt)
        for item in (designations or []):
            ov_sqm = item.get("overlap_sqm", 0)
            for des_wgs_ring in item.get("wgs_rings", []):
                if len(des_wgs_ring) >= 3:
                    des_loc_ring = project_rings_to_local_metres([des_wgs_ring])["local_rings"][0]
                    msp.add_lwpolyline(des_loc_ring, dxfattribs={'layer': 'C-RESERVATIONS', 'closed': True})
                    if des_loc_ring and ov_sqm >= 100.0:
                        dcx = sum(p[0] for p in des_loc_ring) / len(des_loc_ring)
                        dcy = sum(p[1] for p in des_loc_ring) / len(des_loc_ring)
                        txt = msp.add_text(
                            f"DES: {item.get('code')} ({ov_sqm:.0f}m²)",
                            dxfattribs={'layer': 'C-RESERVATIONS', 'height': char_h * 0.75}
                        )
                        txt.set_placement((dcx, dcy), align=TextEntityAlignment.MIDDLE_CENTER)
                        if nudge_text_clear(txt, placed_boxes, char_h * 0.9, direction=(0.0, 1.0), limit=10):
                            box = text_extents(txt)
                            if box:
                                placed_boxes.append(box)
                        else:
                            msp.delete_entity(txt)


    # 9. C-TITLE-BLOCK
    content_x, content_y = [], []
    for entity in msp:
        try:
            if entity.dxftype() == 'LWPOLYLINE':
                for vx, vy in entity.get_points('xy'):
                    content_x.append(vx)
                    content_y.append(vy)
            elif entity.dxftype() == 'LINE':
                content_x += [entity.dxf.start.x, entity.dxf.end.x]
                content_y += [entity.dxf.start.y, entity.dxf.end.y]
            elif entity.dxftype() == 'CIRCLE':
                ctr, rad = entity.dxf.center, entity.dxf.radius
                content_x += [ctr.x - rad, ctr.x + rad]
                content_y += [ctr.y - rad, ctr.y + rad]
            elif entity.dxftype() == 'TEXT':
                box = text_extents(entity)
                if box:
                    content_x += [box[0], box[2]]
                    content_y += [box[1], box[3]]
        except Exception:
            continue
    if not content_x:
        content_x, content_y = [min_x, max_x], [min_y, max_y]

    pad = max(scale * 0.10, 3.0)
    b_min_x = min(content_x) - pad
    plot_right = max(content_x) + pad
    b_min_y = min(content_y) - pad
    b_max_y = max(content_y) + pad

    measured_area = sum(abs(polygon_signed_area(r)) for r in local_rings) or None
    data_rows = legend_data_rows(properties, setback_status, measured_area)

    _lg_row = max(char_h * 1.9, 2.2)
    _needed = (legend_column_height(_lg_row, len(DXF_LEGEND_ROWS), len(data_rows))
               + title_block_height(_lg_row, len(dxf_title_block_lines(properties, utm_cx, utm_cy)))
               + pad * 3)
    if (b_max_y - b_min_y) < _needed:
        b_min_y = b_max_y - _needed

    lg_w = max(scale * 0.95, 26.0)
    lg_x0 = plot_right + scale * 0.06

    lg_x1 = draw_dxf_legend_column(
        msp, properties, setback_status, utm_cx, utm_cy,
        lg_x0, lg_w, b_max_y, b_min_y, char_h, dim_char_h, scale,
        data_rows=data_rows,
    )
    b_max_x = max(lg_x0 + lg_w, lg_x1) + scale * 0.06

    msp.add_lwpolyline(
        [(b_min_x, b_min_y), (b_max_x, b_min_y), (b_max_x, b_max_y), (b_min_x, b_max_y)],
        dxfattribs={'layer': 'C-TITLE-BLOCK', 'closed': True})

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
