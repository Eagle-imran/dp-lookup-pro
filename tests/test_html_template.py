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
    data_text = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    data = json.loads(data_text)
    assert data["plot_identity"]["village"] == "<WORLI>"
    assert data["plot_identity"]["cts_no"] == '947" onclick="bad'
