"""Contracts for the audited, dependency-free planning layer registry."""

from dp_lookup.planning_evidence import (
    CANONICAL_LAYER_IDS,
    CURRENT_CORE_LAYER_IDS,
    LAYER_SPECS,
    STANDARD_LAYER_IDS,
    EvidenceContext,
    EvidenceMode,
    QueryPolicy,
    canonical_layer_id,
    specs_for_mode,
)


def test_registry_ids_and_explicit_field_contracts_are_unique():
    assert len({spec.layer_id for spec in LAYER_SPECS}) == len(LAYER_SPECS)
    assert all("*" not in spec.out_fields for spec in LAYER_SPECS)
    assert all(spec.object_id_field in spec.out_fields for spec in LAYER_SPECS)


def test_audited_duplicate_sources_resolve_to_one_canonical_query():
    assert CANONICAL_LAYER_IDS == {57: 61, 2251: 2250, 2252: 2250}
    assert canonical_layer_id(57) == 61
    assert canonical_layer_id(2252) == 2250


def test_basic_mode_never_requeries_layer_13_and_standard_is_curated():
    assert specs_for_mode(EvidenceMode.BASIC) == ()
    standard = specs_for_mode(EvidenceMode.STANDARD)
    assert tuple(spec.layer_id for spec in standard) == STANDARD_LAYER_IDS
    assert not set(CURRENT_CORE_LAYER_IDS).intersection(spec.layer_id for spec in standard)


def test_full_mode_adds_conditional_families_only_when_applicable():
    without_context = specs_for_mode(EvidenceMode.FULL)
    with_context = specs_for_mode(
        EvidenceMode.FULL,
        context=EvidenceContext(coastal=True, tps=True, spa=True, gorai=True),
    )
    assert all(spec.query_policy is QueryPolicy.ALWAYS for spec in without_context)
    assert {QueryPolicy.TPS, QueryPolicy.SPA, QueryPolicy.GORAI}.issubset(
        {spec.query_policy for spec in with_context}
    )
    assert len(with_context) > len(without_context)
