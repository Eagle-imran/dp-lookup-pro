"""Typed map-image artifact construction used by report-stage exporters."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, List

import qrcode
from PIL import Image

from dp_lookup.application.artifacts import run_artifact, run_artifact_in_thread
from dp_lookup.application.contracts import (
    ArtifactContext,
    DpMapRenderRequest,
    MapFetchContext,
    RenderedMapAssets,
    SatelliteRenderRequest,
)
from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.core.geometry import tile_to_latlon


@dataclass(frozen=True)
class LegacyDpMapRenderer:
    """Typed adapter for the stable positional DP-map renderer function."""

    renderer: Any

    def render(self, request: DpMapRenderRequest) -> Image.Image:
        return self.renderer(
            request.base_png,
            request.rings,
            bbox=request.bbox,
            size=request.size,
            labels=dict(request.labels),
        )


@dataclass(frozen=True)
class LegacySatelliteRenderer:
    """Typed adapter for the stable positional satellite renderer function."""

    renderer: Any

    def render(self, request: SatelliteRenderRequest) -> Image.Image:
        return self.renderer(
            request.tiles,
            request.coordinates,
            request.grid_dimension,
            request.wgs_rings,
            bounds=request.bounds,
            labels=dict(request.labels),
        )


@dataclass(frozen=True)
class MapImageArtifactExporter:
    """Produces the map images consumed by report-stage artifact exporters."""

    dependencies: LookupDependencies
    name: str = "map images"

    async def export(
        self,
        context: ArtifactContext,
        fetched: MapFetchContext,
        warnings: List[str],
    ) -> RenderedMapAssets:
        dp_image = self._render_dp_image(context, fetched, warnings)
        satellite_image = self._render_satellite_image(context, fetched, warnings)
        await self._save_images(context, dp_image, satellite_image, warnings)
        return RenderedMapAssets(
            dp_map_path=context.paths.dp_map,
            satellite_path=context.paths.satellite,
            qr_png=self._render_qr(context, warnings),
        )

    def _render_dp_image(
        self,
        context: ArtifactContext,
        fetched: MapFetchContext,
        warnings: List[str],
    ) -> Image.Image:
        response = fetched.dp_response
        dp_map_ok = (
            not isinstance(response, Exception)
            and getattr(response, "status_code", None) == 200
            and response.headers.get("content-type", "").startswith("image")
        )
        if not dp_map_ok:
            warnings.append("DP base map could not be fetched; the map image is a blank placeholder")
        parcel = context.parcel
        request = DpMapRenderRequest(
            base_png=response.content if dp_map_ok else None,
            rings=parcel.rings,
            bbox=fetched.bbox,
            size=fetched.size,
            labels={
                "cts": parcel.cts_no,
                "village": parcel.village.upper(),
                "ward": parcel.attrs["WARD"],
                "zone": context.planning.zone,
                "area": parcel.area_sqm,
                "status": context.planning.status_badge[:30],
            },
        )
        image: List[Image.Image] = []
        adapter = LegacyDpMapRenderer(self.dependencies.dp_map_renderer)
        run_artifact("DP map rendering", warnings, lambda: image.append(adapter.render(request)))
        return image[0] if image else Image.new("RGB", fetched.size, "white")

    def _render_satellite_image(
        self,
        context: ArtifactContext,
        fetched: MapFetchContext,
        warnings: List[str],
    ) -> Image.Image:
        tiles = _normalised_tiles(fetched, warnings)
        half_dimension = fetched.grid_dimension // 2
        top_lat, left_lon = tile_to_latlon(fetched.tile_x - half_dimension, fetched.tile_y - half_dimension, fetched.zoom)
        bottom_lat, right_lon = tile_to_latlon(
            fetched.tile_x + half_dimension + 1,
            fetched.tile_y + half_dimension + 1,
            fetched.zoom,
        )
        parcel = context.parcel
        request = SatelliteRenderRequest(
            tiles=tiles,
            coordinates=fetched.satellite_coordinates,
            grid_dimension=fetched.grid_dimension,
            wgs_rings=parcel.wgs_rings,
            bounds=(top_lat, left_lon, bottom_lat, right_lon),
            labels={
                "cts": parcel.cts_no,
                "village": parcel.village.upper(),
                "ward": parcel.attrs["WARD"],
                "lat": parcel.latitude,
                "lon": parcel.longitude,
                "neighbours": len(context.neighbours.plots),
            },
        )
        image: List[Image.Image] = []
        adapter = LegacySatelliteRenderer(self.dependencies.satellite_renderer)
        run_artifact("satellite rendering", warnings, lambda: image.append(adapter.render(request)))
        fallback_size = (fetched.grid_dimension * 256, fetched.grid_dimension * 256)
        return image[0] if image else Image.new("RGB", fallback_size, "white")

    async def _save_images(
        self,
        context: ArtifactContext,
        dp_image: Image.Image,
        satellite_image: Image.Image,
        warnings: List[str],
    ) -> None:
        def save() -> None:
            dp_image.convert("RGB").save(context.paths.dp_map, "PNG", compress_level=1)
            satellite_image.convert("RGB").save(context.paths.satellite, "PNG", compress_level=1)

        await run_artifact_in_thread(self.name, warnings, save)

    @staticmethod
    def _render_qr(context: ArtifactContext, warnings: List[str]) -> io.BytesIO:
        qr_bytes = io.BytesIO()

        def render() -> None:
            qr = qrcode.QRCode(box_size=4, border=1)
            qr.add_data(context.map_link)
            qr.make(fit=True)
            qr.make_image(fill_color="black", back_color="white").save(qr_bytes, format="PNG")

        if not run_artifact("QR code", warnings, render):
            qr_bytes.seek(0)
            qr_bytes.truncate(0)
            Image.new("RGB", (64, 64), "white").save(qr_bytes, format="PNG")
        qr_bytes.seek(0)
        return qr_bytes


def _normalised_tiles(fetched: MapFetchContext, warnings: List[str]) -> List[Any]:
    tiles = [] if isinstance(fetched.satellite_tiles, Exception) else list(fetched.satellite_tiles)
    missing = (
        len(fetched.satellite_coordinates)
        if isinstance(fetched.satellite_tiles, Exception)
        else sum(1 for tile in tiles if isinstance(tile, Exception) or not tile)
    )
    if len(tiles) < len(fetched.satellite_coordinates):
        if not isinstance(fetched.satellite_tiles, Exception):
            missing += len(fetched.satellite_coordinates) - len(tiles)
        tiles.extend([None] * (len(fetched.satellite_coordinates) - len(tiles)))
    elif len(tiles) > len(fetched.satellite_coordinates):
        tiles = tiles[: len(fetched.satellite_coordinates)]
    if missing:
        warnings.append(f"{missing} of {len(fetched.satellite_coordinates)} satellite tiles failed to load")
    return tiles or [None] * len(fetched.satellite_coordinates)
