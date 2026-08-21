"""
GeoJSON Vector File Exporter with Multi-Layer Sub-Features.
"""

import json
from typing import Any, List, Mapping

from dp_lookup.core.topology import rings_to_geojson_geometry
from dp_lookup.exporters.contracts import ExportPayload, legacy_export_properties


def _public_area_source(properties: Mapping[str, Any], assessment: Mapping[str, Any]) -> Any:
    """Return an intuitive source label while retaining the legacy key."""
    basis = assessment.get("selected_area_basis")
    if basis == "recorded_plot_area":
        return "Recorded plot area"
    if basis == "calculated_boundary_area":
        return "Calculated boundary area"
    source = properties.get("area_source")
    source_text = str(source or "")
    if "approved" in source_text.casefold():
        return "Recorded plot area"
    return source


def export_geojson(
    wgs_rings: List[List[List[float]]],
    properties: ExportPayload,
    output_path: str,
) -> None:
    """
    Export the parcel as a fully featured GeoJSON FeatureCollection.
    Includes the primary plot boundary and any overlapping PLU Reservation / Designation sub-features.
    """
    properties = legacy_export_properties(properties)
    raw_assessment = properties.get("area_assessment")
    area_assessment = dict(raw_assessment) if isinstance(raw_assessment, Mapping) else {}
    features = [
        {
            "type": "Feature",
            "geometry": rings_to_geojson_geometry(wgs_rings),
            "properties": {
                "feature_type": "BASE_PLOT",
                "village": properties.get("village"),
                "cts_no": properties.get("cts_no"),
                "ward": properties.get("ward"),
                "type": properties.get("type"),
                "area_sqm": properties.get("area_sqm"),
                "zone": properties.get("zone"),
                "status": properties.get("status_badge"),
                "reservation_code": properties.get("reservation_code"),
                "reservation_type": properties.get("reservation_type"),
                "designation_description": properties.get("designation_description"),
                "modification_approval": properties.get("modification_approval"),
                "crz_status": properties.get("crz_buffer_flag"),
                "metro_buffer": properties.get("metro_buffer_flag"),
                "abutting_road": properties.get("abutting_road"),
                "road_width": properties.get("road_width"),
                "area_source": _public_area_source(properties, area_assessment),
                "area_assessment": area_assessment or None,
                "authority_resolution": properties.get("authority_resolution"),
                "adjoining_cts_plots_count": properties.get("adjoining_cts_plots_count"),
                "encumbered_area_sqm": properties.get("encumbered_area_sqm", 0.0),
                "encumbered_percent": properties.get("encumbered_percent", 0.0),
                "net_unencumbered_sqm": properties.get("net_unencumbered_sqm", 0.0),
                "map_link": properties.get("map_link"),
            },
        }
    ]

    for res in properties.get("reservations", []):
        if "wgs_rings" in res:
            features.append(
                {
                    "type": "Feature",
                    "geometry": rings_to_geojson_geometry(res["wgs_rings"]),
                    "properties": {
                        "feature_type": "PLU_RESERVATION",
                        "code": res.get("code"),
                        "type": res.get("type"),
                        "description": res.get("description"),
                        "u_r_id": res.get("u_r_id"),
                        "overlap_sqm": res.get("overlap_sqm"),
                        "overlap_percent": res.get("overlap_percent"),
                    },
                }
            )

    for des in properties.get("designations", []):
        if "wgs_rings" in des:
            features.append(
                {
                    "type": "Feature",
                    "geometry": rings_to_geojson_geometry(des["wgs_rings"]),
                    "properties": {
                        "feature_type": "PLU_DESIGNATION",
                        "code": des.get("code"),
                        "type": des.get("type"),
                        "description": des.get("description"),
                        "u_d_id": des.get("u_d_id"),
                        "overlap_sqm": des.get("overlap_sqm"),
                        "overlap_percent": des.get("overlap_percent"),
                    },
                }
            )

    geojson_data = {
        "type": "FeatureCollection",
        "name": f"CTS_{properties.get('cts_no')}_{properties.get('village')}",
        "crs": {
            "type": "name",
            "properties": {
                "name": "urn:ogc:def:crs:OGC:1.3:CRS84",
            },
        },
        "features": features,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, indent=2)
