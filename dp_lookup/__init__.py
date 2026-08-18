"""
dp-lookup-pro: Enterprise Mumbai Development Plan 2034 Spatial Lookup Engine.
"""

from dp_lookup.cli import format_result_human, main, suggest_villages
from dp_lookup.core.constants import MCGM_VILLAGES, SERVER_URL
from dp_lookup.core.geometry import (
    latlon_to_tile,
    mercator_to_wgs84,
    nearest_road_geoms,
    neighbour_probe_points,
    prepare_geometry,
    road_probe_points,
    tile_to_latlon,
    wgs84_to_utm43n,
)
from dp_lookup.core.orchestrator import lookup_plot_pro
from dp_lookup.core.planning_status import (
    bundle_folder_name,
    crz_flag_from,
    derive_status,
    select_road,
)
from dp_lookup.exporters.dxf import export_dxf
from dp_lookup.exporters.excel import update_excel_register
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.html_map import export_html_map
from dp_lookup.exporters.kml import export_kml
from dp_lookup.exporters.pdf import build_pdf_doc
from dp_lookup.renderers.map_overlay import render_dp_map
from dp_lookup.renderers.satellite import stitch_satellite

__version__ = "3.14.0"

__all__ = [
    "MCGM_VILLAGES",
    "SERVER_URL",
    "build_pdf_doc",
    "bundle_folder_name",
    "crz_flag_from",
    "derive_status",
    "export_dxf",
    "export_geojson",
    "export_html_map",
    "export_kml",
    "format_result_human",
    "latlon_to_tile",
    "lookup_plot_pro",
    "main",
    "mercator_to_wgs84",
    "nearest_road_geoms",
    "neighbour_probe_points",
    "prepare_geometry",
    "render_dp_map",
    "road_probe_points",
    "select_road",
    "stitch_satellite",
    "suggest_villages",
    "tile_to_latlon",
    "update_excel_register",
    "wgs84_to_utm43n",
]
