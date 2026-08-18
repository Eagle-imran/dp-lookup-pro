"""
Local File-Based Cache, Validation, and JSON Response Safety Helpers.
"""
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, Optional

from dp_lookup.core.constants import CACHE_FILENAME, DEFAULT_CACHE_TTL_SECONDS

# In-memory tile cache is process-scoped and safe to share across lookups.
_TILE_CACHE: Dict[str, bytes] = {}

# One lookup store per output directory.
_STORES: Dict[str, Dict[str, Any]] = {}


def sanitize_query_value(value: Any, pattern: "re.Pattern[str]", label: str, max_len: int = 64) -> str:
    """Validate and sanitize user input before interpolating into SQL / WHERE queries."""
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if len(text) > max_len:
        raise ValueError(f"{label} is too long (max {max_len} characters)")
    if not pattern.match(text):
        raise ValueError(
            f"{label} contains unsupported characters. "
            f"Allowed: letters, digits, space, and ( ) . / -"
        )
    return text


def usable_json(resp: Any) -> Optional[Dict[str, Any]]:
    """
    Safely extract parsed JSON from an HTTP response, returning None on
    exceptions, non-200 HTTP statuses, or ArcGIS error payloads.
    """
    if resp is None or isinstance(resp, Exception):
        return None
    if getattr(resp, "status_code", None) != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "error" in data:
        return None
    return data


def cache_path_for(output_dir: str) -> str:
    """Cache store lives beside the bundles it describes, not beside the CWD."""
    return os.path.join(output_dir, CACHE_FILENAME)


def load_disk_cache(output_dir: str) -> Dict[str, Any]:
    path = cache_path_for(output_dir)
    if path in _STORES:
        return _STORES[path]
    store: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                store = loaded
        except (OSError, ValueError):
            store = {}
    _STORES[path] = store
    return store


def save_disk_cache(output_dir: str) -> None:
    path = cache_path_for(output_dir)
    store = _STORES.get(path, {})
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
    except OSError as exc:
        print(f"[dp-lookup-pro] WARNING: could not write cache store {path}: {exc}", file=sys.stderr)


def bundle_is_intact(result: Dict[str, Any]) -> bool:
    """True when every file the cached result promises still exists on disk."""
    files = result.get("export_files")
    if not isinstance(files, dict):
        return False
    for key, path in files.items():
        if key == "master_excel_register" or not isinstance(path, str):
            continue
        if not os.path.exists(path):
            return False
    return True


def read_cache_entry(output_dir: str, key: str, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    """
    Return a cached result, or None when it is absent, expired, in the legacy
    format, or no longer backed by files on disk.
    """
    entry = load_disk_cache(output_dir).get(key)
    if not isinstance(entry, dict):
        return None
    cached_at = entry.get("cached_at")
    result = entry.get("result")
    if not isinstance(cached_at, (int, float)) or not isinstance(result, dict):
        return None
    if ttl_seconds >= 0 and (time.time() - cached_at) > ttl_seconds:
        return None
    if not bundle_is_intact(result):
        return None

    result = json.loads(json.dumps(result))
    age = max(0.0, time.time() - cached_at)
    meta = result.setdefault("metadata", {})
    meta["cached_result"] = True
    meta["cached_at"] = datetime.datetime.fromtimestamp(cached_at).strftime("%Y-%m-%d %H:%M:%S")
    meta["cache_age_days"] = round(age / 86400.0, 2)
    meta["cache_expires_in_days"] = (
        None if ttl_seconds < 0 else round(max(0.0, ttl_seconds - age) / 86400.0, 2)
    )
    return result


def write_cache_entry(output_dir: str, key: str, result: Dict[str, Any]) -> None:
    """Persist a clean lookup result to the local disk cache."""
    store = load_disk_cache(output_dir)
    store[key] = {"cached_at": time.time(), "result": result}
    save_disk_cache(output_dir)
