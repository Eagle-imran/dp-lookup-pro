"""Shared typed payload adapter for built-in and legacy exporter calls."""

from typing import Any, Dict, Mapping, Union

from dp_lookup.core.models import ExportData

ExportPayload = Union[ExportData, Mapping[str, Any]]


def legacy_export_properties(payload: ExportPayload) -> Dict[str, Any]:
    """Return the historical mapping shape at the renderer implementation edge."""
    if isinstance(payload, ExportData):
        return payload.to_legacy_dict()
    return dict(payload)
