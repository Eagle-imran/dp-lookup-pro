"""
Local File-Based Cache, Validation, and JSON Response Safety Helpers.
"""

import datetime
import json
import math
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from dp_lookup.clients.responses import usable_json as usable_json
from dp_lookup.clients.tile_cache import _TILE_CACHE as _TILE_CACHE
from dp_lookup.clients.validation import sanitize_query_value as sanitize_query_value
from dp_lookup.core.constants import (
    APPLICATION_VERSION,
    CACHE_FILENAME,
    CACHE_SCHEMA_VERSION,
    DEFAULT_CACHE_TTL_SECONDS,
)

# One lookup store per output directory.
_STORES: Dict[str, Dict[str, Any]] = {}

# Cache files can be touched by several lookups in one process (and, for
# example, by two CLI invocations started from a shell script).  Keep the
# lock process-local even on platforms without fcntl; the file lock below is
# only an additional best-effort guard for cooperating processes.
_CACHE_LOCK = threading.RLock()

try:  # pragma: no cover - fcntl is unavailable on Windows
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None  # type: ignore[assignment]


CACHE_APP_VERSION = APPLICATION_VERSION
CACHE_METADATA_KEY = "_cache_metadata"


def cache_path_for(output_dir: str) -> str:
    """Cache store lives beside the bundles it describes, not beside the CWD."""
    # realpath also collapses aliases such as ``reports`` and
    # ``reports/../reports`` (and resolves symlinked output directories), so a
    # single in-memory store cannot accidentally diverge into two stores.
    canonical_dir = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(output_dir))))
    return os.path.join(canonical_dir, CACHE_FILENAME)


def _lock_path(path: str) -> str:
    """Return a stable path used for cross-process locking.

    The lock is deliberately separate from the cache file: atomic replacement
    changes the cache inode, while this companion file remains stable.
    """
    return f"{path}.lock"


@contextmanager
def _disk_lock(path: str) -> Iterator[None]:
    """Best-effort advisory lock for cache operations.

    ``fcntl`` is part of the standard library on the Unix platforms we ship
    on.  If it is unavailable or the filesystem rejects locking, the
    in-process lock still provides safe behavior and the operation proceeds.
    """
    lock_handle = None
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        lock_handle = open(_lock_path(path), "a+b")
        if fcntl is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass
    except OSError:
        # A read/write failure on the lock must not make the cache unusable.
        # The caller still has the process-local lock.
        pass
    try:
        yield
    finally:
        if lock_handle is not None:
            if fcntl is not None:
                try:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                lock_handle.close()
            except OSError:
                pass


def _read_store(path: str) -> Dict[str, Any]:
    store: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                store = loaded
        except (OSError, ValueError):
            store = {}
    return store


def _cache_metadata() -> Dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "app_version": CACHE_APP_VERSION,
    }


def _save_store(path: str, store: Dict[str, Any]) -> None:
    """Write a complete cache document without exposing a partial target."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=parent or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            json.dump({**store, CACHE_METADATA_KEY: _cache_metadata()}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        # json serialization errors should retain their existing behavior, but
        # never leave a misleading temporary cache behind.
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load_disk_cache(output_dir: str) -> Dict[str, Any]:
    path = cache_path_for(output_dir)
    with _CACHE_LOCK:
        if path in _STORES:
            return _STORES[path]
        with _disk_lock(path):
            store = _read_store(path)
        _STORES[path] = store
        return store


def save_disk_cache(output_dir: str) -> None:
    path = cache_path_for(output_dir)
    with _CACHE_LOCK:
        previous_store = _STORES.get(path)
        store = _STORES.get(path, {})
        try:
            with _disk_lock(path):
                # Preserve entries written by another process after this
                # process loaded its snapshot.  Keys intentionally present in
                # the caller's in-memory store win, matching the historical
                # "mutate then save" behavior of this public function.
                on_disk = _read_store(path)
                if on_disk:
                    merged = dict(on_disk)
                    merged.update(store)
                    store = merged
                _save_store(path, store)
        except Exception as exc:
            if previous_store is None:
                _STORES.pop(path, None)
            else:
                _STORES[path] = previous_store
            if isinstance(exc, OSError):
                print(f"[dp-lookup-pro] WARNING: could not write cache store {path}: {exc}", file=sys.stderr)
            else:
                raise
        else:
            _STORES[path] = store


def bundle_is_intact(result: Dict[str, Any]) -> bool:
    """True when every file the cached result promises still exists on disk."""
    files = result.get("export_files")
    if not isinstance(files, dict):
        return False
    for key, path in files.items():
        if key == "master_excel_register" or not isinstance(path, str):
            continue
        try:
            if key == "bundle_folder":
                if not os.path.isdir(path):
                    return False
                continue
            if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                return False
        except OSError:
            return False
    return True


def read_cache_entry(
    output_dir: str, key: str, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
) -> Optional[Dict[str, Any]]:
    """
    Return a cached result, or None when it is absent, expired, has a known
    incompatible schema, or is no longer backed by files on disk.

    Old entries remain on disk but must be recomputed after analysis-policy
    changes; missing schema metadata is not proof of compatibility.
    """
    entry = load_disk_cache(output_dir).get(key)
    if not isinstance(entry, dict):
        return None
    cached_at = entry.get("cached_at")
    result = entry.get("result")
    if not isinstance(cached_at, (int, float)) or not isinstance(result, dict):
        return None
    if isinstance(cached_at, bool):
        return None
    try:
        if not math.isfinite(float(cached_at)) or cached_at > time.time():
            return None
    except (OverflowError, ValueError):
        return None
    entry_schema = entry.get("cache_schema_version")
    if entry_schema != CACHE_SCHEMA_VERSION:
        return None
    if ttl_seconds >= 0 and (time.time() - cached_at) > ttl_seconds:
        return None
    if not bundle_is_intact(result):
        return None

    copied_result = json.loads(json.dumps(result))
    if not isinstance(copied_result, dict):
        return None
    result = copied_result
    age = max(0.0, time.time() - cached_at)
    meta = result.setdefault("metadata", {})
    meta["cached_result"] = True
    meta["cached_at"] = datetime.datetime.fromtimestamp(cached_at).strftime("%Y-%m-%d %H:%M:%S")
    meta["cache_age_days"] = round(age / 86400.0, 2)
    meta["cache_expires_in_days"] = None if ttl_seconds < 0 else round(max(0.0, ttl_seconds - age) / 86400.0, 2)
    return result


def write_cache_entry(output_dir: str, key: str, result: Dict[str, Any]) -> None:
    """Persist a clean lookup result to the local disk cache."""
    path = cache_path_for(output_dir)
    with _CACHE_LOCK:
        previous_store = _STORES.get(path)
        # Refresh from disk while holding the advisory lock so two processes
        # writing different keys cannot overwrite one another with stale
        # in-memory snapshots.
        with _disk_lock(path):
            store = _read_store(path)
            store[key] = {
                "cached_at": time.time(),
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "application_version": CACHE_APP_VERSION,
                "result": result,
            }
            try:
                _save_store(path, store)
            except Exception as exc:
                if previous_store is None:
                    _STORES.pop(path, None)
                else:
                    _STORES[path] = previous_store
                if isinstance(exc, OSError):
                    print(f"[dp-lookup-pro] WARNING: could not write cache store {path}: {exc}", file=sys.stderr)
                else:
                    raise
            else:
                _STORES[path] = store
