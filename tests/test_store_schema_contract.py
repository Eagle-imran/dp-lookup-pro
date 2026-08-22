"""Regression contracts for persistence modules split from their store facades."""

import sqlite3
from contextlib import closing

from dp_lookup.authority import store as authority_store
from dp_lookup.authority.schema import SCHEMA as AUTHORITY_SCHEMA
from dp_lookup.planning_snapshot import store as planning_store
from dp_lookup.planning_snapshot.schema import SCHEMA as PLANNING_SCHEMA
from dp_lookup.spatial_store import store as spatial_store
from dp_lookup.spatial_store.schema import SCHEMA as SPATIAL_SCHEMA


def _schema(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def test_store_facades_reexport_their_schema_contracts():
    assert spatial_store.SCHEMA is SPATIAL_SCHEMA
    assert planning_store.SCHEMA is PLANNING_SCHEMA
    assert authority_store.SCHEMA is AUTHORITY_SCHEMA


def test_schema_modules_keep_the_persisted_columns_and_indexes_stable():
    with closing(sqlite3.connect(":memory:")) as spatial:
        spatial.executescript(SPATIAL_SCHEMA)
        assert _schema(spatial, "parcels") == (
            "snapshot_id", "objectid", "village", "cts_no", "ward", "type", "area_app_sqm",
            "raw_attrs_json", "raw_feature_json", "geometry_json", "geom_format", "min_x", "max_x", "min_y", "max_y",
        )
        assert _schema(spatial, "snapshot_inventory") == ("snapshot_id", "objectid")

    with closing(sqlite3.connect(":memory:")) as planning:
        planning.executescript(PLANNING_SCHEMA)
        assert _schema(planning, "planning_layers") == (
            "snapshot_id", "layer_id", "canonical_layer_id", "name", "geometry_type", "object_id_field",
            "metadata_json", "expected_count", "received_count", "content_hash", "complete",
        )
        assert _schema(planning, "planning_features")[-4:] == (
            "bbox_min_x", "bbox_max_x", "bbox_min_y", "bbox_max_y"
        )

    with closing(sqlite3.connect(":memory:")) as authority:
        authority.executescript(AUTHORITY_SCHEMA)
        assert _schema(authority, "authority_records")[-5:] == (
            "reviewed_by", "created_at", "reviewed_at", "updated_at", "record_checksum"
        )
        assert {
            row[1] for row in authority.execute("PRAGMA index_list(authority_selections)")
        } >= {"authority_active_selection", "authority_selection_record"}
