"""Stable DXF facade over focused policy, geometry, text and render modules."""

from dp_lookup.exporters.dxf_geometry import (
    METRES_PER_DEG_LAT,
    METRES_PER_DEG_LON_EQUATOR,
    clip_path_to_window,
    clip_segment_to_box,
    offset_polygon_inward,
    polygon_signed_area,
    project_rings_to_local_metres,
    to_local_metres,
)
from dp_lookup.exporters.dxf_legend import (
    draw_dxf_legend_column,
    dxf_title_block_lines,
    legend_column_height,
    legend_data_row,
    legend_data_rows,
    title_block_height,
)
from dp_lookup.exporters.dxf_policy import (
    DEFAULT_DXF_LAYOUT_POLICY,
    DEFAULT_LAYOUT_POLICY,
    DXF_LAYERS,
    DXF_LEGEND_ROWS,
    LEGEND_PAD_ROWS,
    LEGEND_VALUE_MAX_CHARS,
    DxfLayoutPolicy,
)
from dp_lookup.exporters.dxf_renderer import export_dxf, new_dxf_document
from dp_lookup.exporters.dxf_text import boxes_overlap, fit_label_to_width, nudge_text_clear, text_extents

__all__ = [
    "DEFAULT_DXF_LAYOUT_POLICY",
    "DEFAULT_LAYOUT_POLICY",
    "DXF_LAYERS",
    "DXF_LEGEND_ROWS",
    "LEGEND_PAD_ROWS",
    "LEGEND_VALUE_MAX_CHARS",
    "METRES_PER_DEG_LAT",
    "METRES_PER_DEG_LON_EQUATOR",
    "DxfLayoutPolicy",
    "boxes_overlap",
    "clip_path_to_window",
    "clip_segment_to_box",
    "draw_dxf_legend_column",
    "dxf_title_block_lines",
    "export_dxf",
    "fit_label_to_width",
    "legend_column_height",
    "legend_data_row",
    "legend_data_rows",
    "new_dxf_document",
    "nudge_text_clear",
    "offset_polygon_inward",
    "polygon_signed_area",
    "project_rings_to_local_metres",
    "text_extents",
    "title_block_height",
    "to_local_metres",
]
