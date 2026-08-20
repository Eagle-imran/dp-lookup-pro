"""SQLite lifecycle and query repository for plot-intelligence builds."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union, cast

from dp_lookup.intelligence.models import IntelligenceBuild, PlotIntelligence

SCHEMA_VERSION = 1


class IntelligenceStateError(RuntimeError):
    """A derived build lifecycle transition is unsafe."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


SCHEMA = """
CREATE TABLE IF NOT EXISTS intelligence_meta (
 key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intelligence_builds (
 build_id INTEGER PRIMARY KEY AUTOINCREMENT,
 state TEXT NOT NULL CHECK(state IN ('building','ready','active','retired','failed')),
 scope TEXT NOT NULL CHECK(scope IN ('full','sample')),
 parcel_snapshot_id INTEGER NOT NULL,
 planning_snapshot_id INTEGER NOT NULL,
 algorithm_version TEXT NOT NULL,
 expected_count INTEGER NOT NULL,
 record_count INTEGER NOT NULL DEFAULT 0,
 source_fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL,
 finalized_at TEXT,
 validation_json TEXT,
 error TEXT
);
CREATE INDEX IF NOT EXISTS intelligence_build_sources
 ON intelligence_builds(parcel_snapshot_id,planning_snapshot_id,algorithm_version,state);
CREATE TABLE IF NOT EXISTS plot_intelligence (
 build_id INTEGER NOT NULL REFERENCES intelligence_builds(build_id) ON DELETE CASCADE,
 village TEXT NOT NULL,
 cts_no TEXT NOT NULL,
 ward TEXT,
 source_objectids_json TEXT NOT NULL,
 feature_part_count INTEGER NOT NULL,
 area_sqm REAL NOT NULL,
 area_source TEXT NOT NULL,
 geometry_area_sqm REAL NOT NULL,
 centroid_x REAL NOT NULL,
 centroid_y REAL NOT NULL,
 primary_zone TEXT NOT NULL,
 zones_json TEXT NOT NULL,
 reservations_json TEXT NOT NULL,
 designations_json TEXT NOT NULL,
 modifications_json TEXT NOT NULL,
 metro_buffer TEXT NOT NULL,
 crz_status TEXT NOT NULL,
 encumbered_area_sqm REAL NOT NULL,
 encumbered_percent REAL NOT NULL,
 net_unencumbered_sqm REAL NOT NULL,
 net_unencumbered_percent REAL NOT NULL,
 road_name TEXT NOT NULL,
 road_width TEXT NOT NULL,
 road_distance_m REAL,
 neighbour_count INTEGER NOT NULL,
 neighbours_json TEXT NOT NULL,
 evidence_summary_json TEXT NOT NULL,
 warnings_json TEXT NOT NULL,
 confidence TEXT NOT NULL CHECK(confidence IN ('verified','qualified','review_required')),
 source_refs_json TEXT NOT NULL,
 facts_hash TEXT NOT NULL,
 calculated_at TEXT NOT NULL,
 PRIMARY KEY(build_id,village,cts_no)
);
CREATE INDEX IF NOT EXISTS plot_intelligence_search
 ON plot_intelligence(build_id,village,ward,area_sqm,primary_zone,encumbered_percent);
CREATE INDEX IF NOT EXISTS plot_intelligence_road
 ON plot_intelligence(build_id,road_width,road_distance_m);
CREATE TABLE IF NOT EXISTS plot_evidence_refs (
 build_id INTEGER NOT NULL,
 village TEXT NOT NULL,
 cts_no TEXT NOT NULL,
 evidence_type TEXT NOT NULL,
 layer_id INTEGER NOT NULL,
 object_id INTEGER NOT NULL,
 role TEXT NOT NULL,
 overlap_sqm REAL,
 overlap_percent REAL,
 source_url TEXT NOT NULL,
 attributes_json TEXT NOT NULL,
 PRIMARY KEY(build_id,village,cts_no,evidence_type,layer_id,object_id),
 FOREIGN KEY(build_id,village,cts_no)
   REFERENCES plot_intelligence(build_id,village,cts_no) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS plot_evidence_layer
 ON plot_evidence_refs(build_id,layer_id,object_id);
CREATE TABLE IF NOT EXISTS intelligence_issues (
 build_id INTEGER NOT NULL REFERENCES intelligence_builds(build_id) ON DELETE CASCADE,
 village TEXT NOT NULL,
 cts_no TEXT NOT NULL,
 error TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(build_id,village,cts_no)
);
CREATE TABLE IF NOT EXISTS intelligence_activations (
 activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 build_id INTEGER NOT NULL REFERENCES intelligence_builds(build_id),
 activated_at TEXT NOT NULL,
 deactivated_at TEXT
);
"""


