"""Build query-ready plot facts from two pinned immutable source snapshots."""

from __future__ import annotations

import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from dp_lookup.application.ingestion import build_parcel_context
from dp_lookup.application.local_roads import LocalRoadProvider
from dp_lookup.application.local_spatial import LocalNeighbourProvider
from dp_lookup.application.planning_snapshot import canonical_planning_specs
from dp_lookup.clients.local_parcels import merge_local_features
from dp_lookup.clients.parcel_snapshot import sha256_json
from dp_lookup.clients.planning_evidence_queries import LocalFirstPlanningEvidenceAnalyzer
from dp_lookup.clients.planning_queries import build_spatial_planning_result
from dp_lookup.core.constants import (
    CRZ_LAYER_IDS,
    LAYER_DESIGNATION,
    LAYER_METRO,
    LAYER_MODIFICATION,
    LAYER_RESERVATION,
    LAYER_ZONE,
)
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.intelligence.models import ALGORITHM_VERSION, PlotIntelligence
from dp_lookup.intelligence.store import IntelligenceStore
from dp_lookup.planning_evidence.models import EvidenceMode
from dp_lookup.planning_evidence.registry import SERVER_URL, get_canonical_spec
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore

CORE_LAYER_IDS: Tuple[int, ...] = (
    LAYER_ZONE,
    LAYER_RESERVATION,
    LAYER_DESIGNATION,
    LAYER_MODIFICATION,
    LAYER_METRO,
    *CRZ_LAYER_IDS,
)

ProgressCallback = Callable[[int, int, str, str], None]


def _source_fingerprint(
    parcel_snapshot_id: int,
    parcel_metadata: Mapping[str, Any],
    planning_snapshot_id: int,
    planning_hash: str,
) -> str:
    manifest = parcel_metadata.get("manifest_summary")
    parcel_hash = manifest.get("content_hash") if isinstance(manifest, Mapping) else None
    return sha256_json(
        {
            "parcel_snapshot_id": parcel_snapshot_id,
            "parcel_content_hash": parcel_hash,
            "planning_snapshot_id": planning_snapshot_id,
            "planning_content_hash": planning_hash,
            "algorithm_version": ALGORITHM_VERSION,
        }
    )


def _identity_rows(
    store: SnapshotStore,
    snapshot_id: int,
    *,
    limit: Optional[int],
    offset: int,
) -> List[Tuple[str, str]]:
    sql = (
        "SELECT village,cts_no FROM parcels WHERE snapshot_id=? "
        "AND village IS NOT NULL AND village<>'' AND cts_no IS NOT NULL AND cts_no<>'' "
        "GROUP BY village,cts_no ORDER BY village,cts_no"
    )
    params: List[Any] = [snapshot_id]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)
    return [(str(row[0]), str(row[1])) for row in store.connection.execute(sql, params)]


def _identity_count(store: SnapshotStore, snapshot_id: int) -> int:
    return int(
        store.connection.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM parcels WHERE snapshot_id=? "
            "AND village IS NOT NULL AND village<>'' AND cts_no IS NOT NULL AND cts_no<>'' "
            "GROUP BY village,cts_no)",
            (snapshot_id,),
        ).fetchone()[0]
    )


