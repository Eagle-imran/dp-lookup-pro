import contextlib
import math
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest

from dp_lookup.core.timestamps import age_days, utc_now
from dp_lookup.intelligence.store import IntelligenceStateError, IntelligenceStore
from dp_lookup.planning_snapshot.models import PlanningSnapshotStateError
from dp_lookup.planning_snapshot.store import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore, SpatialStoreError, StoreCorruptError, StoreReadOnlyError
from dp_lookup.storage import SQLiteStore, connect, initialize_schema, stored_schema_version

SCRIPT = "CREATE TABLE IF NOT EXISTS demo_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("invalid", None),
        (math.inf, None),
        (math.nan, None),
        (True, None),
        ("2026-01-01T00:00:00Z", 1.0),
        (datetime(2026, 1, 1, tzinfo=UTC), 1.0),
        (datetime(2026, 1, 1, tzinfo=UTC).timestamp(), 1.0),
        (str(datetime(2026, 1, 1, tzinfo=UTC).timestamp()), 1.0),
        ("2026-01-03T00:00:00+00:00", 0.0),
    ],
)
def test_age_days_reads_every_stored_timestamp_form(value, expected):
    now = datetime(2026, 1, 2, tzinfo=UTC).timestamp()
    assert age_days(value, now=now) == expected


def test_age_days_defaults_to_the_current_time():
    assert age_days(str(time.time())) == pytest.approx(0.0, abs=0.01)
    assert age_days(datetime.now(UTC) - timedelta(days=2)) == pytest.approx(2.0, abs=0.01)


def test_utc_now_is_an_aware_iso_timestamp():
    assert datetime.fromisoformat(utc_now()).utcoffset() == timedelta(0)


def test_connect_applies_the_shared_pragmas(tmp_path):
    connection = connect(tmp_path / "nested" / "store.sqlite")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.row_factory is sqlite3.Row
    finally:
        connection.close()
    with pytest.raises(FileNotFoundError):
        connect(tmp_path / "missing.sqlite", create=False)


def test_initialize_schema_stamps_once_and_refuses_another_version(tmp_path):
    with contextlib.closing(connect(tmp_path / "s.sqlite")) as connection:
        initialize_schema(connection, script=SCRIPT, meta_table="demo_meta", version=1, mismatch=RuntimeError)
        initialize_schema(connection, script=SCRIPT, meta_table="demo_meta", version=1, mismatch=RuntimeError)
        assert stored_schema_version(connection, "demo_meta") == "1"
        with pytest.raises(RuntimeError, match="1"):
            initialize_schema(connection, script=SCRIPT, meta_table="demo_meta", version=2, mismatch=RuntimeError)


def test_transaction_commits_or_rolls_back(tmp_path):
    connection = connect(tmp_path / "t.sqlite")
    connection.execute("CREATE TABLE t (v INTEGER)")
    connection.commit()
    with SQLiteStore(connection, tmp_path / "t.sqlite") as store:
        with store.transaction() as tx:
            tx.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(ZeroDivisionError), store.transaction() as tx:
            tx.execute("INSERT INTO t VALUES (2)")
            raise ZeroDivisionError
        assert [row[0] for row in store.connection.execute("SELECT v FROM t")] == [1]


@pytest.mark.parametrize(
    ("message", "error"),
    [("attempt to write a readonly database", StoreReadOnlyError), ("database is locked", SpatialStoreError)],
)
def test_parcel_store_translates_sqlite_operational_errors(tmp_path, message, error):
    with SnapshotStore.open(tmp_path / "p.sqlite") as store:
        with pytest.raises(error, match=message), store.transaction():
            raise sqlite3.OperationalError(message)
        with pytest.raises(KeyError), store.transaction():
            raise KeyError("not translated")


@pytest.mark.parametrize(
    ("store_type", "meta_table", "error"),
    [
        (SnapshotStore, "meta", StoreCorruptError),
        (PlanningSnapshotStore, "planning_meta", PlanningSnapshotStateError),
        (IntelligenceStore, "intelligence_meta", IntelligenceStateError),
    ],
)
def test_stores_refuse_a_newer_schema(tmp_path, store_type, meta_table, error):
    path = tmp_path / "s.sqlite"
    store_type.open(path).close()
    with contextlib.closing(connect(path)) as connection:
        connection.execute(f"UPDATE {meta_table} SET value='999' WHERE key='schema_version'")
        connection.commit()
    with pytest.raises(error, match="999"):
        store_type.open(path)