class IntelligenceStore:
    def __init__(self, connection: sqlite3.Connection, path: Union[str, Path]) -> None:
        self.connection = connection
        self.path = Path(path)

    @classmethod
    def open(cls, path: Union[str, Path]) -> "IntelligenceStore":
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path_obj), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(SCHEMA)
        existing = connection.execute(
            "SELECT value FROM intelligence_meta WHERE key='schema_version'"
        ).fetchone()
        if existing is not None and int(existing[0]) != SCHEMA_VERSION:
            connection.close()
            raise IntelligenceStateError(
                f"unsupported intelligence schema {existing[0]}; expected {SCHEMA_VERSION}"
            )
        connection.execute(
            "INSERT INTO intelligence_meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO NOTHING",
            (str(SCHEMA_VERSION),),
        )
        connection.commit()
        return cls(connection, path_obj)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "IntelligenceStore":
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

    def begin_build(
        self,
        *,
        parcel_snapshot_id: int,
        planning_snapshot_id: int,
        algorithm_version: str,
        expected_count: int,
        source_fingerprint: str,
        scope: str = "full",
        resume: bool = True,
    ) -> int:
        if scope not in {"full", "sample"}:
            raise ValueError("scope must be full or sample")
        if expected_count < 1:
            raise ValueError("expected_count must be positive")
        if resume:
            row = self.connection.execute(
                "SELECT build_id FROM intelligence_builds WHERE state='building' AND scope=? "
                "AND parcel_snapshot_id=? AND planning_snapshot_id=? AND algorithm_version=? "
                "AND expected_count=? AND source_fingerprint=? ORDER BY build_id DESC LIMIT 1",
                (
                    scope,
                    parcel_snapshot_id,
                    planning_snapshot_id,
                    algorithm_version,
                    expected_count,
                    source_fingerprint,
                ),
            ).fetchone()
            if row is not None:
                return int(row[0])
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO intelligence_builds(state,scope,parcel_snapshot_id,planning_snapshot_id,"
                "algorithm_version,expected_count,source_fingerprint,created_at) VALUES('building',?,?,?,?,?,?,?)",
                (
                    scope,
                    parcel_snapshot_id,
                    planning_snapshot_id,
                    algorithm_version,
                    expected_count,
                    source_fingerprint,
                    _now(),
                ),
            )
        if cursor.lastrowid is None:
            raise IntelligenceStateError("SQLite did not return an intelligence build ID")
        return int(cursor.lastrowid)

    def _build_row(self, build_id: int) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM intelligence_builds WHERE build_id=?", (build_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown intelligence build {build_id}")
        return cast(sqlite3.Row, row)

    def _building(self, build_id: int) -> sqlite3.Row:
        row = self._build_row(build_id)
        if row["state"] != "building":
            raise IntelligenceStateError(f"intelligence build {build_id} is {row['state']}, not building")
        return row

    def completed_keys(self, build_id: int) -> Tuple[Tuple[str, str], ...]:
        self._build_row(build_id)
        return tuple(
            (str(row["village"]), str(row["cts_no"]))
            for row in self.connection.execute(
                "SELECT village,cts_no FROM plot_intelligence WHERE build_id=? ORDER BY village,cts_no",
                (build_id,),
            )
        )

    def upsert(self, build_id: int, plot: PlotIntelligence) -> None:
        self._building(build_id)
        values = (
            build_id,
            plot.village,
            plot.cts_no,
            plot.ward,
            _json(plot.source_objectids),
            plot.feature_part_count,
            plot.area_sqm,
            plot.area_source,
            plot.geometry_area_sqm,
            plot.centroid_x,
            plot.centroid_y,
            plot.primary_zone,
            _json(plot.zones),
            _json(plot.reservations),
            _json(plot.designations),
            _json(plot.modifications),
            plot.metro_buffer,
            plot.crz_status,
            plot.encumbered_area_sqm,
            plot.encumbered_percent,
            plot.net_unencumbered_sqm,
            plot.net_unencumbered_percent,
            plot.road_name,
            plot.road_width,
            plot.road_distance_m,
            plot.neighbour_count,
            _json(plot.neighbours),
            _json(plot.evidence_summary),
            _json(plot.warnings),
            plot.confidence,
            _json(
                tuple(
                    {key: value for key, value in ref.items() if key != "attributes"}
                    for ref in plot.source_refs
                )
            ),
            plot.facts_hash,
            plot.calculated_at,
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO plot_intelligence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
            connection.execute(
                "DELETE FROM plot_evidence_refs WHERE build_id=? AND village=? AND cts_no=?",
                (build_id, plot.village, plot.cts_no),
            )
            for ref in plot.source_refs:
                layer_id = ref.get("layer_id")
                object_id = ref.get("object_id")
                if not isinstance(layer_id, int) or not isinstance(object_id, int):
                    continue
                connection.execute(
                    "INSERT OR REPLACE INTO plot_evidence_refs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        build_id,
                        plot.village,
                        plot.cts_no,
                        str(ref.get("evidence_type") or "planning"),
                        layer_id,
                        object_id,
                        str(ref.get("role") or "source evidence"),
                        ref.get("overlap_sqm"),
                        ref.get("overlap_percent"),
                        str(ref.get("source_url") or ""),
                        _json(ref.get("attributes") or {}),
                    ),
                )
            connection.execute(
                "UPDATE intelligence_builds SET record_count=(SELECT COUNT(*) FROM plot_intelligence "
                "WHERE build_id=?) WHERE build_id=?",
                (build_id, build_id),
            )
            connection.execute(
                "DELETE FROM intelligence_issues WHERE build_id=? AND village=? AND cts_no=?",
                (build_id, plot.village, plot.cts_no),
            )

    def record_issue(self, build_id: int, village: str, cts_no: str, error: str) -> None:
        self._building(build_id)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO intelligence_issues(build_id,village,cts_no,error,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(build_id,village,cts_no) DO UPDATE SET error=excluded.error,updated_at=excluded.updated_at",
                (build_id, village, cts_no, str(error), _now()),
            )

    def verify(self, build_id: int) -> Dict[str, Any]:
        row = self._build_row(build_id)
        actual = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM plot_intelligence WHERE build_id=?", (build_id,)
            ).fetchone()[0]
        )
        bad_hashes = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM plot_intelligence WHERE build_id=? AND facts_hash=''", (build_id,)
            ).fetchone()[0]
        )
        duplicate_refs = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM (SELECT village,cts_no,evidence_type,layer_id,object_id,COUNT(*) n "
                "FROM plot_evidence_refs WHERE build_id=? GROUP BY village,cts_no,evidence_type,layer_id,object_id "
                "HAVING n>1)",
                (build_id,),
            ).fetchone()[0]
        )
        issue_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM intelligence_issues WHERE build_id=?", (build_id,)
            ).fetchone()[0]
        )
        errors: List[str] = []
        if actual != int(row["expected_count"]):
            errors.append(f"expected {row['expected_count']} plot records but found {actual}")
        if bad_hashes:
            errors.append(f"{bad_hashes} plot records have no facts hash")
        if duplicate_refs:
            errors.append(f"{duplicate_refs} duplicate source-reference groups exist")
        if issue_count:
            errors.append(f"{issue_count} plots have unresolved derivation errors")
        return {
            "ok": not errors,
            "build_id": build_id,
            "scope": str(row["scope"]),
            "expected_count": int(row["expected_count"]),
            "record_count": actual,
            "source_reference_count": int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM plot_evidence_refs WHERE build_id=?", (build_id,)
                ).fetchone()[0]
            ),
            "issue_count": issue_count,
            "errors": errors,
        }

    def finalize(self, build_id: int) -> IntelligenceBuild:
        self._building(build_id)
        report = self.verify(build_id)
        state = "ready" if report["ok"] else "failed"
        with self.transaction() as connection:
            connection.execute(
                "UPDATE intelligence_builds SET state=?,record_count=?,finalized_at=?,validation_json=?,error=? "
                "WHERE build_id=?",
                (
                    state,
                    report["record_count"],
                    _now(),
                    _json(report),
                    None if report["ok"] else "; ".join(report["errors"]),
                    build_id,
                ),
            )
        if not report["ok"]:
            raise IntelligenceStateError("intelligence build validation failed: " + "; ".join(report["errors"]))
        return self.build(build_id)

    def fail(self, build_id: int, error: str) -> IntelligenceBuild:
        self._building(build_id)
        with self.transaction() as connection:
            connection.execute(
                "UPDATE intelligence_builds SET state='failed',finalized_at=?,error=? WHERE build_id=?",
                (_now(), str(error), build_id),
            )
        return self.build(build_id)

    def active_build_id(self) -> Optional[int]:
        row = self.connection.execute(
            "SELECT build_id FROM intelligence_activations WHERE deactivated_at IS NULL "
            "ORDER BY activation_id DESC LIMIT 1"
        ).fetchone()
        return int(row[0]) if row else None

    def activate(self, build_id: int) -> IntelligenceBuild:
        row = self._build_row(build_id)
        if row["state"] not in {"ready", "active", "retired"}:
            raise IntelligenceStateError("only a verified intelligence build can be activated")
        if row["scope"] != "full":
            raise IntelligenceStateError("sample intelligence builds cannot be activated")
        report = self.verify(build_id)
        if not report["ok"]:
            raise IntelligenceStateError("intelligence build no longer passes verification")
        with self.transaction() as connection:
            now = _now()
            connection.execute(
                "UPDATE intelligence_builds SET state='retired' WHERE state='active' AND build_id<>?",
                (build_id,),
            )
            connection.execute(
                "UPDATE intelligence_activations SET deactivated_at=? WHERE deactivated_at IS NULL",
                (now,),
            )
            connection.execute("UPDATE intelligence_builds SET state='active' WHERE build_id=?", (build_id,))
            connection.execute(
                "INSERT INTO intelligence_activations(build_id,activated_at) VALUES(?,?)", (build_id, now)
            )
        return self.build(build_id)

    def build(self, build_id: int) -> IntelligenceBuild:
        row = self._build_row(build_id)
        return IntelligenceBuild(
            build_id=int(row["build_id"]),
            state=str(row["state"]),
            scope=str(row["scope"]),
            parcel_snapshot_id=int(row["parcel_snapshot_id"]),
            planning_snapshot_id=int(row["planning_snapshot_id"]),
            algorithm_version=str(row["algorithm_version"]),
            expected_count=int(row["expected_count"]),
            record_count=int(row["record_count"]),
            created_at=str(row["created_at"]),
            finalized_at=row["finalized_at"],
            source_fingerprint=str(row["source_fingerprint"]),
            validation=cast(Mapping[str, Any], _loads(row["validation_json"], {})),
        )

    def status(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "active_build_id": self.active_build_id(),
            "builds": [
                self.build(int(row[0])).to_dict()
                for row in self.connection.execute("SELECT build_id FROM intelligence_builds ORDER BY build_id")
            ],
        }

    def _selected_build(self, build_id: Optional[int]) -> int:
        selected = build_id if build_id is not None else self.active_build_id()
        if selected is None:
            raise IntelligenceStateError("no active plot-intelligence build is available")
        self._build_row(selected)
        return selected

    @staticmethod
    def _plot(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        for key in (
            "source_objectids",
            "zones",
            "reservations",
            "designations",
            "modifications",
            "neighbours",
            "evidence_summary",
            "warnings",
            "source_refs",
        ):
            result[key] = _loads(result.pop(f"{key}_json"), [] if key != "evidence_summary" else {})
        return result

    def get(
        self, village: str, cts_no: str, *, build_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        selected = self._selected_build(build_id)
        row = self.connection.execute(
            "SELECT * FROM plot_intelligence WHERE build_id=? AND village=? AND cts_no=?",
            (selected, village.strip().upper(), cts_no.strip().upper()),
        ).fetchone()
        if row is None:
            return None
        result = self._plot(row)
        result["source_refs"] = [
            {
                **{key: value for key, value in dict(ref).items() if key != "attributes_json"},
                "attributes": _loads(ref["attributes_json"], {}),
            }
            for ref in self.connection.execute(
                "SELECT evidence_type,layer_id,object_id,role,overlap_sqm,overlap_percent,"
                "source_url,attributes_json FROM plot_evidence_refs "
                "WHERE build_id=? AND village=? AND cts_no=? ORDER BY layer_id,object_id",
                (selected, village.strip().upper(), cts_no.strip().upper()),
            )
        ]
        return result

    def search(
        self,
        *,
        build_id: Optional[int] = None,
        village: Optional[str] = None,
        ward: Optional[str] = None,
        min_area_sqm: Optional[float] = None,
        max_area_sqm: Optional[float] = None,
        zone: Optional[str] = None,
        reservations: Optional[bool] = None,
        designations: Optional[bool] = None,
        max_encumbered_percent: Optional[float] = None,
        road_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        selected = self._selected_build(build_id)
        if limit < 1 or limit > 10_000 or offset < 0:
            raise ValueError("limit must be 1..10000 and offset must be non-negative")
        clauses = ["build_id=?"]
        params: List[Any] = [selected]
        filters = (
            (village, "village=?", lambda value: str(value).strip().upper()),
            (ward, "ward=?", lambda value: str(value).strip().upper()),
            (min_area_sqm, "area_sqm>=?", float),
            (max_area_sqm, "area_sqm<=?", float),
            (zone, "primary_zone=?", lambda value: str(value).strip().upper()),
            (max_encumbered_percent, "encumbered_percent<=?", float),
        )
        for value, clause, normalizer in filters:
            if value is not None:
                clauses.append(clause)
                params.append(normalizer(value))
        if reservations is not None:
            clauses.append("reservations_json " + ("<> '[]'" if reservations else "= '[]'"))
        if designations is not None:
            clauses.append("designations_json " + ("<> '[]'" if designations else "= '[]'"))
        if road_name:
            clauses.append("road_name LIKE ? ESCAPE '\\'")
            escaped = str(road_name).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        params.extend([limit, offset])
        rows = self.connection.execute(
            "SELECT * FROM plot_intelligence WHERE " + " AND ".join(clauses) +
            " ORDER BY area_sqm DESC,village,cts_no LIMIT ? OFFSET ?",
            params,
        )
        return [self._plot(row) for row in rows]

    def compare(
        self, identities: Sequence[Tuple[str, str]], *, build_id: Optional[int] = None
    ) -> Dict[str, Any]:
        if len(identities) < 2 or len(identities) > 20:
            raise ValueError("compare requires between 2 and 20 plots")
        selected = self._selected_build(build_id)
        records = []
        missing = []
        for village, cts_no in identities:
            record = self.get(village, cts_no, build_id=selected)
            if record is None:
                missing.append({"village": village, "cts_no": cts_no})
            else:
                records.append(record)
        return {
            "build_id": selected,
            "records": records,
            "missing": missing,
            "comparison_fields": (
                "area_sqm",
                "primary_zone",
                "encumbered_percent",
                "net_unencumbered_sqm",
                "road_name",
                "road_width",
                "road_distance_m",
                "neighbour_count",
                "confidence",
            ),
        }


__all__ = ["SCHEMA_VERSION", "IntelligenceStateError", "IntelligenceStore"]
