"""Shared SQLite plumbing for the project's durable stores.

Every store uses one WAL-mode file per database with foreign keys on and
``synchronous=FULL``, records its schema version in a ``key``/``value`` meta
table, and writes through ``BEGIN IMMEDIATE`` transactions.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Self

BUSY_TIMEOUT_SECONDS = 30.0


def connect(path: str | os.PathLike[str], *, create: bool = True) -> sqlite3.Connection:
    """Open ``path`` with row access by name and the shared durability pragmas."""
    path_obj = Path(path)
    if create:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
    elif not path_obj.is_file():
        raise FileNotFoundError(path_obj)
    connection = sqlite3.connect(str(path_obj), timeout=BUSY_TIMEOUT_SECONDS)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
    except BaseException:
        connection.close()
        raise
    return connection


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    )


def stored_schema_version(connection: sqlite3.Connection, meta_table: str) -> str | None:
    if not table_exists(connection, meta_table):
        return None
    row = connection.execute(f"SELECT value FROM {meta_table} WHERE key='schema_version'").fetchone()
    return None if row is None else str(row[0])


def set_meta(connection: sqlite3.Connection, meta_table: str, key: str, value: str, *, replace: bool = False) -> None:
    conflict = "DO UPDATE SET value=excluded.value" if replace else "DO NOTHING"
    connection.execute(f"INSERT INTO {meta_table}(key,value) VALUES(?,?) ON CONFLICT(key) {conflict}", (key, value))


def initialize_schema(
    connection: sqlite3.Connection,
    *,
    script: str,
    meta_table: str,
    version: int,
    mismatch: Callable[[str], Exception],
) -> None:
    """Refuse another schema version, then create missing tables and stamp the version.

    Nothing is committed; the caller commits after any store-specific setup.
    """
    existing = stored_schema_version(connection, meta_table)
    if existing is not None and int(existing) != version:
        raise mismatch(existing)
    connection.executescript(script)
    set_meta(connection, meta_table, "schema_version", str(version))


class SQLiteStore:
    """Connection ownership, context management and write transactions."""

    def __init__(self, connection: sqlite3.Connection, path: str | os.PathLike[str]) -> None:
        self.connection = connection
        self.path = Path(path)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _transaction_error(self, error: Exception) -> Exception | None:
        """Return a store-specific error to raise instead of ``error``, or ``None`` to re-raise it."""
        return None

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception as error:
            self.connection.rollback()
            replacement = self._transaction_error(error)
            if replacement is None:
                raise
            raise replacement from error
