import hashlib
from pathlib import Path

import pytest

from dp_lookup.authority import AuthorityManifest, AuthorityStore, SelectionPurpose, SourceStatus, SourceType
from dp_lookup.authority.store import AuthorityStateError, AuthorityValidationError


def _document(tmp_path: Path, content: bytes = b"official source", name: str = "evidence.pdf"):
    path = tmp_path / name
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def _manifest(path: Path, digest: str, **overrides):
    payload = {
        "village": "WORLI",
        "cts_no": "733",
        "source_type": SourceType.PROPERTY_CARD,
        "source_uri": path.name,
        "source_sha256": digest,
        "issuer": "City Survey Office",
        "reference_no": "PC-733",
        "mime_type": "application/pdf",
        "byte_size": path.stat().st_size,
        "recorded_area_sqm": 1317.74,
        "created_by": "architect",
    }
    payload.update(overrides)
    return AuthorityManifest(**payload)


def _rings():
    return {
        "rings": [[[72.82, 19.01], [72.821, 19.01], [72.821, 19.011], [72.82, 19.01]]],
        "spatialReference": {"wkid": 4326},
    }


def test_registry_is_additive_and_idempotent_by_record_checksum(tmp_path: Path):
    document, digest = _document(tmp_path)
    database = tmp_path / "existing.sqlite"
    with AuthorityStore.open(database) as store:
        first = store.register(_manifest(document, digest), manifest_dir=tmp_path)
        same = store.register(_manifest(document, digest), manifest_dir=tmp_path)
        second = store.register(_manifest(document, digest, reference_no="PC-733-REV2"), manifest_dir=tmp_path)

        assert first.record_id == same.record_id
        assert first.version == 1
        assert second.version == 2
        assert store.revision("worli", "733") == 2
        assert len(store.list("WORLI", "733")) == 2
        assert (
            store.connection.execute("SELECT value FROM authority_meta WHERE key='schema_version'").fetchone()[0] == "1"
        )


def test_verification_requires_local_matching_document_and_issuer(tmp_path: Path):
    document, digest = _document(tmp_path)
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        record = store.register(_manifest(document, digest), manifest_dir=tmp_path)
        verified = store.verify(record.record_id, actor="reviewer", manifest_dir=tmp_path)
        assert verified.status is SourceStatus.VERIFIED
        assert verified.reviewed_by == "reviewer"
        assert [event["event_type"] for event in store.audit(record.record_id)] == ["registered", "verified"]

    changed, changed_digest = _document(tmp_path, b"changed")
    with AuthorityStore.open(tmp_path / "changed.sqlite") as store:
        record = store.register(_manifest(changed, digest), manifest_dir=tmp_path)
        with pytest.raises(AuthorityValidationError, match="SHA-256"):
            store.verify(record.record_id, actor="reviewer", manifest_dir=tmp_path)
        assert record.status is SourceStatus.REGISTERED
        assert changed_digest != digest


def test_geometry_preserves_original_and_normalizes_wgs84_to_epsg3857(tmp_path: Path):
    document, digest = _document(tmp_path)
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        record = store.register(
            _manifest(
                document,
                digest,
                source_type=SourceType.TOTAL_STATION_SURVEY,
                original_geometry=_rings(),
                original_crs=4326,
            ),
            manifest_dir=tmp_path,
        )
        assert record.original_geometry["spatialReference"]["wkid"] == 4326
        assert record.original_crs == 4326
        assert record.normalized_epsg3857_rings[0][0][0] > 8_000_000
        assert record.calculated_area_sqm is not None and record.calculated_area_sqm > 0
        assert record.geometry_sha256
        assert record.to_dict()["normalized_epsg3857_rings"]


