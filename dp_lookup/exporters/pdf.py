"""
ReportLab 2-Page DP Remark PDF Report Builder.
"""

import datetime
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _esc(val: Any) -> str:
    """XML-escape data values before putting them into ReportLab Paragraphs."""
    if val is None:
        return ""
    return xml_escape(str(val))


def build_pdf_doc(
    pdf_path: str,
    status_badge: str,
    status_summary: str,
    village: str,
    attrs: Dict[str, Any],
    cts_number: str,
    zone: str,
    des_desc: str,
    des_code: str,
    mod_approval: str,
    mod_label: str,
    crz_buffer_flag: str,
    metro_buffer_flag: str,
    road_name: str,
    road_width: str,
    dp_snapshot_path: str,
    qr_bytes: Any,
    map_link: str,
    sat_snapshot_path: str,
    neighbors: List[Dict[str, Any]],
    area_source_label: str = "MCGM cadastral parcel record",
    *,
    res_code: str = "None",
    res_type: str = "None",
    reservations: Optional[List[Dict[str, Any]]] = None,
    designations: Optional[List[Dict[str, Any]]] = None,
    encumbered_percent: float = 0.0,
    encumbered_area_sqm: float = 0.0,
    net_unencumbered_sqm: float = 0.0,
) -> None:
    """
    Build a strictly 2-page, high-density DP Remark Dossier PDF.
    Page 1: Title, Status banner, Planning attributes table, HD DP Map, Interactive QR Code.
    Page 2: Title, Satellite Aerial View, Adjoining cadastral cluster table.
    """
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
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
        if "CLEAR" in status_badge
        else (
            colors.HexColor("#FFFDE7")
            if ("MODIFIED" in status_badge or "PARTIALLY" in status_badge)
            else colors.HexColor("#FFEBEE")
        )
    )
    banner_text = f"<b>STATUS: {_esc(status_badge)}</b> - {_esc(status_summary)}"
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

    mod_label_trimmed = mod_label[:60] + ("..." if len(mod_label) > 60 else "")

    # Format reservation details (cap at 3 in summary table to guarantee 2-page docket)
    res_items = reservations or []
    if res_items:
        res_display = [
            f"• <b>{_esc(r['code'])}</b> ({_esc(r['description'])}) - {_esc(str(r['overlap_sqm']))} m² ({_esc(str(r['overlap_percent']))}%)"
            for r in res_items[:3]
        ]
        if len(res_items) > 3:
            res_display.append(f"• <i>... and {len(res_items) - 3} more reservations (see CAD/GeoJSON)</i>")
        res_text = "<br/>".join(res_display)
    elif res_code != "None":
        res_text = f"<b>{_esc(res_code)}</b> ({_esc(res_type)})"
    else:
        res_text = "None"

    # Format designation details (cap at 3 in summary table)
    des_items = designations or []
    if des_items:
        des_display = [
            f"• <b>{_esc(d['code'])}</b> ({_esc(d['description'])}) - {_esc(str(d['overlap_sqm']))} m² ({_esc(str(d['overlap_percent']))}%)"
            for d in des_items[:3]
        ]
        if len(des_items) > 3:
            des_display.append(f"• <i>... and {len(des_items) - 3} more designations (see CAD/GeoJSON)</i>")
        des_text = "<br/>".join(des_display)
    elif des_desc != "None":
        des_text = f"{_esc(des_desc)} ({_esc(des_code)})"
    else:
        des_text = "None"

    area_assessment = attrs.get("_DP_AREA_ASSESSMENT")
    authority = attrs.get("_DP_AUTHORITY_RESOLUTION")
    if not isinstance(authority, dict):
        authority = {}
    area_authority = authority.get("area") if isinstance(authority.get("area"), dict) else {}
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
        working_source = area_authority.get("source_label") or area_source_label
        authority_note = (
            "Active authority record(s): " + ", ".join(str(value) for value in active_authority_ids)
            if active_authority_ids
            else "No certified source has been activated"
        )
        area_rows = [
            [
                Paragraph("Working plot area", body_style),
                Paragraph(f"{_esc(selected_area)} sq m" if selected_area is not None else "Not available", body_style),
                Paragraph(_esc(working_source), body_style),
            ],
            [
                Paragraph("Source area comparison", body_style),
                Paragraph(
                    f"Recorded: {_esc(recorded_area)} sq m<br/>Boundary: {_esc(calculated_area)} sq m",
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
                    f"{_esc(attrs.get('AREA_APP_SQ_MTRS'))} sq m" if attrs.get("AREA_APP_SQ_MTRS") else "Not available",
                    body_style,
                ),
                Paragraph(_esc(area_source_label), body_style),
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
            Paragraph(f"{_esc(village.upper())} (Ward {_esc(attrs['WARD'])})", body_style),
            Paragraph("MCGM Administrative Division", body_style),
        ],
        [
            Paragraph("Plot CTS No.", body_style),
            Paragraph(f"CTS {_esc(cts_number)} ({_esc(attrs['TYPE'])})", body_style),
            Paragraph("City Survey Cadastral Parcel", body_style),
        ],
        *area_rows,
        [
            Paragraph("Land-Use Zone", body_style),
            Paragraph(f"<b>Zone {_esc(zone)}</b>", body_style),
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
    if encumbered_percent > 0.0:
        table_data.append(
            [
                Paragraph("Encumbrance", body_style),
                Paragraph(
                    f"<b>{encumbered_percent:.1f}% Encumbered</b> ({encumbered_area_sqm:,.1f} m²)<br/>Net Unencumbered: <b>{net_unencumbered_sqm:,.1f} m²</b>",
                    body_style,
                ),
                Paragraph("Spatial Polygon Overlay", body_style),
            ]
        )
    table_data += [
        [
            Paragraph("DP Modification", body_style),
            Paragraph(f"Approval: {_esc(mod_approval)}", body_style),
            Paragraph(_esc(mod_label_trimmed), body_style),
        ],
        [
            Paragraph("CRZ Status", body_style),
            Paragraph(f"<b>{_esc(crz_buffer_flag)}</b>", body_style),
            Paragraph("Coastal Regulation Zone Layer Query", body_style),
        ],
        [
            Paragraph("Metro Buffer", body_style),
            Paragraph(_esc(metro_buffer_flag), body_style),
            Paragraph("Layer 1550 Metro Rail Influence", body_style),
        ],
        [
            Paragraph("Abutting Road", body_style),
            Paragraph(f"<b>{_esc(road_name)}</b> ({_esc(road_width)})", body_style),
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
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 4))

    dp_img_rl = RLImage(dp_snapshot_path, width=290, height=290)
    qr_img_rl = RLImage(qr_bytes, width=85, height=85)

    qr_cell = [
        Paragraph("<b>Scan for Live Interactive Map:</b>", body_style),
        Spacer(1, 3),
        qr_img_rl,
        Spacer(1, 3),
        Paragraph(
            f"<a href='{_esc(map_link)}'>Open ArcGIS Web Map</a>",
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
            f"Spatial Planning Screening Report | Page 2 of 2 | Plot CTS {_esc(cts_number)} ({_esc(village.upper())})",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 8))

    sat_img_rl = RLImage(sat_snapshot_path, width=540, height=340)
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
            Paragraph("<b>Plot Area (sq m)</b>", bold_style),
        ]
    ]
    for n in neighbors[:8]:
        adj_table_data.append(
            [
                Paragraph(f"CTS {_esc(n['cts_no'])}", body_style),
                Paragraph(_esc(n["village"].upper()), body_style),
                Paragraph(f"{_esc(n['area_sqm'])} sq m" if n["area_sqm"] != "N/A" else "N/A", body_style),
            ]
        )
    if not neighbors:
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

    doc.build(story)
