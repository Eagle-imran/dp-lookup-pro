"""Composition root for the lookup CLI's local/live adapters."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional

from dp_lookup.application.authority_resolver import AuthorityResolver
from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES, LookupDependencies
from dp_lookup.application.ingestion import fetch_parcel_feature
from dp_lookup.application.local_roads import LocalRoadProvider
from dp_lookup.application.local_spatial import LocalNeighbourProvider
from dp_lookup.authority import AuthorityStore, AuthorityStoreError
from dp_lookup.clients.local_parcels import LocalParcelFetcher
from dp_lookup.clients.local_planning import LocalFirstPlanningQuery
from dp_lookup.clients.planning_evidence_queries import LocalFirstPlanningEvidenceAnalyzer
from dp_lookup.planning_evidence.models import EvidenceMode
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore, SpatialStoreError

SnapshotSelector = Callable[[str, str], tuple[str, Optional[int]]]


def local_snapshot_selection(source_mode: str, database_path: str) -> tuple[str, Optional[int]]:
    """Pin active parcel/planning versions in the report-cache namespace."""
    path = Path(database_path).expanduser().resolve()
    active_snapshot_id: Optional[int] = None
    try:
        if path.is_file():
            with SnapshotStore.open(path) as store:
                active_snapshot_id = store.active_snapshot_id()
    except (OSError, sqlite3.DatabaseError, SpatialStoreError):
        active_snapshot_id = None
    planning_snapshot_id: Optional[int] = None
    try:
        if path.is_file():
            with PlanningSnapshotStore.open(path) as planning_store:
                planning_snapshot_id = planning_store.active_snapshot_id()
    except (OSError, sqlite3.DatabaseError):
        planning_snapshot_id = None
    cache_snapshot: Any = active_snapshot_id if active_snapshot_id is not None else "unavailable"
    planning_cache_snapshot: Any = planning_snapshot_id if planning_snapshot_id is not None else "unavailable"
    authority_revision: Any = "unavailable"
    try:
        if path.is_file():
            with AuthorityStore.open(path, create=False) as authority_store:
                authority_revision = authority_store.revision()
    except (OSError, sqlite3.DatabaseError, AuthorityStoreError):
        authority_revision = "unavailable"
    return (
        f"{source_mode}:{path}:snapshot={cache_snapshot}:planning_snapshot={planning_cache_snapshot}:"
        f"authority_revision={authority_revision}",
        active_snapshot_id,
    )


@dataclass
class LookupRuntime:
    """Owned resources and immutable dependencies for one CLI invocation."""

    dependencies: LookupDependencies
    planning_store: Optional[Any] = None
    authority_store: Optional[AuthorityStore] = None
    parcel_store: Optional[SnapshotStore] = None

    def close(self) -> None:
        """Close stores opened while composing local adapters."""
        if self.parcel_store is not None:
            self.parcel_store.close()
            self.parcel_store = None
        if self.planning_store is not None:
            self.planning_store.close()
            self.planning_store = None
        if self.authority_store is not None:
            self.authority_store.close()
            self.authority_store = None

    def __enter__(self) -> "LookupRuntime":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()


def compose_lookup_runtime(
    source_mode: str,
    database_path: Optional[str],
    evidence_mode: EvidenceMode,
    *,
    snapshot_selector: SnapshotSelector = local_snapshot_selection,
    base_dependencies: LookupDependencies = DEFAULT_DEPENDENCIES,
    parcel_fallback: Any = fetch_parcel_feature,
) -> LookupRuntime:
    """Build one lookup's dependency graph and retain owned store handles."""
    dependencies = replace(base_dependencies, planning_evidence_mode=evidence_mode)
    parcel_store: Optional[SnapshotStore] = None
    planning_store: Optional[Any] = None
    authority_store: Optional[AuthorityStore] = None
    if source_mode != "live":
        if database_path is None:
            raise ValueError("--database PATH is required for local source mode")
        cache_namespace, selected_snapshot_id = snapshot_selector(source_mode, database_path)
        database = Path(database_path)
        if database.is_file():
            try:
                parcel_store = SnapshotStore.open(database)
            except (OSError, sqlite3.DatabaseError, SpatialStoreError):
                parcel_store = None
            try:
                planning_store = PlanningSnapshotStore.open(database)
            except (OSError, sqlite3.DatabaseError):
                planning_store = None
        dependencies = replace(
            dependencies,
            parcel_cache_namespace=cache_namespace,
            parcel_fetcher=LocalParcelFetcher(
                database,
                fallback=parcel_fallback if source_mode == "auto" else None,
                snapshot_id=selected_snapshot_id,
                store=parcel_store,
            ),
            neighbour_provider=LocalNeighbourProvider(database, store=parcel_store),
            road_provider=LocalRoadProvider(planning_store),
            planning_identify_required=False,
            spatial_planning_query=LocalFirstPlanningQuery(
                planning_store,
                mode=source_mode,
                max_snapshot_age_days=210.0,
                allow_stale_local=source_mode == "local",
            ),
            planning_evidence_analyzer=LocalFirstPlanningEvidenceAnalyzer(
                planning_store,
                mode=source_mode,
                max_snapshot_age_days=210.0,
                allow_stale_local=source_mode == "local",
            ),
        )
    if database_path and Path(database_path).is_file():
        try:
            authority_store = AuthorityStore.open(Path(database_path), create=False)
        except (OSError, sqlite3.DatabaseError, AuthorityStoreError):
            authority_store = None
        if authority_store is not None:
            cache_namespace = dependencies.parcel_cache_namespace
            if cache_namespace == "live":
                database = Path(database_path).expanduser().resolve()
                cache_namespace = f"live:{database}:authority_revision={authority_store.revision()}"
            dependencies = replace(
                dependencies,
                parcel_cache_namespace=cache_namespace,
                authority_resolver=AuthorityResolver(authority_store),
            )
    return LookupRuntime(
        dependencies=dependencies,
        planning_store=planning_store,
        authority_store=authority_store,
        parcel_store=parcel_store,
    )
