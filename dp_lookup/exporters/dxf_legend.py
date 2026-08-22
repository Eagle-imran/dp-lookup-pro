"""Plot metadata, layer legend and title-block composition for DXF sheets."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from dp_lookup.exporters.dxf_policy import DEFAULT_DXF_LAYOUT_POLICY, DXF_LEGEND_ROWS, DxfLayoutPolicy
from dp_lookup.exporters.dxf_text import text_extents


def dxf_title_block_lines(properties: Dict[str, Any], utm_cx: float, utm_cy: float) -> List[str]:
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


def title_block_height(
    row_height: float,
    line_count: int,
    policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> float:
    return row_height * (line_count + policy.title_block_height_extra_rows)


def legend_column_height(
    row_height: float,
    legend_count: int,
    data_count: int,
    policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> float:
    return row_height * (legend_count + data_count + policy.legend_pad_rows)


def legend_data_row(
    label: str,
    value: Any,
    policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> List[str]:
    text = str(value)
    max_chars = policy.legend_value_max_chars
    label_width = policy.legend_label_width_chars
    if len(text) <= max_chars:
        return [f"{label:<{label_width}}: {text}"]
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return [f"{label:<{label_width}}: {lines[0]}"] + [f"{'':<{label_width}}  {line}" for line in lines[1:]]


def legend_data_rows(
    properties: Dict[str, Any],
    setback_status: Dict[float, bool],
    measured_area_sqm: Optional[float] = None,
    policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> List[str]:
    setback_3m = "drawn" if setback_status.get(3.0) else "NOT VIABLE - plot too narrow"
    setback_6m = "drawn" if setback_status.get(6.0) else "NOT VIABLE - plot too narrow"
    raw_assessment = properties.get("area_assessment")
    assessment = raw_assessment if isinstance(raw_assessment, Mapping) else None
    area_note = properties.get("area_source") or ""
    derived = any(token in str(area_note).casefold() for token in ("derived", "calculated boundary"))
    record_area = properties.get("area_sqm")

    if assessment is not None:
        recorded_area = assessment.get("recorded_plot_area_sqm")
        calculated_area = assessment.get("calculated_boundary_area_sqm")
        selected_basis = assessment.get("selected_area_basis")
        if selected_basis == "recorded_plot_area":
            source_label = assessment.get("recorded_area_source")
        elif selected_basis == "calculated_boundary_area":
            source_label = assessment.get("geometry_source")
        else:
            source_label = "Unavailable"
        rows = legend_data_row(
            "RECORDED PLOT AREA",
            f"{recorded_area} sq m" if isinstance(recorded_area, (int, float)) else "Not available",
            policy,
        )
        if isinstance(calculated_area, (int, float)):
            delta = ""
            difference_percent = assessment.get("difference_percent")
            difference_sqm = assessment.get("difference_sqm")
            if isinstance(difference_percent, (int, float)):
                sign = "+" if not isinstance(difference_sqm, (int, float)) or difference_sqm >= 0 else "-"
                delta = f"  ({sign}{abs(difference_percent):.2f}% vs record)"
            rows += legend_data_row("CALCULATED (BDY)", f"{calculated_area:.2f} sq m{delta}", policy)
        else:
            rows += legend_data_row("CALCULATED (BDY)", "Not available", policy)
        rows += legend_data_row("AREA SOURCE", source_label or "Unavailable", policy)
        rows += legend_data_row(
            "AREA RELIABILITY",
            assessment.get("reliability_label") or assessment.get("reliability_status") or "Unknown",
            policy,
        )
    else:
        rows = legend_data_row("GROSS PLOT AREA", f"{record_area} sq m", policy)
        rows += legend_data_row(
            "AREA SOURCE",
            "Calculated boundary area" if derived else "MCGM cadastral parcel record",
            policy,
        )
    if measured_area_sqm and assessment is None:
        delta = ""
        if not derived and isinstance(record_area, (int, float)) and record_area:
            percent = (measured_area_sqm - record_area) / record_area * 100.0
            delta = f"  ({percent:+.2f}% vs record)"
        rows += legend_data_row("MEASURED (BDY)", f"{measured_area_sqm:.2f} sq m{delta}", policy)
    raw_authority = properties.get("authority_resolution")
    if isinstance(raw_authority, Mapping) and raw_authority.get("active_record_ids"):
        record_ids = ", ".join(str(value) for value in raw_authority["active_record_ids"])
        rows += legend_data_row("AUTHORITY RECORDS", record_ids, policy)
    rows += legend_data_row("CTS / VILLAGE", f"{properties.get('cts_no')} / {properties.get('village')}", policy)
    rows += legend_data_row("WARD / ZONE", f"{properties.get('ward')} / {properties.get('zone')}", policy)
    rows += legend_data_row(
        "ABUTTING ROAD", f"{properties.get('abutting_road')} ({properties.get('road_width')})", policy
    )
    crz_value = properties.get("crz_buffer_flag")
    if str(crz_value or "").upper().startswith("YES"):
        crz_value = f"{crz_value} - verify with MCGM/MCZMA"
    rows += legend_data_row("CRZ STATUS", crz_value, policy)
    rows += legend_data_row("METRO BUFFER", properties.get("metro_buffer_flag"), policy)
    rows += legend_data_row("3.0 m SETBACK", setback_3m, policy)
    rows += legend_data_row("6.0 m SETBACK", setback_6m, policy)
    encumbered_percent = properties.get("encumbered_percent")
    if encumbered_percent is not None and encumbered_percent > 0:
        encumbered_sqm = properties.get("encumbered_area_sqm", 0.0)
        net_sqm = properties.get("net_unencumbered_sqm", 0.0)
        rows += legend_data_row("ENCUMBERED", f"{encumbered_percent:.1f}% ({encumbered_sqm:,.1f} sq m)", policy)
        rows += legend_data_row("NET DEVELOPABLE", f"{net_sqm:,.1f} sq m", policy)
    return rows


def draw_dxf_legend_column(
    msp: Any,
    properties: Dict[str, Any],
    setback_status: Dict[float, bool],
    utm_cx: float,
    utm_cy: float,
    legend_x: float,
    legend_width: float,
    border_max_y: float,
    border_min_y: float,
    char_height: float,
    dimension_char_height: float,
    scale: float,
    data_rows: Optional[List[str]] = None,
    policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> float:
    if data_rows is None:
        data_rows = legend_data_rows(properties, setback_status, policy=policy)
    row_height = max(char_height * policy.legend_row_height_fraction, policy.legend_row_min)
    left = legend_x + row_height * policy.legend_left_fraction
    legend_top = border_max_y - scale * policy.legend_top_fraction
    right_edge = legend_x + legend_width
    emitted = []

    def place(text: str, height: float, x: float, y: float) -> Any:
        entity = msp.add_text(text, dxfattribs={"layer": "C-TITLE-BLOCK", "height": height})
        entity.set_placement((x, y))
        emitted.append(entity)
        return entity

    y = legend_top - row_height * policy.legend_heading_gap_fraction
    place("LAYER LEGEND", char_height * policy.legend_heading_height_fraction, left, y)
    y -= row_height * policy.legend_section_gap_fraction
    swatch_width = row_height * policy.legend_swatch_width_fraction
    for layer_name, meaning in DXF_LEGEND_ROWS:
        msp.add_line(
            (left, y + row_height * policy.legend_swatch_y_fraction),
            (left + swatch_width, y + row_height * policy.legend_swatch_y_fraction),
            dxfattribs={"layer": layer_name},
        )
        place(
            f"{layer_name}  -  {meaning}",
            dimension_char_height * policy.legend_text_height_fraction,
            left + swatch_width + row_height * policy.legend_swatch_text_gap_fraction,
            y,
        )
        y -= row_height
    y -= row_height * policy.legend_data_gap_fraction
    place("PLOT DATA", char_height * policy.legend_heading_height_fraction, left, y)
    y -= row_height * policy.legend_data_heading_gap_fraction
    for row in data_rows:
        place(row, dimension_char_height * policy.legend_text_height_fraction, left, y)
        y -= row_height

    measured_right = right_edge
    for entity in emitted:
        box = text_extents(entity)
        if box:
            measured_right = max(measured_right, box[2])
    legend_right = measured_right + row_height * policy.legend_border_pad_fraction
    legend_bottom = min(
        y + row_height - row_height * policy.legend_text_height_fraction,
        legend_top - legend_column_height(row_height, len(DXF_LEGEND_ROWS), len(data_rows), policy),
    )
    msp.add_lwpolyline(
        [(legend_x, legend_bottom), (legend_right, legend_bottom), (legend_right, legend_top), (legend_x, legend_top)],
        close=True,
        dxfattribs={"layer": "C-TITLE-BLOCK"},
    )
    title_lines = dxf_title_block_lines(properties, utm_cx, utm_cy)
    title_char_height = dimension_char_height * policy.legend_text_height_fraction
    title_height = title_block_height(row_height, len(title_lines), policy)
    title_bottom = border_min_y + scale * policy.title_block_y_fraction
    title = msp.add_mtext(
        "\n".join(title_lines),
        dxfattribs={"layer": "C-TITLE-BLOCK", "char_height": title_char_height},
    )
    title.set_location((left, title_bottom + title_height - row_height * policy.title_block_top_gap_fraction))
    msp.add_lwpolyline(
        [
            (legend_x, title_bottom),
            (legend_right, title_bottom),
            (legend_right, title_bottom + title_height),
            (legend_x, title_bottom + title_height),
        ],
        close=True,
        dxfattribs={"layer": "C-TITLE-BLOCK"},
    )
    return legend_right
