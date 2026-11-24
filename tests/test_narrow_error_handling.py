"""Fallbacks catch only the failures they are written for; anything else surfaces."""

from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from shapely.errors import GEOSException

from dp_lookup.application.snapshot_ingestion import _sorted_ids
from dp_lookup.clients.tile_cache import fetch_tile_cached
from dp_lookup.exporters.dxf_geometry import offset_polygon_inward
from dp_lookup.exporters.dxf_renderer import new_dxf_document
from dp_lookup.spatial_store import codecs

SQUARE = [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]


def test_object_ids_skip_values_that_are_not_whole_non_negative_numbers():
    assert _sorted_ids([3, "2", None, "abc", float("inf"), float("nan"), True, -1, 2]) == (2, 3)


class _FailingClient:
    def __init__(self, error: Exception):
        self.error = error

    async def get(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
        raise self.error


def _stale_tile(directory: Path) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="JPEG")
    content = buffer.getvalue()
    path = directory / "esri_tile_5_6_7.jpg"
    path.write_bytes(content)
    os.utime(path, (0, 0))
    return content


def test_satellite_tile_falls_back_to_the_stale_copy_when_the_network_fails(tmp_path: Path):
    stale = _stale_tile(tmp_path)
    client: Any = _FailingClient(httpx.ConnectError("offline"))

    assert asyncio.run(fetch_tile_cached(client, 5, 6, 7, tile_dir=str(tmp_path))) == stale


def test_satellite_tile_does_not_hide_programming_errors(tmp_path: Path):
    _stale_tile(tmp_path)
    client: Any = _FailingClient(RuntimeError("bug"))

    with pytest.raises(RuntimeError, match="bug"):
        asyncio.run(fetch_tile_cached(client, 5, 6, 7, tile_dir=str(tmp_path / "other")))


@pytest.mark.parametrize(
    "ring",
    [
        [(float("nan"), 0.0), (1.0, 1.0), (0.0, 1.0)],
        [(1e308, 0.0), (-1e308, 0.0), (0.0, 1e308)],
        [(0.0, 0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
    ],
)
def test_inward_offset_of_a_ring_shapely_rejects_is_empty(ring: list[tuple[float, ...]]):
    assert offset_polygon_inward(ring, 1.0) == []


def test_polygon_topology_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch):
    def broken(_rings: Any) -> Any:
        raise GEOSException("TopologyException")

    monkeypatch.setattr(codecs, "arcgis_rings_to_geometry", broken)

    message = codecs.polygon_validation_error({"rings": SQUARE})

    assert message == "polygon topology could not be interpreted (TopologyException)"


def test_new_dxf_document_defines_the_project_linetypes():
    doc = new_dxf_document()

    assert "DASHED" in doc.linetypes
    assert "PHANTOM" in doc.linetypes
