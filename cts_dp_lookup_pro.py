"""
MCGM SDP 2014-34 DP Lookup Tool — Backward-Compatible Facade.

This module re-exports all `dp_lookup` package components to maintain
100% backward compatibility with existing test suites, CLI entry points,
and standalone scripts.
"""
import io
import math
import sys

from PIL import Image

from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.application.lookup_service import lookup_plot_pro
from dp_lookup.cli import USAGE, format_result_human, main, suggest_villages

# Clients & Cache
from dp_lookup.clients.arcgis import (
    fetch_tile_cached,
    identify_payload,
    map_export_params,
    planning_layers,
    query_spatial_planning_layers,
    spatial_query_payload,
)
from dp_lookup.clients.cache import (
    _STORES,
    _TILE_CACHE,
    bundle_is_intact,
    cache_path_for,
    load_disk_cache,
    read_cache_entry,
    sanitize_query_value,
    save_disk_cache,
    usable_json,
    write_cache_entry,
)

# Core Constants & Validation Regexes
from dp_lookup.core.constants import (
    _CTS_RE,
    _VILLAGE_RE,
    APPLICATION_VERSION,
    CACHE_FILENAME,
    CRZ_LAYER_IDS,
    DEFAULT_CACHE_TTL_SECONDS,
    GENERIC_ROAD_NAMES,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
    MCGM_VILLAGES,
    NEIGHBOUR_LAYERS,
    PLANNING_LAYER_IDS,
    ROAD_EDGE_NUDGES,
    ROAD_EDGE_PROBE_LIMIT,
    ROAD_LAYERS,
    SERVER_URL,
    SLIVER_AREA_THRESHOLD_SQM,
    SLIVER_PERCENT_THRESHOLD,
    WEB_MERCATOR_R,
)

# Core Geometry
from dp_lookup.core.geometry import (
    latlon_to_tile,
    mercator_to_wgs84,
    nearest_road_geoms,
    neighbour_probe_points,
    polygon_area,
    polygon_centroid,
    prepare_geometry,
    resolve_plot_area,
    road_probe_points,
    tile_to_latlon,
    wgs84_to_utm43n,
)
from dp_lookup.core.models import (
    ArtifactManifest,
    EvidenceState,
    LookupResult,
    PlanningRemarks,
    PlotIdentity,
    RegulatoryInfrastructure,
    RunMetadata,
    SourceEvidence,
    SpatialCluster,
)

# Core Planning Status
from dp_lookup.core.planning_status import (
    bundle_folder_name,
    crz_flag_from,
    derive_status,
    filesystem_identity_token,
    select_road,
)
from dp_lookup.core.topology import arcgis_rings_to_geometry

# Exporters
from dp_lookup.exporters.dxf import (
    DXF_LAYERS,
    DXF_LEGEND_ROWS,
    LEGEND_PAD_ROWS,
    LEGEND_VALUE_MAX_CHARS,
    METRES_PER_DEG_LAT,
    METRES_PER_DEG_LON_EQUATOR,
    boxes_overlap,
    clip_path_to_window,
    clip_segment_to_box,
    draw_dxf_legend_column,
    dxf_title_block_lines,
    export_dxf,
    fit_label_to_width,
    legend_column_height,
    legend_data_row,
    legend_data_rows,
    new_dxf_document,
    nudge_text_clear,
    offset_polygon_inward,
    polygon_signed_area,
    project_rings_to_local_metres,
    text_extents,
    title_block_height,
    to_local_metres,
)
from dp_lookup.exporters.excel import update_excel_register
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.html_map import export_html_map
from dp_lookup.exporters.kml import _esc, export_kml
from dp_lookup.exporters.pdf import build_pdf_doc

# Renderers
from dp_lookup.renderers.map_overlay import render_dp_map
from dp_lookup.renderers.satellite import stitch_satellite

__version__ = APPLICATION_VERSION

__all__ = [
    "CACHE_FILENAME",
    "CRZ_LAYER_IDS",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DXF_LAYERS",
    "DXF_LEGEND_ROWS",
    "GENERIC_ROAD_NAMES",
    "LAYER_DESIGNATION",
    "LAYER_METRO",
    "LAYER_MODIFICATION",
    "LAYER_RESERVATION",
    "LAYER_ZONE",
    "LEGEND_PAD_ROWS",
    "LEGEND_VALUE_MAX_CHARS",
    "MCGM_VILLAGES",
    "METRES_PER_DEG_LAT",
    "METRES_PER_DEG_LON_EQUATOR",
    "NEIGHBOUR_LAYERS",
    "PLANNING_LAYER_IDS",
    "ROAD_EDGE_NUDGES",
    "ROAD_EDGE_PROBE_LIMIT",
    "ROAD_LAYERS",
    "SERVER_URL",
    "SLIVER_AREA_THRESHOLD_SQM",
    "SLIVER_PERCENT_THRESHOLD",
    "USAGE",
    "WEB_MERCATOR_R",
    "_CTS_RE",
    "_STORES",
    "_TILE_CACHE",
    "_VILLAGE_RE",
    "ArtifactManifest",
    "EvidenceState",
    "Image",
    "LookupDependencies",
    "LookupResult",
    "PlanningRemarks",
    "PlotIdentity",
    "RegulatoryInfrastructure",
    "RunMetadata",
    "SourceEvidence",
    "SpatialCluster",
    "_esc",
    "arcgis_rings_to_geometry",
    "boxes_overlap",
    "build_pdf_doc",
    "bundle_folder_name",
    "bundle_is_intact",
    "cache_path_for",
    "clip_path_to_window",
    "clip_segment_to_box",
    "crz_flag_from",
    "derive_status",
    "draw_dxf_legend_column",
    "dxf_title_block_lines",
    "export_dxf",
    "export_geojson",
    "export_html_map",
    "export_kml",
    "fetch_tile_cached",
    "filesystem_identity_token",
    "fit_label_to_width",
    "format_result_human",
    "identify_payload",
    "io",
    "latlon_to_tile",
    "legend_column_height",
    "legend_data_row",
    "legend_data_rows",
    "load_disk_cache",
    "lookup_plot_pro",
    "main",
    "map_export_params",
    "math",
    "mercator_to_wgs84",
    "nearest_road_geoms",
    "neighbour_probe_points",
    "new_dxf_document",
    "nudge_text_clear",
    "offset_polygon_inward",
    "planning_layers",
    "polygon_area",
    "polygon_centroid",
    "polygon_signed_area",
    "prepare_geometry",
    "project_rings_to_local_metres",
    "query_spatial_planning_layers",
    "read_cache_entry",
    "render_dp_map",
    "resolve_plot_area",
    "road_probe_points",
    "sanitize_query_value",
    "save_disk_cache",
    "select_road",
    "spatial_query_payload",
    "stitch_satellite",
    "suggest_villages",
    "sys",
    "text_extents",
    "tile_to_latlon",
    "title_block_height",
    "to_local_metres",
    "update_excel_register",
    "usable_json",
    "wgs84_to_utm43n",
    "write_cache_entry",
]

if __name__ == "__main__":
    sys.exit(main())
