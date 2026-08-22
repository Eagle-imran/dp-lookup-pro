"""Typed artifact plug-in boundary and adapters for legacy writer functions.

Every generated file crosses this module through a small request object.  The
older public writer functions remain supported here, at the implementation
edge, instead of leaking their long positional signatures into orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Protocol, Sequence, Tuple, Union

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

Rings = List[List[List[float]]]
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
        neighbors: List[Dict[str, Any]],
        roads: RoadGeometry,
        reservations: List[Dict[str, Any]],
        designations: List[Dict[str, Any]],
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


class LegacyArtifactProcedure(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> None: ...


class PdfDataWriter(Protocol):
    def __call__(self, data: PlotReportData) -> None: ...


class ExcelDataWriter(Protocol):
    def __call__(self, data: ExcelRegisterData) -> None: ...


def _plot_report_data(
    request: Union[PdfReportRequest, ExcelRegisterRequest],
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
class LegacyPdfReportWriter:
    """Adapter which keeps ``build_pdf_doc`` publicly compatible."""

    writer: LegacyArtifactProcedure

    def write(self, request: PdfReportRequest) -> None:
        artifact = request.context.artifact
        parcel = artifact.parcel
        planning = artifact.planning
        road = artifact.road
        self.writer(
            request.output_path,
            planning.status_badge,
            planning.status_summary,
            parcel.village,
            parcel.attrs,
            parcel.cts_no,
            planning.zone,
            planning.designation_description,
            planning.designation_code,
            planning.modification_approval,
            planning.modification_label,
            planning.crz_status,
            planning.metro_buffer,
            road.name,
            road.width,
            request.context.maps.dp_map_path,
            request.context.maps.qr_png,
            artifact.map_link,
            request.context.maps.satellite_path,
            artifact.neighbours.plots,
            (
                "MCGM cadastral parcel record"
                if parcel.area_source == "Recorded plot area"
                else "Calculated from the MCGM cadastral parcel boundary for screening"
            ),
            res_code=planning.reservation_code,
            res_type=planning.reservation_type,
            reservations=planning.reservations,
            designations=planning.designations,
            encumbered_percent=planning.encumbered_percent,
            encumbered_area_sqm=planning.encumbered_area_sqm,
            net_unencumbered_sqm=planning.net_unencumbered_sqm,
        )


@dataclass(frozen=True)
class LegacyExcelRegisterWriter:
    """Adapter which keeps ``update_excel_register`` publicly compatible."""

    writer: LegacyArtifactProcedure

    def write(self, request: ExcelRegisterRequest) -> None:
        artifact = request.context.artifact
        parcel = artifact.parcel
        planning = artifact.planning
        road = artifact.road
        filenames = artifact.paths.filenames
        self.writer(
            register_path=request.output_path,
            attrs=parcel.attrs,
            village=parcel.village,
            cts_number=parcel.cts_no,
            zone=planning.zone,
            status_badge=planning.status_badge,
            res_code=planning.reservation_code,
            res_type=planning.reservation_type,
            des_code=planning.designation_code,
            des_desc=planning.designation_description,
            mod_approval=planning.modification_approval,
            mod_label=planning.modification_label,
            mod_doc=planning.modification_document,
            crz_buffer_flag=planning.crz_status,
            metro_buffer_flag=planning.metro_buffer,
            road_name=road.name,
            road_width=road.width,
            neighbors=artifact.neighbours.plots,
            dp_snapshot_fname=filenames["dp_map"],
            sat_snapshot_fname=filenames["satellite"],
            pdf_fname=filenames["pdf"],
            dxf_fname=filenames["dxf"],
            geojson_fname=filenames["geojson"],
            kml_fname=filenames["kml"],
            map_link=artifact.map_link,
            reservations=planning.reservations,
            designations=planning.designations,
        )


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


def registered_artifact_exporters(dependencies: LookupDependencies) -> Tuple[ArtifactExporter, ...]:
    """Resolve built-ins plus caller-supplied plug-ins without editing orchestration."""
    built_ins: Tuple[ArtifactExporter, ...] = (
        SimpleVectorExporter("GeoJSON", "autocad_geojson", "geojson", dependencies.geojson_writer),
        RichVectorExporter("DXF", "autocad_dxf", "dxf", dependencies.dxf_writer),
        SimpleVectorExporter("KML", "google_earth_kml", "kml", dependencies.kml_writer),
        RichVectorExporter("HTML map", "interactive_html_map", "html_map", dependencies.html_writer),
    )
    return built_ins + tuple(dependencies.artifact_exporters)


def registered_report_artifact_exporters(dependencies: LookupDependencies) -> Tuple[ReportArtifactExporter, ...]:
    """Resolve typed PDF/register adapters plus optional report-stage plug-ins."""
    if dependencies.pdf_report_writer is not None:
        pdf_writer: PdfReportWriter = dependencies.pdf_report_writer
    elif dependencies.pdf_writer is not None:
        pdf_writer = LegacyPdfReportWriter(dependencies.pdf_writer)
    else:
        pdf_writer = TypedPdfReportWriter(dependencies.pdf_data_writer)

    if dependencies.excel_register_writer is not None:
        excel_writer: ExcelRegisterWriter = dependencies.excel_register_writer
    elif dependencies.excel_writer is not None:
        excel_writer = LegacyExcelRegisterWriter(dependencies.excel_writer)
    else:
        excel_writer = TypedExcelRegisterWriter(dependencies.excel_data_writer)
    built_ins: Tuple[ReportArtifactExporter, ...] = (
        PdfArtifactExporter(pdf_writer),
        ExcelArtifactExporter(excel_writer),
    )
    return built_ins + tuple(dependencies.report_artifact_exporters)
