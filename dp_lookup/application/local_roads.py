"""Deterministic road/access evidence from an active planning snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from shapely.geometry import LineString, MultiLineString

from dp_lookup.application.contracts import ParcelContext, RoadContext
from dp_lookup.core.constants import GENERIC_ROAD_NAMES
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.topology import arcgis_rings_to_geometry

ROAD_LAYER_IDS: Tuple[int, ...] = (193, 194, 44, 45, 2224)


def _text(attributes: Mapping[str, Any], names: Sequence[str]) -> Optional[str]:
    for name in names:
        value = attributes.get(name)
        if value is None:
            continue
        result = str(value).strip()
        if result and result.casefold() not in {"none", "null", "nan"}:
            return result
    return None


def _road_identity(attributes: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    name = _text(
        attributes,
        (
            "ROAD_NAME",
            "ROADNAME",
            "Roadname",
            "NAME",
            "Name",
            "REFERENCE",
            "TYPE_",
            "TYPE",
            "Type",
            "ROAD_TYPE",
        ),
    )
    width = _text(attributes, ("WIDTH_RL", "ROAD_WIDTH", "WIDTH", "Width"))
    return name, width


def _source_geometry(geometry: Any) -> Any:
    if not isinstance(geometry, Mapping):
        return None
    paths = geometry.get("paths")
    if isinstance(paths, list) and paths:
        valid = [path for path in paths if isinstance(path, list) and len(path) >= 2]
        if not valid:
            return None
        try:
            lines = [LineString(path) for path in valid]
            return lines[0] if len(lines) == 1 else MultiLineString(lines)
        except (TypeError, ValueError):
            return None
    rings = geometry.get("rings")
    if isinstance(rings, list) and rings:
        try:
            return arcgis_rings_to_geometry(rings)
        except (IndexError, TypeError, ValueError):
            return None
    return None


def _wgs_parts(geometry: Any) -> List[List[List[float]]]:
    if not isinstance(geometry, Mapping):
        return []
    raw_parts = geometry.get("paths") or geometry.get("rings") or []
    result: List[List[List[float]]] = []
    if not isinstance(raw_parts, list):
        return result
    for part in raw_parts:
        if not isinstance(part, list) or len(part) < 2:
            continue
        try:
            result.append([mercator_to_wgs84(point[0], point[1]) for point in part])
        except (IndexError, TypeError, ValueError):
            continue
    return result


@dataclass(frozen=True)
class _Candidate:
    layer_id: int
    object_id: int
    distance_m: float
    name: Optional[str]
    width: Optional[str]
    geometries: List[List[List[float]]]

    @property
    def quality(self) -> int:
        return int(bool(self.name)) + int(bool(self.width))


class LocalRoadProvider:
    """Find the closest mapped road without an ArcGIS identify request.

    A result is returned only for parcels sourced from a local snapshot.  A
    caller can therefore use ``None`` as the explicit signal to retain its
    established live fallback for live parcels or unavailable local data.
    """

    def __init__(
        self,
        store: Optional[Any],
        *,
        search_distance_m: float = 30.0,
        snapshot_id: Optional[int] = None,
    ) -> None:
        if search_distance_m <= 0:
            raise ValueError("search_distance_m must be positive")
        self.store = store
        self.search_distance_m = float(search_distance_m)
        self.snapshot_id = snapshot_id

    def __call__(self, parcel: ParcelContext) -> Optional[RoadContext]:
        if parcel.attrs.get("_DP_PARCEL_SOURCE") != "local_snapshot":
            return None
        if self.store is None:
            raise RuntimeError("no local planning snapshot store is configured")
        snapshot = (
            self.store.snapshot(self.snapshot_id) if self.snapshot_id is not None else self.store.pin_active_snapshot()
        )
        if snapshot is None or not bool(getattr(snapshot, "complete", False)):
            raise RuntimeError("no complete active planning snapshot is available")
        snapshot_id = int(snapshot.snapshot_id)
        subject = arcgis_rings_to_geometry(parcel.rings)
        if subject.is_empty:
            raise ValueError("subject parcel geometry is empty")
        min_x, min_y, max_x, max_y = subject.bounds
        pad = self.search_distance_m
        candidates: List[_Candidate] = []
        feature_reader = getattr(self.store, "compact_features_in_bbox", self.store.features_in_bbox)
        for layer_id in ROAD_LAYER_IDS:
            rows = feature_reader(
                layer_id,
                min_x - pad,
                max_x + pad,
                min_y - pad,
                max_y + pad,
                snapshot_id=snapshot_id,
            )
            for row in rows:
                source = _source_geometry(row.get("geometry"))
                if source is None or source.is_empty:
                    continue
                distance = float(subject.distance(source))
                if distance > pad:
                    continue
                attributes = row.get("attributes")
                if not isinstance(attributes, Mapping):
                    attributes = {}
                name, width = _road_identity(attributes)
                candidates.append(
                    _Candidate(
                        layer_id=layer_id,
                        object_id=int(row.get("object_id", 0)),
                        distance_m=distance,
                        name=name,
                        width=width,
                        geometries=_wgs_parts(row.get("geometry")),
                    )
                )
        if not candidates:
            return RoadContext(
                name="None",
                width="N/A",
                warnings=[],
                evidence_state="not_present",
                method="local_snapshot_distance",
                snapshot_id=snapshot_id,
            )

        candidates.sort(key=lambda item: (round(item.distance_m, 6), -item.quality, item.layer_id, item.object_id))
        selected = candidates[0]
        nearby = [item for item in candidates if item.distance_m <= selected.distance_m + 1.0]
        geometries = [part for item in nearby for part in item.geometries]
        selected_name = selected.name or "Unnamed / existing road"
        if selected_name.strip().casefold() in GENERIC_ROAD_NAMES:
            selected_name = "Unnamed / existing road"
        return RoadContext(
            name=selected_name,
            width=selected.width or "N/A",
            geometries=geometries,
            warnings=[],
            evidence_state="confirmed" if selected.name or selected.width else "unknown",
            method="local_snapshot_distance",
            source_layer_ids=sorted({item.layer_id for item in nearby}),
            source_object_ids=sorted({item.object_id for item in nearby}),
            distance_m=round(selected.distance_m, 3),
            snapshot_id=snapshot_id,
        )


__all__ = ["ROAD_LAYER_IDS", "LocalRoadProvider"]
