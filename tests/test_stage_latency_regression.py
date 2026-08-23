"""Offline stage-latency regression harness for the complete lookup pipeline.

The fake adapters retain the real dependency ports and add small, repeatable
delays representative of a slow local/network boundary.  This is deliberately
not a production performance benchmark: it detects stage explosions and
missing parallelism without depending on MCGM availability.
"""

from __future__ import annotations

import asyncio
import io
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES
from dp_lookup.application.lookup_service import lookup_plot_pro


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(stream, format="PNG")
    return stream.getvalue()


class _Response:
    status_code = 200

    def __init__(self, payload: Optional[Dict[str, Any]] = None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content
        self.headers = {"content-type": "image/png" if content else "application/json"}

    def json(self) -> Dict[str, Any]:
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class _DelayedClient:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    async def __aenter__(self) -> "_DelayedClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False

    async def get(self, url: str, **_: Any) -> _Response:
        await asyncio.sleep(self.delay_s)
        if url.endswith("/export"):
            return _Response(content=_png_bytes())
        if "/tile/" in url:
            return _Response(content=_png_bytes())
        raise AssertionError(f"unexpected GET in latency harness: {url}")

    async def post(self, url: str, *, data: Optional[Dict[str, Any]] = None) -> _Response:
        await asyncio.sleep(self.delay_s)
        if not url.endswith("/identify"):
            raise AssertionError(f"unexpected POST in latency harness: {url}")
        layers = (data or {}).get("layers", "")
        if layers.startswith("visible:193") or layers == "visible:13":
            return _Response({"results": []})
        return _Response({"results": [{"layerId": 0, "attributes": {"Zone_Code2": "R"}}]})


def _parcel() -> Dict[str, Any]:
    return {
        "attributes": {
            "WARD": "G/S",
            "TYPE": "CTS",
            "VILLAGE": "WORLI",
            "CTS_CS_NO": "733",
            "AREA_APP_SQ_MTRS": 100.0,
        },
        "geometry": {
            "rings": [[[8106500.0, 2151700.0], [8106510.0, 2151700.0],
                        [8106510.0, 2151710.0], [8106500.0, 2151710.0],
                        [8106500.0, 2151700.0]]]
        },
    }


def _dependencies(delay_s: float):
    def client_factory(_timeout: float, verify_tls: bool = True) -> _DelayedClient:
        del verify_tls
        return _DelayedClient(delay_s)

    async def parcel_fetcher(_client: Any, _village: str, _cts: str) -> Dict[str, Any]:
        await asyncio.sleep(delay_s)
        return _parcel()

    async def planning_query(_client: Any, _rings: Any) -> Dict[str, Any]:
        await asyncio.sleep(delay_s)
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
            "net_unencumbered_sqm": 100.0,
            "net_unencumbered_percent": 100.0,
            "provenance": {"source": "latency_harness"},
        }

    async def tile_fetcher(client: Any, zoom: int, ytile: int, xtile: int, tile_dir: str = "") -> bytes:
        del zoom, ytile, xtile, tile_dir
        response = await client.get("/tile/fake")
        return response.content

    # Keep synchronous writers/renderers inside the same stage so their cost is
    # represented without invoking real PDF/CAD/image work.
    def vector_writer(_rings: Any, _properties: Any, path: str, **_: Any) -> None:
        time.sleep(delay_s)
        Path(path).write_text("vector", encoding="utf-8")

    def pdf_writer(path: str, *_args: Any, **_kwargs: Any) -> None:
        time.sleep(delay_s)
        Path(path).write_bytes(b"pdf")

    def excel_writer(*_args: Any, **kwargs: Any) -> None:
        time.sleep(delay_s)
        Path(kwargs["register_path"]).write_bytes(b"xlsx")

    def map_renderer(*_args: Any, **_kwargs: Any) -> Image.Image:
        time.sleep(delay_s)
        return Image.new("RGB", (32, 32), "white")

    def satellite_renderer(*_args: Any, **_kwargs: Any) -> Image.Image:
        time.sleep(delay_s)
        return Image.new("RGB", (32, 32), "white")

    return replace(
        DEFAULT_DEPENDENCIES,
        client_factory=client_factory,
        parcel_fetcher=parcel_fetcher,
        spatial_planning_query=planning_query,
        tile_fetcher=tile_fetcher,
        geojson_writer=vector_writer,
        dxf_writer=vector_writer,
        kml_writer=vector_writer,
        html_writer=vector_writer,
        pdf_writer=pdf_writer,
        excel_writer=excel_writer,
        dp_map_renderer=map_renderer,
        satellite_renderer=satellite_renderer,
    )


def test_injected_stage_latency_stays_within_offline_regression_budgets(tmp_path: Path) -> None:
    delay_s = 0.015
    result = asyncio.run(
        lookup_plot_pro(
            "WORLI",
            "733",
            output_dir=str(tmp_path),
            use_cache=False,
            dependencies=_dependencies(delay_s),
        )
    )

    diagnostics = result["metadata"]["diagnostics"]
    stages = diagnostics["stages_ms"]
    spans = diagnostics["spans_ms"]
    assert result["metadata"]["complete"] is True
    assert diagnostics["elapsed_ms"] < 1_000
    # Lower bounds prove the delay-bearing adapters actually participate;
    # upper bounds catch accidental serialisation or runaway stage work.
    assert 10 <= stages["parcel_ingestion"] < 150
    assert 10 <= stages["source_queries"] < 250
    assert 10 <= stages["vector_artifacts"] < 300
    assert 20 <= stages["report_artifacts"] < 400
    assert stages["complete"] < 100
    assert 10 <= spans["parcel_fetch"] < 150
    assert 10 <= spans["spatial_planning_query"] < 250
    assert 10 <= spans["vector_exporters"] < 300
    assert spans["visual_fetch_total"] >= spans["visual_fetch_wait"]
    assert 20 <= spans["report_rendering"] < 400
