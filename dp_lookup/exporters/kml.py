"""
Google Earth KML 3D Exporter.
"""

from typing import Any, List, Mapping
from xml.sax.saxutils import escape as xml_escape

from shapely.geometry import MultiPolygon, Polygon

from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.exporters.contracts import ExportPayload, legacy_export_properties


def _esc(val: Any) -> str:
    """XML-escape a value so it cannot break KML parsing."""
    if val is None:
        return ""
    return xml_escape(str(val))


def _coordinates(coords) -> str:
    return " ".join(f"{x},{y},0" for x, y in coords)


def _assessment_value(assessment: Mapping[str, Any], key: str) -> Any:
    value = assessment.get(key)
    return "" if value is None else value


def _public_area_source(properties: Mapping[str, Any], assessment: Mapping[str, Any]) -> Any:
    basis = assessment.get("selected_area_basis")
    if basis == "recorded_plot_area":
        return "Recorded plot area"
    if basis == "calculated_boundary_area":
        return "Calculated boundary area"
    source = properties.get("area_source")
    if "approved" in str(source or "").casefold():
        return "Recorded plot area"
    return source


def _quality_flag_codes(assessment: Mapping[str, Any]) -> str:
    flags = assessment.get("quality_flags")
    if not isinstance(flags, list):
        return ""
    return "; ".join(str(flag.get("code")) for flag in flags if isinstance(flag, Mapping) and flag.get("code"))


def _polygon_xml(polygon: Polygon) -> str:
    inner = "".join(
        "<innerBoundaryIs><LinearRing><coordinates>"
        f"{_coordinates(ring.coords)}"
        "</coordinates></LinearRing></innerBoundaryIs>"
        for ring in polygon.interiors
    )
    return (
        "<Polygon><extrude>1</extrude><altitudeMode>clampToGround</altitudeMode>"
        "<outerBoundaryIs><LinearRing><coordinates>"
        f"{_coordinates(polygon.exterior.coords)}"
        "</coordinates></LinearRing></outerBoundaryIs>"
        f"{inner}</Polygon>"
    )


def _geometry_xml(wgs_rings: List[List[List[float]]]) -> str:
    geometry = arcgis_rings_to_geometry(wgs_rings)
    if isinstance(geometry, Polygon):
        return _polygon_xml(geometry)
    if isinstance(geometry, MultiPolygon):
        return "<MultiGeometry>" + "".join(_polygon_xml(part) for part in geometry.geoms) + "</MultiGeometry>"
    return ""


def export_kml(
    wgs_rings: List[List[List[float]]],
    properties: ExportPayload,
    output_path: str,
) -> None:
    """
    Export the parcel boundary to Google Earth 3D KML format.
    Every interpolated value is XML-escaped to prevent malformed KML.
    """
    properties = legacy_export_properties(properties)
    raw_assessment = properties.get("area_assessment")
    area_assessment = dict(raw_assessment) if isinstance(raw_assessment, Mapping) else {}
    raw_authority = properties.get("authority_resolution")
    authority = dict(raw_authority) if isinstance(raw_authority, Mapping) else {}
    authority_record_ids = ",".join(str(value) for value in authority.get("active_record_ids", []))
    geometry_xml = _geometry_xml(wgs_rings)

    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>CTS {_esc(properties.get("cts_no"))} ({_esc(properties.get("village"))}) DP Remark</name>
    <description>MCGM DP 2034 Spatial Polygon Export</description>
    <Style id="plotStyle">
      <LineStyle>
        <color>ff00e6ff</color>
        <width>4</width>
      </LineStyle>
      <PolyStyle>
        <color>4000e6ff</color>
      </PolyStyle>
    </Style>
    <Placemark>
      <name>CTS {_esc(properties.get("cts_no"))} - {_esc(properties.get("village"))}</name>
      <styleUrl>#plotStyle</styleUrl>
      <ExtendedData>
        <Data name="Ward"><value>{_esc(properties.get("ward"))}</value></Data>
        <Data name="Zone"><value>{_esc(properties.get("zone"))}</value></Data>
        <Data name="Area_sqm"><value>{_esc(properties.get("area_sqm"))}</value></Data>
        <Data name="Area_Source"><value>{_esc(_public_area_source(properties, area_assessment))}</value></Data>
        <Data name="Recorded_Plot_Area_sqm"><value>{_esc(_assessment_value(area_assessment, "recorded_plot_area_sqm"))}</value></Data>
        <Data name="Calculated_Boundary_Area_sqm"><value>{_esc(_assessment_value(area_assessment, "calculated_boundary_area_sqm"))}</value></Data>
        <Data name="Area_Difference_sqm"><value>{_esc(_assessment_value(area_assessment, "difference_sqm"))}</value></Data>
        <Data name="Area_Difference_Percent"><value>{_esc(_assessment_value(area_assessment, "difference_percent"))}</value></Data>
        <Data name="Area_Reliability"><value>{_esc(_assessment_value(area_assessment, "reliability_label"))}</value></Data>
        <Data name="Geometry_Source"><value>{_esc(_assessment_value(area_assessment, "geometry_source"))}</value></Data>
        <Data name="Area_Quality_Flags"><value>{_esc(_quality_flag_codes(area_assessment))}</value></Data>
        <Data name="Source_Snapshot_Date"><value>{_esc(_assessment_value(area_assessment, "source_snapshot_date"))}</value></Data>
        <Data name="Authority_Status"><value>{_esc(authority.get("status"))}</value></Data>
        <Data name="Authority_Policy"><value>{_esc(authority.get("policy_version"))}</value></Data>
        <Data name="Authority_Record_IDs"><value>{_esc(authority_record_ids)}</value></Data>
        <Data name="Status"><value>{_esc(properties.get("status_badge"))}</value></Data>
        <Data name="CRZ_Status"><value>{_esc(properties.get("crz_buffer_flag"))}</value></Data>
        <Data name="Metro_Buffer"><value>{_esc(properties.get("metro_buffer_flag"))}</value></Data>
        <Data name="Abutting_Road"><value>{_esc(properties.get("abutting_road"))} ({_esc(properties.get("road_width"))})</value></Data>
        <Data name="Encumbered_Area_sqm"><value>{_esc(properties.get("encumbered_area_sqm", 0.0))}</value></Data>
        <Data name="Encumbered_Percent"><value>{_esc(properties.get("encumbered_percent", 0.0))}%</value></Data>
        <Data name="Net_Developable_sqm"><value>{_esc(properties.get("net_unencumbered_sqm", 0.0))}</value></Data>
      </ExtendedData>
      {geometry_xml}
    </Placemark>
  </Document>
</kml>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(kml_content)
