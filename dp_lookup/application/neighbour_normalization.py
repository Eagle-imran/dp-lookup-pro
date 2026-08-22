"""Normalize adjoining-parcel probes into a stable application contract."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from dp_lookup.application.contracts import NeighbourContext
from dp_lookup.clients.arcgis_models import decode_arcgis_response
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.models import EvidenceState


def parse_neighbour_responses(
    responses: Any,
    expected_count: int,
    parcel_cts: str,
    parcel_village: str,
) -> NeighbourContext:
    """Normalize adjoining-parcel probes without leaking ArcGIS field casing."""
    neighbours: Dict[str, Dict[str, Any]] = {}
    failures = 0
    if isinstance(responses, Exception) or not isinstance(responses, (list, tuple)):
        failures = expected_count
        response_items: Iterable[Any] = ()
    else:
        response_items = responses

    for response in response_items:
        payload = decode_arcgis_response(response)
        if payload is None or not payload.results_valid:
            failures += 1
            continue
        for item in payload.results:
            attributes = item.attributes
            cts_no = attributes.get("cts_cs_no") or attributes.get("CTS_CS_NO")
            if not cts_no or str(cts_no).strip() == str(parcel_cts).strip():
                continue
            area = attributes.get("area_app_sq_mtrs") or attributes.get("AREA_APP_SQ_MTRS")
            village = attributes.get("village") or attributes.get("VILLAGE")
            rings = item.geometry.get("rings") or []
            if not isinstance(rings, (list, tuple)):
                rings = []
            wgs_rings = []
            for ring in rings:
                if not isinstance(ring, (list, tuple)):
                    continue
                try:
                    wgs_rings.append([mercator_to_wgs84(point[0], point[1]) for point in ring])
                except (IndexError, TypeError, ValueError):
                    continue
            neighbours[str(cts_no)] = {
                "cts_no": str(cts_no),
                "village": str(village or parcel_village),
                "area_sqm": str(area) if area is not None else "N/A",
                "rings": wgs_rings,
            }

    warnings = []
    if failures:
        warnings.append(
            f"{failures} of {expected_count} neighbour probes failed; adjoining plots list may be incomplete"
        )
    state = EvidenceState.FAILED.value if failures == expected_count else EvidenceState.CONFIRMED.value
    return NeighbourContext(plots=list(neighbours.values()), warnings=warnings, evidence_state=state)
