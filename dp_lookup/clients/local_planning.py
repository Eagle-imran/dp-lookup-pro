"""Local-first planning-layer adapter with an explicit live escape hatch.

The parcel snapshot store is intentionally not coupled to this adapter. A
planning repository can be SQLite, a service, or a test fake as long as it
can pin the active snapshot once and spatially query each layer against the
parcel geometry. The deterministic result policy remains in
``planning_queries`` so local and ArcGIS records have identical semantics.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Union, cast

from dp_lookup.clients.planning_queries import (
    build_spatial_planning_result,
    query_spatial_planning_layers,
)
from dp_lookup.core.constants import (
    CRZ_LAYER_IDS,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
)
from dp_lookup.core.topology import arcgis_rings_to_geometry

SnapshotId = Union[int, str]
PLANNING_LAYER_IDS = (
    LAYER_ZONE,
    LAYER_RESERVATION,
    LAYER_DESIGNATION,
    LAYER_MODIFICATION,
    LAYER_METRO,
    *CRZ_LAYER_IDS,
)
DEFAULT_MAX_PLANNING_SNAPSHOT_AGE_DAYS = 210.0


@dataclass(frozen=True)
class PlanningSnapshot:
    """Pinned planning snapshot metadata returned by a repository."""

    snapshot_id: SnapshotId
    finalized_at: Optional[Any] = None
    source: Optional[str] = None


class PlanningSnapshotStore(Protocol):
    """Storage seam required by :class:`LocalFirstPlanningQuery`.

    ``pin_active_snapshot`` must return one immutable snapshot identity for the
    whole lookup. ``query_layer`` must apply a spatial intersection/filter in
    the store using the supplied parcel geometry; identity fields such as
    village or CTS are deliberately not part of this contract.
    """

    def pin_active_snapshot(self) -> Optional[PlanningSnapshot]:
        """Return the active snapshot's metadata, or ``None`` when unavailable."""

    def query_layer(
        self,
        snapshot_id: SnapshotId,
        layer_id: int,
        parcel_geometry: Any,
    ) -> Sequence[Mapping[str, Any]]:
        """Return records spatially intersecting ``parcel_geometry``."""


class LocalPlanningError(RuntimeError):
    """The local planning repository cannot provide a trustworthy result."""


def _snapshot_value(snapshot: Any, name: str, default: Any = None) -> Any:
    if isinstance(snapshot, Mapping):
        return snapshot.get(name, default)
    return getattr(snapshot, name, default)


def _age_days(finalized_at: Any) -> Optional[float]:
    """Return snapshot age in days for common repository timestamp forms."""
    if finalized_at is None:
        return None
    if isinstance(finalized_at, datetime):
        timestamp = finalized_at.timestamp()
    elif isinstance(finalized_at, (int, float)) and not isinstance(finalized_at, bool):
        timestamp = float(finalized_at)
    else:
        text = str(finalized_at).strip()
        try:
            timestamp = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                timestamp = float(text)
            except ValueError:
                return None
    if not math.isfinite(timestamp):
        return None
    return round(max(0.0, (time.time() - timestamp) / 86_400.0), 3)


def _with_provenance(result: Dict[str, Any], provenance: Dict[str, Any], *extra_warnings: str) -> Dict[str, Any]:
    """Attach additive provenance without changing legacy planning fields."""
    result = dict(result)
    if extra_warnings:
        provenance = dict(provenance)
        provenance["warnings"] = list(extra_warnings)
    result["provenance"] = provenance
    return result


