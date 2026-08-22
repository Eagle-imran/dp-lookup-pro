"""Immutable configuration and layer definitions for DXF sheet generation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

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

DXF_LEGEND_ROWS = (
    ("C-PLOT-BDY", "PLOT BOUNDARY - gross plot area"),
    ("C-PROP-HATCH", "Gross plot area (fill)"),
    ("C-ROAD-ALIGN", "Abutting road alignment / frontage"),
    ("C-SETBACK-3M", "3.0 m setback line (true parallel offset)"),
    ("C-SETBACK-6M", "6.0 m setback line (true parallel offset)"),
    ("C-RESTRICT-ZONE", "CRZ / Metro restriction (advisory note)"),
    ("C-ADJN-PLOTS", "Adjoining CTS plots"),
    ("C-ANNO-DIMS", "Boundary segment dimensions (m)"),
    ("C-ANNO-TEXT", "Plot metadata"),
    ("C-NORTH-ARROW", "True north"),
    ("0_GRID_AXIS", "Metric grid, 0,0 at plot centroid"),
    ("C-TITLE-BLOCK", "Sheet border, legend, title block"),
)


@dataclass(frozen=True)
class DxfLayoutPolicy:
    """Named, validated layout controls for deterministic DXF sheets."""

    min_scale: float = 30.0
    min_char_height: float = 1.2
    min_dim_char_height: float = 0.9
    char_height_fraction: float = 0.035
    dim_char_height_fraction: float = 0.025
    label_min_value_chars: int = 8
    grid_breaks: Tuple[Tuple[float, float], ...] = ((1000.0, 500.0), (400.0, 200.0), (150.0, 100.0), (60.0, 50.0))
    default_grid_step: float = 25.0
    grid_extent_fraction: float = 0.25
    grid_label_offset: float = 0.5
    grid_label_height_fraction: float = 0.8
    plot_line_min_width: float = 0.15
    plot_line_width_fraction: float = 0.005
    setback_distances: Tuple[float, ...] = (3.0, 6.0)
    setback_marker_offsets: Tuple[float, ...] = (2.5, 4.0)
    setback_nudge_step_fraction: float = 1.3
    setback_nudge_limit: int = 6
    dimension_min_length: float = 1.0
    dimension_offset_fraction: float = 1.8
    dimension_nudge_step_fraction: float = 1.2
    dimension_nudge_limit: int = 10
    road_clip_fraction: float = 0.9
    road_label_width_fraction: float = 1.2
    road_label_y_offset_fraction: float = 1.2
    road_nudge_step_fraction: float = 1.3
    road_nudge_limit: int = 10
    north_arrow_x_fraction: float = 0.16
    north_arrow_y_fraction: float = 0.06
    north_arrow_radius_fraction: float = 0.07
    north_arrow_tip_fraction: float = 1.5
    north_arrow_half_width_fraction: float = 0.5
    north_arrow_base_y_fraction: float = 0.7
    north_label_x_fraction: float = 0.35
    north_label_y_fraction: float = 1.8
    neighbor_label_height_fraction: float = 0.9
    neighbor_nudge_step_fraction: float = 1.2
    neighbor_nudge_limit: int = 10
    metro_radius_fraction: float = 0.6
    restriction_note_y_offset_fraction: float = 4.4
    restriction_nudge_step_fraction: float = 1.2
    restriction_nudge_limit: int = 14
    restriction_note_gap_fraction: float = 1.1
    restriction_note_fallback_gap_fraction: float = 2.1
    reservation_label_height_fraction: float = 0.75
    reservation_nudge_step_fraction: float = 0.9
    reservation_nudge_limit: int = 10
    content_pad_fraction: float = 0.10
    content_pad_min: float = 3.0
    legend_row_height_fraction: float = 1.9
    legend_row_min: float = 2.2
    legend_left_fraction: float = 0.4
    legend_top_fraction: float = 0.05
    legend_heading_height_fraction: float = 0.95
    legend_heading_gap_fraction: float = 1.2
    legend_section_gap_fraction: float = 1.3
    legend_swatch_width_fraction: float = 1.5
    legend_swatch_y_fraction: float = 0.22
    legend_swatch_text_gap_fraction: float = 0.5
    legend_data_gap_fraction: float = 0.6
    legend_data_heading_gap_fraction: float = 1.25
    legend_text_height_fraction: float = 0.92
    legend_border_pad_fraction: float = 0.4
    legend_pad_rows: float = 4.15
    legend_value_max_chars: int = 34
    legend_label_width_chars: int = 16
    title_block_height_extra_rows: float = 1.2
    title_block_y_fraction: float = 0.05
    title_block_top_gap_fraction: float = 0.5
    legend_width_fraction: float = 0.95
    legend_width_min: float = 26.0
    legend_x_gap_fraction: float = 0.06
    vport_height_fraction: float = 1.08

    def __post_init__(self) -> None:
        numeric_controls = (
            (name, value)
            for name, value in vars(self).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
        if any(not math.isfinite(value) or value <= 0 for _, value in numeric_controls):
            raise ValueError("DXF layout numeric controls must be finite and positive")
        if len(self.setback_distances) != len(self.setback_marker_offsets):
            raise ValueError("setback distances and marker offsets must align")
        if any(not math.isfinite(value) or value <= 0 for value in self.setback_distances):
            raise ValueError("setback distances must be finite and positive")
        if any(not math.isfinite(value) or value <= 0 for value in self.setback_marker_offsets):
            raise ValueError("setback marker offsets must be finite and positive")
        if any(
            not math.isfinite(threshold) or threshold <= 0 or not math.isfinite(step) or step <= 0
            for threshold, step in self.grid_breaks
        ):
            raise ValueError("grid breakpoints must be finite and positive")
        thresholds = [threshold for threshold, _ in self.grid_breaks]
        if thresholds != sorted(thresholds, reverse=True) or len(thresholds) != len(set(thresholds)):
            raise ValueError("grid breakpoints must have unique thresholds in descending order")

    def grid_step_for(self, scale: float) -> float:
        for threshold, step in self.grid_breaks:
            if scale > threshold:
                return step
        return self.default_grid_step


DEFAULT_DXF_LAYOUT_POLICY = DxfLayoutPolicy()
DEFAULT_LAYOUT_POLICY = DEFAULT_DXF_LAYOUT_POLICY
LEGEND_PAD_ROWS = DEFAULT_DXF_LAYOUT_POLICY.legend_pad_rows
LEGEND_VALUE_MAX_CHARS = DEFAULT_DXF_LAYOUT_POLICY.legend_value_max_chars
