"""Opt-in CLI adapter for experimental plot assembly analysis.

The adapter owns command-line concerns only.  Geometry and planning logic are
provided by a late-bound service so the experimental feature can be added or
removed without importing it during a normal plot lookup.  The service
boundary is intentionally small::

    analyze(database, identities, output, gap_tolerance_m) -> Mapping

The command is screening-only and must never be mistaken for legal
amalgamation approval.
"""

from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, TextIO, Tuple, cast

from dp_lookup.cli_parser import default_database_path

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

COMMANDS = ("analyze",)
USAGE = """Usage: dp-lookup-pro experimental assembly analyze VILLAGE:CTS VILLAGE:CTS [more] [options]

Experimental commands (explicit opt-in):
  analyze               screen a proposed assembly of two or more plots

Options:
  --database PATH       local parcel database (default: configured project database)
  --output PATH         output folder (default: output/experimental-assemblies/...)
  --gap-tolerance M     maximum mapping gap in metres (default: 0.25)
  --json                print the machine-readable result
  -h, --help            show this help

Each identity uses VILLAGE:CTS.  Split occurs at the first colon so quoted
CTS values containing additional punctuation remain intact.
"""

Identity = Tuple[str, str]


class AssemblyService(Protocol):
    """Service boundary consumed by the experimental CLI adapter."""

    def analyze(
        self,
        database: Path,
        identities: Sequence[Identity],
        output: Optional[Path],
        gap_tolerance_m: float,
    ) -> Mapping[str, Any]: ...


class _HelpRequested(ValueError):
    pass


def _identity(value: str) -> Identity:
    village, separator, cts = value.partition(":")
    if not separator or not village.strip() or not cts.strip():
        raise ValueError(f"identity must use VILLAGE:CTS (got '{value}')")
    return village.strip().upper(), cts.strip().upper()


