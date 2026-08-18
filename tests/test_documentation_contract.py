"""Small contract checks that keep the user-facing setup docs current."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
START_HERE = (ROOT / "START-HERE.md").read_text(encoding="utf-8")
LAYER_AUDIT = (ROOT / "docs" / "ARCGIS_LAYER_AUDIT.md").read_text(encoding="utf-8")
PLANNING_EVIDENCE = (ROOT / "docs" / "PLANNING_EVIDENCE.md").read_text(encoding="utf-8")


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
    assert "Layer 13 parcel ingestion (unchanged, required)" in PLANNING_EVIDENCE
