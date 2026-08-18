"""Bounded ArcGIS adapter for the optional planning-evidence capability."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from shapely.errors import GEOSException  # type: ignore[import-untyped]

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

    threshold = max(SLIVER_AREA_THRESHOLD_SQM, parcel.area * SLIVER_PERCENT_THRESHOLD)
    findings: List[EvidenceFinding] = []
    malformed = 0
    for feature in features:
        if not isinstance(feature, Mapping):
            malformed += 1
            continue
        attributes = feature.get("attributes")
        geometry = feature.get("geometry")
        if not isinstance(attributes, Mapping) or not isinstance(geometry, Mapping):
            malformed += 1
            continue
        rings = geometry.get("rings")
        if not isinstance(rings, list) or not rings:
            malformed += 1
            continue
        try:
            source_geometry = arcgis_rings_to_geometry(rings)
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
    if payload.get("exceededTransferLimit") is True:
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
        "decision_record_count": sum(
            1 for finding in findings if finding.layer_id in (83, 2000, 92, 85, 81)
        ),
        "crz_categories": crz_categories,
        "asi_zone": asi_zone,
        "applicability": {
            "coastal": context.coastal,
            "tps": context.tps,
            "spa": context.spa,
            "gorai_manori": context.gorai,
        },
    }


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

    bad_states = {QueryState.FAILED, QueryState.MALFORMED, QueryState.TRUNCATED}
    warnings = tuple(warning for outcome in outcomes for warning in outcome.warnings)
    complete = all(outcome.state not in bad_states for outcome in outcomes)
    return PlanningEvidenceReport(
        mode=selected_mode,
        retrieved_at=retrieved_at,
        complete=complete,
        outcomes=tuple(outcomes),
        summary=_build_summary(outcomes, context),
        warnings=warnings,
    )


__all__ = ["MAX_CONCURRENT_LAYER_QUERIES", "collect_planning_evidence"]
