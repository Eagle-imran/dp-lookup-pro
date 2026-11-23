"""Command-line entry point for DP Lookup Pro.

Parsing, dependency composition, command execution and terminal presentation
live in the ``cli_*`` modules; this one wires them together.
"""

from __future__ import annotations

import sys
from importlib import metadata as importlib_metadata
from typing import Any

from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES
from dp_lookup.application.ingestion import fetch_parcel_feature
from dp_lookup.application.lookup_service import lookup_plot_pro
from dp_lookup.authority import AuthorityStore, AuthorityStoreError
from dp_lookup.cli_bootstrap import LookupRuntime, compose_lookup_runtime, local_snapshot_selection
from dp_lookup.cli_command import execute_lookup
from dp_lookup.cli_dispatch import dispatch_admin_command
from dp_lookup.cli_parser import (
    DATABASE_HELP,
    DEFAULT_DATABASE_PATH,
    EXIT_ERROR,
    EXIT_FAILURE,
    EXIT_INCOMPLETE,
    EXIT_INCOMPLETE_RESULT,
    EXIT_OK,
    EXIT_SUCCESS,
    EXIT_USAGE,
    HELP,
    USAGE,
    normalize_admin_args,
    parse_cli_args,
)
from dp_lookup.cli_presentation import format_result_human, print_villages
from dp_lookup.core.constants import APPLICATION_VERSION, MCGM_VILLAGES
from dp_lookup.core.villages import suggest_villages as _suggest_villages
from dp_lookup.planning_evidence.models import EvidenceMode
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore, SpatialStoreError

__all__ = [
    "DATABASE_HELP",
    "DEFAULT_DATABASE_PATH",
    "DEFAULT_DEPENDENCIES",
    "EXIT_ERROR",
    "EXIT_FAILURE",
    "EXIT_INCOMPLETE",
    "EXIT_INCOMPLETE_RESULT",
    "EXIT_OK",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "HELP",
    "USAGE",
    "VERSION",
    "AuthorityStore",
    "AuthorityStoreError",
    "EvidenceMode",
    "PlanningSnapshotStore",
    "SnapshotStore",
    "SpatialStoreError",
    "fetch_parcel_feature",
    "format_result_human",
    "lookup_plot_pro",
    "main",
    "suggest_villages",
]

suggest_villages = _suggest_villages

try:
    VERSION = importlib_metadata.version("dp-lookup-pro")
except importlib_metadata.PackageNotFoundError:
    VERSION = APPLICATION_VERSION


def _compose_lookup_runtime(
    source_mode: str,
    database_path: str | None,
    evidence_mode: EvidenceMode,
    *,
    snapshot_selector: Any,
) -> LookupRuntime:
    return compose_lookup_runtime(
        source_mode,
        database_path,
        evidence_mode,
        snapshot_selector=snapshot_selector,
        base_dependencies=DEFAULT_DEPENDENCIES,
        parcel_fallback=fetch_parcel_feature,
    )


def main(argv: list[str] | None = None) -> int:
    """Console entry point.  Returns a process-compatible exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "lookup":
        raw_args = raw_args[1:]
    if (
        raw_args
        and raw_args[0] in {"db", "database"}
        and (len(raw_args) == 1 or any(token in {"--help", "-h"} for token in raw_args[1:]))
    ):
        print(DATABASE_HELP)
        return EXIT_SUCCESS

    raw_args = normalize_admin_args(raw_args)
    dispatched = dispatch_admin_command(raw_args)
    if dispatched is not None:
        return dispatched

    try:
        parsed = parse_cli_args(raw_args)
    except ValueError as exc:
        print(f"  Error: {exc}")
        print(USAGE)
        return EXIT_USAGE
    if parsed["show_help"]:
        print(HELP)
        return EXIT_SUCCESS
    if parsed["show_version"]:
        print(f"dp-lookup-pro {VERSION}")
        return EXIT_SUCCESS
    if parsed["list_villages"]:
        print_villages(MCGM_VILLAGES)
        return EXIT_SUCCESS
    return execute_lookup(
        parsed,
        lookup=lookup_plot_pro,
        runtime_factory=_compose_lookup_runtime,
        snapshot_selector=local_snapshot_selection,
        usage=USAGE,
    )


if __name__ == "__main__":
    sys.exit(main())
