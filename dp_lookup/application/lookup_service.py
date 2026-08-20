"""Stable application facade coordinating one complete DP plot lookup."""

import asyncio
import os
import sys
import time
from typing import Any, Callable, Dict, Optional

from dp_lookup.application.contracts import ArtifactContext, MapFetchContext
from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES, LookupDependencies
from dp_lookup.application.ingestion import ParcelIngestionError, build_parcel_context, not_found_result
from dp_lookup.application.local_spatial import parcel_source_notes
from dp_lookup.application.normalization import (
    PlanningEvidenceError,
    normalize_planning_evidence,
    parse_neighbour_responses,
    parse_road_responses,
)
from dp_lookup.application.output_layout import (
    build_export_data,
    build_map_link,
    build_output_paths,
)
from dp_lookup.application.planning_evidence import (
    cache_suppression_warning,
    evidence_cache_key,
    normalize_evidence_stage,
)
from dp_lookup.application.reporting import export_vector_artifacts, render_report_artifacts
from dp_lookup.application.result_factory import build_lookup_result
from dp_lookup.application.telemetry import RunDiagnostics
from dp_lookup.clients.arcgis import (
    identify_payload,
    map_export_params,
    planning_layers,
)
from dp_lookup.clients.cache import read_cache_entry, write_cache_entry
from dp_lookup.clients.local_parcels import LocalParcelError
from dp_lookup.clients.validation import sanitize_query_value
from dp_lookup.core.constants import (
    _CTS_RE,
    _VILLAGE_RE,
    CRZ_LAYER_IDS,
    DEFAULT_CACHE_TTL_SECONDS,
    NEIGHBOUR_LAYERS,
    ROAD_LAYERS,
    SERVER_URL,
)
from dp_lookup.core.geometry import (
    latlon_to_tile,
    nearest_road_geoms,
    neighbour_probe_points,
    road_probe_points,
)
from dp_lookup.core.villages import suggest_villages
from dp_lookup.planning_evidence.models import EvidenceMode


