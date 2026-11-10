"""Cadastral ingestion stage for the lookup use case."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from shapely.geometry.base import BaseGeometry

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.clients.arcgis_models import ArcGISFeature, decode_arcgis_response
from dp_lookup.core.area_assessment import assess_plot_area
from dp_lookup.core.constants import MCGM_VILLAGES, SERVER_URL
from dp_lookup.core.geometry import prepare_geometry
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.core.villages import suggest_villages


class ParcelIngestionError(RuntimeError):
    """The required Layer 13 source could not be read safely."""


class ParcelIdentityMismatchError(ParcelIngestionError):
    """Only differently numbered plots matched; never report them as the request."""

    MAX_LISTED = 10

    def __init__(self, village: str, cts_no: str, candidates: Sequence[str]) -> None:
        self.candidates = tuple(candidates)
        listed = ", ".join(self.candidates[: self.MAX_LISTED])
        if len(self.candidates) > self.MAX_LISTED:
            listed += f" (+{len(self.candidates) - self.MAX_LISTED} more)"
        super().__init__(
            f"Village '{village}' has no plot numbered exactly '{cts_no}'. "
            f"Similarly numbered plots exist: {listed}. Re-run with the exact CTS number you need."
        )


def _normalised_cts(value: Any) -> str:
    return str(value or "").strip().casefold()


def _positive_area(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _objectid(feature: ArcGISFeature) -> Optional[int]:
    value = feature.attributes.get("OBJECTID")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _merge_live_matches(matches: Sequence[ArcGISFeature], *, prefix_fallback: bool) -> Dict[str, Any]:
    """Combine every same-identity Layer 13 part, matching the local adapter.

    A village/CTS identity can be stored as several source features. Using
    only the first one would understate the plot boundary and every planning
    overlap computed against it.
    """
    objectids = [_objectid(match) for match in matches]
    known_ids = [value for value in objectids if value is not None]
    ordered = list(matches)
    if len(known_ids) == len(matches):
        ordered = [match for _, match in sorted(zip(known_ids, matches, strict=True), key=lambda item: item[0])]

    combined_rings: List[Any] = []
    unique_geometries: List[BaseGeometry] = []
    duplicate_geometry_count = 0
    for match in ordered:
        rings = match.geometry.get("rings")
        if not isinstance(rings, list) or not rings:
            raise ParcelIngestionError("MCGM Layer 13 returned a parcel part without polygon rings.")
        try:
            geometry = arcgis_rings_to_geometry(rings)
        except (IndexError, TypeError, ValueError) as exc:
            raise ParcelIngestionError("MCGM Layer 13 returned unusable parcel geometry.") from exc
        if any(geometry.equals(existing) for existing in unique_geometries):
            duplicate_geometry_count += 1
            continue
        unique_geometries.append(geometry)
        combined_rings.extend(rings)

    first = ordered[0]
    copied = dict(first.raw)
    attrs = dict(first.attributes)
    geometry_payload = dict(first.geometry)
    geometry_payload["rings"] = combined_rings
    copied["attributes"] = attrs
    copied["geometry"] = geometry_payload
    attrs["_DP_QUERY_MATCH_COUNT"] = len(matches)
    attrs["_DP_QUERY_MATCH_TYPE"] = "prefix" if prefix_fallback else "exact"
    if len(matches) > 1:
        attrs["FEATURE_PART_COUNT"] = len(matches)
        if len(known_ids) == len(matches):
            attrs["SOURCE_OBJECTIDS"] = sorted(known_ids)

    raw_areas = [match.attributes.get("AREA_APP_SQ_MTRS") for match in ordered]
    recorded_values = {area for area in (_positive_area(value) for value in raw_areas) if area is not None}
    if len(matches) > 1:
        # One repeated value can stay the stated area; disagreeing parts must
        # not be summed or silently resolved to the first record.
        attrs["AREA_APP_SQ_MTRS"] = next(iter(recorded_values)) if len(recorded_values) == 1 else None
    if len(recorded_values) > 1:
        attrs["_DP_AREA_CONFLICT_VALUES"] = sorted(recorded_values)
    if recorded_values and any(_positive_area(value) is None for value in raw_areas):
        attrs["_DP_RECORDED_AREA_MISSING_PARTS"] = True
    if duplicate_geometry_count:
        attrs["_DP_DUPLICATE_GEOMETRY_COUNT"] = duplicate_geometry_count
    return copied


def not_found_result(village: str, cts_no: str) -> Dict[str, Any]:
    """Explain an exact parcel miss without confusing it with source failure."""
    if village in MCGM_VILLAGES:
        message = (
            f"Village '{village}' is valid, but it has no plot numbered '{cts_no}'. "
            "Check the CTS number - suffixes and slashes matter ('748A' and '748' "
            "are different plots, as are '16/738' and '16-738')."
        )
    else:
        message = f"'{village}' is not a valid MCGM village name."
    return {"error": message, "suggestions": suggest_villages(village)}


async def fetch_parcel_feature(client: Any, village: str, cts_no: str) -> Optional[Dict[str, Any]]:
    """Fetch every exact Layer 13 part; a prefix retry may only fix spacing/case."""
    query_params = {
        "where": f"VILLAGE='{village}' AND CTS_CS_NO='{cts_no}'",
        "outFields": "OBJECTID,WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS,SHAPE.AREA",
        "returnGeometry": "true",
        "outSR": "102100",
        "f": "json",
    }
    try:
        response = await client.get(f"{SERVER_URL}/13/query", params=query_params)
    except httpx.HTTPError as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise ParcelIngestionError(f"MCGM server error while querying Layer 13 ({detail}).") from exc

    payload = decode_arcgis_response(response)
    if payload is None or not payload.features_valid:
        raise ParcelIngestionError(
            f"Cadastral query to MCGM Layer 13 failed (status {getattr(response, 'status_code', 'unknown')}). "
            "The server may be down or rejecting requests. Please retry."
        )
    if payload.features:
        return _merge_live_matches(payload.features, prefix_fallback=False)

    try:
        fallback_response = await client.get(
            f"{SERVER_URL}/13/query",
            params={**query_params, "where": f"VILLAGE='{village}' AND CTS_CS_NO LIKE '{cts_no}%'"},
        )
    except httpx.HTTPError as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise ParcelIngestionError(f"MCGM server error during the Layer 13 fallback query ({detail}).") from exc
    fallback = decode_arcgis_response(fallback_response)
    if fallback is None or not fallback.features_valid or not fallback.features:
        return None
    requested = _normalised_cts(cts_no)
    same_identity = [
        feature for feature in fallback.features if _normalised_cts(feature.attributes.get("CTS_CS_NO")) == requested
    ]
    if same_identity:
        # Only spacing/case differed from the stored identity.
        return _merge_live_matches(same_identity, prefix_fallback=True)
    candidates = sorted(
        {str(feature.attributes.get("CTS_CS_NO")).strip() for feature in fallback.features} - {"", "None"}
    )
    raise ParcelIdentityMismatchError(village, cts_no, candidates)


def build_parcel_context(feature: Dict[str, Any], village: str, cts_no: str) -> Tuple[ParcelContext, Optional[str]]:
    """Validate and normalize one Layer 13 feature into the stage contract."""
    try:
        attrs = dict(feature["attributes"])
        rings = feature["geometry"]["rings"]
    except (KeyError, TypeError) as exc:
        raise ParcelIngestionError("MCGM Layer 13 returned a malformed parcel feature.") from exc

    assessment = assess_plot_area(
        attrs,
        rings,
        requested_village=village,
        requested_cts_no=cts_no,
    )
    area_sqm = assessment.selected_area_sqm
    if not isinstance(area_sqm, (int, float)):
        raise ParcelIngestionError("MCGM parcel has neither a recorded nor calculable boundary area.")
    attrs["_DP_AREA_ASSESSMENT"] = assessment.to_dict()

    try:
        geometry = prepare_geometry(rings)
    except (IndexError, TypeError, ValueError) as exc:
        raise ParcelIngestionError("MCGM Layer 13 returned unusable parcel geometry.") from exc

    context = ParcelContext(
        village=village,
        cts_no=cts_no,
        attrs=attrs,
        rings=rings,
        wgs_rings=geometry["wgs_rings"],
        area_sqm=float(area_sqm),
        area_source=(
            "Recorded plot area"
            if assessment.selected_area_basis == "recorded_plot_area"
            else "Calculated boundary area"
        ),
        latitude=geometry["lat"],
        longitude=geometry["lon"],
        cx=geometry["cx"],
        cy=geometry["cy"],
        mcx=geometry["mcx"],
        mcy=geometry["mcy"],
        xs=geometry["xs"],
        ys=geometry["ys"],
        window_radius=geometry["d"],
        area_assessment=assessment,
    )
    note = None
    if assessment.selected_area_basis == "calculated_boundary_area":
        note = "Recorded plot area is unavailable; calculated boundary area is used for screening."
    return context, note
