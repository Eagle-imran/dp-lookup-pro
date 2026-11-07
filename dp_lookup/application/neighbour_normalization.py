"""Check adjoining parcel boundaries consistently for local and live data."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from shapely.geometry.base import BaseGeometry

from dp_lookup.application.contracts import NeighbourContext, ParcelContext
from dp_lookup.clients.arcgis_models import decode_arcgis_response
from dp_lookup.core.area_assessment import calculated_boundary_area_sqm
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.topology import arcgis_rings_to_geometry

ADJACENCY_TOLERANCE_M = 0.5
MIN_SHARED_BOUNDARY_M = 0.05
LIVE_METHOD = "live_boundary_query"


def adjoining_parcels(
    parcel: ParcelContext,
    subject: BaseGeometry,
    candidates: Iterable[Mapping[str, Any]],
    *,
    tolerance_m: float = ADJACENCY_TOLERANCE_M,
    min_shared_boundary_m: float = MIN_SHARED_BOUNDARY_M,
) -> List[Dict[str, Any]]:
    subject_village = str(parcel.attrs.get("VILLAGE") or parcel.village).strip().casefold()
    subject_cts = str(parcel.attrs.get("CTS_CS_NO") or parcel.cts_no).strip().casefold()
    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for row in candidates:
        village = str(row.get("village") or "").strip()
        cts_no = str(row.get("cts_no") or "").strip()
        if not cts_no or (village.casefold(), cts_no.casefold()) == (subject_village, subject_cts):
            continue
        grouped[(village, cts_no)].append(row)

    neighbours: List[Dict[str, Any]] = []
    for (village, cts_no), parts in grouped.items():
        rings: List[Any] = []
        for part in parts:
            part_rings = part.get("rings")
            if isinstance(part_rings, list):
                rings.extend(part_rings)
        geometry = arcgis_rings_to_geometry(rings)
        if geometry.is_empty or subject.intersection(geometry).area > 1e-6:
            continue
        shared = float(subject.boundary.intersection(geometry.boundary).length)
        gap = float(subject.distance(geometry))
        if shared >= min_shared_boundary_m:
            relation = "shared_boundary"
        elif 0.0 < gap <= tolerance_m:
            relation = "tolerance_gap"
        else:
            # Point contact and overlapping boundaries are not adjoining parcels.
            continue
        recorded = {
            float(part["area_app_sqm"])
            for part in parts
            if part.get("area_app_sqm") is not None and float(part["area_app_sqm"]) > 0
        }
        if len(recorded) == 1:
            area: Any = next(iter(recorded))
            area_source = "Recorded plot area"
        else:
            calculated = calculated_boundary_area_sqm(rings)
            area = round(calculated, 2) if calculated is not None else "N/A"
            area_source = "Calculated boundary area" if calculated is not None else "Unavailable"
        neighbours.append(
            {
                "cts_no": cts_no,
                "village": village,
                "area_sqm": str(area),
                "area_source": area_source,
                "rings": [[mercator_to_wgs84(point[0], point[1]) for point in ring] for ring in rings],
                "source_objectids": sorted(int(part["objectid"]) for part in parts),
                "adjacency_relation": relation,
                "shared_boundary_m": round(shared, 3),
                "gap_m": round(gap, 3),
            }
        )
    neighbours.sort(key=lambda item: (item["village"], item["cts_no"]))
    return neighbours


def live_neighbours_unavailable(reason: str) -> NeighbourContext:
    return NeighbourContext(
        warnings=[f"Live adjoining plots are unavailable: {reason}."],
        evidence_state="failed",
        method=LIVE_METHOD,
    )


def parse_live_neighbours(response: Any, parcel: ParcelContext, subject: BaseGeometry) -> NeighbourContext:
    payload = decode_arcgis_response(response)
    if payload is None or "features" not in payload.raw or not payload.features_valid:
        return live_neighbours_unavailable("the MCGM boundary query failed")
    if payload.raw.get("exceededTransferLimit"):
        return live_neighbours_unavailable("MCGM returned an incomplete set of parcel boundaries")

    rows = [
        {
            "objectid": feature.attributes.get("OBJECTID"),
            "village": feature.attributes.get("VILLAGE"),
            "cts_no": feature.attributes.get("CTS_CS_NO"),
            "area_app_sqm": feature.attributes.get("AREA_APP_SQ_MTRS"),
            "rings": feature.geometry.get("rings"),
        }
        for feature in payload.features
    ]
    if len(rows) != len(payload.raw["features"]) or any(
        row["objectid"] is None or not row["village"] or not row["cts_no"] or not row["rings"] for row in rows
    ):
        return live_neighbours_unavailable("MCGM returned malformed parcel boundaries")
    return NeighbourContext(plots=adjoining_parcels(parcel, subject, rows), method=LIVE_METHOD)
