"""Run diagnostics remain useful without becoming a logging dependency."""

import json
import time

from dp_lookup.application.telemetry import RunDiagnostics


def test_run_diagnostics_have_unique_ids_and_stage_timings():
    first = RunDiagnostics()
    second = RunDiagnostics()
    first.mark("ingestion")

    snapshot = first.snapshot()
    assert snapshot["run_id"] != second.run_id
    assert snapshot["elapsed_ms"] >= 0
    assert snapshot["stages_ms"]["ingestion"] >= 0


def test_nested_spans_do_not_change_sequential_stage_boundaries():
    diagnostics = RunDiagnostics()
    diagnostics.mark("before")
    with diagnostics.span("adapter"):
        time.sleep(0.001)
    diagnostics.mark("after")

    snapshot = diagnostics.snapshot()
    assert snapshot["spans_ms"]["adapter"] >= 1
    assert set(snapshot["stages_ms"]) == {"before", "after"}


def test_json_logging_is_explicitly_opt_in(monkeypatch, capsys):
    monkeypatch.setenv("DP_LOOKUP_LOG_JSON", "true")
    diagnostics = RunDiagnostics()
    diagnostics.mark("planning", outcome="confirmed")

    event = json.loads(capsys.readouterr().err)
    assert event["event"] == "dp_lookup.stage_completed"
    assert event["run_id"] == diagnostics.run_id
    assert event["stage"] == "planning"
    assert event["outcome"] == "confirmed"
