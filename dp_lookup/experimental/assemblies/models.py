"""Immutable contracts for deterministic experimental plot assembly.

These contracts describe *geometric screening only*.  They intentionally do
not express ownership, title, access rights, municipal approval, or legal
amalgamation.  Original ArcGIS coordinates are retained on every input and
are never changed by the analytical service.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Tuple

Coordinate = Tuple[float, float]
ArcGISRing = Tuple[Coordinate, ...]
ArcGISRings = Tuple[ArcGISRing, ...]


def _normalise_rings(raw_rings: Sequence[Sequence[Sequence[float]]]) -> ArcGISRings:
    """Make an immutable, numeric copy of raw source coordinates."""
    normalised = []
    for raw_ring in raw_rings:
        ring = []
        for point in raw_ring:
            if len(point) < 2:
                raise ValueError("Every raw ArcGIS coordinate must contain x and y values.")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("Raw ArcGIS coordinates must be finite numbers.")
            ring.append((x, y))
        if len(ring) < 4:
            raise ValueError("Every raw ArcGIS ring must contain at least four coordinates.")
        normalised.append(tuple(ring))
    if not normalised:
        raise ValueError("At least one raw ArcGIS ring is required.")
    return tuple(normalised)


@dataclass(frozen=True)
class ParcelAssemblyInput:
    """One selected CTS identity and its preserved parcel-source geometry.

    ``objectids`` may contain multiple source features for a multipart CTS
    identity. ``recorded_area_sqm`` is deliberately one value for that identity
    and is therefore counted at most once in an assembly's gross recorded area.
    """

    village: str
    cts_no: str
    objectids: Sequence[int]
    raw_arcgis_rings: Sequence[Sequence[Sequence[float]]]
    recorded_area_sqm: Optional[float]
    ward: Optional[str] = None
    source_label: str = "MCGM cadastral parcel record"

    def __post_init__(self) -> None:
        village = self.village.strip()
        cts_no = self.cts_no.strip()
        if not village or not cts_no:
            raise ValueError("Parcel assembly inputs require non-empty village and CTS identities.")
        objectids = tuple(sorted({int(value) for value in self.objectids}))
        if not objectids:
            raise ValueError("Parcel assembly inputs require at least one source ObjectID.")
        if any(value < 0 for value in objectids):
            raise ValueError("Source ObjectIDs must be non-negative integers.")
        recorded = self.recorded_area_sqm
        if recorded is not None:
            recorded = float(recorded)
            if not math.isfinite(recorded) or recorded <= 0:
                raise ValueError("Recorded parcel area must be a positive finite number when supplied.")
        object.__setattr__(self, "village", village)
        object.__setattr__(self, "cts_no", cts_no)
        object.__setattr__(self, "objectids", objectids)
        object.__setattr__(self, "raw_arcgis_rings", _normalise_rings(self.raw_arcgis_rings))
        object.__setattr__(self, "recorded_area_sqm", recorded)
        object.__setattr__(self, "ward", self.ward.strip() if self.ward else None)
        object.__setattr__(self, "source_label", self.source_label.strip() or "MCGM cadastral parcel record")

    @property
    def identity_key(self) -> str:
        """Stable human-readable identity used to keep a selection traceable."""
        return f"{self.village} / {self.cts_no}"


class ParcelRelationKind(str, Enum):
    """The deterministic geometric relationship between two selected parcels."""

    SHARED_BOUNDARY = "shared_boundary"
    TOLERANCE_GAP = "tolerance_gap"
    POINT_CONTACT = "point_contact"
    OVERLAP = "overlap"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class PairwiseParcelRelation:
    """Ground-metric relationship between two selected parcel identities."""

    first_identity: str
    second_identity: str
    relation: ParcelRelationKind
    shared_boundary_length_m: float
    gap_distance_m: float
    overlap_area_sqm: float
    within_gap_tolerance: bool


class AssemblySuitabilityStatus(str, Enum):
    """Screening status only; none of these values grants legal approval."""

    GEOMETRY_SCREENING_READY = "geometry_screening_ready"
    REVIEW_TOLERANCE_GAPS = "review_tolerance_gaps"
    REVIEW_OVERLAPS = "review_overlaps"
    REVIEW_SOURCE_GEOMETRY = "review_source_geometry"
    NOT_CONTIGUOUS = "not_contiguous"
    ANALYSIS_UNAVAILABLE = "analysis_unavailable"


@dataclass(frozen=True)
class AssemblyWarning:
    """A deterministic, action-oriented limitation or diagnostic."""

    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class AssemblyAnalysis:
    """The immutable result of a geometric plot-assembly screening calculation.

    ``combined_boundary_wkt`` is an analytical EPSG:32643 geometry.  It is not
    a replacement cadastral boundary and must not be submitted as a certified
    amalgamation plan.
    """

    selected_parcels: Tuple[ParcelAssemblyInput, ...]
    analysis_crs: str
    gap_tolerance_m: float
    gross_recorded_area_sqm: Optional[float]
    known_recorded_area_sqm: float
    recorded_area_complete: bool
    calculated_input_boundary_area_sqm: float
    calculated_combined_boundary_area_sqm: float
    external_perimeter_m: float
    removed_internal_boundary_length_m: float
    overlap_or_duplicate_area_sqm: float
    is_strictly_connected: bool
    is_connected_within_tolerance: bool
    pairwise_relations: Tuple[PairwiseParcelRelation, ...]
    suitability_status: AssemblySuitabilityStatus
    warnings: Tuple[AssemblyWarning, ...] = field(default_factory=tuple)
    combined_boundary_wkt: Optional[str] = None
