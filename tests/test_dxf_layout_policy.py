"""Focused contracts for the configurable DXF layout policy."""

import math
import random
from dataclasses import FrozenInstanceError

import ezdxf
import pytest
from ezdxf.lldxf.const import BOUNDARY_PATH_EXTERNAL, BOUNDARY_PATH_OUTERMOST

from dp_lookup.core.topology import arcgis_rings_to_geometry
from dp_lookup.exporters.dxf import (
    DEFAULT_DXF_LAYOUT_POLICY,
    DxfLayoutPolicy,
    boxes_overlap,
    export_dxf,
    legend_data_rows,
    text_extents,
)


def _properties() -> dict:
    return {
        "cts_no": "IRREGULAR/TEST",
        "village": "POLICY VILLAGE",
        "ward": "K/E",
        "zone": "WEST",
        "area_sqm": 1000,
        "area_source": "MCGM record",
        "abutting_road": "A very long road name for wrapping",
        "road_width": "12m",
        "crz_buffer_flag": "NO",
        "metro_buffer_flag": "NO",
    }


def _irregular_ring(seed: int, count: int = 240) -> list[list[float]]:
    rng = random.Random(seed)
    center_lon, center_lat = 72.83, 19.07
    ring = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        radius = 0.00035 * (1.0 + 0.20 * math.sin(13 * angle) + rng.uniform(-0.025, 0.025))
        ring.append([center_lon + radius * math.cos(angle), center_lat + radius * math.sin(angle)])
    ring.append(ring[0][:])
    return ring


def _assert_valid_dxf(path) -> ezdxf.document.Drawing:
    assert path.exists()
    assert path.stat().st_size > 0
    doc = ezdxf.readfile(path)
    assert len(list(doc.modelspace())) > 0
    for entity in doc.modelspace().query("TEXT"):
        box = text_extents(entity)
        if box is not None:
            assert all(math.isfinite(value) for value in box)
            assert box[2] >= box[0]
            assert box[3] >= box[1]
    return doc


def test_dxf_preserves_cutouts_in_fill_and_setbacks(tmp_path):
    outer = [[72.83, 19.07], [72.831, 19.07], [72.831, 19.071], [72.83, 19.071], [72.83, 19.07]]
    cutout = [
        [72.8303, 19.0703],
        [72.8307, 19.0703],
        [72.8307, 19.0707],
        [72.8303, 19.0707],
        [72.8303, 19.0703],
    ]
    path = tmp_path / "cutout.dxf"
    export_dxf([outer, cutout], _properties(), str(path))
    model = _assert_valid_dxf(path).modelspace()
    parcel = arcgis_rings_to_geometry(
        [entity.get_points("xy") for entity in model.query('LWPOLYLINE[layer=="C-PLOT-BDY"]')]
    )
    (hatch,) = model.query('HATCH[layer=="C-PROP-HATCH"]')
    outside, inside = hatch.paths
    assert outside.path_type_flags & BOUNDARY_PATH_EXTERNAL
    assert inside.path_type_flags & BOUNDARY_PATH_OUTERMOST
    assert arcgis_rings_to_geometry([outside.vertices, inside.vertices]).equals(parcel)
    for distance in (3, 6):
        rings = [entity.get_points("xy") for entity in model.query(f'LWPOLYLINE[layer=="C-SETBACK-{distance}M"]')]
        assert len(rings) == 2
        assert arcgis_rings_to_geometry(rings).equals(parcel.buffer(-distance, join_style=2))


def test_dxf_opens_on_all_plot_parts_with_full_neighbour_geometry_retained(tmp_path):
    first = [[72.83, 19.07], [72.8302, 19.07], [72.8302, 19.0702], [72.83, 19.0702]]
    second = [[72.831, 19.07], [72.8312, 19.07], [72.8312, 19.0702], [72.831, 19.0702]]
    neighbour = [[72.8312, 19.07], [72.834, 19.07], [72.834, 19.0702], [72.8312, 19.0702]]
    path = tmp_path / "plot-view.dxf"
    export_dxf([first, second], _properties(), str(path), neighbors=[{"cts_no": "2", "rings": [neighbour]}])
    doc = _assert_valid_dxf(path)
    model = doc.modelspace()
    (viewport,) = doc.viewports.get_config("*Active")
    plot = [pt for part in model.query('LWPOLYLINE[layer=="C-PLOT-BDY"]') for pt in part.get_points("xy")]
    xs, ys = zip(*plot, strict=True)
    assert viewport.dxf.center.x == pytest.approx((min(xs) + max(xs)) / 2)
    assert viewport.dxf.center.y == pytest.approx((min(ys) + max(ys)) / 2)
    half_width = viewport.dxf.height * viewport.dxf.aspect_ratio / 2
    assert all(abs(x - viewport.dxf.center.x) < half_width for x in xs)
    (neighbour_boundary,) = model.query('LWPOLYLINE[layer=="C-ADJN-PLOTS"]')
    assert max(x for x, _ in neighbour_boundary.get_points("xy")) > viewport.dxf.center.x + half_width


