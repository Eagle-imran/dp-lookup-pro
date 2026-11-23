"""ReportLab implementation of the two-page DP remark PDF dossier."""

import datetime
from typing import Any
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from dp_lookup.exporters.contracts import PlotReportData


def _esc(val: Any) -> str:
    """XML-escape data values before putting them into ReportLab Paragraphs."""
    if val is None:
        return ""
    return xml_escape(str(val))


def _area_text(value: Any) -> str:
    return f"{_esc(value)} sq m" if value is not None else "Not available"


def write_pdf_report(data: PlotReportData) -> None:
    """
    Build a strictly 2-page, high-density DP Remark Dossier PDF.
    Page 1: Title, Status banner, Planning attributes table, HD DP Map, Interactive QR Code.
    Page 2: Title, Satellite Aerial View, Adjoining cadastral cluster table.
    """
    doc = SimpleDocTemplate(
        data.output_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"], fontSize=14, leading=17, textColor=colors.HexColor("#1A237E")
    )
    page_two_title_style = ParagraphStyle("PageTwoTitle", parent=title_style, fontSize=12, leading=15)
    subtitle_style = ParagraphStyle(
        "Sub", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#424242")
    )
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=8.0, leading=10.5)
    bold_style = ParagraphStyle("Bold", parent=styles["Normal"], fontSize=8.0, leading=10.5, fontName="Helvetica-Bold")

    story = []
    story.append(Paragraph("<b>MCGM DEVELOPMENT PLAN 2034 - SPATIAL REMARK DOCKET</b>", title_style))
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story.append(Paragraph(f"Spatial Planning Screening Report | Page 1 of 2 | Generated: {now_str}", subtitle_style))
    story.append(Spacer(1, 4))

    banner_color = (
        colors.HexColor("#E8F5E9")
        if "CLEAR" in data.status_badge
        else (
            colors.HexColor("#FFFDE7")
            if ("MODIFIED" in data.status_badge or "PARTIALLY" in data.status_badge)
            else colors.HexColor("#FFEBEE")
        )
    )
    banner_text = f"<b>STATUS: {_esc(data.status_badge)}</b> - {_esc(data.status_summary)}"
    banner_table = Table(
        [[Paragraph(banner_text, ParagraphStyle("BText", parent=body_style, fontSize=8.5, leading=11))]],
        colWidths=[540],
    )
    banner_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), banner_color),
                ("PADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#BDBDBD")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(banner_table)
    story.append(Spacer(1, 4))

    res_items = data.reservations or []
    if res_items:
        res_display = [
            f"• <b>{_esc(r['code'])}</b> ({_esc(r['description'])}) - {_esc(str(r['overlap_sqm']))} m² ({_esc(str(r['overlap_percent']))}%)"
            for r in res_items[:3]
        ]
        if len(res_items) > 3:
            res_display.append(f"• <i>... and {len(res_items) - 3} more reservations (see CAD/GeoJSON)</i>")
        res_text = "<br/>".join(res_display)
    elif data.reservation_code != "None":
        res_text = f"<b>{_esc(data.reservation_code)}</b> ({_esc(data.reservation_type)})"
    else:
        res_text = "None"

    des_items = data.designations or []
    if des_items:
        des_display = [
            f"• <b>{_esc(d['code'])}</b> ({_esc(d['description'])}) - {_esc(str(d['overlap_sqm']))} m² ({_esc(str(d['overlap_percent']))}%)"
            for d in des_items[:3]
        ]
        if len(des_items) > 3:
            des_display.append(f"• <i>... and {len(des_items) - 3} more designations (see CAD/GeoJSON)</i>")
        des_text = "<br/>".join(des_display)
    elif data.designation_description != "None":
        des_text = f"{_esc(data.designation_description)} ({_esc(data.designation_code)})"
    else:
        des_text = "None"

    area_assessment = data.attrs.get("_DP_AREA_ASSESSMENT")
    authority = data.attrs.get("_DP_AUTHORITY_RESOLUTION")
    if not isinstance(authority, dict):
        authority = {}
    raw_area_authority = authority.get("area")
    area_authority = raw_area_authority if isinstance(raw_area_authority, dict) else {}
    active_authority_ids = authority.get("active_record_ids")
    if not isinstance(active_authority_ids, list):
        active_authority_ids = []
    if isinstance(area_assessment, dict):
        recorded_area = area_assessment.get("recorded_plot_area_sqm")
        calculated_area = area_assessment.get("calculated_boundary_area_sqm")
        selected_area = area_assessment.get("selected_area_sqm")
        difference_percent = area_assessment.get("difference_percent")
        reliability = area_assessment.get("reliability_label") or "Screening"
        quality_flags = area_assessment.get("quality_flags") or []
        flag_messages = [
            str(flag.get("message")) for flag in quality_flags if isinstance(flag, dict) and flag.get("message")
        ]
        reliability_note = str(reliability)
        if flag_messages:
            reliability_note += " - " + "; ".join(flag_messages[:2])
        working_source = area_authority.get("source_label") or data.area_source_label
        authority_note = (
            "Active authority record(s): " + ", ".join(str(value) for value in active_authority_ids)
            if active_authority_ids
            else "No certified source has been activated"
        )
        area_rows = [
            [
                Paragraph("Working plot area", body_style),
                Paragraph(_area_text(selected_area), body_style),
                Paragraph(_esc(working_source), body_style),
            ],
            [
                Paragraph("Source area comparison", body_style),
                Paragraph(
                    f"Recorded: {_area_text(recorded_area)}<br/>Boundary: {_area_text(calculated_area)}",
                    body_style,
                ),
                Paragraph(
                    f"{_esc(area_assessment.get('recorded_area_source'))}<br/>"
                    f"{_esc(area_assessment.get('geometry_source'))}",
                    body_style,
                ),
            ],
            [
                Paragraph("Area difference / reliability", body_style),
                Paragraph(
                    f"{_esc(difference_percent)}%" if difference_percent is not None else "Not comparable",
                    body_style,
                ),
                Paragraph(f"{_esc(reliability_note)}<br/>{_esc(authority_note)}", body_style),
            ],
        ]
    else:
        area_rows = [
            [
                Paragraph("Plot area", body_style),
                Paragraph(
                    f"{_esc(data.attrs.get('AREA_APP_SQ_MTRS'))} sq m"
                    if data.attrs.get("AREA_APP_SQ_MTRS")
                    else "Not available",
                    body_style,
                ),
                Paragraph(_esc(data.area_source_label), body_style),
            ]
        ]

    table_data = [
        [
            Paragraph("<b>Attribute</b>", bold_style),
            Paragraph("<b>Details</b>", bold_style),
            Paragraph("<b>Planning Remarks</b>", bold_style),
        ],
        [
            Paragraph("Village / Ward", body_style),
            Paragraph(f"{_esc(data.village.upper())} (Ward {_esc(data.attrs['WARD'])})", body_style),
            Paragraph("MCGM Administrative Division", body_style),
        ],
        [
            Paragraph("Plot CTS No.", body_style),
            Paragraph(f"CTS {_esc(data.cts_number)} ({_esc(data.attrs['TYPE'])})", body_style),
            Paragraph("City Survey Cadastral Parcel", body_style),
        ],
        *area_rows,
        [
            Paragraph("Land-Use Zone", body_style),
            Paragraph(f"<b>Zone {_esc(data.zone)}</b>", body_style),
            Paragraph("Primary Zoning Classification", body_style),
        ],
        [
            Paragraph("PLU Reservation", body_style),
            Paragraph(res_text, body_style),
            Paragraph("DP 2034 Statutory Reservations", body_style),
        ],
        [
            Paragraph("PLU Designation", body_style),
            Paragraph(des_text, body_style),
            Paragraph("Existing Amenity Designation", body_style),
        ],
    ]
    if data.encumbered_percent > 0.0:
        table_data.append(
            [
                Paragraph("Encumbrance", body_style),
                Paragraph(
                    f"<b>{data.encumbered_percent:.1f}% Encumbered</b> ({data.encumbered_area_sqm:,.1f} m²)<br/>Net Unencumbered: <b>{data.net_unencumbered_sqm:,.1f} m²</b>",
                    body_style,
                ),
                Paragraph("Spatial Polygon Overlay", body_style),
            ]
        )
    modification_row = len(table_data)
    modification_text = (
        f"Approval: {_esc(data.modification_approval)}<br/>{_esc(data.modification_label)}"
        if data.modification_approval != "None" or data.modification_label != "None"
        else "None"
    )
    if data.modification_document.startswith(("https://", "http://")):
        modification_text += (
            f'<br/><a href={quoteattr(data.modification_document)} color="blue">Open source notification</a>'
        )
    table_data += [
        [
            Paragraph("DP Modification", body_style),
            Paragraph(modification_text, body_style),
            "",
        ],
        [
            Paragraph("CRZ Status", body_style),
            Paragraph(f"<b>{_esc(data.crz_status)}</b>", body_style),
            Paragraph("Coastal Regulation Zone Layer Query", body_style),
        ],
        [
            Paragraph("Metro Buffer", body_style),
            Paragraph(_esc(data.metro_buffer), body_style),
            Paragraph("Layer 1550 Metro Rail Influence", body_style),
        ],
        [
            Paragraph("Abutting Road", body_style),
            Paragraph(f"<b>{_esc(data.road_name)}</b> ({_esc(data.road_width)})", body_style),
            Paragraph("DP 2034 Road Access &amp; Width", body_style),
        ],
    ]

    t = Table(table_data, colWidths=[105, 220, 215])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECEFF1")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CFD8DC")),
                ("PADDING", (0, 0), (-1, -1), 1.7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("SPAN", (1, modification_row), (2, modification_row)),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 4))

    dp_img_rl = RLImage(data.dp_map_path, width=290, height=290)
    qr_img_rl = RLImage(data.qr_png, width=85, height=85)

    qr_cell = [
        Paragraph("<b>Scan for Live Interactive Map:</b>", body_style),
        Spacer(1, 3),
        qr_img_rl,
        Spacer(1, 3),
        Paragraph(
            f"<a href='{_esc(data.map_link)}'>Open ArcGIS Web Map</a>",
            ParagraphStyle("Link", parent=body_style, textColor=colors.blue, fontSize=7.5),
        ),
    ]

    media_table = Table([[dp_img_rl, qr_cell]], colWidths=[330, 210])
    media_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ]
        )
    )
    story.append(media_table)

    story.append(PageBreak())
    story.append(Paragraph("<b>SATELLITE & ADJOINING PLOT ANALYSIS</b>", page_two_title_style))
    story.append(
        Paragraph(
            f"Spatial Planning Screening Report | Page 2 of 2 | Plot CTS {_esc(data.cts_number)} ({_esc(data.village.upper())})",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 8))

    sat_img_rl = RLImage(data.satellite_path, width=540, height=340, kind="proportional")
    story.append(sat_img_rl)
    story.append(Spacer(1, 10))

    story.append(
        Paragraph(
            "<b>Adjoining / Neighboring CTS Parcels (Spatial Cluster):</b>",
            ParagraphStyle("H2", parent=bold_style, fontSize=10, textColor=colors.HexColor("#1A237E")),
        )
    )
    story.append(Spacer(1, 4))

    adj_table_data = [
        [
            Paragraph("<b>Adjoining CTS No.</b>", bold_style),
            Paragraph("<b>Village</b>", bold_style),
            Paragraph("<b>Area (sq m) / basis</b>", bold_style),
        ]
    ]
    for n in data.neighbours[:8]:
        area_basis = {
            "Recorded plot area": "MCGM recorded area",
            "Calculated boundary area": "Calculated nearby pieces",
            "Unavailable": "Area unavailable",
        }.get(str(n.get("area_source", "")), "Source record area")
        area_text = f"{_esc(n['area_sqm'])} sq m" if n["area_sqm"] != "N/A" else "N/A"
        adj_table_data.append(
            [
                Paragraph(f"CTS {_esc(n['cts_no'])}", body_style),
                Paragraph(_esc(n["village"].upper()), body_style),
                Paragraph(f"{area_text}<br/>{_esc(area_basis)}", body_style),
            ]
        )
    if not data.neighbours:
        adj_table_data.append(
            [
                Paragraph("No immediate adjoining CTS polygons detected in buffer", body_style),
                Paragraph("-", body_style),
                Paragraph("-", body_style),
            ]
        )

    adj_table = Table(adj_table_data, colWidths=[180, 180, 180])
    adj_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECEFF1")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CFD8DC")),
                ("PADDING", (0, 0), (-1, -1), 3.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(adj_table)
    if any(n.get("area_source") == "Calculated boundary area" for n in data.neighbours[:8]):
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                "Calculated neighbour areas cover nearby source pieces. "
                "A full CTS lookup may include additional pieces and a larger area.",
                body_style,
            )
        )

    doc.build(story)