def _number(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError("--gap-tolerance requires a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("--gap-tolerance must be a finite non-negative number")
    return parsed


def parse_assembly_args(argv: Sequence[str]) -> Dict[str, Any]:
    """Parse the isolated experimental grammar without process side effects."""
    tokens = list(argv)
    if len(tokens) < 3 or tokens[:2] != ["experimental", "assembly"]:
        raise ValueError("expected 'experimental assembly analyze'")
    if tokens[2] in {"--help", "-h"}:
        return {"help": True}
    if tokens[2] not in COMMANDS:
        raise ValueError("expected experimental assembly command: analyze")

    identities: list[Identity] = []
    database: Optional[Path] = None
    output: Optional[Path] = None
    gap_tolerance_m = 0.25
    as_json = False
    index = 3
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            as_json = True
        elif token in {"--help", "-h"}:
            return {"help": True}
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
        elif token == "--output":
            index += 1
            if index >= len(tokens) or not tokens[index] or tokens[index].startswith("-"):
                raise ValueError("--output requires a path")
            output = Path(tokens[index])
        elif token.startswith("--output="):
            value = token.split("=", 1)[1]
            if not value:
                raise ValueError("--output requires a path")
            output = Path(value)
        elif token == "--gap-tolerance":
            index += 1
            if index >= len(tokens):
                raise ValueError("--gap-tolerance requires a number")
            gap_tolerance_m = _number(tokens[index])
        elif token.startswith("--gap-tolerance="):
            gap_tolerance_m = _number(token.split("=", 1)[1])
        elif token.startswith("-"):
            raise ValueError(f"unknown option: {token}")
        else:
            identities.append(_identity(token))
        index += 1

    if len(identities) < 2:
        raise ValueError("analyze requires at least two VILLAGE:CTS identities")
    return {
        "help": False,
        "command": "analyze",
        "identities": identities,
        "database": database or Path(default_database_path()),
        "output": output,
        "gap_tolerance_m": gap_tolerance_m,
        "json": as_json,
    }


def _default_service() -> AssemblyService:
    """Load the optional implementation only when the experimental command runs.

    The first location is the intended application adapter.  The second keeps
    the CLI compatible with an extension package while the experiment is
    being developed.  Import failures are converted to a useful CLI error by
    :func:`main` rather than affecting ordinary lookups.
    """
    candidates = (
        ("dp_lookup.application.assembly_services", "LocalAssemblyServices"),
        ("dp_lookup.experimental.assemblies", "LocalAssemblyServices"),
    )
    for module_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
            factory = getattr(module, class_name)
        except (ImportError, AttributeError):
            continue
        return cast(AssemblyService, factory())
    raise RuntimeError("experimental assembly service is not installed")


def _human(result: Mapping[str, Any], identities: Sequence[Identity], gap_tolerance_m: float) -> str:
    """Render a compact summary while retaining a stable detailed payload."""
    lines = [
        "[EXPERIMENTAL] Plot assembly analysis · screening only",
        "This is a feasibility study, not legal amalgamation or approval.",
        "Plots: " + ", ".join(f"{village} CTS {cts}" for village, cts in identities),
        f"Gap tolerance: {gap_tolerance_m:g} m",
    ]
    for key, label in (
        ("status", "Status"),
        ("assembly_status", "Status"),
        ("combined_area_sqm", "Combined area"),
        ("area_sqm", "Combined area"),
        ("part_count", "Plot count"),
        ("contiguous", "Contiguous"),
        ("gap_count", "Mapping gaps"),
        ("gap_area_sqm", "Gap area"),
    ):
        if key not in result or any(line.startswith(f"{label}:") for line in lines):
            continue
        value = result[key]
        if isinstance(value, (int, float)) and "area" in key:
            value = f"{value:,.2f} m²"
        lines.append(f"{label}: {value}")
    geometry = result.get("geometry")
    if isinstance(geometry, Mapping):
        recorded = geometry.get("gross_recorded_area_sqm")
        perimeter = geometry.get("external_perimeter_m")
        internal = geometry.get("removed_internal_boundary_length_m")
        if isinstance(recorded, (int, float)):
            lines.append(f"Recorded area total: {recorded:,.2f} m²")
        if isinstance(perimeter, (int, float)):
            lines.append(f"External perimeter: {perimeter:,.2f} m")
        if isinstance(internal, (int, float)):
            lines.append(f"Internal boundary removed: {internal:,.2f} m")
    planning = result.get("planning")
    if isinstance(planning, Mapping):
        lines.append(f"Combined planning zone: {planning.get('primary_zone', 'Unknown')}")
        lines.append(f"Reservations / designations: {len(planning.get('reservations') or [])} / {len(planning.get('designations') or [])}")
        lines.append(f"CRZ / Metro: {planning.get('crz_status', 'Unknown')} / {planning.get('metro_buffer', 'Unknown')}")
    warnings = result.get("warnings")
    if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)):
        messages = [
            str(item.get("message")) if isinstance(item, Mapping) else str(item)
            for item in warnings
        ]
        lines.append("Warnings: " + ("; ".join(messages) or "none"))
    outputs = result.get("outputs")
    if isinstance(outputs, Mapping) and outputs:
        lines.append("Outputs: " + str(Path(str(next(iter(outputs.values())))).parent))
    return "\n".join(lines)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    service: Optional[AssemblyService] = None,
    out: Optional[TextIO] = None,
) -> int:
    """Run the explicit experimental assembly command."""
    output_stream = out or sys.stdout
    try:
        parsed = parse_assembly_args(list(sys.argv[1:] if argv is None else argv))
    except _HelpRequested:
        print(USAGE, file=output_stream)
        return EXIT_SUCCESS
    except ValueError as exc:
        print(f"Error: {exc}", file=output_stream)
        print(USAGE, file=output_stream)
        return EXIT_USAGE
    if parsed.get("help"):
        print(USAGE, file=output_stream)
        return EXIT_SUCCESS

    try:
        result = (service or _default_service()).analyze(
            parsed["database"],
            parsed["identities"],
            parsed["output"],
            parsed["gap_tolerance_m"],
        )
    except Exception as exc:
        if parsed["json"]:
            print(
                json.dumps(
                    {
                        "command": "experimental assembly analyze",
                        "database": str(parsed["database"]),
                        "gap_tolerance_m": parsed["gap_tolerance_m"],
                        "identities": [
                            {"village": village, "cts": cts}
                            for village, cts in parsed["identities"]
                        ],
                        "error": str(exc),
                    },
                    sort_keys=True,
                ),
                file=output_stream,
            )
        else:
            print(f"Error: experimental assembly analysis failed: {exc}", file=output_stream)
        return EXIT_ERROR

    if parsed["json"]:
        payload = {
            "command": "experimental assembly analyze",
            "database": str(parsed["database"]),
            "gap_tolerance_m": parsed["gap_tolerance_m"],
            "identities": [{"village": village, "cts": cts} for village, cts in parsed["identities"]],
            "result": result,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str), file=output_stream)
    else:
        print(_human(result, parsed["identities"], parsed["gap_tolerance_m"]), file=output_stream)
    return EXIT_SUCCESS


__all__ = [
    "COMMANDS",
    "EXIT_ERROR",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "USAGE",
    "AssemblyService",
    "main",
    "parse_assembly_args",
]
