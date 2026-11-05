"""Application facade for building and querying plot intelligence."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from dp_lookup.application.intelligence_builder import (
    PlotIntelligenceBuilder,
    _authority_registry_revision,
    _source_fingerprint,
)
from dp_lookup.intelligence.models import ALGORITHM_VERSION
from dp_lookup.intelligence.store import IntelligenceStateError, IntelligenceStore
from dp_lookup.planning_evidence.models import EvidenceMode
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore


def _age_days(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return round(max(0.0, (time.time() - timestamp) / 86_400.0), 3)


def _summary(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "village": record["village"],
        "cts_no": record["cts_no"],
        "ward": record.get("ward"),
        "area_sqm": record["area_sqm"],
        "primary_zone": record["primary_zone"],
        "reservation_count": len(record.get("reservations") or []),
        "designation_count": len(record.get("designations") or []),
        "encumbered_percent": record["encumbered_percent"],
        "net_unencumbered_sqm": record["net_unencumbered_sqm"],
        "road_name": record["road_name"],
        "road_width": record["road_width"],
        "road_distance_m": record.get("road_distance_m"),
        "neighbour_count": record["neighbour_count"],
        "confidence": record["confidence"],
        "facts_hash": record["facts_hash"],
    }


def _dossier(record: Mapping[str, Any], build: Mapping[str, Any]) -> Dict[str, Any]:
    evidence_summary = record["evidence_summary"]
    assessment = evidence_summary.get("area_assessment") if isinstance(evidence_summary, Mapping) else None
    return {
        "plot_identity": {
            "village": record["village"],
            "cts_no": record["cts_no"],
            "ward": record.get("ward"),
            "source_objectids": record["source_objectids"],
            "feature_part_count": record["feature_part_count"],
            "area_sqm": record["area_sqm"],
            "area_source": record["area_source"],
            "geometry_area_sqm": record["geometry_area_sqm"],
            **({"area_assessment": dict(assessment)} if isinstance(assessment, Mapping) else {}),
            **(
                {"authority_resolution": dict(evidence_summary["authority_resolution"])}
                if isinstance(evidence_summary, Mapping)
                and isinstance(evidence_summary.get("authority_resolution"), Mapping)
                else {}
            ),
            "centroid": {
                "x": record["centroid_x"],
                "y": record["centroid_y"],
                "wkid": 102100,
            },
        },
        "planning": {
            "primary_zone": record["primary_zone"],
            "zones": record["zones"],
            "reservations": record["reservations"],
            "designations": record["designations"],
            "modifications": record["modifications"],
            "metro_buffer": record["metro_buffer"],
            "crz_status": record["crz_status"],
            "encumbered_area_sqm": record["encumbered_area_sqm"],
            "encumbered_percent": record["encumbered_percent"],
            "net_unencumbered_sqm": record["net_unencumbered_sqm"],
            "net_unencumbered_percent": record["net_unencumbered_percent"],
        },
        "access": {
            "road_name": record["road_name"],
            "road_width": record["road_width"],
            "distance_m": record.get("road_distance_m"),
        },
        "adjacency": {
            "neighbour_count": record["neighbour_count"],
            "neighbours": record["neighbours"],
        },
        "evidence_summary": evidence_summary,
        "quality": {
            "confidence": record["confidence"],
            "warnings": record["warnings"],
            "facts_hash": record["facts_hash"],
            "calculated_at": record["calculated_at"],
        },
        "provenance": {
            "intelligence_build_id": build["build_id"],
            "parcel_snapshot_id": build["parcel_snapshot_id"],
            "planning_snapshot_id": build["planning_snapshot_id"],
            "algorithm_version": build["algorithm_version"],
            "source_fingerprint": build["source_fingerprint"],
            "source_refs": record["source_refs"],
        },
    }


class PlotIntelligenceServices:
    def _require_current_build(self, database: Path, build_id: Optional[int]) -> None:
        if build_id is not None:
            return  # Explicit historical IDs remain available for audit.
        check = self.check(database)
        if check["active_intelligence_build_id"] is None:
            raise IntelligenceStateError("no active plot-intelligence build is available")
        if not check["source_alignment"]:
            raise IntelligenceStateError(
                "active plot-intelligence build is stale; build, verify and activate current sources"
            )

    def build(
        self,
        database: Path,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        include_neighbours: bool = True,
        evidence_mode: str = "full",
        parcel_snapshot_id: Optional[int] = None,
        planning_snapshot_id: Optional[int] = None,
        workers: int = 1,
    ) -> Mapping[str, Any]:
        return PlotIntelligenceBuilder(database).build(
            limit=limit,
            offset=offset,
            include_neighbours=include_neighbours,
            evidence_mode=EvidenceMode.parse(evidence_mode),
            parcel_snapshot_id=parcel_snapshot_id,
            planning_snapshot_id=planning_snapshot_id,
            workers=workers,
        )

    def status(self, database: Path) -> Mapping[str, Any]:
        with IntelligenceStore.open(database) as store:
            return store.status()

    def verify(self, database: Path, *, build_id: Optional[int] = None) -> Mapping[str, Any]:
        with IntelligenceStore.open(database) as store:
            selected = build_id
            if selected is None:
                status = store.status()
                builds = status["builds"]
                if not builds:
                    raise IntelligenceStateError("database has no plot-intelligence builds")
                selected = int(builds[-1]["build_id"])
            return store.verify(selected)

    def activate(self, database: Path, *, build_id: Optional[int] = None) -> Mapping[str, Any]:
        with (
            IntelligenceStore.open(database) as store,
            SnapshotStore.open(database) as parcels,
            PlanningSnapshotStore.open(database) as planning,
        ):
            selected = build_id
            if selected is None:
                ready = [item for item in store.status()["builds"] if item["state"] == "ready"]
                if not ready:
                    raise IntelligenceStateError("database has no ready plot-intelligence build")
                selected = int(ready[-1]["build_id"])
            build = store.build(selected)
            if build.parcel_snapshot_id != parcels.active_snapshot_id():
                raise IntelligenceStateError("intelligence build does not match the active parcel snapshot")
            if build.planning_snapshot_id != planning.active_snapshot_id():
                raise IntelligenceStateError("intelligence build does not match the active planning snapshot")
            expected_fingerprint = _source_fingerprint(
                build.parcel_snapshot_id,
                parcels.snapshot_metadata(build.parcel_snapshot_id),
                build.planning_snapshot_id,
                planning.snapshot(build.planning_snapshot_id).content_hash,
                _authority_registry_revision(database),
            )
            if build.algorithm_version != ALGORITHM_VERSION or build.source_fingerprint != expected_fingerprint:
                raise IntelligenceStateError(
                    "intelligence build has a stale algorithm or source fingerprint; rebuild it"
                )
            return store.activate(selected).to_dict()

    def analyze(
        self,
        database: Path,
        village: str,
        cts_no: str,
        *,
        build_id: Optional[int] = None,
    ) -> Mapping[str, Any]:
        self._require_current_build(database, build_id)
        with IntelligenceStore.open(database) as store:
            record = store.get(village, cts_no, build_id=build_id)
            if record is None:
                raise KeyError(f"plot {village} CTS {cts_no} is not present in the selected intelligence build")
            selected = int(record["build_id"])
            return _dossier(record, store.build(selected).to_dict())

    def search(self, database: Path, **filters: Any) -> Mapping[str, Any]:
        self._require_current_build(database, filters.get("build_id"))
        with IntelligenceStore.open(database) as store:
            records = store.search(**filters)
            selected = filters.get("build_id") or store.active_build_id()
            return {
                "build_id": selected,
                "count": len(records),
                "results": [_summary(record) for record in records],
            }

    def compare(
        self,
        database: Path,
        identities: Sequence[Tuple[str, str]],
        *,
        build_id: Optional[int] = None,
    ) -> Mapping[str, Any]:
        self._require_current_build(database, build_id)
        with IntelligenceStore.open(database) as store:
            result = store.compare(identities, build_id=build_id)
            result["records"] = [_summary(record) for record in result["records"]]
            return result

    def check(self, database: Path, *, refresh_days: float = 183.0) -> Mapping[str, Any]:
        if refresh_days <= 0:
            raise ValueError("refresh_days must be positive")
        with (
            SnapshotStore.open(database) as parcels,
            PlanningSnapshotStore.open(database) as planning,
            IntelligenceStore.open(database) as intelligence,
        ):
            parcel_id = parcels.active_snapshot_id()
            planning_id = planning.active_snapshot_id()
            build_id = intelligence.active_build_id()
            parcel = parcels.snapshot(parcel_id) if parcel_id is not None else None
            planning_snapshot = planning.snapshot(planning_id) if planning_id is not None else None
            build = intelligence.build(build_id) if build_id is not None else None
            parcel_age = _age_days(parcel.finalized_at if parcel else None)
            planning_age = _age_days(planning_snapshot.finalized_at if planning_snapshot else None)
            snapshot_alignment = bool(
                build and build.parcel_snapshot_id == parcel_id and build.planning_snapshot_id == planning_id
            )
            algorithm_alignment = bool(build and build.algorithm_version == ALGORITHM_VERSION)
            expected_fingerprint = None
            if parcel_id is not None and planning_id is not None and planning_snapshot is not None:
                expected_fingerprint = _source_fingerprint(
                    parcel_id,
                    parcels.snapshot_metadata(parcel_id),
                    planning_id,
                    planning_snapshot.content_hash,
                    _authority_registry_revision(database),
                )
            fingerprint_alignment = bool(build and build.source_fingerprint == expected_fingerprint)
            aligned = snapshot_alignment and algorithm_alignment and fingerprint_alignment
            refresh_due = bool(
                parcel_age is None or planning_age is None or parcel_age >= refresh_days or planning_age >= refresh_days
            )
            actions = []
            if refresh_due:
                actions.append("build and verify new parcel and planning source snapshots")
            if not aligned:
                actions.append("build, verify and activate plot intelligence for the active source snapshots")
            return {
                "database": str(database),
                "refresh_interval_days": refresh_days,
                "active_parcel_snapshot_id": parcel_id,
                "active_planning_snapshot_id": planning_id,
                "active_intelligence_build_id": build_id,
                "parcel_snapshot_age_days": parcel_age,
                "planning_snapshot_age_days": planning_age,
                "source_alignment": aligned,
                "snapshot_alignment": snapshot_alignment,
                "algorithm_alignment": algorithm_alignment,
                "fingerprint_alignment": fingerprint_alignment,
                "refresh_due": refresh_due,
                "intelligence_rebuild_required": not aligned,
                "ready_for_operational_use": aligned and not refresh_due,
                "recommended_actions": actions,
            }


__all__ = ["PlotIntelligenceServices"]
