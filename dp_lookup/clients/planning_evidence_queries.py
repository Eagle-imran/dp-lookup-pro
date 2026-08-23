"""Bounded ArcGIS adapter for the optional planning-evidence capability."""

from __future__ import annotations

import asyncio
import math
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from shapely.errors import GEOSException
from shapely.geometry.base import BaseGeometry

from dp_lookup.clients.responses import usable_json
from dp_lookup.core.constants import SERVER_URL, SLIVER_AREA_THRESHOLD_SQM, SLIVER_PERCENT_THRESHOLD
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.planning_evidence.models import (
    EvidenceClass,
    EvidenceContext,
    EvidenceFinding,
    EvidenceMode,
    LayerQueryOutcome,
    LayerSpec,
    PlanningEvidenceReport,
    QueryState,
)
from dp_lookup.planning_evidence.registry import CURRENT_CORE_LAYER_IDS, specs_for_mode

MAX_CONCURRENT_LAYER_QUERIES = 4
DEFAULT_MAX_PLANNING_EVIDENCE_AGE_DAYS = 210.0


def _query_payload(bounds: Tuple[float, float, float, float], spec: LayerSpec) -> Dict[str, str]:
    return {
        "where": "1=1",
        "geometry": ",".join(str(value) for value in bounds),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "102100",
        "outFields": ",".join(spec.out_fields),
        "returnGeometry": "true",
        "outSR": "102100",
        "f": "json",
    }


def _authority_for_record(spec: LayerSpec, attributes: Mapping[str, Any]) -> Tuple[EvidenceClass, Tuple[str, ...]]:
    warnings: List[str] = []
    evidence_class = spec.evidence_class
    if spec.layer_id == 83 and not (attributes.get("NOTIFICATION_NO") or attributes.get("GAZETTE_DATE")):
        evidence_class = EvidenceClass.REGULATORY
        warnings.append("EP record has no notification or gazette reference; statutory class was not assigned")
    if spec.layer_id == 2000:
        approved_by = str(attributes.get("APPROVED_BY") or "").strip()
        if approved_by.casefold() == "test" or not attributes.get("NOTIFICATION_NO"):
            evidence_class = EvidenceClass.REGULATORY
            warnings.append("MRTP record lacks validated statutory provenance or contains a test approver")
        document = str(attributes.get("APPROVAL_DOCUMENTS") or "").strip()
        if document.endswith("/aprDocs/"):
            warnings.append("Approval-document value is a directory, not a record-specific document")
    return evidence_class, tuple(warnings)


def _source_url(layer_id: int) -> str:
    return f"{SERVER_URL}/{layer_id}"


async def _query_layer(
    client: Any,
    parcel: Any,
    spec: LayerSpec,
    semaphore: asyncio.Semaphore,
) -> LayerQueryOutcome:
    started = time.perf_counter()
    try:
        async with semaphore:
            response = await client.post(
                f"{SERVER_URL}/{spec.layer_id}/query",
                data=_query_payload(tuple(parcel.bounds), spec),
            )
    except Exception as exc:
        return LayerQueryOutcome(
            spec.layer_id,
            spec.name,
            QueryState.FAILED,
            round((time.perf_counter() - started) * 1000, 1),
            warnings=(f"Layer {spec.layer_id} query failed: {exc}",),
        )

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    payload = usable_json(response)
    if payload is None:
        return LayerQueryOutcome(
            spec.layer_id,
            spec.name,
            QueryState.FAILED,
            duration_ms,
            warnings=(f"Layer {spec.layer_id} returned invalid or ArcGIS error JSON",),
        )
    features = payload.get("features")
    if not isinstance(features, list):
        return LayerQueryOutcome(
            spec.layer_id,
            spec.name,
            QueryState.MALFORMED,
            duration_ms,
            warnings=(f"Layer {spec.layer_id} returned a malformed feature collection",),
        )

    return _parse_layer_features(
        parcel,
        spec,
        features,
        duration_ms,
        transfer_limited=payload.get("exceededTransferLimit") is True,
    )


