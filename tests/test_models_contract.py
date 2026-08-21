"""Contracts for the typed internal result model and legacy serialization."""

from dp_lookup.core.area_assessment import assess_plot_area
from dp_lookup.core.models import (
    ArtifactManifest,
    ExportData,
    LookupResult,
    PlanningRemarks,
    PlotIdentity,
    RegulatoryInfrastructure,
    RunMetadata,
    SpatialCluster,
)
from dp_lookup.exporters.contracts import legacy_export_properties


def test_typed_export_data_reaches_renderer_adapter_without_mutable_leaks():
    reservations = [{"code": "ROS1.5"}]
    payload = ExportData(
        village="WORLI",
        cts_no="733",
        ward="G/S",
        plot_type="CTS",
        area_sqm=100.0,
        zone="R",
        status_badge="CLEAR",
        reservation_code="ROS1.5",
        reservation_type="Garden",
        designation_description="None",
        modification_approval="None",
        crz_status="NO",
        metro_buffer="NO",
        abutting_road="Road",
        road_width="18.30 M",
        area_source="approved",
        adjoining_plots_count=2,
        map_link="https://example.invalid",
        reservations=reservations,
        designations=[],
        encumbered_area_sqm=25.0,
        encumbered_percent=25.0,
        net_unencumbered_sqm=75.0,
        net_unencumbered_percent=75.0,
    )

    adapted = legacy_export_properties(payload)
    adapted["reservations"][0]["code"] = "changed"

    assert payload.reservations[0]["code"] == "ROS1.5"
    assert adapted["type"] == "CTS"


def test_typed_result_serializes_to_the_existing_public_shape():
    result = LookupResult(
        plot_identity=PlotIdentity("WORLI", "733", "G/S", "CTS", 100.0, "approved", 19.0, 72.8),
        planning_remarks=PlanningRemarks(
            "CLEAR",
            "Unreserved",
            "R",
            [{"zone": "R"}],
            [],
            [],
            [],
            0.0,
            0.0,
            100.0,
            100.0,
        ),
        regulatory_and_infrastructure=RegulatoryInfrastructure("NO", "NO", "Road", "18.30 M"),
        spatial_cluster=SpatialCluster([], method="probe"),
        export_files=ArtifactManifest(
            "bundle", "a.pdf", "a.png", "s.png", "a.dxf", "a.geojson", "a.kml", "a.html", "a.xlsx"
        ),
        metadata=RunMetadata(
            "MCGM SDP 2014-34",
            "2026-08-18 12:00:00",
            100.0,
            True,
            False,
            [],
            [],
            "https://example.invalid",
            "3.14.0",
            1,
        ),
    ).to_dict()

    assert set(result) == {
        "plot_identity",
        "planning_remarks",
        "regulatory_and_infrastructure",
        "spatial_cluster",
        "export_files",
        "metadata",
    }
    assert result["plot_identity"]["type"] == "CTS"
    assert result["planning_remarks"]["reservation"] == {"code": "None", "type": "None"}
    assert result["metadata"]["cached_result"] is False
    assert result["metadata"]["result_schema_version"] == 1


def test_typed_result_preserves_legacy_singular_planning_fields():
    remarks = PlanningRemarks(
        "RESERVED",
        "Reserved",
        "R",
        [],
        [{"code": "ROS1.5", "type": "Garden", "description": "Garden"}],
        [{"code": "EOS", "description": "Existing open space"}],
        [{"approval_no": "MO-1", "details": "Modified", "document_link": "doc"}],
        50.0,
        50.0,
        50.0,
        50.0,
    ).to_dict()

    assert remarks["reservation"]["code"] == "ROS1.5"
    assert remarks["designation"]["code"] == "EOS"
    assert remarks["dp_modification"]["approval_no"] == "MO-1"


def test_area_assessment_is_additive_to_legacy_result_and_export_shapes():
    rings = [
        [
            [8_106_500.0, 2_151_700.0],
            [8_106_510.0, 2_151_700.0],
            [8_106_510.0, 2_151_710.0],
            [8_106_500.0, 2_151_710.0],
            [8_106_500.0, 2_151_700.0],
        ]
    ]
    assessment = assess_plot_area(
        {"OBJECTID": 1, "VILLAGE": "WORLI", "CTS_CS_NO": "733", "AREA_APP_SQ_MTRS": 100.0},
        rings,
    )
    identity = PlotIdentity(
        "WORLI",
        "733",
        "G/S",
        "CTS",
        100.0,
        "Recorded plot area",
        19.0,
        72.8,
        assessment,
    ).to_dict()

    assert identity["area_sqm"] == 100.0
    assert identity["area_source"] == "Recorded plot area"
    assert identity["area_assessment"]["recorded_plot_area_sqm"] == 100.0
