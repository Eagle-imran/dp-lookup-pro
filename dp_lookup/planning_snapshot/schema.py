"""Stable SQLite schema for planning evidence snapshots."""

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS planning_meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS planning_snapshots (
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
 version INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('building','ready','active','retired','failed')),
 source_url TEXT, source_metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
 finalized_at TEXT, content_hash TEXT NOT NULL DEFAULT '', complete INTEGER NOT NULL DEFAULT 0,
 validation_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS planning_snapshot_versions ON planning_snapshots(version);
CREATE TABLE IF NOT EXISTS planning_layers (
 snapshot_id INTEGER NOT NULL REFERENCES planning_snapshots(snapshot_id) ON DELETE CASCADE,
 layer_id INTEGER NOT NULL, canonical_layer_id INTEGER NOT NULL, name TEXT NOT NULL,
 geometry_type TEXT, object_id_field TEXT NOT NULL, metadata_json TEXT NOT NULL,
 expected_count INTEGER, received_count INTEGER NOT NULL DEFAULT 0,
 content_hash TEXT NOT NULL DEFAULT '', complete INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(snapshot_id, canonical_layer_id)
);
CREATE TABLE IF NOT EXISTS planning_layer_inventory (
 snapshot_id INTEGER NOT NULL, canonical_layer_id INTEGER NOT NULL, object_id INTEGER NOT NULL,
 PRIMARY KEY(snapshot_id, canonical_layer_id, object_id),
 FOREIGN KEY(snapshot_id, canonical_layer_id) REFERENCES planning_layers(snapshot_id, canonical_layer_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS planning_features (
 snapshot_id INTEGER NOT NULL, canonical_layer_id INTEGER NOT NULL, object_id INTEGER NOT NULL,
 attributes_json TEXT NOT NULL, geometry_json TEXT, raw_feature_json TEXT NOT NULL,
 bbox_min_x REAL, bbox_max_x REAL, bbox_min_y REAL, bbox_max_y REAL,
 PRIMARY KEY(snapshot_id, canonical_layer_id, object_id),
 FOREIGN KEY(snapshot_id, canonical_layer_id) REFERENCES planning_layers(snapshot_id, canonical_layer_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS planning_features_bbox ON planning_features(snapshot_id, canonical_layer_id, bbox_min_x, bbox_max_x, bbox_min_y, bbox_max_y);
CREATE TABLE IF NOT EXISTS planning_activations (
 activation_id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id INTEGER NOT NULL REFERENCES planning_snapshots(snapshot_id),
 activated_at TEXT NOT NULL, deactivated_at TEXT
);
"""

__all__ = ["SCHEMA", "SCHEMA_VERSION"]
