"""Public typing, packaging-marker, and compatibility API contracts."""

import inspect
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

import cts_dp_lookup_pro as legacy
import dp_lookup
from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.application.lookup_service import lookup_plot_pro

PROJECT_ROOT = Path(__file__).parents[1]


def test_typed_package_marker_is_present_and_included_by_hatch():
    marker = PROJECT_ROOT / "dp_lookup" / "py.typed"
    assert marker.is_file(), "PEP 561 marker is required for the public dp_lookup package"

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["cts_dp_lookup_pro.py", "dp_lookup"]' in pyproject


WHEEL_REQUIRED_FILES = {
    "cts_dp_lookup_pro.py",
    "dp_lookup/py.typed",
    "dp_lookup/application/lookup_service.py",
    "dp_lookup/authority/store.py",
    "dp_lookup/core/models.py",
    "dp_lookup/exporters/templates/html_map.html",
    "dp_lookup/exporters/templates/dossier.css",
    "dp_lookup/exporters/templates/dossier.js",
    "dp_lookup/storage/sqlite.py",
}


def test_built_wheel_contains_the_package_marker_modules_and_templates():
    wheels = sorted((PROJECT_ROOT / "dist").glob("*.whl"))
    if not wheels:
        pytest.skip("no wheel built; run `uv build` first")
    with ZipFile(wheels[-1]) as wheel:
        missing = WHEEL_REQUIRED_FILES - set(wheel.namelist())
    assert not missing, f"wheel is missing {sorted(missing)}"


def test_legacy_facade_matches_package_level_api():
    assert legacy.lookup_plot_pro is lookup_plot_pro
    assert legacy.LookupDependencies is LookupDependencies
    assert legacy.__version__ == dp_lookup.__version__
    assert "LookupDependencies" in legacy.__all__
    assert dp_lookup.LookupDependencies is LookupDependencies


def test_lookup_signature_preserves_public_and_injection_parameters():
    names = list(inspect.signature(lookup_plot_pro).parameters)
    assert names == [
        "village",
        "cts_number",
        "output_dir",
        "use_cache",
        "cache_ttl_seconds",
        "timeout_seconds",
        "on_data",
        "verify_tls",
        "dependencies",
    ]


def test_mypy_configuration_is_strict_for_the_complete_production_package():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.mypy]" in pyproject
    assert "strict = true" in pyproject
    assert 'files = ["dp_lookup"]' in pyproject
    overrides = tomllib.loads(pyproject)["tool"]["mypy"]["overrides"]
    untyped = {
        module for override in overrides if override.get("ignore_missing_imports") for module in override["module"]
    }
    assert untyped == {"ezdxf.*", "openpyxl.*", "qrcode.*", "reportlab.*", "shapely.*"}
