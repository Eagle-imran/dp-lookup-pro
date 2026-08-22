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
        "authority": (
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
    assert "registered_report_artifact_exporters" in reporting_source
    assert "dependencies.geojson_writer" not in reporting_source
    assert "dependencies.pdf_writer" not in reporting_source
    assert "dependencies.excel_writer" not in reporting_source
    contracts_source = contracts.read_text(encoding="utf-8")
    assert "class PdfReportRequest" in contracts_source
    assert "class ExcelRegisterRequest" in contracts_source


def test_cli_is_a_small_compatibility_facade_over_focused_boundaries():
    facade = PROJECT_ROOT / "dp_lookup" / "cli.py"
    source = facade.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 225
    for module in ("cli_parser.py", "cli_bootstrap.py", "cli_command.py", "cli_presentation.py"):
        assert (facade.parent / module).is_file()
    assert "def format_result_human(" not in source
    assert "def _parse_cli_args(" in source  # deliberately retained compatibility wrapper


def test_dxf_facade_delegates_policy_geometry_text_and_legend_subsystems():
    exporter = PROJECT_ROOT / "dp_lookup" / "exporters" / "dxf.py"
    source = exporter.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 100
    for module in ("dxf_policy.py", "dxf_geometry.py", "dxf_text.py", "dxf_legend.py"):
        assert (exporter.parent / module).is_file()
    assert (exporter.parent / "dxf_renderer.py").is_file()
    assert "class DxfLayoutPolicy" not in source
    assert "def polygon_signed_area(" not in source
    assert "def text_extents(" not in source
    assert "def legend_data_rows(" not in source
    assert "shapely" not in source


def test_pdf_public_module_is_a_small_facade_over_typed_renderer():
    exporter = PROJECT_ROOT / "dp_lookup" / "exporters" / "pdf.py"
    source = exporter.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 15
    assert (exporter.parent / "pdf_renderer.py").is_file()
    assert "build_pdf_doc" in source
    assert "write_pdf_report" in source


def test_normalization_facade_delegates_to_focused_typed_stages():
    facade = PROJECT_ROOT / "dp_lookup" / "application" / "normalization.py"
    source = facade.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 25
    for module in (
        "road_normalization.py",
        "neighbour_normalization.py",
        "planning_normalization.py",
    ):
        assert (facade.parent / module).is_file()
    assert "def normalize_planning_evidence(" not in source


def test_arcgis_http_payload_is_typed_before_ingestion_and_normalization():
    models = PROJECT_ROOT / "dp_lookup" / "clients" / "arcgis_models.py"
    ingestion = PROJECT_ROOT / "dp_lookup" / "application" / "ingestion.py"
    source = ingestion.read_text(encoding="utf-8")
    assert "class ArcGISFeature" in models.read_text(encoding="utf-8")
    assert "class ArcGISPayload" in models.read_text(encoding="utf-8")
    assert "decode_arcgis_response" in source
    assert "usable_json" not in source


def test_pdf_and_excel_default_to_native_typed_data_writers():
    exporter_contracts = PROJECT_ROOT / "dp_lookup" / "exporters" / "contracts.py"
    dependencies = PROJECT_ROOT / "dp_lookup" / "application" / "dependencies.py"
    contracts_source = exporter_contracts.read_text(encoding="utf-8")
    dependencies_source = dependencies.read_text(encoding="utf-8")
    assert "class PlotReportData" in contracts_source
    assert "class ExcelRegisterData" in contracts_source
    assert "pdf_data_writer: PdfDataWriter = write_pdf_report" in dependencies_source
    assert "excel_data_writer: ExcelDataWriter = write_excel_register" in dependencies_source
    assert "pdf_writer: Optional[ArtifactProcedure] = None" in dependencies_source
    assert "excel_writer: Optional[ArtifactProcedure] = None" in dependencies_source


def test_planning_snapshot_spatial_reads_are_separate_from_lifecycle_store():
    package = PROJECT_ROOT / "dp_lookup" / "planning_snapshot"
    query_source = (package / "query.py").read_text(encoding="utf-8")
    store_source = (package / "store.py").read_text(encoding="utf-8")
    assert "class PlanningFeatureQuery" in query_source
    assert "PlanningFeatureQuery(" in store_source
    assert "CROSS JOIN planning_feature_rtree" not in store_source


def test_experimental_extensions_are_opt_in_and_keep_transport_and_output_boundaries():
    package = PROJECT_ROOT / "dp_lookup" / "experimental"
    assert package.is_dir(), "experimental extensions must live in their own package"
    modules = tuple((package / "assemblies").glob("*.py"))
    assert modules, "the experimental package must contain a focused adapter"

    forbidden = (
        "dp_lookup.cli",
        "dp_lookup.clients",
        "dp_lookup.exporters",
        "dp_lookup.renderers",
    )
    for path in modules:
        offenders = [name for name in _imports(path) if _matches_layer(name, forbidden)]
        assert offenders == [], f"{path.relative_to(PROJECT_ROOT)} crosses an opt-in boundary: {offenders}"

    # Importing the normal parser must not import or register the experiment.
    parser_source = (PROJECT_ROOT / "dp_lookup" / "cli_parser.py").read_text(encoding="utf-8")
    assert "dp_lookup.experimental" not in parser_source
    cli_source = (package / "assemblies_cli.py").read_text(encoding="utf-8")
    assert "importlib.import_module" in cli_source
    assert "dp_lookup.application.assembly_services" in cli_source
