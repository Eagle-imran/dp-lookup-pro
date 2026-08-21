"""Topology and source-shape contracts for the ArcGIS planning adapter."""

from xml.etree import ElementTree as ET

import pytest

from dp_lookup.core.geometry import prepare_geometry
from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.exporters.geojson import export_geojson
from dp_lookup.exporters.kml import export_kml


def test_arcgis_rings_support_a_hole():
    shell = [[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]
    hole = [[5, 5], [5, 15], [15, 15], [15, 5], [5, 5]]

    geometry = arcgis_rings_to_geometry([shell, hole])

    assert geometry.geom_type == "Polygon"
    assert len(geometry.interiors) == 1
    assert geometry.area == pytest.approx(300.0)


def test_arcgis_rings_preserve_nested_island_topology():
    shell = [[0, 0], [30, 0], [30, 30], [0, 30], [0, 0]]
    hole = [[5, 5], [5, 25], [25, 25], [25, 5], [5, 5]]
    island = [[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]]

    geometry = arcgis_rings_to_geometry([island, shell, hole])

    assert geometry.geom_type == "MultiPolygon"
    assert geometry.area == pytest.approx(600.0)


def test_arcgis_rings_support_disjoint_multipart_parcels():
    first = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    second = [[20, 0], [25, 0], [25, 5], [20, 5], [20, 0]]

    geometry = arcgis_rings_to_geometry([first, second])

    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms) == 2
    assert geometry.area == pytest.approx(125.0)


def test_arcgis_rings_reject_degenerate_input_without_crashing():
    geometry = arcgis_rings_to_geometry([[[0, 0], [1, 1]]])
    assert geometry.is_empty


def test_geojson_preserves_multipart_geometry(tmp_path):
    first = [[72.8, 19.0], [72.81, 19.0], [72.81, 19.01], [72.8, 19.01], [72.8, 19.0]]
    second = [[72.82, 19.0], [72.83, 19.0], [72.83, 19.01], [72.82, 19.01], [72.82, 19.0]]
    path = tmp_path / "multipart.geojson"

    export_geojson([first, second], {"cts_no": "1", "village": "WORLI"}, str(path))

    import json

    geometry = json.loads(path.read_text())["features"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2


def test_kml_preserves_polygon_holes(tmp_path):
    shell = [[72.8, 19.0], [72.82, 19.0], [72.82, 19.02], [72.8, 19.02], [72.8, 19.0]]
    hole = [[72.805, 19.005], [72.805, 19.015], [72.815, 19.015], [72.815, 19.005], [72.805, 19.005]]
    path = tmp_path / "hole.kml"

    export_kml([shell, hole], {"cts_no": "1", "village": "WORLI"}, str(path))

    root = ET.parse(path).getroot()
    namespace = {"k": "http://www.opengis.net/kml/2.2"}
    assert root.find(".//k:innerBoundaryIs", namespace) is not None


def test_vector_exports_include_structured_area_assessment_without_legacy_approval_wording(tmp_path):
    ring = [[[72.8, 19.0], [72.81, 19.0], [72.81, 19.01], [72.8, 19.01], [72.8, 19.0]]]
    assessment = {
        "recorded_plot_area_sqm": 100.0,
        "calculated_boundary_area_sqm": 106.1,
        "selected_area_basis": "recorded_plot_area",
        "difference_sqm": 6.1,
        "difference_percent": 6.1,
        "reliability_status": "qualified_with_warnings",
        "reliability_label": "Qualified with warnings",
        "recorded_area_source": "MCGM cadastral parcel record",
        "geometry_source": "MCGM cadastral parcel boundary",
        "quality_flags": [{"code": "area_difference_over_5_percent", "severity": "warning"}],
        "source_snapshot_date": "2026-08-21T00:00:00+00:00",
    }
    properties = {
        "cts_no": "1",
        "village": "WORLI",
        "area_sqm": 100.0,
        "area_source": "approved (legacy input)",
        "area_assessment": assessment,
    }
    geojson_path = tmp_path / "area.geojson"
    kml_path = tmp_path / "area.kml"

    export_geojson(ring, properties, str(geojson_path))
    export_kml(ring, properties, str(kml_path))

    import json

    exported_properties = json.loads(geojson_path.read_text())["features"][0]["properties"]
    assert exported_properties["area_sqm"] == 100.0
    assert exported_properties["area_source"] == "Recorded plot area"
    assert exported_properties["area_assessment"] == assessment

    root = ET.parse(kml_path).getroot()
    namespace = {"k": "http://www.opengis.net/kml/2.2"}
    extended = {
        item.attrib["name"]: item.findtext("k:value", namespaces=namespace)
        for item in root.findall(".//k:ExtendedData/k:Data", namespace)
    }
    assert extended["Recorded_Plot_Area_sqm"] == "100.0"
    assert extended["Calculated_Boundary_Area_sqm"] == "106.1"
    assert extended["Area_Difference_Percent"] == "6.1"
    assert extended["Area_Reliability"] == "Qualified with warnings"
    assert extended["Area_Quality_Flags"] == "area_difference_over_5_percent"
    assert "approved" not in kml_path.read_text().casefold()


def test_prepare_geometry_uses_an_interior_point_for_concave_plot():
    concave = [
        [
            [0, 0],
            [10, 0],
            [10, 2],
            [2, 2],
            [2, 10],
            [0, 10],
            [0, 0],
        ]
    ]
    prepared = prepare_geometry(concave)
    geometry = arcgis_rings_to_geometry(concave)
    assert geometry.covers(geometry.representative_point())
    from shapely.geometry import Point

    assert geometry.covers(Point(prepared["cx"], prepared["cy"]))
