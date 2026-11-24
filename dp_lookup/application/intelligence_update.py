"""Find the plots whose intelligence can change between two pairs of source snapshots.

A plot record depends on its own parcel features, on parcels within the adjacency
tolerance (its neighbour list) and on planning features that overlap it or lie within
the road search distance. Every other plot can be copied from the earlier build.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import batched

from dp_lookup.application.local_roads import ROAD_SEARCH_DISTANCE_M
from dp_lookup.application.neighbour_normalization import ADJACENCY_TOLERANCE_M
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore

Identity = tuple[str, str]
Box = tuple[float, float, float, float]

PARCEL_REACH_M = ADJACENCY_TOLERANCE_M + 1.0
PLANNING_REACH_M = ROAD_SEARCH_DISTANCE_M + 1.0


@dataclass(frozen=True)
class AffectedPlots:
    identities: frozenset[Identity]
    changed_parcel_objectids: tuple[int, ...]
    changed_planning_features: int


def _changed_parcels(store: SnapshotStore, old_id: int, new_id: int) -> tuple[set[Identity], list[Box], list[int]]:
    diff = store.diff_snapshots(old_id, new_id)
    objectids = sorted(set(diff["added"]) | set(diff["removed"]) | set(diff["changed"]))
    identities: set[Identity] = set()
    boxes: list[Box] = []
    for snapshot_id in (old_id, new_id):
        for chunk in batched(objectids, 500, strict=False):
            rows = store.connection.execute(
                "SELECT village,cts_no,min_x,max_x,min_y,max_y FROM parcels WHERE snapshot_id=? "
                f"AND objectid IN ({','.join('?' * len(chunk))})",
                (snapshot_id, *chunk),
            )
            for village, cts_no, min_x, max_x, min_y, max_y in rows:
                if village and cts_no:
                    identities.add((str(village), str(cts_no)))
                if min_x is not None:
                    boxes.append((min_x, max_x, min_y, max_y))
    return identities, boxes, objectids


def _changed_planning_boxes(store: PlanningSnapshotStore, old_id: int, new_id: int) -> list[Box]:
    boxes: list[Box] = []
    for newer, older in ((new_id, old_id), (old_id, new_id)):
        rows = store.connection.execute(
            "SELECT n.bbox_min_x,n.bbox_max_x,n.bbox_min_y,n.bbox_max_y FROM planning_features n "
            "LEFT JOIN planning_features o ON o.snapshot_id=? AND o.canonical_layer_id=n.canonical_layer_id "
            "AND o.object_id=n.object_id WHERE n.snapshot_id=? "
            "AND (o.object_id IS NULL OR o.raw_feature_json IS NOT n.raw_feature_json)",
            (older, newer),
        )
        boxes.extend(row for row in rows if row[0] is not None)
    return boxes


def _plots_near(store: SnapshotStore, snapshot_id: int, boxes: Iterable[Box], reach: float) -> set[Identity]:
    found: set[Identity] = set()
    for min_x, max_x, min_y, max_y in boxes:
        for row in store.parcels_in_bbox(
            min_x - reach, max_x + reach, min_y - reach, max_y + reach, snapshot_id=snapshot_id
        ):
            if row.get("village") and row.get("cts_no"):
                found.add((str(row["village"]), str(row["cts_no"])))
    return found


def affected_plots(
    parcels: SnapshotStore,
    planning: PlanningSnapshotStore,
    *,
    old_parcel_snapshot_id: int,
    new_parcel_snapshot_id: int,
    old_planning_snapshot_id: int,
    new_planning_snapshot_id: int,
) -> AffectedPlots:
    identities: set[Identity] = set()
    objectids: list[int] = []
    planning_boxes: list[Box] = []
    if old_parcel_snapshot_id != new_parcel_snapshot_id:
        own, boxes, objectids = _changed_parcels(parcels, old_parcel_snapshot_id, new_parcel_snapshot_id)
        identities |= own
        identities |= _plots_near(parcels, new_parcel_snapshot_id, boxes, PARCEL_REACH_M)
    if old_planning_snapshot_id != new_planning_snapshot_id:
        planning_boxes = _changed_planning_boxes(planning, old_planning_snapshot_id, new_planning_snapshot_id)
        identities |= _plots_near(parcels, new_parcel_snapshot_id, planning_boxes, PLANNING_REACH_M)
    return AffectedPlots(frozenset(identities), tuple(objectids), len(planning_boxes))


__all__ = ["AffectedPlots", "affected_plots"]
