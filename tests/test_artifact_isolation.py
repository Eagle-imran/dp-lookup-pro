"""Optional output failures must stay visible and isolated."""

import asyncio

from dp_lookup.application.artifacts import run_artifact, run_artifact_in_thread


def _fail():
    raise RuntimeError("writer exploded")


def test_synchronous_artifact_failure_becomes_warning():
    warnings = []
    assert run_artifact("DXF", warnings, _fail) is False
    assert warnings == ["DXF generation failed: RuntimeError: writer exploded"]


def test_threaded_artifact_failure_becomes_warning():
    warnings = []
    assert asyncio.run(run_artifact_in_thread("PDF", warnings, _fail)) is False
    assert warnings == ["PDF generation failed: RuntimeError: writer exploded"]
