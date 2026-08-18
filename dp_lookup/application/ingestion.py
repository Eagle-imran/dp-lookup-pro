"""Cadastral ingestion stage for the lookup use case."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.clients.responses import usable_json
from dp_lookup.core.constants import SERVER_URL
from dp_lookup.core.geometry import prepare_geometry, resolve_plot_area


class ParcelIngestionError(RuntimeError):
    """The required Layer 13 source could not be read safely."""


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
        return features[0]

    try:
        fallback_response = await client.get(
            f"{SERVER_URL}/13/query",
            params={**query_params, "where": f"VILLAGE='{village}' AND CTS_CS_NO LIKE '{cts_no}%'"},
        )
        fallback = usable_json(fallback_response)
        fallback_features = fallback.get("features") if fallback else None
        if isinstance(fallback_features, list) and fallback_features:
            return fallback_features[0]
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

    area = resolve_plot_area(attrs)
    area_sqm = area["area_sqm"]
    if not isinstance(area_sqm, (int, float)):
        raise ParcelIngestionError("MCGM parcel has neither an approved nor derivable area.")
    attrs["AREA_APP_SQ_MTRS"] = area_sqm

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
        area_source=area["area_source"],
        latitude=geometry["lat"],
        longitude=geometry["lon"],
        cx=geometry["cx"],
        cy=geometry["cy"],
        mcx=geometry["mcx"],
        mcy=geometry["mcy"],
        xs=geometry["xs"],
        ys=geometry["ys"],
        window_radius=geometry["d"],
    )
    return context, area.get("note")
