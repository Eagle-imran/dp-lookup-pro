"""Deterministic, local spatial operations on cadastral parcel records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

from shapely.geometry.base import BaseGeometry  # type: ignore[import-untyped]
from shapely.ops import unary_union  # type: ignore[import-untyped]

from dp_lookup.core.topology import arcgis_rings_to_geometry

Ring = Tuple[Tuple[float, float], ...]
Rings = Tuple[Ring, ...]


def _freeze_rings(rings: Sequence[Sequence[Sequence[float]]]) -> Rings:
    return tuple(tuple((float(point[0]), float(point[1])) for point in ring) for ring in rings)


@dataclass(frozen=True)
class ParcelGeometryRecord:
    objectid: int
    village: str
    cts_no: str
    area_sqm: Optional[float]
    rings: Rings
    ward: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rings", _freeze_rings(self.rings))
        if self.area_sqm is not None:
            object.__setattr__(self, "area_sqm", float(self.area_sqm))

    @property
    def geometry(self) -> BaseGeometry:
        return arcgis_rings_to_geometry(self.rings)


@dataclass(frozen=True)
class AdjacencyResult:
    subject_objectid: int
    candidate_objectid: int
    shared_boundary_m: float
    gap_m: float
    relation: str

    @property
    def exact_touch(self) -> bool:
        return self.relation == "touch"

    @property
    def tolerance_gap(self) -> bool:
        return self.relation == "tolerance-gap"


@dataclass(frozen=True)
class AmalgamatedGeometry:
    geometry: BaseGeometry
    area_sqm: float
    member_objectids: Tuple[int, ...]


@dataclass(frozen=True)
class SearchCriteria:
    village: Optional[str] = None
    ward: Optional[str] = None
    min_area_sqm: Optional[float] = None
    max_area_sqm: Optional[float] = None


def find_adjacent(subject: ParcelGeometryRecord, candidates: Iterable[ParcelGeometryRecord], tolerance_m: float = 0.5) -> Tuple[AdjacencyResult, ...]:
    """Return edge-touching or near-gap parcels, deterministically ordered."""
    if tolerance_m < 0:
        raise ValueError("tolerance_m must be non-negative")
    subject_geometry = subject.geometry
    if subject_geometry.is_empty or not subject_geometry.is_valid:
        raise ValueError("subject geometry is empty or invalid")
    results = []
    for candidate in candidates:
        if candidate.objectid == subject.objectid:
            continue
        geometry = candidate.geometry
        if geometry.is_empty or not geometry.is_valid:
            continue
        if subject_geometry.intersection(geometry).area > 1e-6:
            continue
        shared = subject_geometry.boundary.intersection(geometry.boundary).length
        gap = subject_geometry.distance(geometry)
        if shared > 0:
            relation = "touch"
        elif 0.0 < gap <= tolerance_m:
            relation = "tolerance-gap"
        else:
            continue
        results.append(AdjacencyResult(subject.objectid, candidate.objectid, float(shared), float(gap), relation))
    return tuple(sorted(results, key=lambda result: result.candidate_objectid))


def amalgamate(records: Iterable[ParcelGeometryRecord]) -> AmalgamatedGeometry:
    """Union parcel geometries and report the non-overlapping combined area."""
    members = tuple(records)
    if not members:
        raise ValueError("at least one parcel is required")
    geometries = [record.geometry for record in members]
    if any(geometry.is_empty or not geometry.is_valid for geometry in geometries):
        raise ValueError("all parcel geometries must be non-empty and valid")
    geometry = unary_union(geometries)
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("amalgamated geometry is empty or invalid")
    return AmalgamatedGeometry(geometry, float(geometry.area), tuple(sorted(record.objectid for record in members)))


def filter_parcels(records: Iterable[ParcelGeometryRecord], criteria: SearchCriteria, *, wards: Optional[dict[int, str]] = None) -> Tuple[ParcelGeometryRecord, ...]:
    """Filter official parcel area and identity fields, with stable objectid order.

    ``wards`` is optional because the compact parcel record intentionally stores
    only the requested identity fields; callers with ward metadata can provide
    an objectid-to-ward mapping.
    """
    if criteria.min_area_sqm is not None and criteria.max_area_sqm is not None and criteria.min_area_sqm > criteria.max_area_sqm:
        raise ValueError("minimum area cannot exceed maximum area")
    village = criteria.village.casefold() if criteria.village is not None else None
    ward = criteria.ward.casefold() if criteria.ward is not None else None
    selected = []
    for record in records:
        if village is not None and record.village.casefold() != village:
            continue
        record_ward = wards.get(record.objectid) if wards is not None else record.ward
        if ward is not None and (record_ward is None or record_ward.casefold() != ward):
            continue
        if criteria.min_area_sqm is not None and (record.area_sqm is None or record.area_sqm < criteria.min_area_sqm):
            continue
        if criteria.max_area_sqm is not None and (record.area_sqm is None or record.area_sqm > criteria.max_area_sqm):
            continue
        selected.append(record)
    return tuple(sorted(selected, key=lambda record: record.objectid))


__all__ = ["AdjacencyResult", "AmalgamatedGeometry", "ParcelGeometryRecord", "SearchCriteria", "amalgamate", "filter_parcels", "find_adjacent"]
