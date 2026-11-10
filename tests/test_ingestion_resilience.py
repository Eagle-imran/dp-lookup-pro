"""Failure semantics at the cadastral ingestion boundary."""

import asyncio

import httpx
import pytest

from dp_lookup.application.ingestion import (
    ParcelIdentityMismatchError,
    ParcelIngestionError,
    build_parcel_context,
    fetch_parcel_feature,
)


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FailingFallbackClient:
    calls = 0

    async def get(self, _url, *, params):
        self.calls += 1
        if self.calls == 1:
            return Response({"features": []})
        raise httpx.ReadTimeout("fallback timed out")


def test_fallback_transport_failure_is_not_misreported_as_not_found():
    with pytest.raises(ParcelIngestionError, match="fallback query"):
        asyncio.run(fetch_parcel_feature(FailingFallbackClient(), "WORLI", "733"))


class SequenceClient:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.params = []

    async def get(self, _url, *, params):
        self.params.append(params)
        return Response(next(self.payloads))


def _square(x0, y0=2_151_700.0, size=10.0):
    return [
        [x0, y0],
        [x0 + size, y0],
        [x0 + size, y0 + size],
        [x0, y0 + size],
        [x0, y0],
    ]


def _feature(cts_no, area, objectid, x0=8_106_500.0):
    return {
        "attributes": {
            "OBJECTID": objectid,
            "VILLAGE": "WORLI",
            "CTS_CS_NO": cts_no,
            "WARD": "G/S",
            "TYPE": "CTS",
            "AREA_APP_SQ_MTRS": area,
        },
        "geometry": {"rings": [_square(x0)]},
    }


def test_live_exact_multiple_records_merge_every_part_and_expose_conflict():
    first = _feature("733", 100.0, 2)
    second = _feature("733", 200.0, 1, x0=8_106_520.0)
    client = SequenceClient([{"features": [first, second]}])

    result = asyncio.run(fetch_parcel_feature(client, "WORLI", "733"))

    assert result is not None
    assert result["geometry"]["rings"] == second["geometry"]["rings"] + first["geometry"]["rings"]
    attrs = result["attributes"]
    assert attrs["_DP_QUERY_MATCH_COUNT"] == 2
    assert attrs["FEATURE_PART_COUNT"] == 2
    assert attrs["SOURCE_OBJECTIDS"] == [1, 2]
    assert attrs["_DP_AREA_CONFLICT_VALUES"] == [100.0, 200.0]
    assert attrs["AREA_APP_SQ_MTRS"] is None
    assert "_DP_UNMERGED_SOURCE_RECORDS" not in attrs
    assert client.params[0]["outFields"] == "OBJECTID,WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS,SHAPE.AREA"


def test_live_split_parcel_area_covers_all_parts():
    parts = [_feature("733", 250.0, 1), _feature("733", 250.0, 2, x0=8_106_520.0)]
    single = asyncio.run(fetch_parcel_feature(SequenceClient([{"features": parts[:1]}]), "WORLI", "733"))
    merged = asyncio.run(fetch_parcel_feature(SequenceClient([{"features": parts}]), "WORLI", "733"))

    single_parcel, _ = build_parcel_context(single, "WORLI", "733")
    merged_parcel, _ = build_parcel_context(merged, "WORLI", "733")

    single_boundary = single_parcel.area_assessment.calculated_boundary_area_sqm
    merged_boundary = merged_parcel.area_assessment.calculated_boundary_area_sqm
    assert merged_boundary == pytest.approx(2 * single_boundary, rel=1e-3)
    assert merged["attributes"]["AREA_APP_SQ_MTRS"] == 250.0


def test_live_duplicate_parts_are_counted_once():
    client = SequenceClient([{"features": [_feature("733", 100.0, 1), _feature("733", 100.0, 2)]}])

    result = asyncio.run(fetch_parcel_feature(client, "WORLI", "733"))

    assert len(result["geometry"]["rings"]) == 1
    assert result["attributes"]["_DP_DUPLICATE_GEOMETRY_COUNT"] == 1


def test_live_prefix_fallback_refuses_a_differently_numbered_plot():
    client = SequenceClient(
        [
            {"features": []},
            {"features": [_feature("733A", 100.0, 1), _feature("7330", 100.0, 2)]},
        ]
    )

    with pytest.raises(ParcelIdentityMismatchError, match="no plot numbered exactly '733'") as caught:
        asyncio.run(fetch_parcel_feature(client, "WORLI", "733"))

    assert caught.value.candidates == ("7330", "733A")
    assert isinstance(caught.value, ParcelIngestionError)


def test_live_prefix_fallback_accepts_a_spacing_only_difference():
    client = SequenceClient(
        [
            {"features": []},
            {"features": [_feature("733 ", 100.0, 1), _feature("733A", 90.0, 2)]},
        ]
    )

    result = asyncio.run(fetch_parcel_feature(client, "WORLI", "733"))

    assert result["attributes"]["_DP_QUERY_MATCH_TYPE"] == "prefix"
    assert result["attributes"]["_DP_QUERY_MATCH_COUNT"] == 1
    assert result["attributes"]["AREA_APP_SQ_MTRS"] == 100.0


def test_identity_mismatch_lists_a_bounded_number_of_candidates():
    error = ParcelIdentityMismatchError("WORLI", "7", [str(n) for n in range(70, 85)])
    assert "(+5 more)" in str(error)


def test_context_preserves_missing_recorded_area_and_uses_calculated_boundary():
    feature = _feature("733", None, 1)

    parcel, note = build_parcel_context(feature, "WORLI", "733")

    assert parcel.attrs["AREA_APP_SQ_MTRS"] is None
    assert parcel.area_assessment is not None
    assert parcel.area_assessment.recorded_area_sqm is None
    assert parcel.area_assessment.selected_area_basis == "calculated_boundary_area"
    assert parcel.area_sqm == parcel.area_assessment.calculated_boundary_area_sqm
    assert note is not None and "screening" in note
