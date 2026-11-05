"""Deterministic contracts for parcel-area quality and reliability."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

import pytest

from dp_lookup.core import area_assessment as area_assessment_module
from dp_lookup.core.area_assessment import assess_plot_area, calculated_boundary_area_sqm
from dp_lookup.core.models import ReliabilityStatus


def _square(
    *,
    x: float = 8_106_500.0,
    y: float = 2_151_700.0,
    size: float = 10.0,
) -> list[list[list[float]]]:
    return [
        [
            [x, y],
            [x + size, y],
            [x + size, y + size],
            [x, y + size],
            [x, y],
        ]
    ]


def _attrs(recorded_area: Optional[float] = None, **extra: object) -> dict[str, object]:
    attrs: dict[str, object] = {
        "OBJECTID": 733,
        "VILLAGE": "WORLI",
        "CTS_CS_NO": "733",
    }
    if recorded_area is not None:
        attrs["AREA_APP_SQ_MTRS"] = recorded_area
    attrs.update(extra)
    return attrs


def _flag_codes(assessment: object) -> list[str]:
    return [flag.code for flag in assessment.flags]


@pytest.mark.parametrize(
    "calculated,expected_thresholds",
    [
        (102.0, ()),
        (102.0001, (2,)),
        (105.0, (2,)),
        (105.0001, (2, 5)),
        (110.0, (2, 5)),
        (110.0001, (2, 5, 10)),
        (98.0, ()),
        (97.9999, (2,)),
        (95.0, (2,)),
        (94.9999, (2, 5)),
        (90.0, (2, 5)),
        (89.9999, (2, 5, 10)),
    ],
)
def test_area_difference_thresholds_are_strict_and_symmetric(
    monkeypatch: pytest.MonkeyPatch,
    calculated: float,
    expected_thresholds: tuple[int, ...],
) -> None:
    rings = _square()
    monkeypatch.setattr(
        area_assessment_module,
        "calculated_boundary_area_sqm",
        lambda _rings: calculated,
    )

    assessment = assess_plot_area(_attrs(100.0), rings)

    assert assessment.difference_percent == round(abs(calculated - 100.0), 3)
    assert assessment.thresholds_exceeded == expected_thresholds
    difference_flags = [code for code in _flag_codes(assessment) if code.startswith("area_difference_over_")]
    assert difference_flags == (
        [f"area_difference_over_{expected_thresholds[-1]}_percent"] if expected_thresholds else []
    )


def test_missing_recorded_area_uses_boundary_without_inventing_a_difference() -> None:
    rings = _square()
    calculated = calculated_boundary_area_sqm(rings)
    assert calculated is not None

    assessment = assess_plot_area(_attrs(), rings)

    assert assessment.recorded_area_sqm is None
    assert assessment.calculated_boundary_area_sqm == round(calculated, 2)
    assert assessment.selected_area_sqm == round(calculated, 2)
    assert assessment.selected_area_basis == "calculated_boundary_area"
    assert assessment.difference_sqm is None
    assert assessment.difference_percent is None
    assert assessment.thresholds_exceeded == ()
    assert "recorded_area_unavailable" in _flag_codes(assessment)
    assert not any(code.startswith("area_difference_over_") for code in _flag_codes(assessment))


def test_repairable_invalid_geometry_is_flagged_and_raw_rings_are_unchanged() -> None:
    x = 8_106_500.0
    y = 2_151_700.0
    rings = [
        [
            [x, y],
            [x + 10.0, y + 10.0],
            [x, y + 10.0],
            [x + 10.0, y],
            [x, y],
        ]
    ]
    original = deepcopy(rings)

    assessment = assess_plot_area(_attrs(50.0), rings)

    assert rings == original
    assert assessment.calculated_boundary_area_sqm is not None
    assert "source_geometry_invalid" in _flag_codes(assessment)
    assert "topology repaired for analysis only" in assessment.calculation_method
    assert assessment.reliability_status is ReliabilityStatus.QUALIFIED_WITH_WARNINGS


def test_disconnected_multipart_boundary_is_flagged_as_fragmented() -> None:
    rings = _square()
    rings.extend(_square(x=8_106_520.0, size=5.0))
    calculated = calculated_boundary_area_sqm(rings)
    assert calculated is not None

    assessment = assess_plot_area(_attrs(calculated), rings)

    assert "fragmented_boundary" in _flag_codes(assessment)
    assert "source_geometry_invalid" not in _flag_codes(assessment)
    assert assessment.calculated_boundary_area_sqm == round(calculated, 2)
    assert assessment.reliability_status is ReliabilityStatus.QUALIFIED_WITH_WARNINGS


def test_overlapping_source_parts_keep_coordinates_and_report_repaired_ground_area() -> None:
    rings = _square()
    rings.extend(_square(x=8_106_505.0))
    original = deepcopy(rings)

    assessment = assess_plot_area(_attrs(150.0), rings)

    assert rings == original
    assert assessment.calculated_boundary_area_sqm is not None
    assert "source_geometry_invalid" in _flag_codes(assessment)
    assert "boundary_area_unavailable" not in _flag_codes(assessment)
    assert "topology repaired for analysis only" in assessment.calculation_method


def test_conflicting_recorded_areas_are_not_silently_selected() -> None:
    assessment = assess_plot_area(
        _attrs(100.0, _DP_AREA_CONFLICT_VALUES=[100.0, 200.0]),
        _square(),
    )

    assert assessment.recorded_area_sqm is None
    assert assessment.selected_area_basis == "calculated_boundary_area"
    assert "conflicting_recorded_areas" in _flag_codes(assessment)
    assert "recorded_area_unavailable" in _flag_codes(assessment)
    conflict = next(flag for flag in assessment.flags if flag.code == "conflicting_recorded_areas")
    assert conflict.severity == "critical"


def test_duplicate_geometry_marker_is_a_critical_quality_failure() -> None:
    calculated = calculated_boundary_area_sqm(_square())
    assert calculated is not None

    assessment = assess_plot_area(
        _attrs(calculated, _DP_DUPLICATE_GEOMETRY_COUNT=2),
        _square(),
    )

    duplicate = next(flag for flag in assessment.flags if flag.code == "duplicate_geometry")
    assert duplicate.severity == "critical"
    assert assessment.reliability_status is ReliabilityStatus.QUALIFIED_WITH_WARNINGS


@pytest.mark.parametrize(
    "attrs,requested_village,requested_cts",
    [
        (_attrs(89.0, _DP_IDENTITY_AMBIGUOUS=True), "WORLI", "733"),
        (_attrs(89.0), "WORLI", "734"),
    ],
)
def test_ambiguous_or_mismatched_identity_is_critical(
    attrs: dict[str, object],
    requested_village: str,
    requested_cts: str,
) -> None:
    assessment = assess_plot_area(
        attrs,
        _square(),
        requested_village=requested_village,
        requested_cts_no=requested_cts,
    )

    ambiguous = [flag for flag in assessment.flags if flag.code == "ambiguous_identity"]
    assert len(ambiguous) == 1
    assert ambiguous[0].severity == "critical"
    assert assessment.reliability_status is ReliabilityStatus.QUALIFIED_WITH_WARNINGS


def test_clean_local_source_is_verified_while_clean_live_source_is_screening() -> None:
    rings = _square()
    calculated = calculated_boundary_area_sqm(rings)
    assert calculated is not None
    live = assess_plot_area(_attrs(calculated), rings)
    local = assess_plot_area(
        _attrs(
            calculated,
            _DP_PARCEL_SOURCE="local_snapshot",
            _DP_SNAPSHOT_ID=12,
            _DP_SNAPSHOT_FINALIZED_AT_ISO="2026-08-22T00:00:00+00:00",
        ),
        rings,
    )

    assert live.flags == ()
    assert live.reliability_status is ReliabilityStatus.SCREENING
    assert live.reliability_label == "Screening"
    assert local.flags == ()
    assert local.reliability_status is ReliabilityStatus.VERIFIED_SOURCE
    assert local.reliability_label == "Verified source"
    assert local.source_snapshot_id == 12
    assert local.source_snapshot_date == "2026-08-22T00:00:00+00:00"


@pytest.mark.parametrize("recorded", [True, 0, -1, float("nan"), float("inf"), "bad"])
def test_non_positive_or_non_finite_recorded_values_are_unavailable(recorded: object) -> None:
    assessment = assess_plot_area(_attrs(AREA_APP_SQ_MTRS=recorded), _square())

    assert assessment.recorded_area_sqm is None
    assert assessment.selected_area_basis == "calculated_boundary_area"
    assert "recorded_area_unavailable" in _flag_codes(assessment)


def test_malformed_boundary_is_qualified_without_losing_a_valid_recorded_area() -> None:
    malformed = [[[]], [["bad", object()]]]  # type: ignore[list-item]

    assessment = assess_plot_area(_attrs(100.0), malformed)

    assert assessment.selected_area_sqm == 100.0
    assert assessment.calculated_boundary_area_sqm is None
    assert {"source_geometry_invalid", "boundary_area_unavailable"}.issubset(_flag_codes(assessment))


def test_partial_live_stale_and_small_geometry_flags_are_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(area_assessment_module, "calculated_boundary_area_sqm", lambda _rings: 0.5)
    assessment = assess_plot_area(
        _attrs(
            1.0,
            _DP_RECORDED_AREA_MISSING_PARTS=True,
            _DP_UNMERGED_SOURCE_RECORDS=True,
            _DP_SNAPSHOT_STALE=True,
        ),
        _square(),
    )

    codes = _flag_codes(assessment)
    assert "partial_recorded_area_evidence" in codes
    assert "multiple_live_source_records" in codes
    assert "stale_source_snapshot" in codes
    assert "unusually_small_geometry" in codes


def test_incomplete_identity_and_malformed_provenance_are_safe() -> None:
    rings = _square()
    calculated = calculated_boundary_area_sqm(rings)
    assert calculated is not None
    assessment = assess_plot_area(
        {
            "AREA_APP_SQ_MTRS": calculated,
            "SOURCE_OBJECTIDS": ["7", "bad", None, 7],
            "FEATURE_PART_COUNT": "bad",
            "_DP_SNAPSHOT_ID": "bad",
        },
        rings,
    )

    assert "incomplete_identity" in _flag_codes(assessment)
    assert assessment.source_objectids == (7,)
    assert assessment.feature_part_count == 1
    assert assessment.source_snapshot_id is None


def test_assessment_public_dict_uses_intuitive_labels_and_structured_flags() -> None:
    assessment = assess_plot_area(_attrs(), _square()).to_dict()

    assert assessment["recorded_area_source"] == "MCGM cadastral parcel record"
    assert assessment["geometry_source"] == "MCGM cadastral parcel boundary"
    assert assessment["reliability_label"] == "Qualified with warnings"
    assert assessment["quality_flags"][0]["code"] == "recorded_area_unavailable"
