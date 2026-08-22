"""ezdxf implementation for the scale-accurate cadastral CAD sheet."""

import math
from typing import Any, Dict, List, Optional, Sequence

import ezdxf
from ezdxf.enums import TextEntityAlignment

from dp_lookup.core.geometry import wgs84_to_utm43n
from dp_lookup.exporters.contracts import ExportPayload, legacy_export_properties
from dp_lookup.exporters.dxf_geometry import (
    METRES_PER_DEG_LAT as METRES_PER_DEG_LAT,
)
from dp_lookup.exporters.dxf_geometry import (
    METRES_PER_DEG_LON_EQUATOR as METRES_PER_DEG_LON_EQUATOR,
)
from dp_lookup.exporters.dxf_geometry import (
    clip_path_to_window as clip_path_to_window,
)
from dp_lookup.exporters.dxf_geometry import (
    clip_segment_to_box as clip_segment_to_box,
)
from dp_lookup.exporters.dxf_geometry import (
    offset_polygon_inward as offset_polygon_inward,
)
from dp_lookup.exporters.dxf_geometry import (
    polygon_signed_area as polygon_signed_area,
)
from dp_lookup.exporters.dxf_geometry import (
    project_rings_to_local_metres as project_rings_to_local_metres,
)
from dp_lookup.exporters.dxf_geometry import (
    to_local_metres as to_local_metres,
)
from dp_lookup.exporters.dxf_legend import (
    draw_dxf_legend_column as draw_dxf_legend_column,
)
from dp_lookup.exporters.dxf_legend import (
    dxf_title_block_lines as dxf_title_block_lines,
)
from dp_lookup.exporters.dxf_legend import (
    legend_column_height as legend_column_height,
)
from dp_lookup.exporters.dxf_legend import (
    legend_data_row as legend_data_row,
)
from dp_lookup.exporters.dxf_legend import (
    legend_data_rows as legend_data_rows,
)
from dp_lookup.exporters.dxf_legend import (
    title_block_height as title_block_height,
)
from dp_lookup.exporters.dxf_policy import (
    DEFAULT_DXF_LAYOUT_POLICY as DEFAULT_DXF_LAYOUT_POLICY,
)
from dp_lookup.exporters.dxf_policy import (
    DEFAULT_LAYOUT_POLICY as DEFAULT_LAYOUT_POLICY,
)
from dp_lookup.exporters.dxf_policy import (
    DXF_LAYERS as DXF_LAYERS,
)
from dp_lookup.exporters.dxf_policy import (
    DXF_LEGEND_ROWS as DXF_LEGEND_ROWS,
)
from dp_lookup.exporters.dxf_policy import (
    LEGEND_PAD_ROWS as LEGEND_PAD_ROWS,
)
from dp_lookup.exporters.dxf_policy import (
    LEGEND_VALUE_MAX_CHARS as LEGEND_VALUE_MAX_CHARS,
)
from dp_lookup.exporters.dxf_policy import (
    DxfLayoutPolicy as DxfLayoutPolicy,
)
from dp_lookup.exporters.dxf_text import (
    boxes_overlap as boxes_overlap,
)
from dp_lookup.exporters.dxf_text import (
    fit_label_to_width as fit_label_to_width,
)
from dp_lookup.exporters.dxf_text import (
    nudge_text_clear as nudge_text_clear,
)
from dp_lookup.exporters.dxf_text import (
    text_extents as text_extents,
)


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