def test_verification_supersedes_old_record_but_keeps_selection_history(tmp_path: Path):
    document, digest = _document(tmp_path)
    replacement, replacement_digest = _document(tmp_path, b"replacement official source", "replacement.pdf")
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        old = store.register(
            _manifest(document, digest, source_type=SourceType.CTS_FINAL_PLOT_PLAN), manifest_dir=tmp_path
        )
        store.verify(old.record_id, actor="reviewer", manifest_dir=tmp_path)
        store.activate(old.record_id, SelectionPurpose.AREA, actor="reviewer", reason="first accepted area source")
        new = store.register(
            _manifest(
                replacement,
                replacement_digest,
                source_type=SourceType.CTS_FINAL_PLOT_PLAN,
                reference_no="FP-REV2",
                supersedes_id=old.record_id,
            ),
            manifest_dir=tmp_path,
        )
        store.verify(new.record_id, actor="reviewer", manifest_dir=tmp_path)
        assert store.get(old.record_id).status is SourceStatus.SUPERSEDED
        assert store.active("WORLI", "733") == {}
        assert any(event["event_type"] == "superseded" for event in store.audit(old.record_id))
        assert store.connection.execute("SELECT COUNT(*) FROM authority_selections").fetchone()[0] == 1


def test_activation_is_purpose_specific_and_requires_verified_evidence(tmp_path: Path):
    document, digest = _document(tmp_path)
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        property_card = store.register(_manifest(document, digest), manifest_dir=tmp_path)
        with pytest.raises(AuthorityStateError):
            store.activate(property_card.record_id, SelectionPurpose.AREA, actor="reviewer", reason="not verified")
        store.verify(property_card.record_id, actor="reviewer", manifest_dir=tmp_path)
        store.activate(property_card.record_id, SelectionPurpose.AREA, actor="reviewer", reason="recorded area")
        assert store.active("WORLI", "733")[SelectionPurpose.AREA.value].record_id == property_card.record_id
        with pytest.raises(AuthorityStateError):
            store.activate(
                property_card.record_id, SelectionPurpose.PLANNING, actor="reviewer", reason="wrong evidence type"
            )


def test_dp_remarks_is_planning_evidence_not_geometry_evidence(tmp_path: Path):
    document, digest = _document(tmp_path)
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        remarks = store.register(_manifest(document, digest, source_type=SourceType.DP_REMARKS), manifest_dir=tmp_path)
        store.verify(remarks.record_id, actor="reviewer", manifest_dir=tmp_path)
        store.activate(remarks.record_id, SelectionPurpose.PLANNING, actor="reviewer", reason="official DP remarks")
        with pytest.raises(AuthorityStateError):
            store.activate(
                remarks.record_id, SelectionPurpose.GEOMETRY, actor="reviewer", reason="not a boundary source"
            )


def test_generic_official_document_cannot_bypass_the_planning_policy(tmp_path: Path):
    document, digest = _document(tmp_path)
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        generic = store.register(
            _manifest(document, digest, source_type=SourceType.OTHER_OFFICIAL_DOCUMENT),
            manifest_dir=tmp_path,
        )
        store.verify(generic.record_id, actor="reviewer", manifest_dir=tmp_path)
        with pytest.raises(AuthorityStateError):
            store.activate(
                generic.record_id,
                SelectionPurpose.PLANNING,
                actor="reviewer",
                reason="unsupported planning evidence",
            )


def test_withdraw_deactivates_current_selection_and_preserves_audit(tmp_path: Path):
    document, digest = _document(tmp_path)
    with AuthorityStore.open(tmp_path / "db.sqlite") as store:
        record = store.register(_manifest(document, digest), manifest_dir=tmp_path)
        store.verify(record.record_id, actor="reviewer", manifest_dir=tmp_path)
        store.activate(record.record_id, SelectionPurpose.AREA, actor="reviewer", reason="accepted")
        store.withdraw(record.record_id, actor="reviewer", reason="source replaced by issuing office")
        assert store.active("WORLI", "733") == {}
        assert store.get(record.record_id).status is SourceStatus.WITHDRAWN
        assert store.audit(record.record_id)[-1]["event_type"] == "withdrawn"


def test_existing_database_can_be_opened_without_touching_parcel_schema(tmp_path: Path):
    import sqlite3

    database = tmp_path / "parcel.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO meta VALUES('schema_version','2')")
    connection.commit()
    connection.close()
    with AuthorityStore.open(database) as store:
        assert store.connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
        assert (
            store.connection.execute("SELECT value FROM authority_meta WHERE key='schema_version'").fetchone()[0] == "1"
        )
