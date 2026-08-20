"""Focused, network-free tests for the public command-line contract."""

import dp_lookup.cli as cli
from dp_lookup.planning_evidence import EvidenceMode


def _result(*, cached=False, complete=True):
    return {
        "plot_identity": {"village": "WORLI", "cts_no": "733", "ward": "G/S",
                          "area_sqm": 1317.74, "area_source": "approved (MCGM)"},
        "planning_remarks": {"status_badge": "CLEAR", "zone": "R",
                             "reservation": {"code": "None", "type": "None"},
                             "designation": {"description": "None"},
                             "dp_modification": {"approval_no": "None"}},
        "regulatory_and_infrastructure": {
            "crz_status": "NO", "metro_buffer": "NO",
            "abutting_road": {"name": "None", "width": "None"},
        },
        "spatial_cluster": {"adjoining_plots_count": 0, "adjoining_cts_plots": []},
        "export_files": {"bundle_folder": "./output/worli-733", "pdf_report": "./output/r.pdf",
                         "master_excel_register": "./output/dp-lookups.xlsx"},
        "metadata": {"execution_time_ms": 900, "cached_result": cached,
                     "cached_at": "2026-08-18 12:00:00" if cached else None,
                     "cache_age_days": 0.1 if cached else None,
                     "complete": complete, "warnings": ["road probe failed"] if not complete else [],
                     "notes": []},
    }


def test_help_and_version_are_successful(capsys):
    assert cli.main(["--help"]) == cli.EXIT_SUCCESS
    assert "Usage:" in capsys.readouterr().out

    assert cli.main(["--version"]) == cli.EXIT_SUCCESS
    assert cli.VERSION in capsys.readouterr().out


def test_unknown_flags_and_extra_positionals_are_rejected(capsys):
    assert cli.main(["WORLI", "733", "--wat"]) == cli.EXIT_USAGE
    assert "unknown option" in capsys.readouterr().out

    assert cli.main(["WORLI", "733", "one", "two"]) == cli.EXIT_USAGE
    assert "too many positional" in capsys.readouterr().out

    assert cli.main(["WORLI", "733", "--evidence", "magic"]) == cli.EXIT_USAGE
    assert "evidence mode must be one of" in capsys.readouterr().out


def test_conversational_cts_and_legacy_aliases_are_preserved(monkeypatch, capsys, tmp_path):
    calls = {}

    async def fake_lookup(**kwargs):
        calls.update(kwargs)
        return _result()

    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    assert cli.main(["WORLI", "CTS", "733", str(tmp_path), "--raw", "--fresh"]) == cli.EXIT_SUCCESS
    assert calls["village"] == "WORLI"
    assert calls["cts_number"] == "733"
    assert calls["use_cache"] is False
    assert '"plot_identity"' in capsys.readouterr().out


def test_evidence_mode_is_passed_through_the_dependency_boundary(monkeypatch, capsys):
    calls = {}

    async def fake_lookup(**kwargs):
        calls.update(kwargs)
        return _result()

    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    assert cli.main(["WORLI", "733", "--evidence=standard"]) == cli.EXIT_SUCCESS
    assert calls["dependencies"].planning_evidence_mode is EvidenceMode.STANDARD
    assert "[standard evidence]" in capsys.readouterr().out


def test_cached_hit_does_not_claim_to_build_and_reports_retrieval_latency(monkeypatch, capsys):
    cached = _result(cached=True)

    async def fake_lookup(**kwargs):
        kwargs["on_data"](cached)
        return cached

    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    assert cli.main(["WORLI", "733"]) == cli.EXIT_SUCCESS
    output = capsys.readouterr().out
    assert "Cached result from" in output
    assert "Building PDF" not in output
    assert "Cache retrieval:" in output


def test_incomplete_result_has_distinct_nonzero_exit(monkeypatch, capsys):
    incomplete = _result(complete=False)

    async def fake_lookup(**kwargs):
        return incomplete

    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    assert cli.main(["WORLI", "733"]) == cli.EXIT_INCOMPLETE
    assert "INCOMPLETE" in capsys.readouterr().out


def test_local_source_is_explicit_and_requires_database(monkeypatch, capsys, tmp_path):
    assert cli.main(["WORLI", "733", "--source", "local"]) == cli.EXIT_USAGE
    assert "--database PATH is required" in capsys.readouterr().out

    calls = {}

    async def fake_lookup(**kwargs):
        calls.update(kwargs)
        return _result()

    monkeypatch.setattr(cli, "lookup_plot_pro", fake_lookup)
    database = tmp_path / "parcels.sqlite"
    assert cli.main(["WORLI", "733", "--source=auto", "--database", str(database)]) == cli.EXIT_SUCCESS
    assert calls["dependencies"].parcel_fetcher.database == database
    assert calls["dependencies"].parcel_fetcher.fallback is not None
    assert calls["dependencies"].neighbour_provider.database == database


def test_database_command_routes_before_lookup_grammar(capsys, tmp_path):
    database = tmp_path / "not-built.sqlite"
    assert cli.main(["database", "status", "--database", str(database), "--json"]) == cli.EXIT_SUCCESS
    assert '"exists": false' in capsys.readouterr().out
