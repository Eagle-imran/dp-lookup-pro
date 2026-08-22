"""Presentation helpers for the public :mod:`dp_lookup.cli` frontend.

The lookup use case returns a JSON-compatible mapping.  Keeping terminal
formatting here means the command runner can be reused by other frontends
without importing the report-generation stack.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence


def format_result_human(result: Mapping[str, Any]) -> str:
    """Return the historical readable lookup summary.

    Raw JSON remains available behind ``--json``.  This function intentionally
    accepts a mapping rather than a domain object because cached results and
    older integrations use the serialized result contract.
    """
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
    area_txt = f"{area:,.2f} m²" if isinstance(area, (int, float)) else "not on record"
    assessment = ident.get("area_assessment")
    if isinstance(assessment, dict) and assessment.get("selected_area_basis") == "calculated_boundary_area":
        area_txt += "  (calculated from boundary)"
    elif not isinstance(assessment, dict) and "derived" in str(ident.get("area_source", "")).casefold():
        area_txt += "  (derived from boundary; legacy result)"

    res_list = plan.get("reservations") or []
    if res_list:
        res_txt = ", ".join(f"{item['code']} ({item['description']})" for item in res_list)
    elif plan.get("reservation", {}).get("code") != "None":
        res_txt = plan["reservation"].get("type")
    else:
        res_txt = "None"

    des_list = plan.get("designations") or []
    if des_list:
        des_txt = ", ".join(f"{item['code']} ({item['description']})" for item in des_list)
    elif plan.get("designation", {}).get("code") != "None":
        des_txt = plan["designation"].get("description")
    else:
        des_txt = "None"

    rows: list[tuple[str, Any]] = [("Working plot area", area_txt)]
    if isinstance(assessment, dict):
        recorded = assessment.get("recorded_plot_area_sqm")
        calculated = assessment.get("calculated_boundary_area_sqm")
        difference = assessment.get("difference_percent")
        rows.extend(
            [
                ("Recorded area", f"{recorded:,.2f} m²" if isinstance(recorded, (int, float)) else "not available"),
                ("Boundary area", f"{calculated:,.2f} m²" if isinstance(calculated, (int, float)) else "not available"),
                ("Area difference", f"{difference:.2f}%" if isinstance(difference, (int, float)) else "not comparable"),
                ("Reliability", assessment.get("reliability_label", "Screening")),
            ]
        )
    authority = ident.get("authority_resolution")
    if isinstance(authority, dict) and authority.get("active_record_ids"):
        rows.append(("Authority source", f"{authority.get('status', 'active')} - records " + ", ".join(str(value) for value in authority["active_record_ids"])))
    rows += [
        ("Zone", plan.get("zone")),
        ("Reservation", res_txt),
        ("Designation", des_txt),
        ("DP modification", plan.get("dp_modification", {}).get("approval_no")),
    ]

    enc = plan.get("encumbrance") or {}
    if enc.get("encumbered_percent", 0) > 0:
        rows.extend(
            [
                ("Encumbered area", f"{enc.get('encumbered_area_sqm', 0):,.2f} m² ({enc.get('encumbered_percent', 0):.2f}% of plot)"),
                ("Net developable", f"{enc.get('net_unencumbered_sqm', 0):,.2f} m² ({enc.get('net_unencumbered_percent', 0):.2f}% - Zone {plan.get('zone')})"),
            ]
        )

    rows += [
        ("CRZ", reg.get("crz_status")),
        ("Metro buffer", reg.get("metro_buffer")),
        ("Abutting road", f"{reg['abutting_road'].get('name')} ({reg['abutting_road'].get('width')})"),
        ("Adjoining plots", str(cluster.get("adjoining_plots_count"))),
    ]

    out = [
        "",
        f"  {plan.get('status_badge')}",
        f"  {ident.get('village')}  ·  CTS {ident.get('cts_no')}  ·  Ward {ident.get('ward')}",
        "",
    ]
    out.extend(f"    {label:<17} {value}" for label, value in rows)

    if isinstance(assessment, dict):
        for flag in assessment.get("quality_flags") or []:
            if isinstance(flag, dict) and flag.get("message"):
                out.append(f"    Area check       {flag['message']}")

    neighbours = [item.get("cts_no") for item in cluster.get("adjoining_cts_plots", [])][:6]
    if neighbours:
        out.append(f"    {'Neighbours':<17} CTS " + ", ".join(str(item) for item in neighbours))

    bundle_f_count = len(
        [path for key, path in (files or {}).items() if key not in ("bundle_folder", "master_excel_register") and path and os.path.exists(path)]
    )
    out += [
        "",
        f"    Files            {files.get('bundle_folder')}  ({bundle_f_count} files)",
        f"    Report           {files.get('pdf_report')}",
        f"    Register         {files.get('master_excel_register')}",
    ]

    if meta.get("cached_result"):
        out.append(f"\n    Cached result from {meta.get('cached_at')} ({meta.get('cache_age_days')} days old). Use --no-cache to refetch.")
    else:
        out.append(f"\n    Fetched in {meta.get('execution_time_ms', 0) / 1000:.1f}s")
    out.extend(f"    Note: {note}" for note in meta.get("notes") or [])
    if not meta.get("complete", True):
        out.append("\n    INCOMPLETE - this report is missing data:")
        out.extend(f"      - {warning}" for warning in meta.get("warnings") or [])
        out.append("    Re-run before relying on it.")
    out.append("")
    return "\n".join(out)


def print_villages(villages: Sequence[str]) -> None:
    """Print the village catalogue shared by ``--list-villages``."""
    print(f"\n{len(villages)} valid MCGM village names:\n")
    for index in range(0, len(villages), 3):
        print("  " + "".join(f"{village:<26}" for village in villages[index : index + 3]).rstrip())
    print("\nNames are exact. BANDRA, KURLA and BHANDUP alone are NOT valid -")
    print("use BANDRA-A..BANDRA-I, KURLA - 1..4, BHANDUP-E/W.\n")
