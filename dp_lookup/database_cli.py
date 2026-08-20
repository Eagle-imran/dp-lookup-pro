"""Small, dependency-injected frontend for database administration commands.

The frontend deliberately knows nothing about the database format.  A caller
supplies a :class:`DatabaseServices` implementation; this keeps command-line
parsing and output testable while the storage/ingestion implementation evolves.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, TextIO

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

COMMANDS = ("build", "status", "verify", "diff", "activate", "rollback")


class DatabaseServices(Protocol):
    """Operations supplied by the database adapter.

    Each operation receives the path selected by ``--database`` and may return
    any JSON-serialisable value (or a human-readable scalar).
    """

    def build(self, database: Path) -> Any: ...
    def status(self, database: Path) -> Any: ...
    def verify(self, database: Path) -> Any: ...
    def diff(self, database: Path) -> Any: ...
    def activate(self, database: Path) -> Any: ...
    def rollback(self, database: Path) -> Any: ...


class DatabaseServiceCall(Protocol):
    def __call__(self, database: Path) -> Any: ...


class _MissingServices:
    def __getattr__(self, name: str) -> DatabaseServiceCall:
        def unavailable(database: Path) -> Any:
            del database
            raise RuntimeError(f"database service '{name}' is not configured")

        return unavailable


def parse_database_args(argv: Sequence[str]) -> Dict[str, Any]:
    """Parse the isolated ``database`` grammar without terminating the host."""
    tokens = list(argv)
    if not tokens or tokens[0] != "database":
        raise ValueError("expected 'database' command")
    if len(tokens) < 2 or tokens[1] not in COMMANDS:
        got = tokens[1] if len(tokens) > 1 else ""
        raise ValueError(f"expected one of: {', '.join(COMMANDS)} (got '{got}')")

    command = tokens[1]
    database: Optional[Path] = None
    as_json = False
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            as_json = True
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
        elif token in ("--help", "-h"):
            raise ValueError("help requested")
        else:
            raise ValueError(f"unknown database option or argument: {token}")
        index += 1
    if database is None:
        raise ValueError("--database PATH is required")
    return {"command": command, "database": database, "json": as_json}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _emit(value: Any, command: str, database: Path, as_json: bool, out: TextIO) -> None:
    if as_json:
        print(json.dumps({"command": command, "database": str(database), "result": _json_safe(value)}, sort_keys=True, default=str), file=out)
        return
    print(f"database {command}: OK", file=out)
    if isinstance(value, Mapping):
        for key, item in value.items():
            print(f"  {key}: {_json_safe(item)}", file=out)
    elif value is not None:
        print(f"  {value}", file=out)


def main(argv: Optional[Sequence[str]] = None, *, services: Optional[DatabaseServices] = None, out: Optional[TextIO] = None) -> int:
    """Dispatch a database command and return a process-compatible exit code."""
    output = out or sys.stdout
    try:
        parsed = parse_database_args(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        print(f"Error: {exc}", file=output)
        return EXIT_USAGE
    service = services or _MissingServices()
    try:
        result = getattr(service, parsed["command"])(parsed["database"])
        _emit(result, parsed["command"], parsed["database"], parsed["json"], output)
    except Exception as exc:  # adapter errors become stable CLI failures
        if parsed["json"]:
            print(json.dumps({"command": parsed["command"], "database": str(parsed["database"]), "error": str(exc)}, sort_keys=True), file=output)
        else:
            print(f"Error: database {parsed['command']} failed: {exc}", file=output)
        return EXIT_ERROR
    return EXIT_SUCCESS


__all__ = ["COMMANDS", "EXIT_ERROR", "EXIT_SUCCESS", "EXIT_USAGE", "DatabaseServices", "main", "parse_database_args"]
