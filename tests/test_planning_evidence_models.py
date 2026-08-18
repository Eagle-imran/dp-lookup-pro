"""Serialization and immutability contracts for optional planning evidence."""

import pytest

from dp_lookup.planning_evidence import (
    EvidenceClass,
    EvidenceFinding,
    EvidenceMode,
    LayerQueryOutcome,
    PlanningEvidenceReport,
    QueryState,
)


def test_finding_copies_source_attributes_and_serializes_without_mutable_leaks():
    attributes = {"DECISION": "Refused", "nested": {"value": 1}}
    finding = EvidenceFinding(
        83,
        "Sanctioned_EP",
        10,
        EvidenceClass.STATUTORY,
        "EP decision evidence",
        50.0,
        25.0,
        "https://example.invalid/83",
        attributes,
    )
    attributes["DECISION"] = "Changed"
    serialized = finding.to_dict()
    serialized["attributes"]["nested"]["value"] = 9

    assert finding.attributes["DECISION"] == "Refused"
    assert finding.attributes["nested"]["value"] == 1
    with pytest.raises(TypeError):
        finding.attributes["new"] = "value"


def test_report_keeps_layer_failure_distinct_from_not_present():
    failed = LayerQueryOutcome(92, "Corrections", QueryState.FAILED, 10.0, warnings=("timeout",))
    report = PlanningEvidenceReport(
        EvidenceMode.SHADOW,
        "2026-08-18T12:00:00+00:00",
        False,
        outcomes=(failed,),
    ).to_dict()

    assert report["complete"] is False
    assert report["outcomes"][0]["state"] == "failed"
    assert report["outcomes"][0]["state"] != "not_present"
