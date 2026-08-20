"""Contracts for local-first planning snapshot reads."""

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone

import pytest

from dp_lookup.clients import local_planning as local_planning_module
from dp_lookup.clients.local_planning import (
    LocalFirstPlanningQuery,
    LocalPlanningError,
    PlanningSnapshot,
)
from dp_lookup.core.constants import LAYER_ZONE


def _ring(left, bottom, right, top):
    return [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]


def _feature(ring, **attributes):
    return {"attributes": attributes, "geometry": {"rings": [ring]}}


class FakePlanningStore:
    def __init__(self, snapshot, layers=None, error=None):
        self.snapshot = snapshot
        self.layers = layers or {}
        self.error = error
        self.pin_calls = 0
        self.queries = []

    def pin_active_snapshot(self):
        self.pin_calls += 1
        if self.error:
            raise self.error
        return self.snapshot

    def query_layer(self, snapshot_id, layer_id, parcel_geometry):
        self.queries.append((snapshot_id, layer_id, parcel_geometry))
        if self.error:
            raise self.error
        return self.layers.get(layer_id, [])


def _live_result():
    return {
        "primary_zone": "R",
        "zones": [{"zone": "R", "overlap_sqm": 100.0, "overlap_percent": 100.0}],
        "reservations": [],
        "designations": [],
        "modifications": [],
        "metro_buffer": "NO",
        "crz_status": "NO (Outside CRZ Buffer)",
        "encumbered_area_sqm": 0.0,
        "encumbered_percent": 0.0,
        "net_unencumbered_sqm": 100.0,
        "net_unencumbered_percent": 100.0,
        "warnings": [],
        "queried_layers": [0],
        "successful_layers": [0],
    }


def test_local_query_pins_one_snapshot_and_passes_parcel_geometry_to_every_layer():
    store = FakePlanningStore(
        PlanningSnapshot("planning-17", finalized_at=datetime.now(timezone.utc)),
        {LAYER_ZONE: [_feature(_ring(0, 0, 10, 10), ZONE_CODE2="R")]},
    )
    query = LocalFirstPlanningQuery(store, max_snapshot_age_days=None)

    result = asyncio.run(query(object(), [_ring(0, 0, 10, 10)]))

    assert result["primary_zone"] == "R"
    assert result["provenance"] == {
        "source": "local_snapshot",
        "method": "local_snapshot_spatial_query",
        "snapshot_id": "planning-17",
        "snapshot_finalized_at": store.snapshot.finalized_at,
        "snapshot_age_days": 0.0,
        "snapshot_stale": False,
        "fallback": False,
    }
    assert store.pin_calls == 1
    assert len(store.queries) == 8
    assert {call[0] for call in store.queries} == {"planning-17"}
    assert all(call[2].area == 100.0 for call in store.queries)


def test_auto_falls_back_to_live_for_unavailable_local_snapshot():
    store = FakePlanningStore(None, error=RuntimeError("database is corrupt"))

    async def live(_client, _rings):
        return _live_result()

    result = asyncio.run(LocalFirstPlanningQuery(store, live_query=live)(object(), [_ring(0, 0, 10, 10)]))

    assert result["primary_zone"] == "R"
    assert result["provenance"]["source"] == "live_arcgis"
    assert result["provenance"]["fallback"] is True
    assert "database is corrupt" in result["provenance"]["fallback_reason"]
    assert any("live ArcGIS" in warning for warning in result["provenance"]["warnings"])


def test_stale_snapshot_falls_back_and_reports_staleness_reason():
    old = datetime.now(timezone.utc) - timedelta(days=211)
    store = FakePlanningStore(PlanningSnapshot(4, finalized_at=old))

    async def live(_client, _rings):
        return _live_result()

    result = asyncio.run(LocalFirstPlanningQuery(store, live_query=live)(object(), [_ring(0, 0, 10, 10)]))

    assert result["provenance"]["fallback"] is True
    assert "stale" in result["provenance"]["fallback_reason"]
    assert result["provenance"]["source"] == "live_arcgis"


def test_live_mode_does_not_touch_local_store():
    store = FakePlanningStore(None, error=AssertionError("must not be called"))

    async def live(_client, _rings):
        return _live_result()

    result = asyncio.run(
        LocalFirstPlanningQuery(store, mode="live", live_query=live)(object(), [_ring(0, 0, 10, 10)])
    )

    assert result == _live_result()
    assert store.pin_calls == 0


