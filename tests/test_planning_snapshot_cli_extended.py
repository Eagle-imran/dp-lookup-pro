"""Failure and option coverage for planning snapshot administration."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from dp_lookup.planning_snapshot_cli import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE, main, parse_planning_snapshot_args


@pytest.mark.parametrize(
    "argv,message",
    [
        ([], "expected one of"),
        (["unknown"], "expected one of"),
        (["status-planning"], "--database PATH is required"),
        (["status-planning", "--database"], "--database requires"),
        (["status-planning", "--database="], "--database requires"),
        (["build-planning", "--database", "x", "--manifest"], "--manifest requires"),
        (["build-planning", "--database", "x", "--checkpoint="], "--checkpoint requires"),
        (["build-planning", "--database", "x", "--batch-size", "bad"], "requires an integer"),
        (["build-planning", "--database", "x", "--max-attempts=bad"], "requires an integer"),
        (["build-planning", "--database", "x", "--mystery"], "unknown planning snapshot option"),
    ],
)
def test_invalid_planning_admin_arguments_are_stable(argv, message):
    with pytest.raises(ValueError, match=message):
        parse_planning_snapshot_args(argv)


def test_equals_options_and_rollback_dispatch():
    parsed = parse_planning_snapshot_args(
        [
            "rollback-planning",
            "--database=db.sqlite",
            "--manifest=manifest.json",
            "--checkpoint=checkpoint.json",
            "--batch-size=25",
            "--max-attempts=4",
        ]
    )
    assert parsed["database"] == Path("db.sqlite")
    assert parsed["manifest"] == Path("manifest.json")
    assert parsed["resume"] == Path("checkpoint.json")
    assert parsed["config"].batch_size == 25
    assert parsed["config"].max_attempts == 4

    class Services:
        def rollback_planning(self, database, options):
            return {"database": database, "attempts": options["config"].max_attempts}

    output = io.StringIO()
    assert main(["rollback-planning", "--database", "db.sqlite"], services=Services(), out=output) == EXIT_SUCCESS
    assert "rollback-planning: OK" in output.getvalue()


def test_frontend_reports_usage_and_service_errors_in_both_formats():
    output = io.StringIO()
    assert main([], out=output) == EXIT_USAGE
    assert "expected one of" in output.getvalue()

    output = io.StringIO()
    assert main(["status-planning", "--database", "x", "--json"], out=output) == EXIT_ERROR
    assert '"error"' in output.getvalue()

    output = io.StringIO()
    assert main(["status-planning", "--database", "x"], out=output) == EXIT_ERROR
    assert "failed" in output.getvalue()
