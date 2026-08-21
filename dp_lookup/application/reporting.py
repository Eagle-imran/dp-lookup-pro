"""Vector, image, PDF, and register generation stage."""

import io
import os
from typing import List

import qrcode
from PIL import Image

from dp_lookup.application.artifacts import run_artifact, run_artifact_in_thread, run_artifact_result
from dp_lookup.application.contracts import ArtifactContext, MapFetchContext
from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.application.exporting import ArtifactExporter, registered_artifact_exporters
from dp_lookup.core.geometry import tile_to_latlon


def export_vector_artifacts(
    context: ArtifactContext,
    dependencies: LookupDependencies,
    warnings: List[str],
) -> None:
    seen_keys = set()
    for exporter in registered_artifact_exporters(dependencies):
        if exporter.manifest_key in seen_keys:
            warnings.append(
                f"Artifact exporter '{exporter.name}' reused manifest key '{exporter.manifest_key}' and was skipped"
            )
            continue
        seen_keys.add(exporter.manifest_key)
        output_path = run_artifact_result(
            exporter.name,
            warnings,
            _export_registered_artifact,
            exporter,
            context,
        )
        if output_path is not None:
            context.artifact_outputs[exporter.manifest_key] = output_path


def _export_registered_artifact(exporter: ArtifactExporter, context: ArtifactContext) -> str:
    """Export and verify that a plug-in produced a cacheable bundle artifact."""
    output_path = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(exporter.export(context)))))
    bundle_folder = os.path.realpath(context.paths.bundle_folder)
    if os.path.commonpath((bundle_folder, output_path)) != bundle_folder:
        raise ValueError("exported artifact must be inside the lookup bundle")
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise ValueError("exported artifact is missing or empty")
    return output_path


