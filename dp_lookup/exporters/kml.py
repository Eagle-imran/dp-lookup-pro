"""
Google Earth KML 3D Exporter.
"""
from typing import Any, Dict, List
from xml.sax.saxutils import escape as xml_escape


def _esc(val: Any) -> str:
    """XML-escape a value so it cannot break KML parsing."""
    if val is None:
        return ""
    return xml_escape(str(val))


def export_kml(
    wgs_rings: List[List[List[float]]],
    properties: Dict[str, Any],
    output_path: str,
) -> None:
    """
    Export the parcel boundary to Google Earth 3D KML format.
    Every interpolated value is XML-escaped to prevent malformed KML.
    """
    ring0 = wgs_rings[0]
    coords_str = " ".join(f"{p[0]},{p[1]},0" for p in ring0)

    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>CTS {_esc(properties.get('cts_no'))} ({_esc(properties.get('village'))}) DP Remark</name>
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
      <name>CTS {_esc(properties.get('cts_no'))} - {_esc(properties.get('village'))}</name>
      <styleUrl>#plotStyle</styleUrl>
      <ExtendedData>
        <Data name="Ward"><value>{_esc(properties.get('ward'))}</value></Data>
        <Data name="Zone"><value>{_esc(properties.get('zone'))}</value></Data>
        <Data name="Area_sqm"><value>{_esc(properties.get('area_sqm'))}</value></Data>
        <Data name="Status"><value>{_esc(properties.get('status_badge'))}</value></Data>
        <Data name="CRZ_Status"><value>{_esc(properties.get('crz_buffer_flag'))}</value></Data>
        <Data name="Metro_Buffer"><value>{_esc(properties.get('metro_buffer_flag'))}</value></Data>
        <Data name="Abutting_Road"><value>{_esc(properties.get('abutting_road'))} ({_esc(properties.get('road_width'))})</value></Data>
        <Data name="Encumbered_Area_sqm"><value>{_esc(properties.get('encumbered_area_sqm', 0.0))}</value></Data>
        <Data name="Encumbered_Percent"><value>{_esc(properties.get('encumbered_percent', 0.0))}%</value></Data>
        <Data name="Net_Developable_sqm"><value>{_esc(properties.get('net_unencumbered_sqm', 0.0))}</value></Data>
      </ExtendedData>
      <Polygon>
        <extrude>1</extrude>
        <altitudeMode>clampToGround</altitudeMode>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coords_str}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(kml_content)