def _parse_layer_features(
    parcel: Any,
    spec: LayerSpec,
    features: Sequence[Any],
    duration_ms: float,
    *,
    transfer_limited: bool = False,
) -> LayerQueryOutcome:
    """Apply the deterministic evidence policy to source-shaped features.

    Both the live ArcGIS adapter and the local snapshot adapter call this
    function.  Keeping parsing, sliver filtering, authority guards, and
    outcome state transitions in one place prevents source-specific drift.
    """
    threshold = max(SLIVER_AREA_THRESHOLD_SQM, parcel.area * SLIVER_PERCENT_THRESHOLD)
    findings: List[EvidenceFinding] = []
    malformed = 0
    for feature in features:
        if not isinstance(feature, Mapping):
            malformed += 1
            continue
        raw_attributes = feature.get("attributes")
        geometry = feature.get("geometry")
        if not isinstance(raw_attributes, Mapping) or not isinstance(geometry, Mapping):
            malformed += 1
            continue
        # The archival snapshot intentionally retains every published source
        # field. Runtime evidence remains on the same audited allow-list as the
        # live query so local mode cannot leak unrelated/schema-drift fields.
        attributes = {field: raw_attributes.get(field) for field in spec.out_fields if field in raw_attributes}
        rings = geometry.get("rings")
        if not isinstance(rings, list) or not rings:
            malformed += 1
            continue
        try:
            runtime_geometry = feature.get("_dp_runtime_geometry")
            source_geometry = (
                runtime_geometry
                if isinstance(runtime_geometry, BaseGeometry)
                else arcgis_rings_to_geometry(rings)
            )
            intersection = parcel.intersection(source_geometry)
        except (GEOSException, IndexError, KeyError, TypeError, ValueError):
            malformed += 1
            continue
        if intersection.is_empty or intersection.area <= threshold:
            continue
        evidence_class, record_warnings = _authority_for_record(spec, attributes)
        object_id = attributes.get(spec.object_id_field)
        findings.append(
            EvidenceFinding(
                layer_id=spec.layer_id,
                layer_name=spec.name,
                object_id=int(object_id) if isinstance(object_id, (int, float)) else None,
                evidence_class=evidence_class,
                role=spec.role,
                overlap_sqm=round(intersection.area, 2),
                overlap_percent=round(intersection.area / parcel.area * 100, 3),
                source_url=_source_url(spec.layer_id),
                attributes=attributes,
                warnings=record_warnings,
            )
        )

    warnings: List[str] = []
    state = QueryState.HIT if findings else QueryState.NOT_PRESENT
    if malformed:
        state = QueryState.MALFORMED
        warnings.append(f"Layer {spec.layer_id} contained {malformed} malformed feature(s)")
    if transfer_limited:
        state = QueryState.TRUNCATED
        warnings.append(f"Layer {spec.layer_id} exceeded the ArcGIS transfer limit")
    return LayerQueryOutcome(
        layer_id=spec.layer_id,
        layer_name=spec.name,
        state=state,
        duration_ms=duration_ms,
        returned_features=len(features),
        findings=tuple(findings),
        warnings=tuple(warnings),
    )


async def _query_specs(client: Any, parcel: Any, specs: Sequence[LayerSpec]) -> Tuple[LayerQueryOutcome, ...]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LAYER_QUERIES)
    return tuple(await asyncio.gather(*(_query_layer(client, parcel, spec, semaphore) for spec in specs)))


def _hit(outcomes: Sequence[LayerQueryOutcome], layer_id: int) -> bool:
    return any(outcome.layer_id == layer_id and bool(outcome.findings) for outcome in outcomes)


