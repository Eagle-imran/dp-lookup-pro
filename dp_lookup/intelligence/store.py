"""SQLite lifecycle and query repository for plot-intelligence builds."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import fields
from itertools import batched
from pathlib import Path
from typing import Any, cast

from dp_lookup.core.timestamps import utc_now
from dp_lookup.intelligence.models import IntelligenceBuild, PlotIntelligence
from dp_lookup.storage import SQLiteStore, connect, initialize_schema

SCHEMA_VERSION = 1


class IntelligenceStateError(RuntimeError):
    """A derived build lifecycle transition is unsafe."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except TypeError, ValueError:
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


def _schema_mismatch(found: str) -> IntelligenceStateError:
    return IntelligenceStateError(f"unsupported intelligence schema {found}; expected {SCHEMA_VERSION}")


class IntelligenceStore(SQLiteStore):
    @classmethod
    def open(cls, path: str | Path) -> IntelligenceStore:
        connection = connect(path)
        try:
            initialize_schema(
                connection,
                script=SCHEMA,
                meta_table="intelligence_meta",
                version=SCHEMA_VERSION,
                mismatch=_schema_mismatch,
            )
            connection.commit()
        except Exception:
            connection.close()
            raise
        return cls(connection, path)

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
        parameters: Mapping[str, Any] | None = None,
    ) -> int:
        if scope not in {"full", "sample"}:
            raise ValueError("scope must be full or sample")
        if expected_count < 1:
            raise ValueError("expected_count must be positive")
        build_parameters = dict(parameters or {})
        if resume:
            rows = self.connection.execute(
                "SELECT build_id,validation_json FROM intelligence_builds WHERE state='building' AND scope=? "
                "AND parcel_snapshot_id=? AND planning_snapshot_id=? AND algorithm_version=? "
                "AND expected_count=? AND source_fingerprint=? ORDER BY build_id DESC",
                (
                    scope,
                    parcel_snapshot_id,
                    planning_snapshot_id,
                    algorithm_version,
                    expected_count,
                    source_fingerprint,
                ),
            )
            for row in rows:
                validation = _loads(row["validation_json"], {})
                if validation.get("parameters", {}) == build_parameters:
                    return int(row["build_id"])
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO intelligence_builds(state,scope,parcel_snapshot_id,planning_snapshot_id,"
                "algorithm_version,expected_count,source_fingerprint,created_at,validation_json) "
                "VALUES('building',?,?,?,?,?,?,?,?)",
                (
                    scope,
                    parcel_snapshot_id,
                    planning_snapshot_id,
                    algorithm_version,
                    expected_count,
                    source_fingerprint,
                    utc_now(),
                    _json({"parameters": build_parameters}),
                ),
            )
        if cursor.lastrowid is None:
            raise IntelligenceStateError("SQLite did not return an intelligence build ID")
        return int(cursor.lastrowid)

    def _build_row(self, build_id: int) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM intelligence_builds WHERE build_id=?", (build_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown intelligence build {build_id}")
        return cast(sqlite3.Row, row)

    def _building(self, build_id: int) -> sqlite3.Row:
        row = self._build_row(build_id)
        if row["state"] != "building":
            raise IntelligenceStateError(f"intelligence build {build_id} is {row['state']}, not building")
        return row

    def completed_keys(self, build_id: int) -> tuple[tuple[str, str], ...]:
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
            _json(tuple({key: value for key, value in ref.items() if key != "attributes"} for ref in plot.source_refs)),
            plot.facts_hash,
            plot.calculated_at,
        )
        with self.transaction() as connection:
            existed = (
                connection.execute(
                    "SELECT 1 FROM plot_intelligence WHERE build_id=? AND village=? AND cts_no=?",
                    (build_id, plot.village, plot.cts_no),
                ).fetchone()
                is not None
            )
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
                "UPDATE intelligence_builds SET record_count=record_count+? WHERE build_id=?",
                (int(not existed), build_id),
            )
            connection.execute(
                "DELETE FROM intelligence_issues WHERE build_id=? AND village=? AND cts_no=?",
                (build_id, plot.village, plot.cts_no),
            )

    def copy_records(
        self, source_build_id: int, target_build_id: int, identities: Iterable[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        """Copy plot records and their source references unchanged.

        Returns every requested identity the target now holds, including ones an earlier,
        interrupted copy already wrote, so a caller can finish relabelling them.
        """
        self._building(target_build_id)
        self._build_row(source_build_id)
        with self.transaction() as connection:
            connection.execute(
                "CREATE TEMP TABLE IF NOT EXISTS copy_plots(village TEXT NOT NULL, cts_no TEXT NOT NULL, "
                "PRIMARY KEY(village,cts_no))"
            )
            connection.execute("DELETE FROM copy_plots")
            connection.executemany("INSERT OR IGNORE INTO copy_plots VALUES(?,?)", identities)
            for table in ("plot_intelligence", "plot_evidence_refs"):
                columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
                selected = ",".join("?" if column == "build_id" else f"t.{column}" for column in columns)
                connection.execute(
                    f"INSERT OR IGNORE INTO {table}({','.join(columns)}) SELECT {selected} FROM {table} t "
                    "JOIN copy_plots k ON k.village=t.village AND k.cts_no=t.cts_no WHERE t.build_id=?",
                    (target_build_id, source_build_id),
                )
            copied = tuple(
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    "SELECT k.village,k.cts_no FROM copy_plots k JOIN plot_intelligence p ON p.build_id=? "
                    "AND p.village=k.village AND p.cts_no=k.cts_no ORDER BY k.village,k.cts_no",
                    (target_build_id,),
                )
            )
            connection.execute("DELETE FROM copy_plots")
            connection.execute(
                "UPDATE intelligence_builds SET record_count=(SELECT COUNT(*) FROM plot_intelligence "
                "WHERE build_id=?) WHERE build_id=?",
                (target_build_id, target_build_id),
            )
        return copied

    def rewrite_facts(
        self,
        build_id: int,
        identities: Iterable[tuple[str, str]],
        change: Callable[[PlotIntelligence], PlotIntelligence],
        *,
        batch_size: int = 2000,
    ) -> int:
        """Replace the evidence summary and facts hash of existing records with ``change``'s result."""
        self._building(build_id)
        rewritten = 0
        for batch in batched(identities, batch_size, strict=False):
            updates = []
            for village, cts_no in batch:
                record = self.get(village, cts_no, build_id=build_id)
                if record is None:
                    raise IntelligenceStateError(f"plot {village} CTS {cts_no} is missing from build {build_id}")
                plot = change(PlotIntelligence(**{item.name: record[item.name] for item in fields(PlotIntelligence)}))
                updates.append((_json(plot.evidence_summary), plot.facts_hash, build_id, village, cts_no))
            with self.transaction() as connection:
                connection.executemany(
                    "UPDATE plot_intelligence SET evidence_summary_json=?,facts_hash=? "
                    "WHERE build_id=? AND village=? AND cts_no=?",
                    updates,
                )
            rewritten += len(updates)
        return rewritten

    def record_issue(self, build_id: int, village: str, cts_no: str, error: str) -> None:
        self._building(build_id)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO intelligence_issues(build_id,village,cts_no,error,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(build_id,village,cts_no) DO UPDATE SET error=excluded.error,updated_at=excluded.updated_at",
                (build_id, village, cts_no, str(error), utc_now()),
            )

    def verify(self, build_id: int) -> dict[str, Any]:
        row = self._build_row(build_id)
        actual = int(
            self.connection.execute("SELECT COUNT(*) FROM plot_intelligence WHERE build_id=?", (build_id,)).fetchone()[
                0
            ]
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
        errors: list[str] = []
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
            "parameters": _loads(row["validation_json"], {}).get("parameters", {}),
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
                    utc_now(),
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
                (utc_now(), str(error), build_id),
            )
        return self.build(build_id)

    def active_build_id(self) -> int | None:
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
            now = utc_now()
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

    def status(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "active_build_id": self.active_build_id(),
            "builds": [
                self.build(int(row[0])).to_dict()
                for row in self.connection.execute("SELECT build_id FROM intelligence_builds ORDER BY build_id")
            ],
        }

    def _selected_build(self, build_id: int | None) -> int:
        selected = build_id if build_id is not None else self.active_build_id()
        if selected is None:
            raise IntelligenceStateError("no active plot-intelligence build is available")
        self._build_row(selected)
        return selected

    @staticmethod
    def _plot(row: sqlite3.Row) -> dict[str, Any]:
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

    def get(self, village: str, cts_no: str, *, build_id: int | None = None) -> dict[str, Any] | None:
        selected = self._selected_build(build_id)
        row = self.connection.execute(
            "SELECT * FROM plot_intelligence WHERE build_id=? AND village=? AND cts_no=?",
            (selected, village.strip().upper(), cts_no.strip().upper()),
        ).fetchone()
        if row is None:
            return None
        result = self._plot(row)
        normalized_refs = [
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
        attributes = {
            (ref["evidence_type"], ref["layer_id"], ref["object_id"]): ref["attributes"] for ref in normalized_refs
        }
        result["source_refs"] = [
            {
                **ref,
                "attributes": attributes.get(
                    (str(ref.get("evidence_type") or "planning"), ref.get("layer_id"), ref.get("object_id")), {}
                ),
            }
            for ref in result["source_refs"]
        ]
        return result

    def search(
        self,
        *,
        build_id: int | None = None,
        village: str | None = None,
        ward: str | None = None,
        min_area_sqm: float | None = None,
        max_area_sqm: float | None = None,
        zone: str | None = None,
        reservations: bool | None = None,
        designations: bool | None = None,
        max_encumbered_percent: float | None = None,
        road_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        selected = self._selected_build(build_id)
        if limit < 1 or limit > 10_000 or offset < 0:
            raise ValueError("limit must be 1..10000 and offset must be non-negative")
        clauses = ["build_id=?"]
        params: list[Any] = [selected]
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
            "SELECT * FROM plot_intelligence WHERE "
            + " AND ".join(clauses)
            + " ORDER BY area_sqm DESC,village,cts_no LIMIT ? OFFSET ?",
            params,
        )
        return [self._plot(row) for row in rows]

    def compare(self, identities: Sequence[tuple[str, str]], *, build_id: int | None = None) -> dict[str, Any]:
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
