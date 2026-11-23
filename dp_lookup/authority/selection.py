"""Deterministic recommendations for versioned authority records.

This module deliberately does not mutate a parcel or decide which source is
operationally active.  It ranks *verified* records and explains the result.
The resolver is the only module which may apply an explicitly active source.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from dp_lookup.authority.models import AuthorityRecord, SelectionPurpose, SourceStatus, SourceType

AUTHORITY_POLICY_VERSION = "authority-policy/1.0"

_RANKS: dict[SelectionPurpose, dict[SourceType, int]] = {
    SelectionPurpose.AREA: {
        SourceType.CERTIFIED_SURVEY_RECONCILIATION: 110,
        SourceType.PROPERTY_CARD: 100,
        SourceType.CITY_SURVEY_MEASUREMENT: 95,
        SourceType.CTS_FINAL_PLOT_PLAN: 90,
        SourceType.TOTAL_STATION_SURVEY: 70,
    },
    SelectionPurpose.GEOMETRY: {
        SourceType.CERTIFIED_SURVEY_RECONCILIATION: 110,
        SourceType.TOTAL_STATION_SURVEY: 100,
        SourceType.CITY_SURVEY_MEASUREMENT: 95,
        SourceType.CTS_FINAL_PLOT_PLAN: 90,
    },
    SelectionPurpose.PLANNING: {SourceType.DP_REMARKS: 100},
}

_SOURCE_LABELS: dict[SourceType, str] = {
    SourceType.PROPERTY_CARD: "Property Card",
    SourceType.CTS_FINAL_PLOT_PLAN: "Certified CTS / Final Plot plan",
    SourceType.CITY_SURVEY_MEASUREMENT: "City Survey measurement record",
    SourceType.TOTAL_STATION_SURVEY: "Licensed total-station survey",
    SourceType.DP_REMARKS: "Official DP Remarks plan",
    SourceType.CERTIFIED_SURVEY_RECONCILIATION: "Certified survey reconciliation",
    SourceType.OTHER_OFFICIAL_DOCUMENT: "Other official document",
}

_RETIRED = frozenset({SourceStatus.SUPERSEDED, SourceStatus.WITHDRAWN, SourceStatus.REJECTED})


class AuthorityRegistry(Protocol):
    """The two reads the selector and resolver make; ``AuthorityStore`` implements both."""

    def list(self, village: str | None = None, cts_no: str | None = None) -> Sequence[AuthorityRecord]: ...

    def active(self, village: str, cts_no: str, *, purpose: SelectionPurpose) -> Sequence[AuthorityRecord]: ...


def source_type_label(source_type: SourceType) -> str:
    """Return the public label for a source type."""
    return _SOURCE_LABELS[source_type]


def _date_key(value: str | None) -> tuple[int, str]:
    if value is None:
        return (0, "")
    try:
        return (1, datetime.fromisoformat(value).isoformat())
    except ValueError:
        return (1, value)


def _area(record: AuthorityRecord, purpose: SelectionPurpose) -> float | None:
    if purpose is SelectionPurpose.GEOMETRY:
        value = record.calculated_area_sqm
    elif record.recorded_area_sqm is not None:
        value = record.recorded_area_sqm
    else:
        value = record.calculated_area_sqm
    return value if value is not None and value > 0 else None


def _identity_matches(record: AuthorityRecord, village: str | None, cts_no: str | None) -> bool:
    return (village is None or record.village.strip().casefold() == village.strip().casefold()) and (
        cts_no is None or record.cts_no.strip().casefold() == cts_no.strip().casefold()
    )


def _eligibility(
    record: AuthorityRecord,
    purpose: SelectionPurpose,
    rank: int,
    area_sqm: float | None,
    village: str | None,
    cts_no: str | None,
) -> tuple[bool, str]:
    if purpose is SelectionPurpose.GEOMETRY and not record.normalized_epsg3857_rings:
        return False, "source has no usable geometry"
    if purpose is SelectionPurpose.AREA and area_sqm is None:
        return False, "source has no usable area"
    if rank <= 0:
        return False, f"source type '{record.source_type.value}' is not allowed for {purpose.value}"
    if not _identity_matches(record, village, cts_no):
        return False, "identity does not exactly match the requested village/CTS"
    if record.status in _RETIRED:
        return False, f"source status is {record.status.value}"
    if record.status is not SourceStatus.VERIFIED:
        return False, "source is not verified"
    return True, "verified and current"


@dataclass(frozen=True)
class AuthorityCandidate:
    """Explainable view of one registry record for one purpose."""

    record: AuthorityRecord
    purpose: SelectionPurpose
    rank: int
    area_sqm: float | None
    eligible: bool
    eligibility_reason: str

    @property
    def record_id(self) -> int:
        return self.record.record_id

    @property
    def source_type(self) -> SourceType:
        return self.record.source_type

    @property
    def checksum(self) -> str:
        return self.record.source_sha256

    @property
    def geometry_checksum(self) -> str | None:
        return self.record.geometry_sha256

    @property
    def effective_date(self) -> str | None:
        return self.record.issue_date or self.record.survey_date

    @property
    def verification_date(self) -> str | None:
        return self.record.reviewed_at

    def _dates(self) -> tuple[tuple[int, str], tuple[int, str]]:
        return _date_key(self.effective_date), _date_key(self.verification_date)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_type": self.source_type.value,
            "purpose": self.purpose.value,
            "rank": self.rank,
            "area_sqm": self.area_sqm,
            "geometry_checksum": self.geometry_checksum,
            "checksum": self.checksum,
            "effective_date": self.effective_date,
            "verification_date": self.verification_date,
            "eligible": self.eligible,
            "eligibility_reason": self.eligibility_reason,
            "record": self.record.to_dict(),
        }

    def to_ref(self, *, selection_reason: str = "") -> dict[str, Any]:
        """Return the compact source reference used by result provenance."""
        return {
            "record_id": self.record_id,
            "source_type": self.source_type.value,
            "source_label": source_type_label(self.source_type),
            "version": str(self.record.version),
            "issuer": self.record.issuer or "",
            "reference_no": self.record.reference_no or "",
            "issue_date": self.record.issue_date,
            "document_sha256": self.checksum,
            "selected_value_sqm": self.area_sqm,
            "calculated_area_sqm": self.area_sqm if self.purpose is SelectionPurpose.GEOMETRY else None,
            "selection_reason": selection_reason,
        }


@dataclass(frozen=True)
class AuthorityResolution:
    """Recommendation or explicit selection, including why it was made."""

    purpose: SelectionPurpose
    policy_version: str
    selected: AuthorityCandidate | None
    candidates: Sequence[AuthorityCandidate] = field(default_factory=tuple)
    conflict: bool = False
    reason: str = "No eligible authority source was found."
    active: bool = False
    village: str = ""
    cts_no: str = ""
    baseline_area_assessment: Mapping[str, Any] | None = None
    applied_to_working_result: bool = False

    @property
    def has_selection(self) -> bool:
        return self.selected is not None and not self.conflict

    def to_dict(self) -> dict[str, Any]:
        selected_ref = self.selected.to_ref(selection_reason=self.reason) if self.selected is not None else None
        status = "conflict" if self.conflict else ("selected" if selected_ref else "no_selection")
        planning = [selected_ref] if selected_ref and self.purpose is SelectionPurpose.PLANNING else []
        return {
            "policy_version": self.policy_version,
            "mode": "active" if self.active else "recommended",
            "village": self.village,
            "cts_no": self.cts_no,
            "status": status,
            "area": selected_ref if self.purpose is SelectionPurpose.AREA else None,
            "geometry": selected_ref if self.purpose is SelectionPurpose.GEOMETRY else None,
            "planning": planning,
            "active_record_ids": [self.selected.record_id] if self.active and self.selected else [],
            "evaluated_record_ids": [candidate.record_id for candidate in self.candidates],
            "reasons": [self.reason],
            "conflicts": [self.reason] if self.conflict else [],
            "baseline_area_assessment": dict(self.baseline_area_assessment or {}),
            "applied_to_working_result": self.applied_to_working_result,
        }


def _candidate(
    record: AuthorityRecord, purpose: SelectionPurpose, village: str | None, cts_no: str | None
) -> AuthorityCandidate:
    rank = _RANKS[purpose].get(record.source_type, 0)
    area_sqm = _area(record, purpose)
    eligible, reason = _eligibility(record, purpose, rank, area_sqm, village, cts_no)
    return AuthorityCandidate(
        record=record,
        purpose=purpose,
        rank=rank,
        area_sqm=area_sqm,
        eligible=eligible,
        eligibility_reason=reason,
    )


def recommend_authority_sources(
    records: Iterable[AuthorityRecord],
    purpose: SelectionPurpose,
    *,
    village: str | None = None,
    cts_no: str | None = None,
    active: bool = False,
    baseline_area_assessment: Mapping[str, Any] | None = None,
    applied_to_working_result: bool = False,
) -> AuthorityResolution:
    """Rank records deterministically without applying the recommendation."""
    candidates = tuple(_candidate(record, purpose, village, cts_no) for record in records)

    def resolution(selected: AuthorityCandidate | None, reason: str, *, conflict: bool = False) -> AuthorityResolution:
        return AuthorityResolution(
            purpose=purpose,
            policy_version=AUTHORITY_POLICY_VERSION,
            selected=selected,
            candidates=candidates,
            conflict=conflict,
            reason=reason,
            active=active,
            village=village or "",
            cts_no=cts_no or "",
            baseline_area_assessment=baseline_area_assessment,
            applied_to_working_result=applied_to_working_result,
        )

    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return resolution(None, "No verified, current, identity-matched source is eligible for this purpose.")
    top_rank = max(candidate.rank for candidate in eligible)
    top = [candidate for candidate in eligible if candidate.rank == top_rank]
    area_signatures = {round(candidate.area_sqm, 6) for candidate in top if candidate.area_sqm is not None}
    geometry_signatures = {candidate.geometry_checksum for candidate in top if candidate.geometry_checksum}
    area_conflict = purpose is SelectionPurpose.AREA and len(area_signatures) > 1
    geometry_conflict = purpose is SelectionPurpose.GEOMETRY and len(geometry_signatures) > 1
    if area_conflict or geometry_conflict:
        conflict_kind = "area" if area_conflict else "geometry"
        return resolution(
            None,
            f"Top-rank sources disagree on {conflict_kind}; no source was selected automatically.",
            conflict=True,
        )
    latest_dates = max(candidate._dates() for candidate in top)
    selected = min(
        (candidate for candidate in top if candidate._dates() == latest_dates),
        key=lambda candidate: candidate.checksum,
    )
    return resolution(
        selected,
        f"Selected verified {selected.source_type.value} source at rank {selected.rank}; "
        "ties were resolved by effective date, verification date and checksum.",
    )


def recommend_authority(store: AuthorityRegistry, village: str, cts_no: str) -> dict[str, Any]:
    """Return JSON-safe, field-specific recommendations for the CLI."""
    records = tuple(store.list(village, cts_no))
    return {
        "policy_version": AUTHORITY_POLICY_VERSION,
        "village": village.strip().upper(),
        "cts_no": cts_no.strip().upper(),
        "recommendations": {
            purpose.value: recommend_authority_sources(records, purpose, village=village, cts_no=cts_no).to_dict()
            for purpose in SelectionPurpose
        },
        "requires_explicit_activation": True,
    }


__all__ = [
    "AUTHORITY_POLICY_VERSION",
    "AuthorityCandidate",
    "AuthorityRegistry",
    "AuthorityResolution",
    "recommend_authority",
    "recommend_authority_sources",
    "source_type_label",
]
