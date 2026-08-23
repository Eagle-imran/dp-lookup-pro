"""Offline contracts for versioned planning-layer snapshot storage."""

from pathlib import Path

import pytest

from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.planning_snapshot import (
    PlanningLayerInput,
    PlanningSnapshotStateError,
    PlanningSnapshotStore,
    PlanningSnapshotValidationError,
    ingest_planning_snapshot,
)
from dp_lookup.planning_snapshot import store as store_module


def _feature(object_id: int, x: float = 0.0):
    return {
        "attributes": {"OBJECTID": object_id, "CATEGORY": "A"},
        "geometry": {"rings": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 0]]]}
    }


def test_ingestion_is_versioned_atomic_and_preserves_exact_source(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        snapshot = ingest_planning_snapshot(
            store,
            [PlanningLayerInput(57, [_feature(1), _feature(2, 2)], name="legacy", metadata={"audit": "fixture"})],
            source_url="fixture://planning",
            batch_size=1,
        )
        assert snapshot.version == 1
        assert snapshot.complete
        assert snapshot.layers[0].canonical_layer_id == 61
        assert snapshot.layers[0].received_count == 2
        assert snapshot.layers[0].metadata["audit"] == "fixture"
        row = store.features_in_bbox(61, -1, 1, -1, 1, snapshot_id=snapshot.snapshot_id)[0]
        assert row["attributes"] == {"OBJECTID": 1, "CATEGORY": "A"}
        assert row["geometry"]["rings"][0][1] == [1, 0]
        compact = store.compact_features_in_bbox(
            61, -1, 1, -1, 1, snapshot_id=snapshot.snapshot_id
        )[0]
        assert compact["attributes"] == row["attributes"]
        assert "raw_feature" not in compact
        assert store.rtree_available
        assert store.connection.execute(
            "SELECT 1 FROM sqlite_stat1 WHERE idx='planning_features_bbox'"
        ).fetchone()
        selected = store.query_layer(
            snapshot.snapshot_id,
            61,
            arcgis_rings_to_geometry([[[0, 0], [1, 0], [1, 1], [0, 0]]]),
        )
        assert selected[0]["_dp_runtime_geometry"].area > 0
        assert selected[0]["geometry"]["rings"][0][1] == [1, 0]


def test_alias_layer_is_canonically_deduplicated_and_conflicts_fail(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        sid = store.begin_snapshot()
        store.register_layer(sid, 57, expected_count=1)
        store.insert_batch(sid, 57, [_feature(1)])
        assert store.insert_batch(sid, 61, [_feature(1)]) == 1
        assert store.validate(sid)["layers"][0]["count"] == 1
        with pytest.raises(ValueError, match="conflicting duplicate"):
            store.insert_batch(sid, 61, [_feature(1, 9)])


def test_incomplete_snapshot_cannot_finalize_or_activate(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        sid = store.begin_snapshot()
        store.register_layer(sid, 2250, expected_count=2)
        store.set_layer_inventory(sid, 2250, [1, 2])
        store.insert_batch(sid, 2250, [_feature(1)])
        with pytest.raises(PlanningSnapshotValidationError):
            store.finalize(sid)
        assert store.snapshot(sid).state == "failed"
        with pytest.raises(PlanningSnapshotStateError):
            store.activate(sid)


def test_activation_and_rollback_are_independent_of_parcel_snapshot(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        first = ingest_planning_snapshot(store, {0: [_feature(1)]})
        store.activate(first.snapshot_id)
        second = ingest_planning_snapshot(store, {0: [_feature(2)]})
        store.activate(second.snapshot_id)
        assert store.active_snapshot_id() == second.snapshot_id
        assert store.rollback().snapshot_id == first.snapshot_id


def test_inventory_record_with_empty_official_geometry_is_complete_but_warned(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        sid = store.begin_snapshot()
        store.register_layer(sid, 47, expected_count=1)
        store.set_layer_inventory(sid, 47, [1])
        store.insert_batch(
            sid,
            47,
            [{"attributes": {"OBJECTID": 1}, "geometry": {"rings": []}}],
        )

        report = store.validate(sid)

        assert report["ok"] is True
        assert any("no finite coordinates" in warning for warning in report["warnings"])
        assert store.finalize(sid).complete is True


def test_status_is_compact_and_failed_snapshots_can_be_pruned(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        failed_id = store.begin_snapshot(metadata={"large_internal_value": "not-for-status"})
        store.register_layer(failed_id, 2250, expected_count=2)
        store.set_layer_inventory(failed_id, 2250, [1, 2])
        store.insert_batch(failed_id, 2250, [_feature(1)])
        with pytest.raises(PlanningSnapshotValidationError):
            store.finalize(failed_id)

        ready = ingest_planning_snapshot(store, {0: [_feature(2)]})
        store.activate(ready.snapshot_id)
        status = store.status()

        assert status["active_snapshot_id"] == ready.snapshot_id
        assert status["snapshots"][-1]["layer_count"] == 1
        assert status["snapshots"][-1]["record_count"] == 1
        assert "layers" not in status["snapshots"][-1]

        assert store.prune_failed_snapshots() == (failed_id,)
        assert [item["snapshot_id"] for item in store.status()["snapshots"]] == [ready.snapshot_id]
        assert store.prune_failed_snapshots() == ()


def test_store_state_and_input_guards_fail_before_corruption(tmp_path: Path):
    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        assert store.pin_active_snapshot() is None
        assert store.features_in_bbox(0, 0, 1, 0, 1) == []
        with pytest.raises(ValueError, match="positive integer"):
            store.begin_snapshot(version=0)

        sid = store.begin_snapshot(metadata={"registry_hash": "fixture"})
        assert store.find_resumable_snapshot("fixture") == sid
        store.update_snapshot_metadata(sid, {"registry_hash": "updated"})
        assert store.find_resumable_snapshot("fixture") is None
        assert store.find_resumable_snapshot("updated") == sid
        with pytest.raises(ValueError, match="non-negative"):
            store.register_layer(sid, 1, expected_count=-1)
        with pytest.raises(ValueError, match="must not be blank"):
            store.register_layer(sid, 1, object_id_field="")
        with pytest.raises(ValueError, match="non-negative"):
            store.set_layer_inventory(sid, 1, [-1])
        with pytest.raises(ValueError, match="feature must be"):
            store.insert_batch(sid, 1, [object()])
        with pytest.raises(ValueError, match="attributes must be"):
            store.insert_batch(sid, 1, [{"attributes": []}])
        with pytest.raises(ValueError, match="missing OBJECTID"):
            store.insert_batch(sid, 1, [{"attributes": {"CODE": "x"}}])
        with pytest.raises(PlanningSnapshotStateError, match="can be activated"):
            store.activate(sid)
        with pytest.raises(PlanningSnapshotStateError, match="no previous"):
            store.rollback()
        with pytest.raises(ValueError, match="shapely bounds"):
            store.query_layer(sid, 1, object())
        with pytest.raises(KeyError, match="unknown planning snapshot"):
            store.object_ids(999, 1)
        assert store.fail_snapshot(sid, "fixture failure").state == "failed"
        with pytest.raises(PlanningSnapshotStateError, match="not building"):
            store.update_snapshot_metadata(sid, {})


def test_bbox_fallback_and_serialization_guards(tmp_path: Path):
    assert store_module._bbox({"x": 2, "y": 3}) == (2.0, 2.0, 3.0, 3.0)
    assert store_module._bbox({"paths": [[[0, 1], [2, 3]]]}) == (0.0, 2.0, 1.0, 3.0)
    assert store_module._bbox({"unexpected": True}) is None
    assert store_module._bbox([[float("nan"), 1]]) is None
    with pytest.raises(ValueError, match="not valid JSON"):
        store_module._json("{", "fixture")
    with pytest.raises(ValueError, match="cannot be encoded"):
        store_module._json({"bad": float("nan")}, "fixture")

    with PlanningSnapshotStore.open(tmp_path / "planning.sqlite") as store:
        snapshot = ingest_planning_snapshot(store, {0: [_feature(1)]})
        store.activate(snapshot.snapshot_id)
        store._rtree_available = False
        rows = store.features_in_bbox(0, -1, 2, -1, 2)
        assert [row["object_id"] for row in rows] == [1]