def test_strict_local_mode_surfaces_unavailable_snapshot():
    query = LocalFirstPlanningQuery(FakePlanningStore(None, error=RuntimeError("offline")), mode="local")

    with pytest.raises(LocalPlanningError, match="offline"):
        asyncio.run(query(object(), [_ring(0, 0, 10, 10)]))


def test_constructor_and_timestamp_guards_are_explicit():
    with pytest.raises(ValueError, match="auto, local, or live"):
        LocalFirstPlanningQuery(None, mode="unknown")
    with pytest.raises(ValueError, match="positive"):
        LocalFirstPlanningQuery(None, max_snapshot_age_days=0)
    assert local_planning_module._age_days(None) is None
    assert local_planning_module._age_days("invalid") is None
    assert local_planning_module._age_days(math.inf) is None
    assert local_planning_module._age_days(str(time.time())) == pytest.approx(0.0, abs=0.01)
    assert local_planning_module._snapshot_value({"snapshot_id": 9}, "snapshot_id") == 9


def test_strict_local_allows_stale_snapshot_only_when_requested():
    old = datetime.now(timezone.utc) - timedelta(days=400)
    store = FakePlanningStore(
        PlanningSnapshot(8, finalized_at=old),
        {LAYER_ZONE: [_feature(_ring(0, 0, 10, 10), ZONE_CODE2="R")]},
    )
    result = asyncio.run(
        LocalFirstPlanningQuery(store, mode="local", allow_stale_local=True)(
            object(), [_ring(0, 0, 10, 10)]
        )
    )
    assert result["provenance"]["snapshot_stale"] is True
    assert "stale" in result["warnings"][0]


@pytest.mark.parametrize(
    "snapshot,message",
    [
        (None, "no active"),
        (PlanningSnapshot("", finalized_at=datetime.now(timezone.utc)), "no valid snapshot ID"),
        (PlanningSnapshot(1, finalized_at=None), "no finalized timestamp"),
        (PlanningSnapshot(1, finalized_at="not-a-date"), "invalid finalized timestamp"),
    ],
)
def test_strict_local_rejects_invalid_snapshot_metadata(snapshot, message):
    query = LocalFirstPlanningQuery(FakePlanningStore(snapshot), mode="local")
    with pytest.raises(LocalPlanningError, match=message):
        asyncio.run(query(object(), [_ring(0, 0, 10, 10)]))


@pytest.mark.parametrize("records,message", [(None, "no collection"), ({}, "malformed collection")])
def test_strict_local_rejects_malformed_store_collections(records, message):
    class Store(FakePlanningStore):
        def query_layer(self, snapshot_id, layer_id, parcel_geometry):
            del snapshot_id, layer_id, parcel_geometry
            return records

    store = Store(PlanningSnapshot(1, finalized_at=datetime.now(timezone.utc)))
    with pytest.raises(LocalPlanningError, match=message):
        asyncio.run(LocalFirstPlanningQuery(store, mode="local")(object(), [_ring(0, 0, 10, 10)]))


def test_legacy_store_seams_and_query_failures_are_supported_safely():
    class LegacyStore:
        def active_snapshot(self):
            return {"snapshot_id": 3, "finalized_at": datetime.now(timezone.utc)}

        def records_intersecting(self, snapshot_id, layer_id, parcel):
            del snapshot_id, parcel
            if layer_id == LAYER_ZONE:
                return [_feature(_ring(0, 0, 10, 10), ZONE_CODE2="R")]
            return []

    result = asyncio.run(
        LocalFirstPlanningQuery(LegacyStore(), mode="local")(object(), [_ring(0, 0, 10, 10)])
    )
    assert result["primary_zone"] == "R"

    class MissingQuery:
        def pin_active_snapshot(self):
            return PlanningSnapshot(1, finalized_at=datetime.now(timezone.utc))

    with pytest.raises(LocalPlanningError, match="no spatial layer query"):
        asyncio.run(
            LocalFirstPlanningQuery(MissingQuery(), mode="local")(object(), [_ring(0, 0, 10, 10)])
        )

    class ExplodingStore(FakePlanningStore):
        def query_layer(self, *_args):
            raise ValueError("bad index")

    exploding = ExplodingStore(PlanningSnapshot(1, finalized_at=datetime.now(timezone.utc)))
    with pytest.raises(LocalPlanningError, match="bad index"):
        asyncio.run(
            LocalFirstPlanningQuery(exploding, mode="local")(object(), [_ring(0, 0, 10, 10)])
        )

    with pytest.raises(LocalPlanningError, match="no valid polygon rings"):
        asyncio.run(LocalFirstPlanningQuery(LegacyStore(), mode="local")(object(), [[]]))
