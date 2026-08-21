"""Typed contracts passed between lookup application stages."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dp_lookup.core.models import AreaAssessment, ExportData


@dataclass
class ParcelContext:
    village: str
    cts_no: str
    attrs: Dict[str, Any]
    rings: List[List[List[float]]]
    wgs_rings: List[List[List[float]]]
    area_sqm: float
    area_source: str
    latitude: float
    longitude: float
    cx: float
    cy: float
    mcx: float
    mcy: float
    xs: List[float]
    ys: List[float]
    window_radius: float
    area_assessment: Optional[AreaAssessment] = None
    authority_resolution: Optional[Mapping[str, Any]] = None


@dataclass
class RoadContext:
    name: str
    width: str
    geometries: List[List[List[float]]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence_state: str = "confirmed"
    method: str = "boundary_probe"
    source_layer_ids: List[int] = field(default_factory=list)
    source_object_ids: List[int] = field(default_factory=list)
    distance_m: Optional[float] = None
    snapshot_id: Optional[int] = None


@dataclass
class NeighbourContext:
    plots: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence_state: str = "confirmed"
    method: str = "probe"


@dataclass
class PlanningContext:
    zone: str
    zones: List[Mapping[str, Any]]
    reservations: List[Dict[str, Any]]
    designations: List[Dict[str, Any]]
    modifications: List[Dict[str, Any]]
    metro_buffer: str
    crz_status: str
    encumbered_area_sqm: float
    encumbered_percent: float
    net_unencumbered_sqm: float
    net_unencumbered_percent: float
    status_badge: str
    status_summary: str
    warnings: List[str] = field(default_factory=list)
    evidence: Dict[str, Dict[str, Any]] = field(default_factory=dict)

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
    def filenames(self) -> Dict[str, str]:
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
    artifact_outputs: Dict[str, str] = field(default_factory=dict)


@dataclass
class MapFetchContext:
    dp_response: Any
    satellite_tiles: Any
    satellite_coordinates: List[Tuple[int, int]]
    bbox: Tuple[float, float, float, float]
    size: Tuple[int, int]
    tile_x: int
    tile_y: int
    zoom: int
    grid_dimension: int
