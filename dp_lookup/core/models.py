"""Typed domain contracts for lookup results.

The public API historically returns dictionaries.  These models give the
application an explicit internal contract while ``to_dict()`` preserves that
legacy wire format for CLI, cache, and third-party callers.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence


class EvidenceState(str, Enum):
    """Whether a source-backed fact is known, absent, or unavailable."""

    CONFIRMED = "confirmed"
    NOT_PRESENT = "not_present"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True)
class ExportData:
    """Typed, renderer-neutral payload for bundle artifact exporters."""

    village: str
    cts_no: str
    ward: str
    plot_type: str
    area_sqm: float
    zone: str
    status_badge: str
    reservation_code: str
    reservation_type: str
    designation_description: str
    modification_approval: str
    crz_status: str
    metro_buffer: str
    abutting_road: str
    road_width: str
    area_source: str
    adjoining_plots_count: int
    map_link: str
    reservations: Sequence[Mapping[str, Any]]
    designations: Sequence[Mapping[str, Any]]
    encumbered_area_sqm: float
    encumbered_percent: float
    net_unencumbered_sqm: float
    net_unencumbered_percent: float

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Adapt at a legacy renderer edge without leaking mutable state."""
        return {
            "village": self.village,
            "cts_no": self.cts_no,
            "ward": self.ward,
            "type": self.plot_type,
            "area_sqm": self.area_sqm,
            "zone": self.zone,
            "status_badge": self.status_badge,
            "reservation_code": self.reservation_code,
            "reservation_type": self.reservation_type,
            "designation_description": self.designation_description,
            "modification_approval": self.modification_approval,
            "crz_buffer_flag": self.crz_status,
            "metro_buffer_flag": self.metro_buffer,
            "abutting_road": self.abutting_road,
            "road_width": self.road_width,
            "area_source": self.area_source,
            "adjoining_cts_plots_count": self.adjoining_plots_count,
            "map_link": self.map_link,
            "reservations": deepcopy(list(self.reservations)),
            "designations": deepcopy(list(self.designations)),
            "encumbered_area_sqm": self.encumbered_area_sqm,
            "encumbered_percent": self.encumbered_percent,
            "net_unencumbered_sqm": self.net_unencumbered_sqm,
            "net_unencumbered_percent": self.net_unencumbered_percent,
        }


@dataclass(frozen=True)
class SourceEvidence:
    """Traceable value returned or derived from a source layer."""

    value: Any
    state: EvidenceState
    source: str
    method: str
    layer_ids: Sequence[int] = field(default_factory=tuple)
    retrieved_at: Optional[str] = None
    warnings: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": deepcopy(self.value),
            "state": self.state.value,
            "source": self.source,
            "method": self.method,
            "layer_ids": list(self.layer_ids),
            "retrieved_at": self.retrieved_at,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PlotIdentity:
    village: str
    cts_no: str
    ward: str
    plot_type: str
    area_sqm: Optional[float]
    area_source: str
    latitude: float
    longitude: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "village": self.village,
            "cts_no": self.cts_no,
            "ward": self.ward,
            "type": self.plot_type,
            "area_sqm": self.area_sqm,
            "area_source": self.area_source,
            "coordinates_wgs84": {
                "latitude": self.latitude,
                "longitude": self.longitude,
            },
        }


