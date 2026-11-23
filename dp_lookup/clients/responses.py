"""Compatibility helpers for safely decoded ArcGIS JSON endpoints."""

from typing import Any

from dp_lookup.clients.arcgis_models import decode_arcgis_response


def usable_json(response: Any) -> dict[str, Any] | None:
    """Return the historical mapping shape after typed boundary validation."""
    payload = decode_arcgis_response(response)
    return dict(payload.raw) if payload is not None else None