class LocalFirstPlanningQuery:
    """Query a pinned local planning snapshot, with optional live fallback.

    ``mode='live'`` calls the existing ArcGIS adapter without touching the
    repository. ``mode='local'`` is strict and raises ``LocalPlanningError``
    when local data is unavailable or stale. ``mode='auto'`` falls back to
    ArcGIS and annotates the returned result with the reason.
    """

    def __init__(
        self,
        store: Optional[PlanningSnapshotStore],
        *,
        live_query: Any = query_spatial_planning_layers,
        mode: str = "auto",
        max_snapshot_age_days: Optional[float] = DEFAULT_MAX_PLANNING_SNAPSHOT_AGE_DAYS,
        allow_stale_local: bool = False,
    ) -> None:
        selected_mode = str(mode).strip().lower()
        if selected_mode not in {"auto", "local", "live"}:
            raise ValueError("planning source mode must be auto, local, or live")
        if max_snapshot_age_days is not None and max_snapshot_age_days <= 0:
            raise ValueError("max_snapshot_age_days must be positive or None")
        self.store = store
        self.live_query = live_query
        self.mode = selected_mode
        self.max_snapshot_age_days = max_snapshot_age_days
        self.allow_stale_local = allow_stale_local

    def _pin(self) -> Any:
        if self.store is None:
            raise LocalPlanningError("no local planning snapshot store is configured")
        try:
            # ``active_snapshot`` is accepted as a migration convenience for
            # repositories that predate this explicit pinning contract.
            pin = getattr(self.store, "pin_active_snapshot", None)
            if pin is None:
                pin = getattr(self.store, "active_snapshot", None)
            snapshot = pin() if callable(pin) else None
        except Exception as exc:
            raise LocalPlanningError(f"active planning snapshot could not be pinned: {exc}") from exc
        if snapshot is None:
            raise LocalPlanningError("no active planning snapshot is available")
        snapshot_id = _snapshot_value(snapshot, "snapshot_id")
        if snapshot_id is None or isinstance(snapshot_id, bool) or str(snapshot_id).strip() == "":
            raise LocalPlanningError("active planning snapshot has no valid snapshot ID")
        return snapshot

    def _local_result(self, rings: List[Any]) -> Dict[str, Any]:
        snapshot = self._pin()
        snapshot_id = _snapshot_value(snapshot, "snapshot_id")
        finalized_at = _snapshot_value(snapshot, "finalized_at")
        if finalized_at is None:
            raise LocalPlanningError(f"planning snapshot {snapshot_id} has no finalized timestamp")
        age_days = _age_days(finalized_at)
        if age_days is None:
            raise LocalPlanningError(f"planning snapshot {snapshot_id} has an invalid finalized timestamp")
        stale = (
            age_days is not None
            and self.max_snapshot_age_days is not None
            and age_days > self.max_snapshot_age_days
        )
        if stale and not self.allow_stale_local:
            raise LocalPlanningError(
                f"planning snapshot {snapshot_id} is stale ({age_days} days old; "
                f"limit {self.max_snapshot_age_days} days)"
            )

        parcel = arcgis_rings_to_geometry(rings)
        if parcel.is_empty or parcel.area <= 0:
            raise ValueError("Parcel geometry has no valid polygon rings")
        by_layer: Dict[int, List[Dict[str, Any]]] = {}
        try:
            for layer_id in PLANNING_LAYER_IDS:
                query = getattr(self.store, "query_layer", None)
                if query is None:
                    query = getattr(self.store, "records_intersecting", None)
                if not callable(query):
                    raise LocalPlanningError("planning snapshot store has no spatial layer query method")
                records = query(snapshot_id, layer_id, parcel)
                if records is None:
                    raise LocalPlanningError(f"planning snapshot {snapshot_id} returned no collection for layer {layer_id}")
                if not isinstance(records, (list, tuple)):
                    raise LocalPlanningError(f"planning snapshot layer {layer_id} returned a malformed collection")
                by_layer[layer_id] = [dict(record) for record in records if isinstance(record, Mapping)]
        except LocalPlanningError:
            raise
        except Exception as exc:
            raise LocalPlanningError(f"planning snapshot {snapshot_id} query failed: {exc}") from exc

        provenance = {
            "source": "local_snapshot",
            "method": "local_snapshot_spatial_query",
            "snapshot_id": snapshot_id,
            "snapshot_finalized_at": finalized_at,
            "snapshot_age_days": age_days,
            "snapshot_stale": stale,
            "fallback": False,
        }
        warning = (
            f"Local planning snapshot {snapshot_id} is stale ({age_days} days old); "
            "verify planning status against live ArcGIS."
            if stale
            else None
        )
        return cast(
            Dict[str, Any],
            build_spatial_planning_result(
                parcel,
                by_layer,
                [warning] if warning else [],
                provenance=provenance,
            ),
        )

    async def __call__(self, client: Any, rings: List[Any]) -> Dict[str, Any]:
        if self.mode == "live":
            return cast(Dict[str, Any], await self.live_query(client, rings))
        try:
            return self._local_result(rings)
        except Exception as exc:
            if self.mode == "local":
                if isinstance(exc, LocalPlanningError):
                    raise
                raise LocalPlanningError(str(exc)) from exc
            reason = str(exc)
            live_result = cast(Dict[str, Any], await self.live_query(client, rings))
            provenance = {
                "source": "live_arcgis",
                "method": "spatial_polygon",
                "fallback": True,
                "fallback_reason": reason,
            }
            return _with_provenance(
                live_result,
                provenance,
                f"Local planning snapshot was unavailable; live ArcGIS planning layers were used ({reason}).",
            )


__all__ = [
    "DEFAULT_MAX_PLANNING_SNAPSHOT_AGE_DAYS",
    "PLANNING_LAYER_IDS",
    "LocalFirstPlanningQuery",
    "LocalPlanningError",
    "PlanningSnapshot",
    "PlanningSnapshotStore",
]