@dataclass(frozen=True)
class PlanningRemarks:
    status_badge: str
    status_summary: str
    zone: str
    zones: Sequence[Mapping[str, Any]]
    reservations: Sequence[Mapping[str, Any]]
    designations: Sequence[Mapping[str, Any]]
    modifications: Sequence[Mapping[str, Any]]
    encumbered_area_sqm: float
    encumbered_percent: float
    net_unencumbered_sqm: float
    net_unencumbered_percent: float

    def to_dict(self) -> Dict[str, Any]:
        reservations = deepcopy(list(self.reservations))
        designations = deepcopy(list(self.designations))
        modifications = deepcopy(list(self.modifications))
        first_res = reservations[0] if reservations else {}
        first_des = designations[0] if designations else {}
        first_mod = modifications[0] if modifications else {}
        return {
            "status_badge": self.status_badge,
            "status_summary": self.status_summary,
            "zone": self.zone,
            "zones": deepcopy(list(self.zones)),
            # Singular fields are retained for backwards compatibility.
            "reservation": {
                "code": first_res.get("code", "None"),
                "type": first_res.get("type", "None"),
            },
            "reservations": reservations,
            "designation": {
                "code": first_des.get("code", "None"),
                "description": first_des.get("description", "None"),
            },
            "designations": designations,
            "dp_modification": {
                "approval_no": first_mod.get("approval_no", "None"),
                "details": first_mod.get("details", "None"),
                "document_link": first_mod.get("document_link", "None"),
            },
            "dp_modifications": modifications,
            "encumbrance": {
                "encumbered_area_sqm": self.encumbered_area_sqm,
                "encumbered_percent": self.encumbered_percent,
                "net_unencumbered_sqm": self.net_unencumbered_sqm,
                "net_unencumbered_percent": self.net_unencumbered_percent,
            },
        }


@dataclass(frozen=True)
class RegulatoryInfrastructure:
    crz_status: str
    metro_buffer: str
    road_name: str
    road_width: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "crz_status": self.crz_status,
            "metro_buffer": self.metro_buffer,
            "abutting_road": {"name": self.road_name, "width": self.road_width},
        }


@dataclass(frozen=True)
class SpatialCluster:
    neighbours: Sequence[Mapping[str, Any]]
    method: str = "probe"

    def to_dict(self) -> Dict[str, Any]:
        public_neighbours: List[Dict[str, Any]] = [
            {key: deepcopy(value) for key, value in neighbour.items() if key != "rings"}
            for neighbour in self.neighbours
        ]
        return {
            "adjoining_plots_count": len(public_neighbours),
            "adjoining_cts_plots": public_neighbours,
            "adjacency_method": self.method,
        }


@dataclass(frozen=True)
class ArtifactManifest:
    bundle_folder: str
    pdf_report: str
    hd_dp_map: str
    satellite_view: str
    autocad_dxf: str
    autocad_geojson: str
    google_earth_kml: str
    interactive_html_map: str
    master_excel_register: str
    additional_files: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        manifest = {
            "bundle_folder": self.bundle_folder,
            "pdf_report": self.pdf_report,
            "hd_dp_map": self.hd_dp_map,
            "satellite_view": self.satellite_view,
            "autocad_dxf": self.autocad_dxf,
            "autocad_geojson": self.autocad_geojson,
            "google_earth_kml": self.google_earth_kml,
            "interactive_html_map": self.interactive_html_map,
            "master_excel_register": self.master_excel_register,
        }
        manifest.update(dict(self.additional_files))
        return manifest


@dataclass(frozen=True)
class RunMetadata:
    source: str
    lookup_datetime: str
    execution_time_ms: float
    complete: bool
    documents_pending: bool
    warnings: Sequence[str]
    notes: Sequence[str]
    interactive_web_map: str
    application_version: str
    result_schema_version: int
    cached_result: bool = False
    evidence: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "lookup_datetime": self.lookup_datetime,
            "execution_time_ms": self.execution_time_ms,
            "cached_result": self.cached_result,
            "complete": self.complete,
            "documents_pending": self.documents_pending,
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "interactive_web_map": self.interactive_web_map,
            "application_version": self.application_version,
            "result_schema_version": self.result_schema_version,
            "evidence": deepcopy(dict(self.evidence)),
            "diagnostics": deepcopy(dict(self.diagnostics)),
        }


@dataclass(frozen=True)
class LookupResult:
    plot_identity: PlotIdentity
    planning_remarks: PlanningRemarks
    regulatory_and_infrastructure: RegulatoryInfrastructure
    spatial_cluster: SpatialCluster
    export_files: ArtifactManifest
    metadata: RunMetadata

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plot_identity": self.plot_identity.to_dict(),
            "planning_remarks": self.planning_remarks.to_dict(),
            "regulatory_and_infrastructure": self.regulatory_and_infrastructure.to_dict(),
            "spatial_cluster": self.spatial_cluster.to_dict(),
            "export_files": self.export_files.to_dict(),
            "metadata": self.metadata.to_dict(),
        }
