"""Stable SQLite schema for parcel snapshot databases.

The SQL is deliberately isolated from :mod:`store`: opening an existing
database executes exactly this same idempotent DDL, so schema ownership can be
reviewed independently of lifecycle and query behaviour.
"""

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    state TEXT NOT NULL CHECK (state IN ('building','ready','active','retired','failed')),
    expected_count INTEGER,
    received_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    finalized_at REAL,
    validation_json TEXT,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
    started_at REAL NOT NULL,
    finished_at REAL,
    state TEXT NOT NULL CHECK (state IN ('running','complete','failed')),
    expected_count INTEGER,
    received_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS ingestion_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
    run_id INTEGER REFERENCES ingestion_runs(run_id),
    objectid INTEGER,
    severity TEXT NOT NULL CHECK (severity IN ('warning','error')),
    issue_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS parcels (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
    objectid INTEGER NOT NULL,
    village TEXT,
    cts_no TEXT,
    ward TEXT,
    type TEXT,
    area_app_sqm REAL,
    raw_attrs_json TEXT NOT NULL,
    raw_feature_json TEXT NOT NULL,
    geometry_json,
    geom_format TEXT NOT NULL CHECK (geom_format IN ('rings_json','wkb','none')),
    min_x REAL,
    max_x REAL,
    min_y REAL,
    max_y REAL,
    PRIMARY KEY (snapshot_id, objectid)
);
CREATE TABLE IF NOT EXISTS snapshot_inventory (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    objectid INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, objectid)
);
CREATE INDEX IF NOT EXISTS parcels_lookup ON parcels(snapshot_id, village, cts_no);
CREATE INDEX IF NOT EXISTS parcels_search ON parcels(snapshot_id, village, ward, area_app_sqm, objectid);
CREATE INDEX IF NOT EXISTS parcels_bbox ON parcels(snapshot_id, min_x, max_x, min_y, max_y);
CREATE TABLE IF NOT EXISTS parcel_bbox_map (
    bbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    objectid INTEGER NOT NULL,
    UNIQUE (snapshot_id, objectid),
    FOREIGN KEY (snapshot_id, objectid) REFERENCES parcels(snapshot_id, objectid) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS snapshot_activations (
    activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
    activated_at REAL NOT NULL,
    deactivated_at REAL
);
"""

__all__ = ["SCHEMA", "SCHEMA_VERSION"]
