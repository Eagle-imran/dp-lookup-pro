"""Network-free contracts for the experimental deterministic assembly core."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

import pytest

from dp_lookup.core.area_assessment import calculated_boundary_area_sqm
from dp_lookup.experimental.assemblies import (
    AssemblySuitabilityStatus,
    ParcelAssemblyInput,
    ParcelRelationKind,
    analyze_plot_assembly,
)


def _rectangle(
    *,
    x: float = 8_106_500.0,
    y: float = 2_151_700.0,
    width: float = 10.0,
    height: float = 10.0,
) -> list[list[list[float]]]:
    """A Web Mercator test rectangle located in the Mumbai UTM 43N extent."""
    return [
        [
            [x, y],
            [x + width, y],
            [x + width, y + height],
            [x, y + height],
            [x, y],
        ]
    ]


def _parcel(
    cts: str,
    objectids: list[int],
    rings: list[list[list[float]]],
    *,
    recorded: Optional[float] = 100.0,
) -> ParcelAssemblyInput:
    return ParcelAssemblyInput(
        village="WORLI",
        cts_no=cts,
        objectids=objectids,
        raw_arcgis_rings=rings,
        recorded_area_sqm=recorded,
        ward="G/S",
    )


def _warning_codes(analysis: object) -> set[str]:
    return {warning.code for warning in analysis.warnings}


def test_adjacent_selection_uses_ground_metrics_and_counts_multipart_recorded_area_once() -> None:
    source_rings = _rectangle()
    original = deepcopy(source_rings)
    first = _parcel("100", [10, 11], source_rings, recorded=100.0)
    second = _parcel("101", [12], _rectangle(x=8_106_510.0), recorded=200.0)

    analysis = analyze_plot_assembly([first, second])

    expected_first = calculated_boundary_area_sqm(source_rings)
    expected_second = calculated_boundary_area_sqm(_rectangle(x=8_106_510.0))
    assert expected_first is not None
    assert expected_second is not None
    assert analysis.analysis_crs.endswith("EPSG:32643)")
    assert analysis.gross_recorded_area_sqm == 300.0
    assert analysis.known_recorded_area_sqm == 300.0
    assert analysis.recorded_area_complete is True
    assert analysis.calculated_input_boundary_area_sqm == round(expected_first + expected_second, 2)
    assert analysis.calculated_combined_boundary_area_sqm == analysis.calculated_input_boundary_area_sqm
    assert analysis.overlap_or_duplicate_area_sqm == 0.0
    assert analysis.removed_internal_boundary_length_m > 9.0
    assert analysis.removed_internal_boundary_length_m == analysis.pairwise_relations[0].shared_boundary_length_m
    assert analysis.external_perimeter_m < 2 * 4 * 10
    assert analysis.is_strictly_connected is True
    assert analysis.is_connected_within_tolerance is True
    assert analysis.suitability_status is AssemblySuitabilityStatus.GEOMETRY_SCREENING_READY
    assert analysis.pairwise_relations[0].relation is ParcelRelationKind.SHARED_BOUNDARY
    assert analysis.pairwise_relations[0].shared_boundary_length_m > 9.0
    assert "experimental_screening_only" in _warning_codes(analysis)
    assert "POLYGON" in (analysis.combined_boundary_wkt or "")

    source_rings[0][0][0] = -1.0
    assert original != source_rings
    assert first.raw_arcgis_rings[0][0] == (8_106_500.0, 2_151_700.0)


def test_small_gap_is_reported_as_tolerance_connection_not_exact_contiguity() -> None:
    first = _parcel("100", [10], _rectangle())
    second = _parcel("101", [11], _rectangle(x=8_106_510.1))

    analysis = analyze_plot_assembly([first, second], gap_tolerance_m=0.2)

    relation = analysis.pairwise_relations[0]
    assert relation.relation is ParcelRelationKind.TOLERANCE_GAP
    assert 0.0 < relation.gap_distance_m <= 0.2
    assert analysis.is_strictly_connected is False
    assert analysis.is_connected_within_tolerance is True
    assert analysis.removed_internal_boundary_length_m == 0.0
    assert analysis.suitability_status is AssemblySuitabilityStatus.REVIEW_TOLERANCE_GAPS
    assert "tolerance_gap_requires_review" in _warning_codes(analysis)


def test_overlap_is_not_silently_treated_as_a_clean_assembly() -> None:
    first = _parcel("100", [10], _rectangle())
    second = _parcel("101", [11], _rectangle(x=8_106_509.0))

    analysis = analyze_plot_assembly([first, second])

    relation = analysis.pairwise_relations[0]
    assert relation.relation is ParcelRelationKind.OVERLAP
    assert relation.overlap_area_sqm > 0.0
    assert analysis.overlap_or_duplicate_area_sqm > 0.0
    assert analysis.calculated_combined_boundary_area_sqm < analysis.calculated_input_boundary_area_sqm
    assert analysis.removed_internal_boundary_length_m == 0.0
    assert analysis.suitability_status is AssemblySuitabilityStatus.REVIEW_OVERLAPS
    assert "source_boundary_overlap" in _warning_codes(analysis)


def test_disconnected_and_point_only_selections_are_not_claimed_as_contiguous() -> None:
    disconnected = analyze_plot_assembly(
        [_parcel("100", [10], _rectangle()), _parcel("101", [11], _rectangle(x=8_106_540.0))]
    )
    point_only = analyze_plot_assembly(
        [_parcel("102", [12], _rectangle()), _parcel("103", [13], _rectangle(x=8_106_510.0, y=2_151_710.0))]
    )

    assert disconnected.pairwise_relations[0].relation is ParcelRelationKind.DISCONNECTED
    assert disconnected.is_connected_within_tolerance is False
    assert disconnected.suitability_status is AssemblySuitabilityStatus.NOT_CONTIGUOUS
    assert "non_contiguous_selection" in _warning_codes(disconnected)
    assert point_only.pairwise_relations[0].relation is ParcelRelationKind.POINT_CONTACT
    assert point_only.is_strictly_connected is False
    assert point_only.suitability_status is AssemblySuitabilityStatus.NOT_CONTIGUOUS


def test_missing_recorded_area_keeps_known_sum_but_does_not_invent_a_gross_total() -> None:
    analysis = analyze_plot_assembly(
        [_parcel("100", [10], _rectangle(), recorded=100.0), _parcel("101", [11], _rectangle(x=8_106_510.0), recorded=None)]
    )

    assert analysis.gross_recorded_area_sqm is None
    assert analysis.known_recorded_area_sqm == 100.0
    assert analysis.recorded_area_complete is False
    assert "recorded_area_incomplete" in _warning_codes(analysis)


def test_repairable_source_geometry_is_explicitly_flagged_without_mutating_source() -> None:
    x = 8_106_500.0
    y = 2_151_700.0
    bow_tie = [[[x, y], [x + 10.0, y + 10.0], [x, y + 10.0], [x + 10.0, y], [x, y]]]
    original = deepcopy(bow_tie)

    analysis = analyze_plot_assembly(
        [_parcel("100", [10], bow_tie), _parcel("101", [11], _rectangle(x=8_106_510.0))]
    )

    assert "source_geometry_repaired_for_analysis" in _warning_codes(analysis)
    assert bow_tie == original


def test_three_plot_chain_generates_all_pairwise_diagnostics_deterministically() -> None:
    parcels = [
        _parcel("100", [10], _rectangle()),
        _parcel("101", [11], _rectangle(x=8_106_510.0)),
        _parcel("102", [12], _rectangle(x=8_106_520.0)),
    ]

    first = analyze_plot_assembly(parcels)
    second = analyze_plot_assembly(parcels)

    assert first == second
    assert len(first.pairwise_relations) == 3
    assert [relation.relation for relation in first.pairwise_relations] == [
        ParcelRelationKind.SHARED_BOUNDARY,
        ParcelRelationKind.DISCONNECTED,
        ParcelRelationKind.SHARED_BOUNDARY,
    ]
    assert first.is_strictly_connected is True


@pytest.mark.parametrize(
    "parcels,error",
    [
        ([_parcel("100", [10], _rectangle())], "at least two"),
        (
            [_parcel("100", [10], _rectangle()), _parcel("100", [11], _rectangle(x=8_106_510.0))],
            "identity may appear only once",
        ),
        (
            [_parcel("100", [10], _rectangle()), _parcel("101", [10], _rectangle(x=8_106_510.0))],
            "ObjectIDs may not be selected more than once",
        ),
    ],
)
def test_invalid_assembly_selections_fail_closed(parcels: list[ParcelAssemblyInput], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        analyze_plot_assembly(parcels)


@pytest.mark.parametrize("tolerance", [-0.01, float("inf")])
def test_invalid_gap_tolerance_is_rejected(tolerance: float) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        analyze_plot_assembly(
            [_parcel("100", [10], _rectangle()), _parcel("101", [11], _rectangle(x=8_106_510.0))],
            gap_tolerance_m=tolerance,
        )


def test_input_validation_normalises_to_immutable_source_contract() -> None:
    parcel = _parcel(" 100 ", [12, 11, 12], _rectangle())

    assert parcel.village == "WORLI"
    assert parcel.cts_no == "100"
    assert parcel.identity_key == "WORLI / 100"
    assert parcel.objectids == (11, 12)
    assert isinstance(parcel.raw_arcgis_rings, tuple)
    assert isinstance(parcel.raw_arcgis_rings[0], tuple)
    assert isinstance(parcel.raw_arcgis_rings[0][0], tuple)
