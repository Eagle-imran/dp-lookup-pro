"""Typed, defensive models at the ArcGIS HTTP boundary.

ArcGIS is intentionally dynamic on the wire.  The rest of the application
should not repeatedly rediscover whether ``features``, ``results``,
``attributes`` and ``geometry`` have the expected shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ArcGISFeature:
    """One validated feature/identify result, preserving its raw payload."""

    attributes: Mapping[str, Any]
    geometry: Mapping[str, Any]
    layer_id: Optional[int]
    raw: Mapping[str, Any]

    @classmethod
    def from_value(cls, value: Any) -> Optional["ArcGISFeature"]:
        if not isinstance(value, Mapping):
            return None
        attributes = value.get("attributes")
        geometry = value.get("geometry")
        raw_layer_id = value.get("layerId")
        layer_id: Optional[int]
        try:
            layer_id = int(raw_layer_id) if raw_layer_id is not None else None
        except (TypeError, ValueError):
            layer_id = None
        return cls(
            attributes=dict(attributes) if isinstance(attributes, Mapping) else {},
            geometry=dict(geometry) if isinstance(geometry, Mapping) else {},
            layer_id=layer_id,
            raw=dict(value),
        )


@dataclass(frozen=True)
class ArcGISPayload:
    """A successfully decoded ArcGIS JSON object."""

    raw: Mapping[str, Any]
    features: Tuple[ArcGISFeature, ...]
    results: Tuple[ArcGISFeature, ...]
    features_valid: bool
    results_valid: bool

    @classmethod
    def from_mapping(cls, value: Any) -> Optional["ArcGISPayload"]:
        if not isinstance(value, Mapping) or "error" in value:
            return None
        raw_features = value.get("features", [])
        raw_results = value.get("results", [])
        return cls(
            raw=dict(value),
            features=_feature_collection(raw_features),
            results=_feature_collection(raw_results),
            features_valid=isinstance(raw_features, (list, tuple)),
            results_valid=isinstance(raw_results, (list, tuple)),
        )


def _feature_collection(value: Any) -> Tuple[ArcGISFeature, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    features = (ArcGISFeature.from_value(item) for item in value)
    return tuple(feature for feature in features if feature is not None)


def decode_arcgis_response(response: Any) -> Optional[ArcGISPayload]:
    """Decode a successful HTTP response once, at the transport boundary."""
    if response is None or isinstance(response, Exception):
        return None
    if getattr(response, "status_code", None) != 200:
        return None
    try:
        value = response.json()
    except Exception:
        return None
    return ArcGISPayload.from_mapping(value)
