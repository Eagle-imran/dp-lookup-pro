"""Build bounded live ArcGIS probe queries for lookup fallbacks."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Dict, List, Tuple, cast

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.clients.arcgis import identify_payload
from dp_lookup.core.constants import NEIGHBOUR_LAYERS, ROAD_LAYERS, SERVER_URL
from dp_lookup.core.geometry import neighbour_probe_points, road_probe_points

ProbePoint = Tuple[float, float]
ProbeRequest = Awaitable[Any]


def build_live_probe_queries(
    client: Any,
    parcel: ParcelContext,
    *,
    has_local_road: bool,
    has_local_neighbours: bool,
) -> Tuple[List[ProbePoint], List[ProbeRequest], List[ProbePoint], List[ProbeRequest]]:
    """Create rate-limited road and neighbour probes only when local data is absent."""
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
    neighbour_points = cast(
        List[ProbePoint],
        [] if has_local_neighbours else neighbour_probe_points(parcel.mcx, parcel.mcy, parcel.window_radius),
    )
    neighbour_tasks: List[ProbeRequest] = [
        post_limited(
            identify_payload(
                x,
                y,
                NEIGHBOUR_LAYERS,
                parcel.mcx,
                parcel.mcy,
                parcel.window_radius,
                tolerance=30,
                return_geometry=True,
            )
        )
        for x, y in neighbour_points
    ]
    return road_points, road_tasks, neighbour_points, neighbour_tasks
