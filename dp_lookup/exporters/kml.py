"""
Google Earth KML 3D Exporter.
"""

from typing import Any, List
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
