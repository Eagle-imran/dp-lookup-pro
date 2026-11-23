"""A planning feature that cannot be checked must be reported, never silently skipped."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_stage_latency_regression import _dependencies, _parcel

from dp_lookup.application.lookup_service import lookup_plot_pro
from dp_lookup.application.normalization import normalize_planning_evidence
from dp_lookup.clients import planning_queries as planning_queries_module
from dp_lookup.clients.planning_queries import build_spatial_planning_result
from dp_lookup.core.constants import (
    CRZ_LAYER_IDS,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
)
from dp_lookup.core.topology import arcgis_rings_to_geometry

PLOT_RING = [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]
HALF_PLOT_RING = [[50, 0], [150, 0], [150, 100], [50, 100], [50, 0]]
PLOT = arcgis_rings_to_geometry([PLOT_RING])
WGS_RINGS = [[[72.8, 19.0], [72.801, 19.0], [72.801, 19.001], [72.8, 19.0]]]


class JsonResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


NO_IDENTIFY_HITS = JsonResponse({"results": []})


def _feature(ring: Any, **attributes: Any) -> dict[str, Any]:
    return {"attributes": {"OBJECTID": 1, **attributes}, "geometry": {"rings": [ring]}}


BROKEN_FEATURES: dict[str, Any] = {
    "missing coordinate": _feature([[50, 0], [150, 0], [150, None], [50, 100], [50, 0]], OBJECTID=7),
    "text coordinate": _feature([["a", 0], [150, 0], [150, 100], [50, 0]], OBJECTID=7),
    "no rings": {"attributes": {"OBJECTID": 7}, "geometry": {}},
    "empty shape": _feature([[50, 0], [150]], OBJECTID=7),
    "attributes not an object": {"attributes": "junk", "geometry": {"rings": [HALF_PLOT_RING]}},
    "feature not an object": ["junk"],
}

GOOD_FEATURE_FOUND = {
    LAYER_ZONE: lambda result: result["primary_zone"] == "R",
    LAYER_RESERVATION: lambda result: len(result["reservations"]) == 1,
    LAYER_DESIGNATION: lambda result: len(result["designations"]) == 1,
    LAYER_MODIFICATION: lambda result: len(result["modifications"]) == 1,
    LAYER_METRO: lambda result: result["metro_buffer"].startswith("YES"),
    **{layer_id: (lambda result: result["crz_status"].startswith("YES")) for layer_id in CRZ_LAYER_IDS},
}


@pytest.mark.parametrize("layer_id", list(GOOD_FEATURE_FOUND))
@pytest.mark.parametrize("broken", list(BROKEN_FEATURES.values()), ids=list(BROKEN_FEATURES))
def test_unusable_feature_is_reported_and_its_layer_is_not_counted_as_checked(layer_id: int, broken: Any) -> None:
    good = _feature(HALF_PLOT_RING, ZONE_CODE2="R", CATEGORY="CRZ II", FINAL_RES_CODE="RG", APPROVAL_NO="EP-1")

    result = build_spatial_planning_result(PLOT, {layer_id: [broken, good]}, [])

    layer_warnings = [warning for warning in result["warnings"] if warning.startswith(f"Layer {layer_id} ")]
    assert len(layer_warnings) == 1
    assert "could not be checked against the plot" in layer_warnings[0]
    assert layer_id not in result["successful_layers"]
    assert GOOD_FEATURE_FOUND[layer_id](result)


def test_warning_names_the_feature_and_leaves_the_callers_list_alone() -> None:
    upstream: list[str] = []

    result = build_spatial_planning_result(
        PLOT, {LAYER_RESERVATION: [BROKEN_FEATURES["missing coordinate"], ["junk"]]}, upstream
    )

    assert upstream == []
    assert [warning.split(" could not")[0] for warning in result["warnings"]] == [
        "Layer 46 OBJECTID 7",
        "Layer 46 #2",
    ]


def test_clean_features_produce_no_warnings() -> None:
    layers = {layer_id: [_feature(HALF_PLOT_RING, ZONE_CODE2="R")] for layer_id in GOOD_FEATURE_FOUND}

    result = build_spatial_planning_result(PLOT, layers, [])

    assert result["warnings"] == []
    assert sorted(result["successful_layers"]) == sorted(result["queried_layers"])


def test_programming_errors_are_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_converter(_rings: Any) -> Any:
        raise KeyError("bug in the converter")

    monkeypatch.setattr(planning_queries_module, "arcgis_rings_to_geometry", broken_converter)

    with pytest.raises(KeyError, match="bug in the converter"):
        build_spatial_planning_result(PLOT, {LAYER_RESERVATION: [_feature(HALF_PLOT_RING)]}, [])


def test_unchecked_reservation_turns_a_clear_result_into_unverified() -> None:
    spatial = build_spatial_planning_result(
        PLOT,
        {LAYER_ZONE: [_feature(PLOT_RING, ZONE_CODE2="R")], LAYER_RESERVATION: [BROKEN_FEATURES["missing coordinate"]]},
        [],
    )

    planning = normalize_planning_evidence(spatial, NO_IDENTIFY_HITS, 100.0, WGS_RINGS, CRZ_LAYER_IDS)

    assert planning.reservations == []
    assert "UNVERIFIED" in planning.status_badge
    assert "CLEAR" not in planning.status_badge
    assert planning.evidence["planning_constraints"]["state"] == "unknown"


def test_unchecked_metro_feature_keeps_the_reservation_badge_but_not_confirmed() -> None:
    spatial = build_spatial_planning_result(
        PLOT,
        {LAYER_ZONE: [_feature(PLOT_RING, ZONE_CODE2="R")], LAYER_METRO: [BROKEN_FEATURES["missing coordinate"]]},
        [],
    )

    planning = normalize_planning_evidence(spatial, NO_IDENTIFY_HITS, 100.0, WGS_RINGS, CRZ_LAYER_IDS)

    assert "CLEAR" in planning.status_badge
    assert planning.evidence["planning_constraints"]["state"] == "unknown"
    assert any(warning.startswith("Layer 1550 ") for warning in planning.warnings)


def test_lookup_with_an_unchecked_reservation_is_incomplete_and_unverified(tmp_path: Path) -> None:
    ring = _parcel()["geometry"]["rings"][0]
    broken = [list(point) for point in ring]
    broken[2][1] = None

    async def planning_query(_client: Any, rings: Any) -> dict[str, Any]:
        layers = {
            LAYER_ZONE: [_feature(ring, ZONE_CODE2="R")],
            LAYER_RESERVATION: [_feature(broken, FINAL_RES_CODE="RG", OBJECTID=7)],
        }
        return build_spatial_planning_result(arcgis_rings_to_geometry(rings), layers, [])

    dependencies = replace(_dependencies(0.0), spatial_planning_query=planning_query)

    result = asyncio.run(
        lookup_plot_pro("WORLI", "733", output_dir=str(tmp_path), use_cache=False, dependencies=dependencies)
    )

    assert result["metadata"]["complete"] is False
    assert "UNVERIFIED" in result["planning_remarks"]["status_badge"]
    assert any("Layer 46 OBJECTID 7" in warning for warning in result["metadata"]["warnings"])
