"""Compatibility helpers for safely decoded ArcGIS JSON endpoints."""

from typing import Any, Dict, Optional

from dp_lookup.clients.arcgis_models import decode_arcgis_response


def usable_json(response: Any) -> Optional[Dict[str, Any]]:
    """Return the historical mapping shape after typed boundary validation."""
    payload = decode_arcgis_response(response)
    return dict(payload.raw) if payload is not None else None
