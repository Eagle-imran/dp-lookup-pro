"""SQLite registry for immutable authority documents and source selections."""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union, cast

from dp_lookup.authority.codecs import (
    crs_wkid as _crs_wkid,
)
from dp_lookup.authority.codecs import (
    digest as _hash,
)
from dp_lookup.authority.codecs import document_path as _document_path
from dp_lookup.authority.codecs import (
    file_sha256 as _file_sha256,
)
from dp_lookup.authority.codecs import (
    json_value as _json,
)
from dp_lookup.authority.codecs import (
    loads as _loads,
)
from dp_lookup.authority.codecs import (
    manifest_payload as _manifest_payload,
)
from dp_lookup.authority.codecs import (
    normalise_geometry as _normalise_geometry,
)
from dp_lookup.authority.codecs import (
    normalised_identity as _normalised_identity,
)
from dp_lookup.authority.codecs import (
    positive_area as _positive_area,
)
from dp_lookup.authority.codecs import (
    record_from_row as _codec_record_from_row,
)
from dp_lookup.authority.codecs import (
    sha256_value as _sha256_value,
)
from dp_lookup.authority.errors import AuthorityStateError, AuthorityStoreError, AuthorityValidationError
from dp_lookup.authority.models import AuthorityManifest, AuthorityRecord, SelectionPurpose, SourceStatus, SourceType
from dp_lookup.authority.schema import AUTHORITY_SCHEMA_VERSION, SCHEMA


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthorityStore:
    """Durable authority registry sharing the project's existing SQLite file."""

    def __init__(self, connection: sqlite3.Connection, path: Union[str, Path], owns_connection: bool = True) -> None:
        self.connection = connection
        self.path = Path(path)
        self._owns_connection = owns_connection

    @classmethod
    def open(cls, path: Union[str, Path], create: bool = True) -> "AuthorityStore":
        path_obj = Path(path)
        if not create and not path_obj.is_file():
            raise FileNotFoundError(path_obj)
        if create:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path_obj), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            if create:
                connection.executescript(SCHEMA)
                existing = connection.execute("SELECT value FROM authority_meta WHERE key='schema_version'").fetchone()
                if existing is not None and int(existing[0]) != AUTHORITY_SCHEMA_VERSION:
                    raise AuthorityStoreError(
                        f"unsupported authority schema {existing[0]}; expected {AUTHORITY_SCHEMA_VERSION}"
                    )
                connection.execute(
                    "INSERT INTO authority_meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO NOTHING",
                    (str(AUTHORITY_SCHEMA_VERSION),),
                )
                connection.commit()
            else:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='authority_meta'"
                ).fetchone()
                if exists is None:
                    raise AuthorityStoreError("authority registry is not initialized")
        except Exception:
            connection.close()
            raise
        return cls(connection, path_obj)

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection, path: Union[str, Path] = "") -> "AuthorityStore":
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO authority_meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO NOTHING",
            (str(AUTHORITY_SCHEMA_VERSION),),
        )
        connection.commit()
        return cls(connection, path, owns_connection=False)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "AuthorityStore":
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

    def _row(self, record_id: int) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM authority_records WHERE record_id=?", (int(record_id),)).fetchone()
        if row is None:
            raise KeyError(f"unknown authority record {record_id}")
        return cast(sqlite3.Row, row)

    def _record_from_row(self, row: sqlite3.Row) -> AuthorityRecord:
        return _codec_record_from_row(row)

    def _event(
        self,
        connection: sqlite3.Connection,
        record_id: int,
        event_type: str,
        actor: Optional[str],
        reason: Optional[str],
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        connection.execute(
            "INSERT INTO authority_events(record_id,event_type,actor,event_at,reason,details_json) VALUES(?,?,?,?,?,?)",
            (record_id, event_type, actor, _now(), reason, _json(details or {})),
        )

    def register(
        self,
        manifest: Union[AuthorityManifest, Mapping[str, Any]],
        *,
        manifest_dir: Optional[Union[str, Path]] = None,
        actor: Optional[str] = None,
    ) -> AuthorityRecord:
        """Register an immutable record, returning an existing checksum match idempotently."""
        item = manifest if isinstance(manifest, AuthorityManifest) else AuthorityManifest.from_mapping(manifest)
        source_sha256 = _sha256_value(item.source_sha256, "source_sha256")
        if item.byte_size is not None and (isinstance(item.byte_size, bool) or int(item.byte_size) < 0):
            raise AuthorityValidationError("byte_size must be a non-negative integer")
        recorded_area = _positive_area(item.recorded_area_sqm)
        object.__setattr__(item, "source_sha256", source_sha256)
        object.__setattr__(item, "recorded_area_sqm", recorded_area)
        original_crs = _crs_wkid(item.original_crs)
        object.__setattr__(item, "original_crs", original_crs)
        normalized_json, normalized_crs, geometry_hash, calculated = _normalise_geometry(
            item.original_geometry, original_crs
        )
        identity = (_normalised_identity(item.village), _normalised_identity(item.cts_no))
        source_type = SourceType.parse(item.source_type)
        supplied_version = item.version
        with self.transaction() as connection:
            payload_for_checksum = _manifest_payload(
                item, int(supplied_version or 0), normalized_json, geometry_hash, calculated
            )
            existing_by_checksum = connection.execute(
                "SELECT * FROM authority_records WHERE record_checksum=?", (_hash(payload_for_checksum),)
            ).fetchone()
            if existing_by_checksum is not None:
                return self._record_from_row(cast(sqlite3.Row, existing_by_checksum))
            max_row = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM authority_records WHERE village=? AND cts_no=? AND source_type=?",
                (identity[0], identity[1], source_type.value),
            ).fetchone()
            version = int(supplied_version) if supplied_version is not None else int(max_row[0]) + 1
            if version < 1:
                raise AuthorityValidationError("version must be a positive integer")
            payload_for_checksum = _manifest_payload(item, version, normalized_json, geometry_hash, calculated)
            record_checksum = _hash(payload_for_checksum)
            if (
                item.record_checksum is not None
                and _sha256_value(item.record_checksum, "record_checksum") != record_checksum
            ):
                raise AuthorityValidationError("record_checksum does not match the immutable manifest payload")
            same_version = connection.execute(
                "SELECT record_checksum FROM authority_records WHERE village=? AND cts_no=? AND source_type=? AND version=?",
                (identity[0], identity[1], source_type.value, version),
            ).fetchone()
            if same_version is not None:
                raise AuthorityStateError("that plot/source type/version already contains a different record")
            if item.supersedes_id is not None:
                old = self._row(int(item.supersedes_id))
                if str(old["village"]) != identity[0] or str(old["cts_no"]) != identity[1]:
                    raise AuthorityValidationError("superseded record must belong to the same village and CTS")
            now = _now()
            cursor = connection.execute(
                """INSERT INTO authority_records(
                    village,cts_no,ward,source_type,version,status,issuer,reference_no,issue_date,survey_date,
                    source_uri,source_sha256,mime_type,byte_size,recorded_area_sqm,original_geometry_json,
                    original_crs,normalized_rings_json,normalized_crs,geometry_sha256,calculated_area_sqm,
                    supersedes_id,metadata_json,created_by,created_at,updated_at,record_checksum
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identity[0],
                    identity[1],
                    item.ward,
                    source_type.value,
                    version,
                    SourceStatus.REGISTERED.value,
                    item.issuer,
                    item.reference_no,
                    item.issue_date,
                    item.survey_date,
                    item.source_uri,
                    source_sha256,
                    item.mime_type,
                    item.byte_size,
                    recorded_area,
                    _json(item.original_geometry) if item.original_geometry is not None else None,
                    original_crs,
                    normalized_json,
                    normalized_crs,
                    geometry_hash,
                    calculated,
                    item.supersedes_id,
                    _json(dict(item.metadata)),
                    item.created_by or actor,
                    now,
                    now,
                    record_checksum,
                ),
            )
            if cursor.lastrowid is None:
                raise AuthorityStoreError("SQLite did not return an authority record ID")
            record_id = int(cursor.lastrowid)
            self._event(
                connection, record_id, "registered", actor or item.created_by, "record registered", {"version": version}
            )
        return self.get(record_id)

    def get(self, record_id: int) -> AuthorityRecord:
        return self._record_from_row(self._row(record_id))

    def list(
        self,
        village: Optional[str] = None,
        cts_no: Optional[str] = None,
        *,
        source_type: Optional[Union[SourceType, str]] = None,
        status: Optional[Union[SourceStatus, str]] = None,
    ) -> Tuple[AuthorityRecord, ...]:
        clauses: List[str] = []
        values: List[Any] = []
        if village is not None:
            clauses.append("village=?")
            values.append(_normalised_identity(village))
        if cts_no is not None:
            clauses.append("cts_no=?")
            values.append(_normalised_identity(cts_no))
        if source_type is not None:
            clauses.append("source_type=?")
            values.append(SourceType.parse(source_type).value)
        if status is not None:
            clauses.append("status=?")
            values.append(SourceStatus(status).value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM authority_records{where} ORDER BY village,cts_no,source_type,version,record_id", values
        ).fetchall()
        return tuple(self._record_from_row(cast(sqlite3.Row, row)) for row in rows)

    def add_manifest(
        self,
        items: Union[AuthorityManifest, Mapping[str, Any], Sequence[Union[AuthorityManifest, Mapping[str, Any]]]],
        *,
        actor: Optional[str] = None,
        manifest_dir: Optional[Union[str, Path]] = None,
    ) -> List[Dict[str, Any]]:
        """CLI-friendly batch registration returning JSON-safe records."""
        if isinstance(items, (AuthorityManifest, Mapping)):
            iterable: Sequence[Union[AuthorityManifest, Mapping[str, Any]]] = (items,)
        else:
            iterable = items
        return [self.register(item, actor=actor, manifest_dir=manifest_dir).to_dict() for item in iterable]

    def list_sources(
        self,
        village: Optional[str] = None,
        cts: Optional[str] = None,
        *,
        cts_no: Optional[str] = None,
        source_type: Optional[Union[SourceType, str]] = None,
        status: Optional[Union[SourceStatus, str]] = None,
    ) -> Dict[str, Any]:
        """Return a stable JSON envelope for the authority CLI."""
        records = self.list(village, cts_no or cts, source_type=source_type, status=status)
        return {"records": [record.to_dict() for record in records], "revision": self.revision(village, cts_no or cts)}

    def get_source(self, record_id: Union[int, str]) -> Dict[str, Any]:
        return self.get(int(record_id)).to_dict()

    def verify(
        self,
        record_id: int,
        *,
        actor: str,
        manifest_dir: Optional[Union[str, Path]] = None,
        notes: Optional[str] = None,
    ) -> AuthorityRecord:
        """Verify a record only when its local document hash and issuer agree."""
        if not str(actor).strip():
            raise AuthorityValidationError("actor is required to verify a source")
        record = self.get(record_id)
        if record.status in {SourceStatus.WITHDRAWN, SourceStatus.REJECTED, SourceStatus.SUPERSEDED}:
            raise AuthorityStateError(f"record {record_id} cannot be verified from status {record.status.value}")
        if not record.issuer or not record.source_uri or not record.source_sha256:
            raise AuthorityValidationError("verification requires issuer, document URI, and document SHA-256")
        path = _document_path(record.source_uri, manifest_dir)
        if path is None or not path.is_file():
            raise AuthorityValidationError("verification requires a readable local document URI")
        if _file_sha256(path) != record.source_sha256:
            raise AuthorityValidationError("local document SHA-256 does not match the registered source_sha256")
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE authority_records SET status=?,reviewed_by=?,reviewed_at=?,updated_at=? WHERE record_id=?",
                (SourceStatus.VERIFIED.value, actor, now, now, record_id),
            )
            self._event(connection, record_id, "verified", actor, notes or "source verified")
            if record.supersedes_id is not None:
                old = self._row(record.supersedes_id)
                if old["status"] not in {SourceStatus.SUPERSEDED.value, SourceStatus.WITHDRAWN.value}:
                    connection.execute(
                        "UPDATE authority_records SET status=?,updated_at=? WHERE record_id=?",
                        (SourceStatus.SUPERSEDED.value, now, record.supersedes_id),
                    )
                    self._event(
                        connection,
                        record.supersedes_id,
                        "superseded",
                        actor,
                        f"superseded by authority record {record_id}",
                        {"replacement_id": record_id},
                    )
                    connection.execute(
                        """UPDATE authority_selections SET active=0,deactivated_at=?,deactivated_by=?,deactivation_reason=?
                           WHERE record_id=? AND active=1""",
                        (now, actor, f"record superseded by {record_id}", record.supersedes_id),
                    )
        return self.get(record_id)

    def verify_source(
        self,
        record_id: Union[int, str],
        *,
        reviewed_by: str,
        manifest_dir: Optional[Union[str, Path]] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.verify(int(record_id), actor=reviewed_by, manifest_dir=manifest_dir, notes=notes).to_dict()

    def withdraw(self, record_id: int, *, actor: str, reason: str) -> AuthorityRecord:
        if not str(actor).strip() or not str(reason).strip():
            raise AuthorityValidationError("actor and reason are required to withdraw a source")
        record = self.get(record_id)
        if record.status in {SourceStatus.WITHDRAWN, SourceStatus.REJECTED}:
            return record
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE authority_records SET status=?,updated_at=? WHERE record_id=?",
                (SourceStatus.WITHDRAWN.value, now, record_id),
            )
            self._event(connection, record_id, "withdrawn", actor, reason)
            connection.execute(
                """UPDATE authority_selections SET active=0,deactivated_at=?,deactivated_by=?,deactivation_reason=?
                   WHERE record_id=? AND active=1""",
                (now, actor, reason, record_id),
            )
        return self.get(record_id)

    def withdraw_source(self, record_id: Union[int, str], *, actor: str, reason: str) -> Dict[str, Any]:
        return self.withdraw(int(record_id), actor=actor, reason=reason).to_dict()

    def _suitable(self, record: AuthorityRecord, purpose: SelectionPurpose) -> bool:
        if record.status is not SourceStatus.VERIFIED:
            return False
        if purpose is SelectionPurpose.AREA:
            return record.recorded_area_sqm is not None or record.calculated_area_sqm is not None
        if purpose is SelectionPurpose.GEOMETRY:
            return record.has_geometry
        return record.source_type is SourceType.DP_REMARKS

    def activate(
        self, record_id: int, purpose: Union[SelectionPurpose, str], *, actor: str, reason: str
    ) -> AuthorityRecord:
        selected_purpose = SelectionPurpose.parse(purpose)
        if not str(actor).strip() or not str(reason).strip():
            raise AuthorityValidationError("actor and reason are required to activate a source")
        record = self.get(record_id)
        if not self._suitable(record, selected_purpose):
            raise AuthorityStateError(f"record {record_id} is not verified or suitable for {selected_purpose.value}")
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                """UPDATE authority_selections SET active=0,deactivated_at=?,deactivated_by=?,deactivation_reason=?
                   WHERE village=? AND cts_no=? AND purpose=? AND active=1""",
                (
                    now,
                    actor,
                    f"replaced for {selected_purpose.value}",
                    record.village,
                    record.cts_no,
                    selected_purpose.value,
                ),
            )
            connection.execute(
                """INSERT INTO authority_selections(record_id,village,cts_no,purpose,active,selected_at,selected_by,reason)
                   VALUES(?,?,?,?,1,?,?,?)""",
                (record_id, record.village, record.cts_no, selected_purpose.value, now, actor, reason),
            )
            self._event(connection, record_id, "activated", actor, reason, {"purpose": selected_purpose.value})
        return record

    def activate_source(
        self,
        record_id: Union[int, str],
        *,
        purpose: Union[SelectionPurpose, str],
        activated_by: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.activate(
            int(record_id), purpose, actor=activated_by, reason=reason or "explicit source activation"
        ).to_dict()

    def active(
        self,
        village: str,
        cts_no: str,
        *,
        purpose: Optional[Union[SelectionPurpose, str]] = None,
        selection_purpose: Optional[Union[SelectionPurpose, str]] = None,
    ) -> Union[Dict[str, AuthorityRecord], Tuple[AuthorityRecord, ...]]:
        selected_purpose = purpose if purpose is not None else selection_purpose
        purpose_value: Optional[str] = None
        if selected_purpose is not None:
            raw_purpose = str(getattr(selected_purpose, "value", selected_purpose)).strip().casefold()
            purpose_aliases = {
                "area_reconciliation": SelectionPurpose.AREA.value,
                "geometry_reconciliation": SelectionPurpose.GEOMETRY.value,
                "planning_remarks": SelectionPurpose.PLANNING.value,
            }
            purpose_value = (
                purpose_aliases[raw_purpose]
                if raw_purpose in purpose_aliases
                else SelectionPurpose.parse(raw_purpose).value
            )
        clauses = " AND s.purpose=?" if purpose_value is not None else ""
        values: List[Any] = [_normalised_identity(village), _normalised_identity(cts_no), SourceStatus.VERIFIED.value]
        if purpose_value is not None:
            values.append(purpose_value)
        rows = self.connection.execute(
            f"""SELECT r.*,s.purpose FROM authority_selections s JOIN authority_records r ON r.record_id=s.record_id
               WHERE s.village=? AND s.cts_no=? AND s.active=1 AND r.status=?{clauses} ORDER BY s.purpose""",
            values,
        ).fetchall()
        records = tuple(self._record_from_row(cast(sqlite3.Row, row)) for row in rows)
        if purpose_value is not None:
            return records
        return {str(row["purpose"]): record for row, record in zip(rows, records, strict=False)}

    def revision(self, village: Optional[str] = None, cts_no: Optional[str] = None) -> int:
        """Return a plot revision, or a monotonic global registry revision."""
        if village is None and cts_no is None:
            row = self.connection.execute(
                "SELECT MAX(revision) FROM (SELECT COALESCE(MAX(event_id),0) revision FROM authority_events UNION ALL SELECT COALESCE(MAX(selection_id),0) FROM authority_selections)"
            ).fetchone()
            return int(row[0] or 0)
        if village is None or cts_no is None:
            raise AuthorityValidationError("village and cts_no must be supplied together")
        row = self.connection.execute(
            "SELECT COALESCE(MAX(version),0) FROM authority_records WHERE village=? AND cts_no=?",
            (_normalised_identity(village), _normalised_identity(cts_no)),
        ).fetchone()
        return int(row[0])

    def audit(self, record_id: Optional[int] = None) -> Union[Tuple[Mapping[str, Any], ...], Dict[str, Any]]:
        if record_id is None:
            counts = {
                str(row["status"]): int(row["count"])
                for row in self.connection.execute(
                    "SELECT status,COUNT(*) count FROM authority_records GROUP BY status"
                )
            }
            bad_checksums = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM authority_records WHERE record_checksum IS NULL OR length(record_checksum) != 64"
                ).fetchone()[0]
            )
            return {
                "schema_version": AUTHORITY_SCHEMA_VERSION,
                "revision": self.revision(),
                "record_count": int(self.connection.execute("SELECT COUNT(*) FROM authority_records").fetchone()[0]),
                "event_count": int(self.connection.execute("SELECT COUNT(*) FROM authority_events").fetchone()[0]),
                "selection_count": int(
                    self.connection.execute("SELECT COUNT(*) FROM authority_selections").fetchone()[0]
                ),
                "active_selection_count": int(
                    self.connection.execute("SELECT COUNT(*) FROM authority_selections WHERE active=1").fetchone()[0]
                ),
                "status_counts": counts,
                "invalid_record_checksum_count": bad_checksums,
                "ok": bad_checksums == 0,
            }
        self._row(record_id)
        rows = self.connection.execute(
            "SELECT event_id,record_id,event_type,actor,event_at,reason,details_json FROM authority_events WHERE record_id=? ORDER BY event_id",
            (record_id,),
        ).fetchall()
        return tuple(
            {
                "event_id": int(row["event_id"]),
                "record_id": int(row["record_id"]),
                "event_type": str(row["event_type"]),
                "actor": row["actor"],
                "event_at": str(row["event_at"]),
                "reason": row["reason"],
                "details": _loads(row["details_json"], {}),
            }
            for row in rows
        )


__all__ = [
    "AUTHORITY_SCHEMA_VERSION",
    "AuthorityStateError",
    "AuthorityStore",
    "AuthorityStoreError",
    "AuthorityValidationError",
]
