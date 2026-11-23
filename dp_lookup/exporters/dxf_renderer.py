"""ezdxf implementation for the scale-accurate cadastral CAD sheet."""

import contextlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import ezdxf
from ezdxf.enums import TextEntityAlignment
from ezdxf.lldxf.const import BOUNDARY_PATH_EXTERNAL, BOUNDARY_PATH_OUTERMOST
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from dp_lookup.core.geometry import wgs84_to_utm43n
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.exporters.contracts import ExportPayload, legacy_export_properties
from dp_lookup.exporters.dxf_geometry import (
    Ring,
    clip_path_to_window,
    inset_polygon_parts,
    project_rings_to_local_metres,
    to_local_metres,
)
from dp_lookup.exporters.dxf_legend import (
    draw_dxf_legend_column,
    dxf_road_label,
    dxf_title_block_lines,
    legend_column_height,
    legend_data_rows,
    title_block_height,
)
from dp_lookup.exporters.dxf_policy import (
    DEFAULT_DXF_LAYOUT_POLICY,
    DXF_LAYERS,
    DXF_LEGEND_ROWS,
    DXF_RESERVATION_LEGEND_ROW,
    DxfLayoutPolicy,
)
from dp_lookup.exporters.dxf_text import Box, Point, fit_label_to_width, nudge_text_clear, text_extents

SETBACK_LAYERS = ("C-SETBACK-3M", "C-SETBACK-6M")
OVERLAY_LABEL_MIN_SQM = 100.0


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
        with contextlib.suppress(Exception):
            doc.layers.add(name="C-RESERVATIONS", color=6, linetype="DASHED", lineweight=25)
    return doc


@dataclass
class _Sheet:
    """Model space plus the local frame, text sizes and label boxes shared by every drawing step.

    The parcel's first ring sets ``min_x``..``max_y``; its centroid sits at the local origin.
    """

    msp: Any
    policy: DxfLayoutPolicy
    lon0: float
    lat0: float
    mpd_lon: float
    mpd_lat: float
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    placed_boxes: list[Box] = field(default_factory=list)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def scale(self) -> float:
        return max(self.width, self.height, self.policy.min_scale)

    @property
    def char_h(self) -> float:
        return max(self.policy.min_char_height, self.scale * self.policy.char_height_fraction)

    @property
    def dim_char_h(self) -> float:
        return max(self.policy.min_dim_char_height, self.scale * self.policy.dim_char_height_fraction)

    def to_local(self, ring: Ring) -> list[Point]:
        return to_local_metres(ring, self.lon0, self.lat0, self.mpd_lon, self.mpd_lat)

    def remember(self, entity: Any) -> Box | None:
        """Record a placed label so later labels steer around it."""
        box = text_extents(entity)
        if box:
            self.placed_boxes.append(box)
        return box

    def place(self, entity: Any, step: float, *, limit: int, direction: Point = (0.0, 1.0)) -> Box | None:
        """Nudge a label clear of earlier ones and keep it even if it still overlaps."""
        nudge_text_clear(entity, self.placed_boxes, step, direction=direction, limit=limit)
        return self.remember(entity)

    def place_or_drop(self, entity: Any, step: float, *, limit: int, direction: Point = (0.0, 1.0)) -> None:
        """Nudge a label clear of earlier ones, or delete it if no clear spot is found."""
        if nudge_text_clear(entity, self.placed_boxes, step, direction=direction, limit=limit):
            self.remember(entity)
        else:
            self.msp.delete_entity(entity)


def _draw_grid(sheet: _Sheet) -> None:
    policy = sheet.policy
    step = policy.grid_step_for(sheet.scale)
    extent = sheet.scale * policy.grid_extent_fraction
    g_min_x = math.floor((sheet.min_x - extent) / step) * step
    g_max_x = math.ceil((sheet.max_x + extent) / step) * step
    g_min_y = math.floor((sheet.min_y - extent) / step) * step
    g_max_y = math.ceil((sheet.max_y + extent) / step) * step
    label_attribs = {"layer": "0_GRID_AXIS", "height": sheet.dim_char_h * policy.grid_label_height_fraction}

    gx = g_min_x
    while gx <= g_max_x:
        sheet.msp.add_line((gx, g_min_y), (gx, g_max_y), dxfattribs={"layer": "0_GRID_AXIS"})
        label = sheet.msp.add_text(f"{int(gx)}m", dxfattribs=label_attribs)
        label.set_placement((gx + policy.grid_label_offset, g_min_y + policy.grid_label_offset))
        sheet.remember(label)
        gx += step

    gy = g_min_y
    while gy <= g_max_y:
        sheet.msp.add_line((g_min_x, gy), (g_max_x, gy), dxfattribs={"layer": "0_GRID_AXIS"})
        if gy > g_min_y:
            label = sheet.msp.add_text(f"{int(gy)}m", dxfattribs=label_attribs)
            label.set_placement((g_min_x + policy.grid_label_offset, gy + policy.grid_label_offset))
            sheet.remember(label)
        gy += step


