"""Cadastral ingestion stage for the lookup use case."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import httpx

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.clients.responses import usable_json
from dp_lookup.core.area_assessment import assess_plot_area
from dp_lookup.core.constants import MCGM_VILLAGES, SERVER_URL
from dp_lookup.core.geometry import prepare_geometry
from dp_lookup.core.villages import suggest_villages


class ParcelIngestionError(RuntimeError):
    """The required Layer 13 source could not be read safely."""


def _annotate_live_match(
    feature: Dict[str, Any],
    matches: list,
    *,
    requested_cts_no: str,
    prefix_fallback: bool,
) -> Dict[str, Any]:
    """Copy one historical live match and expose ambiguity without changing selection."""
    if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
        raise ParcelIngestionError("MCGM Layer 13 returned a malformed parcel feature.")
    copied = dict(feature)
    attrs = dict(feature["attributes"])
    copied["attributes"] = attrs
    attrs["_DP_QUERY_MATCH_COUNT"] = len(matches)
    attrs["_DP_QUERY_MATCH_TYPE"] = "prefix" if prefix_fallback else "exact"
    if len(matches) > 1:
        attrs["FEATURE_PART_COUNT"] = len(matches)
    recorded_values = set()
    returned_cts_values = set()
    for match in matches:
        match_attrs = match.get("attributes") if isinstance(match, dict) else None
        if not isinstance(match_attrs, dict):
            continue
        value = match_attrs.get("AREA_APP_SQ_MTRS")
        try:
            number = float(value)
            if math.isfinite(number) and number > 0:
                recorded_values.add(number)
        except (TypeError, ValueError):
            pass
        returned_cts = str(match_attrs.get("CTS_CS_NO") or "").strip().casefold()
        if returned_cts:
            returned_cts_values.add(returned_cts)
    if len(recorded_values) > 1:
        attrs["_DP_AREA_CONFLICT_VALUES"] = sorted(recorded_values)
    if prefix_fallback and (
        len(returned_cts_values) != 1 or returned_cts_values != {requested_cts_no.strip().casefold()}
    ):
        attrs["_DP_IDENTITY_AMBIGUOUS"] = True
    if len(matches) > 1:
        attrs["_DP_UNMERGED_SOURCE_RECORDS"] = True
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
    """Fetch an exact Layer 13 parcel, retaining the historical prefix fallback."""
    query_params = {
        "where": f"VILLAGE='{village}' AND CTS_CS_NO='{cts_no}'",
        "outFields": "WARD,TYPE,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS,SHAPE.AREA",
        "returnGeometry": "true",
        "outSR": "102100",
        "f": "json",
    }
    try:
        response = await client.get(f"{SERVER_URL}/13/query", params=query_params)
    except httpx.HTTPError as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise ParcelIngestionError(f"MCGM server error while querying Layer 13 ({detail}).") from exc

    data = usable_json(response)
    if data is None:
        raise ParcelIngestionError(
            f"Cadastral query to MCGM Layer 13 failed (status {getattr(response, 'status_code', 'unknown')}). "
            "The server may be down or rejecting requests. Please retry."
        )
    features = data.get("features")
    if isinstance(features, list) and features:
        return _annotate_live_match(features[0], features, requested_cts_no=cts_no, prefix_fallback=False)

    try:
        fallback_response = await client.get(
            f"{SERVER_URL}/13/query",
            params={**query_params, "where": f"VILLAGE='{village}' AND CTS_CS_NO LIKE '{cts_no}%'"},
        )
        fallback = usable_json(fallback_response)
        fallback_features = fallback.get("features") if fallback else None
        if isinstance(fallback_features, list) and fallback_features:
            return _annotate_live_match(
                fallback_features[0],
                fallback_features,
                requested_cts_no=cts_no,
                prefix_fallback=True,
            )
    except httpx.HTTPError as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise ParcelIngestionError(f"MCGM server error during the Layer 13 fallback query ({detail}).") from exc
    return None


def build_parcel_context(feature: Dict[str, Any], village: str, cts_no: str) -> tuple:
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
