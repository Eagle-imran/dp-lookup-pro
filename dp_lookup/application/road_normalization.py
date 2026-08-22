"""Normalize road probes into a stable application contract."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from dp_lookup.application.contracts import RoadContext
from dp_lookup.clients.arcgis_models import decode_arcgis_response
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.models import EvidenceState
from dp_lookup.core.planning_status import select_road


def _road_attributes(attributes: Mapping[str, Any]) -> Tuple[Any, Any]:
    name = (
        attributes.get("ROAD_NAME")
        or attributes.get("Roadname")
        or attributes.get("NAME")
        or attributes.get("Name")
        or attributes.get("TYPE_")
        or attributes.get("Type")
    )
    width = attributes.get("WIDTH_RL") or attributes.get("WIDTH") or attributes.get("Width")
    return name, width


def parse_road_responses(responses: Any, expected_count: int) -> RoadContext:
    """Normalize repeated road probes and retain source-quality state."""
    road_map: Dict[str, Dict[str, Any]] = {}
    geometries: List[List[List[float]]] = []
    failures = 0
    if isinstance(responses, Exception) or not isinstance(responses, (list, tuple)):
        failures = expected_count
        response_items: Iterable[Any] = ()
    else:
        response_items = responses

    for response in response_items:
        payload = decode_arcgis_response(response)
        if payload is None or not payload.features_valid or not payload.results_valid:
            failures += 1
            continue
        for item in payload.features + payload.results:
            name, width = _road_attributes(item.attributes)
            if name or width:
                road_map[f"{name}|{width}"] = {"name": name or "Road", "width": width or "N/A"}
            raw_parts = item.geometry.get("paths") or item.geometry.get("rings") or []
            if not isinstance(raw_parts, (list, tuple)):
                continue
            for part in raw_parts:
                if not isinstance(part, (list, tuple)) or len(part) < 2:
                    continue
                try:
                    geometries.append([mercator_to_wgs84(point[0], point[1]) for point in part])
                except (IndexError, TypeError, ValueError):
                    continue

    warnings = []
    if failures:
        warnings.append(f"{failures} of {expected_count} road probes failed; abutting road may be incomplete")
    selected = select_road(road_map)
    name = selected["name"]
    if failures == expected_count:
        state = EvidenceState.FAILED.value
    elif name in {"Unnamed / existing road", "None"}:
        state = EvidenceState.UNKNOWN.value
    else:
        state = EvidenceState.CONFIRMED.value
    return RoadContext(
        name=name,
        width=selected["width"],
        geometries=geometries,
        warnings=warnings,
        evidence_state=state,
    )
