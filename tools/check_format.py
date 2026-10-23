"""Run the shared local/CI formatter scope; pass --fix to apply formatting."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "dp_lookup/authority",
    "dp_lookup/authority_cli.py",
    "dp_lookup/application",
    "dp_lookup/clients",
    "dp_lookup/core/area_assessment.py",
    "dp_lookup/core/models.py",
    "dp_lookup/core/topology.py",
    "dp_lookup/core/villages.py",
    "dp_lookup/planning_snapshot/copying.py",
    "dp_lookup/planning_snapshot_cli.py",
    "dp_lookup/exporters/contracts.py",
    "dp_lookup/exporters/dxf.py",
    "dp_lookup/exporters/excel.py",
    "dp_lookup/exporters/html_map.py",
    "tests/test_application_stages.py",
    "tests/test_area_assessment.py",
    "tests/test_authority_cli.py",
    "tests/test_authority_selection.py",
    "tests/test_authority_store.py",
    "tests/test_architecture_contract.py",
    "tests/test_artifact_isolation.py",
    "tests/test_cache_hardening.py",
    "tests/test_documentation_contract.py",
    "tests/test_dxf_layout_policy.py",
    "tests/test_excel_register_safety.py",
    "tests/test_html_template.py",
    "tests/test_ingestion_resilience.py",
    "tests/test_models_contract.py",
    "tests/test_orchestration_contract.py",
    "tests/test_planning_queries.py",
    "tests/test_planning_database_services.py",
    "tests/test_planning_snapshot_store.py",
    "tests/test_planning_snapshot_cli_extended.py",
    "tests/test_telemetry.py",
    "tests/test_tile_cache.py",
    "tests/test_topology_contract.py",
    "tests/test_transport_resilience.py",
    "tests/test_typing_contract.py",
    "tools/check_format.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="apply formatting instead of checking")
    args = parser.parse_args()
    command = [sys.executable, "-m", "ruff", "format"]
    if not args.fix:
        command.append("--check")
    return subprocess.call([*command, *TARGETS], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
