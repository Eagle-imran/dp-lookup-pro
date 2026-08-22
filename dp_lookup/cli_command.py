"""Lookup command runner, independent from parsing and adapter composition."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Callable, Coroutine, Mapping

from dp_lookup.application.lookup_service import lookup_plot_pro
from dp_lookup.cli_bootstrap import LookupRuntime, compose_lookup_runtime, local_snapshot_selection
from dp_lookup.cli_parser import EXIT_ERROR, EXIT_INCOMPLETE, EXIT_SUCCESS, USAGE
from dp_lookup.cli_presentation import format_result_human
from dp_lookup.clients.validation import sanitize_query_value
from dp_lookup.core.constants import _CTS_RE, _VILLAGE_RE
from dp_lookup.planning_evidence.models import EvidenceMode

LookupCallable = Callable[..., Coroutine[Any, Any, dict[str, Any]]]
RuntimeFactory = Callable[..., LookupRuntime]


def execute_lookup(
    parsed: Mapping[str, Any],
    *,
    lookup: LookupCallable = lookup_plot_pro,
    runtime_factory: RuntimeFactory = compose_lookup_runtime,
    snapshot_selector: Callable[[str, str], tuple[str, int | None]] = local_snapshot_selection,
    usage: str = USAGE,
) -> int:
    """Execute one parsed lookup and emit the historical terminal contract."""
    args = list(parsed["positionals"])
    # Tolerate the conversational form: ``WORLI CTS 947``.
    if len(args) >= 3 and args[1].upper() in ("CTS", "CS", "PLOT", "NO", "NO."):
        args = [args[0], args[2], *args[3:]]
    if len(args) < 2:
        print(usage)
        return EXIT_ERROR
    if len(args) > 3:
        print("  Error: too many positional arguments")
        print(usage)
        return EXIT_ERROR

    as_json = bool(parsed["as_json"])
    use_cache = bool(parsed["use_cache"])
    evidence_mode = parsed["evidence_mode"]
    source_mode = str(parsed["source_mode"])
    database_path = parsed.get("database_path")
    village, cts_number = args[0], args[1]
    output_dir = args[2] if len(args) > 2 else "./output"
    try:
        safe_village = sanitize_query_value(village, _VILLAGE_RE, "village", 64)
        safe_cts = sanitize_query_value(cts_number, _CTS_RE, "cts_number", 32)
    except ValueError as exc:
        print(f"  Error: {exc}")
        return EXIT_ERROR

    if not as_json:
        suffix = f" [{evidence_mode.value} evidence]" if evidence_mode is not EvidenceMode.BASIC else ""
        print(f"  Looking up {safe_village} CTS {safe_cts}{' (fresh)' if not use_cache else ''}{suffix}...")

    shown = {"done": False}

    def show_early(snapshot: dict[str, Any]) -> None:
        if as_json or shown["done"]:
            return
        shown["done"] = True
        print(format_result_human(snapshot))
        if not snapshot.get("metadata", {}).get("cached_result"):
            print("  Building PDF, maps and CAD files...", flush=True)

    lookup_started = time.perf_counter()
    runtime = runtime_factory(
        source_mode,
        database_path,
        evidence_mode,
        snapshot_selector=snapshot_selector,
    )
    try:
        result: dict[str, Any] = asyncio.run(
            lookup(
                village=safe_village,
                cts_number=safe_cts,
                output_dir=output_dir,
                use_cache=use_cache,
                on_data=None if as_json else show_early,
                dependencies=runtime.dependencies,
            )
        )
    finally:
        runtime.close()
    lookup_elapsed_ms = (time.perf_counter() - lookup_started) * 1000

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif "error" in result:
        if not shown["done"]:
            print(format_result_human(result))
    elif result.get("metadata", {}).get("cached_result"):
        if not shown["done"]:
            print(format_result_human(result))
        print(f"  Cache retrieval: {lookup_elapsed_ms:.1f} ms.")
        print()
    elif not result.get("metadata", {}).get("complete", True):
        print(format_result_human(result))
    elif shown["done"]:
        meta = result.get("metadata", {})
        files = result.get("export_files") or {}
        bundle_f_count = len(
            [path for key, path in files.items() if key not in ("bundle_folder", "master_excel_register") and path and os.path.exists(path)]
        )
        print(f"  Done in {meta.get('execution_time_ms', 0) / 1000:.1f}s - all {bundle_f_count} files written.")
        for warning in meta.get("warnings") or []:
            print(f"  Warning: {warning}")
        print()
    else:
        print(format_result_human(result))
    if "error" in result:
        return EXIT_ERROR
    if not result.get("metadata", {}).get("complete", True):
        return EXIT_INCOMPLETE
    return EXIT_SUCCESS