def _draw_parcel(sheet: _Sheet, local_rings: list[list[Point]], parcel: BaseGeometry, cts_no: Any) -> None:
    policy = sheet.policy
    for ring in local_rings:
        outline = sheet.msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "C-PLOT-BDY"})
        outline.dxf.const_width = max(policy.plot_line_min_width, sheet.scale * policy.plot_line_width_fraction)
    parts = parcel.geoms if isinstance(parcel, MultiPolygon) else (parcel,)
    for part in parts:
        if isinstance(part, Polygon) and not part.is_empty:
            hatch = sheet.msp.add_hatch(color=252, dxfattribs={"layer": "C-PROP-HATCH"})
            hatch.paths.add_polyline_path(part.exterior.coords, flags=BOUNDARY_PATH_EXTERNAL)
            for cutout in part.interiors:
                hatch.paths.add_polyline_path(cutout.coords, flags=BOUNDARY_PATH_OUTERMOST)
            hatch.transparency = 0.65

    label = sheet.msp.add_text(f"CTS {cts_no}", dxfattribs={"layer": "C-ANNO-TEXT", "height": sheet.char_h})
    label.set_placement((0.0, 0.0), align=TextEntityAlignment.MIDDLE_CENTER)
    sheet.remember(label)


def _draw_setbacks(sheet: _Sheet, parcel: BaseGeometry) -> dict[float, bool]:
    """Draw each inset setback line; return which distances leave buildable area."""
    policy = sheet.policy
    status: dict[float, bool] = {}
    for layer, distance, marker_offset in zip(
        SETBACK_LAYERS, policy.setback_distances, policy.setback_marker_offsets, strict=False
    ):
        inset_parts = inset_polygon_parts(parcel, distance)
        for part in inset_parts:
            for ring in (part.exterior, *part.interiors):
                sheet.msp.add_lwpolyline(list(ring.coords)[:-1], close=True, dxfattribs={"layer": layer})
        status[distance] = bool(inset_parts)
        if not inset_parts:
            marker = sheet.msp.add_text(
                f"{distance:.1f}m SETBACK N/A", dxfattribs={"layer": layer, "height": sheet.dim_char_h}
            )
            marker.set_placement((sheet.min_x, sheet.min_y - sheet.dim_char_h * marker_offset))
            sheet.place(
                marker,
                sheet.dim_char_h * policy.setback_nudge_step_fraction,
                direction=(0.0, -1.0),
                limit=policy.setback_nudge_limit,
            )
    return status


def _draw_edge_dimensions(sheet: _Sheet, local_rings: list[list[Point]]) -> None:
    """Label edges longest first, outside the parcel, dropping labels that cannot fit."""
    policy = sheet.policy
    segments = []
    for ring in local_rings:
        for i, p1 in enumerate(ring):
            p2 = ring[(i + 1) % len(ring)]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.sqrt(dx * dx + dy * dy)
            if length > policy.dimension_min_length:
                segments.append((length, dx, dy, p1, p2))
    segments.sort(key=lambda s: -s[0])

    offset = sheet.dim_char_h * policy.dimension_offset_fraction
    for length, dx, dy, p1, p2 in segments:
        mx = (p1[0] + p2[0]) / 2.0
        my = (p1[1] + p2[1]) / 2.0
        nx = -dy / length
        ny = dx / length
        if (mx + nx) ** 2 + (my + ny) ** 2 < mx**2 + my**2:
            nx = -nx
            ny = -ny
        angle = math.degrees(math.atan2(dy, dx))
        if angle > 90 or angle < -90:
            angle += 180

        label = sheet.msp.add_text(
            f"{length:.2f}m",
            dxfattribs={"layer": "C-ANNO-DIMS", "height": sheet.dim_char_h, "rotation": angle},
        )
        label.set_placement((mx + nx * offset, my + ny * offset))
        sheet.place_or_drop(
            label,
            sheet.dim_char_h * policy.dimension_nudge_step_fraction,
            direction=(nx, ny),
            limit=policy.dimension_nudge_limit,
        )


