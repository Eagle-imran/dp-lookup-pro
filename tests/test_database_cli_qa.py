"""Additional network-free QA for the local snapshot workflow.

These tests exercise the user-facing seams that are easy to break while the
database implementation evolves: CLI grammar, lifecycle output, fallback
behavior, and the distinction between source features and CTS identities.
"""

import asyncio
import hashlib
import io
import json
from pathlib import Path

import pytest

import dp_lookup.cli as cli
from dp_lookup.application.contracts import ParcelContext
from dp_lookup.application.local_spatial import LocalNeighbourProvider
from dp_lookup.authority import AuthorityManifest, AuthorityStore, SelectionPurpose, SourceType
from dp_lookup.clients.local_parcels import LocalParcelError, LocalParcelFetcher, merge_local_features
from dp_lookup.database_cli import EXIT_SUCCESS
from dp_lookup.database_cli import main as database_main
from dp_lookup.spatial_store import SnapshotStore


def _parcel(objectid: int, cts: str, x: float, *, village: str = "WORLI", area: float = 100.0):
    attributes = {
        "OBJECTID": objectid,
        "VILLAGE": village,
        "CTS_CS_NO": cts,
        "WARD": "G/S",
        "TYPE": "CTS",
        "AREA_APP_SQ_MTRS": area,
    }
    rings = [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]]
    return {
        "objectid": objectid,
        "attributes": attributes,
        "geometry": {"rings": rings, "spatialReference": {"wkid": 102100}},
    }


def _ready_database(path: Path, records):
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source="qa", expected_count=len(records))
        store.insert_batch(snapshot_id, records)
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)
        return snapshot_id


def test_lookup_source_modes_are_explicit_and_round_trip_paths(tmp_path):
    database = str(tmp_path / "snapshot.sqlite")
    parsed = cli._parse_cli_args(["WORLI", "733", "--source", "local", "--database", database])
    assert parsed["source_mode"] == "local"
    assert parsed["database_path"] == database

    parsed = cli._parse_cli_args(["WORLI", "733", "--source=auto", "--database=" + database])
    assert parsed["source_mode"] == "auto"
    assert parsed["database_path"] == database

    with pytest.raises(ValueError, match="one of: live, local, auto"):
        cli._parse_cli_args(["WORLI", "733", "--source", "remote"])
    with pytest.raises(ValueError, match="--database PATH is required"):
        cli._parse_cli_args(["WORLI", "733", "--source", "local"])


def test_report_cache_namespace_changes_when_authority_registry_changes(tmp_path):
    database = tmp_path / "snapshot.sqlite"
    _ready_database(database, [_parcel(1, "733", 0)])
    before = cli._local_cache_namespace("local", str(database))
    document = tmp_path / "property-card.pdf"
    document.write_bytes(b"property card")
    with AuthorityStore.open(database) as store:
        record = store.register(
            AuthorityManifest(
                village="WORLI",
                cts_no="733",
                source_type=SourceType.PROPERTY_CARD,
                source_uri=str(document),
                source_sha256=hashlib.sha256(document.read_bytes()).hexdigest(),
                issuer="City Survey Office",
                recorded_area_sqm=1400.0,
            )
        )
        store.verify(record.record_id, actor="reviewer")
        store.activate(record.record_id, SelectionPurpose.AREA, actor="reviewer", reason="accepted area")
    after = cli._local_cache_namespace("local", str(database))

    assert before != after
    assert "authority_revision=" in after


def test_database_status_json_is_stable_for_missing_store(tmp_path):
    output = io.StringIO()
    database = tmp_path / "missing.sqlite"
    assert (
        database_main(
            ["database", "status", "--database", str(database), "--json"],
            services=_StatusServices(),
            out=output,
        )
        == EXIT_SUCCESS
    )
    payload = json.loads(output.getvalue())
    assert payload["command"] == "status"
    assert payload["database"] == str(database)
    assert payload["result"]["active_snapshot_id"] is None


class _StatusServices:
    def status(self, database):
        return {"path": str(database), "exists": False, "active_snapshot_id": None, "snapshots": []}

    def build(self, database):
        raise AssertionError("not used")

    def verify(self, database):
        raise AssertionError("not used")

    def diff(self, database):
        raise AssertionError("not used")

    def activate(self, database):
        raise AssertionError("not used")

    def rollback(self, database):
        raise AssertionError("not used")


def test_snapshot_activation_rollback_and_status_are_reproducible(tmp_path):
    path = tmp_path / "snapshots.sqlite"
    with SnapshotStore.open(path) as store:
        first = store.begin_snapshot(source="qa", expected_count=1)
        store.insert_batch(first, [_parcel(1, "733", 0)])
        store.finalize_snapshot(first)
        second = store.begin_snapshot(source="qa", expected_count=1)
        store.insert_batch(second, [_parcel(2, "734", 20)])
        store.finalize_snapshot(second)
        store.activate(first)
        store.activate(second)
        assert store.active_snapshot_id() == second
        assert store.rollback().snapshot_id == first
        status = store.status()
        assert status["active_snapshot_id"] == first
        assert [row["state"] for row in status["snapshots"]] == ["active", "retired"]


def test_local_fetcher_auto_fallback_is_used_for_missing_identity(tmp_path):
    path = tmp_path / "snapshots.sqlite"
    _ready_database(path, [_parcel(1, "733", 0)])
    calls = []

    async def fallback(_client, village, cts):
        calls.append((village, cts))
        return {"attributes": {"OBJECTID": 99}, "geometry": {"rings": []}}

    result = asyncio.run(LocalParcelFetcher(path, fallback=fallback)(object(), "WORLI", "999"))
    assert result["attributes"]["OBJECTID"] == 99
    assert calls == [("WORLI", "999")]


