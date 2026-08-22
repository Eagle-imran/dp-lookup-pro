"""Local SQLite parcel adapter with an explicit live-fallback boundary."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

from shapely.geometry.base import BaseGeometry

from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.spatial_store import SnapshotStore, SpatialStoreError

LiveParcelFetcher = Callable[[Any, str, str], Awaitable[Optional[Dict[str, Any]]]]
DEFAULT_MAX_SNAPSHOT_AGE_DAYS = 210.0


class LocalParcelError(RuntimeError):
    """A requested local snapshot could not provide trustworthy parcel data."""


def _rings(row: Mapping[str, Any]) -> List[Any]:
    geometry = row.get("geometry")
    if isinstance(geometry, Mapping):
        rings = geometry.get("rings")
    else:
        rings = row.get("rings")
    if not isinstance(rings, list) or not rings:
        raise LocalParcelError(f"local parcel ObjectID {row.get('objectid')} has no polygon rings")
    return rings


def merge_local_features(rows: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return one pipeline feature while preserving every same-identity part.

    Layer 13 contains thousands of village/CTS identities represented by more
    than one source feature. The historical ArcGIS query selected the first;
    the local adapter deliberately combines every returned polygon ring.
    """
    if not rows:
        return None
    ordered = sorted(rows, key=lambda row: int(row["objectid"]))
    combined_rings: List[Any] = []
    unique_geometries: List[BaseGeometry] = []
    duplicate_geometry_count = 0
    for row in ordered:
        row_rings = _rings(row)
        row_geometry = arcgis_rings_to_geometry(row_rings)
        if any(row_geometry.equals(existing) for existing in unique_geometries):
            duplicate_geometry_count += 1
            continue
        unique_geometries.append(row_geometry)
        combined_rings.extend(row_rings)
    geometry = arcgis_rings_to_geometry(combined_rings)
    if geometry.is_empty:
        raise LocalParcelError("local parcel parts produced an empty combined geometry")

    attrs = dict(ordered[0].get("raw_attrs") or {})
    objectids = [int(row["objectid"]) for row in ordered]
    recorded_values = {
        float(row["area_app_sqm"])
        for row in ordered
        if row.get("area_app_sqm") is not None and float(row["area_app_sqm"]) > 0
    }
    # A single repeated recorded value can safely remain the stated value. When
    # parts disagree, fall back to the combined boundary and surface that it
    # is derived rather than inventing a sum of possibly repeated totals.
    attrs["AREA_APP_SQ_MTRS"] = next(iter(recorded_values)) if len(recorded_values) == 1 else None
    attrs["SHAPE.AREA"] = float(geometry.area)
    attrs["OBJECTID"] = objectids[0]
    attrs["SOURCE_OBJECTIDS"] = objectids
    attrs["FEATURE_PART_COUNT"] = len(objectids)
    attrs["_DP_PARCEL_SOURCE"] = "local_snapshot"
    if len(recorded_values) > 1:
        attrs["_DP_AREA_CONFLICT_VALUES"] = sorted(recorded_values)
    if recorded_values and any(row.get("area_app_sqm") is None for row in ordered):
        attrs["_DP_RECORDED_AREA_MISSING_PARTS"] = True
    if duplicate_geometry_count:
        attrs["_DP_DUPLICATE_GEOMETRY_COUNT"] = duplicate_geometry_count

    spatial_reference: Mapping[str, Any] = {"wkid": 102100}
    first_geometry = ordered[0].get("geometry")
    if isinstance(first_geometry, Mapping) and isinstance(first_geometry.get("spatialReference"), Mapping):
        spatial_reference = first_geometry["spatialReference"]
    return {
        "attributes": attrs,
        "geometry": {"rings": combined_rings, "spatialReference": dict(spatial_reference)},
    }


class LocalParcelFetcher:
    """Lookup an active snapshot, optionally falling back to live ArcGIS."""

    def __init__(
        self,
        database: Path,
        *,
        fallback: Optional[LiveParcelFetcher] = None,
        max_snapshot_age_days: float = DEFAULT_MAX_SNAPSHOT_AGE_DAYS,
        snapshot_id: Optional[int] = None,
    ) -> None:
        if max_snapshot_age_days <= 0:
            raise ValueError("max_snapshot_age_days must be positive")
        self.database = Path(database)
        self.fallback = fallback
        self.max_snapshot_age_days = max_snapshot_age_days
        self.snapshot_id = snapshot_id

    async def _fallback_feature(self, client: Any, village: str, cts_no: str, reason: str) -> Optional[Dict[str, Any]]:
        if self.fallback is None:
            return None
        feature = await self.fallback(client, village, cts_no)
        if feature is not None and isinstance(feature.get("attributes"), Mapping):
            copied = dict(feature)
            copied["attributes"] = dict(feature["attributes"])
            copied["attributes"]["_DP_LOCAL_FALLBACK_REASON"] = reason
            return copied
        return feature

    async def __call__(self, client: Any, village: str, cts_no: str) -> Optional[Dict[str, Any]]:
        try:
            if not self.database.is_file():
                raise LocalParcelError(f"local parcel database does not exist: {self.database}")
            with SnapshotStore.open(self.database) as store:
                active_snapshot_id = store.active_snapshot_id()
                if active_snapshot_id is None:
                    raise LocalParcelError("local parcel database has no active snapshot")
                selected_snapshot_id = self.snapshot_id if self.snapshot_id is not None else active_snapshot_id
                feature = merge_local_features(store.lookup(village, cts_no, snapshot_id=selected_snapshot_id))
                snapshot = store.snapshot(selected_snapshot_id)
                if snapshot.finalized_at is None:
                    raise LocalParcelError("active local parcel snapshot has no finalized timestamp")
                snapshot_age_days = max(0.0, (time.time() - float(snapshot.finalized_at)) / 86_400.0)
        except (OSError, sqlite3.DatabaseError, SpatialStoreError, LocalParcelError) as exc:
            if self.fallback is None:
                if isinstance(exc, LocalParcelError):
                    raise
                raise LocalParcelError(str(exc)) from exc
            return await self._fallback_feature(client, village, cts_no, str(exc))
        if feature is not None:
            feature["attributes"]["_DP_SNAPSHOT_ID"] = snapshot.snapshot_id
            feature["attributes"]["_DP_SNAPSHOT_FINALIZED_AT"] = snapshot.finalized_at
            feature["attributes"]["_DP_SNAPSHOT_FINALIZED_AT_ISO"] = datetime.fromtimestamp(
                float(snapshot.finalized_at), timezone.utc
            ).isoformat()
            feature["attributes"]["_DP_SNAPSHOT_AGE_DAYS"] = round(snapshot_age_days, 3)
            if snapshot_age_days > self.max_snapshot_age_days:
                feature["attributes"]["_DP_SNAPSHOT_STALE"] = True
            return feature
        if self.fallback is not None:
            return await self._fallback_feature(
                client,
                village,
                cts_no,
                f"village/CTS identity was absent from local snapshot {snapshot.snapshot_id}",
            )
        return None


__all__ = [
    "DEFAULT_MAX_SNAPSHOT_AGE_DAYS",
    "LocalParcelError",
    "LocalParcelFetcher",
    "merge_local_features",
]
