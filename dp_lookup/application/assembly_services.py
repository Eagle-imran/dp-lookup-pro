"""Local adapters for the opt-in experimental plot-assembly extension.

The deterministic geometry policy lives in :mod:`dp_lookup.experimental.assemblies`.
This module is the composition boundary that reads immutable local snapshots,
queries the combined site against the active planning snapshot, and writes a
small experimental hand-off bundle.  Normal lookup and ArcGIS ingestion do not
import this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from dp_lookup.clients.local_parcels import merge_local_features
from dp_lookup.clients.local_planning import LocalFirstPlanningQuery
from dp_lookup.clients.local_planning import PlanningSnapshotStore as PlanningSnapshotReader
from dp_lookup.core.geometry import mercator_to_wgs84
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.experimental.assemblies import ParcelAssemblyInput, analyze_plot_assembly
from dp_lookup.exporters.dxf import export_dxf
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.kml import export_kml
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore

Identity = Tuple[str, str]
ASSEMBLY_SCHEMA = "experimental-plot-assembly/0.1"
DISCLAIMER = (
    "Experimental feasibility screening only. This result does not establish title, ownership, access, "
    "a certified boundary, or legal/municipal amalgamation approval."
)


def _public(value: Any) -> Any:
    """Convert immutable assembly models into a stable JSON-compatible value."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _public(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public(item) for item in value]
    return value


