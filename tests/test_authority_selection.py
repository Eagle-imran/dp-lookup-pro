"""Deterministic authority-source policy and explicit-activation tests."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from dp_lookup.application.authority_resolver import AuthorityResolver
from dp_lookup.application.ingestion import build_parcel_context
from dp_lookup.authority import AuthorityManifest, AuthorityStore, SelectionPurpose, SourceType
from dp_lookup.authority.selection import recommend_authority_sources

RING = [
    [8_106_500.0, 2_151_700.0],
    [8_106_510.0, 2_151_700.0],
    [8_106_510.0, 2_151_710.0],
    [8_106_500.0, 2_151_710.0],
    [8_106_500.0, 2_151_700.0],
]


@dataclass(frozen=True)
class Record:
    village: str = "WORLI"
    cts_no: str = "733"
    source_type: str = "property_card"
    status: str = "verified"
    area_sqm: float = 1317.74
    geometry: Any = None
    geometry_crs: int = 102100
    checksum: str = "a"
    effective_date: str = "2026-01-01"
    verification_date: str = "2026-01-02"
    record_id: str = "r1"
    superseded_by: Any = None
    supersedes_id: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class Store:
    def __init__(self, records: Iterable[Record], active: Iterable[Record] = ()) -> None:
        self.records = list(records)
        self.active_records = list(active)

    def list(self, **_kwargs: Any) -> List[Record]:
        return list(self.records)

    def active(self, **kwargs: Any) -> List[Record]:
        purpose = kwargs.get("purpose") or kwargs.get("selection_purpose")
        return [
            item
            for item in self.active_records
            if (
                purpose in {None, "area", "area_reconciliation"}
                and item.source_type in {"property_card", "city_survey"}
            )
            or (purpose in {"geometry", "geometry_reconciliation"} and item.geometry is not None)
        ]


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
    property_card = Record(source_type="property_card", checksum="property")
    survey = Record(source_type="total_station", checksum="survey", geometry=[RING])

    area = recommend_authority_sources([survey, property_card], "area_reconciliation", village="WORLI", cts_no="733")
    geometry = recommend_authority_sources(
        [property_card, survey], "geometry_reconciliation", village="WORLI", cts_no="733"
    )

    assert area.selected is not None and area.selected.source_type == "property_card"
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
    assert "selection_reason" in area.to_dict()["area"]
    assert geometry.selected is not None and geometry.selected.source_type == "total_station"
    assert geometry.selected.rank == 100


def test_unverified_superseded_and_wrong_identity_records_are_rejected():
    records = [
        Record(status="draft", checksum="draft"),
        Record(superseded_by="r2", checksum="old"),
        Record(village="COLABA", checksum="other"),
    ]
    result = recommend_authority_sources(records, "area_reconciliation", village="WORLI", cts_no="733")

    assert result.selected is None
    assert all(not item.eligible for item in result.candidates)
    assert all(item.eligibility_reason for item in result.candidates)


def test_verified_replacement_record_is_eligible_when_it_supersedes_an_older_version():
    # The registry's ``supersedes_id`` points backwards from the replacement;
    # only the old record becomes superseded and should be excluded.
    replacement = Record(checksum="replacement", supersedes_id=1)
    result = recommend_authority_sources([replacement], "area_reconciliation", village="WORLI", cts_no="733")
    assert result.selected is not None


def test_same_top_rank_disagreement_is_a_conflict_and_selects_nothing():
    first = Record(area_sqm=100.0, checksum="a", record_id="one")
    second = Record(area_sqm=200.0, checksum="b", record_id="two")
    result = recommend_authority_sources([first, second], "area_reconciliation", village="WORLI", cts_no="733")

    assert result.conflict is True
    assert result.selected is None
    assert "disagree" in result.reason


def test_tie_breaks_by_effective_date_then_verification_date_then_checksum():
    old = Record(effective_date="2025-01-01", checksum="z", record_id="old")
    new = Record(effective_date="2026-01-01", checksum="a", record_id="new")
    result = recommend_authority_sources([old, new], "area_reconciliation", village="WORLI", cts_no="733")
    assert result.selected is not None and result.selected.record_id == "new"

    same_date_z = Record(effective_date="2026-01-01", verification_date="2026-01-01", checksum="z", record_id="z")
    same_date_a = Record(effective_date="2026-01-01", verification_date="2026-01-01", checksum="a", record_id="a")
    result = recommend_authority_sources(
        [same_date_z, same_date_a], "area_reconciliation", village="WORLI", cts_no="733"
    )
    assert result.selected is not None and result.selected.record_id == "a"


def test_resolver_does_not_apply_recommendations_and_only_applies_active_sources():
    property_card = Record(source_type="property_card", area_sqm=1400.0, checksum="pc")
    store = Store([property_card], active=[])
    base = parcel()
    resolved = AuthorityResolver(store).resolve(base)

    assert resolved.area_sqm == base.area_sqm
    assert resolved.attrs["_DP_AUTHORITY_ACTIVE"] is False
    assert resolved.attrs["_DP_AUTHORITY_RESOLUTION"]["area"] is None


def test_resolver_applies_active_area_and_geometry_but_preserves_baseline():
    survey = Record(
        source_type="total_station",
        area_sqm=150.0,
        geometry=[
            [
                [8_106_500.0, 2_151_700.0],
                [8_106_520.0, 2_151_700.0],
                [8_106_520.0, 2_151_710.0],
                [8_106_500.0, 2_151_710.0],
                [8_106_500.0, 2_151_700.0],
            ]
        ],
        checksum="survey",
    )
    property_card = Record(source_type="property_card", area_sqm=150.0, checksum="pc")
    resolved = AuthorityResolver(Store([property_card, survey], active=[property_card, survey])).resolve(parcel())
    resolution = resolved.attrs["_DP_AUTHORITY_RESOLUTION"]

    assert resolved.area_sqm == 150.0
    assert resolved.area_source == "Property Card"
    assert resolved.rings != parcel().rings
    assert resolution["baseline"]["area_sqm"] == parcel().area_sqm
    assert resolution["working"]["geometry_replaced"] is True
    assert resolution["working"]["calculated_boundary_area_sqm"] is not None
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