def test_local_fetcher_corrupt_geometry_falls_back_in_auto_mode(tmp_path):
    path = tmp_path / "snapshots.sqlite"
    # A ready snapshot can contain a source row with no geometry; local mode
    # must reject it, while auto mode should have a live escape hatch.
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source="qa", expected_count=1)
        store.insert_batch(snapshot_id, [{"objectid": 1, "attributes": {"VILLAGE": "WORLI", "CTS_CS_NO": "733"}}])
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)

    async def fallback(_client, _village, _cts):
        return {"attributes": {"OBJECTID": 7}, "geometry": {"rings": []}}

    result = asyncio.run(LocalParcelFetcher(path, fallback=fallback)(object(), "WORLI", "733"))
    assert result["attributes"]["OBJECTID"] == 7
    with pytest.raises(LocalParcelError, match="has no polygon rings"):
        asyncio.run(LocalParcelFetcher(path)(object(), "WORLI", "733"))


def test_local_neighbours_group_duplicate_source_parts_and_report_ids(tmp_path):
    path = tmp_path / "snapshots.sqlite"
    subject = _parcel(1, "733", 0)
    # Make the subject 40 m wide so both adjoining source parts are inside
    # the spatial prefilter. The two parts still remain separate source
    # features under one CTS identity.
    subject["geometry"]["rings"] = [[[0, 0], [40, 0], [40, 10], [0, 10], [0, 0]]]
    first_part = _parcel(2, "734", 40)
    first_part["geometry"]["rings"] = [[[40, 0], [50, 0], [50, 5], [40, 5], [40, 0]]]
    second_part = _parcel(3, "734", 40)
    second_part["geometry"]["rings"] = [[[40, 5], [50, 5], [50, 10], [40, 10], [40, 5]]]
    records = [subject, first_part, second_part]
    _ready_database(path, records)
    fetched = asyncio.run(LocalParcelFetcher(path)(object(), "WORLI", "733"))
    parcel = ParcelContext(
        village="WORLI",
        cts_no="733",
        attrs=fetched["attributes"],
        rings=fetched["geometry"]["rings"],
        wgs_rings=[],
        area_sqm=100,
        area_source="approved",
        latitude=0,
        longitude=0,
        cx=5,
        cy=5,
        mcx=5,
        mcy=5,
        xs=[0, 10],
        ys=[0, 10],
        window_radius=100,
    )
    neighbours = LocalNeighbourProvider(path)(parcel)
    assert [item["cts_no"] for item in neighbours.plots] == ["734"]
    assert neighbours.plots[0]["source_objectids"] == [2, 3]


def test_auto_mode_does_not_replace_live_neighbour_evidence(tmp_path):
    """A live-fallback parcel must keep the existing probe-based path.

    The local provider is installed for ``--source auto`` but only owns
    adjacency when the parcel itself came from the local snapshot. Returning
    ``None`` is the dependency signal for the normal live neighbour stage.
    """
    parcel = ParcelContext(
        village="WORLI",
        cts_no="733",
        attrs={"OBJECTID": 99},
        rings=[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        wgs_rings=[],
        area_sqm=100,
        area_source="approved",
        latitude=0,
        longitude=0,
        cx=5,
        cy=5,
        mcx=5,
        mcy=5,
        xs=[0, 10],
        ys=[0, 10],
        window_radius=100,
    )
    assert LocalNeighbourProvider(tmp_path / "not-used.sqlite")(parcel) is None


def test_duplicate_cts_merge_keeps_conflicting_area_explicit():
    rows = [
        {
            "objectid": 2,
            "area_app_sqm": 200,
            "raw_attrs": {"VILLAGE": "WORLI", "CTS_CS_NO": "733"},
            "geometry": _parcel(2, "733", 10)["geometry"],
        },
        {
            "objectid": 1,
            "area_app_sqm": 100,
            "raw_attrs": {"VILLAGE": "WORLI", "CTS_CS_NO": "733"},
            "geometry": _parcel(1, "733", 0)["geometry"],
        },
    ]
    merged = merge_local_features(rows)
    assert merged is not None
    assert merged["attributes"]["AREA_APP_SQ_MTRS"] is None
    assert merged["attributes"]["_DP_AREA_CONFLICT_VALUES"] == [100.0, 200.0]


def test_duplicate_geometry_is_deduplicated_and_flagged_without_changing_source_ids():
    geometry = _parcel(1, "733", 0)["geometry"]
    rows = [
        {
            "objectid": 1,
            "area_app_sqm": 100,
            "raw_attrs": {"VILLAGE": "WORLI", "CTS_CS_NO": "733"},
            "geometry": geometry,
        },
        {
            "objectid": 2,
            "area_app_sqm": None,
            "raw_attrs": {"VILLAGE": "WORLI", "CTS_CS_NO": "733"},
            "geometry": geometry,
        },
    ]

    merged = merge_local_features(rows)

    assert merged is not None
    assert merged["attributes"]["SOURCE_OBJECTIDS"] == [1, 2]
    assert merged["attributes"]["_DP_DUPLICATE_GEOMETRY_COUNT"] == 1
    assert merged["attributes"]["_DP_RECORDED_AREA_MISSING_PARTS"] is True
    assert merged["geometry"]["rings"] == geometry["rings"]
