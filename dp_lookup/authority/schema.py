"""Stable SQLite schema for the authority evidence registry."""

AUTHORITY_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS authority_meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_records (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    village TEXT NOT NULL, cts_no TEXT NOT NULL, ward TEXT, source_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('registered','verified','superseded','withdrawn','rejected')),
    issuer TEXT, reference_no TEXT, issue_date TEXT, survey_date TEXT,
    source_uri TEXT NOT NULL, source_sha256 TEXT NOT NULL, mime_type TEXT, byte_size INTEGER,
    recorded_area_sqm REAL, original_geometry_json TEXT, original_crs INTEGER,
    normalized_rings_json TEXT, normalized_crs INTEGER, geometry_sha256 TEXT,
    calculated_area_sqm REAL, supersedes_id INTEGER REFERENCES authority_records(record_id),
    metadata_json TEXT NOT NULL, created_by TEXT, reviewed_by TEXT, created_at TEXT NOT NULL,
    reviewed_at TEXT, updated_at TEXT NOT NULL, record_checksum TEXT NOT NULL UNIQUE,
    UNIQUE(village, cts_no, source_type, version)
);
CREATE INDEX IF NOT EXISTS authority_records_identity
    ON authority_records(village, cts_no, source_type, status, version);
CREATE TABLE IF NOT EXISTS authority_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES authority_records(record_id), event_type TEXT NOT NULL,
    actor TEXT, event_at TEXT NOT NULL, reason TEXT, details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS authority_events_record
    ON authority_events(record_id, event_at, event_id);
CREATE TABLE IF NOT EXISTS authority_selections (
    selection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES authority_records(record_id), village TEXT NOT NULL,
    cts_no TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN ('area','geometry','planning')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), selected_at TEXT NOT NULL,
    selected_by TEXT, reason TEXT, deactivated_at TEXT, deactivated_by TEXT,
    deactivation_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS authority_active_selection
    ON authority_selections(village, cts_no, purpose) WHERE active = 1;
CREATE INDEX IF NOT EXISTS authority_selection_record
    ON authority_selections(record_id, purpose, selected_at);
"""

__all__ = ["AUTHORITY_SCHEMA_VERSION", "SCHEMA"]
