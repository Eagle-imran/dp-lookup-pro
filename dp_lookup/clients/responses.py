"""Safe response decoding for ArcGIS JSON endpoints."""

from typing import Any, Dict, Optional


def usable_json(response: Any) -> Optional[Dict[str, Any]]:
    if response is None or isinstance(response, Exception):
        return None
    if getattr(response, "status_code", None) != 200:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    return data
