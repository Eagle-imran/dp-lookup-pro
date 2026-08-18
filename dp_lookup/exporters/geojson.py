"""
GeoJSON Vector File Exporter with Multi-Layer Sub-Features.
"""
import json
from typing import Any, Dict, List


def export_geojson(
    wgs_rings: List[List[List[float]]],
    properties: Dict[str, Any],
    output_path: str,
) -> None:
    """
    Export the parcel as a fully featured GeoJSON FeatureCollection.
    Includes the primary plot boundary and any overlapping PLU Reservation / Designation sub-features.
    """
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": wgs_rings,
            },
            "properties": {
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
                "area_source": properties.get("area_source"),
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
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": res["wgs_rings"],
                },
                "properties": {
                    "feature_type": "PLU_RESERVATION",
                    "code": res.get("code"),
                    "type": res.get("type"),
                    "description": res.get("description"),
                    "u_r_id": res.get("u_r_id"),
                    "overlap_sqm": res.get("overlap_sqm"),
                    "overlap_percent": res.get("overlap_percent"),
                },
            })

    for des in properties.get("designations", []):
        if "wgs_rings" in des:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": des["wgs_rings"],
                },
                "properties": {
                    "feature_type": "PLU_DESIGNATION",
                    "code": des.get("code"),
                    "type": des.get("type"),
                    "description": des.get("description"),
                    "u_d_id": des.get("u_d_id"),
                    "overlap_sqm": des.get("overlap_sqm"),
                    "overlap_percent": des.get("overlap_percent"),
                },
            })

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
