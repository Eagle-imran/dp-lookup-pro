"""Integration tests for the local adapter around experimental assemblies."""

import json
import xml.etree.ElementTree as ET

import ezdxf
import pytest

from dp_lookup.application import assembly_services
from dp_lookup.application.assembly_services import LocalAssemblyServices
from dp_lookup.spatial_store import SnapshotStore


def _parcel(objectid, cts, x, *, area=100.0):
    rings = [[[x, 2_150_000.0], [x + 10, 2_150_000.0], [x + 10, 2_150_010.0], [x, 2_150_010.0], [x, 2_150_000.0]]]
    attrs = {
        "OBJECTID": objectid,
        "VILLAGE": "WORLI",
        "CTS_CS_NO": cts,
        "WARD": "G/S",
        "AREA_APP_SQ_MTRS": area,
    }
    return {
        "objectid": objectid,
        "village": "WORLI",
        "cts_no": cts,
        "ward": "G/S",
        "area_app_sqm": area,
        "raw_attrs": attrs,
        "rings": rings,
    }


def _database(path):
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source="test", expected_count=3)
        store.insert_batch(
            snapshot_id,
            [
                _parcel(1, "733", 8_100_000.0),
                _parcel(2, "734", 8_100_010.0),
                _parcel(3, "900", 8_100_100.0),
            ],
        )
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)
        before = (store.active_snapshot_id(), store.count(snapshot_id))
    return before


def _planning(*_args, **_kwargs):
    return {
        "primary_zone": "R",
        "zones": [{"zone": "R", "overlap_percent": 100.0}],
        "reservations": [],
        "designations": [],
        "modifications": [],
        "metro_buffer": "NO",
        "crz_status": "NO",
        "encumbered_area_sqm": 0.0,
        "encumbered_percent": 0.0,
        "net_unencumbered_sqm": 180.0,
        "provenance": {"source": "local_snapshot", "snapshot_id": 7},
    }


def test_local_service_generates_traceable_combined_bundle_without_mutating_snapshot(tmp_path, monkeypatch):
    database = tmp_path / "parcels.sqlite"
    before = _database(database)
    monkeypatch.setattr(assembly_services, "_planning_result", _planning)
    output = tmp_path / "assembly"

    result = LocalAssemblyServices().analyze(
        database,
        [("WORLI", "733"), ("WORLI", "734")],
        output,
        0.25,
    )

    assert result["experimental"] is True
    assert result["assembly_status"] == "geometry_screening_ready"
    assert result["contiguous"] is True
    assert result["part_count"] == 2
    assert result["planning"]["primary_zone"] == "R"
    assert result["planning"]["provenance"]["source"] == "local_snapshot"
    assert [member["source_objectids"] for member in result["members"]] == [[1], [2]]
    assert all(len(member["geometry_sha256"]) == 64 for member in result["members"])
    assert result["source"]["parcel_snapshot_id"] == before[0]

    outputs = result["outputs"]
    assert set(outputs) == {"analysis_json", "assembly_geojson", "assembly_kml", "assembly_dxf"}
    analysis = json.loads((output / "assembly-analysis.json").read_text(encoding="utf-8"))
    geojson = json.loads((output / "assembly-boundary.geojson").read_text(encoding="utf-8"))
    assert analysis["assembly_status"] == "geometry_screening_ready"
    assert [feature["properties"]["feature_type"] for feature in geojson["features"]].count("SOURCE_PLOT") == 2
    assert ET.parse(output / "assembly-boundary.kml").getroot().tag.endswith("kml")
    modelspace = ezdxf.readfile(output / "assembly-boundary.dxf").modelspace()
    assert len(modelspace) > 0
    assert any(entity.dxf.layer == "C-ADJN-PLOTS" for entity in modelspace)

    with SnapshotStore.open(database) as store:
        assert (store.active_snapshot_id(), store.count()) == before


def test_local_service_reports_disconnected_selection(tmp_path, monkeypatch):
    database = tmp_path / "parcels.sqlite"
    _database(database)
    monkeypatch.setattr(assembly_services, "_planning_result", _planning)

    result = LocalAssemblyServices().analyze(
        database,
        [("WORLI", "733"), ("WORLI", "900")],
        tmp_path / "disconnected",
        0.25,
    )

    assert result["assembly_status"] == "not_contiguous"
    assert result["contiguous"] is False
    assert any(warning["code"] == "non_contiguous_selection" for warning in result["warnings"])


def test_local_service_keeps_geometry_result_when_planning_is_unavailable(tmp_path, monkeypatch):
    database = tmp_path / "parcels.sqlite"
    _database(database)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("planning snapshot missing")

    monkeypatch.setattr(assembly_services, "_planning_result", unavailable)
    result = LocalAssemblyServices().analyze(
        database,
        [("WORLI", "733"), ("WORLI", "734")],
        tmp_path / "without-planning",
        0.25,
    )
    assert result["planning"]["status"] == "unavailable"
    assert any(warning["code"] == "planning_analysis_unavailable" for warning in result["warnings"])


def test_local_service_rejects_missing_database_or_identity(tmp_path, monkeypatch):
    service = LocalAssemblyServices()
    with pytest.raises(ValueError, match="does not exist"):
        service.analyze(tmp_path / "missing.sqlite", [("WORLI", "733"), ("WORLI", "734")], None, 0.25)

    database = tmp_path / "parcels.sqlite"
    _database(database)
    monkeypatch.setattr(assembly_services, "_planning_result", _planning)
    with pytest.raises(ValueError, match="absent from active parcel snapshot"):
        service.analyze(database, [("WORLI", "733"), ("WORLI", "999")], None, 0.25)
