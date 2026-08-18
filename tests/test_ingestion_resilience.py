"""Failure semantics at the cadastral ingestion boundary."""

import asyncio

import httpx
import pytest

from dp_lookup.application.ingestion import ParcelIngestionError, fetch_parcel_feature


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
