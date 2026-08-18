"""Satellite tile retrieval and process-local/disk caching."""

import os
import tempfile
import threading
from collections import OrderedDict
from io import BytesIO
from typing import Optional, Tuple

import httpx
from PIL import Image

MAX_MEMORY_TILES = 512
TileKey = Tuple[str, str, int, int, int]
_TILE_CACHE: OrderedDict[TileKey, bytes] = OrderedDict()
_TILE_LOCK = threading.RLock()


def _valid_image(content: bytes) -> bool:
    if not content:
        return False
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        return True
    except Exception:
        return False


def _remember(key: TileKey, content: bytes) -> None:
    with _TILE_LOCK:
        _TILE_CACHE[key] = content
        _TILE_CACHE.move_to_end(key)
        while len(_TILE_CACHE) > MAX_MEMORY_TILES:
            _TILE_CACHE.popitem(last=False)


def _write_atomic(path: str, content: bytes) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".tile-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except OSError:
            pass


async def fetch_tile_cached(
    client: httpx.AsyncClient,
    zoom: int,
    ytile: int,
    xtile: int,
    tile_dir: str = "/tmp/dp_tile_cache",
) -> Optional[bytes]:
    directory = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(tile_dir))))
    key = (directory, "esri-world-imagery", zoom, ytile, xtile)
    with _TILE_LOCK:
        if key in _TILE_CACHE:
            content = _TILE_CACHE[key]
            _TILE_CACHE.move_to_end(key)
            return content

    os.makedirs(directory, exist_ok=True)
    cache_path = os.path.join(directory, f"esri_tile_{zoom}_{ytile}_{xtile}.jpg")
    try:
        with open(cache_path, "rb") as handle:
            content = handle.read()
        if _valid_image(content):
            _remember(key, content)
            return content
    except OSError:
        pass

    url = f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ytile}/{xtile}"
    try:
        response = await client.get(url, timeout=6.0)
        if response.status_code != 200 or not _valid_image(response.content):
            return None
        content = bytes(response.content)
        _remember(key, content)
        try:
            _write_atomic(cache_path, content)
        except OSError:
            pass
        return content
    except Exception:
        return None