async def render_report_artifacts(
    context: ArtifactContext,
    fetched: MapFetchContext,
    dependencies: LookupDependencies,
    warnings: List[str],
) -> None:
    """Render optional visual/report artifacts without hiding partial failure."""
    parcel = context.parcel
    planning = context.planning
    road = context.road
    paths = context.paths
    dp_response = fetched.dp_response
    dp_map_ok = (
        not isinstance(dp_response, Exception)
        and getattr(dp_response, "status_code", None) == 200
        and dp_response.headers.get("content-type", "").startswith("image")
    )
    if not dp_map_ok:
        warnings.append("DP base map could not be fetched; the map image is a blank placeholder")

    labels = {
        "cts": parcel.cts_no,
        "village": parcel.village.upper(),
        "ward": parcel.attrs["WARD"],
        "zone": planning.zone,
        "area": parcel.area_sqm,
        "status": planning.status_badge[:30],
    }
    dp_images = []

    def render_dp() -> None:
        dp_images.append(
            dependencies.dp_map_renderer(
                dp_response.content if dp_map_ok else None,
                parcel.rings,
                bbox=fetched.bbox,
                size=fetched.size,
                labels=labels,
            )
        )

    run_artifact("DP map rendering", warnings, render_dp)
    dp_image = dp_images[0] if dp_images else Image.new("RGB", fetched.size, "white")

    tile_values = [] if isinstance(fetched.satellite_tiles, Exception) else list(fetched.satellite_tiles)
    missing_tiles = (
        len(fetched.satellite_coordinates)
        if isinstance(fetched.satellite_tiles, Exception)
        else sum(1 for tile in tile_values if isinstance(tile, Exception) or not tile)
    )
    if len(tile_values) < len(fetched.satellite_coordinates):
        if not isinstance(fetched.satellite_tiles, Exception):
            missing_tiles += len(fetched.satellite_coordinates) - len(tile_values)
        tile_values.extend([None] * (len(fetched.satellite_coordinates) - len(tile_values)))
    elif len(tile_values) > len(fetched.satellite_coordinates):
        tile_values = tile_values[: len(fetched.satellite_coordinates)]
    if missing_tiles:
        warnings.append(f"{missing_tiles} of {len(fetched.satellite_coordinates)} satellite tiles failed to load")
    half_dimension = fetched.grid_dimension // 2
    top_lat, left_lon = tile_to_latlon(
        fetched.tile_x - half_dimension,
        fetched.tile_y - half_dimension,
        fetched.zoom,
    )
    bottom_lat, right_lon = tile_to_latlon(
        fetched.tile_x + half_dimension + 1,
        fetched.tile_y + half_dimension + 1,
        fetched.zoom,
    )
    satellite_images = []

    def render_satellite() -> None:
        satellite_images.append(
            dependencies.satellite_renderer(
                tile_values or [None] * len(fetched.satellite_coordinates),
                fetched.satellite_coordinates,
                fetched.grid_dimension,
                parcel.wgs_rings,
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
        )

    run_artifact("satellite rendering", warnings, render_satellite)
    satellite_image = (
        satellite_images[0]
        if satellite_images
        else Image.new("RGB", (fetched.grid_dimension * 256, fetched.grid_dimension * 256), "white")
    )

    def save_images() -> None:
        dp_image.convert("RGB").save(paths.dp_map, "PNG", compress_level=1)
        satellite_image.convert("RGB").save(paths.satellite, "PNG", compress_level=1)

    await run_artifact_in_thread("map images", warnings, save_images)

    qr_bytes = io.BytesIO()

    def render_qr() -> None:
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(context.map_link)
        qr.make(fit=True)
        qr.make_image(fill_color="black", back_color="white").save(qr_bytes, format="PNG")

    if not run_artifact("QR code", warnings, render_qr):
        qr_bytes.seek(0)
        qr_bytes.truncate(0)
        Image.new("RGB", (64, 64), "white").save(qr_bytes, format="PNG")
    qr_bytes.seek(0)

    await run_artifact_in_thread(
        "PDF report",
        warnings,
        dependencies.pdf_writer,
        paths.pdf,
        planning.status_badge,
        planning.status_summary,
        parcel.village,
        parcel.attrs,
        parcel.cts_no,
        planning.zone,
        planning.designation_description,
        planning.designation_code,
        planning.modification_approval,
        planning.modification_label,
        planning.crz_status,
        planning.metro_buffer,
        road.name,
        road.width,
        paths.dp_map,
        qr_bytes,
        context.map_link,
        paths.satellite,
        context.neighbours.plots,
        (
            "MCGM cadastral parcel record"
            if parcel.area_source == "Recorded plot area"
            else "Calculated from the MCGM cadastral parcel boundary for screening"
        ),
        res_code=planning.reservation_code,
        res_type=planning.reservation_type,
        reservations=planning.reservations,
        designations=planning.designations,
        encumbered_percent=planning.encumbered_percent,
        encumbered_area_sqm=planning.encumbered_area_sqm,
        net_unencumbered_sqm=planning.net_unencumbered_sqm,
    )
    names = paths.filenames
    run_artifact(
        "Excel register",
        warnings,
        dependencies.excel_writer,
        register_path=paths.register,
        attrs=parcel.attrs,
        village=parcel.village,
        cts_number=parcel.cts_no,
        zone=planning.zone,
        status_badge=planning.status_badge,
        res_code=planning.reservation_code,
        res_type=planning.reservation_type,
        des_code=planning.designation_code,
        des_desc=planning.designation_description,
        mod_approval=planning.modification_approval,
        mod_label=planning.modification_label,
        mod_doc=planning.modification_document,
        crz_buffer_flag=planning.crz_status,
        metro_buffer_flag=planning.metro_buffer,
        road_name=road.name,
        road_width=road.width,
        neighbors=context.neighbours.plots,
        dp_snapshot_fname=names["dp_map"],
        sat_snapshot_fname=names["satellite"],
        pdf_fname=names["pdf"],
        dxf_fname=names["dxf"],
        geojson_fname=names["geojson"],
        kml_fname=names["kml"],
        map_link=context.map_link,
        reservations=planning.reservations,
        designations=planning.designations,
    )
