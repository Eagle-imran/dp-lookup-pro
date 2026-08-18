"""
Master Excel Register Log Exporter using openpyxl.
"""
import datetime
import os
from typing import Any, Dict, List

from openpyxl import Workbook, load_workbook


def update_excel_register(
    register_path: str,
    attrs: Dict[str, Any],
    village: str,
    cts_number: str,
    zone: str,
    status_badge: str,
    res_code: str,
    res_type: str,
    des_code: str,
    des_desc: str,
    mod_approval: str,
    mod_label: str,
    mod_doc: str,
    crz_buffer_flag: str,
    metro_buffer_flag: str,
    road_name: str,
    road_width: str,
    neighbors: List[Dict[str, Any]],
    dp_snapshot_fname: str,
    sat_snapshot_fname: str,
    pdf_fname: str,
    dxf_fname: str,
    geojson_fname: str,
    kml_fname: str,
    map_link: str,
    reservations: Any = None,
    designations: Any = None,
) -> None:
    """Append a structured lookup record row to the master Excel register."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    headers = [
        "lookup_datetime", "source", "ward", "village", "cts_no", "type",
        "area_sqm", "zone", "status_badge", "reservation_code", "reservation_type",
        "designation_code", "designation_desc", "modification_approval",
        "modification_label", "modification_doc", "crz_buffer", "metro_buffer",
        "abutting_road", "road_width", "adjoining_plots_count", "hd_snapshot_file",
        "satellite_snapshot_file", "pdf_report_file", "dxf_file", "geojson_file", "kml_file", "map_link"
    ]

    excel_res_code = "; ".join(r["code"] for r in reservations) if reservations else res_code
    excel_res_type = "; ".join(f"{r['type']} ({r['description']})" for r in reservations) if reservations else res_type
    excel_des_code = "; ".join(d["code"] for d in designations) if designations else des_code
    excel_des_desc = "; ".join(d["description"] for d in designations) if designations else des_desc

    row = [
        now_str, "MCGM SDP 2014-34", attrs.get("WARD"), village, cts_number, attrs.get("TYPE"),
        attrs.get("AREA_APP_SQ_MTRS"), zone, status_badge, excel_res_code, excel_res_type,
        excel_des_code, excel_des_desc, mod_approval, mod_label, mod_doc, crz_buffer_flag, metro_buffer_flag,
        road_name, road_width, len(neighbors), dp_snapshot_fname, sat_snapshot_fname, pdf_fname,
        dxf_fname, geojson_fname, kml_fname, map_link
    ]

    os.makedirs(os.path.dirname(os.path.abspath(register_path)), exist_ok=True)
    wb = load_workbook(register_path) if os.path.exists(register_path) else Workbook()
    ws = wb.active
    if ws.max_row == 1 and ws["A1"].value is None:
        ws.append(headers)
    ws.append(row)
    wb.save(register_path)
