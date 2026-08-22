"""Stable command-line entry point for DP Lookup Pro.

This module intentionally remains a compatibility facade.  Parsing,
dependency composition, command execution, and terminal presentation live in
focused modules so embedded callers can reuse each boundary independently.
"""
from __future__ import annotations

import sys
from importlib import metadata as importlib_metadata
from typing import Any, Optional, Sequence

from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES
from dp_lookup.application.ingestion import fetch_parcel_feature
from dp_lookup.application.lookup_service import lookup_plot_pro
from dp_lookup.authority import AuthorityStore, AuthorityStoreError
from dp_lookup.cli_bootstrap import LookupRuntime, compose_lookup_runtime, local_snapshot_selection
from dp_lookup.cli_command import execute_lookup
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


def _print_villages() -> None:
    """Compatibility wrapper for the village catalogue printer."""
    print_villages(MCGM_VILLAGES)


def _local_snapshot_selection(source_mode: str, database_path: str) -> tuple[str, Optional[int]]:
    """Compatibility wrapper used by cache-contract tests and callers."""
    return local_snapshot_selection(source_mode, database_path)


def _local_cache_namespace(source_mode: str, database_path: str) -> str:
    """Return the cache namespace for a local database."""
    return _local_snapshot_selection(source_mode, database_path)[0]


def _default_database_path() -> str:
    """Compatibility alias for the environment-configured DB path."""
    from dp_lookup.cli_parser import default_database_path

    return default_database_path()


def _has_database_option(args: Sequence[str]) -> bool:
    return any(token == "--database" or token.startswith("--database=") for token in args)


def _compose_lookup_runtime(
    source_mode: str,
    database_path: Optional[str],
    evidence_mode: EvidenceMode,
    *,
    snapshot_selector: Any,
) -> LookupRuntime:
    """Compose through facade globals so legacy monkeypatches still work."""
    return compose_lookup_runtime(
        source_mode,
        database_path,
        evidence_mode,
        snapshot_selector=snapshot_selector,
        base_dependencies=DEFAULT_DEPENDENCIES,
        parcel_fallback=fetch_parcel_feature,
    )


def _normalize_admin_args(raw_args: list[str]) -> list[str]:
    return normalize_admin_args(raw_args)


def _parse_cli_args(raw_args: list[str]) -> dict[str, Any]:
    return parse_cli_args(raw_args)


def main(argv: Optional[list[str]] = None) -> int:
    """Console entry point.  Returns a process-compatible exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    # ``lookup`` is the explicit spelling for scripts and future subcommands;
    # the historical positional form remains untouched.
    if raw_args and raw_args[0] == "lookup":
        raw_args = raw_args[1:]
    if raw_args and raw_args[0] in {"db", "database"} and (
        len(raw_args) == 1 or any(token in {"--help", "-h"} for token in raw_args[1:])
    ):
        print(DATABASE_HELP)
        return EXIT_SUCCESS

    raw_args = _normalize_admin_args(raw_args)
    if raw_args and raw_args[0] == "experimental":
        from dp_lookup.experimental.assemblies_cli import main as experimental_main

        return int(experimental_main(raw_args))
    if raw_args and raw_args[0] == "intelligence":
        from dp_lookup.intelligence_cli import main as intelligence_main

        return int(intelligence_main(raw_args))
    if raw_args and raw_args[0] == "sources":
        from dp_lookup.authority_cli import main as authority_main

        return int(authority_main(raw_args))
    if raw_args and raw_args[0] == "database":
        from dp_lookup.planning_snapshot_cli import COMMANDS as planning_commands

        if len(raw_args) > 1 and raw_args[1] in planning_commands:
            from dp_lookup.application.planning_database_services import LocalPlanningDatabaseServices
            from dp_lookup.planning_snapshot_cli import main as planning_database_main

            return int(planning_database_main(raw_args[1:], services=LocalPlanningDatabaseServices()))
        from dp_lookup.application.database_services import LocalDatabaseServices
        from dp_lookup.database_cli import main as database_main

        return int(database_main(raw_args, services=LocalDatabaseServices()))

    try:
        parsed = _parse_cli_args(raw_args)
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
        _print_villages()
        return EXIT_SUCCESS
    return execute_lookup(
        parsed,
        lookup=lookup_plot_pro,
        runtime_factory=_compose_lookup_runtime,
        snapshot_selector=_local_snapshot_selection,
        usage=USAGE,
    )


if __name__ == "__main__":
    sys.exit(main())
