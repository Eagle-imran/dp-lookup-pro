"""Small dependency-boundary checks that keep the modular split intentional."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def _matches_layer(module: str, prefixes) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def test_domain_modules_do_not_depend_on_clients_exporters_or_renderers():
    forbidden = ("dp_lookup.clients", "dp_lookup.exporters", "dp_lookup.renderers")
    compatibility_shims = {"orchestrator.py"}
    for path in (PROJECT_ROOT / "dp_lookup" / "core").glob("*.py"):
        if path.name in compatibility_shims:
            continue
        offenders = [name for name in _imports(path) if _matches_layer(name, forbidden)]
        assert offenders == [], f"{path.name} crosses the domain boundary: {offenders}"


def test_package_layers_follow_the_documented_dependency_direction():
    forbidden_by_layer = {
        "core": (
            "dp_lookup.application",
            "dp_lookup.clients",
            "dp_lookup.exporters",
            "dp_lookup.renderers",
            "dp_lookup.cli",
        ),
        "clients": ("dp_lookup.application", "dp_lookup.exporters", "dp_lookup.renderers", "dp_lookup.cli"),
        "exporters": ("dp_lookup.application", "dp_lookup.clients", "dp_lookup.renderers", "dp_lookup.cli"),
        "renderers": ("dp_lookup.application", "dp_lookup.clients", "dp_lookup.exporters", "dp_lookup.cli"),
        "spatial_store": (
            "dp_lookup.application",
            "dp_lookup.clients",
            "dp_lookup.exporters",
            "dp_lookup.renderers",
            "dp_lookup.cli",
        ),
        "application": ("dp_lookup.cli",),
        "planning_evidence": (
            "dp_lookup.application",
            "dp_lookup.clients",
            "dp_lookup.exporters",
            "dp_lookup.renderers",
            "dp_lookup.cli",
        ),
        "planning_snapshot": (
            "dp_lookup.application",
            "dp_lookup.clients",
            "dp_lookup.exporters",
            "dp_lookup.renderers",
            "dp_lookup.cli",
        ),
        "intelligence": (
            "dp_lookup.application",
            "dp_lookup.clients",
            "dp_lookup.exporters",
            "dp_lookup.renderers",
            "dp_lookup.cli",
        ),
    }
    exceptions = {PROJECT_ROOT / "dp_lookup" / "core" / "orchestrator.py"}
    for layer, forbidden in forbidden_by_layer.items():
        for path in (PROJECT_ROOT / "dp_lookup" / layer).glob("*.py"):
            if path in exceptions:
                continue
            offenders = [name for name in _imports(path) if _matches_layer(name, forbidden)]
            assert offenders == [], f"{path.relative_to(PROJECT_ROOT)} has forbidden imports: {offenders}"


def test_planning_evidence_registry_is_pure_and_arcgis_adapter_stays_in_clients():
    package = PROJECT_ROOT / "dp_lookup" / "planning_evidence"
    assert (package / "models.py").is_file()
    assert (package / "registry.py").is_file()
    assert (PROJECT_ROOT / "dp_lookup" / "clients" / "planning_evidence_queries.py").is_file()


def test_real_lookup_coordinator_lives_in_application_layer():
    service = PROJECT_ROOT / "dp_lookup" / "application" / "lookup_service.py"
    compatibility_module = PROJECT_ROOT / "dp_lookup" / "core" / "orchestrator.py"
    assert service.exists()
    assert len(compatibility_module.read_text(encoding="utf-8").splitlines()) < 20
    assert len(service.read_text(encoding="utf-8").splitlines()) < 375


def test_compatibility_facades_delegate_without_duplicating_the_pipeline():
    import dp_lookup
    from dp_lookup.application.lookup_service import lookup_plot_pro
    from dp_lookup.core.orchestrator import lookup_plot_pro as legacy_lookup

    assert legacy_lookup is lookup_plot_pro
    assert dp_lookup.lookup_plot_pro is lookup_plot_pro

    facade = PROJECT_ROOT / "cts_dp_lookup_pro.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    implementations = [
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert implementations == []


def test_artifact_orchestration_uses_typed_registry_instead_of_writer_calls():
    contracts = PROJECT_ROOT / "dp_lookup" / "application" / "contracts.py"
    models = PROJECT_ROOT / "dp_lookup" / "core" / "models.py"
    reporting = PROJECT_ROOT / "dp_lookup" / "application" / "reporting.py"
    exporting = PROJECT_ROOT / "dp_lookup" / "application" / "exporting.py"

    assert "class ExportData" in models.read_text(encoding="utf-8")
    assert "export_properties:" not in contracts.read_text(encoding="utf-8")
    assert "class ArtifactExporter(Protocol)" in exporting.read_text(encoding="utf-8")
    assert "context.export_data.to_legacy_dict()" not in exporting.read_text(encoding="utf-8")
    reporting_source = reporting.read_text(encoding="utf-8")
    assert "registered_artifact_exporters" in reporting_source
    assert "dependencies.geojson_writer" not in reporting_source
