"""CLI frontend for versioned plot-authority source records.

This module intentionally does not own the SQLite schema; it is a small
adapter over the versioned authority repository.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, TextIO

from dp_lookup.authority.store import AuthorityStore

COMMANDS = ("add", "list", "show", "verify", "recommend", "activate", "withdraw", "audit")
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _required_value(tokens: Sequence[str], index: int, option: str) -> tuple[str, int]:
    if index + 1 >= len(tokens) or not tokens[index + 1] or tokens[index + 1].startswith("-"):
        raise ValueError(f"{option} requires a value")
    return tokens[index + 1], index + 1


def parse_authority_args(argv: Sequence[str]) -> Dict[str, Any]:
    """Parse the isolated ``sources`` grammar without terminating the host."""

    tokens = list(argv)
    if not tokens or tokens[0] != "sources":
        raise ValueError("expected 'sources' command")
    if len(tokens) < 2 or tokens[1] not in COMMANDS:
        got = tokens[1] if len(tokens) > 1 else ""
        raise ValueError(f"expected one of: {', '.join(COMMANDS)} (got '{got}')")
    command = tokens[1]
    positionals: list[str] = []
    options: Dict[str, Any] = {"json": False}
    value_options = {
        "--database": "database",
        "--actor": "actor",
        "--village": "village",
        "--cts": "cts",
        "--status": "status",
        "--reviewed-by": "reviewed_by",
        "--notes": "notes",
        "--purpose": "purpose",
        "--activated-by": "activated_by",
        "--reason": "reason",
    }
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            options["json"] = True
        elif token.startswith("--"):
            name, separator, inline = token.partition("=")
            key = value_options.get(name)
            if key is None:
                raise ValueError(f"unknown sources option: {name}")
            if separator:
                value = inline
                if not value:
                    raise ValueError(f"{name} requires a value")
            else:
                value, index = _required_value(tokens, index, name)
            if key == "database":
                options[key] = Path(value)
            else:
                options[key] = value
        else:
            positionals.append(token)
        index += 1

    if "database" not in options:
        raise ValueError("--database PATH is required")
    required_positionals = {"add": 1, "show": 1, "verify": 1, "recommend": 2, "activate": 1, "withdraw": 1}
    expected = required_positionals.get(command, 0)
    if len(positionals) != expected:
        label = (
            "MANIFEST"
            if command == "add"
            else "RECORD_ID"
            if command in {"show", "verify", "activate", "withdraw"}
            else "VILLAGE CTS"
        )
        raise ValueError(f"{command} requires {label}")
    if command == "activate":
        purpose = str(options.get("purpose", ""))
        if purpose not in {"area", "geometry", "planning"}:
            raise ValueError("--purpose must be one of: area, geometry, planning")
        if not str(options.get("activated_by", "")).strip():
            raise ValueError("--activated-by NAME is required")
        if not str(options.get("reason", "")).strip():
            raise ValueError("--reason TEXT is required")
    if command == "verify" and not str(options.get("reviewed_by", "")).strip():
        raise ValueError("--reviewed-by NAME is required")
    if command == "withdraw":
        if not str(options.get("actor", "")).strip():
            raise ValueError("--actor NAME is required")
        if not str(options.get("reason", "")).strip():
            raise ValueError("--reason TEXT is required")
    options.update(command=command, positionals=positionals)
    return options


def _load_manifest(path: Path) -> list[Dict[str, Any]]:
    """Load either one source object or ``{manifest_version: 1, items: []}``."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read manifest: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {exc}") from exc
    if isinstance(payload, Mapping):
        items = payload.get("items") if "items" in payload else [payload]
    else:
        raise ValueError("manifest must be a JSON object")
    if not isinstance(items, list) or not items:
        raise ValueError("manifest must contain at least one source item")
    normalized: list[Dict[str, Any]] = []
    for number, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"manifest item {number} must be an object")
        record = dict(item)
        file_value = record.get("file") or record.get("file_path")
        if file_value:
            file_path = Path(str(file_value))
            if not file_path.is_absolute():
                file_path = (path.parent / file_path).resolve()
            record["file"] = str(file_path)
            if not file_path.is_file():
                raise ValueError(f"manifest item {number} file does not exist: {file_path}")
            expected_hash = record.get("sha256")
            if expected_hash:
                digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
                if digest.casefold() != str(expected_hash).casefold():
                    raise ValueError(f"manifest item {number} checksum does not match: {file_path}")
            else:
                record["sha256"] = hashlib.sha256(file_path.read_bytes()).hexdigest()
        for field in ("village", "cts_no", "cts", "source_type"):
            if field in record and record[field] is not None and not str(record[field]).strip():
                raise ValueError(f"manifest item {number} has a blank {field}")
        normalized.append(record)
    return normalized


