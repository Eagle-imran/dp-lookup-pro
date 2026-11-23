"""Typed contracts passed between lookup application stages."""

from __future__ import annotations

import io
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dp_lookup.core.models import AreaAssessment, ExportData


@dataclass
class ParcelContext:
    village: str
    cts_no: str
    attrs: dict[str, Any]
    rings: list[list[list[float]]]
    wgs_rings: list[list[list[float]]]
    area_sqm: float
    area_source: str
    latitude: float
    longitude: float
    cx: float
    cy: float
    mcx: float
    mcy: float
    xs: list[float]
    ys: list[float]
    window_radius: float
    area_assessment: AreaAssessment | None = None
    authority_resolution: Mapping[str, Any] | None = None


@dataclass
class RoadContext:
    name: str
    width: str
    geometries: list[list[list[float]]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_state: str = "confirmed"
    method: str = "boundary_probe"
    source_layer_ids: list[int] = field(default_factory=list)
    source_object_ids: list[int] = field(default_factory=list)
    distance_m: float | None = None
    snapshot_id: int | None = None
    selected_source_layer_id: int | None = None
    selected_source_object_id: int | None = None


@dataclass
class NeighbourContext:
    plots: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_state: str = "confirmed"
    method: str = "probe"


@dataclass
class PlanningContext:
    zone: str
    zones: Sequence[Mapping[str, Any]]
    reservations: list[dict[str, Any]]
    designations: list[dict[str, Any]]
    modifications: list[dict[str, Any]]
    metro_buffer: str
    crz_status: str
    encumbered_area_sqm: float
    encumbered_percent: float
    net_unencumbered_sqm: float
    net_unencumbered_percent: float
    status_badge: str
    status_summary: str
    warnings: list[str] = field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def reservation_code(self) -> str:
        return str(self.reservations[0].get("code", "None")) if self.reservations else "None"

    @property
    def reservation_type(self) -> str:
        return str(self.reservations[0].get("type", "None")) if self.reservations else "None"

    @property
    def designation_code(self) -> str:
        return str(self.designations[0].get("code", "None")) if self.designations else "None"

    @property
    def designation_description(self) -> str:
        return str(self.designations[0].get("description", "None")) if self.designations else "None"

    @property
    def modification_approval(self) -> str:
        return str(self.modifications[0].get("approval_no", "None")) if self.modifications else "None"

    @property
    def modification_label(self) -> str:
        return str(self.modifications[0].get("details", "None")) if self.modifications else "None"

    @property
    def modification_document(self) -> str:
        return str(self.modifications[0].get("document_link", "None")) if self.modifications else "None"


@dataclass(frozen=True)
class OutputPaths:
    bundle_folder: str
    register: str
    pdf: str
    dp_map: str
    satellite: str
    dxf: str
    geojson: str
    kml: str
    html_map: str

    @property
    def filenames(self) -> dict[str, str]:
        return {
            "pdf": os.path.basename(self.pdf),
            "dp_map": os.path.basename(self.dp_map),
            "satellite": os.path.basename(self.satellite),
            "dxf": os.path.basename(self.dxf),
            "geojson": os.path.basename(self.geojson),
            "kml": os.path.basename(self.kml),
        }


@dataclass
class ArtifactContext:
    parcel: ParcelContext
    planning: PlanningContext
    road: RoadContext
    neighbours: NeighbourContext
    paths: OutputPaths
    map_link: str
    export_data: ExportData
    nearest_roads: Sequence[Sequence[Sequence[float]]]
    artifact_outputs: dict[str, str] = field(default_factory=dict)


@dataclass
class MapFetchContext:
    dp_response: Any
    satellite_tiles: Any
    satellite_coordinates: list[tuple[int, int]]
    bbox: tuple[float, float, float, float]
    size: tuple[int, int]
    tile_x: int
    tile_y: int
    zoom: int
    grid_dimension: int


@dataclass(frozen=True)
class DpMapRenderRequest:
    """Everything needed to render the Development Plan image."""

    base_png: bytes | None
    rings: list[list[list[float]]]
    bbox: tuple[float, float, float, float]
    size: tuple[int, int]
    labels: Mapping[str, Any]


@dataclass(frozen=True)
class SatelliteRenderRequest:
    """Everything needed to stitch and annotate the satellite image."""

    tiles: list[Any]
    coordinates: list[tuple[int, int]]
    grid_dimension: int
    wgs_rings: list[list[list[float]]]
    bounds: tuple[float, float, float, float]
    labels: Mapping[str, Any]


@dataclass(frozen=True)
class RenderedMapAssets:
    """Rendered files shared by the report exporters in one lookup bundle."""

    dp_map_path: str
    satellite_path: str
    qr_png: io.BytesIO


@dataclass(frozen=True)
class ReportArtifactContext:
    """Typed view of a lookup supplied to report and register exporters."""

    artifact: ArtifactContext
    maps: RenderedMapAssets


@dataclass(frozen=True)
class PdfReportRequest:
    """Stable, complete input contract for a PDF dossier writer."""

    context: ReportArtifactContext

    @property
    def output_path(self) -> str:
        return self.context.artifact.paths.pdf


@dataclass(frozen=True)
class ExcelRegisterRequest:
    """Stable, complete input contract for the master-register writer."""

    context: ReportArtifactContext

    @property
    def output_path(self) -> str:
        return self.context.artifact.paths.register
