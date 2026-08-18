"""Canonical output layout and export-property construction."""

import os
from typing import Any, Dict

from dp_lookup.application.contracts import (
    NeighbourContext,
    OutputPaths,
    ParcelContext,
    PlanningContext,
    RoadContext,
)
from dp_lookup.core.models import ExportData
from dp_lookup.core.planning_status import bundle_folder_name, filesystem_identity_token


def build_output_paths(output_dir: str, parcel: ParcelContext) -> OutputPaths:
    """Derive every output from one canonical root and exact plot identity."""
    root = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(output_dir))))
    bundle = os.path.join(root, bundle_folder_name(parcel.village, parcel.cts_no))
    ward = str(parcel.attrs["WARD"]).replace("/", "-").replace("\\", "-")
    cts = filesystem_identity_token(parcel.cts_no)
    village = filesystem_identity_token(parcel.village, lower=True)
    stem = f"{ward}_{cts}_{village}"
    return OutputPaths(
        bundle_folder=bundle,
        register=os.path.join(root, "dp-lookups.xlsx"),
        pdf=os.path.join(bundle, f"dp_report_{stem}.pdf"),
        dp_map=os.path.join(bundle, f"plot_{stem}_hd.png"),
        satellite=os.path.join(bundle, f"plot_{stem}_satellite.png"),
        dxf=os.path.join(bundle, f"plot_{stem}.dxf"),
        geojson=os.path.join(bundle, f"plot_{stem}.geojson"),
        kml=os.path.join(bundle, f"plot_{stem}.kml"),
        html_map=os.path.join(bundle, f"plot_map_{stem}.html"),
    )


def build_map_link(parcel: ParcelContext) -> str:
    return (
        "https://mcgm.maps.arcgis.com/apps/webappviewer/index.html?"
        "id=67118c3502fd492e94680d10e77ec112"
        f"&marker={parcel.longitude},{parcel.latitude},4326,{parcel.cts_no}%20{parcel.village}"
        f"&center={parcel.longitude},{parcel.latitude}&level=19"
    )


def build_export_data(
    parcel: ParcelContext,
    planning: PlanningContext,
    road: RoadContext,
    neighbours: NeighbourContext,
    map_link: str,
) -> ExportData:
    return ExportData(
        village=parcel.village.upper(),
        cts_no=parcel.cts_no,
        ward=str(parcel.attrs["WARD"]),
        plot_type=str(parcel.attrs["TYPE"]),
        area_sqm=parcel.area_sqm,
        zone=planning.zone,
        status_badge=planning.status_badge,
        reservation_code=planning.reservation_code,
        reservation_type=planning.reservation_type,
        designation_description=planning.designation_description,
        modification_approval=planning.modification_approval,
        crz_status=planning.crz_status,
        metro_buffer=planning.metro_buffer,
        abutting_road=road.name,
        road_width=road.width,
        area_source=parcel.area_source,
        adjoining_plots_count=len(neighbours.plots),
        map_link=map_link,
        reservations=planning.reservations,
        designations=planning.designations,
        encumbered_area_sqm=planning.encumbered_area_sqm,
        encumbered_percent=planning.encumbered_percent,
        net_unencumbered_sqm=planning.net_unencumbered_sqm,
        net_unencumbered_percent=planning.net_unencumbered_percent,
    )


def build_export_properties(
    parcel: ParcelContext,
    planning: PlanningContext,
    road: RoadContext,
    neighbours: NeighbourContext,
    map_link: str,
) -> Dict[str, Any]:
    """Compatibility adapter for callers using the historical dictionary."""
    return build_export_data(parcel, planning, road, neighbours, map_link).to_legacy_dict()
