"""Pure parsing and compatibility aliases for the main lookup CLI."""
from __future__ import annotations

import os
from typing import Any, Optional, Sequence

from dp_lookup.core.constants import APPLICATION_VERSION
from dp_lookup.planning_evidence.models import EvidenceMode

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_INCOMPLETE = 2
EXIT_USAGE = EXIT_ERROR
EXIT_OK = EXIT_SUCCESS
EXIT_FAILURE = EXIT_ERROR
EXIT_INCOMPLETE_RESULT = EXIT_INCOMPLETE
DEFAULT_DATABASE_PATH = "data/mcgm-layer13.sqlite"

USAGE = """Usage: dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER> [OUTPUT_DIR] [options]
       dp-lookup-pro lookup <VILLAGE_NAME> <CTS_NUMBER> [OUTPUT_DIR] [options]
       dp-lookup-pro db <COMMAND> [--database PATH] [--json]
       dp-lookup-pro plots <COMMAND> [--database PATH] [--json]
       dp-lookup-pro evidence <COMMAND> [--database PATH] [--json]
       dp-lookup-pro experimental assembly analyze VILLAGE:CTS VILLAGE:CTS [options]

Options:
  --json            print the full JSON response instead of a summary
  --no-cache        force a fresh lookup, ignoring any cached report
  --evidence MODE   basic, shadow, standard, or full (default: basic)
  --source MODE     auto, live, or local (default: auto: local first, live fallback)
  --database PATH   override auto's DB path; required with strict local mode
  --list-villages   print all 128 valid village names and exit

Examples:
  dp-lookup-pro WORLI 947
  dp-lookup-pro "MALABAR HILL" "16/738"
  dp-lookup-pro BANDRA-A 409 ./client-reports --no-cache
  dp-lookup-pro db health
  dp-lookup-pro db check-upstream
  dp-lookup-pro experimental assembly analyze WORLI:733 WORLI:734

Village must be one of the 128 exact MCGM revenue village names
(e.g. BANDRA-A, not BANDRA). See START-HERE.md for the full list."""

HELP = USAGE + "\n\nOptions:\n  -h, --help        show this help message and exit\n  --version         show the installed version and exit"

DATABASE_HELP = """Database administration:
  dp-lookup-pro db health [--database PATH] [--json]
  dp-lookup-pro db check-upstream [--database PATH] [--json]
  dp-lookup-pro db parcels <build|status|verify|diff|activate|rollback> [--database PATH] [--json]
  dp-lookup-pro db planning <build|status|verify|activate|rollback> [--database PATH] [--json]

Convenient action-first forms:
  dp-lookup-pro db refresh parcels
  dp-lookup-pro db refresh planning
  dp-lookup-pro db planning build --layers 81,85,92,192,194,2400
  dp-lookup-pro db status parcels
  dp-lookup-pro db status planning

The existing `database build`, `database build-planning`, and related flat
commands remain supported for scripts. DP_LOOKUP_DATABASE sets the default
database; otherwise data/mcgm-layer13.sqlite is used by the new aliases."""

_PARCEL_DATABASE_ACTIONS = {"build": "build", "refresh": "build", "status": "status", "verify": "verify", "diff": "diff", "activate": "activate", "rollback": "rollback"}
_PLANNING_DATABASE_ACTIONS = {"build": "build-planning", "refresh": "build-planning", "status": "status-planning", "verify": "verify-planning", "activate": "activate-planning", "rollback": "rollback-planning"}


def default_database_path() -> str:
    """Resolve the snapshot location, honoring the existing environment override."""
    return os.getenv("DP_LOOKUP_DATABASE", "").strip() or DEFAULT_DATABASE_PATH


def has_database_option(args: Sequence[str]) -> bool:
    return any(token == "--database" or token.startswith("--database=") for token in args)


def normalize_admin_args(raw_args: Sequence[str]) -> list[str]:
    """Map clearer aliases onto the stable legacy command grammars."""
    if not raw_args:
        return []
    args = list(raw_args)
    used_new_alias = args[0] in {"db", "plots", "evidence"}
    args[0] = {"db": "database", "plots": "intelligence", "evidence": "sources"}.get(args[0], args[0])
    if args[0] == "database" and len(args) >= 3:
        category, action = args[1].casefold(), args[2].casefold()
        if category in {"parcel", "parcels"} and action in _PARCEL_DATABASE_ACTIONS:
            args = ["database", _PARCEL_DATABASE_ACTIONS[action], *args[3:]]
        elif category == "planning" and action in _PLANNING_DATABASE_ACTIONS:
            args = ["database", _PLANNING_DATABASE_ACTIONS[action], *args[3:]]
        elif category in _PARCEL_DATABASE_ACTIONS and action in {"parcel", "parcels"}:
            args = ["database", _PARCEL_DATABASE_ACTIONS[category], *args[3:]]
        elif category in _PLANNING_DATABASE_ACTIONS and action == "planning":
            args = ["database", _PLANNING_DATABASE_ACTIONS[category], *args[3:]]
    if used_new_alias and not has_database_option(args):
        args.extend(["--database", default_database_path()])
    return args


def parse_cli_args(raw_args: Sequence[str]) -> dict[str, Any]:
    """Parse the small lookup grammar without argparse process side effects."""
    positionals: list[str] = []
    as_json = list_villages = show_help = show_version = False
    use_cache = True
    evidence_mode = EvidenceMode.BASIC
    source_mode = "auto"
    database_path: Optional[str] = None
    index = 0
    tokens = list(raw_args)
    while index < len(tokens):
        token = tokens[index]
        if token in ("--json", "--raw"):
            as_json = True
        elif token in ("--no-cache", "--fresh"):
            use_cache = False
        elif token in ("--list-villages", "--villages"):
            list_villages = True
        elif token in ("--help", "-h"):
            show_help = True
        elif token == "--version":
            show_version = True
        elif token == "--evidence":
            index += 1
            if index >= len(tokens):
                raise ValueError("--evidence requires a mode")
            evidence_mode = EvidenceMode.parse(tokens[index])
        elif token.startswith("--evidence="):
            evidence_mode = EvidenceMode.parse(token.split("=", 1)[1])
        elif token == "--source":
            index += 1
            if index >= len(tokens):
                raise ValueError("--source requires live, local, or auto")
            source_mode = tokens[index].lower()
        elif token.startswith("--source="):
            source_mode = token.split("=", 1)[1].lower()
        elif token == "--database":
            index += 1
            if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                raise ValueError("--database requires a path")
            database_path = tokens[index]
        elif token.startswith("--database="):
            database_path = token.split("=", 1)[1]
            if not database_path:
                raise ValueError("--database requires a path")
        elif token.startswith("-"):
            raise ValueError(f"unknown option: {token}")
        else:
            positionals.append(token)
        index += 1
    if list_villages and positionals:
        raise ValueError("--villages does not accept positional arguments")
    if show_version and positionals:
        raise ValueError("--version does not accept positional arguments")
    if source_mode not in {"live", "local", "auto"}:
        raise ValueError("--source must be one of: live, local, auto")
    if source_mode == "local" and not database_path:
        raise ValueError("--database PATH is required for local source mode")
    if source_mode == "auto" and not database_path:
        database_path = default_database_path()
    return {
        "positionals": positionals,
        "as_json": as_json,
        "use_cache": use_cache,
        "list_villages": list_villages,
        "show_help": show_help,
        "show_version": show_version,
        "evidence_mode": evidence_mode,
        "source_mode": source_mode,
        "database_path": database_path,
    }


VERSION = APPLICATION_VERSION
