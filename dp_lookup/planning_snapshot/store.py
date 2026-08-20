"""SQLite storage for complete, audited planning-layer snapshots.

This store is intentionally independent from the parcel database.  A snapshot
is built in a transaction-safe ``building`` state, validated, and only then
published as ``ready``/``active``.  Feature payloads are never normalised or
discarded; the canonical hash is an additional audit value.
"""

from __future__ import annotations

import contextlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union, cast

from dp_lookup.planning_evidence.registry import canonical_layer_id
from dp_lookup.planning_snapshot.models import (
    PlanningFeature,
    PlanningLayerSnapshot,
    PlanningSnapshot,
    PlanningSnapshotStateError,
    PlanningSnapshotValidationError,
    canonical_json,
    sha256_json,
    utc_now,
)

SCHEMA_VERSION = 1


def _json(value: Any, field: str) -> str:
    if isinstance(value, str):
        try:
            json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is not valid JSON") from exc
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as JSON") from exc


def _canonical(value: Any, field: str) -> str:
    try:
        return canonical_json(value).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} cannot be encoded as canonical JSON") from exc


def _bbox(geometry: Any) -> Optional[Tuple[float, float, float, float]]:
    if geometry is None or isinstance(geometry, (str, bytes)):
        return None
    if isinstance(geometry, Mapping):
        if "x" in geometry and "y" in geometry:
            geometry = [[geometry["x"], geometry["y"]]]
        elif "point" in geometry:
            point = geometry["point"]
            if isinstance(point, Mapping) and "x" in point and "y" in point:
                geometry = [[point["x"], point["y"]]]
            else:
                geometry = point
        if isinstance(geometry, Mapping) and "rings" in geometry:
            geometry = geometry["rings"]
        elif isinstance(geometry, Mapping) and "coordinates" in geometry:
            geometry = geometry["coordinates"]
        elif isinstance(geometry, Mapping) and "paths" in geometry:
            geometry = geometry["paths"]
        elif isinstance(geometry, Mapping) and "points" in geometry:
            geometry = geometry["points"]
        elif isinstance(geometry, Mapping):
            return None
    points: List[Tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and not isinstance(value[0], (list, tuple, Mapping)):
                try:
                    x, y = float(value[0]), float(value[1])
                except (TypeError, ValueError, OverflowError):
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


class PlanningSnapshotStore:
    def __init__(self, connection: sqlite3.Connection, path: Union[str, Path]) -> None:
        self.connection = connection
        self.path = Path(path)
        self._rtree_available = False

    @classmethod
    def open(cls, path: Union[str, Path]) -> "PlanningSnapshotStore":
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path_obj), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO planning_meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO NOTHING", (str(SCHEMA_VERSION),))
        conn.commit()
        store = cls(conn, path_obj)
        store._init_rtree()
        return store

    create_or_open = open

    def _init_rtree(self) -> None:
        try:
            self.connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS planning_feature_rtree USING rtree(id,min_x,max_x,min_y,max_y)")
            self.connection.execute("CREATE TABLE IF NOT EXISTS planning_feature_rtree_map (id INTEGER PRIMARY KEY, snapshot_id INTEGER, canonical_layer_id INTEGER, object_id INTEGER, UNIQUE(snapshot_id,canonical_layer_id,object_id))")
            self.connection.execute("INSERT INTO planning_meta(key,value) VALUES('rtree_available','1') ON CONFLICT(key) DO UPDATE SET value='1'")
            self.connection.commit()
            self._rtree_available = True
        except sqlite3.OperationalError:
            self.connection.rollback()

    @property
    def rtree_available(self) -> bool:
        return self._rtree_available

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PlanningSnapshotStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def begin_snapshot(self, *, source_url: Optional[str] = None, metadata: Optional[Mapping[str, Any]] = None, version: Optional[int] = None) -> int:
        if version is None:
            row = self.connection.execute("SELECT COALESCE(MAX(version),0)+1 FROM planning_snapshots").fetchone()
            version = int(row[0])
        if isinstance(version, bool) or int(version) < 1:
            raise ValueError("version must be a positive integer")
        with self.transaction() as conn:
            cur = conn.execute("INSERT INTO planning_snapshots(version,state,source_url,source_metadata_json,created_at) VALUES(?,?,?,?,?)", (int(version), "building", source_url, _json(metadata or {}, "metadata"), utc_now()))
            if cur.lastrowid is None:
                raise RuntimeError("SQLite did not return a snapshot ID")
            return int(cur.lastrowid)

    def _snapshot_row(self, snapshot_id: int) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM planning_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown planning snapshot {snapshot_id}")
        return cast(sqlite3.Row, row)

    def _building(self, snapshot_id: int) -> sqlite3.Row:
        row = self._snapshot_row(snapshot_id)
        if row["state"] != "building":
            raise PlanningSnapshotStateError(f"snapshot {snapshot_id} is {row['state']}, not building")
        return row

    def find_resumable_snapshot(self, registry_hash: str) -> Optional[int]:
        """Return the newest building snapshot for one exact registry contract."""
        for row in self.connection.execute(
            "SELECT snapshot_id,source_metadata_json FROM planning_snapshots "
            "WHERE state='building' ORDER BY version DESC"
        ):
            try:
                metadata = json.loads(row["source_metadata_json"] or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(metadata, Mapping) and metadata.get("registry_hash") == registry_hash:
                return int(row["snapshot_id"])
        return None

    def update_snapshot_metadata(self, snapshot_id: int, metadata: Mapping[str, Any]) -> None:
        self._building(snapshot_id)
        with self.transaction() as conn:
            conn.execute(
                "UPDATE planning_snapshots SET source_metadata_json=? WHERE snapshot_id=?",
                (_json(metadata, "planning snapshot metadata"), snapshot_id),
            )

    def fail_snapshot(self, snapshot_id: int, error: str) -> PlanningSnapshot:
        self._building(snapshot_id)
        with self.transaction() as conn:
            conn.execute(
                "UPDATE planning_snapshots SET state='failed',finalized_at=?,complete=0,validation_json=? "
                "WHERE snapshot_id=?",
                (utc_now(), _json({"ok": False, "errors": [str(error)]}, "validation"), snapshot_id),
            )
        return self.snapshot(snapshot_id)

    def register_layer(self, snapshot_id: int, layer_id: int, *, name: str = "", geometry_type: Optional[str] = None, object_id_field: str = "OBJECTID", expected_count: Optional[int] = None, metadata: Optional[Mapping[str, Any]] = None, canonical_id: Optional[int] = None) -> int:
        self._building(snapshot_id)
        source_id = int(layer_id)
        canonical_id = int(canonical_id if canonical_id is not None else canonical_layer_id(source_id))
        if expected_count is not None and (isinstance(expected_count, bool) or expected_count < 0):
            raise ValueError("expected_count must be non-negative or None")
        if not str(object_id_field).strip():
            raise ValueError("object_id_field must not be blank")
        with self.transaction() as conn:
            existing = conn.execute("SELECT layer_id,name,geometry_type,object_id_field,metadata_json,expected_count FROM planning_layers WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, canonical_id)).fetchone()
            if existing is None:
                conn.execute("INSERT INTO planning_layers(snapshot_id,layer_id,canonical_layer_id,name,geometry_type,object_id_field,metadata_json,expected_count) VALUES(?,?,?,?,?,?,?,?)", (snapshot_id, source_id, canonical_id, str(name), geometry_type, str(object_id_field), _json(metadata or {}, "layer metadata"), expected_count))
            else:
                # Preserve the first canonical source contract; aliases enrich provenance.
                previous = json.loads(existing["metadata_json"] or "{}")
                merged = dict(previous) if isinstance(previous, Mapping) else {}
                merged.update(dict(metadata or {}))
                source_ids = set(merged.get("source_layer_ids", []))
                source_ids.add(int(existing["layer_id"]))
                source_ids.add(source_id)
                merged["source_layer_ids"] = sorted(source_ids)
                conn.execute("UPDATE planning_layers SET metadata_json=? WHERE snapshot_id=? AND canonical_layer_id=?", (_json(merged, "layer metadata"), snapshot_id, canonical_id))
        return canonical_id

    def set_layer_inventory(self, snapshot_id: int, layer_id: int, object_ids: Iterable[int]) -> int:
        canonical_id = self.register_layer(snapshot_id, layer_id)
        values = tuple(sorted(set(int(value) for value in object_ids)))
        if any(value < 0 for value in values):
            raise ValueError("object IDs must be non-negative")
        with self.transaction() as conn:
            old = tuple(int(row[0]) for row in conn.execute("SELECT object_id FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=? ORDER BY object_id", (snapshot_id, canonical_id)))
            if old and old != values:
                raise PlanningSnapshotStateError("layer inventory differs from its persisted inventory")
            conn.executemany("INSERT OR IGNORE INTO planning_layer_inventory(snapshot_id,canonical_layer_id,object_id) VALUES(?,?,?)", ((snapshot_id, canonical_id, value) for value in values))
        return len(values)

    @staticmethod
    def _feature(value: Any, object_id_field: str) -> PlanningFeature:
        if isinstance(value, PlanningFeature):
            return value
        # The downloader in ``application.planning_snapshot`` uses an
        # equivalent immutable dataclass.  Accept it without importing the
        # application module (which would pull in the HTTP client).
        if all(hasattr(value, name) for name in ("object_id", "attributes", "geometry")):
            return PlanningFeature(
                int(value.object_id),
                value.attributes,
                value.geometry,
                raw_feature=getattr(value, "raw_feature", None),
                source_layer_id=getattr(value, "layer_id", None),
            )
        if not isinstance(value, Mapping):
            raise ValueError("feature must be a mapping or PlanningFeature")
        attrs = value.get("attributes", value.get("attrs"))
        if not isinstance(attrs, Mapping):
            raise ValueError("feature attributes must be a mapping")
        object_id = value.get("object_id", value.get("objectId", attrs.get(object_id_field)))
        if object_id is None:
            raise ValueError(f"feature is missing {object_id_field}")
        geometry = value.get("geometry")
        raw = value.get("raw_feature", value)
        return PlanningFeature(int(object_id), attrs, geometry, raw_feature=raw, source_layer_id=value.get("source_layer_id"))

    def insert_batch(self, snapshot_id: int, layer_id: int, features: Iterable[Any]) -> int:
        self._building(snapshot_id)
        canonical_id = self.register_layer(snapshot_id, layer_id)
        layer = self.connection.execute("SELECT object_id_field FROM planning_layers WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, canonical_id)).fetchone()
        object_id_field = str(layer[0])
        prepared: List[Tuple[int, str, Optional[str], str, Optional[Tuple[float, float, float, float]], str]] = []
        seen: Dict[int, str] = {}
        for raw in features:
            feature = self._feature(raw, object_id_field)
            attrs_json = _json(feature.attributes, "attributes")
            geometry_json = None if feature.geometry is None else _json(feature.geometry, "geometry")
            raw_json = _json(feature.raw_feature if feature.raw_feature is not None else feature.to_dict(), "raw_feature")
            digest = sha256_json({"attributes": json.loads(attrs_json), "geometry": None if geometry_json is None else json.loads(geometry_json)})
            prior = seen.get(feature.object_id)
            if prior is not None and prior != digest:
                raise ValueError(f"conflicting duplicate object ID {feature.object_id} in batch")
            seen[feature.object_id] = digest
            prepared.append((feature.object_id, attrs_json, geometry_json, raw_json, _bbox(feature.geometry), digest))
        if not prepared:
            return 0
        with self.transaction() as conn:
            for object_id, attrs_json, geometry_json, raw_json, bbox, digest in prepared:
                existing = conn.execute("SELECT attributes_json,geometry_json FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? AND object_id=?", (snapshot_id, canonical_id, object_id)).fetchone()
                if existing is not None:
                    old_digest = sha256_json({"attributes": json.loads(existing[0]), "geometry": None if existing[1] is None else json.loads(existing[1])})
                    if old_digest != digest:
                        raise ValueError(f"conflicting duplicate object ID {object_id} for canonical layer {canonical_id}")
                    continue
                min_x, max_x, min_y, max_y = bbox or (None, None, None, None)
                conn.execute("INSERT INTO planning_features(snapshot_id,canonical_layer_id,object_id,attributes_json,geometry_json,raw_feature_json,bbox_min_x,bbox_max_x,bbox_min_y,bbox_max_y) VALUES(?,?,?,?,?,?,?,?,?,?)", (snapshot_id, canonical_id, object_id, attrs_json, geometry_json, raw_json, min_x, max_x, min_y, max_y))
            count = int(conn.execute("SELECT COUNT(*) FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, canonical_id)).fetchone()[0])
            conn.execute("UPDATE planning_layers SET received_count=? WHERE snapshot_id=? AND canonical_layer_id=?", (count, snapshot_id, canonical_id))
            if self._rtree_available:
                for object_id, _attrs, _geometry, _raw, bbox, _digest in prepared:
                    if bbox is None:
                        continue
                    min_x, max_x, min_y, max_y = bbox
                    mapped = conn.execute("SELECT id FROM planning_feature_rtree_map WHERE snapshot_id=? AND canonical_layer_id=? AND object_id=?", (snapshot_id, canonical_id, object_id)).fetchone()
                    if mapped is None:
                        cur = conn.execute("INSERT INTO planning_feature_rtree_map(snapshot_id,canonical_layer_id,object_id) VALUES(?,?,?)", (snapshot_id, canonical_id, object_id))
                        if cur.lastrowid is None:
                            raise RuntimeError("SQLite did not return an R-tree ID")
                        rid = int(cur.lastrowid)
                    else:
                        rid = int(mapped[0])
                    conn.execute("INSERT OR REPLACE INTO planning_feature_rtree(id,min_x,max_x,min_y,max_y) VALUES(?,?,?,?,?)", (rid, min_x, max_x, min_y, max_y))
        return len(prepared)

    insert_features = insert_batch

    def _layer_hash(self, snapshot_id: int, canonical_id: int) -> str:
        rows = self.connection.execute("SELECT object_id,attributes_json,geometry_json,raw_feature_json FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? ORDER BY object_id", (snapshot_id, canonical_id))
        return sha256_json([{"object_id": int(row[0]), "attributes": json.loads(row[1]), "geometry": None if row[2] is None else json.loads(row[2]), "raw_feature": json.loads(row[3])} for row in rows])

    def content_hash(self, snapshot_id: int) -> str:
        """Return the deterministic top-level hash for any built snapshot."""
        row = self._snapshot_row(snapshot_id)
        if row["content_hash"]:
            return str(row["content_hash"])
        return sha256_json([
            {"layer_id": int(item["canonical_layer_id"]), "content_hash": self._layer_hash(snapshot_id, int(item["canonical_layer_id"]))}
            for item in self.connection.execute("SELECT canonical_layer_id FROM planning_layers WHERE snapshot_id=? ORDER BY canonical_layer_id", (snapshot_id,))
        ])

    def validate(self, snapshot_id: int) -> Dict[str, Any]:
        self._snapshot_row(snapshot_id)
        errors: List[str] = []
        warnings: List[str] = []
        layers: List[Dict[str, Any]] = []
        for layer in self.connection.execute("SELECT * FROM planning_layers WHERE snapshot_id=? ORDER BY canonical_layer_id", (snapshot_id,)):
            layer_id = int(layer["canonical_layer_id"])
            count = int(self.connection.execute("SELECT COUNT(*) FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, layer_id)).fetchone()[0])
            expected = layer["expected_count"]
            inventory = int(self.connection.execute("SELECT COUNT(*) FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, layer_id)).fetchone()[0])
            layer_errors: List[str] = []
            layer_warnings: List[str] = []
            if expected is not None and count != int(expected):
                layer_errors.append(f"expected {expected} features, received {count}")
            if inventory:
                missing = self.connection.execute("SELECT object_id FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=? EXCEPT SELECT object_id FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? LIMIT 20", (snapshot_id, layer_id, snapshot_id, layer_id)).fetchall()
                extra = self.connection.execute("SELECT object_id FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? EXCEPT SELECT object_id FROM planning_layer_inventory WHERE snapshot_id=? AND canonical_layer_id=? LIMIT 20", (snapshot_id, layer_id, snapshot_id, layer_id)).fetchall()
                if missing:
                    layer_errors.append("inventory IDs missing: " + ", ".join(str(row[0]) for row in missing))
                if extra:
                    layer_errors.append("feature IDs absent from inventory: " + ", ".join(str(row[0]) for row in extra))
            for feature in self.connection.execute("SELECT object_id,attributes_json,geometry_json,bbox_min_x,bbox_max_x,bbox_min_y,bbox_max_y FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, layer_id)):
                try:
                    json.loads(feature["attributes_json"])
                    if feature["geometry_json"] is None:
                        layer_warnings.append(f"object ID {feature['object_id']}: source geometry is missing")
                    else:
                        geometry = json.loads(feature["geometry_json"])
                        if _bbox(geometry) is None:
                            layer_warnings.append(
                                f"object ID {feature['object_id']}: source geometry has no finite coordinates"
                            )
                except (TypeError, ValueError) as exc:
                    layer_errors.append(f"object ID {feature['object_id']}: invalid JSON ({exc})")
            if layer_errors:
                errors.extend(f"layer {layer_id}: {error}" for error in layer_errors)
            warnings.extend(f"layer {layer_id}: {warning}" for warning in layer_warnings)
            layers.append(
                {
                    "layer_id": layer_id,
                    "count": count,
                    "expected_count": expected,
                    "content_hash": self._layer_hash(snapshot_id, layer_id),
                    "complete": not layer_errors,
                    "errors": layer_errors,
                    "warnings": layer_warnings,
                }
            )
        return {
            "ok": not errors,
            "snapshot_id": snapshot_id,
            "layers": layers,
            "errors": errors,
            "warnings": warnings,
        }

    validate_snapshot = validate

    def finalize(self, snapshot_id: int) -> PlanningSnapshot:
        self._building(snapshot_id)
        report = self.validate(snapshot_id)
        if not report["ok"]:
            with self.transaction() as conn:
                conn.execute("UPDATE planning_snapshots SET state='failed',validation_json=?,finalized_at=?,complete=0 WHERE snapshot_id=?", (_json(report, "validation"), utc_now(), snapshot_id))
            raise PlanningSnapshotValidationError("planning snapshot validation failed: " + "; ".join(report["errors"]))
        digest = sha256_json([{"layer_id": item["layer_id"], "content_hash": item["content_hash"]} for item in report["layers"]])
        with self.transaction() as conn:
            for item in report["layers"]:
                conn.execute("UPDATE planning_layers SET content_hash=?,complete=1,received_count=? WHERE snapshot_id=? AND canonical_layer_id=?", (item["content_hash"], item["count"], snapshot_id, item["layer_id"]))
            conn.execute("UPDATE planning_snapshots SET state='ready',content_hash=?,complete=1,validation_json=?,finalized_at=? WHERE snapshot_id=?", (digest, _json(report, "validation"), utc_now(), snapshot_id))
        return self.snapshot(snapshot_id)

    finalize_snapshot = finalize

    def snapshot(self, snapshot_id: int) -> PlanningSnapshot:
        row = self._snapshot_row(snapshot_id)
        layers = tuple(self.layer_snapshot(snapshot_id, int(item["canonical_layer_id"])) for item in self.connection.execute("SELECT canonical_layer_id FROM planning_layers WHERE snapshot_id=? ORDER BY canonical_layer_id", (snapshot_id,)))
        metadata = json.loads(row["source_metadata_json"] or "{}")
        return PlanningSnapshot(int(row["snapshot_id"]), int(row["version"]), str(row["state"]), row["source_url"], str(row["created_at"]), row["finalized_at"], str(row["content_hash"]), bool(row["complete"]), layers, metadata if isinstance(metadata, Mapping) else {})

    def layer_snapshot(self, snapshot_id: int, layer_id: int) -> PlanningLayerSnapshot:
        canonical_id = canonical_layer_id(layer_id)
        row = self.connection.execute("SELECT * FROM planning_layers WHERE snapshot_id=? AND canonical_layer_id=?", (snapshot_id, canonical_id)).fetchone()
        if row is None:
            raise KeyError(f"unknown planning layer {layer_id} in snapshot {snapshot_id}")
        metadata = json.loads(row["metadata_json"] or "{}")
        return PlanningLayerSnapshot(snapshot_id, int(row["layer_id"]), canonical_id, str(row["name"]), row["geometry_type"], str(row["object_id_field"]), row["expected_count"], int(row["received_count"]), str(row["content_hash"]), bool(row["complete"]), metadata if isinstance(metadata, Mapping) else {})

    def _features_in_bbox(
        self,
        layer_id: int,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
        *,
        snapshot_id: Optional[int],
        include_archive_payload: bool,
    ) -> List[Dict[str, Any]]:
        sid = snapshot_id if snapshot_id is not None else self.active_snapshot_id()
        if sid is None:
            return []
        canonical_id = canonical_layer_id(layer_id)
        selection = "f.*" if include_archive_payload else "f.object_id,f.attributes_json,f.geometry_json"
        if self._rtree_available:
            # CROSS JOIN is deliberate: it makes SQLite begin with the R-tree
            # bounding-box search, then resolve the tiny candidate set back to
            # stored features. A regular JOIN lets the planner begin with every
            # feature in a large layer (notably CRZ), turning one parcel lookup
            # into thousands of repeated R-tree scans.
            rows = self.connection.execute(
                f"SELECT {selection} FROM planning_feature_rtree r "
                "CROSS JOIN planning_feature_rtree_map m "
                "CROSS JOIN planning_features f "
                "WHERE r.id=m.id "
                "AND m.snapshot_id=f.snapshot_id "
                "AND m.canonical_layer_id=f.canonical_layer_id "
                "AND m.object_id=f.object_id "
                "AND m.snapshot_id=? AND m.canonical_layer_id=? "
                "AND r.max_x>=? AND r.min_x<=? AND r.max_y>=? AND r.min_y<=? "
                "ORDER BY f.object_id",
                (sid, canonical_id, min_x, max_x, min_y, max_y),
            )
        else:
            rows = self.connection.execute(
                f"SELECT {selection.replace('f.', '')} FROM planning_features "
                "WHERE snapshot_id=? AND canonical_layer_id=? AND bbox_max_x>=? AND bbox_min_x<=? "
                "AND bbox_max_y>=? AND bbox_min_y<=? ORDER BY object_id",
                (sid, canonical_id, min_x, max_x, min_y, max_y),
            )
        if include_archive_payload:
            return [self._feature_dict(row) for row in rows]
        return [
            {
                "object_id": int(row["object_id"]),
                "attributes": json.loads(row["attributes_json"]),
                "geometry": None if row["geometry_json"] is None else json.loads(row["geometry_json"]),
            }
            for row in rows
        ]

    def features_in_bbox(self, layer_id: int, min_x: float, max_x: float, min_y: float, max_y: float, *, snapshot_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._features_in_bbox(
            layer_id,
            min_x,
            max_x,
            min_y,
            max_y,
            snapshot_id=snapshot_id,
            include_archive_payload=True,
        )

    parcels_in_bbox = features_in_bbox

    def query_layer(self, snapshot_id: int, layer_id: int, parcel_geometry: Any) -> List[Dict[str, Any]]:
        """Return exact geometry intersections for the local-query adapter."""
        bounds = getattr(parcel_geometry, "bounds", None)
        if not bounds or len(bounds) != 4:
            raise ValueError("parcel_geometry must expose shapely bounds")
        candidates = self._features_in_bbox(
            layer_id,
            float(bounds[0]),
            float(bounds[2]),
            float(bounds[1]),
            float(bounds[3]),
            snapshot_id=snapshot_id,
            include_archive_payload=False,
        )
        from dp_lookup.core.topology import arcgis_rings_to_geometry

        result: List[Dict[str, Any]] = []
        for candidate in candidates:
            geometry = candidate.get("geometry") or {}
            rings = geometry.get("rings") if isinstance(geometry, Mapping) else None
            if not rings:
                continue
            polygon = arcgis_rings_to_geometry(rings)
            if not polygon.is_empty and parcel_geometry.intersects(polygon):
                result.append(candidate)
        return result

    records_intersecting = query_layer

    def pin_active_snapshot(self) -> Optional[PlanningSnapshot]:
        active = self.active_snapshot_id()
        return self.snapshot(active) if active is not None else None

    active_snapshot = pin_active_snapshot

    def object_ids(self, snapshot_id: int, layer_id: int) -> Tuple[int, ...]:
        canonical_id = canonical_layer_id(layer_id)
        self._snapshot_row(snapshot_id)
        return tuple(int(row[0]) for row in self.connection.execute("SELECT object_id FROM planning_features WHERE snapshot_id=? AND canonical_layer_id=? ORDER BY object_id", (snapshot_id, canonical_id)))

    def set_inventory(self, snapshot_id: int, layer_id: int, object_ids: Iterable[int]) -> int:
        return self.set_layer_inventory(snapshot_id, layer_id, object_ids)

    @staticmethod
    def _feature_dict(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["attributes"] = json.loads(result["attributes_json"])
        result["geometry"] = None if result["geometry_json"] is None else json.loads(result["geometry_json"])
        result["raw_feature"] = json.loads(result["raw_feature_json"])
        return result

    def active_snapshot_id(self) -> Optional[int]:
        row = self.connection.execute("SELECT snapshot_id FROM planning_activations WHERE deactivated_at IS NULL ORDER BY activation_id DESC LIMIT 1").fetchone()
        return int(row[0]) if row else None

    def activate(self, snapshot_id: int) -> PlanningSnapshot:
        row = self._snapshot_row(snapshot_id)
        if row["state"] not in {"ready", "active", "retired"} or not bool(row["complete"]):
            raise PlanningSnapshotStateError("only a complete finalized snapshot can be activated")
        with self.transaction() as conn:
            now = utc_now()
            conn.execute("UPDATE planning_snapshots SET state='retired' WHERE state='active' AND snapshot_id<>?", (snapshot_id,))
            conn.execute("UPDATE planning_activations SET deactivated_at=? WHERE deactivated_at IS NULL", (now,))
            conn.execute("UPDATE planning_snapshots SET state='active' WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("INSERT INTO planning_activations(snapshot_id,activated_at) VALUES(?,?)", (snapshot_id, now))
        return self.snapshot(snapshot_id)

    activate_snapshot = activate

    def rollback(self, snapshot_id: Optional[int] = None) -> PlanningSnapshot:
        if snapshot_id is None:
            active = self.active_snapshot_id()
            row = self.connection.execute("SELECT snapshot_id FROM planning_activations WHERE snapshot_id<>? ORDER BY activation_id DESC LIMIT 1", (active if active is not None else -1,)).fetchone()
            if row is None:
                raise PlanningSnapshotStateError("no previous planning snapshot is available")
            snapshot_id = int(row[0])
        return self.activate(snapshot_id)

    def prune_failed_snapshots(self) -> Tuple[int, ...]:
        """Remove only failed, never-publishable snapshots and their indexes."""
        snapshot_ids = tuple(
            int(row[0])
            for row in self.connection.execute(
                "SELECT snapshot_id FROM planning_snapshots WHERE state='failed' ORDER BY snapshot_id"
            )
        )
        if not snapshot_ids:
            return ()
        with self.transaction() as conn:
            for snapshot_id in snapshot_ids:
                if self._rtree_available:
                    conn.execute(
                        "DELETE FROM planning_feature_rtree WHERE id IN "
                        "(SELECT id FROM planning_feature_rtree_map WHERE snapshot_id=?)",
                        (snapshot_id,),
                    )
                    conn.execute(
                        "DELETE FROM planning_feature_rtree_map WHERE snapshot_id=?",
                        (snapshot_id,),
                    )
                conn.execute(
                    "DELETE FROM planning_snapshots WHERE snapshot_id=? AND state='failed'",
                    (snapshot_id,),
                )
        return snapshot_ids

    def vacuum(self) -> None:
        """Compact free pages after an explicitly requested maintenance pass."""
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connection.execute("VACUUM")

    def _snapshot_summary(self, row: sqlite3.Row) -> Dict[str, Any]:
        metadata = json.loads(row["source_metadata_json"] or "{}")
        counts = self.connection.execute(
            "SELECT COUNT(*) AS layer_count,COALESCE(SUM(received_count),0) AS record_count "
            "FROM planning_layers WHERE snapshot_id=?",
            (int(row["snapshot_id"]),),
        ).fetchone()
        return {
            "snapshot_id": int(row["snapshot_id"]),
            "version": int(row["version"]),
            "state": str(row["state"]),
            "source_url": row["source_url"],
            "created_at": str(row["created_at"]),
            "finalized_at": row["finalized_at"],
            "content_hash": str(row["content_hash"]),
            "complete": bool(row["complete"]),
            "layer_count": int(counts["layer_count"]),
            "record_count": int(counts["record_count"]),
            "metadata": (
                metadata.get("manifest_summary", metadata)
                if isinstance(metadata, Mapping)
                else {}
            ),
        }

    def status(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "rtree_available": self._rtree_available,
            "active_snapshot_id": self.active_snapshot_id(),
            "snapshots": [
                self._snapshot_summary(row)
                for row in self.connection.execute(
                    "SELECT * FROM planning_snapshots ORDER BY version"
                )
            ],
        }


open_store = PlanningSnapshotStore.open
create_or_open = open_store

__all__ = ["SCHEMA_VERSION", "PlanningSnapshotStore", "create_or_open", "open_store"]
