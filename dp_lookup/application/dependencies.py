"""Composition root for replaceable network, export, and rendering adapters."""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, List, Optional, Protocol, Sequence, Tuple

from PIL import Image

from dp_lookup.application.contracts import NeighbourContext, ParcelContext, RoadContext
from dp_lookup.application.exporting import (
    ArtifactExporter,
    ExcelDataWriter,
    ExcelRegisterWriter,
    PdfDataWriter,
    PdfReportWriter,
    ReportArtifactExporter,
    RichVectorWriter,
    SimpleVectorWriter,
)
from dp_lookup.application.ingestion import fetch_parcel_feature
from dp_lookup.clients.arcgis import fetch_tile_cached, query_spatial_planning_layers
from dp_lookup.clients.cache import read_cache_entry, write_cache_entry
from dp_lookup.clients.planning_evidence_queries import collect_planning_evidence
from dp_lookup.clients.transport import create_arcgis_client
from dp_lookup.exporters.dxf import export_dxf
from dp_lookup.exporters.excel import write_excel_register
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.html_map import export_html_map
from dp_lookup.exporters.kml import export_kml
from dp_lookup.exporters.pdf import write_pdf_report
from dp_lookup.planning_evidence.models import EvidenceMode, PlanningEvidenceReport
from dp_lookup.renderers.map_overlay import render_dp_map
from dp_lookup.renderers.satellite import stitch_satellite


class ClientFactory(Protocol):
    def __call__(self, timeout_seconds: float, verify_tls: bool = True) -> Any: ...


class ParcelFetcher(Protocol):
    def __call__(self, client: Any, village: str, cts_no: str) -> Awaitable[Optional[Dict[str, Any]]]: ...


class ParcelAuthorityResolver(Protocol):
    """Optionally apply explicitly activated authority evidence to a parcel."""

    def __call__(self, parcel: ParcelContext) -> ParcelContext: ...


def no_authority_resolution(parcel: ParcelContext) -> ParcelContext:
    return parcel


class NeighbourProvider(Protocol):
    def __call__(self, parcel: ParcelContext) -> Optional[NeighbourContext]: ...


def no_local_neighbours(parcel: ParcelContext) -> Optional[NeighbourContext]:
    del parcel
    return None


class RoadProvider(Protocol):
    def __call__(self, parcel: ParcelContext) -> Optional[RoadContext]: ...


def no_local_roads(parcel: ParcelContext) -> Optional[RoadContext]:
    del parcel
    return None


class SpatialPlanningQuery(Protocol):
    def __call__(self, client: Any, rings: List[Any]) -> Awaitable[Dict[str, Any]]: ...


class PlanningEvidenceAnalyzer(Protocol):
    def __call__(
        self,
        client: Any,
        rings: List[Any],
        village: str,
        mode: EvidenceMode,
    ) -> Awaitable[PlanningEvidenceReport]: ...


class TileFetcher(Protocol):
    def __call__(
        self,
        client: Any,
        zoom: int,
        ytile: int,
        xtile: int,
        tile_dir: str = "/tmp/dp_tile_cache",
    ) -> Awaitable[Optional[bytes]]: ...


class ResultCacheReader(Protocol):
    def __call__(self, output_dir: str, key: str, ttl_seconds: int) -> Optional[Dict[str, Any]]: ...


class ResultCacheWriter(Protocol):
    def __call__(self, output_dir: str, key: str, result: Dict[str, Any]) -> None: ...


class ArtifactProcedure(Protocol):
    """Legacy report/register callable retained behind a named output port."""

    def __call__(self, *args: Any, **kwargs: Any) -> None: ...


class DpMapRenderer(Protocol):
    def __call__(
        self,
        base_png: Optional[bytes],
        rings: List[Any],
        bbox: Tuple[float, float, float, float],
        size: Tuple[int, int],
        labels: Dict[str, Any],
    ) -> Image.Image: ...


class SatelliteRenderer(Protocol):
    def __call__(
        self,
        tiles: List[Any],
        coords: List[Tuple[int, int]],
        grid_dim: int,
        wgs_rings: List[List[List[float]]],
        bounds: Tuple[float, float, float, float],
        labels: Dict[str, Any],
    ) -> Image.Image: ...


@dataclass(frozen=True)
class LookupDependencies:
    """Adapters used by the lookup use case.

    Tests and future UIs can replace any boundary without monkeypatching module
    globals or changing the deterministic domain functions.
    """

    client_factory: ClientFactory = create_arcgis_client
    parcel_fetcher: ParcelFetcher = fetch_parcel_feature
    parcel_cache_namespace: str = "live"
    authority_resolver: ParcelAuthorityResolver = no_authority_resolution
    neighbour_provider: NeighbourProvider = no_local_neighbours
    road_provider: RoadProvider = no_local_roads
    spatial_planning_query: SpatialPlanningQuery = query_spatial_planning_layers
    planning_identify_required: bool = True
    tile_fetcher: TileFetcher = fetch_tile_cached
    result_cache_reader: ResultCacheReader = read_cache_entry
    result_cache_writer: ResultCacheWriter = write_cache_entry
    geojson_writer: SimpleVectorWriter = export_geojson
    dxf_writer: RichVectorWriter = export_dxf
    kml_writer: SimpleVectorWriter = export_kml
    html_writer: RichVectorWriter = export_html_map
    artifact_exporters: Sequence[ArtifactExporter] = field(default_factory=tuple)
    report_artifact_exporters: Sequence[ReportArtifactExporter] = field(default_factory=tuple)
    pdf_report_writer: Optional[PdfReportWriter] = None
    excel_register_writer: Optional[ExcelRegisterWriter] = None
    pdf_data_writer: PdfDataWriter = write_pdf_report
    excel_data_writer: ExcelDataWriter = write_excel_register
    pdf_writer: Optional[ArtifactProcedure] = None
    excel_writer: Optional[ArtifactProcedure] = None
    dp_map_renderer: DpMapRenderer = render_dp_map
    satellite_renderer: SatelliteRenderer = stitch_satellite
    planning_evidence_analyzer: PlanningEvidenceAnalyzer = collect_planning_evidence
    planning_evidence_mode: EvidenceMode = EvidenceMode.BASIC


DEFAULT_DEPENDENCIES = LookupDependencies()