def _draw_roads(sheet: _Sheet, roads: Sequence[Sequence[Sequence[float]]], properties: Mapping[str, Any]) -> None:
    """Clip road centrelines to a window around the parcel and label the abutting road once."""
    policy = sheet.policy
    clip = sheet.scale * policy.road_clip_fraction
    window = (sheet.min_x - clip, sheet.min_y - clip, sheet.max_x + clip, sheet.max_y + clip)
    drawn = 0
    for road in roads:
        for segment in clip_path_to_window(sheet.to_local(road), *window):
            if len(segment) >= 2:
                sheet.msp.add_lwpolyline(segment, dxfattribs={"layer": "C-ROAD-ALIGN"})
                drawn += 1
    if not drawn:
        return

    road_label, road_value = dxf_road_label(properties)
    label = sheet.msp.add_text(
        fit_label_to_width(
            f"{road_label}: {{}}",
            road_value,
            max_width=max(sheet.width, sheet.height) * policy.road_label_width_fraction,
            char_h=sheet.dim_char_h,
            policy=policy,
        ),
        dxfattribs={"layer": "C-ROAD-ALIGN", "height": sheet.dim_char_h},
    )
    label.set_placement((sheet.min_x, sheet.min_y - sheet.dim_char_h * policy.road_label_y_offset_fraction))
    sheet.place(
        label,
        sheet.dim_char_h * policy.road_nudge_step_fraction,
        direction=(0.0, -1.0),
        limit=policy.road_nudge_limit,
    )


def _draw_north_arrow(sheet: _Sheet) -> None:
    policy = sheet.policy
    x = sheet.max_x + sheet.scale * policy.north_arrow_x_fraction
    y = sheet.max_y - sheet.scale * policy.north_arrow_y_fraction
    r = sheet.scale * policy.north_arrow_radius_fraction
    base_y = y - r * policy.north_arrow_base_y_fraction
    half_width = r * policy.north_arrow_half_width_fraction
    sheet.msp.add_circle((x, y), radius=r, dxfattribs={"layer": "C-NORTH-ARROW"})
    sheet.msp.add_lwpolyline(
        [(x, y + r * policy.north_arrow_tip_fraction), (x - half_width, base_y), (x + half_width, base_y)],
        close=True,
        dxfattribs={"layer": "C-NORTH-ARROW"},
    )
    label = sheet.msp.add_text("N", dxfattribs={"layer": "C-NORTH-ARROW", "height": sheet.char_h})
    label.set_placement((x - sheet.char_h * policy.north_label_x_fraction, y + r * policy.north_label_y_fraction))
    sheet.remember(label)


def _draw_neighbours(sheet: _Sheet, neighbours: Sequence[Mapping[str, Any]]) -> None:
    policy = sheet.policy
    label_attribs = {"layer": "C-ADJN-PLOTS", "height": sheet.dim_char_h * policy.neighbor_label_height_fraction}
    for neighbour in neighbours:
        cts_no = neighbour.get("cts_no", "N/A")
        for ring in neighbour.get("rings", []):
            local = sheet.to_local(ring)
            sheet.msp.add_lwpolyline(local, close=True, dxfattribs={"layer": "C-ADJN-PLOTS"})
            if not local:
                continue
            label = sheet.msp.add_text(f"CTS {cts_no}", dxfattribs=label_attribs)
            label.set_placement((sum(p[0] for p in local) / len(local), sum(p[1] for p in local) / len(local)))
            sheet.place_or_drop(
                label,
                sheet.dim_char_h * policy.neighbor_nudge_step_fraction,
                limit=policy.neighbor_nudge_limit,
            )


def _restriction_notes(properties: Mapping[str, Any]) -> list[str]:
    notes = []
    crz_flag = str(properties.get("crz_buffer_flag") or "")
    if crz_flag.upper().startswith("YES"):
        notes += [f"CRZ: {crz_flag}", "DEVELOPMENT RESTRICTED"]
    if str(properties.get("metro_buffer_flag") or "").upper().startswith("YES"):
        notes.append("METRO BUFFER INTERSECTS PLOT")
    return notes


