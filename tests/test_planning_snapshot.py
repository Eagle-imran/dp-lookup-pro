"""Offline contracts for the canonical planning-layer downloader."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from dp_lookup.application import planning_snapshot as snapshot_module
from dp_lookup.application.planning_snapshot import (
    PlanningIngestionConfig,
    PlanningLayerCheckpoint,
    PlanningSnapshotCheckpoint,
    PlanningSnapshotError,
    canonical_planning_specs,
    ingest_planning_snapshot,
)
from dp_lookup.planning_evidence.models import EvidenceClass, EvidenceContext, LayerSpec, QueryPolicy
from dp_lookup.planning_snapshot_cli import EXIT_SUCCESS, main, parse_planning_snapshot_args


class Response:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.headers: Dict[str, str] = {}

    def json(self) -> Dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, responses: List[Any]):
        self.responses = list(responses)
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    async def get(self, url: str, *, params: Dict[str, Any]) -> Any:
        self.calls.append(("GET", dict(params)))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def post(self, url: str, *, data: Dict[str, Any]) -> Any:
        self.calls.append(("POST", dict(data)))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def spec(layer_id: int, name: str = "Layer") -> LayerSpec:
    return LayerSpec(
        layer_id=layer_id,
        name=name,
        evidence_class=EvidenceClass.REGULATORY,
        query_policy=QueryPolicy.ALWAYS,
        out_fields=("OBJECTID", "CODE"),
        role="test layer",
    )


def feature(object_id: int, code: str = "A") -> Dict[str, Any]:
    return {
        "attributes": {"OBJECTID": object_id, "CODE": code},
        "geometry": {"rings": [[[72.8, 19.0], [72.81, 19.0], [72.81, 19.01], [72.8, 19.0]]]},
    }


def run(client: FakeClient, **kwargs: Any):
    return asyncio.run(ingest_planning_snapshot(client, **kwargs))


def test_default_registry_is_canonical_and_excludes_layer13_anchor():
    selected = canonical_planning_specs()
    ids = tuple(item.layer_id for item in selected)
    assert 13 not in ids
    assert len(ids) == len(set(ids))
    assert 57 not in ids and 2251 not in ids and 2252 not in ids
    assert 61 in ids and 2250 in ids


def test_inventory_then_bounded_explicit_batches_and_audit_manifest():
    client = FakeClient(
        [
            Response({"objectIds": [3, 1, 2, 2]}),
            Response({"features": [feature(1), feature(2)]}),
            Response({"features": [feature(3)]}),
        ]
    )
    result = run(client, specs=(spec(40),), config=PlanningIngestionConfig(batch_size=2, fetch_layer_metadata=False))
    assert [item[0] for item in client.calls] == ["GET", "POST", "POST"]
    assert client.calls[1][1]["objectIds"] == "1,2"
    assert client.calls[1][1]["outFields"] == "OBJECTID,CODE"
    layer = result.manifest.layers[0]
    assert layer.expected_ids == (1, 2, 3)
    assert layer.received_ids == (1, 2, 3)
    assert layer.duplicate_ids == (2,)
    assert layer.complete
    assert result.manifest.complete
    assert result.manifest.registry_hash
    assert result.manifest.content_hash


def test_partial_response_is_incomplete_and_checkpoint_resumes_only_missing_ids():
    first = FakeClient([Response({"objectIds": [1, 2]}), Response({"features": [feature(1)]})])
    partial = run(first, specs=(spec(40),), config=PlanningIngestionConfig(fetch_layer_metadata=False))
    assert partial.manifest.layers[0].missing_ids == (2,)
    assert not partial.complete

    second = FakeClient([Response({"objectIds": [1, 2]}), Response({"features": [feature(2)]})])
    resumed = run(
        second,
        specs=(spec(40),),
        config=PlanningIngestionConfig(fetch_layer_metadata=False),
        checkpoint=partial.checkpoint,
    )
    assert resumed.complete
    assert second.calls[1][1]["objectIds"] == "2"


def test_wrong_json_shapes_are_retried_before_abandoning_inventory_or_batch():
    client = FakeClient([
        Response({"status": "temporarily unavailable"}),
        Response({"objectIds": [1]}),
        Response({"status": "temporarily unavailable"}),
        Response({"features": [feature(1)]}),
    ])
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    result = run(
        client, specs=(spec(40),), sleep=sleep,
        config=PlanningIngestionConfig(fetch_layer_metadata=False, max_attempts=2),
    )
    assert result.complete
    assert result.manifest.layers[0].received_ids == (1,)
    assert [method for method, _ in client.calls] == ["GET", "GET", "POST", "POST"]
    assert len(sleeps) == 2


def test_repeated_wrong_inventory_shape_remains_incomplete():
    client = FakeClient([Response({}), Response({})])

    async def sleep(_delay):
        pass

    result = run(
        client, specs=(spec(40),), sleep=sleep,
        config=PlanningIngestionConfig(fetch_layer_metadata=False, max_attempts=2),
    )
    assert not result.complete
    assert "objectIds" in result.manifest.layers[0].inventory_error
    assert len(client.calls) == 2


def test_retry_and_batch_error_are_bounded_and_reported():
    sleeps: List[float] = []
    client = FakeClient(
        [
            Response({"objectIds": [1]}),
            Response({"error": {"code": 500, "message": "busy"}}),
            Response({"features": [feature(1)]}),
        ]
    )
    result = run(
        client,
        specs=(spec(40),),
        config=PlanningIngestionConfig(fetch_layer_metadata=False, base_delay_seconds=0.1, max_delay_seconds=0.1),
        sleep=lambda delay: _record_sleep(sleeps, delay),
    )
    assert result.complete
    assert sleeps == [0.1]


async def _record_sleep(sleeps: List[float], delay: float) -> None:
    sleeps.append(delay)


def test_checkpoint_rejects_registry_or_inventory_change():
    checkpoint = PlanningSnapshotCheckpoint(
        registry_layer_ids=(40,),
        layers=(PlanningLayerCheckpoint(layer_id=40, expected_ids=(1,), completed_ids=(1,)),),
    )
    client = FakeClient([Response({"objectIds": [2]})])
    with pytest.raises(PlanningSnapshotError, match="different inventory"):
        run(client, specs=(spec(40),), checkpoint=checkpoint, config=PlanningIngestionConfig(fetch_layer_metadata=False))
    client = FakeClient([])
    with pytest.raises(PlanningSnapshotError, match="different canonical planning registry"):
        run(client, specs=(spec(41),), checkpoint=checkpoint, config=PlanningIngestionConfig(fetch_layer_metadata=False))


def test_cli_parser_and_dispatch_are_dependency_injected():
    parsed = parse_planning_snapshot_args(
        ["build-planning", "--database", "data/planning.sqlite", "--batch-size", "100", "--checkpoint", "run.json", "--json"]
    )
    assert parsed["database"] == Path("data/planning.sqlite")
    assert parsed["resume"] == Path("run.json")
    assert parsed["config"].batch_size == 100

    class Services:
        def build_planning(self, database, options):
            return {"database": str(database), "batch_size": options["config"].batch_size}

        status_planning = verify_planning = activate_planning = build_planning

    output = io.StringIO()
    assert main(["build-planning", "--database", "x.sqlite", "--json"], services=Services(), out=output) == EXIT_SUCCESS
    assert '"batch_size": 500' in output.getvalue()


def test_batch_limit_is_rejected_before_network():
    with pytest.raises(ValueError, match="cannot exceed"):
        PlanningIngestionConfig(batch_size=2001)


def test_metadata_oid_is_authoritative_and_empty_source_geometry_is_preserved():
    client = FakeClient(
        [
            Response({"objectIds": [9]}),
            Response(
                {
                    "geometryType": "esriGeometryPolygon",
                    "fields": [{"name": "OID_ALT", "type": "esriFieldTypeOID"}],
                }
            ),
            Response(
                {
                    "features": [
                        {
                            "attributes": {"OID_ALT": 9, "CODE": "empty-source-shape"},
                            "geometry": {"rings": []},
                        }
                    ]
                }
            ),
        ]
    )

    result = run(client, specs=(spec(40),), config=PlanningIngestionConfig(all_fields=True))

    layer = result.manifest.layers[0]
    assert result.complete
    assert layer.object_id_field == "OID_ALT"
    assert layer.received_ids == (9,)
    assert layer.non_spatial_feature_count == 1
    assert result.features[0].geometry == {"rings": []}
    assert client.calls[-1][1]["outFields"] == "*"


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"batch_size": 0}, "batch_size must be positive"),
        ({"max_batch_size": 0}, "max_batch_size must be positive"),
        ({"max_attempts": 0}, "max_attempts must be positive"),
        ({"base_delay_seconds": -1}, "delays must not be negative"),
    ],
)
def test_ingestion_config_rejects_unsafe_limits(kwargs, message):
    with pytest.raises(ValueError, match=message):
        PlanningIngestionConfig(**kwargs)


def test_checkpoint_round_trip_and_selection_helpers_cover_edge_shapes():
    layer = PlanningLayerCheckpoint.from_dict(
        {
            "layer_id": "40",
            "expected_ids": [2, 1, 2],
            "completed_ids": [1],
            "rejected_ids": [2],
            "updated_at": "fixture-time",
        }
    )
    checkpoint = PlanningSnapshotCheckpoint.from_dict(
        {"registry_layer_ids": [40], "layers": [layer.to_dict(), "ignored"]}
    )
    assert checkpoint.for_layer(40) == layer
    assert checkpoint.for_layer(99) is None
    assert PlanningSnapshotCheckpoint.from_dict(checkpoint.to_dict()).registry_layer_ids == (40,)
    with pytest.raises(ValueError, match="layers must be a list"):
        PlanningSnapshotCheckpoint.from_dict({"layers": "bad"})

    layer13 = spec(13, "Parcel")
    coastal = LayerSpec(
        layer_id=41,
        name="Coastal",
        evidence_class=EvidenceClass.CONTEXTUAL,
        query_policy=QueryPolicy.COASTAL,
        out_fields=("OBJECTID",),
        role="coastal fixture",
    )
    assert [item.layer_id for item in snapshot_module.canonical_planning_specs((layer13, coastal))] == [41]
    assert [
        item.layer_id
        for item in snapshot_module.canonical_planning_specs(
            (layer13, coastal),
            include_layer13=True,
            context=EvidenceContext(coastal=False),
        )
    ] == [13]

    assert snapshot_module._int_id(True) is None
    assert snapshot_module._int_id("not-an-id") is None
    assert snapshot_module._int_id(-1) is None
    assert snapshot_module._usable_geometry({"paths": [[[0, 0], [1, 1]]]}, "esriGeometryPolyline")
    assert snapshot_module._usable_geometry({"x": 1, "y": 2}, "esriGeometryPoint")
    assert not snapshot_module._usable_geometry({"x": 1}, "esriGeometryPoint")
    assert snapshot_module._usable_geometry({"value": 1}, "custom")
    assert not snapshot_module._usable_geometry(None, "custom")


def test_response_payload_guards_classify_protocol_failures():
    assert snapshot_module._response_payload({"ok": True}) == {"ok": True}

    class BrokenResponse:
        status_code = 502

        def json(self):
            raise ValueError("not json")

    class ListResponse:
        status_code = 200

        def json(self):
            return []

    with pytest.raises(PlanningSnapshotError, match="non-JSON"):
        snapshot_module._response_payload(BrokenResponse())
    with pytest.raises(PlanningSnapshotError, match="non-object"):
        snapshot_module._response_payload(ListResponse())
    with pytest.raises(PlanningSnapshotError, match="ArcGIS planning-layer error"):
        snapshot_module._response_payload(Response({"error": "denied"}))
    with pytest.raises(PlanningSnapshotError, match="HTTP error"):
        snapshot_module._response_payload(Response({}, status_code=404))


def test_request_retry_guards_cover_http_generic_and_nonretryable_failures():
    sleeps: List[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    connect_error = httpx.ConnectError("offline", request=httpx.Request("GET", "https://fixture"))
    client = FakeClient([connect_error, connect_error])
    with pytest.raises(PlanningSnapshotError, match="after 2 attempts"):
        asyncio.run(
            snapshot_module._get_json(
                client,
                "https://fixture",
                {},
                PlanningIngestionConfig(max_attempts=2),
                sleep,
            )
        )
    assert len(sleeps) == 1

    client = FakeClient([ValueError("broken client")])
    with pytest.raises(PlanningSnapshotError, match="broken client"):
        asyncio.run(
            snapshot_module._get_json(
                client,
                "https://fixture",
                {},
                PlanningIngestionConfig(max_attempts=1),
                sleep,
            )
        )

    client = FakeClient([Response({}, status_code=400)])
    with pytest.raises(PlanningSnapshotError, match="HTTP error"):
        asyncio.run(
            snapshot_module._get_json(
                client,
                "https://fixture",
                {},
                PlanningIngestionConfig(max_attempts=3),
                sleep,
            )
        )
    assert len(client.calls) == 1


def test_ingestion_manifests_malformed_inventory_batch_and_features():
    inventory_failure = run(
        FakeClient([Response({"features": []})]),
        specs=(spec(40),),
        config=PlanningIngestionConfig(fetch_layer_metadata=False, max_attempts=1),
    )
    assert not inventory_failure.complete
    assert "objectIds" in str(inventory_failure.manifest.layers[0].inventory_error)

    missing_features = run(
        FakeClient([Response({"objectIds": [1]}), Response({"unexpected": []})]),
        specs=(spec(40),),
        config=PlanningIngestionConfig(fetch_layer_metadata=False, max_attempts=1),
    )
    assert missing_features.manifest.layers[0].rejected_ids == (1,)
    assert "features list" in missing_features.manifest.layers[0].batch_errors[0]

    malformed = run(
        FakeClient(
            [
                Response({"objectIds": [1, 2]}),
                Response(
                    {
                        "features": [
                            feature(1),
                            feature(1),
                            feature(99),
                            "not-an-object",
                            {"attributes": []},
                            {"attributes": {"CODE": "missing-oid"}, "geometry": {}},
                        ]
                    }
                ),
            ]
        ),
        specs=(spec(40),),
        config=PlanningIngestionConfig(fetch_layer_metadata=False),
    )
    layer = malformed.manifest.layers[0]
    assert layer.received_ids == (1,)
    assert layer.missing_ids == (2,)
    assert layer.duplicate_ids == (1,)
    assert layer.extra_ids == (99,)
    assert layer.invalid_feature_count == 3


def test_durable_sink_guards_sync_inventory_and_batch_errors():
    outside = run(
        FakeClient([Response({"objectIds": [1]})]),
        specs=(spec(40),),
        config=PlanningIngestionConfig(fetch_layer_metadata=False),
        on_inventory=lambda *_args: (99,),
    )
    assert not outside.complete
    assert "outside layer" in str(outside.manifest.layers[0].inventory_error)

    def reject_batch(*_args):
        raise RuntimeError("disk full")

    with pytest.raises(PlanningSnapshotError, match="durable planning sink rejected"):
        run(
            FakeClient([Response({"objectIds": [1]}), Response({"features": [feature(1)]})]),
            specs=(spec(40),),
            config=PlanningIngestionConfig(fetch_layer_metadata=False),
            on_batch=reject_batch,
        )
