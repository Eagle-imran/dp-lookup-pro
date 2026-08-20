"""Offline reliability contracts for the Layer 13 bulk importer."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx
import pytest

from dp_lookup.application.snapshot_ingestion import SnapshotIngestionConfig, ingest_layer13_snapshot
from dp_lookup.clients.parcel_snapshot import SnapshotCheckpoint


class Response:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Dict[str, Any]:
        return self.payload


def feature(object_id: int, *, name: str = "parcel") -> Dict[str, Any]:
    return {
        "attributes": {"OBJECTID": object_id, "VILLAGE": "WORLI", "CTS_CS_NO": str(object_id), "NAME": name},
        "geometry": {"rings": [[[72.8, 19.0], [72.81, 19.0], [72.81, 19.01], [72.8, 19.0]]]},
    }


class FakeClient:
    def __init__(self, responses: List[Any]):
        self.responses = list(responses)
        self.calls: List[tuple[str, Dict[str, Any]]] = []
        self.methods: List[str] = []

    async def get(self, url: str, *, params: Dict[str, Any]) -> Any:
        self.methods.append("GET")
        self.calls.append((url, params))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def post(self, url: str, *, data: Dict[str, Any]) -> Any:
        self.methods.append("POST")
        self.calls.append((url, data))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def run(client: FakeClient, **kwargs: Any):
    return asyncio.run(ingest_layer13_snapshot(client, **kwargs))


def test_inventory_is_first_and_batches_are_sorted_explicit_and_complete():
    client = FakeClient(
        [
            Response({"objectIds": [3, 1, 2, 2]}),
            Response({"features": [feature(2), feature(1)]}),
            Response({"features": [feature(3)]}),
        ]
    )
    result = run(client, config=SnapshotIngestionConfig(batch_size=2))

    assert client.calls[0][0].endswith("/MapServer/13/query")
    assert [item[1] for item in client.calls] == [
        {"where": "1=1", "returnIdsOnly": "true", "returnGeometry": "false", "f": "json"},
        {"objectIds": "1,2", "outFields": "*", "returnGeometry": "true", "outSR": "102100", "f": "json"},
        {"objectIds": "3", "outFields": "*", "returnGeometry": "true", "outSR": "102100", "f": "json"},
    ]
    assert client.methods == ["GET", "POST", "POST"]
    assert result.manifest.expected_ids == (1, 2, 3)
    assert result.manifest.received_ids == (1, 2, 3)
    assert result.manifest.duplicate_ids == (2,)
    assert result.complete
    assert result.manifest.content_hash


def test_partial_batch_is_not_complete_and_reports_missing_without_claiming_publishable():
    client = FakeClient([Response({"objectIds": [1, 2, 3]}), Response({"features": [feature(1), feature(3)]})])
    result = run(client, config=SnapshotIngestionConfig(batch_size=3))

    assert result.manifest.missing_ids == (2,)
    assert result.manifest.rejected_ids == ()
    assert not result.manifest.complete
    assert result.checkpoint.completed_ids == (1, 3)


def test_malformed_feature_is_rejected_and_embedded_error_is_retried():
    sleeps: List[float] = []
    client = FakeClient(
        [
            Response({"objectIds": [10, 11]}),
            Response({"error": {"code": 500, "message": "busy"}}),
            Response({"features": [feature(10), {"attributes": {"OBJECTID": 11}}]}),
        ]
    )
    result = asyncio.run(
        ingest_layer13_snapshot(
            client,
            config=SnapshotIngestionConfig(base_delay_seconds=0.01, max_delay_seconds=0.01),
            sleep=lambda delay: _record_sleep(sleeps, delay),
        )
    )

    assert result.manifest.received_ids == (10,)
    assert result.manifest.missing_ids == (11,)
    assert result.manifest.invalid_feature_count == 1
    assert sleeps == [0.01]


async def _record_sleep(sleeps: List[float], delay: float) -> None:
    sleeps.append(delay)


def test_transport_timeout_retries_then_accepts_batch():
    client = FakeClient([Response({"objectIds": [7]}), httpx.ReadTimeout("temporary"), Response({"features": [feature(7)]})])
    result = run(client, config=SnapshotIngestionConfig(base_delay_seconds=0, max_delay_seconds=0))
    assert result.complete
    assert len(client.calls) == 3


def test_checkpoint_resume_reuses_prior_records_and_rejects_inventory_change():
    first = FakeClient([Response({"objectIds": [1, 2]}), Response({"features": [feature(1)]})])
    partial = run(first, config=SnapshotIngestionConfig(batch_size=2))
    second = FakeClient([Response({"objectIds": [1, 2]}), Response({"features": [feature(2)]})])
    resumed = run(
        second,
        config=SnapshotIngestionConfig(batch_size=2),
        checkpoint=partial.checkpoint,
        prior_features={item.object_id: item for item in partial.features},
    )
    assert resumed.complete
    assert resumed.manifest.received_ids == (1, 2)
    assert second.calls[1][1]["objectIds"] == "2"

    changed = FakeClient([Response({"objectIds": [1, 3]})])
    with pytest.raises(Exception, match="different Layer 13 inventory"):
        run(
            changed,
            checkpoint=SnapshotCheckpoint(expected_ids=(1, 2), completed_ids=(1,)),
            prior_features={item.object_id: item for item in partial.features},
        )


def test_metadata_oid_field_is_resolved_from_oid_typed_field():
    metadata = {
        "objectIdField": None,
        "fields": [{"name": "MCGM_OID", "type": "esriFieldTypeOID"}],
        "spatialReference": {"wkid": 102100},
    }
    source_feature = feature(4)
    source_feature["attributes"] = {"MCGM_OID": 4, "VILLAGE": "WORLI"}
    client = FakeClient([Response({"objectIds": [4]}), Response(metadata), Response({"features": [source_feature]})])
    result = run(client, config=SnapshotIngestionConfig(fetch_layer_metadata=True))
    assert result.manifest.object_id_field == "MCGM_OID"
    assert result.manifest.source_spatial_reference == {"wkid": 102100}
