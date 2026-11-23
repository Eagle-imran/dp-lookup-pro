"""Deterministic authority-source policy and explicit-activation tests."""

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from dp_lookup.application.authority_resolver import AuthorityResolver
from dp_lookup.application.ingestion import build_parcel_context
from dp_lookup.authority import (
    AuthorityManifest,
    AuthorityRecord,
    AuthorityStore,
    SelectionPurpose,
    SourceStatus,
    SourceType,
)
from dp_lookup.authority.selection import recommend_authority_sources, source_type_label

RING = [
    [8_106_500.0, 2_151_700.0],
    [8_106_510.0, 2_151_700.0],
    [8_106_510.0, 2_151_710.0],
    [8_106_500.0, 2_151_710.0],
    [8_106_500.0, 2_151_700.0],
]


def record(**overrides: Any) -> AuthorityRecord:
    fields: dict[str, Any] = {
        "record_id": 1,
        "village": "WORLI",
        "cts_no": "733",
        "source_type": SourceType.PROPERTY_CARD,
        "status": SourceStatus.VERIFIED,
        "version": 1,
        "issuer": "City Survey Office",
        "reference_no": None,
        "issue_date": "2026-01-01",
        "survey_date": None,
        "source_uri": "card.pdf",
        "source_sha256": "a",
        "mime_type": None,
        "byte_size": None,
        "ward": None,
        "recorded_area_sqm": 1317.74,
        "original_geometry": None,
        "original_crs": None,
        "normalized_epsg3857_rings": (),
        "geometry_sha256": None,
        "calculated_area_sqm": None,
        "supersedes_id": None,
        "metadata": {},
        "created_by": None,
        "reviewed_by": "reviewer",
        "created_at": "2026-01-01T00:00:00+00:00",
        "reviewed_at": "2026-01-02",
        "updated_at": "2026-01-02T00:00:00+00:00",
        "record_checksum": "0" * 64,
    }
    fields.update(overrides)
    return AuthorityRecord(**fields)


class Store:
    def __init__(self, records: Iterable[AuthorityRecord], active: Mapping[SelectionPurpose, list[AuthorityRecord]]):
        self.records = tuple(records)
        self.selections = active

    def list(self, village: str | None = None, cts_no: str | None = None) -> tuple[AuthorityRecord, ...]:
        del village, cts_no
        return self.records

    def active(self, village: str, cts_no: str, *, purpose: SelectionPurpose) -> tuple[AuthorityRecord, ...]:
        del village, cts_no
        return tuple(self.selections.get(purpose, ()))


def parcel():
    return build_parcel_context(
        {
            "attributes": {
                "OBJECTID": 1,
                "VILLAGE": "WORLI",
                "CTS_CS_NO": "733",
                "WARD": "G/S",
                "TYPE": "CTS",
                "AREA_APP_SQ_MTRS": 1317.74,
            },
            "geometry": {"rings": [RING]},
        },
        "WORLI",
        "733",
    )[0]


def test_field_specific_ranks_prefer_property_card_for_area_and_total_station_for_geometry():
    property_card = record(record_id=1, source_sha256="property")
    survey = record(
        record_id=2,
        source_type=SourceType.TOTAL_STATION_SURVEY,
        source_sha256="survey",
        normalized_epsg3857_rings=[RING],
        geometry_sha256="g",
        calculated_area_sqm=100.0,
    )

    area = recommend_authority_sources([survey, property_card], SelectionPurpose.AREA, village="WORLI", cts_no="733")
    geometry = recommend_authority_sources(
        [property_card, survey], SelectionPurpose.GEOMETRY, village="WORLI", cts_no="733"
    )

    assert area.selected is not None and area.selected.source_type is SourceType.PROPERTY_CARD
    assert area.selected.rank == 100
    assert set(area.to_dict()) == {
        "policy_version",
        "mode",
        "village",
        "cts_no",
        "status",
        "area",
        "geometry",
        "planning",
        "active_record_ids",
        "evaluated_record_ids",
        "reasons",
        "conflicts",
        "baseline_area_assessment",
        "applied_to_working_result",
    }
    assert area.to_dict()["area"]["selected_value_sqm"] == 1317.74
    assert area.to_dict()["area"]["source_label"] == "Property Card"
    assert "selection_reason" in area.to_dict()["area"]
    assert geometry.selected is not None and geometry.selected.source_type is SourceType.TOTAL_STATION_SURVEY
    assert geometry.selected.rank == 100
    assert geometry.to_dict()["geometry"]["calculated_area_sqm"] == 100.0


def test_ranks_cover_every_purpose_and_labels_cover_every_source_type():
    assert {source_type_label(source_type) for source_type in SourceType}
    for purpose in SelectionPurpose:
        result = recommend_authority_sources([record(source_type=SourceType.OTHER_OFFICIAL_DOCUMENT)], purpose)
        assert result.selected is None


def test_unverified_superseded_and_wrong_identity_records_are_rejected():
    records = [
        record(record_id=1, status=SourceStatus.REGISTERED, source_sha256="draft"),
        record(record_id=2, status=SourceStatus.SUPERSEDED, source_sha256="old"),
        record(record_id=3, village="COLABA", source_sha256="other"),
    ]
    result = recommend_authority_sources(records, SelectionPurpose.AREA, village="WORLI", cts_no="733")

    assert result.selected is None
    assert [item.eligibility_reason for item in result.candidates] == [
        "source is not verified",
        "source status is superseded",
        "identity does not exactly match the requested village/CTS",
    ]