async def _cancel_and_drain(task: Any) -> None:
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def lookup_plot_pro(
    village: str,
    cts_number: str,
    output_dir: str = "./output",
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    timeout_seconds: float = 20.0,
    on_data: Optional[Callable[[Dict[str, Any]], None]] = None,
    verify_tls: bool = True,
    dependencies: Optional[LookupDependencies] = None,
) -> Dict[str, Any]:
    """Look up one parcel and generate its planning evidence bundle."""
    started = time.perf_counter()
    diagnostics = RunDiagnostics()
    deps = dependencies or DEFAULT_DEPENDENCIES
    try:
        evidence_mode = EvidenceMode.parse(deps.planning_evidence_mode)
    except ValueError as exc:
        diagnostics.mark("planning_evidence", outcome="invalid_mode")
        return {"error": str(exc), "diagnostics": diagnostics.snapshot()}
    try:
        safe_village = sanitize_query_value(village, _VILLAGE_RE, "village", 64)
        safe_cts = sanitize_query_value(cts_number, _CTS_RE, "cts_number", 32)
    except ValueError as exc:
        diagnostics.mark("validation", outcome="rejected")
        return {
            "error": str(exc),
            "suggestions": suggest_villages(village),
            "diagnostics": diagnostics.snapshot(),
        }
    diagnostics.mark("validation", outcome="accepted")

    village_upper = safe_village.upper()
    parcel_key = f"{village_upper}:{safe_cts}"
    if deps.parcel_cache_namespace != "live":
        parcel_key = f"{deps.parcel_cache_namespace}:{parcel_key}"
    cache_key = evidence_cache_key(parcel_key, evidence_mode)
    output_root = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(output_dir))))
    os.makedirs(output_root, exist_ok=True)
    if use_cache:
        cached = read_cache_entry(output_root, cache_key, ttl_seconds=cache_ttl_seconds)
        if cached is not None:
            diagnostics.mark("cache_lookup", outcome="hit")
            cached.setdefault("metadata", {})["diagnostics"] = diagnostics.snapshot()
            if on_data is not None:
                try:
                    on_data(cached)
                except Exception:
                    pass
            return cached
    diagnostics.mark("cache_lookup", outcome="miss" if use_cache else "disabled")
    warnings, notes = [], []
    async with deps.client_factory(timeout_seconds, verify_tls=verify_tls) as client:
        try:
            feature = await deps.parcel_fetcher(client, village_upper, safe_cts)
            if feature is None:
                diagnostics.mark("parcel_ingestion", outcome="not_found")
                result = not_found_result(village_upper, safe_cts)
                result["diagnostics"] = diagnostics.snapshot()
                return result
            parcel, area_note = build_parcel_context(feature, safe_village, safe_cts)
        except (ParcelIngestionError, LocalParcelError) as exc:
            diagnostics.mark("parcel_ingestion", outcome="failed")
            return {"error": str(exc), "diagnostics": diagnostics.snapshot()}
        diagnostics.mark("parcel_ingestion", outcome="confirmed")
        if area_note:
            notes.append(area_note)
        notes.extend(parcel_source_notes(parcel))

        try:
            local_neighbours = deps.neighbour_provider(parcel)
        except Exception as exc:
            local_neighbours = None
            notes.append(f"Local adjacency was unavailable; live neighbour probes were used ({exc}).")

        try:
            local_road = deps.road_provider(parcel)
        except Exception as exc:
            local_road = None
            notes.append(f"Local road analysis was unavailable; live road probes were used ({exc}).")
        paths = build_output_paths(output_root, parcel)
        os.makedirs(paths.bundle_folder, exist_ok=True)
        crz_layers = list(CRZ_LAYER_IDS)
        identify_task = (
            client.post(
                f"{SERVER_URL}/identify",
                data=identify_payload(
                    parcel.cx,
                    parcel.cy,
                    planning_layers(crz_layers),
                    parcel.mcx,
                    parcel.mcy,
                    parcel.window_radius,
                    tolerance=30,
                    return_geometry=False,
                ),
            )
            if deps.planning_identify_required
            else asyncio.sleep(0, result=None)
        )

        half = max(
            70,
            max(max(parcel.xs) - min(parcel.xs), max(parcel.ys) - min(parcel.ys)) * 0.9,
        )
        width, height = 1000, 1000
        bbox = (
            parcel.mcx - half,
            parcel.mcy - half,
            parcel.mcx + half,
            parcel.mcy + half,
        )
        dp_map_task = client.get(
            f"{SERVER_URL}/export",
            params=map_export_params(*bbox, width, height),
        )

        semaphore = asyncio.Semaphore(6)

        async def post_limited(data: dict):
            async with semaphore:
                return await client.post(f"{SERVER_URL}/identify", data=data)

        road_points = [] if local_road else road_probe_points(
            parcel.rings[0],
            parcel.mcx,
            parcel.mcy,
            parcel.xs,
            parcel.ys,
        )
        road_tasks = [
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
        neighbour_points = [] if local_neighbours else neighbour_probe_points(
            parcel.mcx, parcel.mcy, parcel.window_radius
        )
        neighbour_tasks = [
            post_limited(identify_payload(
                x, y, NEIGHBOUR_LAYERS, parcel.mcx, parcel.mcy,
                parcel.window_radius, tolerance=30, return_geometry=True,
            ))
            for x, y in neighbour_points
        ]

        zoom, grid_dimension = 18, 3
        tile_x, tile_y = latlon_to_tile(parcel.latitude, parcel.longitude, zoom)
        half_grid = grid_dimension // 2
        satellite_coordinates = []
        satellite_tasks = []
        for delta_y in range(-half_grid, half_grid + 1):
            for delta_x in range(-half_grid, half_grid + 1):
                x, y = tile_x + delta_x, tile_y + delta_y
                satellite_tasks.append(deps.tile_fetcher(client, zoom, y, x))
                satellite_coordinates.append((delta_x + half_grid, delta_y + half_grid))

        slow_group = asyncio.gather(
            dp_map_task,
            asyncio.gather(*satellite_tasks, return_exceptions=True),
            return_exceptions=True,
        )
        fast_results = await asyncio.gather(
            identify_task,
            deps.spatial_planning_query(client, parcel.rings),
            asyncio.gather(*road_tasks, return_exceptions=True),
            asyncio.gather(*neighbour_tasks, return_exceptions=True),
            (
                deps.planning_evidence_analyzer(client, parcel.rings, village_upper, evidence_mode)
                if evidence_mode is not EvidenceMode.BASIC
                else asyncio.sleep(0, result=None)
            ),
            return_exceptions=True,
        )
        diagnostics.mark("source_queries")
        road = local_road or parse_road_responses(fast_results[2], len(road_points))
        neighbours = local_neighbours or parse_neighbour_responses(
            fast_results[3], len(neighbour_points), safe_cts, safe_village
        )
        warnings.extend(road.warnings)
        warnings.extend(neighbours.warnings)
        if isinstance(fast_results[1], dict):
            planning_provenance = fast_results[1].get("provenance")
            if isinstance(planning_provenance, dict) and planning_provenance.get("fallback"):
                fallback_reason = planning_provenance.get("fallback_reason") or "local planning data was unavailable"
                notes.append(f"Local planning database was not used: {fallback_reason}")
        try:
            planning = normalize_planning_evidence(
                fast_results[1],
                fast_results[0],
                parcel.area_sqm,
                parcel.wgs_rings,
                crz_layers,
            )
        except PlanningEvidenceError as exc:
            await _cancel_and_drain(slow_group)
            diagnostics.mark("normalization", outcome="failed_closed")
            return {
                "error": (
                    f"{exc} No planning status or report was generated because missing "
                    "planning evidence must not be interpreted as a clear parcel. Please retry."
                ),
                "partial_data": {
                    "village": village_upper,
                    "cts_no": safe_cts,
                    "ward": str(parcel.attrs.get("WARD")),
                    "area_sqm": parcel.area_sqm,
                },
                "diagnostics": diagnostics.snapshot(),
            }
        warnings.extend(planning.warnings)
        diagnostics.mark("normalization", outcome="complete" if not planning.warnings else "partial")

        planning_due_diligence, evidence_outcome, evidence_detail, evidence_note = normalize_evidence_stage(fast_results[4], evidence_mode)
        if evidence_mode is not EvidenceMode.BASIC:
            diagnostics.mark("planning_evidence", outcome=evidence_outcome, detail=evidence_detail)
        if evidence_note:
            notes.append(evidence_note)

        map_link = build_map_link(parcel)
        export_data = build_export_data(parcel, planning, road, neighbours, map_link)
        artifact_context = ArtifactContext(
            parcel=parcel,
            planning=planning,
            road=road,
            neighbours=neighbours,
            paths=paths,
            map_link=map_link,
            export_data=export_data,
            nearest_roads=nearest_road_geoms(road.geometries, parcel.wgs_rings),
        )
        export_vector_artifacts(artifact_context, deps, warnings)
        diagnostics.mark("vector_artifacts")

        if on_data is not None:
            snapshot = build_lookup_result(
                parcel,
                planning,
                road,
                neighbours,
                paths,
                map_link,
                round((time.perf_counter() - started) * 1000, 1),
                True,
                warnings,
                notes,
                diagnostics.snapshot(),
                artifact_context.artifact_outputs,
                planning_due_diligence,
            )
            try:
                on_data(snapshot)
            except Exception as exc:
                print(f"[dp-lookup-pro] on_data callback raised: {exc}", file=sys.stderr)

        slow_results = await slow_group
        await render_report_artifacts(
            artifact_context,
            MapFetchContext(
                dp_response=slow_results[0],
                satellite_tiles=slow_results[1],
                satellite_coordinates=satellite_coordinates,
                bbox=bbox,
                size=(width, height),
                tile_x=tile_x,
                tile_y=tile_y,
                zoom=zoom,
                grid_dimension=grid_dimension,
            ),
            deps,
            warnings,
        )
        diagnostics.mark("report_artifacts")

    diagnostics.mark("complete", outcome="partial" if warnings else "complete")
    result = build_lookup_result(
        parcel,
        planning,
        road,
        neighbours,
        paths,
        map_link,
        round((time.perf_counter() - started) * 1000, 1),
        False,
        warnings,
        notes,
        diagnostics.snapshot(),
        artifact_context.artifact_outputs,
        planning_due_diligence,
    )
    cache_warning = cache_suppression_warning(warnings, planning_due_diligence)
    if cache_warning:
        print(f"[dp-lookup-pro] WARNING: {cache_warning}", file=sys.stderr)
    else:
        write_cache_entry(output_root, cache_key, result)
    return result
