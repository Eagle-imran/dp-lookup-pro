"""Focused contracts for local-first STANDARD/FULL planning evidence."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from dp_lookup.clients.planning_evidence_queries import (
    DEFAULT_MAX_PLANNING_EVIDENCE_AGE_DAYS,
    LocalFirstPlanningEvidenceAnalyzer,
    LocalPlanningEvidenceError,
    collect_planning_evidence,
)
from dp_lookup.planning_evidence import STANDARD_LAYER_IDS, EvidenceMode


def _ring(left=0, bottom=0, right=10, top=10):
    return [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]


def _feature(attributes, ring=None):
    return {"attributes": attributes, "geometry": {"rings": [ring or _ring()]}}


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _LiveClient:
    async def post(self, url, *, data):
        del data
        layer_id = int(url.rsplit("/", 2)[-2])
        features = []
        if layer_id == 83:
            features = [_feature({"OBJECTID": 10, "EP_NO": "EP-1", "NOTIFICATION_NO": "N-1"})]
        return _Response({"features": features})


class _Snapshot:
    def __init__(self, finalized_at):
        self.snapshot_id = 7
        self.finalized_at = finalized_at
        self.complete = True


class _Store:
    def __init__(self, finalized_at):
        self.snapshot = _Snapshot(finalized_at)
        self.calls = []

    def pin_active_snapshot(self):
        return self.snapshot

    def query_layer(self, snapshot_id, layer_id, parcel):
        self.calls.append((snapshot_id, layer_id))
        del parcel
        if layer_id == 83:
            return [_feature({"OBJECTID": 10, "EP_NO": "EP-1", "NOTIFICATION_NO": "N-1"})]
        return []


def test_local_standard_uses_one_pinned_snapshot_and_matches_live_findings():
    rings = [_ring()]
    live = asyncio.run(collect_planning_evidence(_LiveClient(), rings, "COLABA", EvidenceMode.STANDARD))
    store = _Store(datetime.now(timezone.utc))
    local = asyncio.run(
        LocalFirstPlanningEvidenceAnalyzer(store, mode="local")(
            _LiveClient(), rings, "COLABA", EvidenceMode.STANDARD
        )
    )

    assert local.complete is live.complete
    assert [finding.to_dict() for finding in local.findings] == [finding.to_dict() for finding in live.findings]
    assert {snapshot_id for snapshot_id, _ in store.calls} == {7}
    assert len(store.calls) == len(STANDARD_LAYER_IDS)
    assert local.provenance["source"] == "local_snapshot"
    assert local.provenance["snapshot_id"] == 7


def test_auto_falls_back_to_live_when_snapshot_is_older_than_biannual_limit():
    old = datetime.now(timezone.utc) - timedelta(days=DEFAULT_MAX_PLANNING_EVIDENCE_AGE_DAYS + 1)
    store = _Store(old)
    report = asyncio.run(
        LocalFirstPlanningEvidenceAnalyzer(store, mode="auto")(
            _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
        )
    )

    assert report.provenance["source"] == "live_arcgis"
    assert report.provenance["fallback"] is True
    assert "stale" in report.provenance["fallback_reason"]
    assert any("live ArcGIS" in warning for warning in report.warnings)


def test_local_mode_surfaces_snapshot_failure_without_live_fallback():
    store = _Store(datetime.now(timezone.utc))

    def fail(*args):
        del args
        raise RuntimeError("disk unavailable")

    store.query_layer = fail
    try:
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(store, mode="local")(
                _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
            )
        )
    except LocalPlanningEvidenceError as exc:
        assert "disk unavailable" in str(exc)
    else:
        raise AssertionError("strict local mode unexpectedly fell back")


def test_basic_and_live_modes_bypass_local_snapshot_safely():
    basic = asyncio.run(
        LocalFirstPlanningEvidenceAnalyzer(None, mode="local")(
            _LiveClient(), [_ring()], "COLABA", EvidenceMode.BASIC
        )
    )
    assert basic.complete is True
    assert basic.outcomes == ()

    live = asyncio.run(
        LocalFirstPlanningEvidenceAnalyzer(None, mode="live")(
            _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
        )
    )
    assert live.provenance == {
        "source": "live_arcgis",
        "method": "bounded_layer_queries",
        "fallback": False,
    }


def test_constructor_and_snapshot_metadata_guards():
    with pytest.raises(ValueError, match="auto, local, or live"):
        LocalFirstPlanningEvidenceAnalyzer(None, mode="wrong")
    with pytest.raises(ValueError, match="positive"):
        LocalFirstPlanningEvidenceAnalyzer(None, max_snapshot_age_days=True)
    with pytest.raises(LocalPlanningEvidenceError, match="no local planning"):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(None, mode="local")(
                _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
            )
        )

    store = _Store(datetime.now(timezone.utc))
    store.snapshot.snapshot_id = ""
    with pytest.raises(LocalPlanningEvidenceError, match="no valid snapshot ID"):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(store, mode="local")(
                _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
            )
        )

    store = _Store(datetime.now(timezone.utc))
    store.snapshot.complete = False
    with pytest.raises(LocalPlanningEvidenceError, match="incomplete"):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(store, mode="local")(
                _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
            )
        )


def test_stale_strict_evidence_can_be_used_with_visible_warning():
    old = datetime.now(timezone.utc) - timedelta(days=400)
    report = asyncio.run(
        LocalFirstPlanningEvidenceAnalyzer(
            _Store(old), mode="local", allow_stale_local=True
        )(_LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD)
    )
    assert report.provenance["snapshot_stale"] is True
    assert any("stale" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    "finalized_at,message",
    [(None, "no finalized timestamp"), ("bad-date", "invalid finalized timestamp")],
)
def test_evidence_rejects_invalid_snapshot_timestamps(finalized_at, message):
    store = _Store(finalized_at)
    with pytest.raises(LocalPlanningEvidenceError, match=message):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(store, mode="local")(
                _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
            )
        )


def test_evidence_store_shape_and_geometry_errors_are_not_hidden():
    class MissingQuery:
        def pin_active_snapshot(self):
            return _Snapshot(datetime.now(timezone.utc))

    with pytest.raises(LocalPlanningEvidenceError, match="no spatial layer query"):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(MissingQuery(), mode="local")(
                _LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD
            )
        )

    class MalformedStore(_Store):
        def query_layer(self, *_args):
            return None

    with pytest.raises(LocalPlanningEvidenceError, match="malformed collection"):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(
                MalformedStore(datetime.now(timezone.utc)), mode="local"
            )(_LiveClient(), [_ring()], "COLABA", EvidenceMode.STANDARD)
        )

    with pytest.raises(LocalPlanningEvidenceError, match="no valid polygon rings"):
        asyncio.run(
            LocalFirstPlanningEvidenceAnalyzer(
                _Store(datetime.now(timezone.utc)), mode="local"
            )(_LiveClient(), [[]], "COLABA", EvidenceMode.STANDARD)
        )
