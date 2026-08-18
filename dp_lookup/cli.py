"""
Command-Line Interface (CLI) & Terminal Summary Formatter.
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from importlib import metadata as importlib_metadata
from typing import Any, Dict, List, Optional

from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES
from dp_lookup.application.lookup_service import lookup_plot_pro
from dp_lookup.clients.validation import sanitize_query_value
from dp_lookup.core.constants import _CTS_RE, _VILLAGE_RE, APPLICATION_VERSION, MCGM_VILLAGES
from dp_lookup.core.villages import suggest_villages as _suggest_villages
from dp_lookup.planning_evidence.models import EvidenceMode

suggest_villages = _suggest_villages

USAGE = """Usage: dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER> [OUTPUT_DIR] [options]

Options:
  --json            print the full JSON response instead of a summary
  --no-cache        force a fresh lookup, ignoring any cached report
  --evidence MODE   basic, shadow, standard, or full (default: basic)
  --list-villages   print all 128 valid village names and exit

Examples:
  dp-lookup-pro WORLI 947
  dp-lookup-pro "MALABAR HILL" "16/738"
  dp-lookup-pro BANDRA-A 409 ./client-reports --no-cache

Village must be one of the 128 exact MCGM revenue village names
(e.g. BANDRA-A, not BANDRA). See START-HERE.md for the full list."""


# These values are part of the command-line contract.  Keep validation and
# lookup failures at 1 for compatibility with the original CLI; a result that
# was produced but is known to be incomplete gets its own status instead.
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_INCOMPLETE = 2
EXIT_USAGE = EXIT_ERROR

# Friendly aliases for callers that use the conventional names.
EXIT_OK = EXIT_SUCCESS
EXIT_FAILURE = EXIT_ERROR
EXIT_INCOMPLETE_RESULT = EXIT_INCOMPLETE

try:
    VERSION = importlib_metadata.version("dp-lookup-pro")
except importlib_metadata.PackageNotFoundError:
    # Source checkouts do not necessarily have an installed distribution.
    VERSION = APPLICATION_VERSION


HELP = USAGE + "\n\nOptions:\n  -h, --help        show this help message and exit\n  --version         show the installed version and exit"


def format_result_human(result: Dict[str, Any]) -> str:
    """Readable summary of a lookup. Raw JSON stays available behind --json."""
    if "error" in result:
        lines = ["", "  Could not complete the lookup:", f"  {result['error']}", ""]
        return "\n".join(lines)

    ident = result["plot_identity"]
    plan = result["planning_remarks"]
    reg = result["regulatory_and_infrastructure"]
    cluster = result["spatial_cluster"]
    files = result["export_files"]
    meta = result["metadata"]

    area = ident.get("area_sqm")
    area_txt = f"{area:,.2f} m\u00b2" if isinstance(area, (int, float)) else "not on record"
    if "derived" in str(ident.get("area_source", "")):
        area_txt += "  (derived from boundary, not MCGM-approved)"

    res_list = plan.get("reservations") or []
    if res_list:
        res_txt = ", ".join(f"{r['code']} ({r['description']})" for r in res_list)
    elif plan.get("reservation", {}).get("code") != "None":
        res_txt = plan["reservation"].get("type")
    else:
        res_txt = "None"

    des_list = plan.get("designations") or []
    if des_list:
        des_txt = ", ".join(f"{d['code']} ({d['description']})" for d in des_list)
    elif plan.get("designation", {}).get("code") != "None":
        des_txt = plan["designation"].get("description")
    else:
        des_txt = "None"

    rows = [
        ("Plot area", area_txt),
        ("Zone", plan.get("zone")),
        ("Reservation", res_txt),
        ("Designation", des_txt),
        ("DP modification", plan.get("dp_modification", {}).get("approval_no")),
    ]

    enc = plan.get("encumbrance") or {}
    if enc.get("encumbered_percent", 0) > 0:
        rows.append(("Encumbered area", f"{enc.get('encumbered_area_sqm', 0):,.2f} m² ({enc.get('encumbered_percent', 0):.2f}% of plot)"))
        rows.append(("Net developable", f"{enc.get('net_unencumbered_sqm', 0):,.2f} m² ({enc.get('net_unencumbered_percent', 0):.2f}% - Zone {plan.get('zone')})"))

    rows += [
        ("CRZ", reg.get("crz_status")),
        ("Metro buffer", reg.get("metro_buffer")),
        ("Abutting road", f"{reg['abutting_road'].get('name')} ({reg['abutting_road'].get('width')})"),
        ("Adjoining plots", str(cluster.get("adjoining_plots_count"))),
    ]

    out = ["", f"  {plan.get('status_badge')}",
           f"  {ident.get('village')}  ·  CTS {ident.get('cts_no')}  ·  Ward {ident.get('ward')}", ""]
    for label, value in rows:
        out.append(f"    {label:<17} {value}")

    neighbours = [n.get("cts_no") for n in cluster.get("adjoining_cts_plots", [])][:6]
    if neighbours:
        out.append(f"    {'Neighbours':<17} CTS " + ", ".join(str(n) for n in neighbours))

    bundle_f_count = len([p for k, p in (files or {}).items() if k not in ("bundle_folder", "master_excel_register") and p and os.path.exists(p)])
    out += ["", f"    Files            {files.get('bundle_folder')}  ({bundle_f_count} files)",
            f"    Report           {files.get('pdf_report')}",
            f"    Register         {files.get('master_excel_register')}"]

    if meta.get("cached_result"):
        out.append(f"\n    Cached result from {meta.get('cached_at')} "
                   f"({meta.get('cache_age_days')} days old). Use --no-cache to refetch.")
    else:
        out.append(f"\n    Fetched in {meta.get('execution_time_ms', 0) / 1000:.1f}s")

    for note in meta.get("notes") or []:
        out.append(f"    Note: {note}")
    if not meta.get("complete", True):
        out.append("\n    INCOMPLETE - this report is missing data:")
        for w in meta.get("warnings") or []:
            out.append(f"      - {w}")
        out.append("    Re-run before relying on it.")

    out.append("")
    return "\n".join(out)


def _print_villages() -> None:
    """Print the village catalogue shared by ``--list-villages``/``--villages``."""
    print(f"\n{len(MCGM_VILLAGES)} valid MCGM village names:\n")
    for i in range(0, len(MCGM_VILLAGES), 3):
        print("  " + "".join(f"{v:<26}" for v in MCGM_VILLAGES[i:i + 3]).rstrip())
    print("\nNames are exact. BANDRA, KURLA and BHANDUP alone are NOT valid -")
    print("use BANDRA-A..BANDRA-I, KURLA - 1..4, BHANDUP-E/W.\n")


def _parse_cli_args(raw_args: List[str]) -> Dict[str, Any]:
    """Parse the deliberately small CLI grammar without argparse side effects.

    ``argparse`` writes errors and exits from inside the parser, which makes
    the Python API ``main([...])`` awkward to embed and subtly changes the
    historical return values.  This parser keeps those values deterministic.
    """
    positionals: List[str] = []
    as_json = False
    use_cache = True
    list_villages = False
    show_help = False
    show_version = False
    evidence_mode = EvidenceMode.BASIC

    index = 0
    while index < len(raw_args):
        token = raw_args[index]
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
            if index >= len(raw_args):
                raise ValueError("--evidence requires a mode")
            evidence_mode = EvidenceMode.parse(raw_args[index])
        elif token.startswith("--evidence="):
            evidence_mode = EvidenceMode.parse(token.split("=", 1)[1])
        elif token.startswith("-"):
            raise ValueError(f"unknown option: {token}")
        else:
            positionals.append(token)
        index += 1

    if list_villages and positionals:
        raise ValueError("--villages does not accept positional arguments")
    if show_version and positionals:
        raise ValueError("--version does not accept positional arguments")

    return {
        "positionals": positionals,
        "as_json": as_json,
        "use_cache": use_cache,
        "list_villages": list_villages,
        "show_help": show_help,
        "show_version": show_version,
        "evidence_mode": evidence_mode,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Console entry point. Returns a process exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
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

    args = parsed["positionals"]
    # Tolerate the conversational form: "WORLI CTS 947".  Do this before
    # checking the positional count so its optional output directory remains
    # compatible with the original implementation.
    if len(args) >= 3 and args[1].upper() in ("CTS", "CS", "PLOT", "NO", "NO."):
        args = [args[0], args[2], *args[3:]]

    if len(args) < 2:
        print(USAGE)
        return EXIT_USAGE
    if len(args) > 3:
        print("  Error: too many positional arguments")
        print(USAGE)
        return EXIT_USAGE

    as_json = parsed["as_json"]
    use_cache = parsed["use_cache"]
    evidence_mode = parsed["evidence_mode"]
    village, cts_number = args[0], args[1]
    output_dir = args[2] if len(args) > 2 else "./output"

    try:
        safe_village = sanitize_query_value(village, _VILLAGE_RE, "village", 64)
        safe_cts = sanitize_query_value(cts_number, _CTS_RE, "cts_number", 32)
    except ValueError as exc:
        print(f"  Error: {exc}")
        return EXIT_ERROR

    if not as_json:
        print(f"  Looking up {safe_village} CTS {safe_cts}"
              f"{' (fresh)' if not use_cache else ''}"
              f"{' [' + evidence_mode.value + ' evidence]' if evidence_mode is not EvidenceMode.BASIC else ''}...")

    shown = {"done": False}

    def _show_early(snapshot):
        if as_json or shown["done"]:
            return
        shown["done"] = True
        print(format_result_human(snapshot))
        if not snapshot.get("metadata", {}).get("cached_result"):
            print("  Building PDF, maps and CAD files...", flush=True)

    lookup_started = time.perf_counter()
    result = asyncio.run(
        lookup_plot_pro(
            village=safe_village,
            cts_number=safe_cts,
            output_dir=output_dir,
            use_cache=use_cache,
            on_data=None if as_json else _show_early,
            dependencies=replace(DEFAULT_DEPENDENCIES, planning_evidence_mode=evidence_mode),
        )
    )
    lookup_elapsed_ms = (time.perf_counter() - lookup_started) * 1000

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif "error" in result:
        # The early callback can have printed a planning snapshot already;
        # retain the final error wording and the legacy error return code.
        if not shown["done"]:
            print(format_result_human(result))
    elif result.get("metadata", {}).get("cached_result"):
        # A cache callback is synchronous, so it used to be mistaken for the
        # first phase of a cold lookup and printed "Building ...".  Report the
        # real local retrieval latency instead of the old lookup duration.
        if not shown["done"]:
            print(format_result_human(result))
        print(f"  Cache retrieval: {lookup_elapsed_ms:.1f} ms.")
        print()
    elif not result.get("metadata", {}).get("complete", True):
        # The early snapshot may have looked complete; the final result is the
        # authoritative status and must visibly call out missing data.
        print(format_result_human(result))
    elif shown["done"]:
        meta = result.get("metadata", {})
        files = result.get("export_files") or {}
        bundle_f_count = len([p for k, p in files.items() if k not in ("bundle_folder", "master_excel_register") and p and os.path.exists(p)])
        print(f"  Done in {meta.get('execution_time_ms', 0) / 1000:.1f}s - all {bundle_f_count} files written.")
        for w in meta.get("warnings") or []:
            print(f"  Warning: {w}")
        print()
    else:
        print(format_result_human(result))
    if "error" in result:
        return EXIT_ERROR
    if not result.get("metadata", {}).get("complete", True):
        return EXIT_INCOMPLETE
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
