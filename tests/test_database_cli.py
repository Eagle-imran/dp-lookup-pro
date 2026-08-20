import io
import json
from pathlib import Path

from dp_lookup.database_cli import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE, main, parse_database_args


class Services:
    def __init__(self):
        self.calls = []

    def status(self, database):
        self.calls.append(("status", database))
        return {"records": 3, "healthy": True}

    def build(self, database): return {"built": str(database)}
    def verify(self, database): return {"valid": True}
    def diff(self, database): return {"changes": 0}
    def activate(self, database): return {"active": True}
    def rollback(self, database): return {"rolled_back": True}


def test_parse_database_command():
    parsed = parse_database_args(["database", "status", "--database", "db.sqlite", "--json"])
    assert parsed == {"command": "status", "database": Path("db.sqlite"), "json": True}


def test_dispatch_human_and_injects_path():
    services, output = Services(), io.StringIO()
    assert main(["database", "status", "--database=db.sqlite"], services=services, out=output) == EXIT_SUCCESS
    assert services.calls == [("status", Path("db.sqlite"))]
    assert "database status: OK" in output.getvalue()
    assert "records: 3" in output.getvalue()


def test_dispatch_json_contract():
    output = io.StringIO()
    assert main(["database", "verify", "--database", "db.sqlite", "--json"], services=Services(), out=output) == EXIT_SUCCESS
    payload = json.loads(output.getvalue())
    assert payload == {"command": "verify", "database": "db.sqlite", "result": {"valid": True}}


def test_safe_usage_errors():
    output = io.StringIO()
    assert main(["database", "status"], services=Services(), out=output) == EXIT_USAGE
    assert "--database PATH is required" in output.getvalue()
    output = io.StringIO()
    assert main(["database", "nope", "--database", "x"], out=output) == EXIT_USAGE


def test_service_error_has_error_exit_and_json():
    class Broken(Services):
        def status(self, database): raise RuntimeError("corrupt")
    output = io.StringIO()
    assert main(["database", "status", "--database", "x", "--json"], services=Broken(), out=output) == EXIT_ERROR
    assert json.loads(output.getvalue())["error"] == "corrupt"
