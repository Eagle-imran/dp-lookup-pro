"""Contracts for the isolated ``sources`` authority CLI grammar."""

import hashlib
import io
import json
from pathlib import Path

import dp_lookup.authority_cli as cli


def test_parse_commands_and_required_fields(tmp_path: Path):
    database = tmp_path / "authority.sqlite"
    parsed = cli.parse_authority_args(
        ["sources", "list", "--database", str(database), "--village", "WORLI", "--status", "verified"]
    )
    assert parsed["command"] == "list"
    assert parsed["database"] == database
    assert parsed["village"] == "WORLI"
    assert parsed["status"] == "verified"

    try:
        cli.parse_authority_args(
            ["sources", "activate", "12", "--database", str(database), "--purpose", "bad", "--activated-by", "x"]
        )
    except ValueError as exc:
        assert "purpose" in str(exc)
    else:
        raise AssertionError("invalid purpose must be rejected")


def test_manifest_wrapper_resolves_paths_and_checksums(tmp_path: Path):
    document = tmp_path / "documents" / "card.pdf"
    document.parent.mkdir()
    document.write_bytes(b"card")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"manifest_version": 1, "items": [{"village": "WORLI", "cts_no": "733", "file": "documents/card.pdf"}]}
        ),
        encoding="utf-8",
    )
    item = cli._load_manifest(manifest)[0]
    assert item["file"] == str(document.resolve())
    assert item["sha256"] == hashlib.sha256(b"card").hexdigest()


def test_single_object_manifest_is_supported(tmp_path: Path):
    document = tmp_path / "card.pdf"
    document.write_bytes(b"card")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"village": "WORLI", "cts": "733", "source_type": "property-card", "file": "card.pdf"}),
        encoding="utf-8",
    )
    assert len(cli._load_manifest(manifest)) == 1


class _FakeStore:
    def __init__(self, path):
        self.path = path
        self.calls = []

    @classmethod
    def open(cls, path):
        return cls(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def list_sources(self, **filters):
        self.calls.append(("list", filters))
        return {"records": [{"source_id": 2}]}


def test_json_output_is_stable_and_uses_store(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "AuthorityStore", _FakeStore)
    output = io.StringIO()
    assert (
        cli.main(["sources", "list", "--database", str(tmp_path / "authority.sqlite"), "--json"], out=output)
        == cli.EXIT_SUCCESS
    )
    payload = json.loads(output.getvalue())
    assert payload["command"] == "list"
    assert payload["result"]["records"][0]["source_id"] == 2


def test_usage_and_runtime_errors_have_distinct_codes(tmp_path: Path):
    assert (
        cli.main(["sources", "show", "1", "--database", str(tmp_path / "x.sqlite"), "--json"], out=io.StringIO())
        == cli.EXIT_ERROR
    )
    assert cli.main(["sources", "show", "--database", str(tmp_path / "x.sqlite")], out=io.StringIO()) == cli.EXIT_USAGE


def test_real_registry_cli_lifecycle_is_auditable_and_requires_explicit_activation(tmp_path: Path):
    document = tmp_path / "property-card.pdf"
    document.write_bytes(b"property card")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "village": "WORLI",
                "cts_no": "733",
                "source_type": "property-card",
                "file": document.name,
                "issuing_authority": "City Survey Office",
                "recorded_area_sqm": 1400.0,
            }
        ),
        encoding="utf-8",
    )
    database = tmp_path / "plots.sqlite"

    output = io.StringIO()
    assert (
        cli.main(
            ["sources", "add", str(manifest), "--database", str(database), "--actor", "author", "--json"],
            out=output,
        )
        == cli.EXIT_SUCCESS
    )
    record_id = json.loads(output.getvalue())["result"][0]["record_id"]

    output = io.StringIO()
    assert (
        cli.main(
            ["sources", "verify", str(record_id), "--database", str(database), "--reviewed-by", "reviewer", "--json"],
            out=output,
        )
        == cli.EXIT_SUCCESS
    )

    output = io.StringIO()
    assert (
        cli.main(
            ["sources", "recommend", "WORLI", "733", "--database", str(database), "--json"],
            out=output,
        )
        == cli.EXIT_SUCCESS
    )
    recommendation = json.loads(output.getvalue())["result"]
    assert recommendation["recommendations"]["area"]["area"]["record_id"] == record_id
    assert recommendation["requires_explicit_activation"] is True

    missing_reason = io.StringIO()
    assert (
        cli.main(
            [
                "sources",
                "activate",
                str(record_id),
                "--purpose",
                "area",
                "--database",
                str(database),
                "--activated-by",
                "reviewer",
            ],
            out=missing_reason,
        )
        == cli.EXIT_USAGE
    )

    output = io.StringIO()
    assert (
        cli.main(
            [
                "sources",
                "activate",
                str(record_id),
                "--purpose",
                "area",
                "--database",
                str(database),
                "--activated-by",
                "reviewer",
                "--reason",
                "accepted recorded area",
                "--json",
            ],
            out=output,
        )
        == cli.EXIT_SUCCESS
    )

    output = io.StringIO()
    assert cli.main(["sources", "audit", "--database", str(database), "--json"], out=output) == cli.EXIT_SUCCESS
    audit = json.loads(output.getvalue())["result"]
    assert audit["ok"] is True
    assert audit["active_selection_count"] == 1
