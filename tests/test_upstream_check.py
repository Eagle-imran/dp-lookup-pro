import asyncio
import json

import pytest

from dp_lookup.application.upstream_check import (
    UpstreamCheckError,
    _decode_response,
    check_database_upstream,
    inventory_hash,
    metadata_hash,
)
from dp_lookup.clients.parcel_snapshot import LAYER13_URL
from dp_lookup.planning_snapshot import PlanningSnapshotStore
from dp_lookup.spatial_store import SnapshotStore

METADATA = {
    "id": 13,
    "name": "Parcels",
    "type": "Feature Layer",
    "geometryType": "esriGeometryPolygon",
    "objectIdField": "OBJECTID",
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID", "nullable": False},
        {"name": "LAST_EDITED_DATE", "type": "esriFieldTypeDate", "nullable": True},
    ],
}


def _database(path):
    attrs = {
        "OBJECTID": 1,
        "VILLAGE": "WORLI",
        "CTS_CS_NO": "733",
        "AREA_APP_SQ_MTRS": 100.0,
        "LAST_EDITED_DATE": 1000,
    }
    geometry = {"rings": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    metadata = {"manifest": {"schema_metadata": {"layer_metadata": METADATA}}}
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source=LAYER13_URL, expected_count=1, metadata=metadata)
        store.set_inventory(snapshot_id, [1])
        store.insert_batch(snapshot_id, [{"objectid": 1, "attributes": attrs, "geometry": geometry}])
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)


class _Client:
    def __init__(self, object_ids=(1,), max_edited=1000, metadata=None):
        self.object_ids = list(object_ids)
        self.max_edited = max_edited
        self.metadata = dict(metadata or METADATA)
        self.calls = []

    async def get(self, url, params):
        self.calls.append((url, dict(params)))
        if url == LAYER13_URL:
            return self.metadata
        if "returnIdsOnly" in params:
            return {"objectIds": self.object_ids}
        return {"features": [{"attributes": {"MAX_LAST_EDITED_DATE": self.max_edited}}]}


def test_metadata_fingerprint_ignores_renderer_but_detects_schema_changes():
    rendered = {**METADATA, "drawingInfo": {"renderer": {"type": "uniqueValue"}}}
    changed = {**METADATA, "geometryType": "esriGeometryPolyline"}

    assert metadata_hash(rendered) == metadata_hash(METADATA)
    assert metadata_hash(changed) != metadata_hash(METADATA)
    assert inventory_hash([3, 1, 2, 1]) == inventory_hash([1, 2, 3])


