"""Plan a parcel update that downloads only the plots MCGM added or edited since the active snapshot."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dp_lookup.application.snapshot_ingestion import (
    IngestionClient,
    SnapshotIngestionConfig,
    _get_json,
    _sorted_ids,
)
from dp_lookup.clients.parcel_snapshot import LAYER13_URL, SnapshotIngestionError
from dp_lookup.spatial_store import SnapshotStore

EDIT_FIELD = "LAST_EDITED_DATE"
EDIT_MARGIN_SECONDS = 2 * 86_400
VERIFICATION_LIMIT = (
    "Unchanged parcels are copied from the base snapshot. A parcel MCGM changed without updating "
    f"{EDIT_FIELD} would be missed; a full build re-downloads everything."
)


@dataclass(frozen=True)
class ChangedOnlyPlan:
    """Which parcels to copy from the active snapshot and which to download again."""

    base_snapshot_id: int
    base_ids: frozenset[int]
    edited_since: str
    edited_ids: frozenset[int]

    def contract(self) -> dict[str, Any]:
        return {
            "refresh_mode": "changed_only",
            "base_snapshot_id": self.base_snapshot_id,
            "edited_since": self.edited_since,
            "edited_ids": sorted(self.edited_ids),
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "refresh_mode": "changed_only",
            "base_snapshot_id": self.base_snapshot_id,
            "edited_since": self.edited_since,
            "edited_candidate_count": len(self.edited_ids),
            "verification_limit": VERIFICATION_LIMIT,
        }

    def copy_ids(self, inventory: Iterable[int]) -> set[int]:
        return (set(inventory) & self.base_ids) - self.edited_ids


async def edited_ids(
    client: IngestionClient,
    edited_since: str,
    config: SnapshotIngestionConfig,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> frozenset[int]:
    """Ask MCGM which parcels carry an edit date at or after ``edited_since`` (UTC)."""
    params = {
        "where": f"{EDIT_FIELD} >= timestamp '{edited_since}'",
        "returnIdsOnly": "true",
        "returnGeometry": "false",
        "f": "json",
    }
    payload = await _get_json(client, f"{LAYER13_URL}/query", params, config, sleep)
    raw_ids = payload.get("objectIds")
    if raw_ids is None:
        return frozenset()
    if not isinstance(raw_ids, list):
        raise SnapshotIngestionError("Layer 13 edited-parcel query did not return an objectIds list.")
    return frozenset(_sorted_ids(raw_ids))


async def plan_changed_only(
    client: IngestionClient, database: Path, config: SnapshotIngestionConfig
) -> ChangedOnlyPlan:
    if not database.is_file():
        raise SnapshotIngestionError("a parcel update needs an existing database; run a full build first")
    with SnapshotStore.open(database) as store:
        base_snapshot_id = store.active_snapshot_id()
        if base_snapshot_id is None:
            raise SnapshotIngestionError("no active parcel snapshot to update; run a full build first")
        latest_edit = store.max_attribute(base_snapshot_id, EDIT_FIELD)
        if latest_edit is None:
            raise SnapshotIngestionError(f"the active parcel snapshot has no {EDIT_FIELD} values; run a full build")
        base_ids = frozenset(store.object_ids(base_snapshot_id))
    cutoff = datetime.fromtimestamp(float(latest_edit) / 1000 - EDIT_MARGIN_SECONDS, UTC)
    edited_since = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    return ChangedOnlyPlan(
        base_snapshot_id=base_snapshot_id,
        base_ids=base_ids,
        edited_since=edited_since,
        edited_ids=await edited_ids(client, edited_since, config),
    )


__all__ = ["EDIT_FIELD", "ChangedOnlyPlan", "edited_ids", "plan_changed_only"]
