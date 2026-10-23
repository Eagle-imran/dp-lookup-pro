"""Small contract checks that keep the user-facing setup docs current."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
START_HERE = (ROOT / "START-HERE.md").read_text(encoding="utf-8")
LAYER_AUDIT = (ROOT / "docs" / "reference" / "arcgis-layers.md").read_text(encoding="utf-8")
PLANNING_EVIDENCE = (ROOT / "docs" / "guides" / "planning-evidence.md").read_text(encoding="utf-8")
PLOT_INTELLIGENCE = (ROOT / "docs" / "guides" / "plot-intelligence.md").read_text(encoding="utf-8")
DOCS_INDEX = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
ASSEMBLIES = (ROOT / "docs" / "guides" / "experimental-plot-assemblies.md").read_text(encoding="utf-8")
PERFORMANCE = (ROOT / "docs" / "operations" / "performance-regression.md").read_text(encoding="utf-8")

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def test_docs_identify_the_current_release_and_cache_policy():
    for document in (README, START_HERE):
        assert "3.14.0" in document
        assert "30 days" in document


def test_readme_lists_every_query_bundle_artifact_and_shared_register():
    expected = (
        "pdf",
        "html",
        "_hd.png",
        "_satellite.png",
        ".dxf",
        ".geojson",
        ".kml",
    )
    assert all(token in README for token in expected)
    assert "dp-lookups.xlsx" in README
    assert "seven bundle artifacts" in README


def test_pip_install_instructions_include_all_runtime_dependencies():
    pip_line = next(line for line in README.splitlines() if line.startswith("pip install "))
    assert "shapely" in pip_line


def test_planning_evidence_docs_preserve_audit_and_runtime_contracts():
    assert "Ten-CTS live layer-audit corpus" in LAYER_AUDIT
    assert "57 and 61" in LAYER_AUDIT
    assert "2250, 2251 and 2252" in LAYER_AUDIT
    assert "Layer 192 returns field names `LABEL` and `APPROVAL_DOCUMENTS`" in LAYER_AUDIT
    for mode in ("`basic`", "`shadow`", "`standard`", "`full`"):
        assert mode in PLANNING_EVIDENCE
    assert "Validated Layer 13 parcel (local-first CLI, required)" in PLANNING_EVIDENCE
    assert "local snapshot or bounded live ArcGIS adapter" in PLANNING_EVIDENCE


def test_plot_intelligence_docs_preserve_authority_and_refresh_boundaries():
    counts = [re.search(r"([\d,]+)\s+queryable village/CTS identities", text) for text in (README, PLOT_INTELLIGENCE)]
    assert all(count is not None for count in counts)
    assert len({count.group(1) for count in counts if count is not None}) == 1
    assert "internal operational system of record" in PLOT_INTELLIGENCE
    assert "not a statutory declaration" in PLOT_INTELLIGENCE
    assert "183 days" in PLOT_INTELLIGENCE
    for command in ("build", "verify", "activate", "analyze", "search", "compare", "check"):
        assert f"intelligence {command}" in PLOT_INTELLIGENCE


def test_documentation_index_exposes_each_owned_section():
    for section in ("architecture/", "guides/", "operations/", "reference/", "project/", "decisions/", "audits/"):
        assert section in DOCS_INDEX


def test_experimental_assembly_docs_keep_the_feature_opt_in_and_honest():
    assert "experimental assembly analyze" in ASSEMBLIES
    assert "--gap-tolerance" in ASSEMBLIES
    assert "No AI, LLM or agent is required" in ASSEMBLIES
    assert "certified boundary survey" in ASSEMBLIES.lower()
    assert "Raw snapshots are never rewritten" in ASSEMBLIES
    assert "combined-site zoning" in ASSEMBLIES
    assert "assembly-boundary.geojson" in ASSEMBLIES
    assert "assembly-boundary.dxf" in ASSEMBLIES
    assert "PDF, HTML" in ASSEMBLIES and "not included" in ASSEMBLIES
    assert "promotion gates" in ASSEMBLIES.lower()
    assert "experimental-plot-assemblies.md" in DOCS_INDEX


def test_performance_regression_docs_define_offline_limits_and_live_caveats():
    assert "test_stage_latency_regression.py" in PERFORMANCE
    assert "LookupDependencies" in PERFORMANCE
    assert "15 ms" in PERFORMANCE
    assert "1,000 ms" in PERFORMANCE
    assert "not a live MCGM benchmark" in PERFORMANCE
    assert "performance-regression.md" in DOCS_INDEX


def test_local_markdown_links_resolve():
    documents = [ROOT / "README.md", ROOT / "START-HERE.md", ROOT / "CONTRIBUTING.md"]
    documents.extend((ROOT / "docs").rglob("*.md"))
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            assert resolved.exists(), f"Broken documentation link in {document.relative_to(ROOT)}: {raw_target}"
