"""Builders for the typed exporter contracts used across report tests."""

from typing import Any

from dp_lookup.exporters.contracts import PlotReportData

DEFAULT_REPORT: dict[str, Any] = {
    "output_path": "report.pdf",
    "status_badge": "CLEAR",
    "status_summary": "Clear",
    "village": "WORLI",
    "attrs": {"WARD": "G/S", "TYPE": "CTS"},
    "cts_number": "947",
    "zone": "R",
    "reservation_code": "None",
    "reservation_type": "None",
    "designation_description": "None",
    "designation_code": "None",
    "modification_approval": "None",
    "modification_label": "None",
    "modification_document": "None",
    "crz_status": "NO",
    "metro_buffer": "NO",
    "road_name": "Road",
    "road_width": "12 M",
    "neighbours": (),
    "reservations": (),
    "designations": (),
    "encumbered_percent": 0.0,
    "encumbered_area_sqm": 0.0,
    "net_unencumbered_sqm": 0.0,
    "area_source_label": "MCGM cadastral parcel record",
    "dp_map_path": "dp.png",
    "satellite_path": "sat.png",
    "qr_png": None,
    "map_link": "https://example.invalid/plot",
}


def plot_report(**fields: Any) -> PlotReportData:
    return PlotReportData(**{**DEFAULT_REPORT, **fields})
