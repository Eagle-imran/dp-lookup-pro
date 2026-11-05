"""Deterministic, read-only health reporting for the unified local database."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
from urllib.parse import unquote, urlparse

from dp_lookup.application.planning_snapshot import canonical_planning_specs, planning_registry_hash
from dp_lookup.intelligence.models import ALGORITHM_VERSION
from dp_lookup.intelligence.provenance import source_fingerprint
from dp_lookup.intelligence.store import SCHEMA_VERSION as INTELLIGENCE_SCHEMA_VERSION
from dp_lookup.planning_snapshot.store import SCHEMA_VERSION as PLANNING_SCHEMA_VERSION
from dp_lookup.spatial_store.store import SCHEMA_VERSION as PARCEL_SCHEMA_VERSION

_SEVERITY = {"healthy": 0, "not_configured": 0, "attention": 1, "critical": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return default
    return decoded


def _age_days(value: Any, checked_at: datetime) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            timestamp = float(value)
        else:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None
    return round(max(0.0, (checked_at.timestamp() - timestamp) / 86_400.0), 3)


def _section(status: str, **values: Any) -> Dict[str, Any]:
    return {"status": status, **values}


def _max_status(statuses: Iterable[str]) -> str:
    return max(statuses, key=lambda value: _SEVERITY.get(value, 2), default="healthy")


def _finding(findings: list[Dict[str, str]], severity: str, code: str, message: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message})


def _sqlite_health(connection: sqlite3.Connection, findings: list[Dict[str, str]]) -> Dict[str, Any]:
    integrity_rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
    foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
    integrity_ok = integrity_rows == ["ok"]
    if not integrity_ok:
        _finding(findings, "critical", "sqlite_integrity_failed", "; ".join(integrity_rows[:5]))
    if foreign_keys:
        _finding(
            findings,
            "critical",
            "sqlite_foreign_key_failed",
            f"{len(foreign_keys)} foreign-key violation(s) were found",
        )
    return _section(
        "healthy" if integrity_ok and not foreign_keys else "critical",
        integrity_ok=integrity_ok,
        integrity_result=integrity_rows,
        foreign_key_violation_count=len(foreign_keys),
    )


def _parcel_health(
    connection: sqlite3.Connection,
    tables: set[str],
    checked_at: datetime,
    findings: list[Dict[str, str]],
) -> Dict[str, Any]:
    required = {"meta", "snapshots", "parcels", "snapshot_inventory"}
    if not required.issubset(tables):
        _finding(findings, "critical", "parcel_schema_missing", "Parcel snapshot tables are missing")
        return _section("critical", configured=False, active_snapshot_id=None)
    schema_row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    schema_version = int(schema_row[0]) if schema_row and str(schema_row[0]).isdigit() else None
    active_count = int(connection.execute("SELECT COUNT(*) FROM snapshots WHERE state='active'").fetchone()[0])
    active_row = connection.execute(
        "SELECT * FROM snapshots WHERE state='active' ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    active_pointer_row = connection.execute("SELECT value FROM meta WHERE key='active_snapshot_id'").fetchone()
    active_pointer = int(active_pointer_row[0]) if active_pointer_row else None
    if schema_version != PARCEL_SCHEMA_VERSION:
        _finding(
            findings,
            "critical",
            "parcel_schema_version",
            f"Parcel schema is {schema_version}; expected {PARCEL_SCHEMA_VERSION}",
        )
    if active_row is None:
        _finding(findings, "critical", "parcel_snapshot_inactive", "No active parcel snapshot is available")
        return _section(
            "critical",
            configured=True,
            active_snapshot_id=None,
            snapshot_count=int(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]),
        )

    snapshot_id = int(active_row["snapshot_id"])
    expected = active_row["expected_count"]
    received = int(connection.execute("SELECT COUNT(*) FROM parcels WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0])
    inventory = int(
        connection.execute("SELECT COUNT(*) FROM snapshot_inventory WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
    )
    missing_inventory = int(
        connection.execute(
            "SELECT COUNT(*) FROM (SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? "
            "EXCEPT SELECT objectid FROM parcels WHERE snapshot_id=?)",
            (snapshot_id, snapshot_id),
        ).fetchone()[0]
    )
    extra_inventory = int(
        connection.execute(
            "SELECT COUNT(*) FROM (SELECT objectid FROM parcels WHERE snapshot_id=? "
            "EXCEPT SELECT objectid FROM snapshot_inventory WHERE snapshot_id=?)",
            (snapshot_id, snapshot_id),
        ).fetchone()[0]
    )
    missing_identity = int(
        connection.execute(
            "SELECT COUNT(*) FROM parcels WHERE snapshot_id=? AND "
            "(village IS NULL OR trim(village)='' OR cts_no IS NULL OR trim(cts_no)='')",
            (snapshot_id,),
        ).fetchone()[0]
    )
    missing_geometry = int(
        connection.execute(
            "SELECT COUNT(*) FROM parcels WHERE snapshot_id=? AND geometry_json IS NULL", (snapshot_id,)
        ).fetchone()[0]
    )
    missing_recorded_area = int(
        connection.execute(
            "SELECT COUNT(*) FROM parcels WHERE snapshot_id=? AND (area_app_sqm IS NULL OR area_app_sqm<=0)",
            (snapshot_id,),
        ).fetchone()[0]
    )
    duplicate_identity_groups = int(
        connection.execute(
            "SELECT COUNT(*) FROM (SELECT village,cts_no FROM parcels WHERE snapshot_id=? "
            "AND village IS NOT NULL AND cts_no IS NOT NULL GROUP BY village,cts_no HAVING COUNT(*)>1)",
            (snapshot_id,),
        ).fetchone()[0]
    )
    validation = _loads(active_row["validation_json"], {})
    validation_errors = list(validation.get("errors") or []) if isinstance(validation, Mapping) else []
    validation_warnings = list(validation.get("warnings") or []) if isinstance(validation, Mapping) else []
    metadata = _loads(active_row["metadata_json"], {})
    summary = metadata.get("manifest_summary", {}) if isinstance(metadata, Mapping) else {}
    age = _age_days(active_row["finalized_at"], checked_at)

    pointer_valid = active_pointer == snapshot_id
    critical = bool(
        schema_version != PARCEL_SCHEMA_VERSION
        or active_count != 1
        or not pointer_valid
        or validation_errors
        or missing_inventory
        or extra_inventory
        or missing_geometry
        or (expected is not None and received != int(expected))
        or (inventory and inventory != received)
    )
    attention = bool(missing_identity or duplicate_identity_groups or (age is not None and age >= 183.0))
    if critical:
        _finding(
            findings,
            "critical",
            "parcel_snapshot_invalid",
            "The active parcel snapshot failed completeness or geometry checks",
        )
    if not pointer_valid:
        _finding(
            findings,
            "critical",
            "parcel_active_pointer_invalid",
            "The parcel active-snapshot pointer does not match the active row",
        )
    if active_count != 1:
        _finding(
            findings,
            "critical",
            "parcel_active_count_invalid",
            f"Expected one active parcel snapshot; found {active_count}",
        )
    if missing_identity:
        _finding(
            findings,
            "attention",
            "parcel_identity_missing",
            f"{missing_identity} parcel feature(s) have no complete village/CTS identity",
        )
    if duplicate_identity_groups:
        _finding(
            findings,
            "attention",
            "parcel_identity_multiple",
            f"{duplicate_identity_groups} village/CTS identities contain multiple source features; these may be valid parcel parts and require review",
        )
    if age is not None and age >= 183.0:
        _finding(
            findings,
            "attention",
            "parcel_snapshot_due",
            f"The parcel snapshot is {age:.1f} days old and is due for an upstream check",
        )
    status = "critical" if critical else ("attention" if attention else "healthy")
    return _section(
        status,
        configured=True,
        schema_version=schema_version,
        active_snapshot_id=snapshot_id,
        active_snapshot_count=active_count,
        active_pointer_valid=pointer_valid,
        source=active_row["source"],
        finalized_at=active_row["finalized_at"],
        age_days=age,
        expected_record_count=expected,
        record_count=received,
        inventory_count=inventory,
        missing_inventory_count=missing_inventory,
        extra_inventory_count=extra_inventory,
        missing_identity_count=missing_identity,
        missing_geometry_count=missing_geometry,
        missing_recorded_area_count=missing_recorded_area,
        multi_feature_identity_group_count=duplicate_identity_groups,
        validation_error_count=len(validation_errors),
        validation_warning_count=len(validation_warnings),
        inventory_hash=metadata.get("inventory_hash") if isinstance(metadata, Mapping) else None,
        content_hash=summary.get("content_hash") if isinstance(summary, Mapping) else None,
    )


def _planning_health(
    connection: sqlite3.Connection,
    tables: set[str],
    checked_at: datetime,
    findings: list[Dict[str, str]],
) -> Dict[str, Any]:
    required = {
        "planning_meta",
        "planning_snapshots",
        "planning_layers",
        "planning_features",
        "planning_layer_inventory",
    }
    if not required.issubset(tables):
        _finding(findings, "attention", "planning_schema_missing", "Planning snapshot tables are not configured")
        return _section("attention", configured=False, active_snapshot_id=None)
    schema_row = connection.execute("SELECT value FROM planning_meta WHERE key='schema_version'").fetchone()
    schema_version = int(schema_row[0]) if schema_row and str(schema_row[0]).isdigit() else None
    active_count = int(connection.execute("SELECT COUNT(*) FROM planning_snapshots WHERE state='active'").fetchone()[0])
    active = connection.execute(
        "SELECT * FROM planning_snapshots WHERE state='active' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if active is None:
        _finding(findings, "attention", "planning_snapshot_inactive", "No active planning snapshot is available")
        return _section(
            "attention",
            configured=True,
            active_snapshot_id=None,
            snapshot_count=int(connection.execute("SELECT COUNT(*) FROM planning_snapshots").fetchone()[0]),
        )
    snapshot_id = int(active["snapshot_id"])
    metadata = _loads(active["source_metadata_json"], {})
    expected_registry_hash = planning_registry_hash(canonical_planning_specs())
    stored_registry_hash = metadata.get("registry_hash") if isinstance(metadata, Mapping) else None
    expected_layer_ids = {spec.layer_id for spec in canonical_planning_specs()}
    present_layer_ids = {
        int(row[0])
        for row in connection.execute(
            "SELECT canonical_layer_id FROM planning_layers WHERE snapshot_id=?", (snapshot_id,)
        )
    }
    missing_layer_ids = sorted(expected_layer_ids - present_layer_ids)
    aggregates = connection.execute(
        "SELECT COUNT(*) layer_count,COALESCE(SUM(expected_count),0) expected_count,"
        "COALESCE(SUM(received_count),0) received_count,"
        "SUM(CASE WHEN complete=0 THEN 1 ELSE 0 END) incomplete_layers "
        "FROM planning_layers WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    inventory_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM planning_layer_inventory WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()[0]
    )
    feature_count = int(
        connection.execute("SELECT COUNT(*) FROM planning_features WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
    )
    missing_inventory = int(
        connection.execute(
            "SELECT COUNT(*) FROM (SELECT canonical_layer_id,object_id FROM planning_layer_inventory "
            "WHERE snapshot_id=? EXCEPT SELECT canonical_layer_id,object_id FROM planning_features "
            "WHERE snapshot_id=?)",
            (snapshot_id, snapshot_id),
        ).fetchone()[0]
    )
    missing_geometry = int(
        connection.execute(
            "SELECT COUNT(*) FROM planning_features WHERE snapshot_id=? AND geometry_json IS NULL",
            (snapshot_id,),
        ).fetchone()[0]
    )
    age = _age_days(active["finalized_at"], checked_at)
    validation = _loads(active["validation_json"], {})
    validation_errors = list(validation.get("errors") or []) if isinstance(validation, Mapping) else []
    validation_warnings = list(validation.get("warnings") or []) if isinstance(validation, Mapping) else []
    layer_count = int(aggregates["layer_count"])
    expected_count = int(aggregates["expected_count"])
    incomplete = int(aggregates["incomplete_layers"] or 0)
    critical = bool(
        schema_version != PLANNING_SCHEMA_VERSION
        or active_count != 1
        or not bool(active["complete"])
        or incomplete
        or missing_inventory
        or feature_count != expected_count
        or missing_layer_ids
        or stored_registry_hash != expected_registry_hash
        or validation_errors
    )
    attention = bool(missing_geometry or validation_warnings or (age is not None and age >= 183.0))
    if critical:
        _finding(findings, "critical", "planning_snapshot_invalid", "The active planning snapshot is incomplete")
    if active_count != 1:
        _finding(
            findings,
            "critical",
            "planning_active_count_invalid",
            f"Expected one active planning snapshot; found {active_count}",
        )
    if missing_geometry:
        _finding(
            findings,
            "attention",
            "planning_geometry_missing",
            f"{missing_geometry} planning feature(s) have no source geometry",
        )
    if missing_layer_ids:
        _finding(
            findings,
            "critical",
            "planning_layers_missing",
            f"Required planning layers are missing: {missing_layer_ids}",
        )
    if stored_registry_hash != expected_registry_hash:
        _finding(
            findings,
            "critical",
            "planning_registry_changed",
            "The active planning snapshot does not match the current canonical layer registry",
        )
    if validation_warnings:
        _finding(
            findings,
            "attention",
            "planning_validation_warning",
            f"The active planning snapshot retains {len(validation_warnings)} source geometry warning(s)",
        )
    if age is not None and age >= 183.0:
        _finding(
            findings,
            "attention",
            "planning_snapshot_due",
            f"The planning snapshot is {age:.1f} days old and is due for an upstream check",
        )
    return _section(
        "critical" if critical else ("attention" if attention else "healthy"),
        configured=True,
        schema_version=schema_version,
        active_snapshot_id=snapshot_id,
        active_snapshot_count=active_count,
        version=int(active["version"]),
        source=active["source_url"],
        finalized_at=active["finalized_at"],
        age_days=age,
        layer_count=layer_count,
        missing_canonical_layer_ids=missing_layer_ids,
        registry_hash=stored_registry_hash,
        registry_hash_matches=stored_registry_hash == expected_registry_hash,
        expected_record_count=expected_count,
        record_count=feature_count,
        inventory_count=inventory_count,
        incomplete_layer_count=incomplete,
        missing_inventory_count=missing_inventory,
        missing_geometry_count=missing_geometry,
        validation_error_count=len(validation_errors),
        validation_warning_count=len(validation_warnings),
        content_hash=active["content_hash"],
    )


def _intelligence_health(
    connection: sqlite3.Connection,
    tables: set[str],
    parcel_snapshot_id: Optional[int],
    planning_snapshot_id: Optional[int],
    findings: list[Dict[str, str]],
) -> Dict[str, Any]:
    required = {"intelligence_meta", "intelligence_builds", "plot_intelligence", "intelligence_activations"}
    if not required.issubset(tables):
        return _section("not_configured", configured=False, active_build_id=None)
    active = connection.execute(
        "SELECT b.* FROM intelligence_activations a JOIN intelligence_builds b ON b.build_id=a.build_id "
        "WHERE a.deactivated_at IS NULL ORDER BY a.activation_id DESC LIMIT 1"
    ).fetchone()
    build_count = int(connection.execute("SELECT COUNT(*) FROM intelligence_builds").fetchone()[0])
    if active is None:
        if build_count:
            _finding(findings, "attention", "intelligence_inactive", "Plot intelligence exists but no build is active")
            return _section("attention", configured=True, active_build_id=None, build_count=build_count)
        return _section("not_configured", configured=False, active_build_id=None, build_count=0)
    build_id = int(active["build_id"])
    schema_row = connection.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()
    schema_version = int(schema_row[0]) if schema_row and str(schema_row[0]).isdigit() else None
    record_count = int(
        connection.execute("SELECT COUNT(*) FROM plot_intelligence WHERE build_id=?", (build_id,)).fetchone()[0]
    )
    aligned = bool(
        int(active["parcel_snapshot_id"]) == parcel_snapshot_id
        and int(active["planning_snapshot_id"]) == planning_snapshot_id
    )
    complete = record_count == int(active["expected_count"]) and record_count == int(active["record_count"])
    full_build = str(active["scope"]) == "full"
    current_algorithm = str(active["algorithm_version"]) == ALGORITHM_VERSION
    fingerprint_current = False
    if parcel_snapshot_id is not None and planning_snapshot_id is not None:
        parcel_row = connection.execute(
            "SELECT metadata_json FROM snapshots WHERE snapshot_id=?", (parcel_snapshot_id,)
        ).fetchone()
        planning_row = connection.execute(
            "SELECT content_hash FROM planning_snapshots WHERE snapshot_id=?", (planning_snapshot_id,)
        ).fetchone()
        authority_revision = None
        if {"authority_events", "authority_selections"}.issubset(tables):
            authority_revision = int(
                connection.execute(
                    "SELECT MAX(revision) FROM (SELECT COALESCE(MAX(event_id),0) revision FROM authority_events "
                    "UNION ALL SELECT COALESCE(MAX(selection_id),0) FROM authority_selections)"
                ).fetchone()[0]
                or 0
            )
        if parcel_row is not None and planning_row is not None:
            fingerprint_current = str(active["source_fingerprint"]) == source_fingerprint(
                parcel_snapshot_id,
                _loads(parcel_row[0], {}),
                planning_snapshot_id,
                str(planning_row[0]),
                authority_revision,
            )
    if not aligned:
        _finding(
            findings,
            "attention",
            "intelligence_stale",
            "Active plot intelligence does not match the active source snapshots",
        )
    if not complete:
        _finding(
            findings, "critical", "intelligence_incomplete", "Active plot intelligence has an incomplete record set"
        )
    if not full_build:
        _finding(
            findings, "attention", "intelligence_sample_only", "The active plot-intelligence build covers only a sample"
        )
    if not current_algorithm:
        _finding(
            findings,
            "attention",
            "intelligence_algorithm_stale",
            f"Plot intelligence uses {active['algorithm_version']}; current is {ALGORITHM_VERSION}",
        )
    if not fingerprint_current:
        _finding(
            findings,
            "attention",
            "intelligence_fingerprint_stale",
            "Active plot intelligence has an outdated source, authority or algorithm fingerprint",
        )

    discrepancy = {"comparable_count": 0, "over_2_percent": 0, "over_5_percent": 0, "over_10_percent": 0}
    try:
        row = connection.execute(
            "SELECT COUNT(value),"
            "SUM(CASE WHEN value>2 THEN 1 ELSE 0 END),"
            "SUM(CASE WHEN value>5 THEN 1 ELSE 0 END),"
            "SUM(CASE WHEN value>10 THEN 1 ELSE 0 END) FROM ("
            "SELECT CAST(json_extract(evidence_summary_json,'$.area_assessment.difference_percent') AS REAL) value "
            "FROM plot_intelligence WHERE build_id=? AND "
            "json_type(evidence_summary_json,'$.area_assessment.difference_percent') IN ('integer','real'))",
            (build_id,),
        ).fetchone()
        discrepancy = {
            "comparable_count": int(row[0] or 0),
            "over_2_percent": int(row[1] or 0),
            "over_5_percent": int(row[2] or 0),
            "over_10_percent": int(row[3] or 0),
        }
    except sqlite3.DatabaseError:
        discrepancy["available"] = False
    return _section(
        "critical"
        if not complete or schema_version != INTELLIGENCE_SCHEMA_VERSION
        else (
            "attention"
            if not aligned or not full_build or not current_algorithm or not fingerprint_current
            else "healthy"
        ),
        configured=True,
        schema_version=schema_version,
        active_build_id=build_id,
        scope=active["scope"],
        algorithm_version=active["algorithm_version"],
        algorithm_current=current_algorithm,
        record_count=record_count,
        expected_record_count=int(active["expected_count"]),
        parcel_snapshot_id=int(active["parcel_snapshot_id"]),
        planning_snapshot_id=int(active["planning_snapshot_id"]),
        source_alignment=aligned and current_algorithm and fingerprint_current,
        fingerprint_current=fingerprint_current,
        area_discrepancy=discrepancy,
    )


def _local_source_path(source_uri: str) -> Optional[Path]:
    parsed = urlparse(source_uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(source_uri).expanduser()


def _enrichment_health(
    connection: sqlite3.Connection,
    tables: set[str],
    findings: list[Dict[str, str]],
) -> Dict[str, Any]:
    required = {"authority_meta", "authority_records", "authority_selections", "authority_events"}
    if not required.issubset(tables):
        return _section("not_configured", configured=False, record_count=0)
    status_counts = {
        str(row[0]): int(row[1])
        for row in connection.execute("SELECT status,COUNT(*) FROM authority_records GROUP BY status")
    }
    record_count = sum(status_counts.values())
    active_count = int(connection.execute("SELECT COUNT(*) FROM authority_selections WHERE active=1").fetchone()[0])
    invalid_checksums = int(
        connection.execute(
            "SELECT COUNT(*) FROM authority_records WHERE length(source_sha256)!=64 OR length(record_checksum)!=64"
        ).fetchone()[0]
    )
    invalid_active = int(
        connection.execute(
            "SELECT COUNT(*) FROM authority_selections s JOIN authority_records r ON r.record_id=s.record_id "
            "WHERE s.active=1 AND (r.status!='verified' OR r.village!=s.village OR r.cts_no!=s.cts_no)"
        ).fetchone()[0]
    )
    missing_files = 0
    for row in connection.execute("SELECT source_uri FROM authority_records"):
        local_path = _local_source_path(str(row[0]))
        if local_path is not None and not local_path.is_file():
            missing_files += 1
    bad = bool(invalid_checksums or invalid_active or missing_files)
    if invalid_checksums:
        _finding(
            findings,
            "critical",
            "enrichment_checksum_invalid",
            f"{invalid_checksums} enrichment record(s) have malformed checksums",
        )
    if invalid_active:
        _finding(
            findings,
            "critical",
            "enrichment_selection_invalid",
            f"{invalid_active} active enrichment selection(s) are invalid",
        )
    if missing_files:
        _finding(
            findings, "attention", "enrichment_file_missing", f"{missing_files} local enrichment file(s) are missing"
        )
    return _section(
        "critical" if invalid_checksums or invalid_active else ("attention" if missing_files else "healthy"),
        configured=True,
        record_count=record_count,
        status_counts=status_counts,
        active_selection_count=active_count,
        missing_local_file_count=missing_files,
        malformed_checksum_count=invalid_checksums,
        invalid_active_selection_count=invalid_active,
        ok=not bad,
    )


def database_health(database: Path, *, checked_at: Optional[datetime] = None) -> Dict[str, Any]:
    """Return one stable health envelope without changing the SQLite file."""
    path = Path(database).expanduser()
    timestamp = checked_at or _now()
    findings: list[Dict[str, str]] = []
    if not path.is_file():
        return {
            "health_policy_version": "database-health/1.0",
            "overall_status": "critical",
            "checked_at": timestamp.isoformat(),
            "database": str(path),
            "database_size_bytes": 0,
            "summary": {"critical": 1, "attention": 0, "healthy": 0, "not_configured": 0},
            "checks": {},
            "findings": [
                {"severity": "critical", "code": "database_missing", "message": f"Database does not exist: {path}"}
            ],
        }
    try:
        with closing(_connect_read_only(path)) as connection:
            present = _tables(connection)
            sqlite_health = _sqlite_health(connection, findings)
            parcels = _parcel_health(connection, present, timestamp, findings)
            planning = _planning_health(connection, present, timestamp, findings)
            intelligence = _intelligence_health(
                connection,
                present,
                parcels.get("active_snapshot_id"),
                planning.get("active_snapshot_id"),
                findings,
            )
            enrichment = _enrichment_health(connection, present, findings)
    except (OSError, sqlite3.DatabaseError) as exc:
        return {
            "health_policy_version": "database-health/1.0",
            "overall_status": "critical",
            "checked_at": timestamp.isoformat(),
            "database": str(path),
            "database_size_bytes": path.stat().st_size,
            "summary": {"critical": 1, "attention": 0, "healthy": 0, "not_configured": 0},
            "checks": {},
            "findings": [{"severity": "critical", "code": "database_unreadable", "message": str(exc)}],
        }
    checks = {
        "sqlite": sqlite_health,
        "parcels": parcels,
        "planning": planning,
        "intelligence": intelligence,
        "enrichment": enrichment,
    }
    statuses: Sequence[str] = tuple(str(section["status"]) for section in checks.values())
    summary = {name: statuses.count(name) for name in ("critical", "attention", "healthy", "not_configured")}
    return {
        "health_policy_version": "database-health/1.0",
        "overall_status": _max_status(statuses),
        "checked_at": timestamp.isoformat(),
        "database": str(path),
        "database_size_bytes": path.stat().st_size,
        "wal_size_bytes": path.with_name(path.name + "-wal").stat().st_size
        if path.with_name(path.name + "-wal").is_file()
        else 0,
        "summary": summary,
        "checks": checks,
        "findings": findings,
    }


__all__ = ["database_health"]
