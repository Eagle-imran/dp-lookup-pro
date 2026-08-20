"""Small, durable SQLite store for immutable parcel snapshots.

The module deliberately uses only the Python standard library.  Geometry is
stored as the source rings JSON (or WKB supplied by a caller) and no geometry
is simplified or re-projected here.  Spatial indexing is an optimisation: a
normal bbox scan is used when the SQLite build does not provide R-Tree.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union, cast

from dp_lookup.core.topology import arcgis_rings_to_geometry

SCHEMA_VERSION = 2


class SpatialStoreError(RuntimeError):
    """Base class for explicit store failures."""


class StoreCorruptError(SpatialStoreError):
    """The database is not a readable database with this schema."""


class StoreReadOnlyError(SpatialStoreError):
    """A write was attempted against a read-only database."""


class SnapshotStateError(SpatialStoreError):
    """An operation is incompatible with a snapshot's lifecycle state."""


class SnapshotValidationError(SpatialStoreError):
    """A snapshot failed validation and therefore cannot be finalized."""


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: int
    state: str
    source: Optional[str]
    expected_count: Optional[int]
    received_count: int
    created_at: float
    finalized_at: Optional[float]


def _now() -> float:
    return time.time()


def _json_value(value: Any, *, field: str) -> str:
    if isinstance(value, str):
        # Preserve a caller's raw JSON bytes/text.  Parsing validates it while
        # retaining its exact representation in the database.
        try:
            json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is not valid JSON") from exc
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as JSON") from exc


def _canonical_json_value(value: Any, *, field: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as canonical JSON") from exc


def _number(value: Any, *, field: str) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _identity_text(value: Any, *, uppercase: bool = False) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.upper() if uppercase else normalized


def _polygon_validation_error(geometry: Any) -> Optional[str]:
    """Return a reason when an ArcGIS polygon cannot be used safely."""
    if isinstance(geometry, Mapping):
        rings = geometry.get("rings", geometry.get("coordinates"))
    else:
        rings = geometry
    if not isinstance(rings, list) or not rings:
        return "polygon has no rings"
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            return "polygon contains a ring with fewer than four coordinates"
        distinct: set[Tuple[float, float]] = set()
        for point in ring:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return "polygon contains an invalid coordinate"
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError, OverflowError):
                return "polygon contains a non-numeric coordinate"
            if not math.isfinite(x) or not math.isfinite(y):
                return "polygon contains a non-finite coordinate"
            distinct.add((x, y))
        if len(distinct) < 3:
            return "polygon ring has fewer than three distinct coordinates"
    try:
        normalized = arcgis_rings_to_geometry(rings)
    except Exception as exc:
        return f"polygon topology could not be interpreted ({exc})"
    if normalized.is_empty or normalized.area <= 0:
        return "polygon is empty or has no area"
    if not normalized.is_valid:
        return "polygon remains topologically invalid after normalization"
    return None


def _bbox_from_geometry(geometry: Any) -> Optional[Tuple[float, float, float, float]]:
    """Find [x, y] coordinate pairs in common ArcGIS/GeoJSON ring shapes."""
    if geometry is None:
        return None
    if isinstance(geometry, Mapping):
        if "rings" in geometry:
            geometry = geometry["rings"]
        elif "coordinates" in geometry:
            geometry = geometry["coordinates"]
        elif "wkb" in geometry:
            return None

    points: List[Tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and not isinstance(value[0], (list, tuple, Mapping)):
                try:
                    x, y = float(value[0]), float(value[1])
                except (TypeError, ValueError):
                    return
                if math.isfinite(x) and math.isfinite(y):
                    points.append((x, y))
                return
            for child in value:
                walk(child)

    walk(geometry)
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), max(xs), min(ys), max(ys)


def _record_geometry(record: Mapping[str, Any]) -> Tuple[Any, str, Optional[Tuple[float, float, float, float]]]:
    geometry = record.get("geometry", record.get("rings", record.get("geometry_rings", record.get("geometry_json"))))
    geom_format = record.get("geom_format")
    if isinstance(geometry, Mapping) and "wkb" in geometry:
        geometry = geometry["wkb"]
        geom_format = geom_format or "wkb"
    if geom_format is None:
        geom_format = "rings_json" if geometry is not None else "none"
    if geom_format not in {"rings_json", "wkb", "none"}:
        raise ValueError(f"unsupported geom_format: {geom_format}")
    bbox = record.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError("bbox must contain min_x, max_x, min_y, max_y")
        bbox_values = [_number(v, field="bbox") for v in bbox]
        if any(value is None for value in bbox_values):
            raise ValueError("bbox values cannot be null")
        min_x, max_x, min_y, max_y = cast(List[float], bbox_values)
        bbox = (min_x, max_x, min_y, max_y)
    else:
        bbox = _bbox_from_geometry(geometry) if geom_format == "rings_json" else None
    geometry_value: Any
    if geometry is not None and geom_format != "wkb":
        geometry_value = _json_value(geometry, field="geometry")
    elif geometry is None:
        geometry_value = None
    elif isinstance(geometry, bytes):
        geometry_value = geometry
    else:
        # WKB can be supplied as a hex string or base64 by a higher layer; keep
        # it losslessly as text rather than guessing its encoding.
        geometry_value = str(geometry)
    return geometry_value, geom_format, bbox


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


