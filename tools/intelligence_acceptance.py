"""Verify a current intelligence build against local sources and public queries.

No source download or activation is performed. Use --require-active to also
exercise the default CLI against the published build. --allow-sample is for
checking the harness on a non-publishable sample.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import sys
import time
from contextlib import redirect_stdout
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dp_lookup.application.ingestion import build_parcel_context  # noqa: E402
from dp_lookup.application.intelligence_builder import _authority_registry_revision, _source_fingerprint  # noqa: E402
from dp_lookup.application.intelligence_services import PlotIntelligenceServices  # noqa: E402
from dp_lookup.application.normalization import PlanningEvidenceError, normalize_planning_evidence  # noqa: E402
from dp_lookup.cli import main as cli_main  # noqa: E402
from dp_lookup.cli_bootstrap import compose_lookup_runtime  # noqa: E402
from dp_lookup.clients.parcel_snapshot import sha256_json  # noqa: E402
from dp_lookup.core.constants import CRZ_LAYER_IDS  # noqa: E402
from dp_lookup.intelligence import IntelligenceStore, PlotIntelligence  # noqa: E402
from dp_lookup.intelligence.models import ALGORITHM_VERSION  # noqa: E402
from dp_lookup.planning_evidence.models import EvidenceMode  # noqa: E402
from dp_lookup.planning_snapshot import PlanningSnapshotStore  # noqa: E402
from dp_lookup.spatial_store import SnapshotStore  # noqa: E402

CONTROLS = (
    ("WORLI", "733"),
    ("WORLI", "983"),
    ("EKSAR", "1515A/1"),
    ("MULGAON", "8B"),
    ("MOGRA", "59"),
    ("MOGRA", "60"),
    ("MOGRA", "61"),
    ("MOGRA", "62"),
    ("GUNDAVALI", "343"),
    ("MOHILI", "638/3"),
    ("POISAR", "651"),
)


def _near(actual, expected, label, *, tolerance=0.02):
    assert math.isfinite(float(actual)) and math.isfinite(float(expected)), label
    assert abs(float(actual) - float(expected)) <= tolerance, (label, actual, expected)


def _cli(database, build_id, arguments, require_active):
    command = ["plots", *arguments, "--database", str(database), "--json"]
    if not require_active:
        command.extend(["--build-id", str(build_id)])
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli_main(command)
    assert code == 0, (command, output.getvalue())
    return json.loads(output.getvalue())


async def _parity(database, build_id, identities):
    service = PlotIntelligenceServices()
    results = []
    with compose_lookup_runtime("local", str(database), EvidenceMode.FULL) as runtime:
        deps = runtime.dependencies
        for village, cts_no in identities:
            dossier = service.analyze(database, village, cts_no, build_id=build_id)
            feature = await deps.parcel_fetcher(None, village, cts_no)
            assert feature is not None, (village, cts_no)
            parcel, _ = build_parcel_context(feature, village, cts_no)
            parcel = deps.authority_resolver(parcel)
            spatial = await deps.spatial_planning_query(None, parcel.rings)
            road = deps.road_provider(parcel)
            neighbours = deps.neighbour_provider(parcel)
            assert road is not None and neighbours is not None
            identity = dossier["plot_identity"]
            planning = dossier["planning"]
            _near(identity["area_sqm"], parcel.area_sqm, "selected area")
            assert identity["area_assessment"] == parcel.area_assessment.to_dict()
            assert planning["primary_zone"] == spatial["primary_zone"]
            expected_no_zoning = False
            try:
                normal = normalize_planning_evidence(spatial, None, parcel.area_sqm, parcel.wgs_rings, CRZ_LAYER_IDS)
            except PlanningEvidenceError:
                assert spatial["primary_zone"] == "Unknown"
                assert dossier["quality"]["confidence"] == "review_required"
                expected_no_zoning = True
            else:
                assert planning["primary_zone"] == normal.zone
                _near(planning["encumbered_percent"], normal.encumbered_percent, "overlap percentage")
                _near(planning["encumbered_area_sqm"], normal.encumbered_area_sqm, "affected selected area")
                _near(planning["net_unencumbered_sqm"], normal.net_unencumbered_sqm, "remaining selected area")
                for key in ("reservations", "designations", "modifications"):
                    items = getattr(normal, key)
                    assert len(planning[key]) == len(items), (village, cts_no, key)
                    for actual, expected in zip(planning[key], items, strict=True):
                        assert actual["overlap_percent"] == expected["overlap_percent"]
                assert planning["crz_status"] == normal.crz_status
                assert planning["metro_buffer"] == normal.metro_buffer
            assert dossier["access"] == {
                "road_name": road.name,
                "road_width": road.width,
                "distance_m": road.distance_m,
            }
            assert dossier["adjacency"]["neighbours"] == neighbours.plots
            road_refs = [ref for ref in dossier["provenance"]["source_refs"] if ref["evidence_type"] == "road_access"]
            expected_refs = (
                []
                if road.selected_source_object_id is None
                else [(road.selected_source_layer_id, road.selected_source_object_id)]
            )
            assert [(ref["layer_id"], ref["object_id"]) for ref in road_refs] == expected_refs
            report = await deps.planning_evidence_analyzer(None, parcel.rings, village, EvidenceMode.FULL)
            assert dossier["evidence_summary"]["complete"] == report.complete
            assert dossier["evidence_summary"]["queried_layer_count"] == len(report.outcomes)
            results.append(
                {"village": village, "cts_no": cts_no, "ok": True, "missing_zoning_handled": expected_no_zoning}
            )
    return results


def audit(database, build_id, sample_size, *, allow_sample=False, require_active=False):
    started = time.perf_counter()
    service = PlotIntelligenceServices()
    with (
        IntelligenceStore.open(database) as store,
        SnapshotStore.open(database) as parcels,
        PlanningSnapshotStore.open(database) as planning,
    ):
        selected = build_id if build_id is not None else store.active_build_id()
        assert selected is not None, "no selected or active intelligence build"
        build = store.build(selected)
        assert build.state in {"ready", "active"}
        assert allow_sample or build.scope == "full"
        assert build.algorithm_version == ALGORITHM_VERSION
        assert build.parcel_snapshot_id == parcels.active_snapshot_id()
        assert build.planning_snapshot_id == planning.active_snapshot_id()
        assert build.source_fingerprint == _source_fingerprint(
            build.parcel_snapshot_id,
            parcels.snapshot_metadata(build.parcel_snapshot_id),
            build.planning_snapshot_id,
            planning.snapshot(build.planning_snapshot_id).content_hash,
            _authority_registry_revision(database),
        )
        verification = store.verify(selected)
        assert verification["ok"], verification
        connection = store.connection
        if build.scope == "full":
            for first, second in (
                (
                    "SELECT village,cts_no FROM parcels WHERE snapshot_id=? AND village IS NOT NULL AND village<>'' AND cts_no IS NOT NULL AND cts_no<>'' GROUP BY village,cts_no",
                    "SELECT village,cts_no FROM plot_intelligence WHERE build_id=?",
                ),
                (
                    "SELECT village,cts_no FROM plot_intelligence WHERE build_id=?",
                    "SELECT village,cts_no FROM parcels WHERE snapshot_id=? AND village IS NOT NULL AND village<>'' AND cts_no IS NOT NULL AND cts_no<>'' GROUP BY village,cts_no",
                ),
            ):
                params = (
                    (build.parcel_snapshot_id, selected)
                    if first.startswith("SELECT village,cts_no FROM parcels")
                    else (selected, build.parcel_snapshot_id)
                )
                assert not connection.execute(f"{first} EXCEPT {second} LIMIT 1", params).fetchall()
        missing_refs = connection.execute(
            "SELECT r.village,r.cts_no,r.evidence_type,r.layer_id,r.object_id FROM plot_evidence_refs r "
            "LEFT JOIN parcels p ON p.snapshot_id=? AND p.objectid=r.object_id AND r.evidence_type='cadastral' "
            "LEFT JOIN planning_features f ON f.snapshot_id=? AND f.canonical_layer_id=r.layer_id "
            "AND f.object_id=r.object_id AND r.evidence_type<>'cadastral' "
            "WHERE r.build_id=? AND p.objectid IS NULL AND f.object_id IS NULL LIMIT 10",
            (build.parcel_snapshot_id, build.planning_snapshot_id, selected),
        ).fetchall()
        assert not missing_refs, missing_refs
        hash_count = 0
        for row in connection.execute("SELECT * FROM plot_intelligence WHERE build_id=?", (selected,)):
            record = IntelligenceStore._plot(row)
            attrs = {
                (ref["evidence_type"], ref["layer_id"], ref["object_id"]): json.loads(ref["attributes_json"])
                for ref in connection.execute(
                    "SELECT evidence_type,layer_id,object_id,attributes_json FROM plot_evidence_refs "
                    "WHERE build_id=? AND village=? AND cts_no=?",
                    (selected, record["village"], record["cts_no"]),
                )
            }
            record["source_refs"] = [
                {**ref, "attributes": attrs[(ref["evidence_type"], ref["layer_id"], ref["object_id"])]}
                for ref in record["source_refs"]
            ]
            plot = PlotIntelligence(**{item.name: record[item.name] for item in fields(PlotIntelligence)})
            facts = plot.to_dict()
            facts["quality"].pop("facts_hash")
            facts["quality"].pop("calculated_at")
            assert sha256_json(facts) == record["facts_hash"], (record["village"], record["cts_no"], "facts hash")
            hash_count += 1
        keys = store.completed_keys(selected)
        assert len(keys) >= 2, "acceptance comparison needs two distinct plots"
        chosen = {keys[round(index * (len(keys) - 1) / max(1, sample_size - 1))] for index in range(sample_size)}
        chosen.update(identity for identity in CONTROLS if identity in set(keys))
        confidence = dict(
            connection.execute(
                "SELECT confidence,COUNT(*) FROM plot_intelligence WHERE build_id=? GROUP BY confidence", (selected,)
            ).fetchall()
        )
    parity = asyncio.run(_parity(database, selected, sorted(chosen)))
    first = keys[0]
    search = _cli(
        database, selected, ["search", "--village", first[0], "--min-area", "0", "--limit", "20"], require_active
    )
    assert search["count"] > 0 and search["build_id"] == selected
    assert all(row["village"] == first[0] for row in search["results"])
    empty = _cli(database, selected, ["search", "--village", "__NO_SUCH_VILLAGE__"], require_active)
    assert empty["count"] == 0
    compare_ids = [first, keys[-1]]
    comparison = _cli(
        database, selected, ["compare", *(f"{village}:{cts}" for village, cts in compare_ids)], require_active
    )
    assert comparison["missing"] == [] and len(comparison["records"]) == 2
    assert comparison["build_id"] == selected
    readiness = service.check(database)
    if require_active:
        assert readiness["active_intelligence_build_id"] == selected
        assert readiness["ready_for_operational_use"], readiness
    return {
        "ok": True,
        "build_id": selected,
        "scope": build.scope,
        "algorithm": build.algorithm_version,
        "parcel_snapshot_id": build.parcel_snapshot_id,
        "planning_snapshot_id": build.planning_snapshot_id,
        "source_fingerprint": build.source_fingerprint,
        "verification": verification,
        "facts_hashes_recomputed": hash_count,
        "missing_source_refs": 0,
        "confidence_counts": confidence,
        "parity_cases": parity,
        "public_cli_search_count": search["count"],
        "public_cli_comparison_count": len(comparison["records"]),
        "readiness": readiness,
        "network_requests": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "area_basis_note": "Plot totals use the selected recorded/calculated area; source-overlap areas retain their digitized boundary basis.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--build-id", type=int)
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--allow-sample", action="store_true")
    parser.add_argument("--require-active", action="store_true")
    parser.add_argument("--json-report", type=Path, required=True)
    args = parser.parse_args()
    if args.sample_size < 2:
        parser.error("--sample-size must be at least 2")
    result = audit(
        args.database,
        args.build_id,
        args.sample_size,
        allow_sample=args.allow_sample,
        require_active=args.require_active,
    )
    args.json_report.write_text(json.dumps(result, indent=2))
    print(
        json.dumps({key: value for key, value in result.items() if key not in {"parity_cases", "readiness"}}, indent=2)
    )


if __name__ == "__main__":
    main()
