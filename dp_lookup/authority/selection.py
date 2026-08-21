"""Deterministic recommendations for versioned authority records.

This module deliberately does not mutate a parcel or decide which source is
operationally active.  It ranks *verified* records and explains the result.
The resolver is the only module which may apply an explicitly active source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

AUTHORITY_POLICY_VERSION = "authority-policy/1.0"

# The values are intentionally policy data, not model-enum values.  This lets
# the selector remain compatible with a persisted enum whose spelling changes.
_RANKS: Dict[str, Dict[str, int]] = {
    "area_reconciliation": {
        "reconciliation": 110,
        "certified_survey_reconciliation": 110,
        "property_card": 100,
        "city_survey": 95,
        "city_survey_measurement": 95,
        "cts_fp": 90,
        "cts_final_plot": 90,
        "cts_final_plot_plan": 90,
        "total_station": 70,
        "total_station_survey": 70,
    },
    "geometry_reconciliation": {
        "reconciliation": 110,
        "certified_survey_reconciliation": 110,
        "total_station": 100,
        "total_station_survey": 100,
        "city_survey": 95,
        "city_survey_measurement": 95,
        "cts_fp": 90,
        "cts_final_plot": 90,
        "cts_final_plot_plan": 90,
    },
    "planning": {"dp_remarks": 100},
}

_TYPE_ALIASES = {
    "cts/fp": "cts_fp",
    "cts_fp_plan": "cts_fp",
    "cts_final_plot_plan": "cts_final_plot",
    "final_plot": "cts_final_plot",
    "final_plot_plan": "cts_final_plot",
    "total station": "total_station",
    "total_station_survey": "total_station",
    "property card": "property_card",
    "city survey": "city_survey",
    "dp remarks": "dp_remarks",
    "dp_remarks_plan": "dp_remarks",
}

_WITHDRAWN = {"withdrawn", "revoked", "superseded", "rejected", "deleted"}

_SOURCE_LABELS = {
    "property_card": "Property Card",
    "cts_fp": "Certified CTS / Final Plot plan",
    "cts_final_plot": "Certified CTS / Final Plot plan",
    "city_survey": "City Survey measurement record",
    "total_station": "Licensed total-station survey",
    "dp_remarks": "Official DP Remarks plan",
    "reconciliation": "Certified survey reconciliation",
    "certified_survey_reconciliation": "Certified survey reconciliation",
    "other_official_document": "Other official document",
}


def _value(record: Any, *names: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().casefold()


def normalize_source_type(value: Any) -> str:
    raw = _enum_value(value).replace("-", "_")
    raw = "_".join(raw.split())
    return _TYPE_ALIASES.get(raw, raw)


def normalize_purpose(value: Any) -> str:
    raw = _enum_value(value).replace("-", "_")
    raw = "_".join(raw.split())
    aliases = {
        "area": "area_reconciliation",
        "geometry": "geometry_reconciliation",
        "geometry_area": "geometry_reconciliation",
        "planning_remarks": "planning",
    }
    return aliases.get(raw, raw)


def source_type_label(value: Any) -> str:
    """Return an intuitive public label without exposing storage enum names."""
    normalized = normalize_source_type(value)
    return _SOURCE_LABELS.get(normalized, normalized.replace("_", " ").title() or "Authority source")


def _record_dict(record: Any) -> Dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return dict(value)
    try:
        return dict(vars(record))
    except TypeError:
        return {"value": str(record)}


def _record_id(record: Any) -> Union[int, str]:
    value = _value(record, "version_id", "source_version_id", "record_id", "source_id", "id")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return str(value) if value is not None else ""


def _checksum(record: Any) -> str:
    value = _value(
        record,
        "document_checksum",
        "source_sha256",
        "checksum",
        "sha256",
        "content_hash",
        "record_checksum",
        "geometry_checksum",
        default="",
    )
    if value:
        return str(value)
    # A stable fallback is useful for injected records and old registries.
    return hashlib.sha256(
        json.dumps(_record_dict(record), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _date_key(value: Any) -> Tuple[int, str]:
    if value is None:
        return (0, "")
    text = str(getattr(value, "isoformat", lambda: value)())
    try:
        return (1, datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat())
    except ValueError:
        return (1, text)


def _area(record: Any, purpose: Optional[str] = None) -> Optional[float]:
    names = (
        ("calculated_area_sqm", "area_sqm", "recorded_area_sqm", "area", "plot_area_sqm")
        if purpose == "geometry_reconciliation"
        else ("area_sqm", "recorded_area_sqm", "calculated_area_sqm", "area", "plot_area_sqm")
    )
    value = _value(record, *names)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _geometry(record: Any) -> Any:
    value = _value(
        record,
        "normalized_epsg3857_rings",
        "geometry",
        "rings",
        "geometry_rings",
        "boundary",
    )
    if isinstance(value, Mapping):
        return value.get("rings", value.get("coordinates", value))
    return value


def _geometry_checksum(record: Any) -> str:
    value = _value(record, "geometry_checksum", "geometry_sha256", "geometry_hash")
    if value:
        return str(value)
    geometry = _geometry(record)
    if geometry is None:
        return ""
    return hashlib.sha256(
        json.dumps(geometry, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _identity_matches(record: Any, village: Optional[str], cts_no: Optional[str]) -> bool:
    if village is None and cts_no is None:
        return True
    returned_village = str(_value(record, "village", "village_name", default="") or "").strip().casefold()
    returned_cts = str(_value(record, "cts_no", "cts", "cts_cs_no", default="") or "").strip().casefold()
    return (village is None or returned_village == village.strip().casefold()) and (
        cts_no is None or returned_cts == cts_no.strip().casefold()
    )


def _eligible(record: Any, village: Optional[str], cts_no: Optional[str]) -> Tuple[bool, str]:
    if not _identity_matches(record, village, cts_no):
        return False, "identity does not exactly match the requested village/CTS"
    status = _enum_value(_value(record, "status", "record_status", default=""))
    if status in _WITHDRAWN:
        return False, f"source status is {status}"
    if status != "verified":
        return False, "source is not verified"
    # ``supersedes_id`` points from a new replacement to the old record; it is
    # not itself evidence that the new record is superseded.  The old record
    # is excluded by its lifecycle status (or by an explicit superseded_by
    # marker in alternate registries).
    if _value(record, "superseded_by", "superseded_at") is not None:
        return False, "source version is superseded"
    return True, "verified and current"


@dataclass(frozen=True)
class AuthorityCandidate:
    """Explainable normalized view of one registry record."""

    record: Any
    record_id: Union[int, str]
    source_type: str
    purpose: str
    rank: int
    area_sqm: Optional[float]
    geometry_checksum: str
    checksum: str
    effective_date: Optional[str]
    verification_date: Optional[str]
    eligible: bool
    eligibility_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_type": self.source_type,
            "purpose": self.purpose,
            "rank": self.rank,
            "area_sqm": self.area_sqm,
            "geometry_checksum": self.geometry_checksum or None,
            "checksum": self.checksum,
            "effective_date": self.effective_date,
            "verification_date": self.verification_date,
            "eligible": self.eligible,
            "eligibility_reason": self.eligibility_reason,
            "record": _record_dict(self.record),
        }

    def to_ref(self, *, selection_reason: str = "") -> Dict[str, Any]:
        """Return the compact source reference used by result provenance."""
        issue_date = _value(self.record, "issue_date", "issued_date", "effective_date", "document_date")
        fallback_label = source_type_label(_value(self.record, "source_type", default=self.source_type))
        return {
            "record_id": self.record_id,
            "source_type": self.source_type,
            "source_label": str(
                _value(self.record, "source_label", "display_name", "document_type", default=fallback_label)
            ),
            "version": str(_value(self.record, "version", "version_id", "source_version_id", default="") or ""),
            "issuer": str(_value(self.record, "issuer", "issued_by", "authority", default="") or ""),
            "reference_no": str(
                _value(self.record, "reference_no", "document_reference", "document_number", default="") or ""
            ),
            "issue_date": str(issue_date) if issue_date is not None else None,
            "document_sha256": self.checksum,
            "selected_value_sqm": self.area_sqm,
            "calculated_area_sqm": self.area_sqm if self.purpose == "geometry_reconciliation" else None,
            "selection_reason": selection_reason,
        }


@dataclass(frozen=True)
class AuthorityResolution:
    """Recommendation or explicit selection, including why it was made."""

    purpose: str
    policy_version: str
    selected: Optional[AuthorityCandidate]
    candidates: Sequence[AuthorityCandidate] = field(default_factory=tuple)
    conflict: bool = False
    reason: str = "No eligible authority source was found."
    active: bool = False
    village: str = ""
    cts_no: str = ""
    baseline_area_assessment: Optional[Mapping[str, Any]] = None
    applied_to_working_result: bool = False

    @property
    def has_selection(self) -> bool:
        return self.selected is not None and not self.conflict

    def to_dict(self) -> Dict[str, Any]:
        selected_ref = self.selected.to_ref(selection_reason=self.reason) if self.selected is not None else None
        status = "conflict" if self.conflict else ("selected" if selected_ref else "no_selection")
        planning = [selected_ref] if selected_ref and self.purpose == "planning" else []
        return {
            "policy_version": self.policy_version,
            "mode": "active" if self.active else "recommended",
            "village": self.village,
            "cts_no": self.cts_no,
            "status": status,
            "area": selected_ref if self.purpose == "area_reconciliation" else None,
            "geometry": selected_ref if self.purpose == "geometry_reconciliation" else None,
            "planning": planning,
            "active_record_ids": [self.selected.record_id] if self.active and self.selected else [],
            "evaluated_record_ids": [candidate.record_id for candidate in self.candidates if candidate.record_id],
            "reasons": [self.reason],
            "conflicts": [self.reason] if self.conflict else [],
            "baseline_area_assessment": dict(self.baseline_area_assessment or {}),
            "applied_to_working_result": self.applied_to_working_result,
        }


def _candidate(record: Any, purpose: str, village: Optional[str], cts_no: Optional[str]) -> AuthorityCandidate:
    source_type = normalize_source_type(_value(record, "source_type", "type", "kind", default=""))
    purpose_value = normalize_purpose(_value(record, "purpose", "selection_purpose", default=purpose))
    rank = _RANKS.get(purpose, {}).get(source_type, 0)
    eligible, reason = _eligible(record, village, cts_no)
    if rank <= 0:
        eligible, reason = False, f"source type '{source_type or 'unknown'}' is not allowed for {purpose}"
    if _area(record, purpose) is None and purpose == "area_reconciliation":
        eligible, reason = False, "source has no usable area"
    if _geometry(record) is None and purpose == "geometry_reconciliation":
        eligible, reason = False, "source has no usable geometry"
    effective = _value(record, "effective_date", "issued_date", "document_date")
    verified = _value(record, "verification_date", "verified_at", "reviewed_at")
    return AuthorityCandidate(
        record=record,
        record_id=_record_id(record),
        source_type=source_type,
        purpose=purpose_value,
        rank=rank,
        area_sqm=_area(record, purpose),
        geometry_checksum=_geometry_checksum(record),
        checksum=_checksum(record),
        effective_date=str(effective) if effective is not None else None,
        verification_date=str(verified) if verified is not None else None,
        eligible=eligible,
        eligibility_reason=reason,
    )


def recommend_authority_sources(
    records: Iterable[Any],
    purpose: Any,
    *,
    village: Optional[str] = None,
    cts_no: Optional[str] = None,
    active: bool = False,
    baseline_area_assessment: Optional[Mapping[str, Any]] = None,
    applied_to_working_result: bool = False,
) -> AuthorityResolution:
    """Rank records deterministically without applying the recommendation."""
    purpose_value = normalize_purpose(purpose)
    candidates = tuple(_candidate(record, purpose_value, village, cts_no) for record in records)
    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return AuthorityResolution(
            purpose=purpose_value,
            policy_version=AUTHORITY_POLICY_VERSION,
            selected=None,
            candidates=candidates,
            reason="No verified, current, identity-matched source is eligible for this purpose.",
            active=active,
            village=village or "",
            cts_no=cts_no or "",
            baseline_area_assessment=baseline_area_assessment,
            applied_to_working_result=applied_to_working_result,
        )
    top_rank = max(candidate.rank for candidate in eligible)
    top = [candidate for candidate in eligible if candidate.rank == top_rank]
    area_signatures = {round(candidate.area_sqm, 6) for candidate in top if candidate.area_sqm is not None}
    geometry_signatures = {candidate.geometry_checksum for candidate in top if candidate.geometry_checksum}
    area_conflict = purpose_value == "area_reconciliation" and len(area_signatures) > 1
    geometry_conflict = purpose_value == "geometry_reconciliation" and len(geometry_signatures) > 1
    if area_conflict or geometry_conflict:
        conflict_kind = "area" if area_conflict else "geometry"
        return AuthorityResolution(
            purpose=purpose_value,
            policy_version=AUTHORITY_POLICY_VERSION,
            selected=None,
            candidates=candidates,
            conflict=True,
            reason=f"Top-rank sources disagree on {conflict_kind}; no source was selected automatically.",
            active=active,
            village=village or "",
            cts_no=cts_no or "",
            baseline_area_assessment=baseline_area_assessment,
            applied_to_working_result=applied_to_working_result,
        )
    dated = sorted(
        top,
        key=lambda candidate: (_date_key(candidate.effective_date), _date_key(candidate.verification_date)),
        reverse=True,
    )
    latest_dates = (
        _date_key(dated[0].effective_date),
        _date_key(dated[0].verification_date),
    )
    # A checksum is a deterministic final tie-breaker. Ascending is
    # intentional: it is stable and does not imply that one hash is more
    # authoritative than another.
    selected = min(
        (
            candidate
            for candidate in dated
            if (_date_key(candidate.effective_date), _date_key(candidate.verification_date)) == latest_dates
        ),
        key=lambda candidate: candidate.checksum,
    )
    return AuthorityResolution(
        purpose=purpose_value,
        policy_version=AUTHORITY_POLICY_VERSION,
        selected=selected,
        candidates=candidates,
        reason=(
            f"Selected verified {selected.source_type} source at rank {selected.rank}; "
            "ties were resolved by effective date, verification date and checksum."
        ),
        active=active,
        village=village or "",
        cts_no=cts_no or "",
        baseline_area_assessment=baseline_area_assessment,
        applied_to_working_result=applied_to_working_result,
    )


def recommend_authority(store: Any, village: str, cts_no: str) -> Dict[str, Any]:
    """Return JSON-safe, field-specific recommendations for the CLI."""
    list_method = getattr(store, "list", None) or getattr(store, "records", None)
    if not callable(list_method):
        raise TypeError("authority store does not expose a record listing operation")
    try:
        records = tuple(list_method(village=village, cts_no=cts_no))
    except TypeError:
        records = tuple(list_method())
    resolutions = {
        purpose: recommend_authority_sources(
            records,
            policy_purpose,
            village=village,
            cts_no=cts_no,
        ).to_dict()
        for purpose, policy_purpose in (
            ("area", "area_reconciliation"),
            ("geometry", "geometry_reconciliation"),
            ("planning", "planning"),
        )
    }
    return {
        "policy_version": AUTHORITY_POLICY_VERSION,
        "village": village.strip().upper(),
        "cts_no": cts_no.strip().upper(),
        "recommendations": resolutions,
        "requires_explicit_activation": True,
    }


__all__ = [
    "AUTHORITY_POLICY_VERSION",
    "AuthorityCandidate",
    "AuthorityResolution",
    "normalize_purpose",
    "normalize_source_type",
    "recommend_authority",
    "recommend_authority_sources",
    "source_type_label",
]
