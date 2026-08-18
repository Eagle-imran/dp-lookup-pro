"""Backward-compatible ArcGIS client facade.

Protocol payloads, tile caching, and spatial planning policy live in focused
modules. Existing imports remain valid through this re-export surface.
"""

from dp_lookup.clients.arcgis_payloads import (
    identify_payload,
    map_export_params,
    planning_layers,
    spatial_query_payload,
)
from dp_lookup.clients.planning_queries import query_spatial_planning_layers
from dp_lookup.clients.tile_cache import fetch_tile_cached

__all__ = [
    "fetch_tile_cached",
    "identify_payload",
    "map_export_params",
    "planning_layers",
    "query_spatial_planning_layers",
    "spatial_query_payload",
]