def _build_summary(outcomes: Sequence[LayerQueryOutcome], context: EvidenceContext) -> Dict[str, Any]:
    findings = [finding for outcome in outcomes for finding in outcome.findings]
    class_counts = Counter(finding.evidence_class.value for finding in findings)
    crz_categories = []
    seen_crz = set()
    for finding in findings:
        if finding.layer_id != 2250:
            continue
        category = str(finding.attributes.get("CATEGORY") or "Unknown")
        subcategory = str(finding.attributes.get("SUB_CATGORY") or "Unknown")
        key = (category, subcategory)
        if key in seen_crz:
            continue
        seen_crz.add(key)
        crz_categories.append(
            {
                "category": category,
                "subcategory": subcategory,
                "overlap_sqm": finding.overlap_sqm,
                "overlap_percent": finding.overlap_percent,
            }
        )

    if _hit(outcomes, 29):
        asi_zone = "prohibited_100m_screening"
    elif _hit(outcomes, 30):
        asi_zone = "regulated_200m_band_screening"
    else:
        asi_outcomes = [outcome for outcome in outcomes if outcome.layer_id in (29, 30)]
        asi_zone = (
            "not_present"
            if len(asi_outcomes) == 2 and all(outcome.state is QueryState.NOT_PRESENT for outcome in asi_outcomes)
            else "not_checked_or_unknown"
        )
    return {
        "finding_count": len(findings),
        "findings_by_evidence_class": dict(sorted(class_counts.items())),
        "decision_record_count": sum(1 for finding in findings if finding.layer_id in (83, 2000, 92, 85, 81)),
        "crz_categories": crz_categories,
        "asi_zone": asi_zone,
        "applicability": {
            "coastal": context.coastal,
            "tps": context.tps,
            "spa": context.spa,
            "gorai_manori": context.gorai,
        },
    }


def _report_for_outcomes(
    selected_mode: EvidenceMode,
    retrieved_at: str,
    outcomes: Sequence[LayerQueryOutcome],
    context: EvidenceContext,
    *,
    warnings: Sequence[str] = (),
    provenance: Optional[Mapping[str, Any]] = None,
) -> PlanningEvidenceReport:
    """Build a report from already parsed outcomes for any source adapter."""
    bad_states = {QueryState.FAILED, QueryState.MALFORMED, QueryState.TRUNCATED}
    all_warnings = tuple(warning for outcome in outcomes for warning in outcome.warnings) + tuple(warnings)
    return PlanningEvidenceReport(
        mode=selected_mode,
        retrieved_at=retrieved_at,
        complete=all(outcome.state not in bad_states for outcome in outcomes),
        outcomes=tuple(outcomes),
        summary=_build_summary(outcomes, context),
        warnings=all_warnings,
        provenance=dict(provenance or {}),
    )


async def collect_planning_evidence(
    client: Any,
    rings: List[Any],
    village: str,
    mode: EvidenceMode,
) -> PlanningEvidenceReport:
    """Collect optional source evidence without re-querying cadastral Layer 13."""

    selected_mode = EvidenceMode.parse(mode)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    if selected_mode is EvidenceMode.BASIC:
        return PlanningEvidenceReport(selected_mode, retrieved_at, True)

    parcel = arcgis_rings_to_geometry(rings)
    initial_specs = specs_for_mode(selected_mode)
    outcomes = list(await _query_specs(client, parcel, initial_specs))
    context = EvidenceContext(
        coastal=_hit(outcomes, 2250),
        tps=_hit(outcomes, 112),
        spa=_hit(outcomes, 1524),
        gorai=_hit(outcomes, 1502) or village.strip().upper() in {"GORAI", "MANORI"},
    )
    if selected_mode is EvidenceMode.FULL:
        queried_ids = {outcome.layer_id for outcome in outcomes}
        extra_specs = tuple(
            spec
            for spec in specs_for_mode(selected_mode, context=context)
            if spec.layer_id not in queried_ids and spec.layer_id not in CURRENT_CORE_LAYER_IDS
        )
        outcomes.extend(await _query_specs(client, parcel, extra_specs))

    return _report_for_outcomes(selected_mode, retrieved_at, outcomes, context)


class LocalPlanningEvidenceError(RuntimeError):
    """A local planning snapshot cannot provide a trustworthy evidence pass."""


def _snapshot_value(snapshot: Any, name: str, default: Any = None) -> Any:
    if isinstance(snapshot, Mapping):
        return snapshot.get(name, default)
    return getattr(snapshot, name, default)


def _snapshot_age_days(finalized_at: Any) -> Optional[float]:
    if finalized_at is None:
        return None
    if isinstance(finalized_at, datetime):
        timestamp = finalized_at.timestamp()
    elif isinstance(finalized_at, (int, float)) and not isinstance(finalized_at, bool):
        timestamp = float(finalized_at)
    else:
        text = str(finalized_at).strip()
        try:
            timestamp = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                timestamp = float(text)
            except ValueError:
                return None
    if not math.isfinite(timestamp):
        return None
    return round(max(0.0, (time.time() - timestamp) / 86_400.0), 3)