def _draw_restriction_notes(sheet: _Sheet, properties: Mapping[str, Any]) -> None:
    """Stack CRZ and metro warnings above the parcel."""
    policy = sheet.policy
    note_y = sheet.max_y + sheet.dim_char_h * policy.restriction_note_y_offset_fraction
    for note in _restriction_notes(properties):
        text = sheet.msp.add_text(note, dxfattribs={"layer": "C-RESTRICT-ZONE", "height": sheet.dim_char_h})
        text.set_placement((sheet.min_x, note_y))
        box = sheet.place(
            text,
            sheet.dim_char_h * policy.restriction_nudge_step_fraction,
            limit=policy.restriction_nudge_limit,
        )
        if box:
            note_y = box[3] + sheet.dim_char_h * policy.restriction_note_gap_fraction
        else:
            note_y += sheet.dim_char_h * policy.restriction_note_fallback_gap_fraction


def _draw_overlays(
    sheet: _Sheet,
    reservations: Sequence[Mapping[str, Any]],
    designations: Sequence[Mapping[str, Any]],
) -> None:
    """Outline reservation and designation polygons; label overlaps of at least 100 m²."""
    policy = sheet.policy
    label_attribs = {"layer": "C-RESERVATIONS", "height": sheet.char_h * policy.reservation_label_height_fraction}
    for prefix, items in (("RES", reservations), ("DES", designations)):
        for item in items:
            overlap_sqm = item.get("overlap_sqm", 0)
            for wgs_ring in item.get("wgs_rings", []):
                if len(wgs_ring) < 3:
                    continue
                local = sheet.to_local(wgs_ring)
                sheet.msp.add_lwpolyline(local, close=True, dxfattribs={"layer": "C-RESERVATIONS"})
                if not local or overlap_sqm < OVERLAY_LABEL_MIN_SQM:
                    continue
                label = sheet.msp.add_text(
                    f"{prefix}: {item.get('code')} ({overlap_sqm:.0f}m²)", dxfattribs=label_attribs
                )
                label.set_placement(
                    (sum(p[0] for p in local) / len(local), sum(p[1] for p in local) / len(local)),
                    align=TextEntityAlignment.MIDDLE_CENTER,
                )
                sheet.place_or_drop(
                    label,
                    sheet.char_h * policy.reservation_nudge_step_fraction,
                    direction=(0.0, 1.0),
                    limit=policy.reservation_nudge_limit,
                )


def _content_bounds(sheet: _Sheet) -> Box:
    """Bounding box of everything drawn so far, falling back to the parcel extent."""
    xs: list[float] = []
    ys: list[float] = []
    for entity in sheet.msp:
        try:
            kind = entity.dxftype()
            if kind == "LWPOLYLINE":
                for vx, vy in entity.get_points("xy"):
                    xs.append(vx)
                    ys.append(vy)
            elif kind == "LINE":
                xs += [entity.dxf.start.x, entity.dxf.end.x]
                ys += [entity.dxf.start.y, entity.dxf.end.y]
            elif kind == "CIRCLE":
                centre, radius = entity.dxf.center, entity.dxf.radius
                xs += [centre.x - radius, centre.x + radius]
                ys += [centre.y - radius, centre.y + radius]
            elif kind == "TEXT":
                box = text_extents(entity)
                if box:
                    xs += [box[0], box[2]]
                    ys += [box[1], box[3]]
        except Exception:
            continue
    if not xs:
        return sheet.min_x, sheet.min_y, sheet.max_x, sheet.max_y
    return min(xs), min(ys), max(xs), max(ys)


