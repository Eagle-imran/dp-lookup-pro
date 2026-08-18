"""Verified, pooled, retrying transport for idempotent ArcGIS operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
    httpx.WriteTimeout,
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must not be negative")


def arcgis_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer",
        "Origin": "https://agsmaps.mcgm.gov.in",
    }


class ArcGISClient:
    """Small async-client facade with bounded retry/backoff.

    ArcGIS GETs and form POSTs used here are read-only and therefore safe to
    retry. Client errors other than throttling/timeouts are returned directly.
    """

    def __init__(
        self,
        timeout_seconds: float,
        verify_tls: bool = True,
        retry_policy: Optional[RetryPolicy] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
        self._client = httpx.AsyncClient(
            headers=arcgis_headers(),
            limits=limits,
            timeout=timeout_seconds,
            verify=verify_tls,
            transport=transport,
        )
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep

    async def __aenter__(self) -> "ArcGISClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self._client.__aexit__(exc_type, exc, traceback)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _retry_delay(self, attempt: int, response: Optional[httpx.Response] = None) -> float:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                return min(self.retry_policy.max_delay_seconds, max(0.0, float(retry_after)))
            except ValueError:
                pass
        exponential = self.retry_policy.base_delay_seconds * float(2 ** max(0, attempt - 1))
        return min(self.retry_policy.max_delay_seconds, exponential)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exception: Optional[Exception] = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return response
                if attempt == self.retry_policy.max_attempts:
                    return response
                await self._sleep(self._retry_delay(attempt, response))
            except RETRYABLE_EXCEPTIONS as exc:
                last_exception = exc
                if attempt == self.retry_policy.max_attempts:
                    raise
                await self._sleep(self._retry_delay(attempt))
        if last_exception is not None:  # pragma: no cover - loop always returns/raises
            raise last_exception
        raise RuntimeError("retry loop ended without a response")  # pragma: no cover

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)


def create_arcgis_client(timeout_seconds: float, verify_tls: bool = True) -> ArcGISClient:
    """Create the shared transport; TLS verification is enabled by default."""
    return ArcGISClient(timeout_seconds, verify_tls=verify_tls)
