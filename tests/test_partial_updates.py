"""Partial updates must produce exactly what a full rebuild of the same sources would."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_plot_intelligence import _parcel, _planning_feature, _polygon

from dp_lookup.application.database_services import LocalDatabaseServices
from dp_lookup.application.intelligence_builder import PlotIntelligenceBuilder
from dp_lookup.application.planning_snapshot import canonical_planning_specs
from dp_lookup.application.snapshot_ingestion import SnapshotIngestionConfig
from dp_lookup.cli_parser import normalize_admin_args
from dp_lookup.clients.parcel_snapshot import SnapshotIngestionError, sha256_json
from dp_lookup.database_cli import parse_database_args
from dp_lookup.intelligence import IntelligenceStore
from dp_lookup.intelligence_cli import parse_intelligence_args
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore

DAY_MS = 86_400_000
EDITED_AT = 1_794_006_052_000


def _source(objectid: int, left: float, edited: int = EDITED_AT) -> dict[str, Any]:
    attributes = {"OBJECTID": objectid, "VILLAGE": "WORLI", "CTS_CS_NO": str(objectid), "LAST_EDITED_DATE": edited}
    return {"attributes": attributes, "geometry": _polygon(left, 0, left + 10, 10)}


class _Client:
    def __init__(self, responses: list[Any]):
        self.responses = [httpx.Response(200, json=item) for item in responses]
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get(self, _url: str, *, params: Mapping[str, Any]) -> httpx.Response:
        self.calls.append(dict(params))
        return self.responses.pop(0)

    async def post(self, _url: str, *, data: Mapping[str, Any]) -> httpx.Response:
        return await self.get(_url, params=data)


def _services(*clients: _Client) -> LocalDatabaseServices:
    queue = iter(clients)
    return LocalDatabaseServices(
        client_factory=lambda: next(queue),
        ingestion_config=SnapshotIngestionConfig(max_attempts=1, request_delay_seconds=0, fetch_layer_metadata=False),
    )


def _base_parcels(database: Path) -> list[dict[str, Any]]:
    features = [_source(1, 0, EDITED_AT - 10 * DAY_MS), _source(2, 20), _source(3, 40)]
    built = _services(_Client([{"objectIds": [1, 2, 3]}, {"features": features}])).build(database)
    LocalDatabaseServices().activate(database)
    assert built["records"] == 3
    return features


def test_parcel_update_downloads_only_added_and_edited_parcels(tmp_path: Path):
    database = tmp_path / "parcels.sqlite"
    unchanged, _edited, _removed = _base_parcels(database)
    edited = _source(2, 25, EDITED_AT + DAY_MS)
    added = _source(4, 60, EDITED_AT + DAY_MS)
    client = _Client(
        [
            {"objectIds": [2, 4]},
            {"objectIds": [1, 2, 4]},
            {"features": [edited, added]},
            {"objectIds": [2, 4]},
        ]
    )

    result = _services(client).update(database)

    assert client.calls[0]["where"] == "LAST_EDITED_DATE >= timestamp '2026-11-04 23:00:52'"
    assert client.calls[2]["objectIds"] == "2,4"
    assert (result["copied_records"], result["downloaded_records"], result["records"]) == (1, 2, 3)
    assert (result["added_objectids"], result["removed_objectids"], result["changed_objectids"]) == ([4], [3], [2])
    assert result["content_hash"] == sha256_json([unchanged, edited, added])
    with SnapshotStore.open(database) as store:
        assert store.validate_snapshot(result["snapshot_id"])["ok"]
        assert store.parcels_in_bbox(60, 61, 0, 1, snapshot_id=result["snapshot_id"])[0]["objectid"] == 4
        assert store.active_snapshot_id() != result["snapshot_id"]


def test_parcel_update_without_mcgm_edits_rechecks_only_the_recent_edit_window(tmp_path: Path):
    database = tmp_path / "parcels.sqlite"
    features = _base_parcels(database)
    client = _Client(
        [{"objectIds": [2, 3]}, {"objectIds": [1, 2, 3]}, {"features": features[1:]}, {"objectIds": [2, 3]}]
    )

    result = _services(client).update(database)

    assert (result["copied_records"], result["downloaded_records"]) == (1, 2)
    assert result["changed_objectids"] == result["added_objectids"] == result["removed_objectids"] == []
    assert result["content_hash"] == sha256_json(features)
    assert len(client.calls) == 4


def test_parcel_update_refuses_a_result_mcgm_edited_mid_run(tmp_path: Path):
    database = tmp_path / "parcels.sqlite"
    _base_parcels(database)
    client = _Client([{"objectIds": []}, {"objectIds": [1, 2, 3]}, {"objectIds": [2]}])

    with pytest.raises(SnapshotIngestionError, match="run the update again"):
        _services(client).update(database)

    with SnapshotStore.open(database) as store:
        assert store.status()["snapshots"][-1]["state"] == "failed"


def test_parcel_update_needs_an_active_snapshot(tmp_path: Path):
    with pytest.raises(SnapshotIngestionError, match="full build first"):
        _services(_Client([])).update(tmp_path / "missing.sqlite")


def test_update_commands_are_reachable_from_the_cli():
    args = normalize_admin_args(["db", "parcels", "update", "--database", "x.sqlite"])
    assert parse_database_args(args)["command"] == "update"
    assert parse_intelligence_args(["intelligence", "update", "--database", "x.sqlite"])["command"] == "update"


def _parcel_snapshot(database: Path, parcels: list[dict[str, Any]]) -> int:
    with SnapshotStore.open(database) as store:
        snapshot_id = store.begin_snapshot(expected_count=len(parcels))
        store.set_inventory(snapshot_id, [item["objectid"] for item in parcels])
        store.insert_batch(snapshot_id, parcels)
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)
        return snapshot_id


def _planning_snapshot(database: Path, features: Mapping[int, list[dict[str, Any]]]) -> int:
    with PlanningSnapshotStore.open(database) as planning:
        snapshot_id = planning.begin_snapshot(source_url="fixture://planning")
        for spec in canonical_planning_specs():
            layer = features.get(spec.layer_id, [])
            planning.register_layer(
                snapshot_id,
                spec.layer_id,
                name=spec.name,
                geometry_type=spec.geometry_type,
                object_id_field=spec.object_id_field,
                expected_count=len(layer),
            )
            planning.set_layer_inventory(
                snapshot_id, spec.layer_id, [int(item["attributes"][spec.object_id_field]) for item in layer]
            )
            if layer:
                planning.insert_batch(snapshot_id, spec.layer_id, layer)
        planning.finalize(snapshot_id)
        planning.activate(snapshot_id)
        return snapshot_id


ZONE = {0: [_planning_feature(10, {"ZONE_CODE2": "R"}, _polygon(-5, -5, 1100, 15))]}
NEAR = _parcel(1, "100", 0)
NEIGHBOUR = _parcel(2, "101", 10)
FAR = _parcel(3, "102", 1000)


def _active_full_build(database: Path) -> int:
    built = PlotIntelligenceBuilder(database).build()
    with IntelligenceStore.open(database) as store:
        store.activate(built["build_id"])
    return int(built["build_id"])


def _hashes(database: Path, build_id: int) -> dict[tuple[str, str], str]:
    with IntelligenceStore.open(database) as store:
        return {
            (row[0], row[1]): row[2]
            for row in store.connection.execute(
                "SELECT village,cts_no,facts_hash FROM plot_intelligence WHERE build_id=?", (build_id,)
            )
        }


def _assert_update_matches_full_build(database: Path, update: Mapping[str, Any]) -> None:
    assert update["state"] == "ready"
    full = PlotIntelligenceBuilder(database).build()
    assert _hashes(database, update["build_id"]) == _hashes(database, full["build_id"])


def test_plot_update_recalculates_an_edited_plot_and_its_neighbours_only(tmp_path: Path):
    database = tmp_path / "intel.sqlite"
    _parcel_snapshot(database, [NEAR, NEIGHBOUR, FAR])
    _planning_snapshot(database, ZONE)
    base = _active_full_build(database)
    edited = _parcel(1, "100", 0)
    edited["geometry"] = edited["raw_feature"]["geometry"] = _polygon(0, 0, 10, 12)
    _parcel_snapshot(database, [edited, NEIGHBOUR, FAR])

    update = PlotIntelligenceBuilder(database).update()

    assert (update["reused_build_id"], update["copied_records"], update["recalculated"]) == (base, 1, 2)
    assert update["changed_parcel_objectids"] == [1]
    _assert_update_matches_full_build(database, update)


def test_plot_update_recalculates_only_plots_near_a_changed_planning_feature(tmp_path: Path):
    database = tmp_path / "intel.sqlite"
    _parcel_snapshot(database, [NEAR, NEIGHBOUR, FAR])
    _planning_snapshot(database, ZONE)
    _active_full_build(database)
    reservation = _planning_feature(20, {"NEW_RES_CODE_31": "R1", "DISCRIPTION": "Garden"}, _polygon(1000, 0, 1005, 10))
    _planning_snapshot(database, {**ZONE, 46: [reservation]})

    update = PlotIntelligenceBuilder(database).update()

    assert (update["copied_records"], update["recalculated"], update["changed_planning_features"]) == (2, 1, 1)
    _assert_update_matches_full_build(database, update)


def test_plot_update_refuses_when_there_is_nothing_to_update(tmp_path: Path):
    database = tmp_path / "intel.sqlite"
    _parcel_snapshot(database, [NEAR, FAR])
    _planning_snapshot(database, ZONE)
    with pytest.raises(RuntimeError, match="no active plot-intelligence build"):
        PlotIntelligenceBuilder(database).update()
    _active_full_build(database)
    with pytest.raises(RuntimeError, match="already matches"):
        PlotIntelligenceBuilder(database).update()
