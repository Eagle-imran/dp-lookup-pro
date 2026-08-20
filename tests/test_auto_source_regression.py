"""Regression coverage for the local-first parcel source policy.

These tests intentionally stay at the source-selection seams: Layer 13 parcel
identity/geometry may come from an active local snapshot, while the live
fallback remains responsible for recovery.  Planning queries are not involved
here and therefore do not become accidentally cached with the parcel source.
"""

import asyncio
from pathlib import Path

import pytest

import dp_lookup.cli as cli
from dp_lookup.application.ingestion import build_parcel_context
from dp_lookup.clients import local_parcels
from dp_lookup.clients.local_parcels import LocalParcelError, LocalParcelFetcher
from dp_lookup.spatial_store import SnapshotStore


def _parcel(objectid: int, cts: str, x: float = 8_066_000.0):
    # EPSG:102100/Web Mercator metres around Mumbai.  Keeping this explicit
    # protects the report's lat/lon assumptions from silently treating local
    # snapshot coordinates as WGS84 degrees.
    attributes = {
        "OBJECTID": objectid,
        "VILLAGE": "WORLI",
        "CTS_CS_NO": cts,
        "WARD": "G/S",
        "TYPE": "CTS",
        "AREA_APP_SQ_MTRS": 100.0,
    }
    geometry = {
        "rings": [[[x, 2_150_000.0], [x + 10, 2_150_000.0],
                    [x + 10, 2_150_010.0], [x, 2_150_010.0],
                    [x, 2_150_000.0]]],
        "spatialReference": {"wkid": 102100},
    }
    return {"objectid": objectid, "attributes": attributes, "geometry": geometry}


def _active_database(path: Path, records):
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source="regression", expected_count=len(records))
        store.insert_batch(snapshot_id, records)
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)
        return snapshot_id


def test_implicit_source_is_auto_when_database_is_supplied(tmp_path):
    parsed = cli._parse_cli_args(["WORLI", "733", "--database", str(tmp_path / "layer13.sqlite")])
    assert parsed["source_mode"] == "auto"
    assert parsed["database_path"] == str(tmp_path / "layer13.sqlite")


def test_implicit_auto_resolves_environment_then_workspace_default(monkeypatch, tmp_path):
    configured = tmp_path / "configured.sqlite"
    monkeypatch.setenv("DP_LOOKUP_DATABASE", str(configured))
    parsed = cli._parse_cli_args(["WORLI", "733"])
    assert parsed["source_mode"] == "auto"
    assert parsed["database_path"] == str(configured)

    monkeypatch.delenv("DP_LOOKUP_DATABASE")
    parsed = cli._parse_cli_args(["WORLI", "733"])
    assert parsed["database_path"] == cli.DEFAULT_DATABASE_PATH


def test_local_hit_preserves_web_mercator_assumption_in_report_coordinates(tmp_path):
    database = tmp_path / "layer13.sqlite"
    snapshot_id = _active_database(database, [_parcel(1, "733")])

    feature = asyncio.run(LocalParcelFetcher(database)(object(), "WORLI", "733"))
    assert feature is not None
    assert feature["attributes"]["_DP_PARCEL_SOURCE"] == "local_snapshot"
    assert feature["attributes"]["_DP_SNAPSHOT_ID"] == snapshot_id
    assert feature["geometry"]["spatialReference"] == {"wkid": 102100}

    parcel, _ = build_parcel_context(feature, "WORLI", "733")
    # A degree-as-metre interpretation would produce absurd values here.
    assert 18.0 < parcel.latitude < 20.0
    assert 71.0 < parcel.longitude < 73.0


@pytest.mark.parametrize("database_kind", ["missing", "corrupt", "no_active", "local_miss"])
def test_auto_fetcher_uses_live_fallback_for_unusable_local_state(tmp_path, database_kind):
    database = tmp_path / f"{database_kind}.sqlite"
    if database_kind == "corrupt":
        database.write_bytes(b"not a sqlite database")
    elif database_kind == "no_active":
        with SnapshotStore.open(database) as store:
            snapshot_id = store.begin_snapshot(source="regression", expected_count=1)
            store.insert_batch(snapshot_id, [_parcel(1, "733")])
            store.finalize_snapshot(snapshot_id)
            # Deliberately leave the ready snapshot inactive.
    elif database_kind == "local_miss":
        _active_database(database, [_parcel(1, "733")])

    calls = []

    async def live_fallback(_client, village, cts):
        calls.append((village, cts))
        return _parcel(99, cts)

    result = asyncio.run(
        LocalParcelFetcher(database, fallback=live_fallback)(object(), "WORLI", "999" if database_kind == "local_miss" else "733")
    )
    assert result["attributes"]["OBJECTID"] == 99
    assert result["attributes"].get("_DP_PARCEL_SOURCE") != "local_snapshot"
    assert result["attributes"]["_DP_LOCAL_FALLBACK_REASON"]
    assert calls == [("WORLI", "999" if database_kind == "local_miss" else "733")]


