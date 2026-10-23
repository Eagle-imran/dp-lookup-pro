"""Exact local adjacency backed by a complete active parcel snapshot."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from dp_lookup.application.contracts import NeighbourContext, ParcelContext
from dp_lookup.core.area_assessment import calculated_boundary_area_sqm
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.spatial_store import SnapshotStore


class LocalNeighbourProvider:
    def __init__(
        self,
        database: Path,
        *,
        tolerance_m: float = 0.5,
        min_shared_boundary_m: float = 0.05,
        store: Optional[SnapshotStore] = None,
    ) -> None:
        if tolerance_m < 0 or min_shared_boundary_m < 0:
            raise ValueError("adjacency tolerances must be non-negative")
        self.database = Path(database)
        self.tolerance_m = tolerance_m
        self.min_shared_boundary_m = min_shared_boundary_m
        self.store = store

    def __call__(self, parcel: ParcelContext) -> Optional[NeighbourContext]:
        # In ``auto`` mode the parcel adapter can legitimately fall back to
        # live ArcGIS. Returning ``None`` here preserves the established live
        # neighbour probes instead of falsely reporting an empty local result.
        if parcel.attrs.get("_DP_PARCEL_SOURCE") != "local_snapshot":
            return None
        subject = arcgis_rings_to_geometry(parcel.rings)
        if subject.is_empty:
            raise ValueError("subject parcel geometry is empty")
        min_x, min_y, max_x, max_y = subject.bounds
        snapshot_id_value = parcel.attrs.get("_DP_SNAPSHOT_ID")
        if snapshot_id_value is None or isinstance(snapshot_id_value, bool):
            raise ValueError("local parcel snapshot ID is invalid")
        try:
            snapshot_id = int(snapshot_id_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("local parcel snapshot ID is missing") from exc
        if self.store is None:
            with SnapshotStore.open(self.database) as store:
                rows = store.parcels_in_bbox(
                    min_x - self.tolerance_m,
                    max_x + self.tolerance_m,
                    min_y - self.tolerance_m,
                    max_y + self.tolerance_m,
                    snapshot_id=snapshot_id,
                )
        else:
            rows = self.store.parcels_in_bbox(
                min_x - self.tolerance_m,
                max_x + self.tolerance_m,
                min_y - self.tolerance_m,
                max_y + self.tolerance_m,
                snapshot_id=snapshot_id,
            )

        grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            village = str(row.get("village") or "")
            cts_no = str(row.get("cts_no") or "")
            if not cts_no or (village == parcel.village and cts_no == parcel.cts_no):
                continue
            grouped[(village, cts_no)].append(row)

        neighbours: List[Dict[str, Any]] = []
        for (village, cts_no), parts in grouped.items():
            rings: List[Any] = []
            for part in parts:
                part_rings = part.get("rings")
                if isinstance(part_rings, list):
                    rings.extend(part_rings)
            geometry = arcgis_rings_to_geometry(rings)
            if geometry.is_empty:
                continue
            if subject.intersection(geometry).area > 1e-6:
                continue
            shared = float(subject.boundary.intersection(geometry.boundary).length)
            gap = float(subject.distance(geometry))
            if shared >= self.min_shared_boundary_m:
                relation = "shared_boundary"
            elif 0.0 < gap <= self.tolerance_m:
                relation = "tolerance_gap"
            else:
                # Point-only contact and overlapping source errors are not
                # silently promoted to an adjoining cadastral boundary.
                continue
            recorded = {
                float(part["area_app_sqm"])
                for part in parts
                if part.get("area_app_sqm") is not None and float(part["area_app_sqm"]) > 0
            }
            if len(recorded) == 1:
                area: Any = next(iter(recorded))
                area_source = "Recorded plot area"
            else:
                calculated = calculated_boundary_area_sqm(rings)
                area = round(calculated, 2) if calculated is not None else "N/A"
                area_source = "Calculated boundary area" if calculated is not None else "Unavailable"
            neighbours.append(
                {
                    "cts_no": cts_no,
                    "village": village,
                    "area_sqm": str(area),
                    "area_source": area_source,
                    "rings": [[mercator_to_wgs84(point[0], point[1]) for point in ring] for ring in rings],
                    "source_objectids": sorted(int(part["objectid"]) for part in parts),
                    "adjacency_relation": relation,
                    "shared_boundary_m": round(shared, 3),
                    "gap_m": round(gap, 3),
                }
            )
        neighbours.sort(key=lambda item: (item["village"], item["cts_no"]))
        return NeighbourContext(
            plots=neighbours,
            warnings=[],
            evidence_state="confirmed",
            method="spatial_database",
        )


def parcel_source_notes(parcel: ParcelContext) -> List[str]:
    """Explain local selection, fallback, staleness, and multipart semantics."""
    notes: List[str] = []
    fallback_reason = parcel.attrs.get("_DP_LOCAL_FALLBACK_REASON")
    if fallback_reason:
        notes.append(f"Local parcel database was unavailable; live Layer 13 was used ({fallback_reason}).")
    if parcel.attrs.get("_DP_SNAPSHOT_STALE"):
        notes.append(
            f"Local parcel snapshot is {parcel.attrs.get('_DP_SNAPSHOT_AGE_DAYS')} days old; "
            "use --source live for current Layer 13 verification."
        )
    feature_part_count = parcel.attrs.get("FEATURE_PART_COUNT")
    if isinstance(feature_part_count, int) and feature_part_count > 1:
        notes.append(
            f"This village/CTS identity contains {feature_part_count} Layer 13 source features; "
            "the parcel boundary and planning checks use their combined geometry."
        )
    area_conflicts = parcel.attrs.get("_DP_AREA_CONFLICT_VALUES")
    if isinstance(area_conflicts, list) and area_conflicts:
        notes.append(
            "The source parts contain conflicting recorded-area values; "
            "the reported area is derived from the combined boundary."
        )
    return notes


__all__ = ["LocalNeighbourProvider", "parcel_source_notes"]
