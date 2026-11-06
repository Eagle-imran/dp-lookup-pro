"""Concurrent online visual-asset fetch boundary for one lookup."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, List, Tuple

from dp_lookup.application.contracts import MapFetchContext, ParcelContext
from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.application.telemetry import RunDiagnostics
from dp_lookup.clients.arcgis import map_export_params
from dp_lookup.core.constants import SERVER_URL
from dp_lookup.core.geometry import latlon_to_tile, mercator_to_wgs84, tile_to_latlon


@dataclass(frozen=True)
class VisualFetchSession:
    """A started map/tile fetch and the metadata needed to render it."""

    task: Any
    started: float
    satellite_coordinates: List[Tuple[int, int]]
    bbox: Tuple[float, float, float, float]
    size: Tuple[int, int]
    tile_x: int
    tile_y: int
    zoom: int
    grid_dimension: int

    async def resolve(self, diagnostics: RunDiagnostics) -> MapFetchContext:
        results = await diagnostics.wait("visual_fetch_wait", self.task)
        diagnostics.record_span("visual_fetch_total", self.started)
        return MapFetchContext(
            dp_response=results[0],
            satellite_tiles=results[1],
            satellite_coordinates=self.satellite_coordinates,
            bbox=self.bbox,
            size=self.size,
            tile_x=self.tile_x,
            tile_y=self.tile_y,
            zoom=self.zoom,
            grid_dimension=self.grid_dimension,
        )


def start_visual_fetch(
    client: Any,
    parcel: ParcelContext,
    dependencies: LookupDependencies,
    diagnostics: RunDiagnostics,
) -> VisualFetchSession:
    """Start the DP-map and satellite fetches without blocking planning work."""
    half = max(
        70,
        max(max(parcel.xs) - min(parcel.xs), max(parcel.ys) - min(parcel.ys)) * 0.9,
    )
    size = (1000, 1000)
    bbox = (
        parcel.mcx - half,
        parcel.mcy - half,
        parcel.mcx + half,
        parcel.mcy + half,
    )
    dp_map = diagnostics.wait(
        "dp_map_fetch",
        client.get(
            f"{SERVER_URL}/export",
            params=map_export_params(*bbox, *size),
        ),
    )

    zoom, grid_dimension = 18, 3
    center_lon, center_lat = mercator_to_wgs84(parcel.mcx, parcel.mcy)
    min_lon, min_lat = mercator_to_wgs84(min(parcel.xs), min(parcel.ys))
    max_lon, max_lat = mercator_to_wgs84(max(parcel.xs), max(parcel.ys))
    # Keep the nine-tile download, but fit every plot part rather than centring
    # a fixed zoom on the representative point of just one part.
    while True:
        tile_x, tile_y = latlon_to_tile(center_lat, center_lon, zoom)
        top, left = tile_to_latlon(tile_x - 1, tile_y - 1, zoom)
        bottom, right = tile_to_latlon(tile_x + 2, tile_y + 2, zoom)
        lon_padding = (right - left) / 32  # 24 pixels clear of the image edge.
        lat_padding = (top - bottom) / 32
        if zoom == 0 or (
            left + lon_padding <= min_lon <= max_lon <= right - lon_padding
            and bottom + lat_padding <= min_lat <= max_lat <= top - lat_padding
        ):
            break
        zoom -= 1
    half_grid = grid_dimension // 2
    coordinates: List[Tuple[int, int]] = []
    tiles = []
    for delta_y in range(-half_grid, half_grid + 1):
        for delta_x in range(-half_grid, half_grid + 1):
            x, y = tile_x + delta_x, tile_y + delta_y
            tiles.append(dependencies.tile_fetcher(client, zoom, y, x))
            coordinates.append((delta_x + half_grid, delta_y + half_grid))

    started = time.perf_counter()
    task = asyncio.gather(
        dp_map,
        diagnostics.wait(
            "satellite_tile_fetch",
            asyncio.gather(*tiles, return_exceptions=True),
        ),
        return_exceptions=True,
    )
    return VisualFetchSession(task, started, coordinates, bbox, size, tile_x, tile_y, zoom, grid_dimension)


__all__ = ["VisualFetchSession", "start_visual_fetch"]
