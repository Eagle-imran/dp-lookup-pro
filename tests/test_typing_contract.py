"""Public typing, packaging-marker, and compatibility API contracts."""

import inspect
from pathlib import Path
from zipfile import ZipFile

import cts_dp_lookup_pro as legacy
import dp_lookup
from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.application.lookup_service import lookup_plot_pro

PROJECT_ROOT = Path(__file__).parents[1]


def test_typed_package_marker_is_present_and_packaged_by_hatch():
    marker = PROJECT_ROOT / "dp_lookup" / "py.typed"
    assert marker.is_file(), "PEP 561 marker is required for the public dp_lookup package"

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["cts_dp_lookup_pro.py", "dp_lookup"]' in pyproject

    wheels = sorted((PROJECT_ROOT / "dist").glob("*.whl"))
    if not wheels:
        # The source marker and Hatch include contract above remain enforced;
        # a build job performs the ZIP-level assertion when a wheel exists.
        return
    with ZipFile(wheels[-1]) as wheel:
        assert "dp_lookup/py.typed" in wheel.namelist()


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


def test_mypy_configuration_is_strict_and_scoped_to_typed_spine():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.mypy]" in pyproject
    assert "strict = true" in pyproject
    for module in (
        "dp_lookup/application/artifacts.py",
        "dp_lookup/application/exporting.py",
        "dp_lookup/application/reporting.py",
        "dp_lookup/clients/arcgis_payloads.py",
        "dp_lookup/clients/responses.py",
        "dp_lookup/clients/validation.py",
        "dp_lookup/core/constants.py",
        "dp_lookup/core/models.py",
        "dp_lookup/core/villages.py",
    ):
        assert f'"{module}"' in pyproject