class LocalFirstPlanningEvidenceAnalyzer:
    """Run STANDARD/FULL evidence against one pinned local snapshot first.

    ``mode`` selects the source policy (``auto``, ``local``, or ``live``),
    while the mode passed to ``__call__`` remains the evidence profile.  Local
    records go through the exact parser used by ArcGIS so findings and state
    transitions are source-independent.
    """

    def __init__(
        self,
        store: Optional[Any],
        *,
        live_analyzer: Any = collect_planning_evidence,
        mode: str = "auto",
        max_snapshot_age_days: Optional[float] = DEFAULT_MAX_PLANNING_EVIDENCE_AGE_DAYS,
        allow_stale_local: bool = False,
        snapshot_id: Optional[int] = None,
    ) -> None:
        selected_mode = str(mode).strip().lower()
        if selected_mode not in {"auto", "local", "live"}:
            raise ValueError("planning evidence source mode must be auto, local, or live")
        if max_snapshot_age_days is not None and (
            isinstance(max_snapshot_age_days, bool) or max_snapshot_age_days <= 0
        ):
            raise ValueError("max_snapshot_age_days must be positive or None")
        self.store = store
        self.live_analyzer = live_analyzer
        self.mode = selected_mode
        self.max_snapshot_age_days = max_snapshot_age_days
        self.allow_stale_local = allow_stale_local
        self.snapshot_id = snapshot_id

    def _pin(self) -> Any:
        if self.store is None:
            raise LocalPlanningEvidenceError("no local planning snapshot store is configured")
        if self.snapshot_id is not None:
            snapshot_reader = getattr(self.store, "snapshot", None)
            if not callable(snapshot_reader):
                raise LocalPlanningEvidenceError("planning snapshot store cannot select a snapshot by ID")
            try:
                return snapshot_reader(self.snapshot_id)
            except Exception as exc:
                raise LocalPlanningEvidenceError(
                    f"planning snapshot {self.snapshot_id} could not be pinned: {exc}"
                ) from exc
        pin = getattr(self.store, "pin_active_snapshot", None)
        if pin is None:
            pin = getattr(self.store, "active_snapshot", None)
        try:
            snapshot = pin() if callable(pin) else None
        except Exception as exc:
            raise LocalPlanningEvidenceError(f"active planning snapshot could not be pinned: {exc}") from exc
        if snapshot is None:
            raise LocalPlanningEvidenceError("no active planning snapshot is available")
        snapshot_id = _snapshot_value(snapshot, "snapshot_id")
        if snapshot_id is None or isinstance(snapshot_id, bool) or str(snapshot_id).strip() == "":
            raise LocalPlanningEvidenceError("active planning snapshot has no valid snapshot ID")
        complete = _snapshot_value(snapshot, "complete")
        if complete is False:
            raise LocalPlanningEvidenceError(f"planning snapshot {snapshot_id} is incomplete")
        return snapshot

    def _local_report(self, rings: List[Any], village: str, selected_mode: EvidenceMode) -> PlanningEvidenceReport:
        snapshot = self._pin()
        snapshot_id = _snapshot_value(snapshot, "snapshot_id")
        finalized_at = _snapshot_value(snapshot, "finalized_at")
        if finalized_at is None:
            raise LocalPlanningEvidenceError(f"planning snapshot {snapshot_id} has no finalized timestamp")
        age_days = _snapshot_age_days(finalized_at)
        if age_days is None:
            raise LocalPlanningEvidenceError(f"planning snapshot {snapshot_id} has an invalid finalized timestamp")
        stale = self.max_snapshot_age_days is not None and age_days > self.max_snapshot_age_days
        if stale and not self.allow_stale_local:
            raise LocalPlanningEvidenceError(
                f"planning snapshot {snapshot_id} is stale ({age_days} days old; "
                f"limit {self.max_snapshot_age_days} days)"
            )

        parcel = arcgis_rings_to_geometry(rings)
        if parcel.is_empty or parcel.area <= 0:
            raise ValueError("Parcel geometry has no valid polygon rings")
        query = getattr(self.store, "query_layer", None)
        if query is None:
            query = getattr(self.store, "records_intersecting", None)
        if not callable(query):
            raise LocalPlanningEvidenceError("planning snapshot store has no spatial layer query method")

        def query_specs(specs: Sequence[LayerSpec]) -> List[LayerQueryOutcome]:
            result: List[LayerQueryOutcome] = []
            for spec in specs:
                started = time.perf_counter()
                try:
                    records = query(snapshot_id, spec.layer_id, parcel)
                except Exception as exc:
                    raise LocalPlanningEvidenceError(
                        f"planning snapshot {snapshot_id} query failed for layer {spec.layer_id}: {exc}"
                    ) from exc
                if records is None or not isinstance(records, (list, tuple)):
                    raise LocalPlanningEvidenceError(
                        f"planning snapshot {snapshot_id} returned a malformed collection for layer {spec.layer_id}"
                    )
                result.append(
                    _parse_layer_features(
                        parcel,
                        spec,
                        records,
                        round((time.perf_counter() - started) * 1000, 1),
                    )
                )
            return result

        retrieved_at = datetime.now(timezone.utc).isoformat()
        initial_specs = specs_for_mode(selected_mode)
        outcomes = query_specs(initial_specs)
        context = EvidenceContext(
            coastal=_hit(outcomes, 2250),
            tps=_hit(outcomes, 112),
            spa=_hit(outcomes, 1524),
            gorai=_hit(outcomes, 1502) or village.strip().upper() in {"GORAI", "MANORI"},
        )
        if selected_mode is EvidenceMode.FULL:
            queried_ids = {outcome.layer_id for outcome in outcomes}
            extra_specs = tuple(
                spec
                for spec in specs_for_mode(selected_mode, context=context)
                if spec.layer_id not in queried_ids and spec.layer_id not in CURRENT_CORE_LAYER_IDS
            )
            outcomes.extend(query_specs(extra_specs))

        stale_warning = (
            f"Local planning snapshot {snapshot_id} is stale ({age_days} days old); "
            "verify planning status against live ArcGIS."
            if stale
            else None
        )
        provenance = {
            "source": "local_snapshot",
            "method": "local_snapshot_spatial_query",
            "snapshot_id": snapshot_id,
            "snapshot_finalized_at": finalized_at,
            "snapshot_age_days": age_days,
            "snapshot_stale": stale,
            "fallback": False,
        }
        return _report_for_outcomes(
            selected_mode,
            retrieved_at,
            outcomes,
            context,
            warnings=(stale_warning,) if stale_warning else (),
            provenance=provenance,
        )

    async def __call__(
        self,
        client: Any,
        rings: List[Any],
        village: str,
        mode: EvidenceMode,
    ) -> PlanningEvidenceReport:
        selected_mode = EvidenceMode.parse(mode)
        if selected_mode is EvidenceMode.BASIC:
            return PlanningEvidenceReport(selected_mode, datetime.now(timezone.utc).isoformat(), True)
        if self.mode == "live":
            report = cast(PlanningEvidenceReport, await self.live_analyzer(client, rings, village, selected_mode))
            return replace(
                report,
                provenance={
                    "source": "live_arcgis",
                    "method": "bounded_layer_queries",
                    "fallback": False,
                },
            )
        try:
            return self._local_report(rings, village, selected_mode)
        except Exception as exc:
            if self.mode == "local":
                if isinstance(exc, LocalPlanningEvidenceError):
                    raise
                raise LocalPlanningEvidenceError(str(exc)) from exc
            reason = str(exc)
            report = cast(PlanningEvidenceReport, await self.live_analyzer(client, rings, village, selected_mode))
            warning = f"Local planning snapshot was unavailable; live ArcGIS planning evidence was used ({reason})."
            return replace(
                report,
                warnings=(*tuple(report.warnings), warning),
                provenance={
                    "source": "live_arcgis",
                    "method": "bounded_layer_queries",
                    "fallback": True,
                    "fallback_reason": reason,
                },
            )


__all__ = [
    "DEFAULT_MAX_PLANNING_EVIDENCE_AGE_DAYS",
    "MAX_CONCURRENT_LAYER_QUERIES",
    "LocalFirstPlanningEvidenceAnalyzer",
    "LocalPlanningEvidenceError",
    "collect_planning_evidence",
]