def _positive_area(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _geometry_rings(geometry: BaseGeometry) -> List[List[List[float]]]:
    """Encode a Polygon/MultiPolygon as lossless ArcGIS-style rings."""
    polygons: Sequence[Polygon]
    if isinstance(geometry, Polygon):
        polygons = (geometry,)
    elif isinstance(geometry, MultiPolygon):
        polygons = tuple(geometry.geoms)
    else:
        raise ValueError("assembly union did not produce polygon geometry")
    rings: List[List[List[float]]] = []
    for polygon in polygons:
        rings.append([[float(x), float(y)] for x, y in polygon.exterior.coords])
        rings.extend([[float(x), float(y)] for x, y in interior.coords] for interior in polygon.interiors)
    return rings


def _wgs_rings(rings: Sequence[Sequence[Sequence[float]]]) -> List[List[List[float]]]:
    return [[mercator_to_wgs84(float(point[0]), float(point[1]), precision=10) for point in ring] for ring in rings]


def _geometry_sha256(rings: Sequence[Sequence[Sequence[float]]]) -> str:
    payload = json.dumps(rings, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_feature(
    store: SnapshotStore,
    snapshot_id: int,
    identity: Identity,
) -> tuple[ParcelAssemblyInput, List[List[List[float]]], Dict[str, Any]]:
    village, cts_no = identity
    rows = store.lookup(village, cts_no, snapshot_id=snapshot_id)
    if not rows:
        raise ValueError(f"{village} CTS {cts_no} is absent from active parcel snapshot {snapshot_id}")
    merged = merge_local_features(rows)
    if merged is None:
        raise ValueError(f"{village} CTS {cts_no} has no usable parcel feature")
    raw_geometry = merged.get("geometry")
    rings_value = raw_geometry.get("rings") if isinstance(raw_geometry, Mapping) else None
    if not isinstance(rings_value, list) or not rings_value:
        raise ValueError(f"{village} CTS {cts_no} has no usable polygon rings")
    rings = [[[float(point[0]), float(point[1])] for point in ring] for ring in rings_value]
    attrs_value = merged.get("attributes")
    attrs = dict(attrs_value) if isinstance(attrs_value, Mapping) else {}
    objectids_value = attrs.get("SOURCE_OBJECTIDS")
    if isinstance(objectids_value, (list, tuple)):
        objectids = [int(value) for value in objectids_value]
    else:
        objectid_value = attrs.get("OBJECTID")
        if objectid_value is None:
            raise ValueError(f"{village} CTS {cts_no} has no source ObjectID")
        objectids = [int(objectid_value)]
    parcel = ParcelAssemblyInput(
        village=village,
        cts_no=cts_no,
        objectids=objectids,
        raw_arcgis_rings=rings,
        recorded_area_sqm=_positive_area(attrs.get("AREA_APP_SQ_MTRS")),
        ward=str(attrs.get("WARD") or rows[0].get("ward") or "") or None,
    )
    member = {
        "village": village,
        "cts_no": cts_no,
        "ward": parcel.ward,
        "source_objectids": list(parcel.objectids),
        "source_feature_count": len(rows),
        "recorded_area_sqm": parcel.recorded_area_sqm,
        "geometry_sha256": _geometry_sha256(rings),
    }
    return parcel, rings, member


def _snapshot_provenance(store: SnapshotStore, snapshot_id: int) -> Dict[str, Any]:
    status = store.status(snapshot_id)
    snapshot = status.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    metadata = snapshot.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return {
        "database": str(store.path),
        "parcel_snapshot_id": snapshot_id,
        "parcel_snapshot_finalized_at": snapshot.get("finalized_at"),
        "parcel_snapshot_content_hash": metadata.get("content_hash"),
        "parcel_record_count": status.get("count"),
    }


def _planning_result(database: Path, combined_rings: List[List[List[float]]]) -> Dict[str, Any]:
    """Run the existing deterministic planning policy against the union."""
    with PlanningSnapshotStore.open(database) as store:
        query = LocalFirstPlanningQuery(
            cast(PlanningSnapshotReader, store),
            mode="local",
            allow_stale_local=True,
        )
        return dict(asyncio.run(query(None, combined_rings)))


def _export_properties(
    identities: Sequence[Identity],
    analysis: Mapping[str, Any],
    planning: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    recorded = analysis.get("gross_recorded_area_sqm")
    calculated_value = analysis.get("calculated_combined_boundary_area_sqm")
    if not isinstance(calculated_value, (int, float)):
        raise ValueError("assembly analysis has no calculated combined boundary area")
    calculated = float(calculated_value)
    recorded_number = _positive_area(recorded)
    villages = sorted({village for village, _cts in identities})
    cts_numbers = [cts for _village, cts in identities]
    return {
        "village": " + ".join(villages),
        "cts_no": " + ".join(cts_numbers),
        "ward": "Multiple" if len(villages) > 1 else "Assembly",
        "type": "EXPERIMENTAL PLOT ASSEMBLY",
        "area_sqm": calculated,
        "area_source": "Calculated combined boundary area",
        "zone": planning.get("primary_zone", "Unknown"),
        "status_badge": f"EXPERIMENTAL · {analysis.get('suitability_status')}",
        "reservation_code": "See assembly analysis",
        "reservation_type": "Combined planning intersection",
        "designation_description": "See assembly analysis",
        "modification_approval": "See assembly analysis",
        "crz_buffer_flag": planning.get("crz_status"),
        "metro_buffer_flag": planning.get("metro_buffer"),
        "abutting_road": "Not analysed by assembly extension",
        "road_width": "N/A",
        "adjoining_cts_plots_count": len(identities),
        "encumbered_area_sqm": planning.get("encumbered_area_sqm", 0.0),
        "encumbered_percent": planning.get("encumbered_percent", 0.0),
        "net_unencumbered_sqm": planning.get("net_unencumbered_sqm", calculated),
        "reservations": planning.get("reservations", []),
        "designations": planning.get("designations", []),
        "area_assessment": {
            "recorded_plot_area_sqm": recorded,
            "calculated_boundary_area_sqm": calculated,
            "selected_area_basis": "calculated_boundary_area",
            "difference_sqm": None if recorded_number is None else round(calculated - recorded_number, 2),
            "difference_percent": (
                None
                if recorded_number is None
                else round(abs(calculated - recorded_number) / recorded_number * 100.0, 2)
            ),
            "reliability_label": "Experimental screening",
            "geometry_source": "Active local MCGM cadastral parcel snapshot",
            "source_snapshot_date": provenance.get("parcel_snapshot_finalized_at"),
            "quality_flags": analysis.get("warnings", []),
        },
    }


def _append_member_features(
    path: Path,
    members: Sequence[Mapping[str, Any]],
    member_rings: Sequence[Sequence[Sequence[Sequence[float]]]],
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("assembly GeoJSON exporter returned no feature list")
    for member, rings in zip(members, member_rings, strict=False):
        geometry = mapping(arcgis_rings_to_geometry(_wgs_rings(rings)))
        features.append(
            {
                "type": "Feature",
                "geometry": _public(geometry),
                "properties": {"feature_type": "SOURCE_PLOT", **dict(member)},
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned or "plot"


def _output_directory(output: Optional[Path], identities: Sequence[Identity]) -> Path:
    if output is not None:
        return Path(output)
    village, cts = identities[0]
    return Path("output") / "experimental-assemblies" / f"{_slug(village)}-{_slug(cts)}-plus-{len(identities) - 1}"


def _write_outputs(
    directory: Path,
    result: Dict[str, Any],
    identities: Sequence[Identity],
    combined_rings: List[List[List[float]]],
    member_rings: Sequence[Sequence[Sequence[Sequence[float]]]],
) -> Dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    wgs_union = _wgs_rings(combined_rings)
    properties = _export_properties(identities, result["geometry"], result["planning"], result["source"])
    wards = sorted({str(member.get("ward")) for member in result["members"] if member.get("ward")})
    properties["ward"] = " + ".join(wards) if wards else "Unknown"
    geojson_path = directory / "assembly-boundary.geojson"
    kml_path = directory / "assembly-boundary.kml"
    dxf_path = directory / "assembly-boundary.dxf"
    json_path = directory / "assembly-analysis.json"
    export_geojson(wgs_union, properties, str(geojson_path))
    _append_member_features(geojson_path, result["members"], member_rings)
    export_kml(wgs_union, properties, str(kml_path))
    export_dxf(
        wgs_union,
        properties,
        str(dxf_path),
        neighbors=[
            {
                "village": member.get("village"),
                "cts_no": member.get("cts_no"),
                "rings": _wgs_rings(rings),
            }
            for member, rings in zip(result["members"], member_rings, strict=False)
        ],
        reservations=list(result["planning"].get("reservations", [])),
        designations=list(result["planning"].get("designations", [])),
    )
    outputs = {
        "analysis_json": str(json_path.resolve()),
        "assembly_geojson": str(geojson_path.resolve()),
        "assembly_kml": str(kml_path.resolve()),
        "assembly_dxf": str(dxf_path.resolve()),
    }
    result["outputs"] = outputs
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return outputs


class LocalAssemblyServices:
    """Read active local snapshots and execute the isolated assembly extension."""

    def analyze(
        self,
        database: Path,
        identities: Sequence[Identity],
        output: Optional[Path],
        gap_tolerance_m: float,
    ) -> Mapping[str, Any]:
        database = Path(database)
        if not database.is_file():
            raise ValueError(f"local assembly database does not exist: {database}")
        normalized = tuple((str(village).strip().upper(), str(cts).strip().upper()) for village, cts in identities)
        if len(normalized) < 2:
            raise ValueError("plot assembly analysis requires at least two CTS identities")

        parcels: List[ParcelAssemblyInput] = []
        member_rings: List[List[List[List[float]]]] = []
        members: List[Dict[str, Any]] = []
        with SnapshotStore.open(database) as store:
            snapshot_id = store.active_snapshot_id()
            if snapshot_id is None:
                raise ValueError("local assembly database has no active parcel snapshot")
            for identity in normalized:
                parcel, rings, member = _source_feature(store, snapshot_id, identity)
                parcels.append(parcel)
                member_rings.append(rings)
                members.append(member)
            provenance = _snapshot_provenance(store, snapshot_id)

        analysis = analyze_plot_assembly(parcels, gap_tolerance_m=gap_tolerance_m)
        geometry_result = _public(analysis)
        web_geometries = [arcgis_rings_to_geometry(rings) for rings in member_rings]
        combined_web = unary_union(web_geometries)
        combined_rings = _geometry_rings(combined_web)
        runtime_warnings: List[Dict[str, str]] = []
        try:
            planning = _planning_result(database, combined_rings)
        except Exception as exc:
            planning = {"status": "unavailable", "error": str(exc), "primary_zone": "Unknown"}
            runtime_warnings.append(
                {
                    "code": "planning_analysis_unavailable",
                    "severity": "warning",
                    "message": f"Combined local planning analysis was unavailable: {exc}",
                }
            )

        warnings = list(geometry_result.get("warnings", [])) + runtime_warnings
        result: Dict[str, Any] = {
            "schema_version": ASSEMBLY_SCHEMA,
            "experimental": True,
            "authority_status": "screening",
            "disclaimer": DISCLAIMER,
            "status": geometry_result["suitability_status"],
            "assembly_status": geometry_result["suitability_status"],
            "part_count": len(parcels),
            "contiguous": geometry_result["is_strictly_connected"],
            "connected_within_tolerance": geometry_result["is_connected_within_tolerance"],
            "combined_area_sqm": geometry_result["calculated_combined_boundary_area_sqm"],
            "gap_count": sum(
                1 for relation in geometry_result["pairwise_relations"] if relation["relation"] == "tolerance_gap"
            ),
            "overlap_count": sum(
                1 for relation in geometry_result["pairwise_relations"] if relation["relation"] == "overlap"
            ),
            "source": provenance,
            "members": members,
            "geometry": geometry_result,
            "planning": planning,
            "warnings": warnings,
            "outputs": {},
        }
        _write_outputs(
            _output_directory(output, normalized),
            result,
            normalized,
            combined_rings,
            member_rings,
        )
        return result


__all__ = ["ASSEMBLY_SCHEMA", "DISCLAIMER", "LocalAssemblyServices"]
