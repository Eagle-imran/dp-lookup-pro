"""Focused contracts for the extracted application stages."""

from pathlib import Path

from dp_lookup.application.contracts import NeighbourContext, ParcelContext, RoadContext
from dp_lookup.application.normalization import (
    normalize_planning_evidence,
    parse_neighbour_responses,
    parse_road_responses,
)
from dp_lookup.application.output_layout import build_output_paths


class JsonResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _parcel():
    rings = [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]
    return ParcelContext(
        village="MALABAR HILL",
        cts_no="1/6",
        attrs={"WARD": "D", "TYPE": "CTS"},
        rings=rings,
        wgs_rings=rings,
        area_sqm=100.0,
        area_source="approved record",
        latitude=19.0,
        longitude=72.0,
        cx=5.0,
        cy=5.0,
        mcx=5.0,
        mcy=5.0,
        xs=[0.0, 10.0],
        ys=[0.0, 10.0],
        window_radius=70.0,
    )


def test_road_placeholders_are_explicit_unknown_evidence():
    response = JsonResponse({"results": [{"attributes": {"ROAD_NAME": "Null"}}]})
    road = parse_road_responses([response], 1)
    assert road.name == "Unnamed / existing road"
    assert road.evidence_state == "unknown"
    assert road.warnings == []


def test_spatial_planning_failure_is_visible_when_identify_fallback_succeeds():
    identify = JsonResponse({"results": [{"layerId": 0, "attributes": {"Zone_Code2": "R"}}]})
    planning = normalize_planning_evidence(
        RuntimeError("spatial unavailable"),
        identify,
        100.0,
        _parcel().wgs_rings,
        [14, 1264, 1548],
    )
    assert planning.zone == "R"
    assert planning.status_badge.endswith("CLEAR (No Reservation)")
    assert planning.warnings
    assert planning.evidence["planning_constraints"]["state"] == "unknown"
    assert planning.evidence["zoning"]["method"] == "identify_fallback"


def test_output_layout_is_absolute_and_preserves_exact_slash_identity(tmp_path):
    alias = Path(tmp_path) / "reports" / ".." / "reports"
    paths = build_output_paths(str(alias), _parcel())
    assert Path(paths.bundle_folder).is_absolute()
    assert paths.bundle_folder.endswith("malabar_hill_cts_1~2f6")
    assert paths.register == str(Path(tmp_path) / "reports" / "dp-lookups.xlsx")


def test_stage_contracts_are_independently_constructible():
    road = RoadContext("Road A", "12 M")
    neighbours = NeighbourContext([{"cts_no": "2"}])
    assert road.name == "Road A"
    assert neighbours.plots[0]["cts_no"] == "2"


def test_malformed_probe_collections_fail_visibly_without_crashing():
    response = JsonResponse({"features": {"unexpected": True}, "results": "not-a-list"})
    road = parse_road_responses([response], 1)
    neighbours = parse_neighbour_responses([response], 1, "733", "WORLI")

    assert road.evidence_state == "failed"
    assert road.name == "None"
    assert road.warnings
    assert neighbours.plots == []
    assert neighbours.evidence_state == "failed"
    assert neighbours.warnings


def test_empty_layer_audit_is_not_confirmed_and_bad_percent_is_sanitized():
    planning = normalize_planning_evidence(
        {
            "primary_zone": "R",
            "zones": [{"zone": "R"}],
            "reservations": [{"code": "R1", "overlap_percent": "NaN"}],
            "designations": None,
            "modifications": "invalid",
            "encumbered_percent": float("inf"),
            "queried_layers": [],
            "successful_layers": [],
        },
        JsonResponse({"results": []}),
        100.0,
        _parcel().wgs_rings,
        [14, 1264, 1548],
    )

    assert planning.encumbered_percent == 0.0
    assert planning.reservations[0]["overlap_percent"] == 0.0
    assert planning.evidence["planning_constraints"]["state"] == "unknown"
    assert any("invalid" in warning for warning in planning.warnings)
