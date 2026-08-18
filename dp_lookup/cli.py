"""
Command-Line Interface (CLI) & Terminal Summary Formatter.
"""
import asyncio
import difflib
import json
import os
import sys
from typing import Any, Dict, List, Optional

from dp_lookup.clients.cache import sanitize_query_value
from dp_lookup.core.constants import _CTS_RE, _VILLAGE_RE, MCGM_VILLAGES
from dp_lookup.core.orchestrator import lookup_plot_pro

USAGE = """Usage: dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER> [OUTPUT_DIR] [options]

Options:
  --json            print the full JSON response instead of a summary
  --no-cache        force a fresh lookup, ignoring any cached report
  --list-villages   print all 128 valid village names and exit

Examples:
  dp-lookup-pro WORLI 947
  dp-lookup-pro "MALABAR HILL" "16/738"
  dp-lookup-pro BANDRA-A 409 ./client-reports --no-cache

Village must be one of the 128 exact MCGM revenue village names
(e.g. BANDRA-A, not BANDRA). See START-HERE.md for the full list."""


def suggest_villages(name: Any, limit: int = 8) -> List[str]:
    """Nearest valid village names for a mistyped one."""
    query = str(name or "").strip().upper()
    if not query:
        return []
    hits = [v for v in MCGM_VILLAGES if v == query]
    hits += [v for v in MCGM_VILLAGES if v.startswith(query) and v not in hits]
    hits += [v for v in MCGM_VILLAGES if query in v and v not in hits]
    for v in difflib.get_close_matches(query, MCGM_VILLAGES, n=limit, cutoff=0.6):
        if v not in hits:
            hits.append(v)
    return hits[:limit]


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


def main(argv: Optional[List[str]] = None) -> int:
    """Console entry point. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)

    if "--list-villages" in args or "--villages" in args:
        print(f"\n{len(MCGM_VILLAGES)} valid MCGM village names:\n")
        for i in range(0, len(MCGM_VILLAGES), 3):
            print("  " + "".join(f"{v:<26}" for v in MCGM_VILLAGES[i:i + 3]).rstrip())
        print("\nNames are exact. BANDRA, KURLA and BHANDUP alone are NOT valid -")
        print("use BANDRA-A..BANDRA-I, KURLA - 1..4, BHANDUP-E/W.\n")
        return 0

    as_json = False
    for flag in ("--json", "--raw"):
        if flag in args:
            args.remove(flag)
            as_json = True

    use_cache = True
    for flag in ("--no-cache", "--fresh"):
        if flag in args:
            args.remove(flag)
            use_cache = False

    # Tolerate the conversational form: "WORLI CTS 947"
    if len(args) >= 3 and args[1].upper() in ("CTS", "CS", "PLOT", "NO", "NO."):
        args = [args[0], args[2], *args[3:]]

    if len(args) < 2:
        print(USAGE)
        return 1

    village, cts_number = args[0], args[1]
    output_dir = args[2] if len(args) > 2 else "./output"

    try:
        safe_village = sanitize_query_value(village, _VILLAGE_RE, "village", 64)
        safe_cts = sanitize_query_value(cts_number, _CTS_RE, "cts_number", 32)
    except ValueError as exc:
        print(f"  Error: {exc}")
        return 1

    if not as_json:
        print(f"  Looking up {safe_village} CTS {safe_cts}"
              f"{' (fresh)' if not use_cache else ''}...")

    shown = {"done": False}

    def _show_early(snapshot):
        if as_json or shown["done"]:
            return
        shown["done"] = True
        print(format_result_human(snapshot))
        print("  Building PDF, maps and CAD files...", flush=True)

    result = asyncio.run(
        lookup_plot_pro(
            village=safe_village,
            cts_number=safe_cts,
            output_dir=output_dir,
            use_cache=use_cache,
            on_data=None if as_json else _show_early,
        )
    )

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif shown["done"] and "error" not in result:
        meta = result.get("metadata", {})
        files = result.get("export_files") or {}
        bundle_f_count = len([p for k, p in files.items() if k not in ("bundle_folder", "master_excel_register") and p and os.path.exists(p)])
        print(f"  Done in {meta.get('execution_time_ms', 0) / 1000:.1f}s - all {bundle_f_count} files written.")
        for w in meta.get("warnings") or []:
            print(f"  Warning: {w}")
        print()
    else:
        print(format_result_human(result))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
