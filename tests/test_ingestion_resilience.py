"""Failure semantics at the cadastral ingestion boundary."""

import asyncio

import httpx
import pytest

from dp_lookup.application.ingestion import ParcelIngestionError, build_parcel_context, fetch_parcel_feature


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


def _feature(cts_no, area, objectid):
    return {
        "attributes": {
            "OBJECTID": objectid,
            "VILLAGE": "WORLI",
            "CTS_CS_NO": cts_no,
            "WARD": "G/S",
            "TYPE": "CTS",
            "AREA_APP_SQ_MTRS": area,
        },
        "geometry": {
            "rings": [
                [
                    [8_106_500.0, 2_151_700.0],
                    [8_106_510.0, 2_151_700.0],
                    [8_106_510.0, 2_151_710.0],
                    [8_106_500.0, 2_151_710.0],
                    [8_106_500.0, 2_151_700.0],
                ]
            ]
        },
    }


def test_live_exact_multiple_records_preserve_first_match_and_expose_conflict():
    first = _feature("733", 100.0, 1)
    second = _feature("733", 200.0, 2)
    client = SequenceClient([{"features": [first, second]}])

    result = asyncio.run(fetch_parcel_feature(client, "WORLI", "733"))

    assert result is not None
    assert result["geometry"] == first["geometry"]
    assert result["attributes"]["_DP_QUERY_MATCH_COUNT"] == 2
    assert result["attributes"]["_DP_AREA_CONFLICT_VALUES"] == [100.0, 200.0]
    assert result["attributes"]["_DP_UNMERGED_SOURCE_RECORDS"] is True
    assert client.params[0]["outFields"] == "WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS,SHAPE.AREA"


def test_live_prefix_fallback_is_marked_ambiguous():
    client = SequenceClient(
        [
            {"features": []},
            {"features": [_feature("733A", 100.0, 1), _feature("733B", 100.0, 2)]},
        ]
    )

    result = asyncio.run(fetch_parcel_feature(client, "WORLI", "733"))

    assert result is not None
    assert result["attributes"]["_DP_QUERY_MATCH_TYPE"] == "prefix"
    assert result["attributes"]["_DP_IDENTITY_AMBIGUOUS"] is True


def test_context_preserves_missing_recorded_area_and_uses_calculated_boundary():
    feature = _feature("733", None, 1)

    parcel, note = build_parcel_context(feature, "WORLI", "733")

    assert parcel.attrs["AREA_APP_SQ_MTRS"] is None
    assert parcel.area_assessment is not None
    assert parcel.area_assessment.recorded_area_sqm is None
    assert parcel.area_assessment.selected_area_basis == "calculated_boundary_area"
    assert parcel.area_sqm == parcel.area_assessment.calculated_boundary_area_sqm
    assert note is not None and "screening" in note