def test_verified_replacement_record_is_eligible_when_it_supersedes_an_older_version():
    replacement = record(source_sha256="replacement", supersedes_id=1)
    result = recommend_authority_sources([replacement], SelectionPurpose.AREA, village="WORLI", cts_no="733")
    assert result.selected is not None


def test_same_top_rank_disagreement_is_a_conflict_and_selects_nothing():
    first = record(record_id=1, recorded_area_sqm=100.0, source_sha256="a")
    second = record(record_id=2, recorded_area_sqm=200.0, source_sha256="b")
    result = recommend_authority_sources([first, second], SelectionPurpose.AREA, village="WORLI", cts_no="733")

    assert result.conflict is True
    assert result.selected is None
    assert "disagree" in result.reason


def test_tie_breaks_by_effective_date_then_verification_date_then_checksum():
    old = record(record_id=1, issue_date="2025-01-01", source_sha256="z")
    new = record(record_id=2, issue_date="2026-01-01", source_sha256="a")
    result = recommend_authority_sources([old, new], SelectionPurpose.AREA, village="WORLI", cts_no="733")
    assert result.selected is not None and result.selected.record_id == 2

    same_date_z = record(record_id=3, issue_date="2026-01-01", reviewed_at="2026-01-01", source_sha256="z")
    same_date_a = record(record_id=4, issue_date="2026-01-01", reviewed_at="2026-01-01", source_sha256="a")
    result = recommend_authority_sources(
        [same_date_z, same_date_a], SelectionPurpose.AREA, village="WORLI", cts_no="733"
    )
    assert result.selected is not None and result.selected.record_id == 4


def test_resolver_does_not_apply_recommendations_and_only_applies_active_sources():
    property_card = record(recorded_area_sqm=1400.0, source_sha256="pc")
    store = Store([property_card], active={})
    base = parcel()
    resolved = AuthorityResolver(store).resolve(base)

    assert resolved.area_sqm == base.area_sqm
    assert resolved.attrs["_DP_AUTHORITY_ACTIVE"] is False
    assert resolved.attrs["_DP_AUTHORITY_RESOLUTION"]["area"] is None


def test_resolver_applies_active_area_and_geometry_but_preserves_baseline():
    survey = record(
        record_id=2,
        source_type=SourceType.TOTAL_STATION_SURVEY,
        recorded_area_sqm=150.0,
        normalized_epsg3857_rings=[
            [
                [8_106_500.0, 2_151_700.0],
                [8_106_520.0, 2_151_700.0],
                [8_106_520.0, 2_151_710.0],
                [8_106_500.0, 2_151_710.0],
                [8_106_500.0, 2_151_700.0],
            ]
        ],
        geometry_sha256="survey-geometry",
        calculated_area_sqm=200.0,
        source_sha256="survey",
    )
    property_card = record(record_id=1, recorded_area_sqm=150.0, source_sha256="pc")
    store = Store(
        [property_card, survey],
        active={SelectionPurpose.AREA: [property_card], SelectionPurpose.GEOMETRY: [survey]},
    )
    resolved = AuthorityResolver(store).resolve(parcel())
    resolution = resolved.attrs["_DP_AUTHORITY_RESOLUTION"]

    assert resolved.area_sqm == 150.0
    assert resolved.area_source == "Property Card"
    assert resolved.rings != parcel().rings
    assert resolution["baseline"]["area_sqm"] == parcel().area_sqm
    assert resolution["working"]["geometry_replaced"] is True
    assert resolution["working"]["calculated_boundary_area_sqm"] is not None
    assert resolution["active_record_ids"] == [1, 2]
    assert resolved.attrs["_DP_AUTHORITY_GEOMETRY_SOURCE"] == "Licensed total-station survey"


def test_resolver_reads_real_store_active_mapping_and_refreshes_assessment(tmp_path: Path):
    document = tmp_path / "property-card.pdf"
    document.write_bytes(b"property card")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    with AuthorityStore.open(tmp_path / "authority.sqlite") as store:
        record = store.register(
            AuthorityManifest(
                village="WORLI",
                cts_no="733",
                source_type=SourceType.PROPERTY_CARD,
                source_uri=document.name,
                source_sha256=digest,
                issuer="City Survey Office",
                recorded_area_sqm=1400.0,
            ),
            manifest_dir=tmp_path,
        )
        store.verify(record.record_id, actor="reviewer", manifest_dir=tmp_path)
        store.activate(record.record_id, SelectionPurpose.AREA, actor="reviewer", reason="accepted area")

        resolved = AuthorityResolver(store).resolve(parcel())

    assert resolved.area_sqm == 1400.0
    assert resolved.area_source == "Property Card"
    assert resolved.area_assessment is not None
    assert resolved.area_assessment.selected_area_basis == "authority_area"
    assert resolved.attrs["_DP_AREA_ASSESSMENT"]["selected_area_sqm"] == 1400.0
    assert resolved.attrs["_DP_AUTHORITY_RESOLUTION"]["active_record_ids"] == [record.record_id]
    assert resolved.attrs["_DP_AUTHORITY_RESOLUTION"]["applied_to_working_result"] is True
