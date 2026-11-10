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


def _age(path, seconds):
    import os
    import time

    old = time.time() - seconds
    os.utime(path, (old, old))


def test_expired_disk_tile_is_refreshed(tmp_path):
    tile_cache._TILE_CACHE.clear()
    path = tmp_path / "esri_tile_18_7_8.jpg"
    old, new = _png("red"), _png("blue")
    path.write_bytes(old)
    _age(path, tile_cache.TILE_MAX_AGE_SECONDS + 60)
    client = Client([new])

    result = asyncio.run(tile_cache.fetch_tile_cached(client, 18, 7, 8, str(tmp_path)))

    assert result == new
    assert path.read_bytes() == new
    assert client.calls == 1


def test_expired_disk_tile_is_used_when_refresh_fails(tmp_path):
    tile_cache._TILE_CACHE.clear()
    path = tmp_path / "esri_tile_18_9_10.jpg"
    old = _png("red")
    path.write_bytes(old)
    _age(path, tile_cache.TILE_MAX_AGE_SECONDS + 60)
    client = Client([b"<html>maintenance</html>"])

    assert asyncio.run(tile_cache.fetch_tile_cached(client, 18, 9, 10, str(tmp_path))) == old


def test_default_tile_dir_is_per_user_and_overridable(monkeypatch, tmp_path):
    import os
    import tempfile

    monkeypatch.delenv(tile_cache.TILE_CACHE_ENV, raising=False)
    default = tile_cache.default_tile_dir()
    assert not os.path.realpath(default).startswith(os.path.realpath(tempfile.gettempdir()))
    assert default.endswith(os.path.join("dp-lookup-pro", "tiles"))

    monkeypatch.setenv(tile_cache.TILE_CACHE_ENV, str(tmp_path / "tiles"))
    assert tile_cache.default_tile_dir() == str(tmp_path / "tiles")