def _draw_legend_and_frame(
    doc: ezdxf.document.Drawing,
    sheet: _Sheet,
    properties: Mapping[str, Any],
    setback_status: dict[float, bool],
    measured_area: float | None,
) -> Box:
    """Add the legend column right of the drawing and a frame around both; return the frame."""
    policy = sheet.policy
    scale, char_h = sheet.scale, sheet.char_h
    utm_x, utm_y = wgs84_to_utm43n(sheet.lon0, sheet.lat0)
    content_left, content_bottom, content_right, content_top = _content_bounds(sheet)
    pad = max(scale * policy.content_pad_fraction, policy.content_pad_min)
    left = content_left - pad
    plot_right = content_right + pad
    bottom = content_bottom - pad
    top = content_top + pad

    data_rows = legend_data_rows(properties, setback_status, measured_area, policy)
    legend_rows: tuple[tuple[str, str], ...] = DXF_LEGEND_ROWS
    if "C-RESERVATIONS" in doc.layers:
        legend_rows = (*legend_rows, DXF_RESERVATION_LEGEND_ROW)

    row_height = max(char_h * policy.legend_row_height_fraction, policy.legend_row_min)
    needed = (
        legend_column_height(row_height, len(legend_rows), len(data_rows), policy)
        + title_block_height(row_height, len(dxf_title_block_lines(properties, utm_x, utm_y)), policy)
        + pad * 3
    )
    if (top - bottom) < needed:
        bottom = top - needed

    legend_width = max(scale * policy.legend_width_fraction, policy.legend_width_min)
    legend_left = plot_right + scale * policy.legend_x_gap_fraction
    legend_right = draw_dxf_legend_column(
        sheet.msp,
        properties,
        setback_status,
        utm_x,
        utm_y,
        legend_left,
        legend_width,
        top,
        bottom,
        char_h,
        sheet.dim_char_h,
        scale,
        data_rows=data_rows,
        policy=policy,
        legend_rows=legend_rows,
    )
    right = max(legend_left + legend_width, legend_right) + scale * policy.legend_x_gap_fraction

    sheet.msp.add_lwpolyline(
        [(left, bottom), (right, bottom), (right, top), (left, top)],
        close=True,
        dxfattribs={"layer": "C-TITLE-BLOCK"},
    )
    return left, bottom, right, top


def export_dxf(
    wgs_rings: list[list[list[float]]],
    properties: ExportPayload,
    output_path: str,
    neighbors: list[dict[str, Any]] | None = None,
    roads: Sequence[Sequence[Sequence[float]]] | None = None,
    reservations: list[dict[str, Any]] | None = None,
    designations: list[dict[str, Any]] | None = None,
    *,
    layout_policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> None:
    """Write a layered DXF sheet in metres (1 CAD unit = 1 m) with the parcel centred on the origin."""
    props = legacy_export_properties(properties)
    reservations = reservations or []
    designations = designations or []
    doc = new_dxf_document(has_reservations=bool(reservations or designations))

    projection = project_rings_to_local_metres(wgs_rings)
    local_rings = projection["local_rings"]
    parcel = arcgis_rings_to_geometry(local_rings)
    xs = [p[0] for p in local_rings[0]]
    ys = [p[1] for p in local_rings[0]]
    sheet = _Sheet(
        msp=doc.modelspace(),
        policy=layout_policy,
        lon0=projection["lon0"],
        lat0=projection["lat0"],
        mpd_lon=projection["mpd_lon"],
        mpd_lat=projection["mpd_lat"],
        min_x=min(xs),
        min_y=min(ys),
        max_x=max(xs),
        max_y=max(ys),
    )

    _draw_grid(sheet)
    _draw_parcel(sheet, local_rings, parcel, props.get("cts_no"))
    setback_status = _draw_setbacks(sheet, parcel)
    _draw_edge_dimensions(sheet, local_rings)
    _draw_roads(sheet, roads or [], props)
    _draw_north_arrow(sheet)
    _draw_neighbours(sheet, neighbors or [])
    _draw_restriction_notes(sheet, props)
    _draw_overlays(sheet, reservations, designations)
    left, bottom, right, top = _draw_legend_and_frame(
        doc, sheet, props, setback_status, measured_area=float(parcel.area) or None
    )

    doc.header["$EXTMIN"] = (left, bottom, 0)
    doc.header["$EXTMAX"] = (right, top, 0)
    doc.header["$LIMMIN"] = (left, bottom)
    doc.header["$LIMMAX"] = (right, top)

    view_left, view_bottom, view_right, view_top = (
        parcel.bounds if not parcel.is_empty else (sheet.min_x, sheet.min_y, sheet.max_x, sheet.max_y)
    )
    with contextlib.suppress(Exception):
        doc.set_modelspace_vport(
            height=max(1.0, view_right - view_left, view_top - view_bottom) * layout_policy.vport_height_fraction,
            center=((view_left + view_right) / 2.0, (view_bottom + view_top) / 2.0),
        )

    doc.saveas(output_path)