def test_local_source_never_falls_back_for_missing_or_invalid_database(tmp_path):
    with pytest.raises(LocalParcelError, match="does not exist"):
        asyncio.run(LocalParcelFetcher(tmp_path / "missing.sqlite")(object(), "WORLI", "733"))
    with pytest.raises(LocalParcelError):
        asyncio.run(LocalParcelFetcher(tmp_path / "missing.sqlite", fallback=None)(object(), "WORLI", "733"))


def test_old_snapshot_remains_local_but_is_visibly_marked_stale(tmp_path, monkeypatch):
    database = tmp_path / "old.sqlite"
    _active_database(database, [_parcel(1, "733")])
    calls = []

    async def live_fallback(_client, village, cts):
        calls.append((village, cts))
        return _parcel(99, cts)

    # Snapshot creation uses the real clock; advance only the local adapter's
    # clock so this test remains deterministic and does not mutate SQLite.
    real_now = local_parcels.time.time()
    monkeypatch.setattr(local_parcels.time, "time", lambda: real_now + 211 * 86_400)
    result = asyncio.run(
        LocalParcelFetcher(database, fallback=live_fallback)(object(), "WORLI", "733")
    )
    assert result["attributes"]["_DP_PARCEL_SOURCE"] == "local_snapshot"
    assert result["attributes"]["_DP_SNAPSHOT_STALE"] is True
    assert result["attributes"]["_DP_SNAPSHOT_AGE_DAYS"] == pytest.approx(211, abs=0.01)
    assert calls == []


def test_fetcher_pins_snapshot_across_concurrent_activation(tmp_path):
    database = tmp_path / "pin.sqlite"
    first = _active_database(database, [_parcel(1, "733")])
    fetcher = LocalParcelFetcher(database, snapshot_id=first)
    with SnapshotStore.open(database) as store:
        second = store.begin_snapshot(source="regression", expected_count=1)
        store.insert_batch(second, [_parcel(2, "733", 8_066_100.0)])
        store.finalize_snapshot(second)
        store.activate(second)

    result = asyncio.run(fetcher(object(), "WORLI", "733"))
    assert result["attributes"]["OBJECTID"] == 1
    assert result["attributes"]["_DP_SNAPSHOT_ID"] == first


def test_snapshot_specific_cache_namespace_changes_with_active_snapshot(tmp_path):
    database = tmp_path / "layer13.sqlite"
    first = _active_database(database, [_parcel(1, "733")])
    first_key = cli._local_cache_namespace("auto", str(database))

    with SnapshotStore.open(database) as store:
        second = store.begin_snapshot(source="regression", expected_count=1)
        store.insert_batch(second, [_parcel(2, "733", 8_066_100.0)])
        store.finalize_snapshot(second)
        store.activate(second)

    second_key = cli._local_cache_namespace("auto", str(database))
    assert f"snapshot={first}:" in first_key
    assert f"snapshot={second}:" in second_key
    assert first_key != second_key


@pytest.mark.parametrize("extra", [[], ["--database", "ignored.sqlite"]])
def test_explicit_live_source_keeps_live_dependencies(monkeypatch, capsys, extra):
    calls = {}

    async def fake_lookup(**kwargs):
        calls.update(kwargs)
        return {"error": "expected test short-circuit"}

    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    assert cli.main(["WORLI", "733", "--source", "live", *extra]) == cli.EXIT_ERROR
    dependencies = calls["dependencies"]
    assert dependencies.parcel_cache_namespace == "live"
    assert not isinstance(dependencies.parcel_fetcher, LocalParcelFetcher)
    assert "expected test short-circuit" in capsys.readouterr().out


def test_explicit_local_source_has_no_live_fallback(monkeypatch, tmp_path):
    calls = {}

    async def fake_lookup(**kwargs):
        calls.update(kwargs)
        return {"error": "expected test short-circuit"}

    database = tmp_path / "layer13.sqlite"
    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    assert cli.main(["WORLI", "733", "--source", "local", "--database", str(database)]) == cli.EXIT_ERROR
    dependencies = calls["dependencies"]
    assert isinstance(dependencies.parcel_fetcher, LocalParcelFetcher)
    assert dependencies.parcel_fetcher.fallback is None
    assert dependencies.neighbour_provider.database == database
