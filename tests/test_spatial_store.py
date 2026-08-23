import json

import pytest

from dp_lookup.spatial_store import (
    SCHEMA_VERSION,
    SnapshotStateError,
    SnapshotStore,
    SnapshotValidationError,
    StoreCorruptError,
)


def parcel(objectid, village="WORLI", cts="733", x=0.0, y=0.0, attrs=None):
    rings = [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y], [x, y]]]
    return {
        "objectid": objectid,
        "village": village,
        "cts_no": cts,
        "ward": "G/S",
        "area_app_sqm": 1.0,
        "raw_attrs": attrs or {"OBJECTID": objectid, "VILLAGE": village, "CTS_CS_NO": cts},
        "rings": rings,
    }


def make_ready(store, records, expected=None):
    sid = store.begin_snapshot(source="test", expected_count=expected if expected is not None else len(records))
    store.insert_batch(sid, records)
    store.finalize_snapshot(sid)
    return sid


def test_schema_is_idempotent_and_wal_foreign_keys(tmp_path):
    path = tmp_path / "parcels.sqlite"
    with SnapshotStore.open(path) as store:
        assert store.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.status()["schema_version"] == SCHEMA_VERSION
    with SnapshotStore.open(path) as reopened:
        assert reopened.status()["snapshots"] == []


def test_snapshot_round_trip_and_duplicate_cts_returns_all(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = make_ready(store, [parcel(1), parcel(2, cts="733")])
        assert store.connection.execute(
            "SELECT 1 FROM sqlite_stat1 WHERE idx='parcels_lookup'"
        ).fetchone()
        store.activate(sid)
        matches = store.lookup("WORLI", "733")
        assert [row["objectid"] for row in matches] == [1, 2]
        assert matches[0]["geometry"] == parcel(1)["rings"]
        assert json.loads(matches[0]["raw_attrs_json"]) == matches[0]["raw_attrs"]
        assert store.count() == 2


def test_composite_identity_upsert_does_not_merge_cts_duplicates(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = store.begin_snapshot(expected_count=2)
        store.insert_batch(sid, [parcel(1), parcel(1, cts="734"), parcel(2)])
        assert store.count(sid) == 2
        store.finalize_snapshot(sid)
        assert [x["cts_no"] for x in store.lookup("WORLI", "734", snapshot_id=sid)] == ["734"]


def test_finalization_validation_and_immutable_rows(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = store.begin_snapshot(expected_count=2)
        store.insert_batch(sid, [parcel(1)])
        with pytest.raises(SnapshotValidationError):
            store.finalize_snapshot(sid)
        assert store.snapshot(sid).state == "failed"
        with pytest.raises(SnapshotStateError):
            store.insert_batch(sid, [parcel(2)])


def test_activation_and_rollback(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        first = make_ready(store, [parcel(1)])
        second = make_ready(store, [parcel(2)])
        store.activate(first)
        store.activate(second)
        assert store.active_snapshot_id() == second
        assert store.rollback().snapshot_id == first
        assert store.active_snapshot_id() == first


def test_bbox_query_and_missing_rtree_fallback(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = make_ready(store, [parcel(1), parcel(2, x=10)])
        found = store.parcels_in_bbox(-1, 2, -1, 2, snapshot_id=sid)
        assert [x["objectid"] for x in found] == [1]
        if store.rtree_available:
            store.connection.execute("DROP TABLE parcel_bbox")
            store.connection.commit()
            store.rtree_available = False
            assert [x["objectid"] for x in store.parcels_in_bbox(-1, 2, -1, 2, snapshot_id=sid)] == [1]


def test_corrupt_database_is_explicit(tmp_path):
    path = tmp_path / "broken.sqlite"
    path.write_bytes(b"not sqlite")
    with pytest.raises(StoreCorruptError):
        SnapshotStore.open(path)


def test_integrity_and_wkb_are_preserved(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = store.begin_snapshot(expected_count=1)
        row = parcel(1)
        row.pop("rings")
        row["geometry"] = b"\x01\x02"
        row["geom_format"] = "wkb"
        store.insert_batch(sid, [row])
        assert store.validate_snapshot(sid)["ok"]
        assert store.list_parcels(sid)[0]["geometry"] == b"\x01\x02"


def test_search_filters_are_indexed_deterministic_and_json_safe(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = make_ready(
            store,
            [
                parcel(3, village="BANDRA", cts="9", x=5, attrs={"x": 3}),
                dict(parcel(1, village="WORLI", cts="1", x=2), area_app_sqm=10.0, ward="G/S"),
                dict(parcel(2, village="WORLI", cts="2", x=3), area_app_sqm=20.0, ward="G/N"),
            ],
        )
        rows = store.search_parcels(sid, village="WORLI", min_area_sqm=10, max_area_sqm=20, limit=1)
        assert [row["objectid"] for row in rows] == [1]
        assert isinstance(rows[0]["geometry_json"], str)
        assert [row["objectid"] for row in store.search_parcels(sid, ward="G/S", offset=0)] == [1, 3]
        assert store.search_parcels(sid, limit=None, offset=1)[0]["objectid"] == 2
        with pytest.raises(ValueError):
            store.search_parcels(sid, min_area_sqm=2, max_area_sqm=1)
        with pytest.raises(ValueError):
            store.search_parcels(sid, limit=-1)


def test_duplicate_identity_groups_reports_all_source_features(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = make_ready(store, [parcel(4, cts="1"), parcel(2, cts="1"), parcel(3, cts="2")])
        assert store.duplicate_identity_groups(sid) == [
            {"snapshot_id": sid, "village": "WORLI", "cts_no": "1", "feature_count": 2, "objectids": [2, 4]}
        ]


def test_diff_snapshots_reports_add_remove_change_and_identity_change(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        old = make_ready(store, [parcel(1, cts="1"), parcel(2, cts="2")])
        changed = parcel(2, cts="9")
        new = make_ready(store, [changed, parcel(3, cts="3")])
        report = store.diff_snapshots(old, new)
        assert report["added_objectids"] == [3]
        assert report["removed_objectids"] == [1]
        assert report["changed_objectids"] == [2]
        assert report["identity_changes"] == [{"objectid": 2, "old": {"village": "WORLI", "cts_no": "2"}, "new": {"village": "WORLI", "cts_no": "9"}}]
        json.dumps(report)


def test_integrity_check_includes_rtree_check(tmp_path):
    with SnapshotStore.open(tmp_path / "db.sqlite") as store:
        sid = make_ready(store, [parcel(1)])
        report = store.integrity_check(sid)
        assert report["ok"]
        if store.rtree_available:
            assert store.connection.execute("SELECT rtreecheck('parcel_bbox')").fetchone()[0] == "ok"
