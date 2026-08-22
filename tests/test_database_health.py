import io
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256

from dp_lookup.application.database_health import database_health
from dp_lookup.application.planning_snapshot import canonical_planning_specs, planning_registry_hash
from dp_lookup.authority import AuthorityManifest, AuthorityStore, SourceType
from dp_lookup.database_cli import EXIT_ERROR, EXIT_SUCCESS
from dp_lookup.database_cli import main as database_main
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore


def _parcel(objectid: int = 1):
    attrs = {
        "OBJECTID": objectid,
        "VILLAGE": "WORLI",
        "CTS_CS_NO": "733",
        "AREA_APP_SQ_MTRS": 100.0,
    }
    geometry = {"rings": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    return {"objectid": objectid, "attributes": attrs, "geometry": geometry}


def _healthy_database(path):
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source="test", expected_count=1)
        store.set_inventory(snapshot_id, [1])
        store.insert_batch(snapshot_id, [_parcel()])
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)
    specs = canonical_planning_specs()
    with PlanningSnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(
            source_url="https://example.test/MapServer",
            metadata={"registry_hash": planning_registry_hash(specs)},
        )
        for spec in specs:
            store.register_layer(
                snapshot_id,
                spec.layer_id,
                name=spec.name,
                geometry_type=spec.geometry_type,
                object_id_field=spec.object_id_field,
                expected_count=0,
            )
        store.finalize(snapshot_id)
        store.activate(snapshot_id)


def test_missing_database_is_critical_and_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"

    report = database_health(path)

    assert report["overall_status"] == "critical"
    assert report["findings"][0]["code"] == "database_missing"
    assert not path.exists()


def test_healthy_sources_are_reported_without_requiring_optional_enrichment(tmp_path):
    path = tmp_path / "healthy.sqlite"
    _healthy_database(path)
    before = path.stat().st_mtime_ns

    report = database_health(path, checked_at=datetime.now(timezone.utc))

    assert report["health_policy_version"] == "database-health/1.0"
    assert report["overall_status"] == "healthy"
    assert report["checks"]["sqlite"]["integrity_ok"] is True
    assert report["checks"]["parcels"]["active_pointer_valid"] is True
    assert report["checks"]["planning"]["registry_hash_matches"] is True
    assert report["checks"]["enrichment"]["status"] == "not_configured"
    assert path.stat().st_mtime_ns == before


def test_inventory_mismatch_is_critical(tmp_path):
    path = tmp_path / "bad.sqlite"
    _healthy_database(path)
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM snapshot_inventory")
    connection.commit()
    connection.close()

    report = database_health(path)

    assert report["overall_status"] == "critical"
    assert report["checks"]["parcels"]["status"] == "critical"


def test_unreadable_database_and_inactive_store_are_critical(tmp_path):
    unreadable = tmp_path / "not-sqlite.sqlite"
    unreadable.write_bytes(b"not a sqlite database")
    assert database_health(unreadable)["findings"][0]["code"] == "database_unreadable"

    inactive = tmp_path / "inactive.sqlite"
    with SnapshotStore.open(inactive):
        pass
    report = database_health(inactive)
    assert report["overall_status"] == "critical"
    assert any(item["code"] == "parcel_snapshot_inactive" for item in report["findings"])


def test_schema_drift_and_stale_sources_are_visible(tmp_path):
    path = tmp_path / "stale.sqlite"
    _healthy_database(path)
    connection = sqlite3.connect(path)
    connection.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
    connection.commit()
    connection.close()

    report = database_health(path, checked_at=datetime(2028, 1, 1, tzinfo=timezone.utc))

    codes = {item["code"] for item in report["findings"]}
    assert report["overall_status"] == "critical"
    assert "parcel_schema_version" in codes
    assert "parcel_snapshot_due" in codes
    assert "planning_snapshot_due" in codes


def test_missing_enrichment_file_is_attention_not_snapshot_corruption(tmp_path):
    path = tmp_path / "enriched.sqlite"
    _healthy_database(path)
    missing = tmp_path / "missing-property-card.pdf"
    with AuthorityStore.open(path) as store:
        store.register(
            AuthorityManifest(
                village="WORLI",
                cts_no="733",
                source_type=SourceType.PROPERTY_CARD,
                source_uri=str(missing),
                source_sha256=sha256(b"expected document").hexdigest(),
                issuer="City Survey Office",
            )
        )

    report = database_health(path)

    assert report["checks"]["enrichment"]["status"] == "attention"
    assert report["checks"]["enrichment"]["missing_local_file_count"] == 1


def test_invalid_active_intelligence_build_is_critical(tmp_path):
    path = tmp_path / "intelligence.sqlite"
    _healthy_database(path)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE intelligence_meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
        INSERT INTO intelligence_meta VALUES('schema_version','1');
        CREATE TABLE intelligence_builds (
          build_id INTEGER PRIMARY KEY, state TEXT, scope TEXT, parcel_snapshot_id INTEGER,
          planning_snapshot_id INTEGER, algorithm_version TEXT, expected_count INTEGER,
          record_count INTEGER, source_fingerprint TEXT, created_at TEXT, finalized_at TEXT,
          validation_json TEXT, error TEXT
        );
        CREATE TABLE plot_intelligence (build_id INTEGER);
        CREATE TABLE intelligence_activations (
          activation_id INTEGER PRIMARY KEY, build_id INTEGER, activated_at TEXT, deactivated_at TEXT
        );
        INSERT INTO intelligence_builds VALUES(
          1,'active','sample',1,1,'plot-intelligence/0.1',1,0,'old','now','now','{}',NULL
        );
        INSERT INTO intelligence_activations VALUES(1,1,'now',NULL);
        """
    )
    connection.commit()
    connection.close()

    report = database_health(path)

    assert report["overall_status"] == "critical"
    codes = {item["code"] for item in report["findings"]}
    assert {"intelligence_incomplete", "intelligence_sample_only", "intelligence_algorithm_stale"} <= codes


class _HealthServices:
    def health(self, _database):
        return {"overall_status": "critical", "checks": {}, "findings": []}


def test_health_cli_is_human_readable_and_critical_is_nonzero(tmp_path):
    output = io.StringIO()

    code = database_main(
        ["database", "health", "--database", str(tmp_path / "db.sqlite")],
        services=_HealthServices(),
        out=output,
    )

    assert code == EXIT_ERROR
    assert "database health: CRITICAL" in output.getvalue()


class _HealthyServices:
    def health(self, _database):
        return {"overall_status": "healthy", "checks": {}, "findings": []}


def test_healthy_health_cli_returns_success(tmp_path):
    assert (
        database_main(
            ["database", "health", "--database", str(tmp_path / "db.sqlite")],
            services=_HealthyServices(),
            out=io.StringIO(),
        )
        == EXIT_SUCCESS
    )
