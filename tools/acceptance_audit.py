"""Run a repeatable local-versus-live CTS acceptance audit.

The audit is intentionally read-only with respect to the database. It compares
the active parcel/planning snapshots with current MCGM ArcGIS responses, then
runs the normal implicit ``auto`` pipeline and opens every generated artifact.

Usage:
    uv run python tools/acceptance_audit.py \
        --database data/mcgm-layer13.sqlite \
        --output-dir /tmp/dp-lookup-acceptance-2026-08-23 \
        --sample-size 20 --seed 20260823

The final JSON document is written to stdout. Progress is written to stderr.
Exit code 1 means at least one acceptance case failed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

import ezdxf  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from PIL import Image  # noqa: E402

from dp_lookup.application.ingestion import build_parcel_context  # noqa: E402
from dp_lookup.application.lookup_service import lookup_plot_pro  # noqa: E402
from dp_lookup.cli_bootstrap import compose_lookup_runtime  # noqa: E402
from dp_lookup.clients.arcgis_models import decode_arcgis_response  # noqa: E402
from dp_lookup.clients.local_parcels import merge_local_features  # noqa: E402
from dp_lookup.clients.local_planning import LocalFirstPlanningQuery  # noqa: E402
from dp_lookup.clients.planning_queries import query_spatial_planning_layers  # noqa: E402
from dp_lookup.clients.transport import create_arcgis_client  # noqa: E402
from dp_lookup.core.constants import MCGM_VILLAGES, SERVER_URL  # noqa: E402
from dp_lookup.planning_evidence.models import EvidenceMode  # noqa: E402
from dp_lookup.planning_snapshot import PlanningSnapshotStore  # noqa: E402
from dp_lookup.spatial_store import SnapshotStore  # noqa: E402

DEFAULT_CHANGE_CONTROLS = (
    ("MOGRA", "59"),
    ("MOGRA", "60"),
    ("MOGRA", "61"),
    ("MOGRA", "62"),
    ("MOGRA", "63"),
)
DEFAULT_CONSTRAINT_CONTROLS = (
    ("MALABAR HILL", "518"),
    ("BYCULLA", "1605"),
    ("WORLI", "733"),
)
EXPECTED_ARTIFACTS = (
    "pdf_report",
    "hd_dp_map",
    "satellite_view",
    "autocad_dxf",
    "autocad_geojson",
    "google_earth_kml",
    "interactive_html_map",
    "master_excel_register",
)
SAFE_CTS = re.compile(r"^[A-Za-z0-9()/. -]+$")


@dataclass(frozen=True)
class AuditCase:
    village: str
    cts_no: str
    ward: str
    part_count: int
    selection: str


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _positive_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _same_optional_number(left: Any, right: Any, tolerance: float = 0.01) -> bool:
    left_number = _positive_float(left)
    right_number = _positive_float(right)
    if left_number is None or right_number is None:
        return left_number is right_number
    return abs(left_number - right_number) <= tolerance


def _active_snapshot_ids(database: Path) -> tuple[int, int]:
    with SnapshotStore.open(database) as parcel_store:
        parcel_id = parcel_store.active_snapshot_id()
    with PlanningSnapshotStore.open(database) as planning_store:
        planning_id = planning_store.active_snapshot_id()
    if parcel_id is None or planning_id is None:
        raise RuntimeError("both parcel and planning snapshots must be active")
    return int(parcel_id), int(planning_id)


def _candidate_cases(database: Path, snapshot_id: int) -> List[AuditCase]:
    with sqlite3.connect(str(database)) as connection:
        rows = connection.execute(
            """SELECT village, cts_no, COALESCE(ward, ''), COUNT(*)
               FROM parcels
               WHERE snapshot_id=? AND village IS NOT NULL AND village<>''
                 AND cts_no IS NOT NULL AND cts_no<>'' AND geometry_json IS NOT NULL
               GROUP BY village, cts_no, ward
               ORDER BY village, cts_no""",
            (snapshot_id,),
        ).fetchall()
    valid_villages = set(MCGM_VILLAGES)
    return [
        AuditCase(str(village), str(cts_no), str(ward), int(parts), "candidate")
        for village, cts_no, ward, parts in rows
        if str(village) in valid_villages and SAFE_CTS.fullmatch(str(cts_no))
    ]


def select_cases(database: Path, snapshot_id: int, sample_size: int, seed: int) -> List[AuditCase]:
    """Select five changed-area controls plus seeded random single/multipart CTS cases."""
    if not 15 <= sample_size <= 25:
        raise ValueError("sample-size must be between 15 and 25")
    candidates = _candidate_cases(database, snapshot_id)
    by_identity = {(case.village, case.cts_no): case for case in candidates}
    selected: List[AuditCase] = []
    for identities, selection in (
        (DEFAULT_CHANGE_CONTROLS, "change_control"),
        (DEFAULT_CONSTRAINT_CONTROLS, "constraint_control"),
    ):
        for identity in identities:
            case = by_identity.get(identity)
            if case is not None and len(selected) < sample_size:
                selected.append(AuditCase(case.village, case.cts_no, case.ward, case.part_count, selection))

    random_count = sample_size - len(selected)
    multipart_target = min(2, random_count)
    rng = random.Random(seed)
    excluded = {(case.village, case.cts_no) for case in selected}
    multipart = [
        case
        for case in candidates
        if 2 <= case.part_count <= 10 and (case.village, case.cts_no) not in excluded
    ]
    rng.shuffle(multipart)
    for case in multipart:
        if len([item for item in selected if item.selection == "seeded_multipart"]) >= multipart_target:
            break
        if case.village in {item.village for item in selected if "control" not in item.selection}:
            continue
        selected.append(AuditCase(case.village, case.cts_no, case.ward, case.part_count, "seeded_multipart"))
        excluded.add((case.village, case.cts_no))

    singles = [case for case in candidates if case.part_count == 1 and (case.village, case.cts_no) not in excluded]
    rng.shuffle(singles)
    random_villages = {item.village for item in selected if "control" not in item.selection}
    for case in singles:
        if len(selected) >= sample_size:
            break
        if case.village in random_villages:
            continue
        selected.append(AuditCase(case.village, case.cts_no, case.ward, case.part_count, "seeded_random"))
        random_villages.add(case.village)
        excluded.add((case.village, case.cts_no))

    if len(selected) != sample_size:
        raise RuntimeError(f"could select only {len(selected)} of {sample_size} requested cases")
    return selected


def _local_rows(store: SnapshotStore, case: AuditCase, snapshot_id: int) -> List[Dict[str, Any]]:
    rows = store.lookup(case.village, case.cts_no, snapshot_id=snapshot_id)
    if not rows:
        raise RuntimeError("identity missing from active local parcel snapshot")
    return rows


async def _live_rows(client: Any, case: AuditCase) -> List[Dict[str, Any]]:
    response = await client.get(
        f"{SERVER_URL}/13/query",
        params={
            "where": f"VILLAGE='{case.village}' AND CTS_CS_NO='{case.cts_no}'",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "102100",
            "orderByFields": "OBJECTID ASC",
            "f": "json",
        },
    )
    payload = decode_arcgis_response(response)
    if payload is None or not payload.features_valid:
        raise RuntimeError("live Layer 13 returned invalid or error JSON")
    rows = []
    for feature in payload.features:
        attrs = dict(feature.attributes)
        object_id = attrs.get("OBJECTID")
        if object_id is None:
            raise RuntimeError("live Layer 13 feature has no OBJECTID")
        rows.append(
            {
                "objectid": int(object_id),
                "raw_attrs": attrs,
                "geometry": dict(feature.geometry),
                "area_app_sqm": attrs.get("AREA_APP_SQ_MTRS"),
            }
        )
    if not rows:
        raise RuntimeError("identity missing from live Layer 13")
    return rows


def _geometry_by_objectid(rows: Iterable[Mapping[str, Any]]) -> Dict[int, str]:
    result: Dict[int, str] = {}
    for row in rows:
        geometry = row.get("geometry")
        rings = geometry.get("rings") if isinstance(geometry, Mapping) else row.get("rings")
        result[int(row["objectid"])] = _json_hash(rings)
    return result


def _identity_values(rows: Iterable[Mapping[str, Any]]) -> set[tuple[str, str]]:
    values = set()
    for row in rows:
        attrs = row.get("raw_attrs")
        if not isinstance(attrs, Mapping):
            attrs = row.get("attributes") if isinstance(row.get("attributes"), Mapping) else {}
        values.add((str(attrs.get("VILLAGE") or "").strip(), str(attrs.get("CTS_CS_NO") or "").strip()))
    return values


def _strip_planning_noise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_planning_noise(item)
            for key, item in value.items()
            if key not in {"provenance", "warnings", "raw_attributes", "wgs_rings"}
        }
    if isinstance(value, list):
        normalized = [_strip_planning_noise(item) for item in value]
        if all(isinstance(item, Mapping) for item in normalized):
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return normalized
    return value


async def _live_planning_with_retry(client: Any, rings: List[Any], attempts: int = 3) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        result = await query_spatial_planning_layers(client, rings)
        if not result.get("warnings"):
            return result
        if attempt < attempts:
            await asyncio.sleep(float(attempt))
    return result


def _validate_artifacts(result: Mapping[str, Any], output_root: Path) -> Dict[str, int]:
    export_files = result.get("export_files")
    if not isinstance(export_files, Mapping):
        raise RuntimeError("lookup result has no export_files mapping")
    sizes: Dict[str, int] = {}
    root = output_root.resolve()
    paths: Dict[str, Path] = {}
    for key in EXPECTED_ARTIFACTS:
        raw_path = export_files.get(key)
        if not raw_path:
            raise RuntimeError(f"lookup result omitted {key}")
        path = Path(str(raw_path)).resolve()
        if root not in path.parents and path != root:
            raise RuntimeError(f"artifact escaped audit output root: {path}")
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"artifact is missing or empty: {key}")
        paths[key] = path
        sizes[key] = path.stat().st_size

    pdf = paths["pdf_report"].read_bytes()
    if not pdf.startswith(b"%PDF") or b"%%EOF" not in pdf[-2048:]:
        raise RuntimeError("PDF signature or EOF marker is invalid")
    for image_key in ("hd_dp_map", "satellite_view"):
        with Image.open(paths[image_key]) as image:
            image.verify()
    ezdxf.readfile(paths["autocad_dxf"])
    geojson = json.loads(paths["autocad_geojson"].read_text(encoding="utf-8"))
    if geojson.get("type") != "FeatureCollection" or not geojson.get("features"):
        raise RuntimeError("GeoJSON is not a populated FeatureCollection")
    ET.parse(paths["google_earth_kml"])
    html = paths["interactive_html_map"].read_text(encoding="utf-8")
    if "<!DOCTYPE html>" not in html or "leaflet" not in html.casefold():
        raise RuntimeError("HTML dossier is missing its document or map contract")
    workbook = load_workbook(paths["master_excel_register"], read_only=True, data_only=True)
    try:
        if not workbook.sheetnames:
            raise RuntimeError("Excel register has no worksheets")
    finally:
        workbook.close()
    return sizes


async def _run_output_acceptance(
    case: AuditCase,
    database: Path,
    output_root: Path,
    *,
    expect_fail_closed: bool = False,
) -> Dict[str, Any]:
    case_root = output_root / f"{case.village.lower().replace(' ', '-')}_{case.cts_no.replace('/', '-') }"
    with compose_lookup_runtime("auto", str(database), EvidenceMode.BASIC) as runtime:
        started = time.perf_counter()
        result = await lookup_plot_pro(
            case.village,
            case.cts_no,
            str(case_root),
            use_cache=False,
            timeout_seconds=30.0,
            dependencies=runtime.dependencies,
        )
    if expect_fail_closed:
        error = str(result.get("error") or "")
        if "no usable zoning evidence" not in error.casefold():
            raise RuntimeError(f"missing-zoning case did not fail closed as expected: {error or 'lookup succeeded'}")
        generated = [
            path
            for path in case_root.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".pdf", ".png", ".dxf", ".geojson", ".kml", ".html"}
        ]
        if generated:
            raise RuntimeError(f"fail-closed lookup generated prohibited artifacts: {generated}")
        return {
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "expected_fail_closed": True,
            "reason": "live and local Layer 0 returned no usable zoning",
            "artifact_count": 0,
            "shared_register_valid": False,
            "artifact_sizes": {},
        }
    if "error" in result:
        raise RuntimeError(f"auto lookup failed: {result['error']}")
    metadata = result.get("metadata") or {}
    if not metadata.get("complete") or metadata.get("warnings"):
        raise RuntimeError(f"auto lookup was incomplete: {metadata.get('warnings')}")
    evidence = metadata.get("evidence") or {}
    parcel_method = (evidence.get("parcel") or {}).get("method")
    zoning_method = (evidence.get("zoning") or {}).get("method")
    if parcel_method != "local_snapshot_attribute_query":
        raise RuntimeError(f"parcel source was not local: {parcel_method}")
    if zoning_method != "local_snapshot_spatial_query":
        raise RuntimeError(f"planning source was not local: {zoning_method}")
    notes = [str(note) for note in metadata.get("notes") or []]
    if any("database was not used" in note.casefold() or "live layer 13 was used" in note.casefold() for note in notes):
        raise RuntimeError(f"unexpected live fallback note: {notes}")
    sizes = _validate_artifacts(result, output_root)
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "parcel_method": parcel_method,
        "planning_method": zoning_method,
        "artifact_count": 7,
        "shared_register_valid": True,
        "artifact_sizes": sizes,
    }


async def audit_case(
    case: AuditCase,
    *,
    database: Path,
    parcel_store: SnapshotStore,
    parcel_snapshot_id: int,
    planning_query: LocalFirstPlanningQuery,
    client: Any,
    output_root: Path,
) -> Dict[str, Any]:
    started = time.perf_counter()
    local_rows = _local_rows(parcel_store, case, parcel_snapshot_id)
    live_rows = await _live_rows(client, case)
    local_ids = sorted(int(row["objectid"]) for row in local_rows)
    live_ids = sorted(int(row["objectid"]) for row in live_rows)
    expected_identity = {(case.village, case.cts_no)}
    local_geometry = _geometry_by_objectid(local_rows)
    live_geometry = _geometry_by_objectid(live_rows)
    local_feature = merge_local_features(local_rows)
    live_feature = merge_local_features(live_rows)
    if local_feature is None or live_feature is None:
        raise RuntimeError("parcel parts could not be merged")
    local_parcel, _ = build_parcel_context(local_feature, case.village, case.cts_no)
    live_parcel, _ = build_parcel_context(live_feature, case.village, case.cts_no)
    local_assessment = local_parcel.area_assessment
    live_assessment = live_parcel.area_assessment
    if local_assessment is None or live_assessment is None:
        raise RuntimeError("area assessment was not produced")

    local_planning = await planning_query(client, local_parcel.rings)
    live_planning = await _live_planning_with_retry(client, local_parcel.rings)
    planning_local_clean = _strip_planning_noise(local_planning)
    planning_live_clean = _strip_planning_noise(live_planning)
    checks = {
        "identity": _identity_values(local_rows) == expected_identity
        and _identity_values(live_rows) == expected_identity,
        "objectids": local_ids == live_ids,
        "geometry_checksum": local_geometry == live_geometry,
        "recorded_area": _same_optional_number(
            local_assessment.recorded_area_sqm,
            live_assessment.recorded_area_sqm,
        ),
        "calculated_area": _same_optional_number(
            local_assessment.calculated_boundary_area_sqm,
            live_assessment.calculated_boundary_area_sqm,
        ),
        "zoning": local_planning.get("primary_zone") == live_planning.get("primary_zone")
        and local_planning.get("zones") == live_planning.get("zones"),
        "constraints": planning_local_clean == planning_live_clean,
    }
    expect_fail_closed = str(local_planning.get("primary_zone") or "").casefold() in {"", "unknown", "none"}
    output = await _run_output_acceptance(
        case,
        database,
        output_root,
        expect_fail_closed=expect_fail_closed,
    )
    checks["outputs"] = (
        bool(output.get("expected_fail_closed"))
        if expect_fail_closed
        else output["artifact_count"] == 7 and output["shared_register_valid"]
    )
    return {
        **asdict(case),
        "passed": all(checks.values()),
        "checks": checks,
        "objectids": local_ids,
        "geometry_sha256": _json_hash(local_geometry),
        "recorded_area_sqm": local_assessment.recorded_area_sqm,
        "calculated_boundary_area_sqm": local_assessment.calculated_boundary_area_sqm,
        "primary_zone": local_planning.get("primary_zone"),
        "expected_outcome": "fail_closed_missing_zoning" if expect_fail_closed else "complete_bundle",
        "constraint_counts": {
            "reservations": len(local_planning.get("reservations") or []),
            "designations": len(local_planning.get("designations") or []),
            "modifications": len(local_planning.get("modifications") or []),
            "crz": len(local_planning.get("crz_categories") or []),
            "metro": 1 if str(local_planning.get("metro_buffer", "NO")).startswith("YES") else 0,
        },
        "output": output,
        "audit_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
    }


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    database = Path(args.database).expanduser().resolve()
    output_root = Path(args.output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    parcel_snapshot_id, planning_snapshot_id = _active_snapshot_ids(database)
    cases = select_cases(database, parcel_snapshot_id, args.sample_size, args.seed)
    results: List[Dict[str, Any]] = []
    started = time.perf_counter()
    with SnapshotStore.open(database) as parcel_store, PlanningSnapshotStore.open(database) as planning_store:
        planning_query = LocalFirstPlanningQuery(planning_store, mode="local", allow_stale_local=True)
        async with create_arcgis_client(args.timeout) as client:
            for index, case in enumerate(cases, 1):
                print(
                    f"[{index:02d}/{len(cases)}] {case.village} CTS {case.cts_no} "
                    f"({case.selection}, {case.part_count} part(s))",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    result = await audit_case(
                        case,
                        database=database,
                        parcel_store=parcel_store,
                        parcel_snapshot_id=parcel_snapshot_id,
                        planning_query=planning_query,
                        client=client,
                        output_root=output_root,
                    )
                except Exception as exc:
                    result = {**asdict(case), "passed": False, "error": f"{type(exc).__name__}: {exc}"}
                results.append(result)
                print("  PASS" if result["passed"] else f"  FAIL: {result.get('error') or result.get('checks')}", file=sys.stderr, flush=True)
                if args.delay > 0 and index < len(cases):
                    await asyncio.sleep(args.delay)
    passed = sum(1 for result in results if result["passed"])
    return {
        "audit_schema": "local-live-acceptance/1.0",
        "database": str(database),
        "parcel_snapshot_id": parcel_snapshot_id,
        "planning_snapshot_id": planning_snapshot_id,
        "seed": args.seed,
        "sample_size": len(cases),
        "selection": {
            "change_controls": sum(case.selection == "change_control" for case in cases),
            "constraint_controls": sum(case.selection == "constraint_control" for case in cases),
            "seeded_random": sum(case.selection == "seeded_random" for case in cases),
            "seeded_multipart": sum(case.selection == "seeded_multipart" for case in cases),
        },
        "passed": passed,
        "failed": len(cases) - passed,
        "overall_pass": passed == len(cases),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "results": results,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/mcgm-layer13.sqlite")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--json-report", help="optional path for the complete indented JSON evidence")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"overall_pass": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    if args.json_report:
        report_path = Path(args.json_report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
