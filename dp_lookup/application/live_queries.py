"""Build live ArcGIS queries for roads and adjoining parcels."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Dict, List, Tuple, cast

from dp_lookup.application.contracts import NeighbourContext, ParcelContext
from dp_lookup.application.neighbour_normalization import ADJACENCY_TOLERANCE_M, parse_live_neighbours
from dp_lookup.clients.arcgis import identify_payload, spatial_query_payload
from dp_lookup.core.constants import ROAD_LAYERS, SERVER_URL
from dp_lookup.core.geometry import road_probe_points
from dp_lookup.core.topology import arcgis_rings_to_geometry

ProbePoint = Tuple[float, float]
ProbeRequest = Awaitable[Any]


def build_live_road_queries(
    client: Any,
    parcel: ParcelContext,
    *,
    has_local_road: bool,
) -> Tuple[List[ProbePoint], List[ProbeRequest]]:
    """Create rate-limited road probes only when local data is absent."""
    semaphore = asyncio.Semaphore(6)

    async def post_limited(data: Dict[str, Any]) -> Any:
        async with semaphore:
            return await client.post(f"{SERVER_URL}/identify", data=data)

    road_points = cast(
        List[ProbePoint],
        [] if has_local_road else road_probe_points(parcel.rings[0], parcel.mcx, parcel.mcy, parcel.xs, parcel.ys),
    )
    road_tasks: List[ProbeRequest] = [
        post_limited(
            identify_payload(
                x,
                y,
                ROAD_LAYERS,
                parcel.mcx,
                parcel.mcy,
                parcel.window_radius,
                tolerance=50,
                return_geometry=True,
            )
        )
        for x, y in road_points
    ]
    return road_points, road_tasks


async def query_live_neighbours(client: Any, parcel: ParcelContext) -> NeighbourContext:
    """Fetch boundaries within the same search bounds used by the local database."""
    subject = arcgis_rings_to_geometry(parcel.rings)
    min_x, min_y, max_x, max_y = subject.bounds
    margin = ADJACENCY_TOLERANCE_M
    params = spatial_query_payload(f"{min_x - margin},{min_y - margin},{max_x + margin},{max_y + margin}")
    params["outFields"] = "OBJECTID,VILLAGE,CTS_CS_NO,AREA_APP_SQ_MTRS"
    response = await client.get(f"{SERVER_URL}/13/query", params=params)
    return parse_live_neighbours(response, parcel, subject)
