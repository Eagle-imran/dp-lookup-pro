"""Satellite cache isolation, validation, and corruption recovery."""

import asyncio
import io

from PIL import Image

from dp_lookup.clients import tile_cache


def _png(colour):
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), colour).save(stream, "PNG")
    return stream.getvalue()


class Response:
    status_code = 200

    def __init__(self, content):
        self.content = content


class Client:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    async def get(self, _url, timeout=None):
        self.calls += 1
        return Response(self.contents.pop(0))


def test_memory_cache_is_scoped_to_canonical_tile_directory(tmp_path):
    tile_cache._TILE_CACHE.clear()
    first = _png("red")
    second = _png("blue")
    client = Client([first, second])

    async def run():
        one = await tile_cache.fetch_tile_cached(client, 18, 1, 2, str(tmp_path / "one"))
        two = await tile_cache.fetch_tile_cached(client, 18, 1, 2, str(tmp_path / "two"))
        return one, two

    assert asyncio.run(run()) == (first, second)
    assert client.calls == 2


def test_invalid_network_body_is_not_cached(tmp_path):
    tile_cache._TILE_CACHE.clear()
    client = Client([b"<html>not an image</html>"])
    result = asyncio.run(tile_cache.fetch_tile_cached(client, 18, 3, 4, str(tmp_path)))
    assert result is None
    assert list(tmp_path.iterdir()) == []
    assert tile_cache._TILE_CACHE == {}


def test_corrupt_disk_tile_is_refetched_atomically(tmp_path):
    tile_cache._TILE_CACHE.clear()
    path = tmp_path / "esri_tile_18_5_6.jpg"
    path.write_bytes(b"corrupt")
    valid = _png("green")
    client = Client([valid])
    result = asyncio.run(tile_cache.fetch_tile_cached(client, 18, 5, 6, str(tmp_path)))
    assert result == valid
    assert path.read_bytes() == valid
    assert client.calls == 1


def test_memory_cache_is_bounded(monkeypatch):
    tile_cache._TILE_CACHE.clear()
    monkeypatch.setattr(tile_cache, "MAX_MEMORY_TILES", 2)
    for index in range(3):
        tile_cache._remember(("dir", "provider", 18, 1, index), _png("white"))
    assert len(tile_cache._TILE_CACHE) == 2
