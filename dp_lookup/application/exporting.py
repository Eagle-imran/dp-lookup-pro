"""Typed artifact plug-in boundary.

Every generated file crosses this module through a small request object, and
the PDF and Excel writers receive frozen ``PlotReportData``/``ExcelRegisterData``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from dp_lookup.application.contracts import (
    ArtifactContext,
    ExcelRegisterRequest,
    PdfReportRequest,
    ReportArtifactContext,
)
from dp_lookup.core.models import ExportData
from dp_lookup.exporters.contracts import ExcelRegisterData, PlotReportData

if TYPE_CHECKING:
    from dp_lookup.application.dependencies import LookupDependencies

Rings = list[list[list[float]]]
RoadGeometry = Sequence[Sequence[Sequence[float]]]


class SimpleVectorWriter(Protocol):
    def __call__(self, wgs_rings: Rings, properties: ExportData, output_path: str) -> None: ...


class RichVectorWriter(Protocol):
    def __call__(
        self,
        wgs_rings: Rings,
        properties: ExportData,
        output_path: str,
        *,
        neighbors: list[dict[str, Any]],
        roads: RoadGeometry,
        reservations: list[dict[str, Any]],
        designations: list[dict[str, Any]],
    ) -> None: ...


class ArtifactExporter(Protocol):
    """Extension point for a synchronous, independently-failable artifact."""

    @property
    def name(self) -> str: ...

    @property
    def manifest_key(self) -> str: ...

    def export(self, context: ArtifactContext) -> str:
        """Write one artifact and return its canonical path."""
        ...


class ReportArtifactExporter(Protocol):
    """Extension point for a report-stage artifact with a typed request."""

    @property
    def name(self) -> str: ...

    @property
    def manifest_key(self) -> str: ...

    def export(self, context: ReportArtifactContext) -> str:
        """Write one report artifact and return its canonical path."""
        ...


class PdfReportWriter(Protocol):
    """Modern output port for a PDF dossier implementation."""

    def write(self, request: PdfReportRequest) -> None: ...


class ExcelRegisterWriter(Protocol):
    """Modern output port for the master-register implementation."""

    def write(self, request: ExcelRegisterRequest) -> None: ...


class PdfDataWriter(Protocol):
    def __call__(self, data: PlotReportData) -> None: ...


class ExcelDataWriter(Protocol):
    def __call__(self, data: ExcelRegisterData) -> None: ...


def _plot_report_data(
    request: PdfReportRequest | ExcelRegisterRequest,
    output_path: str,
) -> PlotReportData:
    artifact = request.context.artifact
    parcel = artifact.parcel
    planning = artifact.planning
    road = artifact.road
    return PlotReportData(
        output_path=output_path,
        status_badge=planning.status_badge,
        status_summary=planning.status_summary,
        village=parcel.village,
        attrs=parcel.attrs,
        cts_number=parcel.cts_no,
        zone=planning.zone,
        reservation_code=planning.reservation_code,
        reservation_type=planning.reservation_type,
        designation_description=planning.designation_description,
        designation_code=planning.designation_code,
        modification_approval=planning.modification_approval,
        modification_label=planning.modification_label,
        modification_document=planning.modification_document,
        crz_status=planning.crz_status,
        metro_buffer=planning.metro_buffer,
        road_name=road.name,
        road_width=road.width,
        neighbours=artifact.neighbours.plots,
        reservations=planning.reservations,
        designations=planning.designations,
        encumbered_percent=planning.encumbered_percent,
        encumbered_area_sqm=planning.encumbered_area_sqm,
        net_unencumbered_sqm=planning.net_unencumbered_sqm,
        area_source_label=(
            "MCGM cadastral parcel record"
            if parcel.area_source == "Recorded plot area"
            else "Calculated from the MCGM cadastral parcel boundary for screening"
        ),
        dp_map_path=request.context.maps.dp_map_path,
        satellite_path=request.context.maps.satellite_path,
        qr_png=request.context.maps.qr_png,
        map_link=artifact.map_link,
    )


@dataclass(frozen=True)
class TypedPdfReportWriter:
    """Translate application context to the native PDF data contract."""

    writer: PdfDataWriter

    def write(self, request: PdfReportRequest) -> None:
        self.writer(_plot_report_data(request, request.output_path))


@dataclass(frozen=True)
class TypedExcelRegisterWriter:
    """Translate application context to the native register data contract."""

    writer: ExcelDataWriter

    def write(self, request: ExcelRegisterRequest) -> None:
        report = _plot_report_data(request, request.output_path)
        self.writer(ExcelRegisterData(report=report, artifact_filenames=request.context.artifact.paths.filenames))


@dataclass(frozen=True)
class SimpleVectorExporter:
    name: str
    manifest_key: str
    path_attribute: str
    writer: SimpleVectorWriter

    def export(self, context: ArtifactContext) -> str:
        output_path = str(getattr(context.paths, self.path_attribute))
        self.writer(context.parcel.wgs_rings, context.export_data, output_path)
        return output_path


@dataclass(frozen=True)
class RichVectorExporter:
    name: str
    manifest_key: str
    path_attribute: str
    writer: RichVectorWriter

    def export(self, context: ArtifactContext) -> str:
        output_path = str(getattr(context.paths, self.path_attribute))
        self.writer(
            context.parcel.wgs_rings,
            context.export_data,
            output_path,
            neighbors=context.neighbours.plots,
            roads=context.nearest_roads,
            reservations=context.planning.reservations,
            designations=context.planning.designations,
        )
        return output_path


@dataclass(frozen=True)
class PdfArtifactExporter:
    writer: PdfReportWriter
    name: str = "PDF report"
    manifest_key: str = "pdf_report"

    def export(self, context: ReportArtifactContext) -> str:
        request = PdfReportRequest(context)
        self.writer.write(request)
        return request.output_path


@dataclass(frozen=True)
class ExcelArtifactExporter:
    writer: ExcelRegisterWriter
    name: str = "Excel register"
    manifest_key: str = "master_excel_register"

    def export(self, context: ReportArtifactContext) -> str:
        request = ExcelRegisterRequest(context)
        self.writer.write(request)
        return request.output_path


def registered_artifact_exporters(dependencies: LookupDependencies) -> tuple[ArtifactExporter, ...]:
    """Resolve built-ins plus caller-supplied plug-ins without editing orchestration."""
    built_ins: tuple[ArtifactExporter, ...] = (
        SimpleVectorExporter("GeoJSON", "autocad_geojson", "geojson", dependencies.geojson_writer),
        RichVectorExporter("DXF", "autocad_dxf", "dxf", dependencies.dxf_writer),
        SimpleVectorExporter("KML", "google_earth_kml", "kml", dependencies.kml_writer),
        RichVectorExporter("HTML map", "interactive_html_map", "html_map", dependencies.html_writer),
    )
    return built_ins + tuple(dependencies.artifact_exporters)


def registered_report_artifact_exporters(dependencies: LookupDependencies) -> tuple[ReportArtifactExporter, ...]:
    """Resolve typed PDF/register adapters plus optional report-stage plug-ins."""
    if dependencies.pdf_report_writer is not None:
        pdf_writer: PdfReportWriter = dependencies.pdf_report_writer
    else:
        pdf_writer = TypedPdfReportWriter(dependencies.pdf_data_writer)

    if dependencies.excel_register_writer is not None:
        excel_writer: ExcelRegisterWriter = dependencies.excel_register_writer
    else:
        excel_writer = TypedExcelRegisterWriter(dependencies.excel_data_writer)
    built_ins: tuple[ReportArtifactExporter, ...] = (
        PdfArtifactExporter(pdf_writer),
        ExcelArtifactExporter(excel_writer),
    )
    return built_ins + tuple(dependencies.report_artifact_exporters)
