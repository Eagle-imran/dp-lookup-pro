"""Construction of the stable public lookup result from typed stage outputs."""

import time
from typing import Any, Dict, List, Mapping, Optional

from dp_lookup.application.contracts import NeighbourContext, OutputPaths, ParcelContext, PlanningContext, RoadContext
from dp_lookup.core.constants import APPLICATION_VERSION, RESULT_SCHEMA_VERSION
from dp_lookup.core.models import (
    ArtifactManifest,
    EvidenceState,
    LookupResult,
    PlanningRemarks,
    PlotIdentity,
    RegulatoryInfrastructure,
    RunMetadata,
    SourceEvidence,
    SpatialCluster,
)


def build_lookup_result(
    parcel: ParcelContext,
    planning: PlanningContext,
    road: RoadContext,
    neighbours: NeighbourContext,
    paths: OutputPaths,
    map_link: str,
    execution_time_ms: float,
    documents_pending: bool,
    warnings: List[str],
    notes: List[str],
    diagnostics: Optional[Mapping[str, Any]] = None,
    additional_artifacts: Optional[Mapping[str, str]] = None,
    planning_due_diligence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Serialize typed stage contracts to the backwards-compatible wire shape."""
    evidence = dict(planning.evidence)
    parcel_warning_items: list[str] = []
    if parcel.attrs.get("_DP_SNAPSHOT_STALE"):
        parcel_warning_items.append(
            f"Local parcel snapshot is {parcel.attrs.get('_DP_SNAPSHOT_AGE_DAYS')} days old; verify against live Layer 13."
        )
    fallback_reason = parcel.attrs.get("_DP_LOCAL_FALLBACK_REASON")
    if fallback_reason:
        parcel_warning_items.append(f"Local database was not used: {fallback_reason}")
    parcel_warnings = tuple(parcel_warning_items)
    if planning_due_diligence is not None:
        evidence["planning_due_diligence"] = dict(planning_due_diligence)
    evidence.update(
        {
            "parcel": SourceEvidence(
                value={
                    "village": parcel.village.upper(),
                    "cts_no": parcel.cts_no,
                    **(
                        {"snapshot_id": parcel.attrs.get("_DP_SNAPSHOT_ID")}
                        if parcel.attrs.get("_DP_SNAPSHOT_ID") is not None
                        else {}
                    ),
                    **(
                        {
                            "feature_part_count": parcel.attrs.get("FEATURE_PART_COUNT"),
                            "source_objectids": parcel.attrs.get("SOURCE_OBJECTIDS"),
                        }
                        if parcel.attrs.get("FEATURE_PART_COUNT") is not None
                        else {}
                    ),
                },
                state=EvidenceState.CONFIRMED,
                source="MCGM Development Plan 2034",
                method=(
                    "local_snapshot_attribute_query"
                    if parcel.attrs.get("_DP_PARCEL_SOURCE") == "local_snapshot"
                    else "attribute_query"
                ),
                layer_ids=(13,),
                retrieved_at=(
                    str(parcel.attrs.get("_DP_SNAPSHOT_FINALIZED_AT_ISO"))
                    if parcel.attrs.get("_DP_SNAPSHOT_FINALIZED_AT_ISO") is not None
                    else None
                ),
                warnings=parcel_warnings,
            ).to_dict(),
            "abutting_road": SourceEvidence(
                value={
                    "name": road.name,
                    "width": road.width,
                    **({"distance_m": road.distance_m} if road.distance_m is not None else {}),
                    **({"snapshot_id": road.snapshot_id} if road.snapshot_id is not None else {}),
                    **(
                        {"source_object_ids": list(road.source_object_ids)}
                        if road.source_object_ids
                        else {}
                    ),
                },
                state=EvidenceState(road.evidence_state),
                source="MCGM Development Plan 2034",
                method=road.method,
                layer_ids=tuple(road.source_layer_ids) or (193, 194, 44, 45, 2224),
                warnings=tuple(road.warnings),
            ).to_dict(),
            "adjoining_plots": SourceEvidence(
                value=len(neighbours.plots),
                state=EvidenceState(neighbours.evidence_state),
                source="MCGM Development Plan 2034",
                method=neighbours.method,
                layer_ids=(13,),
                warnings=tuple(neighbours.warnings),
            ).to_dict(),
        }
    )
    result = LookupResult(
        plot_identity=PlotIdentity(
            village=parcel.village.upper(),
            cts_no=parcel.cts_no,
            ward=str(parcel.attrs["WARD"]),
            plot_type=str(parcel.attrs["TYPE"]),
            area_sqm=parcel.area_sqm,
            area_source=parcel.area_source,
            latitude=parcel.latitude,
            longitude=parcel.longitude,
        ),
        planning_remarks=PlanningRemarks(
            status_badge=planning.status_badge,
            status_summary=planning.status_summary,
            zone=planning.zone,
            zones=planning.zones,
            reservations=planning.reservations,
            designations=planning.designations,
            modifications=planning.modifications,
            encumbered_area_sqm=planning.encumbered_area_sqm,
            encumbered_percent=planning.encumbered_percent,
            net_unencumbered_sqm=planning.net_unencumbered_sqm,
            net_unencumbered_percent=planning.net_unencumbered_percent,
        ),
        regulatory_and_infrastructure=RegulatoryInfrastructure(
            crz_status=planning.crz_status,
            metro_buffer=planning.metro_buffer,
            road_name=road.name,
            road_width=road.width,
        ),
        spatial_cluster=SpatialCluster(neighbours=neighbours.plots, method=neighbours.method),
        export_files=ArtifactManifest(
            bundle_folder=paths.bundle_folder,
            pdf_report=paths.pdf,
            hd_dp_map=paths.dp_map,
            satellite_view=paths.satellite,
            autocad_dxf=paths.dxf,
            autocad_geojson=paths.geojson,
            google_earth_kml=paths.kml,
            interactive_html_map=paths.html_map,
            master_excel_register=paths.register,
            additional_files=additional_artifacts or {},
        ),
        metadata=RunMetadata(
            source="MCGM SDP 2014-34",
            lookup_datetime=time.strftime("%Y-%m-%d %H:%M:%S"),
            execution_time_ms=execution_time_ms,
            complete=not warnings,
            documents_pending=documents_pending,
            warnings=warnings,
            notes=notes,
            interactive_web_map=map_link,
            application_version=APPLICATION_VERSION,
            result_schema_version=RESULT_SCHEMA_VERSION,
            evidence=evidence,
            diagnostics=diagnostics or {},
        ),
    )
    return result.to_dict()
