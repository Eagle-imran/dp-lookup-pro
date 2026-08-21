"""Direct deterministic contracts for ArcGIS planning-layer intersections."""

import asyncio

import httpx

from dp_lookup.clients.planning_queries import build_spatial_planning_result, query_spatial_planning_layers
from dp_lookup.core.constants import (
    CRZ_LAYER_IDS,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
)
from dp_lookup.core.topology import arcgis_rings_to_geometry


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _ring(left, bottom, right, top):
    return [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]


def _feature(ring, **attributes):
    return {"attributes": attributes, "geometry": {"rings": [ring]}}


class PlanningClient:
    def __init__(self, layers, *, failing_layer=None, malformed_layer=None):
        self.layers = layers
        self.failing_layer = failing_layer
        self.malformed_layer = malformed_layer
        self.payloads = []

    async def post(self, url, *, data):
        layer_id = int(url.rsplit("/", 2)[-2])
        self.payloads.append(data)
        if layer_id == self.failing_layer:
            raise httpx.ReadTimeout("layer timeout")
        if layer_id == self.malformed_layer:
            return Response({"features": "not-a-list"})
        return Response({"features": self.layers.get(layer_id, [])})


def test_polygon_queries_union_overlapping_constraints_instead_of_double_counting():
    parcel = [_ring(0, 0, 10, 10)]
    layers = {
        LAYER_ZONE: [_feature(_ring(0, 0, 10, 10), ZONE_CODE2="R")],
        LAYER_RESERVATION: [
            _feature(
                _ring(0, 0, 6, 10),
                NEW_RES_CODE_31="ROS1.5",
                NEW_RES_MAINTYPE_31="ROS",
                DISCRIPTION="Garden",
            )
        ],
        LAYER_DESIGNATION: [
            _feature(
                _ring(4, 0, 10, 10),
                NEW_DES_CODE_31="EOS1.4",
                NEW_DES_MAINTYPE_31="EOS",
                DISCRIPTION="Open Space",
            )
        ],
        LAYER_MODIFICATION: [_feature(_ring(0, 0, 10, 10), APPROVAL_NO="MO-1", **{"LABEL to Display": "Modified"})],
        LAYER_METRO: [_feature(_ring(0, 0, 1, 1))],
        CRZ_LAYER_IDS[0]: [_feature(_ring(0, 0, 1, 1), CATEGORY="II")],
    }
    client = PlanningClient(layers)

    result = asyncio.run(query_spatial_planning_layers(client, parcel))

    assert result["primary_zone"] == "R"
    assert result["reservations"][0]["overlap_percent"] == 60.0
    assert result["designations"][0]["overlap_percent"] == 60.0
    assert result["modifications"][0]["approval_no"] == "MO-1"
    assert result["metro_buffer"].startswith("YES")
    assert result["crz_status"] == "YES (CRZ II)"
    assert result["encumbered_area_sqm"] == 100.0
    assert result["encumbered_percent"] == 100.0
    assert result["net_unencumbered_sqm"] == 0.0
    assert result["warnings"] == []
    assert result["successful_layers"] == result["queried_layers"]
    assert all(payload["geometry"] == "0.0,0.0,10.0,10.0" for payload in client.payloads)


def test_failed_and_malformed_layers_are_excluded_from_success_audit():
    client = PlanningClient(
        {LAYER_ZONE: [_feature(_ring(0, 0, 10, 10), ZONE_CODE2="R")]},
        failing_layer=LAYER_RESERVATION,
        malformed_layer=LAYER_DESIGNATION,
    )

    result = asyncio.run(query_spatial_planning_layers(client, [_ring(0, 0, 10, 10)]))

    assert result["primary_zone"] == "R"
    assert LAYER_RESERVATION not in result["successful_layers"]
    assert LAYER_DESIGNATION not in result["successful_layers"]
    assert any(f"Layer {LAYER_RESERVATION} query failed" in warning for warning in result["warnings"])
    assert any(f"Layer {LAYER_DESIGNATION} returned a malformed" in warning for warning in result["warnings"])


def test_final_codes_real_field_names_and_largest_crz_overlap_take_precedence():
    parcel = [_ring(0, 0, 10, 10)]
    layers = {
        LAYER_ZONE: [_feature(_ring(0, 0, 10, 10), ZONE_CODE2="R")],
        LAYER_RESERVATION: [
            _feature(
                _ring(0, 0, 10, 10),
                NEW_RES_CODE_31="OLD-R",
                FINAL_RES_CODE="FINAL-R",
                NEW_RES_MAINTYPE_31="OLD-TYPE",
                FINAL_RES_MAINTYPE="FINAL-TYPE",
            )
        ],
        LAYER_DESIGNATION: [
            _feature(
                _ring(0, 0, 10, 10),
                NEW_DES_CODE_31="EOS1.5",
                FINAL_DES_CODE="EOS2.8",
                NEW_DES_MAINTYPE_31="EOS-OLD",
                FINAL_DES_MAINTYPE="EOS-FINAL",
            )
        ],
        LAYER_MODIFICATION: [
            _feature(
                _ring(0, 0, 10, 10),
                APPROVAL_NO="MCP/3880",
                LABEL="Corrected Road Alignment",
                APPROVAL_DOCUMENTS="https://example.invalid/correction.pdf",
            )
        ],
        CRZ_LAYER_IDS[0]: [
            _feature(_ring(0, 0, 2, 10), CATEGORY="I"),
            _feature(_ring(2, 0, 10, 10), CATEGORY="II"),
        ],
    }

    result = asyncio.run(query_spatial_planning_layers(PlanningClient(layers), parcel))

    assert result["reservations"][0]["code"] == "FINAL-R"
    assert result["reservations"][0]["proposed_code"] == "OLD-R"
    assert result["designations"][0]["code"] == "EOS2.8"
    assert result["designations"][0]["proposed_code"] == "EOS1.5"
    assert result["modifications"][0]["details"] == "Corrected Road Alignment"
    assert result["modifications"][0]["document_link"].endswith("correction.pdf")
    assert result["crz_status"] == "YES (CRZ II)"
    assert len(result["crz_categories"]) == 2


def test_planning_square_metres_use_the_supplied_ground_area_scale():
    parcel_ring = _ring(0, 0, 10, 10)
    parcel = arcgis_rings_to_geometry([parcel_ring])
    layers = {
        LAYER_ZONE: [_feature(parcel_ring, ZONE_CODE2="R")],
        LAYER_RESERVATION: [_feature(_ring(0, 0, 5, 10), FINAL_RES_CODE="R1")],
        LAYER_MODIFICATION: [_feature(_ring(0, 0, 2, 10), APPROVAL_NO="M1")],
        CRZ_LAYER_IDS[0]: [_feature(_ring(0, 0, 1, 10), CATEGORY="II")],
    }

    result = build_spatial_planning_result(parcel, layers, [], area_scale=0.9)

    assert result["zones"][0]["overlap_sqm"] == 90.0
    assert result["reservations"][0]["overlap_sqm"] == 45.0
    assert result["modifications"][0]["overlap_sqm"] == 18.0
    assert result["crz_categories"][0]["overlap_sqm"] == 9.0
    assert result["encumbered_area_sqm"] == 45.0
    assert result["net_unencumbered_sqm"] == 45.0
