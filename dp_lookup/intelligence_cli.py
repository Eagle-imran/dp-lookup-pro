"""Small CLI for plot-intelligence build, analysis, search and comparison."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dp_lookup.application.intelligence_services import PlotIntelligenceServices

COMMANDS = ("build", "status", "verify", "activate", "analyze", "search", "compare", "check")

USAGE = """Usage: dp-lookup-pro intelligence <COMMAND> --database PATH [options]

Commands:
  build                 derive a resumable intelligence build from active snapshots
  status                list intelligence builds and active version
  verify                verify completeness and provenance indexes
  activate              atomically publish a verified full build
  analyze VILLAGE CTS   show one complete plot dossier
  search                filter plots by site and planning facts
  compare VILLAGE:CTS... compare 2-20 plots side by side
  check                 check source age and intelligence/source alignment
"""


def _bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    raise ValueError(f"{name} requires yes or no")


def _number(value: str, name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} requires a number") from exc


def parse_intelligence_args(argv: Sequence[str]) -> Dict[str, Any]:
    tokens = list(argv)
    if len(tokens) < 2 or tokens[0] != "intelligence" or tokens[1] not in COMMANDS:
        raise ValueError("expected intelligence command: " + ", ".join(COMMANDS))
    command = tokens[1]
    positionals: List[str] = []
    options: Dict[str, Any] = {"json": False, "offset": 0, "include_neighbours": True, "evidence_mode": "full"}
    value_options = {
        "--database": "database",
        "--build-id": "build_id",
        "--limit": "limit",
        "--offset": "offset",
        "--evidence": "evidence_mode",
        "--village": "village",
        "--ward": "ward",
        "--min-area": "min_area_sqm",
        "--max-area": "max_area_sqm",
        "--zone": "zone",
        "--max-encumbered": "max_encumbered_percent",
        "--road": "road_name",
        "--has-reservation": "reservations",
        "--has-designation": "designations",
        "--refresh-days": "refresh_days",
        "--parcel-snapshot-id": "parcel_snapshot_id",
        "--planning-snapshot-id": "planning_snapshot_id",
        "--workers": "workers",
    }
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            options["json"] = True
        elif token == "--no-neighbours":
            options["include_neighbours"] = False
        elif token.startswith("--"):
            name, separator, inline = token.partition("=")
            key = value_options.get(name)
            if key is None:
                raise ValueError(f"unknown intelligence option: {name}")
            if separator:
                value = inline
            else:
                index += 1
                if index >= len(tokens):
                    raise ValueError(f"{name} requires a value")
                value = tokens[index]
            if not value:
                raise ValueError(f"{name} requires a value")
            if key in {
                "build_id",
                "limit",
                "offset",
                "parcel_snapshot_id",
                "planning_snapshot_id",
                "workers",
            }:
                try:
                    options[key] = int(value)
                except ValueError as exc:
                    raise ValueError(f"{name} requires an integer") from exc
            elif key in {"min_area_sqm", "max_area_sqm", "max_encumbered_percent", "refresh_days"}:
                options[key] = _number(value, name)
            elif key in {"reservations", "designations"}:
                options[key] = _bool(value, name)
            elif key == "database":
                options[key] = Path(value)
            else:
                options[key] = value
        else:
            positionals.append(token)
        index += 1
    if "database" not in options:
        raise ValueError("--database PATH is required")
    if command == "analyze" and len(positionals) != 2:
        raise ValueError("analyze requires VILLAGE and CTS")
    if command == "compare" and not 2 <= len(positionals) <= 20:
        raise ValueError("compare requires 2-20 VILLAGE:CTS values")
    if command == "compare" and any(
        ":" not in value or not all(part.strip() for part in value.split(":", 1))
        for value in positionals
    ):
        raise ValueError("compare identities must use VILLAGE:CTS")
    if command not in {"analyze", "compare"} and positionals:
        raise ValueError(f"{command} does not accept positional arguments")
    options["command"] = command
    options["positionals"] = positionals
    return options


def _identity(value: str) -> Tuple[str, str]:
    village, separator, cts_no = value.partition(":")
    if not separator or not village.strip() or not cts_no.strip():
        raise ValueError("compare identities must use VILLAGE:CTS")
    return village.strip().upper(), cts_no.strip().upper()


def _human(command: str, result: Any) -> str:
    if command == "analyze":
        identity = result["plot_identity"]
        planning = result["planning"]
        access = result["access"]
        quality = result["quality"]
        return "\n".join(
            (
                f"{identity['village']} CTS {identity['cts_no']} · Ward {identity.get('ward') or 'N/A'}",
                f"Area: {identity['area_sqm']:,.2f} m² · Zone: {planning['primary_zone']}",
                f"Reservations: {len(planning['reservations'])} · Designations: {len(planning['designations'])}",
                f"Net unencumbered: {planning['net_unencumbered_sqm']:,.2f} m²",
                f"Road: {access['road_name']} ({access['road_width']}) · {access['distance_m']} m",
                f"Confidence: {quality['confidence']} · Facts hash: {quality['facts_hash']}",
            )
        )
    if command == "search":
        lines = [f"{result['count']} plot(s) found in intelligence build {result['build_id']}"]
        lines.extend(
            f"{item['village']} CTS {item['cts_no']} · {item['area_sqm']:,.2f} m² · "
            f"Zone {item['primary_zone']} · {item['confidence']}"
            for item in result["results"]
        )
        return "\n".join(lines)
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    services: Optional[PlotIntelligenceServices] = None,
) -> int:
    try:
        parsed = parse_intelligence_args(list(sys.argv[1:] if argv is None else argv))
        service = services or PlotIntelligenceServices()
        command = parsed.pop("command")
        database = parsed.pop("database")
        positionals = parsed.pop("positionals")
        as_json = bool(parsed.pop("json"))
        if command == "build":
            allowed = {
                key: parsed[key]
                for key in (
                    "limit",
                    "offset",
                    "include_neighbours",
                    "evidence_mode",
                    "parcel_snapshot_id",
                    "planning_snapshot_id",
                    "workers",
                )
                if key in parsed
            }
            result = service.build(database, **allowed)
        elif command == "status":
            result = service.status(database)
        elif command == "verify":
            result = service.verify(database, build_id=parsed.get("build_id"))
        elif command == "activate":
            result = service.activate(database, build_id=parsed.get("build_id"))
        elif command == "analyze":
            result = service.analyze(database, positionals[0], positionals[1], build_id=parsed.get("build_id"))
        elif command == "search":
            allowed_keys = {
                "build_id", "village", "ward", "min_area_sqm", "max_area_sqm", "zone",
                "reservations", "designations", "max_encumbered_percent", "road_name", "limit", "offset",
            }
            result = service.search(database, **{key: value for key, value in parsed.items() if key in allowed_keys})
        elif command == "compare":
            result = service.compare(database, [_identity(value) for value in positionals], build_id=parsed.get("build_id"))
        else:
            result = service.check(database, refresh_days=parsed.get("refresh_days", 183.0))
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str) if as_json else _human(command, result))
    return 0


__all__ = ["COMMANDS", "USAGE", "main", "parse_intelligence_args"]
