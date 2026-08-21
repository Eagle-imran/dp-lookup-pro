"""Contracts for local plot intelligence, road analysis and CLI workflows."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dp_lookup.application.ingestion import build_parcel_context
from dp_lookup.application.intelligence_builder import PlotIntelligenceBuilder
from dp_lookup.application.intelligence_services import PlotIntelligenceServices
from dp_lookup.application.local_roads import LocalRoadProvider
from dp_lookup.application.planning_snapshot import canonical_planning_specs
from dp_lookup.authority import AuthorityManifest, AuthorityStore, SelectionPurpose, SourceType
from dp_lookup.clients.local_parcels import merge_local_features
from dp_lookup.intelligence import IntelligenceStateError, IntelligenceStore, PlotIntelligence
from dp_lookup.intelligence_cli import main as intelligence_main
from dp_lookup.intelligence_cli import parse_intelligence_args
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore


def _polygon(left: float, bottom: float, right: float, top: float):
    return {
        "rings": [
            [
                [left, bottom],
                [right, bottom],
                [right, top],
                [left, top],
                [left, bottom],
            ]
        ],
        "spatialReference": {"wkid": 102100},
    }


def _parcel(object_id: int, cts_no: str, left: float):
    attributes = {
        "OBJECTID": object_id,
        "VILLAGE": "WORLI",
        "CTS_CS_NO": cts_no,
        "WARD": "G/S",
        "TYPE": "CTS",
        "AREA_APP_SQ_MTRS": 100.0,
        "SHAPE.AREA": 100.0,
    }
    geometry = _polygon(left, 0, left + 10, 10)
    return {
        "objectid": object_id,
        "attributes": attributes,
        "geometry": geometry,
        "raw_feature": {"attributes": attributes, "geometry": geometry},
    }


def _planning_feature(object_id: int, attributes, geometry):
    return {"attributes": {"OBJECTID": object_id, **attributes}, "geometry": geometry}


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "intelligence.sqlite"
    with SnapshotStore.open(database) as parcels:
        snapshot_id = parcels.begin_snapshot(expected_count=2)
        parcels.set_inventory(snapshot_id, [1, 2])
        parcels.insert_batch(snapshot_id, [_parcel(1, "100", 0), _parcel(2, "101", 10)])
        parcels.finalize_snapshot(snapshot_id)
        parcels.activate(snapshot_id)

    features = {
        0: [_planning_feature(10, {"ZONE_CODE2": "R"}, _polygon(-5, -5, 25, 15))],
        46: [
            _planning_feature(
                20,
                {"NEW_RES_CODE_31": "R1", "DISCRIPTION": "Garden"},
                _polygon(0, 0, 5, 10),
            )
        ],
        193: [
            {
                "attributes": {"OBJECTID_1": 30, "ROAD_NAME": "Test Road", "WIDTH": 18.3},
                "geometry": {"paths": [[[-5, 0], [25, 0]]]},
            }
        ],
    }
    with PlanningSnapshotStore.open(database) as planning:
        snapshot_id = planning.begin_snapshot(source_url="fixture://planning")
        for spec in canonical_planning_specs():
            layer_features = features.get(spec.layer_id, [])
            planning.register_layer(
                snapshot_id,
                spec.layer_id,
                name=spec.name,
                geometry_type=spec.geometry_type,
                object_id_field=spec.object_id_field,
                expected_count=len(layer_features),
            )
            object_ids = [int(item["attributes"][spec.object_id_field]) for item in layer_features]
            planning.set_layer_inventory(snapshot_id, spec.layer_id, object_ids)
            if layer_features:
                planning.insert_batch(snapshot_id, spec.layer_id, layer_features)
        planning.finalize(snapshot_id)
        planning.activate(snapshot_id)
    return database


def test_intelligence_store_requires_complete_full_build_before_activation(tmp_path: Path):
    with IntelligenceStore.open(tmp_path / "store.sqlite") as store:
        build_id = store.begin_build(
            parcel_snapshot_id=1,
            planning_snapshot_id=2,
            algorithm_version="fixture",
            expected_count=1,
            source_fingerprint="hash",
        )
        with pytest.raises(IntelligenceStateError, match="verified"):
            store.activate(build_id)
        plot = PlotIntelligence(
            "WORLI", "1", "G/S", (10,), 1, 100.0, "approved", 100.0, 5.0, 5.0, "R", facts_hash="facts"
        )
        store.upsert(build_id, plot)
        assert store.finalize(build_id).state == "ready"
        assert store.activate(build_id).state == "active"
        assert store.get("worli", "1")["facts_hash"] == "facts"


def test_local_road_provider_uses_pinned_snapshot_and_source_ids(tmp_path: Path):
    database = _database(tmp_path)
    with SnapshotStore.open(database) as parcels, PlanningSnapshotStore.open(database) as planning:
        feature = merge_local_features(parcels.lookup("WORLI", "100"))
        assert feature is not None
        feature["attributes"]["_DP_SNAPSHOT_ID"] = parcels.active_snapshot_id()
        parcel, _ = build_parcel_context(feature, "WORLI", "100")
        road = LocalRoadProvider(planning, snapshot_id=planning.active_snapshot_id())(parcel)
    assert road is not None
    assert road.name == "Test Road"
    assert road.width == "18.3"
    assert road.distance_m == 0.0
    assert road.source_layer_ids == [193]
    assert road.source_object_ids == [30]


def test_citywide_build_analyze_search_compare_and_update_check(tmp_path: Path):
    database = _database(tmp_path)
    outcome = PlotIntelligenceBuilder(database).build(workers=1)
    assert outcome["state"] == "ready"
    assert outcome["scope"] == "full"
    assert outcome["selected_count"] == 2
    assert outcome["validation"]["ok"] is True

    services = PlotIntelligenceServices()
    activated = services.activate(database)
    assert activated["state"] == "active"
    dossier = services.analyze(database, "WORLI", "100")
    assert dossier["planning"]["primary_zone"] == "R"
    assert dossier["planning"]["encumbered_percent"] == 50.0
    assert dossier["planning"]["net_unencumbered_sqm"] == 50.0
    assert dossier["access"]["road_name"] == "Test Road"
    assert dossier["provenance"]["source_refs"]

    search = services.search(database, min_area_sqm=90, zone="R", reservations=True)
    assert [item["cts_no"] for item in search["results"]] == ["100"]
    comparison = services.compare(database, [("WORLI", "100"), ("WORLI", "101")])
    assert len(comparison["records"]) == 2
    assert comparison["missing"] == []
    check = services.check(database, refresh_days=9999)
    assert check["source_alignment"] is True
    assert check["ready_for_operational_use"] is True


def test_sample_build_is_queryable_but_cannot_be_activated(tmp_path: Path):
    database = _database(tmp_path)
    outcome = PlotIntelligenceBuilder(database).build(limit=1, include_neighbours=False, workers=1)
    assert outcome["scope"] == "sample"
    with IntelligenceStore.open(database) as store:
        assert store.get("WORLI", "100", build_id=outcome["build_id"]) is not None
        with pytest.raises(IntelligenceStateError, match="sample"):
            store.activate(outcome["build_id"])


def test_intelligence_uses_only_active_authority_and_fingerprint_tracks_registry(tmp_path: Path):
    database = _database(tmp_path)
    document = tmp_path / "property-card.pdf"
    document.write_bytes(b"property card")
    with AuthorityStore.open(database) as authority:
        record = authority.register(
            AuthorityManifest(
                village="WORLI",
                cts_no="100",
                source_type=SourceType.PROPERTY_CARD,
                source_uri=str(document),
                source_sha256=hashlib.sha256(document.read_bytes()).hexdigest(),
                issuer="City Survey Office",
                recorded_area_sqm=140.0,
            )
        )
        authority.verify(record.record_id, actor="reviewer")
        authority.activate(record.record_id, SelectionPurpose.AREA, actor="reviewer", reason="accepted area")

    first = PlotIntelligenceBuilder(database).build(limit=1, include_neighbours=False, workers=1)
    assert first["authority_registry_revision"] is not None
    with IntelligenceStore.open(database) as intelligence:
        result = intelligence.get("WORLI", "100", build_id=first["build_id"])
    assert result is not None
    assert result["area_sqm"] == 140.0
    assert result["evidence_summary"]["authority_resolution"]["active_record_ids"] == [record.record_id]
    dossier = PlotIntelligenceServices().analyze(database, "WORLI", "100", build_id=first["build_id"])
    assert dossier["plot_identity"]["authority_resolution"]["status"] == "applied"

    with AuthorityStore.open(database, create=False) as authority:
        authority.withdraw(record.record_id, actor="reviewer", reason="test withdrawal")
    second = PlotIntelligenceBuilder(database).build(limit=1, include_neighbours=False, workers=1)
    assert second["source_fingerprint"] != first["source_fingerprint"]
    with IntelligenceStore.open(database) as intelligence:
        baseline = intelligence.get("WORLI", "100", build_id=second["build_id"])
    assert baseline is not None
    assert baseline["area_sqm"] == 100.0


def test_intelligence_cli_contract_is_explicit_and_small():
    parsed = parse_intelligence_args(
        [
            "intelligence",
            "search",
            "--database",
            "plots.sqlite",
            "--min-area=500",
            "--has-reservation",
            "no",
            "--json",
        ]
    )
    assert parsed["database"] == Path("plots.sqlite")
    assert parsed["min_area_sqm"] == 500.0
    assert parsed["reservations"] is False
    with pytest.raises(ValueError, match="VILLAGE:CTS"):
        parse_intelligence_args(["intelligence", "compare", "WORLI", "COLABA:1", "--database", "plots.sqlite"])


class _FakeIntelligenceServices:
    def __init__(self):
        self.calls = []

    def _result(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return {"operation": name}

    def build(self, *args, **kwargs):
        return self._result("build", *args, **kwargs)

    def status(self, *args, **kwargs):
        return self._result("status", *args, **kwargs)

    def verify(self, *args, **kwargs):
        return self._result("verify", *args, **kwargs)

    def activate(self, *args, **kwargs):
        return self._result("activate", *args, **kwargs)

    def analyze(self, *args, **kwargs):
        return self._result("analyze", *args, **kwargs)

    def search(self, *args, **kwargs):
        return self._result("search", *args, **kwargs)

    def compare(self, *args, **kwargs):
        return self._result("compare", *args, **kwargs)

    def check(self, *args, **kwargs):
        return self._result("check", *args, **kwargs)


@pytest.mark.parametrize(
    "args,operation",
    [
        (["build", "--limit", "2", "--workers", "1", "--no-neighbours"], "build"),
        (["status"], "status"),
        (["verify", "--build-id", "3"], "verify"),
        (["activate", "--build-id", "3"], "activate"),
        (["analyze", "WORLI", "100", "--build-id", "3"], "analyze"),
        (["search", "--zone", "R", "--road", "Marg"], "search"),
        (["compare", "WORLI:100", "WORLI:101"], "compare"),
        (["check", "--refresh-days", "90"], "check"),
    ],
)
def test_intelligence_cli_dispatches_every_command(args, operation, capsys):
    services = _FakeIntelligenceServices()
    argv = ["intelligence", *args, "--database", "plots.sqlite", "--json"]
    assert intelligence_main(argv, services=services) == 0
    assert services.calls[0][0] == operation
    assert f'"operation": "{operation}"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv,message",
    [
        (["intelligence", "search"], "--database"),
        (["intelligence", "search", "--database", "x", "--limit", "bad"], "integer"),
        (["intelligence", "search", "--database", "x", "--min-area", "bad"], "number"),
        (["intelligence", "search", "--database", "x", "--has-reservation", "maybe"], "yes or no"),
        (["intelligence", "unknown", "--database", "x"], "expected intelligence command"),
    ],
)
def test_intelligence_cli_rejects_bad_input_without_tracebacks(argv, message, capsys):
    assert intelligence_main(argv, services=_FakeIntelligenceServices()) == 1
    assert message in capsys.readouterr().out


def test_intelligence_cli_human_views_are_compact(capsys):
    class HumanServices(_FakeIntelligenceServices):
        def analyze(self, *args, **kwargs):
            del args, kwargs
            return {
                "plot_identity": {"village": "WORLI", "cts_no": "1", "ward": "G/S", "area_sqm": 100.0},
                "planning": {
                    "primary_zone": "R",
                    "reservations": [],
                    "designations": [],
                    "net_unencumbered_sqm": 100.0,
                },
                "access": {"road_name": "Main Road", "road_width": "18.3", "distance_m": 0.0},
                "quality": {"confidence": "verified", "facts_hash": "abc"},
            }

        def search(self, *args, **kwargs):
            del args, kwargs
            return {
                "build_id": 4,
                "count": 1,
                "results": [
                    {
                        "village": "WORLI",
                        "cts_no": "1",
                        "area_sqm": 100.0,
                        "primary_zone": "R",
                        "confidence": "verified",
                    }
                ],
            }

    services = HumanServices()
    database = ["--database", "plots.sqlite"]
    assert intelligence_main(["intelligence", "analyze", "WORLI", "1", *database], services=services) == 0
    assert "Net unencumbered: 100.00 m²" in capsys.readouterr().out
    assert intelligence_main(["intelligence", "search", *database], services=services) == 0
    assert "1 plot(s) found" in capsys.readouterr().out


def test_store_resume_issue_filters_compare_and_failure_guards(tmp_path: Path):
    database = tmp_path / "store-branches.sqlite"
    with IntelligenceStore.open(database) as store:
        build_id = store.begin_build(
            parcel_snapshot_id=1,
            planning_snapshot_id=2,
            algorithm_version="fixture",
            expected_count=2,
            source_fingerprint="hash",
        )
        assert (
            store.begin_build(
                parcel_snapshot_id=1,
                planning_snapshot_id=2,
                algorithm_version="fixture",
                expected_count=2,
                source_fingerprint="hash",
            )
            == build_id
        )
        first = PlotIntelligence(
            "WORLI",
            "1",
            "G/S",
            (1,),
            1,
            200.0,
            "approved",
            200.0,
            0.0,
            0.0,
            "R",
            reservations=({"code": "R1"},),
            encumbered_percent=10.0,
            road_name="Main Road",
            facts_hash="one",
        )
        second = PlotIntelligence(
            "COLABA",
            "2",
            "A",
            (2,),
            1,
            100.0,
            "approved",
            100.0,
            0.0,
            0.0,
            "C",
            facts_hash="two",
        )
        store.upsert(build_id, first)
        store.record_issue(build_id, "COLABA", "2", "temporary")
        assert store.verify(build_id)["issue_count"] == 1
        store.upsert(build_id, second)
        assert store.finalize(build_id).state == "ready"
        store.activate(build_id)
        assert [item["cts_no"] for item in store.search(village="WORLI", reservations=True)] == ["1"]
        assert [item["cts_no"] for item in store.search(zone="C", designations=False)] == ["2"]
        assert [item["cts_no"] for item in store.search(road_name="Main", max_encumbered_percent=15)] == ["1"]
        comparison = store.compare([("WORLI", "1"), ("COLABA", "missing")])
        assert len(comparison["records"]) == 1
        assert comparison["missing"] == [{"village": "COLABA", "cts_no": "missing"}]
        with pytest.raises(ValueError, match="between 2 and 20"):
            store.compare([("WORLI", "1")])
        with pytest.raises(ValueError, match="limit"):
            store.search(limit=0)

        failed_id = store.begin_build(
            parcel_snapshot_id=1,
            planning_snapshot_id=2,
            algorithm_version="failed",
            expected_count=1,
            source_fingerprint="failed",
        )
        assert store.fail(failed_id, "fixture").state == "failed"
        with pytest.raises(IntelligenceStateError, match="not building"):
            store.record_issue(failed_id, "WORLI", "9", "late")


def test_services_report_absent_sources_and_builds_cleanly(tmp_path: Path):
    database = tmp_path / "empty.sqlite"
    services = PlotIntelligenceServices()
    check = services.check(database, refresh_days=10)
    assert check["refresh_due"] is True
    assert check["ready_for_operational_use"] is False
    assert len(check["recommended_actions"]) == 2
    with pytest.raises(IntelligenceStateError, match="no plot-intelligence builds"):
        services.verify(database)
    with pytest.raises(IntelligenceStateError, match="no ready"):
        services.activate(database)