def export_dxf(
    wgs_rings: List[List[List[float]]],
    properties: ExportPayload,
    output_path: str,
    neighbors: Optional[List[Dict[str, Any]]] = None,
    roads: Optional[Sequence[Sequence[Sequence[float]]]] = None,
    reservations: Optional[List[Dict[str, Any]]] = None,
    designations: Optional[List[Dict[str, Any]]] = None,
    *,
    layout_policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> None:
    """
    Generates a scale-accurate Multi-Layered AutoCAD DXF CAD drawing file (.dxf)
    centered around Local Origin (0, 0) in Real-World Metric Meters (1 CAD Unit = 1 Meter).
    """
    properties = legacy_export_properties(properties)
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
    scale = max(width, height, layout_policy.min_scale)
    char_h = max(layout_policy.min_char_height, scale * layout_policy.char_height_fraction)
    dim_char_h = max(layout_policy.min_dim_char_height, scale * layout_policy.dim_char_height_fraction)

    # 2. 0_GRID_AXIS: Metric Axis Grid scaled to plot dimensions
    grid_step = layout_policy.grid_step_for(scale)
    g_min_x = math.floor((min_x - scale * layout_policy.grid_extent_fraction) / grid_step) * grid_step
    g_max_x = math.ceil((max_x + scale * layout_policy.grid_extent_fraction) / grid_step) * grid_step
    g_min_y = math.floor((min_y - scale * layout_policy.grid_extent_fraction) / grid_step) * grid_step
    g_max_y = math.ceil((max_y + scale * layout_policy.grid_extent_fraction) / grid_step) * grid_step

    placed_boxes = []

    gx = g_min_x
    while gx <= g_max_x:
        msp.add_line((gx, g_min_y), (gx, g_max_y), dxfattribs={"layer": "0_GRID_AXIS"})
        lbl = msp.add_text(
            f"{int(gx)}m",
            dxfattribs={"layer": "0_GRID_AXIS", "height": dim_char_h * layout_policy.grid_label_height_fraction},
        )
        lbl.set_placement((gx + layout_policy.grid_label_offset, g_min_y + layout_policy.grid_label_offset))
        box = text_extents(lbl)
        if box:
            placed_boxes.append(box)
        gx += grid_step

    gy = g_min_y
    while gy <= g_max_y:
        msp.add_line((g_min_x, gy), (g_max_x, gy), dxfattribs={"layer": "0_GRID_AXIS"})
        if gy > g_min_y:
            lbl = msp.add_text(
                f"{int(gy)}m",
                dxfattribs={"layer": "0_GRID_AXIS", "height": dim_char_h * layout_policy.grid_label_height_fraction},
            )
            lbl.set_placement((g_min_x + layout_policy.grid_label_offset, gy + layout_policy.grid_label_offset))
            box = text_extents(lbl)
            if box:
                placed_boxes.append(box)
        gy += grid_step

    # 3. C-PLOT-BDY
    for loc_ring in local_rings:
        poly = msp.add_lwpolyline(loc_ring, close=True, dxfattribs={"layer": "C-PLOT-BDY"})
        poly.dxf.const_width = max(
            layout_policy.plot_line_min_width,
            scale * layout_policy.plot_line_width_fraction,
        )
        try:
            hatch = msp.add_hatch(color=252, dxfattribs={"layer": "C-PROP-HATCH"})
            hatch.paths.add_polyline_path(loc_ring, is_closed=True)
            hatch.transparency = 0.65
        except Exception:
            pass

    cts_label = msp.add_text(f"CTS {properties.get('cts_no')}", dxfattribs={"layer": "C-ANNO-TEXT", "height": char_h})
    cts_label.set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
    cts_box = text_extents(cts_label)
    if cts_box:
        placed_boxes.append(cts_box)

    # 4. C-SETBACK-3M & C-SETBACK-6M
    setback_status = {}
    setback_layers = ("C-SETBACK-3M", "C-SETBACK-6M")
    for spec_layer, spec_dist, marker_offset in zip(
        setback_layers, layout_policy.setback_distances, layout_policy.setback_marker_offsets
    ):
        drawn = 0
        for loc_ring in local_rings:
            for offset_ring in offset_polygon_inward(loc_ring, spec_dist):
                msp.add_lwpolyline(offset_ring, close=True, dxfattribs={"layer": spec_layer})
                drawn += 1
        setback_status[spec_dist] = drawn > 0
        if not drawn:
            marker = msp.add_text(
                f"{spec_dist:.1f}m SETBACK N/A", dxfattribs={"layer": spec_layer, "height": dim_char_h}
            )
            marker.set_placement((min_x, min_y - dim_char_h * marker_offset))
            nudge_text_clear(
                marker,
                placed_boxes,
                dim_char_h * layout_policy.setback_nudge_step_fraction,
                direction=(0.0, -1.0),
                limit=layout_policy.setback_nudge_limit,
            )
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
            if seg_len > layout_policy.dimension_min_length:
                segments.append((seg_len, dx, dy, p1, p2))
    segments.sort(key=lambda s: -s[0])

    for seg_len, dx, dy, p1, p2 in segments:
        mx = (p1[0] + p2[0]) / 2.0
        my = (p1[1] + p2[1]) / 2.0
        nx = -dy / seg_len
        ny = dx / seg_len
        if (mx + nx - cx) ** 2 + (my + ny - cy) ** 2 < (mx - cx) ** 2 + (my - cy) ** 2:
            nx = -nx
            ny = -ny
        tx = mx + nx * (dim_char_h * layout_policy.dimension_offset_fraction)
        ty = my + ny * (dim_char_h * layout_policy.dimension_offset_fraction)
        angle_deg = math.degrees(math.atan2(dy, dx))
        if angle_deg > 90 or angle_deg < -90:
            angle_deg += 180

        txt_elem = msp.add_text(
            f"{seg_len:.2f}m",
            dxfattribs={
                "layer": "C-ANNO-DIMS",
                "height": dim_char_h,
                "rotation": angle_deg,
            },
        )
        txt_elem.set_placement((tx, ty))
        if nudge_text_clear(
            txt_elem,
            placed_boxes,
            dim_char_h * layout_policy.dimension_nudge_step_fraction,
            direction=(nx, ny),
            limit=layout_policy.dimension_nudge_limit,
        ):
            box = text_extents(txt_elem)
            if box:
                placed_boxes.append(box)
        else:
            msp.delete_entity(txt_elem)

    # 6b. C-ROAD-ALIGN (Placed before neighbours so road label claims priority)
    clip = scale * layout_policy.road_clip_fraction
    cx_lo, cx_hi = min_x - clip, max_x + clip
    cy_lo, cy_hi = min_y - clip, max_y + clip

    road_drawn = 0
    for road_ring in roads or []:
        loc = [((pt[0] - lon0) * meters_per_deg_lon, (pt[1] - lat0) * meters_per_deg_lat) for pt in road_ring]
        for seg in clip_path_to_window(loc, cx_lo, cy_lo, cx_hi, cy_hi):
            if len(seg) >= 2:
                msp.add_lwpolyline(seg, dxfattribs={"layer": "C-ROAD-ALIGN"})
                road_drawn += 1

    if road_drawn:
        road_text = msp.add_text(
            fit_label_to_width(
                "ABUTTING ROAD: {}",
                f"{properties.get('abutting_road') or 'N/A'} ({properties.get('road_width')})",
                max_width=max(width, height) * layout_policy.road_label_width_fraction,
                char_h=dim_char_h,
                policy=layout_policy,
            ),
            dxfattribs={"layer": "C-ROAD-ALIGN", "height": dim_char_h},
        )
        road_text.set_placement((min_x, min_y - dim_char_h * layout_policy.road_label_y_offset_fraction))
        nudge_text_clear(
            road_text,
            placed_boxes,
            dim_char_h * layout_policy.road_nudge_step_fraction,
            direction=(0.0, -1.0),
            limit=layout_policy.road_nudge_limit,
        )
        box = text_extents(road_text)
        if box:
            placed_boxes.append(box)

    # 6c. C-NORTH-ARROW (Placed before neighbours so north arrow claims clear area)
    na_x = max_x + scale * layout_policy.north_arrow_x_fraction
    na_y = max_y - scale * layout_policy.north_arrow_y_fraction
    na_r = scale * layout_policy.north_arrow_radius_fraction
    msp.add_circle((na_x, na_y), radius=na_r, dxfattribs={"layer": "C-NORTH-ARROW"})
    msp.add_lwpolyline(
        [
            (na_x, na_y + na_r * layout_policy.north_arrow_tip_fraction),
            (
                na_x - na_r * layout_policy.north_arrow_half_width_fraction,
                na_y - na_r * layout_policy.north_arrow_base_y_fraction,
            ),
            (
                na_x + na_r * layout_policy.north_arrow_half_width_fraction,
                na_y - na_r * layout_policy.north_arrow_base_y_fraction,
            ),
        ],
        close=True,
        dxfattribs={"layer": "C-NORTH-ARROW"},
    )
    na_lbl = msp.add_text("N", dxfattribs={"layer": "C-NORTH-ARROW", "height": char_h})
    na_lbl.set_placement(
        (na_x - char_h * layout_policy.north_label_x_fraction, na_y + na_r * layout_policy.north_label_y_fraction)
    )
    na_box = text_extents(na_lbl)
    if na_box:
        placed_boxes.append(na_box)

    # 6. C-ADJN-PLOTS
    if neighbors:
        for n in neighbors:
            n_rings = n.get("rings", [])
            n_cts = n.get("cts_no", "N/A")
            for n_ring in n_rings:
                n_loc_ring = [
                    ((pt[0] - lon0) * meters_per_deg_lon, (pt[1] - lat0) * meters_per_deg_lat) for pt in n_ring
                ]
                msp.add_lwpolyline(n_loc_ring, close=True, dxfattribs={"layer": "C-ADJN-PLOTS"})
                if n_loc_ring:
                    ncx = sum(p[0] for p in n_loc_ring) / len(n_loc_ring)
                    ncy = sum(p[1] for p in n_loc_ring) / len(n_loc_ring)
                    label = msp.add_text(
                        f"CTS {n_cts}",
                        dxfattribs={
                            "layer": "C-ADJN-PLOTS",
                            "height": dim_char_h * layout_policy.neighbor_label_height_fraction,
                        },
                    )
                    label.set_placement((ncx, ncy))
                    if not nudge_text_clear(
                        label,
                        placed_boxes,
                        dim_char_h * layout_policy.neighbor_nudge_step_fraction,
                        limit=layout_policy.neighbor_nudge_limit,
                    ):
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
        msp.add_circle(
            (cx, cy),
            radius=scale * layout_policy.metro_radius_fraction,
            dxfattribs={"layer": "C-RESTRICT-ZONE"},
        )
        restrict_notes.append("METRO RAIL BUFFER")

    note_y = max_y + dim_char_h * layout_policy.restriction_note_y_offset_fraction
    for note in restrict_notes:
        note_text = msp.add_text(note, dxfattribs={"layer": "C-RESTRICT-ZONE", "height": dim_char_h})
        note_text.set_placement((min_x, note_y))
        nudge_text_clear(
            note_text,
            placed_boxes,
            dim_char_h * layout_policy.restriction_nudge_step_fraction,
            limit=layout_policy.restriction_nudge_limit,
        )
        box = text_extents(note_text)
        if box:
            placed_boxes.append(box)
            note_y = box[3] + dim_char_h * layout_policy.restriction_note_gap_fraction
        else:
            note_y += dim_char_h * layout_policy.restriction_note_fallback_gap_fraction

    # 7b. C-RESERVATIONS
    all_res_items = (reservations or []) + (designations or [])
    if all_res_items:
        for item in reservations or []:
            ov_sqm = item.get("overlap_sqm", 0)
            for res_wgs_ring in item.get("wgs_rings", []):
                if len(res_wgs_ring) >= 3:
                    res_loc_ring = project_rings_to_local_metres([res_wgs_ring])["local_rings"][0]
                    msp.add_lwpolyline(res_loc_ring, close=True, dxfattribs={"layer": "C-RESERVATIONS"})
                    if res_loc_ring and ov_sqm >= 100.0:
                        rcx = sum(p[0] for p in res_loc_ring) / len(res_loc_ring)
                        rcy = sum(p[1] for p in res_loc_ring) / len(res_loc_ring)
                        txt = msp.add_text(
                            f"RES: {item.get('code')} ({ov_sqm:.0f}m²)",
                            dxfattribs={
                                "layer": "C-RESERVATIONS",
                                "height": char_h * layout_policy.reservation_label_height_fraction,
                            },
                        )
                        txt.set_placement((rcx, rcy), align=TextEntityAlignment.MIDDLE_CENTER)
                        if nudge_text_clear(
                            txt,
                            placed_boxes,
                            char_h * layout_policy.reservation_nudge_step_fraction,
                            direction=(0.0, 1.0),
                            limit=layout_policy.reservation_nudge_limit,
                        ):
                            box = text_extents(txt)
                            if box:
                                placed_boxes.append(box)
                        else:
                            msp.delete_entity(txt)
        for item in designations or []:
            ov_sqm = item.get("overlap_sqm", 0)
            for des_wgs_ring in item.get("wgs_rings", []):
                if len(des_wgs_ring) >= 3:
                    des_loc_ring = project_rings_to_local_metres([des_wgs_ring])["local_rings"][0]
                    msp.add_lwpolyline(des_loc_ring, close=True, dxfattribs={"layer": "C-RESERVATIONS"})
                    if des_loc_ring and ov_sqm >= 100.0:
                        dcx = sum(p[0] for p in des_loc_ring) / len(des_loc_ring)
                        dcy = sum(p[1] for p in des_loc_ring) / len(des_loc_ring)
                        txt = msp.add_text(
                            f"DES: {item.get('code')} ({ov_sqm:.0f}m²)",
                            dxfattribs={
                                "layer": "C-RESERVATIONS",
                                "height": char_h * layout_policy.reservation_label_height_fraction,
                            },
                        )
                        txt.set_placement((dcx, dcy), align=TextEntityAlignment.MIDDLE_CENTER)
                        if nudge_text_clear(
                            txt,
                            placed_boxes,
                            char_h * layout_policy.reservation_nudge_step_fraction,
                            direction=(0.0, 1.0),
                            limit=layout_policy.reservation_nudge_limit,
                        ):
                            box = text_extents(txt)
                            if box:
                                placed_boxes.append(box)
                        else:
                            msp.delete_entity(txt)

    # 9. C-TITLE-BLOCK
    content_x, content_y = [], []
    for entity in msp:
        try:
            if entity.dxftype() == "LWPOLYLINE":
                for vx, vy in entity.get_points("xy"):
                    content_x.append(vx)
                    content_y.append(vy)
            elif entity.dxftype() == "LINE":
                content_x += [entity.dxf.start.x, entity.dxf.end.x]
                content_y += [entity.dxf.start.y, entity.dxf.end.y]
            elif entity.dxftype() == "CIRCLE":
                ctr, rad = entity.dxf.center, entity.dxf.radius
                content_x += [ctr.x - rad, ctr.x + rad]
                content_y += [ctr.y - rad, ctr.y + rad]
            elif entity.dxftype() == "TEXT":
                box = text_extents(entity)
                if box:
                    content_x += [box[0], box[2]]
                    content_y += [box[1], box[3]]
        except Exception:
            continue
    if not content_x:
        content_x, content_y = [min_x, max_x], [min_y, max_y]

    pad = max(scale * layout_policy.content_pad_fraction, layout_policy.content_pad_min)
    b_min_x = min(content_x) - pad
    plot_right = max(content_x) + pad
    b_min_y = min(content_y) - pad
    b_max_y = max(content_y) + pad

    measured_area = sum(abs(polygon_signed_area(r)) for r in local_rings) or None
    data_rows = legend_data_rows(properties, setback_status, measured_area, layout_policy)

    _lg_row = max(char_h * layout_policy.legend_row_height_fraction, layout_policy.legend_row_min)
    _needed = (
        legend_column_height(_lg_row, len(DXF_LEGEND_ROWS), len(data_rows), layout_policy)
        + title_block_height(_lg_row, len(dxf_title_block_lines(properties, utm_cx, utm_cy)), layout_policy)
        + pad * 3
    )
    if (b_max_y - b_min_y) < _needed:
        b_min_y = b_max_y - _needed

    lg_w = max(scale * layout_policy.legend_width_fraction, layout_policy.legend_width_min)
    lg_x0 = plot_right + scale * layout_policy.legend_x_gap_fraction

    lg_x1 = draw_dxf_legend_column(
        msp,
        properties,
        setback_status,
        utm_cx,
        utm_cy,
        lg_x0,
        lg_w,
        b_max_y,
        b_min_y,
        char_h,
        dim_char_h,
        scale,
        data_rows=data_rows,
        policy=layout_policy,
    )
    b_max_x = max(lg_x0 + lg_w, lg_x1) + scale * layout_policy.legend_x_gap_fraction

    msp.add_lwpolyline(
        [(b_min_x, b_min_y), (b_max_x, b_min_y), (b_max_x, b_max_y), (b_min_x, b_max_y)],
        close=True,
        dxfattribs={"layer": "C-TITLE-BLOCK"},
    )

    doc.header["$EXTMIN"] = (b_min_x, b_min_y, 0)
    doc.header["$EXTMAX"] = (b_max_x, b_max_y, 0)
    doc.header["$LIMMIN"] = (b_min_x, b_min_y)
    doc.header["$LIMMAX"] = (b_max_x, b_max_y)

    try:
        doc.set_modelspace_vport(
            height=(b_max_y - b_min_y) * layout_policy.vport_height_fraction,
            center=((b_min_x + b_max_x) / 2.0, (b_min_y + b_max_y) / 2.0),
        )
    except Exception:
        pass

    doc.saveas(output_path)
