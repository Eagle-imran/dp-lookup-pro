"""Retry classification and bounded backoff contracts."""

import asyncio

import httpx

from dp_lookup.clients.transport import ArcGISClient, RetryPolicy, arcgis_headers


def test_headers_preserve_the_public_arcgis_origin_contract():
    headers = arcgis_headers()
    assert headers["Origin"] == "https://agsmaps.mcgm.gov.in"
    assert "Development_Plan_2034" in headers["Referer"]
    assert headers["User-Agent"]


def test_retries_transient_statuses_then_returns_success():
    attempts = []
    delays = []

    async def handler(request):
        attempts.append(request)
        status = 503 if len(attempts) < 3 else 200
        return httpx.Response(status, json={"ok": True})

    async def sleep(delay):
        delays.append(delay)

    async def run():
        client = ArcGISClient(
            2.0,
            transport=httpx.MockTransport(handler),
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.1),
            sleep=sleep,
        )
        async with client:
            return await client.get("https://example.invalid/query")

    response = asyncio.run(run())
    assert response.status_code == 200
    assert len(attempts) == 3
    assert delays == [0.1, 0.2]


def test_retry_after_is_respected_but_capped():
    attempts = 0
    delays = []

    async def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429 if attempts == 1 else 200, headers={"Retry-After": "99"})

    async def sleep(delay):
        delays.append(delay)

    async def run():
        client = ArcGISClient(
            2.0,
            transport=httpx.MockTransport(handler),
            retry_policy=RetryPolicy(max_attempts=2, max_delay_seconds=1.5),
            sleep=sleep,
        )
        async with client:
            return await client.post("https://example.invalid/query", data={})

    assert asyncio.run(run()).status_code == 200
    assert delays == [1.5]


def test_non_retryable_client_error_returns_immediately():
    attempts = 0

    async def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    async def run():
        client = ArcGISClient(2.0, transport=httpx.MockTransport(handler))
        async with client:
            return await client.get("https://example.invalid/query")

    assert asyncio.run(run()).status_code == 400
    assert attempts == 1