def test_default_layout_policy_is_frozen_and_has_stable_grid_breaks():
    assert DEFAULT_DXF_LAYOUT_POLICY.grid_step_for(30.0) == 25.0
    assert DEFAULT_DXF_LAYOUT_POLICY.grid_step_for(61.0) == 50.0
    assert DEFAULT_DXF_LAYOUT_POLICY.grid_step_for(1001.0) == 500.0
    with pytest.raises(FrozenInstanceError):
        DEFAULT_DXF_LAYOUT_POLICY.min_scale = 10.0  # type: ignore[misc]


def test_structured_area_assessment_drives_dxf_legend_and_keeps_legacy_signature():
    properties = {
        **_properties(),
        "area_source": "approved (legacy input)",
        "area_assessment": {
            "recorded_plot_area_sqm": 1000.0,
            "calculated_boundary_area_sqm": 1061.0,
            "selected_area_basis": "recorded_plot_area",
            "difference_sqm": 61.0,
            "difference_percent": 6.1,
            "recorded_area_source": "MCGM cadastral parcel record",
            "geometry_source": "MCGM cadastral parcel boundary",
            "reliability_label": "Qualified with warnings",
        },
    }

    rows = legend_data_rows(properties, {3.0: True, 6.0: True}, measured_area_sqm=9999.0)
    text = " ".join(rows)

    assert "RECORDED PLOT AREA" in text
    assert "CALCULATED (BDY)" in text
    assert "1061.00 sq m  (+6.10% vs record)" in text
    assert "Qualified with warnings" in text
    assert "9999.00" not in text
    assert "approved" not in text.casefold()


@pytest.mark.parametrize(
    "overrides",
    [
        {"grid_extent_fraction": 0.0},
        {"legend_pad_rows": float("nan")},
        {"setback_distances": (3.0, -6.0)},
        {"grid_breaks": ((60.0, 50.0), (150.0, 100.0))},
        {"grid_breaks": ((150.0, 100.0), (150.0, 50.0))},
    ],
)
def test_layout_policy_rejects_invalid_controls(overrides):
    with pytest.raises(ValueError):
        DxfLayoutPolicy(**overrides)


@pytest.mark.parametrize("seed", [0, 7])
def test_high_vertex_irregular_plots_export_as_valid_dxf(tmp_path, seed):
    path = tmp_path / f"irregular-{seed}.dxf"
    export_dxf([_irregular_ring(seed)], _properties(), str(path))
    doc = _assert_valid_dxf(path)

    dimensions = [entity for entity in doc.modelspace().query("TEXT") if entity.dxf.layer == "C-ANNO-DIMS"]
    boxes = [text_extents(entity) for entity in dimensions]
    assert boxes
    assert all(box is not None for box in boxes)
    # The collision pass must keep surviving dimension labels disjoint.
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            assert not boxes_overlap(first, second)


def test_thin_sliver_plot_degrades_to_markers_without_invalid_entities(tmp_path):
    ring = [
        [72.830000, 19.070000],
        [72.830090, 19.07000001],
        [72.830180, 19.070000],
        [72.830090, 19.06999999],
        [72.830000, 19.070000],
    ]
    path = tmp_path / "sliver.dxf"
    policy = DxfLayoutPolicy(
        min_scale=5.0,
        min_char_height=0.4,
        min_dim_char_height=0.3,
        legend_value_max_chars=18,
    )
    export_dxf([ring], _properties(), str(path), layout_policy=policy)
    doc = _assert_valid_dxf(path)

    setback_text = [
        entity for entity in doc.modelspace().query("TEXT") if entity.dxf.layer in {"C-SETBACK-3M", "C-SETBACK-6M"}
    ]
    assert {entity.dxf.layer for entity in setback_text} == {"C-SETBACK-3M", "C-SETBACK-6M"}
    assert all(text_extents(entity) is not None for entity in setback_text)


def test_custom_policy_changes_layout_without_changing_export_contract(tmp_path):
    path = tmp_path / "custom-policy.dxf"
    policy = DxfLayoutPolicy(
        min_scale=80.0,
        grid_extent_fraction=0.5,
        legend_value_max_chars=10,
    )
    export_dxf([_irregular_ring(1, count=32)], _properties(), str(path), layout_policy=policy)
    doc = _assert_valid_dxf(path)
    assert any(entity.dxf.layer == "C-TITLE-BLOCK" for entity in doc.modelspace())
    grid_lines = [entity for entity in doc.modelspace().query("LINE") if entity.dxf.layer == "0_GRID_AXIS"]
    assert grid_lines
