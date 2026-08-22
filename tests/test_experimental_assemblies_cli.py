"""Network-free contract tests for the opt-in assembly CLI adapter."""

import io
from pathlib import Path

import dp_lookup.cli as cli
from dp_lookup.experimental.assemblies_cli import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE,
    main,
    parse_assembly_args,
)


class FakeAssemblyService:
    def __init__(self):
        self.calls = []

    def analyze(self, database, identities, output, gap_tolerance_m):
        self.calls.append((database, identities, output, gap_tolerance_m))
        return {
            "status": "screening",
            "combined_area_sqm": 1200.5,
            "part_count": len(identities),
            "contiguous": True,
            "warnings": [],
        }


def test_parser_uses_default_database_and_splits_cts_on_first_colon(monkeypatch):
    monkeypatch.setenv("DP_LOOKUP_DATABASE", "/tmp/plots.sqlite")
    parsed = parse_assembly_args(
        ["experimental", "assembly", "analyze", "Malabar Hill:16/738:A", "WORLI:733", "--gap-tolerance=1.5"]
    )
    assert parsed["database"] == Path("/tmp/plots.sqlite")
    assert parsed["identities"] == [("MALABAR HILL", "16/738:A"), ("WORLI", "733")]
    assert parsed["gap_tolerance_m"] == 1.5


def test_parser_rejects_less_than_two_identities_and_bad_tolerance():
    try:
        parse_assembly_args(["experimental", "assembly", "analyze", "WORLI:733"])
    except ValueError as exc:
        assert "at least two" in str(exc)
    else:
        raise AssertionError("one identity should be rejected")

    try:
        parse_assembly_args(["experimental", "assembly", "analyze", "WORLI:733", "WORLI:734", "--gap-tolerance", "-1"])
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative tolerance should be rejected")


def test_human_output_is_explicitly_experimental_and_injectable(tmp_path):
    service = FakeAssemblyService()
    stream = io.StringIO()
    code = main(
        [
            "experimental",
            "assembly",
            "analyze",
            "WORLI:733",
            "WORLI:734",
            "--database",
            str(tmp_path / "plots.sqlite"),
            "--output",
            str(tmp_path / "bundle"),
        ],
        service=service,
        out=stream,
    )
    assert code == EXIT_SUCCESS
    assert "EXPERIMENTAL" in stream.getvalue()
    assert "not legal amalgamation" in stream.getvalue()
    assert service.calls == [
        (
            tmp_path / "plots.sqlite",
            [("WORLI", "733"), ("WORLI", "734")],
            tmp_path / "bundle",
            0.25,
        )
    ]


def test_json_output_has_stable_envelope_and_service_errors_are_failures():
    stream = io.StringIO()
    code = main(
        ["experimental", "assembly", "analyze", "WORLI:733", "WORLI:734", "--json"],
        service=FakeAssemblyService(),
        out=stream,
    )
    assert code == EXIT_SUCCESS
    assert '"command": "experimental assembly analyze"' in stream.getvalue()
    assert '"village": "WORLI"' in stream.getvalue()

    class Broken:
        def analyze(self, *args):
            raise RuntimeError("database unavailable")

    stream = io.StringIO()
    assert main(
        ["experimental", "assembly", "analyze", "WORLI:733", "WORLI:734", "--json"],
        service=Broken(),
        out=stream,
    ) == EXIT_ERROR
    assert '"command": "experimental assembly analyze"' in stream.getvalue()
    assert "database unavailable" in stream.getvalue()


def test_cli_routes_only_explicit_experimental_namespace(monkeypatch):
    calls = {}

    def fake_experimental(argv):
        calls["argv"] = argv
        return EXIT_SUCCESS

    import dp_lookup.experimental.assemblies_cli as assemblies_cli

    monkeypatch.setattr(assemblies_cli, "main", fake_experimental)
    assert cli.main(["experimental", "assembly", "analyze", "WORLI:733", "WORLI:734"]) == EXIT_SUCCESS
    assert calls["argv"][0:3] == ["experimental", "assembly", "analyze"]


def test_experimental_parse_errors_have_usage_exit_code(capsys):
    assert main(["experimental", "assembly", "analyze", "WORLI:733"]) == EXIT_USAGE
    assert "at least two" in capsys.readouterr().out