def test_upstream_check_is_read_only_and_does_not_download_geometry(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    _database(path)
    client = _Client()

    result = asyncio.run(check_database_upstream(client, path))

    assert result["geometry_downloaded"] is False
    assert result["parcels"]["status"] == "unchanged"
    assert result["parcels"]["refresh_required"] is False
    assert all(call[1].get("returnGeometry") != "true" for call in client.calls)


def test_inventory_or_edit_change_requires_a_staged_refresh(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    _database(path)

    result = asyncio.run(check_database_upstream(_Client(object_ids=(1, 2)), path))

    assert result["parcels"]["status"] == "changed"
    assert result["parcels"]["signals"]["inventory_hash"] == "changed"
    assert result["parcels"]["refresh_required"] is True


def test_edit_timestamp_change_requires_refresh_even_when_ids_match(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    _database(path)

    result = asyncio.run(check_database_upstream(_Client(max_edited=2000), path))

    assert result["parcels"]["status"] == "changed"
    assert result["parcels"]["signals"]["max_last_edited_date"] == "changed"


def test_arcgis_error_is_unknown_never_unchanged(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    _database(path)

    class Broken:
        async def get(self, _url, params):
            if params == {"f": "json"}:
                return {"error": {"message": "unavailable"}}
            raise AssertionError("metadata failure must stop the layer probe")

    result = asyncio.run(check_database_upstream(Broken(), path))

    assert result["parcels"]["status"] == "unknown"
    assert result["parcels"]["refresh_required"] is True


def test_missing_database_and_malformed_inventory_are_safe(tmp_path):
    with pytest.raises(UpstreamCheckError, match="does not exist"):
        asyncio.run(check_database_upstream(_Client(), tmp_path / "missing.sqlite"))

    path = tmp_path / "snapshot.sqlite"
    _database(path)

    class MissingInventory(_Client):
        async def get(self, url, params):
            if url == LAYER13_URL:
                return self.metadata
            if "returnIdsOnly" in params:
                return {"features": []}
            return await super().get(url, params)

    result = asyncio.run(check_database_upstream(MissingInventory(), path))
    assert result["parcels"]["status"] == "unknown"
    assert "objectIds" in result["parcels"]["error"]


def test_no_edit_field_uses_inventory_with_visible_limitation(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    metadata = {
        **METADATA,
        "fields": [METADATA["fields"][0]],
    }
    attrs = {"OBJECTID": 1, "VILLAGE": "WORLI", "CTS_CS_NO": "733"}
    geometry = {"rings": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    stored = {"manifest": {"schema_metadata": {"layer_metadata": metadata}}}
    with SnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source=LAYER13_URL, expected_count=1, metadata=stored)
        store.set_inventory(snapshot_id, [1])
        store.insert_batch(snapshot_id, [{"objectid": 1, "attributes": attrs, "geometry": geometry}])
        store.finalize_snapshot(snapshot_id)
        store.activate(snapshot_id)
    client = _Client(metadata=metadata)

    result = asyncio.run(check_database_upstream(client, path))

    assert result["parcels"]["status"] == "unchanged"
    assert result["parcels"]["signals"]["max_last_edited_date"] == "unavailable"
    assert any("periodic full verification" in item for item in result["parcels"]["limitations"])


def test_planning_layer_is_checked_and_missing_registry_layers_are_detected(tmp_path):
    path = tmp_path / "planning.sqlite"
    _database(path)
    layer_metadata = {**METADATA, "id": 0, "name": "REVISED PLU ZONES"}
    with PlanningSnapshotStore.open(path) as store:
        snapshot_id = store.begin_snapshot(source_url="https://example.test/MapServer")
        store.register_layer(
            snapshot_id,
            0,
            name="REVISED PLU ZONES",
            object_id_field="OBJECTID",
            expected_count=1,
            metadata={
                "source_context": {
                    "source_url": "https://example.test/MapServer/0",
                    "layer_metadata": layer_metadata,
                }
            },
        )
        store.set_layer_inventory(snapshot_id, 0, [1])
        store.insert_batch(
            snapshot_id,
            0,
            [
                {
                    "attributes": {"OBJECTID": 1, "LAST_EDITED_DATE": 1000},
                    "geometry": {"rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                }
            ],
        )
        store.finalize(snapshot_id)
        store.activate(snapshot_id)

    class PlanningClient(_Client):
        async def get(self, url, params):
            if url.startswith("https://example.test"):
                if params == {"f": "json"}:
                    return layer_metadata
                if "returnIdsOnly" in params:
                    return {"objectIds": [1]}
                statistics = json.loads(params["outStatistics"])
                assert statistics[0]["onStatisticField"] == "LAST_EDITED_DATE"
                return {"features": [{"attributes": {"MAX_LAST_EDITED_DATE": 1000}}]}
            return await super().get(url, params)

    result = asyncio.run(check_database_upstream(PlanningClient(), path))

    assert result["planning"]["layers"][0]["status"] == "unchanged"
    assert result["planning"]["missing_canonical_layer_ids"]
    assert result["planning"]["status"] == "changed"


def test_response_decoder_rejects_http_and_payload_failures():
    class Response:
        def __init__(self, status, payload=None, broken=False):
            self.status_code = status
            self.payload = payload
            self.broken = broken

        def json(self):
            if self.broken:
                raise ValueError("not json")
            return self.payload

    with pytest.raises(UpstreamCheckError, match="non-JSON"):
        _decode_response(Response(200, broken=True), "source")
    with pytest.raises(UpstreamCheckError, match="HTTP 503"):
        _decode_response(Response(503, {}), "source")
    with pytest.raises(UpstreamCheckError, match="non-object"):
        _decode_response(Response(200, []), "source")
    with pytest.raises(UpstreamCheckError, match="denied"):
        _decode_response({"error": "denied"}, "source")


def test_transport_exception_becomes_unknown(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    _database(path)

    class Exploding:
        async def get(self, _url, params):
            del params
            raise OSError("network down")

    result = asyncio.run(check_database_upstream(Exploding(), path))

    assert result["parcels"]["status"] == "unknown"
    assert "network down" in result["parcels"]["error"]