def _open_store(database: Path) -> Any:
    return AuthorityStore.open(database)


def _call(store: Any, names: Iterable[str], *args: Any, **kwargs: Any) -> Any:
    for name in names:
        method = getattr(store, name, None)
        if callable(method):
            try:
                return method(*args, **kwargs)
            except TypeError:
                # Permit a store with the same operation but a narrower
                # metadata signature. Do not hide its actual runtime errors.
                if kwargs:
                    return method(*args)
                raise
    raise RuntimeError(f"authority store does not implement: {', '.join(names)}")


def _run(parsed: Mapping[str, Any]) -> Any:
    database = parsed["database"]
    command = parsed["command"]
    with _open_store(database) as store:
        positionals = parsed["positionals"]
        if command == "add":
            return _call(
                store,
                ("add_manifest", "import_manifest", "add_sources"),
                _load_manifest(Path(positionals[0])),
                actor=parsed.get("actor"),
            )
        if command == "list":
            filters = {key: parsed[key] for key in ("village", "cts", "status") if key in parsed}
            return _call(store, ("list_sources", "list_records", "sources"), **filters)
        if command == "show":
            return _call(store, ("get_source", "get_record", "show_source"), positionals[0])
        if command == "verify":
            return _call(
                store,
                ("verify_source", "verify_record"),
                positionals[0],
                reviewed_by=parsed["reviewed_by"],
                notes=parsed.get("notes"),
            )
        if command == "recommend":
            from dp_lookup.authority.selection import recommend_authority

            return recommend_authority(store, positionals[0], positionals[1])
        if command == "activate":
            return _call(
                store,
                ("activate_source", "activate_record"),
                positionals[0],
                purpose=parsed["purpose"],
                activated_by=parsed["activated_by"],
                reason=parsed.get("reason"),
            )
        if command == "withdraw":
            return _call(
                store,
                ("withdraw_source", "withdraw_record"),
                positionals[0],
                actor=parsed["actor"],
                reason=parsed["reason"],
            )
        return _call(store, ("audit", "audit_sources", "audit_records"))


def _human(command: str, result: Any) -> str:
    if isinstance(result, Mapping):
        if command == "recommend":
            recommendations = result.get("recommendations")
            if isinstance(recommendations, Mapping):
                selected = []
                for purpose in ("area", "geometry", "planning"):
                    resolution = recommendations.get(purpose)
                    if not isinstance(resolution, Mapping):
                        continue
                    source = resolution.get(purpose)
                    if purpose == "planning" and isinstance(source, list):
                        source = source[0] if source else None
                    if isinstance(source, Mapping) and source.get("record_id") is not None:
                        selected.append(f"{purpose}={source['record_id']}")
                return "sources recommend: " + (", ".join(selected) if selected else "no eligible sources")
            selected_id = result.get("selected_source_id", result.get("source_id", "none"))
            return f"sources recommend: selected {selected_id}"
        if command == "list":
            records = result.get("records", result.get("sources", result))
            if isinstance(records, list):
                return (
                    "\n".join(str(item.get("source_id", item.get("record_id", item))) for item in records)
                    or "sources list: no records"
                )
        if command == "audit":
            return "sources audit: " + ", ".join(f"{key}={value}" for key, value in result.items())
        return f"sources {command}: OK" + (
            f" ({result.get('source_id', result.get('record_id'))})"
            if result.get("source_id", result.get("record_id")) is not None
            else ""
        )
    return f"sources {command}: {result}"


def main(argv: Optional[Sequence[str]] = None, *, out: Optional[TextIO] = None) -> int:
    output = out or sys.stdout
    try:
        parsed = parse_authority_args(list(sys.argv[1:] if argv is None else argv))
        result = _run(parsed)
    except ValueError as exc:
        print(f"Error: {exc}", file=output)
        return EXIT_USAGE
    except Exception as exc:
        if "parsed" in locals() and parsed.get("json"):
            print(json.dumps({"command": parsed["command"], "error": str(exc)}, sort_keys=True), file=output)
        else:
            print(f"Error: sources command failed: {exc}", file=output)
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
        print(_human(parsed["command"], result), file=output)
    return EXIT_SUCCESS


__all__ = ["COMMANDS", "EXIT_ERROR", "EXIT_SUCCESS", "EXIT_USAGE", "main", "parse_authority_args"]
