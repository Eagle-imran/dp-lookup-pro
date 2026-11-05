"""Dependency-injected CLI frontend for planning-layer snapshot commands.

The frontend intentionally does not open SQLite or create an HTTP client.  A
storage/application adapter supplies those concerns, which keeps the existing
``database build`` parcel command and its compatibility grammar unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, TextIO

from dp_lookup.application.planning_snapshot import PlanningIngestionConfig

COMMANDS = (
    "build-planning",
    "status-planning",
    "verify-planning",
    "activate-planning",
    "rollback-planning",
)
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


class PlanningSnapshotServices(Protocol):
    """Adapter contract for the planning snapshot lifecycle.

    ``options`` is the parsed, JSON-safe command configuration.  The adapter
    may use the existing SQLite path or any other local snapshot repository.
    """

    def build_planning(self, database: Path, options: Mapping[str, Any]) -> Any: ...
    def status_planning(self, database: Path, options: Mapping[str, Any]) -> Any: ...
    def verify_planning(self, database: Path, options: Mapping[str, Any]) -> Any: ...
    def activate_planning(self, database: Path, options: Mapping[str, Any]) -> Any: ...
    def rollback_planning(self, database: Path, options: Mapping[str, Any]) -> Any: ...


class _MissingServices:
    def __getattr__(self, name: str) -> Any:
        def unavailable(database: Path, options: Mapping[str, Any]) -> Any:
            del database, options
            raise RuntimeError(f"planning snapshot service '{name}' is not configured")

        return unavailable


def parse_planning_snapshot_args(argv: Sequence[str]) -> Dict[str, Any]:
    """Parse the isolated planning snapshot grammar without terminating."""

    tokens = list(argv)
    if not tokens or tokens[0] not in COMMANDS:
        got = tokens[0] if tokens else ""
        raise ValueError(f"expected one of: {', '.join(COMMANDS)} (got '{got}')")
    command = tokens[0]
    database: Optional[Path] = None
    manifest: Optional[Path] = None
    resume: Optional[Path] = None
    layer_ids: Optional[tuple[int, ...]] = None
    as_json = False
    batch_size = PlanningIngestionConfig().batch_size
    max_attempts = PlanningIngestionConfig().max_attempts
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            as_json = True
        elif token == "--layers" or token.startswith("--layers="):
            if token == "--layers":
                index += 1
                if index >= len(tokens):
                    raise ValueError("--layers requires comma-separated layer IDs")
                value = tokens[index]
            else:
                value = token.split("=", 1)[1]
            try:
                layer_ids = tuple(sorted({int(part.strip()) for part in value.split(",")}))
            except ValueError as exc:
                raise ValueError("--layers requires comma-separated layer IDs") from exc
            if not layer_ids or any(value < 0 for value in layer_ids):
                raise ValueError("--layers requires non-negative layer IDs")
        elif token == "--database":
            index += 1
            if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                raise ValueError("--database requires a path")
            database = Path(tokens[index])
        elif token.startswith("--database="):
            value = token.split("=", 1)[1]
            if not value:
                raise ValueError("--database requires a path")
            database = Path(value)
        elif token in ("--manifest", "--checkpoint"):
            index += 1
            if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                raise ValueError(f"{token} requires a path")
            if token == "--manifest":
                manifest = Path(tokens[index])
            else:
                resume = Path(tokens[index])
        elif token.startswith("--manifest="):
            value = token.split("=", 1)[1]
            if not value:
                raise ValueError("--manifest requires a path")
            manifest = Path(value)
        elif token.startswith("--checkpoint="):
            value = token.split("=", 1)[1]
            if not value:
                raise ValueError("--checkpoint requires a path")
            resume = Path(value)
        elif token in ("--batch-size", "--max-attempts"):
            index += 1
            if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                raise ValueError(f"{token} requires an integer")
            try:
                numeric_value = int(tokens[index])
            except ValueError as exc:
                raise ValueError(f"{token} requires an integer") from exc
            if token == "--batch-size":
                batch_size = numeric_value
            else:
                max_attempts = numeric_value
        elif token.startswith("--batch-size=") or token.startswith("--max-attempts="):
            name, raw = token.split("=", 1)
            try:
                numeric_value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} requires an integer") from exc
            if name == "--batch-size":
                batch_size = numeric_value
            else:
                max_attempts = numeric_value
        else:
            raise ValueError(f"unknown planning snapshot option or argument: {token}")
        index += 1
    if database is None:
        raise ValueError("--database PATH is required")
    if layer_ids is not None and command != "build-planning":
        raise ValueError("--layers is only supported by build-planning")
    if layer_ids is not None and resume is not None:
        raise ValueError("incremental refresh uses SQLite resume state; omit --checkpoint")
    config = PlanningIngestionConfig(batch_size=batch_size, max_attempts=max_attempts)
    return {
        "command": command,
        "database": database,
        "manifest": manifest,
        "resume": resume,
        "layer_ids": layer_ids,
        "json": as_json,
        "config": config,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    services: Optional[PlanningSnapshotServices] = None,
    out: Optional[TextIO] = None,
) -> int:
    """Dispatch a planning snapshot command and return a process exit code."""

    output = out or sys.stdout
    try:
        parsed = parse_planning_snapshot_args(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        print(f"Error: {exc}", file=output)
        return EXIT_USAGE
    service = services or _MissingServices()
    try:
        service_method = parsed["command"].replace("-", "_")
        result = getattr(service, service_method)(parsed["database"], parsed)
    except Exception as exc:
        if parsed["json"]:
            print(
                json.dumps(
                    {"command": parsed["command"], "database": str(parsed["database"]), "error": str(exc)},
                    sort_keys=True,
                ),
                file=output,
            )
        else:
            print(f"Error: {parsed['command']} failed: {exc}", file=output)
        return EXIT_ERROR
    if parsed["json"]:
        print(
            json.dumps(
                {"command": parsed["command"], "database": str(parsed["database"]), "result": _json_safe(result)},
                sort_keys=True,
                default=str,
            ),
            file=output,
        )
    else:
        print(f"{parsed['command']}: OK", file=output)
        if isinstance(result, Mapping):
            for key, value in result.items():
                print(f"  {key}: {_json_safe(value)}", file=output)
        elif result is not None:
            print(f"  {_json_safe(result)}", file=output)
    return EXIT_SUCCESS


__all__ = [
    "COMMANDS",
    "EXIT_ERROR",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "PlanningSnapshotServices",
    "main",
    "parse_planning_snapshot_args",
]
