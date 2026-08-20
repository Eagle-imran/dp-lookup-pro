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
from dp_lookup.clients.local_planning import (
    LocalFirstPlanningQuery,
    LocalPlanningError,
    PlanningSnapshot,
    PlanningSnapshotStore,
)
from dp_lookup.clients.planning_evidence_queries import (
    LocalFirstPlanningEvidenceAnalyzer,
    LocalPlanningEvidenceError,
)
from dp_lookup.clients.planning_queries import query_spatial_planning_layers
from dp_lookup.clients.tile_cache import fetch_tile_cached

__all__ = [
    "LocalFirstPlanningEvidenceAnalyzer",
    "LocalFirstPlanningQuery",
    "LocalPlanningError",
    "LocalPlanningEvidenceError",
    "PlanningSnapshot",
    "PlanningSnapshotStore",
    "fetch_tile_cached",
    "identify_payload",
    "map_export_params",
    "planning_layers",
    "query_spatial_planning_layers",
    "spatial_query_payload",
]
