"""Typed public contracts for derived plot intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

ALGORITHM_VERSION = "plot-intelligence/1.1.0"


@dataclass(frozen=True)
class IntelligenceBuild:
    build_id: int
    state: str
    scope: str
    parcel_snapshot_id: int
    planning_snapshot_id: int
    algorithm_version: str
    expected_count: int
    record_count: int
    created_at: str
    finalized_at: Optional[str] = None
    source_fingerprint: str = ""
    validation: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id,
            "state": self.state,
            "scope": self.scope,
            "parcel_snapshot_id": self.parcel_snapshot_id,
            "planning_snapshot_id": self.planning_snapshot_id,
            "algorithm_version": self.algorithm_version,
            "expected_count": self.expected_count,
            "record_count": self.record_count,
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
            "source_fingerprint": self.source_fingerprint,
            "validation": dict(self.validation),
        }


@dataclass(frozen=True)
class PlotIntelligence:
    village: str
    cts_no: str
    ward: Optional[str]
    source_objectids: Tuple[int, ...]
    feature_part_count: int
    area_sqm: float
    area_source: str
    geometry_area_sqm: float
    centroid_x: float
    centroid_y: float
    primary_zone: str
    zones: Tuple[Mapping[str, Any], ...] = ()
    reservations: Tuple[Mapping[str, Any], ...] = ()
    designations: Tuple[Mapping[str, Any], ...] = ()
    modifications: Tuple[Mapping[str, Any], ...] = ()
    metro_buffer: str = "UNKNOWN"
    crz_status: str = "UNKNOWN"
    encumbered_area_sqm: float = 0.0
    encumbered_percent: float = 0.0
    net_unencumbered_sqm: float = 0.0
    net_unencumbered_percent: float = 0.0
    road_name: str = "None"
    road_width: str = "N/A"
    road_distance_m: Optional[float] = None
    neighbour_count: int = 0
    neighbours: Tuple[Mapping[str, Any], ...] = ()
    evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()
    confidence: str = "verified"
    source_refs: Tuple[Mapping[str, Any], ...] = ()
    facts_hash: str = ""
    calculated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plot_identity": {
                "village": self.village,
                "cts_no": self.cts_no,
                "ward": self.ward,
                "source_objectids": list(self.source_objectids),
                "feature_part_count": self.feature_part_count,
                "area_sqm": self.area_sqm,
                "area_source": self.area_source,
                "geometry_area_sqm": self.geometry_area_sqm,
                "centroid": {"x": self.centroid_x, "y": self.centroid_y, "wkid": 102100},
            },
            "planning": {
                "primary_zone": self.primary_zone,
                "zones": list(self.zones),
                "reservations": list(self.reservations),
                "designations": list(self.designations),
                "modifications": list(self.modifications),
                "metro_buffer": self.metro_buffer,
                "crz_status": self.crz_status,
                "encumbered_area_sqm": self.encumbered_area_sqm,
                "encumbered_percent": self.encumbered_percent,
                "net_unencumbered_sqm": self.net_unencumbered_sqm,
                "net_unencumbered_percent": self.net_unencumbered_percent,
            },
            "access": {
                "road_name": self.road_name,
                "road_width": self.road_width,
                "distance_m": self.road_distance_m,
            },
            "adjacency": {"neighbour_count": self.neighbour_count, "neighbours": list(self.neighbours)},
            "evidence_summary": dict(self.evidence_summary),
            "quality": {
                "confidence": self.confidence,
                "warnings": list(self.warnings),
                "facts_hash": self.facts_hash,
                "calculated_at": self.calculated_at,
            },
            "source_refs": list(self.source_refs),
        }
