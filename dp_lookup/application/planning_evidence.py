"""Application-stage helpers for optional planning due-diligence evidence."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from dp_lookup.planning_evidence.models import EvidenceMode, PlanningEvidenceReport


def evidence_cache_key(base_key: str, mode: EvidenceMode) -> str:
    """Keep legacy basic entries while isolating versioned evidence profiles."""

    if mode is EvidenceMode.BASIC:
        return base_key
    return f"{base_key}:planning-evidence-v1:{mode.value}"


def cache_suppression_warning(warnings: Sequence[str], planning_evidence: Mapping[str, Any] | None) -> str | None:
    """Explain why neither a degraded core nor evidence result may be cached."""

    if warnings:
        return f"result incomplete, not cached - {'; '.join(warnings)}"
    if planning_evidence and not bool(planning_evidence.get("complete")):
        return "optional planning evidence incomplete, not cached"
    return None


def normalize_evidence_stage(
    result: Any,
    mode: EvidenceMode,
) -> tuple[dict[str, Any] | None, str, dict[str, Any], str | None]:
    """Turn an optional analyzer result into nested metadata and telemetry."""

    if mode is EvidenceMode.BASIC:
        return None, "disabled", {}, None
    if isinstance(result, PlanningEvidenceReport):
        note = None
        if not result.complete and mode is not EvidenceMode.SHADOW:
            note = "Extended planning evidence is incomplete; inspect metadata.evidence.planning_due_diligence."
        return (
            result.to_dict(),
            "complete" if result.complete else "partial",
            {"mode": mode.value, "layers": len(result.outcomes), "findings": len(result.findings)},
            note,
        )

    detail = str(result) if isinstance(result, Exception) else "unexpected result"
    note = None
    if mode is not EvidenceMode.SHADOW:
        note = "Extended planning evidence failed; the core lookup remains valid but due-diligence evidence is unavailable."
    return (
        {
            "mode": mode.value,
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "complete": False,
            "registry_version": 1,
            "summary": {},
            "outcomes": [],
            "warnings": [f"Planning-evidence analyzer failed: {detail}"],
        },
        "failed",
        {"mode": mode.value},
        note,
    )
