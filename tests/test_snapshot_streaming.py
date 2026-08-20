"""Crash-resume and persisted-evidence contracts for the Layer 13 builder."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dp_lookup.application.database_services import LocalDatabaseServices
from dp_lookup.application.snapshot_ingestion import SnapshotIngestionConfig, ingest_layer13_snapshot
from dp_lookup.clients.parcel_snapshot import SnapshotIngestionError, sha256_json
from dp_lookup.spatial_store import SnapshotStore, SnapshotValidationError


def _feature(objectid: int) -> dict[str, Any]:
    attrs = {"OBJECTID": objectid, "VILLAGE": " worli ", "CTS_CS_NO": f" {objectid} ", "WARD": " g/s "}
    geometry = {
        "rings": [[[objectid, 0], [objectid + 1, 0], [objectid + 1, 1], [objectid, 0]]],
        "spatialReference": {"wkid": 102100},
    }
    return {"attributes": attrs, "geometry": geometry, "source_member": f"raw-{objectid}"}


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self.payload


class _Client:
    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get(self, _url: str, *, params: dict[str, Any]) -> Any:
        self.calls.append(params)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_importer_streams_and_trusts_only_ids_proven_by_durable_sink():
    client = _Client([_Response({"objectIds": [1, 2]}), _Response({"features": [_feature(2)]})])
    batches: list[tuple[int, ...]] = []

    async def inventory(_expected: tuple[int, ...], _context: dict[str, Any]):
        return (1,)

    async def batch(features):
        batches.append(tuple(item.object_id for item in features))

    result = asyncio.run(
        ingest_layer13_snapshot(
            client,
            config=SnapshotIngestionConfig(batch_size=2),
            on_inventory=inventory,
            on_batch=batch,
            retain_features=False,
        )
    )

    assert result.complete
    assert result.features == ()
    assert result.manifest.received_ids == (1, 2)
    assert result.manifest.content_hash == ""
    assert batches == [(2,)]
    assert client.calls[-1]["objectIds"] == "2"


def test_stream_callback_failure_is_explicit():
    client = _Client([_Response({"objectIds": [1]}), _Response({"features": [_feature(1)]})])

    async def broken(_features):
        raise OSError("disk full")

    with pytest.raises(SnapshotIngestionError, match="sink rejected a batch"):
        asyncio.run(ingest_layer13_snapshot(client, on_batch=broken, retain_features=False))


def test_database_build_resumes_committed_batches_and_hashes_raw_source(tmp_path: Path):
    database = tmp_path / "layer13.sqlite"
    first_client = _Client(
        [
            _Response({"objectIds": [1, 2]}),
            _Response({"features": [_feature(1)]}),
            TimeoutError("interrupted"),
        ]
    )
    second_client = _Client(
        [_Response({"objectIds": [1, 2]}), _Response({"features": [_feature(2)]})]
    )
    clients = iter([first_client, second_client])
    services = LocalDatabaseServices(
        client_factory=lambda: next(clients),
        ingestion_config=SnapshotIngestionConfig(
            batch_size=1,
            max_attempts=1,
            request_delay_seconds=0,
            fetch_layer_metadata=False,
        ),
    )

    with pytest.raises(SnapshotIngestionError, match="rerun the same command to resume"):
        services.build(database)
    with SnapshotStore.open(database) as store:
        assert store.status()["active_snapshot_id"] is None
        building = store.status()["snapshots"][-1]
        assert building["state"] == "building"
        assert building["received_count"] == 1

    built = services.build(database)
    assert built["state"] == "ready"
    assert built["records"] == 2
    assert built["resumed_records"] == 1
    assert second_client.calls[-1]["objectIds"] == "2"
    expected_hash = sha256_json([_feature(1), _feature(2)])
    assert built["content_hash"] == expected_hash
    with SnapshotStore.open(database) as store:
        snapshot_id = int(built["snapshot_id"])
        assert store.content_hash(snapshot_id) == expected_hash
        assert store.lookup("  WoRlI ", " 1 ", snapshot_id=snapshot_id)[0]["raw_feature_json"]
        assert store.validate_snapshot(snapshot_id)["ok"]


def test_inventory_reconciliation_rejects_equal_count_wrong_ids(tmp_path: Path):
    with SnapshotStore.open(tmp_path / "wrong.sqlite") as store:
        snapshot_id = store.begin_snapshot(expected_count=1)
        store.set_inventory(snapshot_id, [1])
        record = _feature(2)
        store.insert_batch(
            snapshot_id,
            [
                {
                    "objectid": 2,
                    "attributes": record["attributes"],
                    "geometry": record["geometry"],
                    "raw_feature": record,
                }
            ],
        )
        report = store.validate_snapshot(snapshot_id)
        assert not report["ok"]
        assert any("missing from parcels" in error for error in report["errors"])
        assert any("absent from inventory" in error for error in report["errors"])
        with pytest.raises(SnapshotValidationError):
            store.finalize_snapshot(snapshot_id)


def test_malformed_polygon_cannot_be_finalized(tmp_path: Path):
    with SnapshotStore.open(tmp_path / "bad-geometry.sqlite") as store:
        snapshot_id = store.begin_snapshot(expected_count=1)
        store.insert_batch(
            snapshot_id,
            [{"objectid": 1, "attributes": {"OBJECTID": 1}, "geometry": {"rings": []}}],
        )
        with pytest.raises(SnapshotValidationError, match="polygon has no rings"):
            store.finalize_snapshot(snapshot_id)