def _core_refs(
    parcel: Any,
    by_layer: Mapping[int, Sequence[Mapping[str, Any]]],
    area_scale: float,
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for layer_id, records in by_layer.items():
        spec = get_canonical_spec(layer_id)
        for record in records:
            geometry = record.get("geometry")
            rings = geometry.get("rings") if isinstance(geometry, Mapping) else None
            if not isinstance(rings, list) or not rings:
                continue
            try:
                intersection = parcel.intersection(arcgis_rings_to_geometry(rings))
            except (IndexError, TypeError, ValueError):
                continue
            if intersection.is_empty:
                continue
            attributes = record.get("attributes")
            if not isinstance(attributes, Mapping):
                attributes = {}
            object_id = record.get("object_id")
            if not isinstance(object_id, int):
                object_id = attributes.get(spec.object_id_field if spec else "OBJECTID")
            if not isinstance(object_id, int):
                continue
            refs.append(
                {
                    "evidence_type": "core_planning",
                    "layer_id": layer_id,
                    "object_id": object_id,
                    "role": spec.role if spec else "planning layer",
                    "overlap_sqm": round(float(intersection.area) * area_scale, 2),
                    "overlap_percent": round(float(intersection.area / parcel.area * 100.0), 3),
                    "source_url": f"{SERVER_URL}/{layer_id}",
                    "attributes": (
                        {field: attributes.get(field) for field in spec.out_fields if field in attributes}
                        if spec
                        else {}
                    ),
                }
            )
    return refs


def _evidence_refs(report: Any, area_scale: float) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for finding in report.findings:
        if finding.object_id is None:
            continue
        item = finding.to_dict()
        item["evidence_type"] = "due_diligence"
        item["overlap_sqm"] = round(float(item["overlap_sqm"]) * area_scale, 2)
        result.append(item)
    return result


def _compact(items: Sequence[Mapping[str, Any]]) -> Tuple[Mapping[str, Any], ...]:
    """Keep computed facts; canonical raw attributes/geometry stay in source tables."""
    return tuple(
        {
            key: value
            for key, value in item.items()
            if key not in {"raw_attributes", "wgs_rings"}
        }
        for item in items
    )


def _scaled_items(
    items: Sequence[Mapping[str, Any]], area_scale: float
) -> Tuple[Mapping[str, Any], ...]:
    result = []
    for item in _compact(items):
        scaled = dict(item)
        for key in ("overlap_sqm", "total_res_sqm", "total_des_sqm"):
            if isinstance(scaled.get(key), (int, float)):
                scaled[key] = round(float(scaled[key]) * area_scale, 2)
        result.append(scaled)
    return tuple(result)


def _ground_area_scale(geometry: Any) -> float:
    """Approximate local ground area from EPSG:3857 area at the plot latitude."""
    latitude = mercator_to_wgs84(float(geometry.centroid.x), float(geometry.centroid.y))[1]
    return math.cos(math.radians(latitude)) ** 2


class PlotIntelligenceBuilder:
    """Resumably derive one intelligence record per village/CTS identity."""

    def __init__(self, database: Path) -> None:
        self.database = Path(database)

    def build(
        self,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        include_neighbours: bool = True,
        evidence_mode: EvidenceMode = EvidenceMode.FULL,
        progress: Optional[ProgressCallback] = None,
        parcel_snapshot_id: Optional[int] = None,
        planning_snapshot_id: Optional[int] = None,
        workers: int = 4,
    ) -> Mapping[str, Any]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive or None")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if workers < 1 or workers > 16:
            raise ValueError("workers must be between 1 and 16")
        selected_mode = EvidenceMode.parse(evidence_mode)
        with SnapshotStore.open(self.database) as parcels, PlanningSnapshotStore.open(
            self.database
        ) as planning, IntelligenceStore.open(self.database) as intelligence:
            parcel_snapshot_id = parcel_snapshot_id or parcels.active_snapshot_id()
            planning_snapshot_id = planning_snapshot_id or planning.active_snapshot_id()
            if parcel_snapshot_id is None:
                raise RuntimeError("database has no active parcel snapshot")
            if planning_snapshot_id is None:
                raise RuntimeError("database has no active planning snapshot")
            parcel_snapshot = parcels.snapshot(parcel_snapshot_id)
            planning_snapshot = planning.snapshot(planning_snapshot_id)
            if parcel_snapshot.state not in {"ready", "active", "retired"}:
                raise RuntimeError("parcel source snapshot must be complete and finalized")
            if planning_snapshot.state not in {"ready", "active", "retired"}:
                raise RuntimeError("planning source snapshot must be complete and finalized")
            if not planning_snapshot.complete:
                raise RuntimeError("active planning snapshot is incomplete")
            required_layers = {spec.layer_id for spec in canonical_planning_specs()}
            available_layers = {layer.canonical_layer_id for layer in planning_snapshot.layers}
            missing_layers = sorted(required_layers - available_layers)
            if missing_layers:
                raise RuntimeError(
                    "active planning snapshot is not authoritative for intelligence; "
                    f"missing canonical layers: {missing_layers}"
                )

            all_count = _identity_count(parcels, parcel_snapshot_id)
            identities = _identity_rows(
                parcels, parcel_snapshot_id, limit=limit, offset=offset
            )
            if not identities:
                raise RuntimeError("selected parcel range contains no identities")
            scope = "full" if limit is None and offset == 0 else "sample"
            fingerprint = _source_fingerprint(
                parcel_snapshot_id,
                parcels.snapshot_metadata(parcel_snapshot_id),
                planning_snapshot_id,
                planning_snapshot.content_hash,
            )
            build_id = intelligence.begin_build(
                parcel_snapshot_id=parcel_snapshot_id,
                planning_snapshot_id=planning_snapshot_id,
                algorithm_version=ALGORITHM_VERSION,
                expected_count=len(identities),
                source_fingerprint=fingerprint,
                scope=scope,
            )
            completed = set(intelligence.completed_keys(build_id))
            pending = [identity for identity in identities if identity not in completed]
            worker_count = min(workers, len(pending)) if pending else 1
            shards = [pending[index::worker_count] for index in range(worker_count)]
            progress_lock = Lock()
            progress_count = [len(completed)]

            def derive(shard: Sequence[Tuple[str, str]]) -> int:
                shard_failures = 0
                with SnapshotStore.open(self.database) as worker_parcels, PlanningSnapshotStore.open(
                    self.database
                ) as worker_planning, IntelligenceStore.open(self.database) as worker_intelligence:
                    road_provider = LocalRoadProvider(
                        worker_planning, snapshot_id=planning_snapshot_id
                    )
                    neighbour_provider = LocalNeighbourProvider(
                        self.database, store=worker_parcels
                    )
                    evidence_analyzer = LocalFirstPlanningEvidenceAnalyzer(
                        worker_planning,
                        mode="local",
                        max_snapshot_age_days=None,
                        snapshot_id=planning_snapshot_id,
                    )
                    for village, cts_no in shard:
                        try:
                            plot = self._analyze(
                                worker_parcels,
                                worker_planning,
                                parcel_snapshot_id,
                                planning_snapshot_id,
                                village,
                                cts_no,
                                road_provider,
                                neighbour_provider if include_neighbours else None,
                                evidence_analyzer,
                                selected_mode,
                            )
                            worker_intelligence.upsert(build_id, plot)
                        except Exception as exc:
                            shard_failures += 1
                            worker_intelligence.record_issue(build_id, village, cts_no, str(exc))
                        if progress:
                            with progress_lock:
                                progress_count[0] += 1
                                progress(progress_count[0], len(identities), village, cts_no)
                return shard_failures

            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="plot-intelligence") as pool:
                failures = sum(pool.map(derive, shards))

            report = intelligence.verify(build_id)
            if report["ok"]:
                build = intelligence.finalize(build_id)
                state = build.state
            else:
                state = "building"
            return {
                "build_id": build_id,
                "state": state,
                "scope": scope,
                "selected_count": len(identities),
                "citywide_identity_count": all_count,
                "new_failures": failures,
                "resumed_records": len(completed),
                "workers": worker_count,
                "source_fingerprint": fingerprint,
                "validation": report,
                "note": (
                    "Verify and activate this full build before using it as the default intelligence source."
                    if scope == "full"
                    else "Sample builds are for validation and cannot be activated."
                ),
            }

    def _analyze(
        self,
        parcels: SnapshotStore,
        planning: PlanningSnapshotStore,
        parcel_snapshot_id: int,
        planning_snapshot_id: int,
        village: str,
        cts_no: str,
        road_provider: LocalRoadProvider,
        neighbour_provider: Optional[LocalNeighbourProvider],
        evidence_analyzer: LocalFirstPlanningEvidenceAnalyzer,
        evidence_mode: EvidenceMode,
    ) -> PlotIntelligence:
        rows = parcels.lookup(village, cts_no, snapshot_id=parcel_snapshot_id)
        feature = merge_local_features(rows)
        if feature is None:
            raise RuntimeError("parcel identity disappeared from the pinned snapshot")
        feature["attributes"]["_DP_SNAPSHOT_ID"] = parcel_snapshot_id
        parcel, area_note = build_parcel_context(feature, village, cts_no)
        geometry = arcgis_rings_to_geometry(parcel.rings)
        area_scale = _ground_area_scale(geometry)
        by_layer = {
            layer_id: planning.query_layer(planning_snapshot_id, layer_id, geometry)
            for layer_id in CORE_LAYER_IDS
        }
        planning_result = build_spatial_planning_result(geometry, by_layer, [])
        road = road_provider(parcel)
        if road is None:
            raise RuntimeError("local road provider did not accept a locally sourced parcel")
        neighbours = neighbour_provider(parcel) if neighbour_provider is not None else None
        report = evidence_analyzer._local_report(parcel.rings, village, evidence_mode)

        source_refs: List[Dict[str, Any]] = [
            {
                "evidence_type": "cadastral",
                "layer_id": 13,
                "object_id": int(row["objectid"]),
                "role": "CTS cadastral parcel",
                "overlap_sqm": None,
                "overlap_percent": None,
                "source_url": f"{SERVER_URL}/13",
                "attributes": {
                    key: value
                    for key, value in dict(row.get("raw_attrs") or {}).items()
                    if key in {"OBJECTID", "VILLAGE", "CTS_CS_NO", "WARD", "TYPE", "AREA_APP_SQ_MTRS"}
                },
            }
            for row in rows
        ]
        source_refs.extend(_core_refs(geometry, by_layer, area_scale))
        source_refs.extend(_evidence_refs(report, area_scale))
        source_refs.sort(
            key=lambda item: (int(item.get("layer_id", -1)), int(item.get("object_id", -1)))
        )
        warnings = list(planning_result.get("warnings") or [])
        warnings.extend(road.warnings)
        warnings.extend(report.warnings)
        if area_note:
            warnings.append(str(area_note))
        geometry_area = float(geometry.area) * area_scale
        area_difference_percent = abs(geometry_area - parcel.area_sqm) / parcel.area_sqm * 100.0
        if area_difference_percent > 5.0:
            warnings.append(
                "Approved plot area and digitized boundary area differ by "
                f"{area_difference_percent:.2f}%; approved area is retained for area totals."
            )
        if planning_result["primary_zone"] == "Unknown" or not report.complete:
            confidence = "review_required"
        elif warnings:
            confidence = "qualified"
        else:
            confidence = "verified"
        outcome_counts = Counter(outcome.state.value for outcome in report.outcomes)
        report_summary = dict(report.summary)
        crz_categories = report_summary.get("crz_categories")
        if isinstance(crz_categories, list):
            report_summary["crz_categories"] = [
                {
                    **item,
                    "overlap_sqm": round(float(item["overlap_sqm"]) * area_scale, 2),
                }
                if isinstance(item, Mapping) and isinstance(item.get("overlap_sqm"), (int, float))
                else item
                for item in crz_categories
            ]
        evidence_summary = {
            **report_summary,
            "mode": evidence_mode.value,
            "complete": report.complete,
            "queried_layer_count": len(report.outcomes),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "overlap_area_basis": "digitized parcel geometry",
            "geometry_area_method": "EPSG:3857 area corrected by cos(latitude)^2",
            "area_totals_basis": parcel.area_source,
        }
        source_objectids = tuple(sorted(int(row["objectid"]) for row in rows))
        calculated_at = datetime.now(timezone.utc).isoformat()
        plot = PlotIntelligence(
            village=village,
            cts_no=cts_no,
            ward=str(parcel.attrs.get("WARD") or "") or None,
            source_objectids=source_objectids,
            feature_part_count=len(source_objectids),
            area_sqm=round(parcel.area_sqm, 2),
            area_source=parcel.area_source,
            geometry_area_sqm=round(geometry_area, 2),
            centroid_x=round(float(geometry.centroid.x), 3),
            centroid_y=round(float(geometry.centroid.y), 3),
            primary_zone=str(planning_result["primary_zone"]),
            zones=_scaled_items(planning_result["zones"], area_scale),
            reservations=_scaled_items(planning_result["reservations"], area_scale),
            designations=_scaled_items(planning_result["designations"], area_scale),
            modifications=_scaled_items(planning_result["modifications"], area_scale),
            metro_buffer=str(planning_result["metro_buffer"]),
            crz_status=str(planning_result["crz_status"]),
            encumbered_area_sqm=round(
                parcel.area_sqm * float(planning_result["encumbered_percent"]) / 100.0, 2
            ),
            encumbered_percent=float(planning_result["encumbered_percent"]),
            net_unencumbered_sqm=round(
                parcel.area_sqm * float(planning_result["net_unencumbered_percent"]) / 100.0, 2
            ),
            net_unencumbered_percent=float(planning_result["net_unencumbered_percent"]),
            road_name=road.name,
            road_width=road.width,
            road_distance_m=road.distance_m,
            neighbour_count=len(neighbours.plots) if neighbours else 0,
            neighbours=tuple(neighbours.plots) if neighbours else (),
            evidence_summary=evidence_summary,
            warnings=tuple(dict.fromkeys(warnings)),
            confidence=confidence,
            source_refs=tuple(source_refs),
            calculated_at=calculated_at,
        )
        facts = plot.to_dict()
        facts["quality"].pop("facts_hash", None)
        facts["quality"].pop("calculated_at", None)
        return replace(plot, facts_hash=sha256_json(facts))


__all__ = ["CORE_LAYER_IDS", "PlotIntelligenceBuilder"]