class SnapshotStore:
    """SQLite-backed immutable snapshot store.

    ``SnapshotStore`` owns a connection and is safe to use sequentially from
    one process. SQLite WAL permits readers while a separate writer commits.
    The lifecycle methods make it impossible to mutate a ready/active snapshot.
    """

    def __init__(self, connection: sqlite3.Connection, path: Union[str, os.PathLike[str]]) -> None:
        self.connection = connection
        self.path = Path(path)
        self.rtree_available = self._has_rtree()

    @classmethod
    def open(cls, path: Union[str, os.PathLike[str]]) -> "SnapshotStore":
        path_obj = Path(path)
        connection: Optional[sqlite3.Connection] = None
        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path_obj), timeout=30.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            cls._initialize_schema(connection)
            return cls(connection, path_obj)
        except SpatialStoreError:
            if connection is not None:
                connection.close()
            raise
        except (sqlite3.DatabaseError, OSError) as exc:
            if connection is not None:
                connection.close()
            raise StoreCorruptError(f"unable to open SQLite store {path_obj}: {exc}") from exc

    create_or_open = open

    @staticmethod
    def _initialize_schema(connection: sqlite3.Connection) -> None:
        try:
            existing = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.OperationalError:
            existing = None
        try:
            connection.executescript(SCHEMA)
            if existing is not None and int(existing[0]) != SCHEMA_VERSION:
                raise StoreCorruptError(f"unsupported schema version {existing[0]}; expected {SCHEMA_VERSION}")
            connection.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO NOTHING",
                (str(SCHEMA_VERSION),),
            )
            connection.execute("INSERT INTO meta(key,value) VALUES('created_at',?) ON CONFLICT(key) DO NOTHING", (str(_now()),))
            try:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS parcel_bbox USING rtree(" \
                    "bbox_id, min_x, max_x, min_y, max_y)"
                )
                connection.execute("INSERT INTO meta(key,value) VALUES('rtree_available','1') ON CONFLICT(key) DO UPDATE SET value='1'")
            except sqlite3.OperationalError:
                # SQLite builds without the optional module remain correct via
                # the indexed bbox columns on parcels.
                connection.execute("INSERT INTO meta(key,value) VALUES('rtree_available','0') ON CONFLICT(key) DO UPDATE SET value='0'")
            connection.commit()
        except StoreCorruptError:
            connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise StoreCorruptError(f"could not initialize schema: {exc}") from exc

    def _has_rtree(self) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='parcel_bbox'"
        ).fetchone() is not None

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except sqlite3.OperationalError as exc:
            self.connection.rollback()
            if "readonly" in str(exc).lower() or "read-only" in str(exc).lower():
                raise StoreReadOnlyError(str(exc)) from exc
            raise SpatialStoreError(str(exc)) from exc
        except Exception:
            self.connection.rollback()
            raise

    def begin_snapshot(
        self,
        *,
        source: Optional[str] = None,
        expected_count: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> int:
        if expected_count is not None and expected_count < 0:
            raise ValueError("expected_count cannot be negative")
        now = _now()
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots(source,state,expected_count,created_at,metadata_json) VALUES(?,?,?,?,?)",
                (source, "building", expected_count, now, _json_value(metadata or {}, field="metadata")),
            )
            if cur.lastrowid is None:
                raise SpatialStoreError("SQLite did not return a snapshot ID")
            snapshot_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO ingestion_runs(snapshot_id,started_at,state,expected_count) VALUES(?,?,?,?)",
                (snapshot_id, now, "running", expected_count),
            )
        return snapshot_id

    def _snapshot_row(self, snapshot_id: int) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown snapshot_id {snapshot_id}")
        return row  # type: ignore[no-any-return]

    def _building(self, snapshot_id: int) -> sqlite3.Row:
        row = self._snapshot_row(snapshot_id)
        if row["state"] != "building":
            raise SnapshotStateError(f"snapshot {snapshot_id} is {row['state']}, not building")
        return row

    @staticmethod
    def _field(record: Mapping[str, Any], *names: str) -> Any:
        for name in names:
            if name in record:
                return record[name]
        attrs = record.get("raw_attrs", record.get("attributes"))
        if isinstance(attrs, Mapping):
            for name in names:
                if name in attrs:
                    return attrs[name]
        return None

    def insert_batch(
        self,
        snapshot_id: int,
        records: Iterable[Mapping[str, Any]],
        *,
        ingestion_run_id: Optional[int] = None,
    ) -> int:
        self._building(snapshot_id)
        prepared: List[Tuple[Any, ...]] = []
        for record in records:
            objectid = self._field(record, "objectid", "OBJECTID")
            if objectid is None:
                raise ValueError("parcel record requires objectid")
            try:
                objectid = int(objectid)
            except (TypeError, ValueError) as exc:
                raise ValueError("objectid must be an integer") from exc
            attrs = record.get("raw_attrs", record.get("attributes", record.get("raw_attrs_json", record)))
            raw_json = _json_value(attrs, field="raw_attrs")
            geometry, geom_format, bbox = _record_geometry(record)
            raw_feature = record.get("raw_feature")
            if raw_feature is None:
                raw_feature = {"attributes": attrs, "geometry": record.get("geometry", record.get("rings"))}
            raw_feature_json = _canonical_json_value(raw_feature, field="raw_feature")
            village = _identity_text(self._field(record, "village", "VILLAGE"), uppercase=True)
            cts_no = _identity_text(self._field(record, "cts_no", "cts", "CTS_CS_NO"), uppercase=True)
            ward = _identity_text(self._field(record, "ward", "WARD"), uppercase=True)
            type_ = self._field(record, "type", "type_", "TYPE")
            area = _number(self._field(record, "area_app_sqm", "area_app_sqmtrs", "AREA_APP_SQ_MTRS"), field="area_app_sqm")
            min_x, max_x, min_y, max_y = bbox or (None, None, None, None)
            prepared.append((snapshot_id, objectid, village, cts_no,
                             ward, None if type_ is None else str(type_).strip(), area, raw_json, raw_feature_json,
                             geometry, geom_format, min_x, max_x, min_y, max_y))
        if not prepared:
            return 0
        with self.transaction() as conn:
            conn.executemany(
                """INSERT INTO parcels(snapshot_id,objectid,village,cts_no,ward,type,area_app_sqm,raw_attrs_json,
                   raw_feature_json,geometry_json,geom_format,min_x,max_x,min_y,max_y) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(snapshot_id,objectid) DO UPDATE SET village=excluded.village,cts_no=excluded.cts_no,
                   ward=excluded.ward,type=excluded.type,area_app_sqm=excluded.area_app_sqm,raw_attrs_json=excluded.raw_attrs_json,
                   raw_feature_json=excluded.raw_feature_json,geometry_json=excluded.geometry_json,
                   geom_format=excluded.geom_format,min_x=excluded.min_x,max_x=excluded.max_x,
                   min_y=excluded.min_y,max_y=excluded.max_y""",
                prepared,
            )
            if self.rtree_available:
                for row in prepared:
                    _, objectid, _, _, _, _, _, _, _, _, _, min_x, max_x, min_y, max_y = row
                    if min_x is None:
                        mapping = conn.execute(
                            "SELECT bbox_id FROM parcel_bbox_map WHERE snapshot_id=? AND objectid=?",
                            (snapshot_id, objectid),
                        ).fetchone()
                        if mapping is not None:
                            conn.execute("DELETE FROM parcel_bbox WHERE bbox_id=?", (mapping[0],))
                            conn.execute("DELETE FROM parcel_bbox_map WHERE bbox_id=?", (mapping[0],))
                        continue
                    conn.execute(
                        "INSERT INTO parcel_bbox_map(snapshot_id,objectid) VALUES(?,?) ON CONFLICT(snapshot_id,objectid) DO NOTHING",
                        (snapshot_id, objectid),
                    )
                    bbox_id = conn.execute(
                        "SELECT bbox_id FROM parcel_bbox_map WHERE snapshot_id=? AND objectid=?", (snapshot_id, objectid)
                    ).fetchone()[0]
                    conn.execute("DELETE FROM parcel_bbox WHERE bbox_id=?", (bbox_id,))
                    conn.execute("INSERT INTO parcel_bbox VALUES(?,?,?,?,?)", (bbox_id, min_x, max_x, min_y, max_y))
            count = len(prepared)
            conn.execute("UPDATE snapshots SET received_count=(SELECT COUNT(*) FROM parcels WHERE snapshot_id=?) WHERE snapshot_id=?", (snapshot_id, snapshot_id))
            if ingestion_run_id is not None:
                conn.execute("UPDATE ingestion_runs SET received_count=(SELECT COUNT(*) FROM parcels WHERE snapshot_id=?) WHERE run_id=?", (snapshot_id, ingestion_run_id))
        return count

    def set_inventory(self, snapshot_id: int, objectids: Iterable[int]) -> int:
        """Persist the authoritative inventory used to prove exact coverage."""
        self._building(snapshot_id)
        normalized = tuple(sorted(set(int(value) for value in objectids)))
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? ORDER BY objectid",
                (snapshot_id,),
            ).fetchall()
            if existing:
                existing_ids = tuple(int(row[0]) for row in existing)
                if existing_ids != normalized:
                    raise SnapshotStateError(
                        f"snapshot {snapshot_id} inventory differs from its persisted checkpoint"
                    )
                return len(existing_ids)
            conn.executemany(
                "INSERT INTO snapshot_inventory(snapshot_id,objectid) VALUES(?,?)",
                ((snapshot_id, objectid) for objectid in normalized),
            )
        return len(normalized)

    insert_parcels = insert_batch
    add_parcels = insert_batch
    insert_records = insert_batch

    def add_issue(
        self,
        snapshot_id: int,
        issue_type: str,
        message: str,
        *,
        severity: str = "error",
        objectid: Optional[int] = None,
        run_id: Optional[int] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> int:
        self._building(snapshot_id)
        if severity not in {"warning", "error"}:
            raise ValueError("severity must be warning or error")
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO ingestion_issues(snapshot_id,run_id,objectid,severity,issue_type,message,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (snapshot_id, run_id, objectid, severity, issue_type, message, _json_value(details or {}, field="details"), _now()),
            )
            if cur.lastrowid is None:
                raise SpatialStoreError("SQLite did not return an issue ID")
            return int(cur.lastrowid)

    def validate_snapshot(self, snapshot_id: int) -> Dict[str, Any]:
        row = self._snapshot_row(snapshot_id)
        errors: List[str] = []
        warnings: List[str] = []
        count = int(self.connection.execute("SELECT COUNT(*) FROM parcels WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0])
        expected = row["expected_count"]
        if expected is not None and count != expected:
            errors.append(f"expected {expected} parcels, received {count}")
        inventory_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM snapshot_inventory WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()[0]
        )
        if inventory_count:
            missing = self.connection.execute(
                "SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? "
                "EXCEPT SELECT objectid FROM parcels WHERE snapshot_id=? ORDER BY objectid LIMIT 20",
                (snapshot_id, snapshot_id),
            ).fetchall()
            extra = self.connection.execute(
                "SELECT objectid FROM parcels WHERE snapshot_id=? "
                "EXCEPT SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? ORDER BY objectid LIMIT 20",
                (snapshot_id, snapshot_id),
            ).fetchall()
            if expected is not None and inventory_count != expected:
                errors.append(f"persisted inventory contains {inventory_count} IDs; expected {expected}")
            if missing:
                errors.append("inventory IDs missing from parcels: " + ", ".join(str(row[0]) for row in missing))
            if extra:
                errors.append("parcel IDs absent from inventory: " + ", ".join(str(row[0]) for row in extra))
        for issue in self.connection.execute("SELECT severity,message FROM ingestion_issues WHERE snapshot_id=?", (snapshot_id,)):
            (errors if issue[0] == "error" else warnings).append(issue[1])
        for parcel in self.connection.execute("SELECT objectid,raw_attrs_json,raw_feature_json,geometry_json,geom_format,min_x,max_x,min_y,max_y FROM parcels WHERE snapshot_id=?", (snapshot_id,)):
            try:
                json.loads(parcel["raw_attrs_json"])
                json.loads(parcel["raw_feature_json"])
                if parcel["geom_format"] == "rings_json" and parcel["geometry_json"] is not None:
                    geometry = json.loads(parcel["geometry_json"])
                    geometry_error = _polygon_validation_error(geometry)
                    if geometry_error:
                        errors.append(f"objectid {parcel['objectid']}: {geometry_error}")
                elif parcel["geom_format"] == "rings_json":
                    errors.append(f"objectid {parcel['objectid']}: polygon geometry is missing")
            except (TypeError, ValueError) as exc:
                errors.append(f"objectid {parcel['objectid']}: invalid JSON ({exc})")
            bounds = parcel["min_x"], parcel["max_x"], parcel["min_y"], parcel["max_y"]
            if any(v is not None and not math.isfinite(float(v)) for v in bounds):
                errors.append(f"objectid {parcel['objectid']}: invalid bbox")
        integrity = self.integrity_check(snapshot_id)
        if not integrity["ok"]:
            errors.extend(integrity["errors"])
        return {"ok": not errors, "snapshot_id": snapshot_id, "count": count, "expected_count": expected, "errors": errors, "warnings": warnings}

    def finalize_snapshot(self, snapshot_id: int) -> Snapshot:
        self._building(snapshot_id)
        report = self.validate_snapshot(snapshot_id)
        now = _now()
        failed = not report["ok"]
        with self.transaction() as conn:
            if failed:
                conn.execute("UPDATE snapshots SET state='failed',validation_json=?,finalized_at=? WHERE snapshot_id=?", (_json_value(report, field="validation"), now, snapshot_id))
                conn.execute("UPDATE ingestion_runs SET state='failed',finished_at=?,error=? WHERE snapshot_id=? AND state='running'", (now, "snapshot validation failed", snapshot_id))
            else:
                conn.execute("UPDATE snapshots SET state='ready',received_count=?,validation_json=?,finalized_at=? WHERE snapshot_id=?", (report["count"], _json_value(report, field="validation"), now, snapshot_id))
                conn.execute("UPDATE ingestion_runs SET state='complete',finished_at=?,received_count=? WHERE snapshot_id=? AND state='running'", (now, report["count"], snapshot_id))
        if failed:
            raise SnapshotValidationError("snapshot validation failed: " + "; ".join(report["errors"]))
        return self.snapshot(snapshot_id)

    def snapshot(self, snapshot_id: int) -> Snapshot:
        row = self._snapshot_row(snapshot_id)
        return Snapshot(int(row["snapshot_id"]), row["state"], row["source"], row["expected_count"], int(row["received_count"]), float(row["created_at"]), row["finalized_at"])

    def snapshot_metadata(self, snapshot_id: int) -> Dict[str, Any]:
        row = self._snapshot_row(snapshot_id)
        try:
            value = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError) as exc:
            raise StoreCorruptError(f"snapshot {snapshot_id} has invalid metadata JSON") from exc
        return dict(value) if isinstance(value, Mapping) else {}

    def update_snapshot_metadata(self, snapshot_id: int, metadata: Mapping[str, Any]) -> None:
        self._building(snapshot_id)
        with self.transaction() as conn:
            conn.execute(
                "UPDATE snapshots SET metadata_json=? WHERE snapshot_id=?",
                (_json_value(metadata, field="metadata"), snapshot_id),
            )

    def object_ids(self, snapshot_id: int) -> Tuple[int, ...]:
        self._snapshot_row(snapshot_id)
        return tuple(
            int(row[0])
            for row in self.connection.execute(
                "SELECT objectid FROM parcels WHERE snapshot_id=? ORDER BY objectid", (snapshot_id,)
            )
        )

    def find_resumable_snapshot(self, *, source: str, expected_count: int, inventory_hash: str) -> Optional[int]:
        rows = self.connection.execute(
            "SELECT snapshot_id,metadata_json FROM snapshots WHERE state='building' AND source=? AND expected_count=? ORDER BY snapshot_id DESC",
            (source, expected_count),
        )
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(metadata, Mapping) and metadata.get("inventory_hash") == inventory_hash:
                return int(row["snapshot_id"])
        return None

    def fail_snapshot(self, snapshot_id: int, error: str) -> Snapshot:
        self._building(snapshot_id)
        now = _now()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE snapshots SET state='failed',finalized_at=? WHERE snapshot_id=?",
                (now, snapshot_id),
            )
            conn.execute(
                "UPDATE ingestion_runs SET state='failed',finished_at=?,error=? WHERE snapshot_id=? AND state='running'",
                (now, error, snapshot_id),
            )
        return self.snapshot(snapshot_id)

    def content_hash(self, snapshot_id: int) -> str:
        """Hash the canonical raw ArcGIS feature array without loading it all."""
        self._snapshot_row(snapshot_id)
        digest = hashlib.sha256()
        digest.update(b"[")
        first = True
        for row in self.connection.execute(
            "SELECT raw_feature_json FROM parcels WHERE snapshot_id=? ORDER BY objectid", (snapshot_id,)
        ):
            if not first:
                digest.update(b",")
            first = False
            digest.update(str(row[0]).encode("utf-8"))
        digest.update(b"]")
        return digest.hexdigest()

    finalize = finalize_snapshot

    def activate(self, snapshot_id: int) -> Snapshot:
        row = self._snapshot_row(snapshot_id)
        if row["state"] not in {"ready", "active", "retired"}:
            raise SnapshotStateError(f"snapshot {snapshot_id} is {row['state']} and cannot be activated")
        with self.transaction() as conn:
            now = _now()
            conn.execute("UPDATE snapshots SET state='retired' WHERE state='active' AND snapshot_id<>?", (snapshot_id,))
            conn.execute("UPDATE snapshot_activations SET deactivated_at=? WHERE deactivated_at IS NULL", (now,))
            conn.execute("UPDATE snapshots SET state='active' WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("INSERT INTO snapshot_activations(snapshot_id,activated_at) VALUES(?,?)", (snapshot_id, now))
            conn.execute("INSERT INTO meta(key,value) VALUES('active_snapshot_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(snapshot_id),))
        return self.snapshot(snapshot_id)

    activate_snapshot = activate
    set_active_snapshot = activate

    def rollback(self, snapshot_id: Optional[int] = None) -> Snapshot:
        if snapshot_id is None:
            active = self.active_snapshot_id()
            rows = self.connection.execute("SELECT snapshot_id FROM snapshot_activations WHERE snapshot_id<>? ORDER BY activation_id DESC", (active or -1,)).fetchall()
            if not rows:
                raise SnapshotStateError("no previous snapshot is available for rollback")
            snapshot_id = int(rows[0][0])
        return self.activate(snapshot_id)

    def active_snapshot_id(self) -> Optional[int]:
        row = self.connection.execute("SELECT value FROM meta WHERE key='active_snapshot_id'").fetchone()
        return int(row[0]) if row else None

    def status(self, snapshot_id: Optional[int] = None) -> Dict[str, Any]:
        snapshots = [self._snapshot_summary(row) for row in self.connection.execute("SELECT * FROM snapshots ORDER BY snapshot_id")]
        result: Dict[str, Any] = {"path": str(self.path), "schema_version": SCHEMA_VERSION, "rtree_available": self.rtree_available, "active_snapshot_id": self.active_snapshot_id(), "snapshots": snapshots}
        if snapshot_id is not None:
            result["snapshot"] = self._snapshot_summary(self._snapshot_row(snapshot_id))
            result["count"] = self.count(snapshot_id)
        return result

    @staticmethod
    def _snapshot_summary(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        metadata_raw = result.pop("metadata_json", None)
        validation_raw = result.pop("validation_json", None)
        try:
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        except (TypeError, ValueError):
            metadata = {"error": "invalid snapshot metadata JSON"}
        try:
            validation = json.loads(validation_raw) if validation_raw else None
        except (TypeError, ValueError):
            validation = {"ok": False, "errors": ["invalid validation JSON"]}
        result["metadata"] = metadata.get("manifest_summary", metadata)
        result["validation"] = validation
        return result

    get_status = status

    def count(self, snapshot_id: Optional[int] = None) -> int:
        snapshot_id = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if snapshot_id is None:
            return 0
        return int(self.connection.execute("SELECT COUNT(*) FROM parcels WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0])

    def list_parcels(self, snapshot_id: Optional[int] = None, *, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        snapshot_id = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if snapshot_id is None:
            return []
        sql = "SELECT * FROM parcels WHERE snapshot_id=? ORDER BY objectid"
        params: List[Any] = [snapshot_id]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        return [self._parcel_dict(row) for row in self.connection.execute(sql, params)]

    def search_parcels(
        self,
        snapshot_id: Optional[int] = None,
        *,
        village: Optional[str] = None,
        ward: Optional[str] = None,
        min_area_sqm: Optional[float] = None,
        max_area_sqm: Optional[float] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return parcels matching structured, SQL-backed filters.

        Results are ordered by ObjectID for repeatability.  This is deliberately
        a factual filter: no fuzzy text matching or inferred planning status is
        performed here.
        """
        snapshot_id = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if snapshot_id is None:
            return []
        self._snapshot_row(snapshot_id)
        min_area = _number(min_area_sqm, field="min_area_sqm")
        max_area = _number(max_area_sqm, field="max_area_sqm")
        if min_area is not None and max_area is not None and min_area > max_area:
            raise ValueError("min_area_sqm cannot exceed max_area_sqm")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise ValueError("limit must be a non-negative integer or None")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        clauses = ["snapshot_id=?"]
        params: List[Any] = [snapshot_id]
        if village is not None:
            if not isinstance(village, str):
                raise ValueError("village must be a string")
            clauses.append("village=?")
            params.append(_identity_text(village, uppercase=True))
        if ward is not None:
            if not isinstance(ward, str):
                raise ValueError("ward must be a string")
            clauses.append("ward=?")
            params.append(_identity_text(ward, uppercase=True))
        if min_area is not None:
            clauses.append("area_app_sqm>=?")
            params.append(min_area)
        if max_area is not None:
            clauses.append("area_app_sqm<=?")
            params.append(max_area)
        sql = "SELECT * FROM parcels WHERE " + " AND ".join(clauses) + " ORDER BY objectid"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            # SQLite requires a LIMIT when OFFSET is present.
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        return [self._json_safe_parcel(self._parcel_dict(row)) for row in self.connection.execute(sql, params)]

    search = search_parcels

    def lookup(self, village: str, cts_no: str, *, snapshot_id: Optional[int] = None) -> List[Dict[str, Any]]:
        snapshot_id = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if snapshot_id is None:
            return []
        rows = self.connection.execute(
            "SELECT * FROM parcels WHERE snapshot_id=? AND village=? AND cts_no=? ORDER BY objectid",
            (snapshot_id, _identity_text(village, uppercase=True), _identity_text(cts_no, uppercase=True)),
        )
        return [self._parcel_dict(row) for row in rows]

    lookup_exact = lookup

    def duplicate_identity_groups(self, snapshot_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List village/CTS groups containing more than one source feature."""
        snapshot_id = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if snapshot_id is None:
            return []
        self._snapshot_row(snapshot_id)
        grouped = self.connection.execute(
            """SELECT village, cts_no, COUNT(*) AS feature_count,
                      GROUP_CONCAT(objectid) AS objectids
               FROM (
                   SELECT village, cts_no, objectid FROM parcels
                   WHERE snapshot_id=? AND village IS NOT NULL AND cts_no IS NOT NULL
                   ORDER BY objectid
               )
               GROUP BY village, cts_no HAVING COUNT(*) > 1
               ORDER BY village, cts_no""",
            (snapshot_id,),
        )
        result: List[Dict[str, Any]] = []
        for group in grouped:
            objectids = [int(value) for value in str(group["objectids"]).split(",")]
            result.append({"snapshot_id": snapshot_id, "village": group["village"], "cts_no": group["cts_no"], "feature_count": int(group["feature_count"]), "objectids": objectids})
        return result

    def diff_snapshots(self, old_id: int, new_id: int) -> Dict[str, Any]:
        """Compare source features between two snapshots by ObjectID.

        ObjectID is used only as the source feature key.  Identity fields are
        compared separately so an ObjectID reused for a different village/CTS
        is visible instead of being mistaken for an unchanged parcel.
        """
        self._snapshot_row(old_id)
        self._snapshot_row(new_id)
        added = [int(row[0]) for row in self.connection.execute(
            "SELECT objectid FROM parcels WHERE snapshot_id=? EXCEPT SELECT objectid FROM parcels WHERE snapshot_id=? ORDER BY objectid",
            (new_id, old_id),
        )]
        removed = [int(row[0]) for row in self.connection.execute(
            "SELECT objectid FROM parcels WHERE snapshot_id=? EXCEPT SELECT objectid FROM parcels WHERE snapshot_id=? ORDER BY objectid",
            (old_id, new_id),
        )]
        changed = [
            int(row[0])
            for row in self.connection.execute(
                """SELECT old.objectid FROM parcels old JOIN parcels new ON new.objectid=old.objectid
                   WHERE old.snapshot_id=? AND new.snapshot_id=? AND (
                       old.raw_feature_json IS NOT new.raw_feature_json OR
                       old.raw_attrs_json IS NOT new.raw_attrs_json OR
                       old.geometry_json IS NOT new.geometry_json OR
                       old.geom_format IS NOT new.geom_format OR old.village IS NOT new.village OR
                       old.cts_no IS NOT new.cts_no OR old.ward IS NOT new.ward OR
                       old.type IS NOT new.type OR old.area_app_sqm IS NOT new.area_app_sqm)
                   ORDER BY old.objectid""",
                (old_id, new_id),
            )
        ]
        identity_changes = [
            {
                "objectid": int(row[0]),
                "old": {"village": row[1], "cts_no": row[2]},
                "new": {"village": row[3], "cts_no": row[4]},
            }
            for row in self.connection.execute(
                """SELECT old.objectid,old.village,old.cts_no,new.village,new.cts_no
                   FROM parcels old JOIN parcels new ON new.objectid=old.objectid
                   WHERE old.snapshot_id=? AND new.snapshot_id=? AND
                         (old.village IS NOT new.village OR old.cts_no IS NOT new.cts_no)
                   ORDER BY old.objectid""",
                (old_id, new_id),
            )
        ]
        old_count = self.count(old_id)
        new_count = self.count(new_id)
        old_duplicate_count = len(self.duplicate_identity_groups(old_id))
        new_duplicate_count = len(self.duplicate_identity_groups(new_id))
        return {
            "old_snapshot_id": old_id,
            "new_snapshot_id": new_id,
            "added_objectids": added,
            "removed_objectids": removed,
            "changed_objectids": changed,
            "added": added,
            "removed": removed,
            "changed": changed,
            "identity_changes": identity_changes,
            "old_count": old_count,
            "new_count": new_count,
            "old_duplicate_identity_group_count": old_duplicate_count,
            "new_duplicate_identity_group_count": new_duplicate_count,
            "duplicate_identity_group_counts": {"old": old_duplicate_count, "new": new_duplicate_count},
        }

    diff = diff_snapshots

    def parcels_in_bbox(self, min_x: float, max_x: float, min_y: float, max_y: float, *, snapshot_id: Optional[int] = None) -> List[Dict[str, Any]]:
        snapshot_id = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if snapshot_id is None:
            return []
        if self.rtree_available:
            rows = self.connection.execute("""SELECT p.* FROM parcels p JOIN parcel_bbox_map m ON m.snapshot_id=p.snapshot_id AND m.objectid=p.objectid
                JOIN parcel_bbox b ON b.bbox_id=m.bbox_id WHERE p.snapshot_id=? AND b.max_x>=? AND b.min_x<=? AND b.max_y>=? AND b.min_y<=? ORDER BY p.objectid""", (snapshot_id, min_x, max_x, min_y, max_y))
        else:
            rows = self.connection.execute("SELECT * FROM parcels WHERE snapshot_id=? AND max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? ORDER BY objectid", (snapshot_id, min_x, max_x, min_y, max_y))
        return [self._parcel_dict(row) for row in rows]

    @staticmethod
    def _parcel_dict(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        try:
            result["raw_attrs"] = json.loads(result["raw_attrs_json"])
        except (TypeError, ValueError) as exc:
            raise StoreCorruptError(f"invalid raw_attrs_json for {result.get('objectid')}") from exc
        if result.get("geometry_json") is not None and result.get("geom_format") == "rings_json":
            try:
                result["geometry"] = json.loads(result["geometry_json"])
            except (TypeError, ValueError) as exc:
                raise StoreCorruptError(f"invalid geometry_json for {result.get('objectid')}") from exc
        else:
            result["geometry"] = result.get("geometry_json")
        if result.get("geom_format") == "rings_json" and isinstance(result.get("geometry"), Mapping):
            result["rings"] = result["geometry"].get("rings", result["geometry"].get("coordinates"))
        elif result.get("geom_format") == "rings_json":
            result["rings"] = result.get("geometry")
        return result

    @staticmethod
    def _json_safe_parcel(parcel: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(parcel)
        for key, value in list(result.items()):
            if isinstance(value, bytes):
                result[key] = value.hex()
        return result

    def integrity_check(self, snapshot_id: Optional[int] = None) -> Dict[str, Any]:
        errors: List[str] = []
        result = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            errors.append(str(result))
        fk = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        errors.extend("foreign key: " + repr(tuple(row)) for row in fk)
        if self.rtree_available:
            if snapshot_id is not None:
                missing = self.connection.execute("""SELECT p.objectid FROM parcels p LEFT JOIN parcel_bbox_map m ON m.snapshot_id=p.snapshot_id AND m.objectid=p.objectid
                    WHERE p.snapshot_id=? AND p.min_x IS NOT NULL AND m.bbox_id IS NULL""", (snapshot_id,)).fetchall()
                errors.extend(f"missing bbox index for objectid {row[0]}" for row in missing)
            try:
                rtree_result = self.connection.execute("SELECT rtreecheck('parcel_bbox')").fetchone()[0]
                if rtree_result != "ok":
                    errors.append("rtreecheck: " + str(rtree_result))
            except sqlite3.DatabaseError as exc:
                errors.append("rtreecheck failed: " + str(exc))
        return {"ok": not errors, "errors": errors}


def open_store(path: Union[str, os.PathLike[str]]) -> SnapshotStore:
    return SnapshotStore.open(path)


create_or_open = open_store


__all__ = [
    "SCHEMA_VERSION",
    "Snapshot",
    "SnapshotStateError",
    "SnapshotStore",
    "SnapshotValidationError",
    "SpatialStoreError",
    "StoreCorruptError",
    "StoreReadOnlyError",
    "create_or_open",
    "open_store",
]
