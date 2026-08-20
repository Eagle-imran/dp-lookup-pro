"""Composition root for replaceable network, export, and rendering adapters."""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, List, Optional, Protocol, Sequence, Tuple

from PIL import Image

from dp_lookup.application.contracts import NeighbourContext, ParcelContext, RoadContext
from dp_lookup.application.exporting import ArtifactExporter, RichVectorWriter, SimpleVectorWriter
from dp_lookup.application.ingestion import fetch_parcel_feature
from dp_lookup.clients.arcgis import fetch_tile_cached, query_spatial_planning_layers
from dp_lookup.clients.planning_evidence_queries import collect_planning_evidence
from dp_lookup.clients.transport import create_arcgis_client
from dp_lookup.exporters.dxf import export_dxf
from dp_lookup.exporters.excel import update_excel_register
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.html_map import export_html_map
from dp_lookup.exporters.kml import export_kml
from dp_lookup.exporters.pdf import build_pdf_doc
from dp_lookup.planning_evidence.models import EvidenceMode, PlanningEvidenceReport
from dp_lookup.renderers.map_overlay import render_dp_map
from dp_lookup.renderers.satellite import stitch_satellite


class ClientFactory(Protocol):
    def __call__(self, timeout_seconds: float, verify_tls: bool = True) -> Any: ...


class ParcelFetcher(Protocol):
    def __call__(self, client: Any, village: str, cts_no: str) -> Awaitable[Optional[Dict[str, Any]]]: ...


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
    neighbour_provider: NeighbourProvider = no_local_neighbours
    road_provider: RoadProvider = no_local_roads
    spatial_planning_query: SpatialPlanningQuery = query_spatial_planning_layers
    planning_identify_required: bool = True
    tile_fetcher: TileFetcher = fetch_tile_cached
    geojson_writer: SimpleVectorWriter = export_geojson
    dxf_writer: RichVectorWriter = export_dxf
    kml_writer: SimpleVectorWriter = export_kml
    html_writer: RichVectorWriter = export_html_map
    artifact_exporters: Sequence[ArtifactExporter] = field(default_factory=tuple)
    pdf_writer: ArtifactProcedure = build_pdf_doc
    excel_writer: ArtifactProcedure = update_excel_register
    dp_map_renderer: DpMapRenderer = render_dp_map
    satellite_renderer: SatelliteRenderer = stitch_satellite
    planning_evidence_analyzer: PlanningEvidenceAnalyzer = collect_planning_evidence
    planning_evidence_mode: EvidenceMode = EvidenceMode.BASIC


DEFAULT_DEPENDENCIES = LookupDependencies()
