"""Exact local adjacency backed by a complete active parcel snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from dp_lookup.application.contracts import NeighbourContext, ParcelContext
from dp_lookup.application.neighbour_normalization import (
    ADJACENCY_TOLERANCE_M,
    MIN_SHARED_BOUNDARY_M,
    adjoining_parcels,
)
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.spatial_store import SnapshotStore


class LocalNeighbourProvider:
    def __init__(
        self,
        database: Path,
        *,
        tolerance_m: float = ADJACENCY_TOLERANCE_M,
        min_shared_boundary_m: float = MIN_SHARED_BOUNDARY_M,
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
        # boundary query instead of falsely reporting an empty local result.
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

        return NeighbourContext(
            plots=adjoining_parcels(
                parcel,
                subject,
                rows,
                tolerance_m=self.tolerance_m,
                min_shared_boundary_m=self.min_shared_boundary_m,
            ),
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
