"""Typed payloads shared by exporter implementations and their adapters."""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Union

from dp_lookup.core.models import ExportData

ExportPayload = Union[ExportData, Mapping[str, Any]]


@dataclass(frozen=True)
class PlotReportData:
    """Renderer-neutral plot facts used by the human-readable reports."""

    output_path: str
    status_badge: str
    status_summary: str
    village: str
    attrs: Mapping[str, Any]
    cts_number: str
    zone: str
    reservation_code: str
    reservation_type: str
    designation_description: str
    designation_code: str
    modification_approval: str
    modification_label: str
    modification_document: str
    crz_status: str
    metro_buffer: str
    road_name: str
    road_width: str
    neighbours: Sequence[Mapping[str, Any]]
    reservations: Sequence[Mapping[str, Any]]
    designations: Sequence[Mapping[str, Any]]
    encumbered_percent: float
    encumbered_area_sqm: float
    net_unencumbered_sqm: float
    area_source_label: str
    dp_map_path: str
    satellite_path: str
    qr_png: Any
    map_link: str


@dataclass(frozen=True)
class ExcelRegisterData:
    """Complete typed input for one append to the master register."""

    report: PlotReportData
    artifact_filenames: Mapping[str, str]


def legacy_export_properties(payload: ExportPayload) -> Dict[str, Any]:
    """Return the historical mapping shape at the renderer implementation edge."""
    if isinstance(payload, ExportData):
        return payload.to_legacy_dict()
    return dict(payload)
