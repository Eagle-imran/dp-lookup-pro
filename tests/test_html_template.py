import inspect
import json
from importlib import resources

import pytest

import dp_lookup.exporters.html_map as html_map
from dp_lookup.exporters.html_map import _render_html_template, export_html_map


def _plot_properties(**overrides):
    values = {
        "village": "WORLI",
        "cts_no": "947",
        "ward": "G/S",
        "area_sqm": 462.28,
        "zone": "R",
        "status_badge": "🟢 CLEAR (No Reservation)",
    }
    values.update(overrides)
    return values


def _area_assessment(**overrides):
    values = {
        "recorded_plot_area_sqm": 1256.59,
        "calculated_boundary_area_sqm": 1262.66,
        "selected_area_sqm": 1256.59,
        "difference_sqm": 6.07,
        "difference_percent": 0.483,
        "reliability_status": "verified_source",
        "reliability_label": "Verified source",
        "recorded_area_source": "MCGM cadastral parcel record",
        "geometry_source": "MCGM cadastral parcel boundary",
    }
    values.update(overrides)
    return values


def test_html_shell_is_loaded_from_packaged_template():
    template = resources.files("dp_lookup.exporters.templates").joinpath("html_map.html").read_text()
    css = resources.files("dp_lookup.exporters.templates").joinpath("dossier.css").read_text()
    javascript = resources.files("dp_lookup.exporters.templates").joinpath("dossier.js").read_text()

    assert template.startswith("<!DOCTYPE html>")
    assert "@@D27@@" in template
    assert "{{" not in template
    assert "Leaflet" in template
    assert ".dossier-hud" in css
    assert "@@A0@@" in css
    assert "function toggleMeasureMode" in javascript
    assert "@@A0@@" in javascript
    module_source = inspect.getsource(html_map)
    assert "<style>" not in module_source
    assert "<script>" not in module_source


def test_html_template_renderer_rejects_contract_drift():
    with pytest.raises(ValueError, match="tokens"):
        _render_html_template(["only one value"])


def test_export_renders_escaped_fields_and_valid_embedded_data(tmp_path):
    rings = [[[72.825, 18.975], [72.828, 18.975], [72.828, 18.978], [72.825, 18.978], [72.825, 18.975]]]
    output = tmp_path / "map.html"

    export_html_map(
        rings,
        _plot_properties(village="<WORLI>", cts_no='947" onclick="bad', status_badge="<b>bad</b>"),
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    assert "&lt;WORLI&gt;" in html
    assert "<b>bad</b>" not in html
    assert ".dossier-hud {" in html
    assert "function toggleMeasureMode" in html
    assert "@@A0@@" not in html
    assert "Recorded plot area" in html
    assert "Calculated boundary area" in html
    assert "Screening" in html
    assert "approved" not in html.casefold()
    data_text = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    data = json.loads(data_text)
    assert data["plot_identity"]["village"] == "<WORLI>"
    assert data["plot_identity"]["cts_no"] == '947" onclick="bad'


def test_export_displays_nested_area_assessment_and_uses_selected_area(tmp_path):
    rings = [[[72.825, 18.975], [72.828, 18.975], [72.828, 18.978], [72.825, 18.978], [72.825, 18.975]]]
    output = tmp_path / "area-assessment.html"

    export_html_map(
        rings,
        _plot_properties(
            area_sqm=999.0,
            area_source="historical label that must not be rendered",
            area_assessment=_area_assessment(),
        ),
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    assert "1,256.59 m²" in html
    assert "1,262.66 m²" in html
    assert "0.48% (+6.07 m²)" in html
    assert "Verified source" in html
    assert "MCGM cadastral parcel record" in html
    assert "historical label that must not be rendered" not in html
    assert "approved" not in html.casefold()

    data_text = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    data = json.loads(data_text)
    identity = data["plot_identity"]
    assert identity["area_sqm"] == 1256.59
    assert identity["area_assessment"] == {
        "recorded_plot_area_sqm": 1256.59,
        "calculated_boundary_area_sqm": 1262.66,
        "difference_sqm": 6.07,
        "difference_percent": 0.483,
        "reliability_status": "verified_source",
        "reliability_label": "Verified source",
        "recorded_area_source": "MCGM cadastral parcel record",
        "geometry_source": "MCGM cadastral parcel boundary",
    }


def test_legacy_boundary_area_is_presented_without_claiming_a_recorded_value(tmp_path):
    rings = [[[72.825, 18.975], [72.828, 18.975], [72.828, 18.978], [72.825, 18.978], [72.825, 18.975]]]
    output = tmp_path / "legacy-boundary.html"

    export_html_map(
        rings,
        _plot_properties(area_sqm=462.28, area_source="derived from boundary"),
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    assert "Recorded plot area</span>\n            <strong>Not available</strong>" in html
    assert "Calculated boundary area</span>\n            <strong>462.28 m²</strong>" in html
    assert "Not comparable" in html
    assert "Screening" in html
    assert "approved" not in html.casefold()


def test_active_authority_is_visible_and_original_baseline_is_explicit(tmp_path):
    rings = [[[72.825, 18.975], [72.828, 18.975], [72.828, 18.978], [72.825, 18.978], [72.825, 18.975]]]
    output = tmp_path / "authority.html"
    export_html_map(
        rings,
        _plot_properties(
            area_assessment=_area_assessment(geometry_source="Licensed total-station survey"),
            authority_resolution={
                "status": "applied",
                "active_record_ids": [12, 13],
                "area": {"source_label": "Property Card"},
                "geometry": {"source_label": "Licensed total-station survey"},
                "planning": [],
            },
        ),
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    assert "Authority selection - area: Property Card; geometry: Licensed total-station survey" in html
    assert "record IDs: 12, 13" in html
    assert "MCGM baseline retained" in html
