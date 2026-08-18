"""Focused contracts for the configurable DXF layout policy."""

import math
import random
from dataclasses import FrozenInstanceError

import ezdxf
import pytest

from dp_lookup.exporters.dxf import (
    DEFAULT_DXF_LAYOUT_POLICY,
    DxfLayoutPolicy,
    boxes_overlap,
    export_dxf,
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


def test_default_layout_policy_is_frozen_and_has_stable_grid_breaks():
    assert DEFAULT_DXF_LAYOUT_POLICY.grid_step_for(30.0) == 25.0
    assert DEFAULT_DXF_LAYOUT_POLICY.grid_step_for(61.0) == 50.0
    assert DEFAULT_DXF_LAYOUT_POLICY.grid_step_for(1001.0) == 500.0
    with pytest.raises(FrozenInstanceError):
        DEFAULT_DXF_LAYOUT_POLICY.min_scale = 10.0  # type: ignore[misc]


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
