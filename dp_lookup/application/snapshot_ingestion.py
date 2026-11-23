"""Reliable, store-agnostic bulk ingestion of MCGM Development Plan Layer 13."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from dp_lookup.clients.parcel_snapshot import (
    DEFAULT_OUT_SR,
    LAYER13_ID,
    LAYER13_URL,
    SnapshotCheckpoint,
    SnapshotFeature,
    SnapshotIngestionError,
    SnapshotIngestionResult,
    SnapshotManifest,
    resolve_object_id_field,
    sha256_json,
)
from dp_lookup.clients.transport import RETRYABLE_STATUS_CODES
from dp_lookup.core.batching import batched
from dp_lookup.core.topology import arcgis_rings_to_geometry


class IngestionClient(Protocol):
    """The two ArcGIS calls the importer makes; ``ArcGISClient`` implements both."""

    async def get(self, url: str, *, params: Mapping[str, Any]) -> httpx.Response: ...

    async def post(self, url: str, *, data: Mapping[str, Any]) -> httpx.Response: ...


InventoryConsumer = Callable[[tuple[int, ...], Mapping[str, Any]], Awaitable[Iterable[int]]]
BatchConsumer = Callable[[tuple[SnapshotFeature, ...]], Awaitable[Any]]


@dataclass(frozen=True)
class SnapshotIngestionConfig:
    batch_size: int = 2000
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 4.0
    request_delay_seconds: float = 0.0
    out_sr: int = DEFAULT_OUT_SR
    fetch_layer_metadata: bool = False

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0 or self.request_delay_seconds < 0:
            raise ValueError("delays must not be negative")


def _response_payload(response: httpx.Response) -> Mapping[str, Any]:
    status = response.status_code
    try:
        payload = response.json()
    except ValueError as exc:
        raise SnapshotIngestionError(f"Layer 13 returned non-JSON response (status {status}).") from exc
    if not isinstance(payload, Mapping):
        raise SnapshotIngestionError(f"Layer 13 returned a non-object JSON response (status {status}).")
    if "error" in payload:
        error = payload.get("error")
        if isinstance(error, Mapping):
            detail = error.get("message") or error.get("details") or repr(dict(error))
        else:
            detail = str(error)
        raise SnapshotIngestionError(f"Layer 13 ArcGIS error (status {status}): {detail}")
    if status != 200:
        raise SnapshotIngestionError(f"Layer 13 HTTP error (status {status}).")
    return payload


def _retry_delay(config: SnapshotIngestionConfig, attempt: int, response: httpx.Response | None = None) -> float:
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after is not None:
        try:
            return min(config.max_delay_seconds, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(config.max_delay_seconds, config.base_delay_seconds * float(2 ** max(0, attempt - 1)))


async def _get_json(
    client: IngestionClient,
    url: str,
    params: Mapping[str, Any],
    config: SnapshotIngestionConfig,
    sleep: Callable[[float], Awaitable[Any]],
    *,
    post_form: bool = False,
) -> Mapping[str, Any]:
    """Request JSON, retrying transport errors, retryable statuses and ArcGIS error bodies sent with 200.

    ``post_form`` sends the parameters as a form POST, which long ObjectID lists need.
    """
    last_error: BaseException | None = None
    for attempt in range(1, config.max_attempts + 1):
        response: httpx.Response | None = None
        try:
            if post_form:
                response = await client.post(url, data=dict(params))
            else:
                response = await client.get(url, params=dict(params))
            return _response_payload(response)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == config.max_attempts:
                raise SnapshotIngestionError(f"Layer 13 request failed after {attempt} attempts: {exc}") from exc
        except SnapshotIngestionError as exc:
            last_error = exc
            assert response is not None
            status = response.status_code
            if attempt == config.max_attempts or (status != 200 and status not in RETRYABLE_STATUS_CODES):
                raise
        await sleep(_retry_delay(config, attempt, response))
    raise SnapshotIngestionError("Layer 13 request failed without a response.") from last_error


def _int_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        integer = int(value)
    except Exception:
        return None
    return integer if integer >= 0 and str(value).strip() not in {"", "None", "null"} else None


def _sorted_ids(values: Iterable[Any]) -> tuple[int, ...]:
    parsed = [_int_id(value) for value in values]
    return tuple(sorted({value for value in parsed if value is not None}))


def _usable_polygon(geometry: Mapping[str, Any]) -> bool:
    rings = geometry.get("rings")
    if not isinstance(rings, list) or not rings:
        return False
    try:
        polygon = arcgis_rings_to_geometry(rings)
    except (TypeError, ValueError, OverflowError):
        return False
    return not polygon.is_empty and polygon.is_valid and polygon.area > 0


async def ingest_layer13_snapshot(
    client: IngestionClient,
    *,
    config: SnapshotIngestionConfig | None = None,
    checkpoint: SnapshotCheckpoint | None = None,
    prior_features: Mapping[int, SnapshotFeature] | None = None,
    on_inventory: InventoryConsumer | None = None,
    on_batch: BatchConsumer | None = None,
    retain_features: bool = True,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> SnapshotIngestionResult:
    """Fetch a complete Layer 13 snapshot without writing or publishing it.

    The inventory request is always first.  Batches are sequential, bounded,
    and resumable: a caller can persist ``result.checkpoint`` and accepted
    ``result.features`` in its own store, then pass both back next run.
    """
    cfg = config or SnapshotIngestionConfig()
    inventory_params = {"where": "1=1", "returnIdsOnly": "true", "returnGeometry": "false", "f": "json"}
    inventory = await _get_json(client, f"{LAYER13_URL}/query", inventory_params, cfg, sleep)
    raw_ids = inventory.get("objectIds")
    if not isinstance(raw_ids, list):
        raise SnapshotIngestionError("Layer 13 inventory did not contain an objectIds list.")
    parsed_inventory_ids = [_int_id(value) for value in raw_ids]
    inventory_counts = Counter(value for value in parsed_inventory_ids if value is not None)
    inventory_duplicates = {value for value, count in inventory_counts.items() if count > 1}
    expected_ids = _sorted_ids(raw_ids)
    expected_id_set = set(expected_ids)
    if not expected_ids:
        raise SnapshotIngestionError("Layer 13 inventory was empty; refusing to publish an empty snapshot.")

    prior = dict(prior_features or {})
    if checkpoint is not None and tuple(checkpoint.expected_ids) != expected_ids:
        raise SnapshotIngestionError("Resume checkpoint belongs to a different Layer 13 inventory.")
    completed = set(checkpoint.completed_ids if checkpoint else ())
    rejected = set(checkpoint.rejected_ids if checkpoint else ())
    if not completed.issubset(expected_ids) or not rejected.issubset(expected_ids):
        raise SnapshotIngestionError("Resume checkpoint contains IDs outside the current inventory.")
    completed.intersection_update(prior)

    layer_metadata: Mapping[str, Any] = {}
    if cfg.fetch_layer_metadata:
        layer_metadata = await _get_json(client, LAYER13_URL, {"f": "json"}, cfg, sleep)
    object_id_field = resolve_object_id_field(layer_metadata)
    if on_inventory is not None:
        source_context: dict[str, Any] = {
            "source_url": LAYER13_URL,
            "layer_id": LAYER13_ID,
            "object_id_field": object_id_field,
            "requested_out_sr": cfg.out_sr,
            "layer_metadata": dict(layer_metadata),
        }
        persisted_ids = _sorted_ids(await on_inventory(expected_ids, source_context))
        if not set(persisted_ids).issubset(expected_ids):
            raise SnapshotIngestionError("Durable snapshot sink contains IDs outside the current inventory.")
        completed.update(persisted_ids)

    received_ids_set = set(completed) | {oid for oid in prior if oid in expected_id_set}
    received: dict[int, SnapshotFeature] = (
        {oid: feature for oid, feature in prior.items() if oid in expected_id_set} if retain_features else {}
    )
    duplicates: set[int] = set()
    extra: set[int] = set()
    rejected_this_run: set[int] = set()
    batch_errors: list[str] = []
    invalid_count = 0
    observed_fields: set[str] = set()
    observed_geometry: str | None = None

    pending = [oid for oid in expected_ids if oid not in received_ids_set]
    for batch in batched(pending, cfg.batch_size):
        params = {
            "objectIds": ",".join(str(oid) for oid in batch),
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": str(cfg.out_sr),
            "f": "json",
        }
        try:
            payload = await _get_json(
                client,
                f"{LAYER13_URL}/query",
                params,
                cfg,
                sleep,
                post_form=True,
            )
        except SnapshotIngestionError as exc:
            batch_errors.append(str(exc))
            rejected_this_run.update(batch)
            rejected.update(batch)
            continue
        features = payload.get("features")
        if not isinstance(features, list):
            batch_errors.append(f"objectIds={','.join(map(str, batch))}: missing features list")
            rejected_this_run.update(batch)
            rejected.update(batch)
            continue
        accepted_batch: list[SnapshotFeature] = []
        for raw_feature in features:
            if not isinstance(raw_feature, Mapping):
                invalid_count += 1
                continue
            attrs = raw_feature.get("attributes")
            geometry = raw_feature.get("geometry")
            if not isinstance(attrs, Mapping) or not isinstance(geometry, Mapping) or not _usable_polygon(geometry):
                invalid_count += 1
                continue
            observed_fields.update(str(key) for key in attrs)
            if isinstance(geometry.get("rings"), list):
                observed_geometry = "esriGeometryPolygon"
            oid = _int_id(attrs.get(object_id_field))
            if oid is None:
                oid = _int_id(attrs.get("OBJECTID"))
            if oid is None:
                invalid_count += 1
                continue
            if oid not in expected_id_set:
                extra.add(oid)
                continue
            if oid in received_ids_set:
                duplicates.add(oid)
                continue
            accepted = SnapshotFeature(oid, dict(attrs), dict(geometry), dict(raw_feature))
            accepted_batch.append(accepted)
            received_ids_set.add(oid)
            if retain_features:
                received[oid] = accepted
            rejected.discard(oid)
        if on_batch is not None and accepted_batch:
            try:
                await on_batch(tuple(accepted_batch))
            except Exception as exc:
                raise SnapshotIngestionError(f"Durable snapshot sink rejected a batch: {exc}") from exc
        completed.update(item.object_id for item in accepted_batch)
        if cfg.request_delay_seconds:
            await sleep(cfg.request_delay_seconds)

    received_ids = tuple(sorted(received_ids_set))
    missing_ids = tuple(sorted(set(expected_ids) - set(received_ids)))
    rejected_ids = tuple(sorted(set(rejected) | rejected_this_run))
    raw_for_hash = [received[oid].raw_feature for oid in received_ids] if set(received) == set(received_ids) else []
    schema_metadata: dict[str, Any] = {
        "object_id_field": object_id_field,
        "fields_observed": sorted(observed_fields),
        "geometry_type_observed": observed_geometry,
    }
    if layer_metadata:
        schema_metadata["layer_metadata"] = dict(layer_metadata)
    source_sr_value = inventory.get("spatialReference") or layer_metadata.get("spatialReference")
    source_sr: Mapping[str, Any] | None = source_sr_value if isinstance(source_sr_value, Mapping) else None
    source_metadata = {
        "service_url": LAYER13_URL,
        "layer_id": LAYER13_ID,
        "inventory_request": inventory_params,
        "batch_out_fields": "*",
        "batch_request_method": "POST",
        "requested_out_sr": cfg.out_sr,
        "source_spatial_reference": source_sr,
        "object_id_field_advertised": layer_metadata.get("objectIdField") if layer_metadata else None,
        "object_id_field_resolution": "fields OID type, then advertised field, then OBJECTID fallback",
        "content_hash_scope": "complete" if raw_for_hash or not received_ids else "durable_sink",
    }
    manifest = SnapshotManifest(
        source_url=LAYER13_URL,
        layer_id=LAYER13_ID,
        object_id_field=object_id_field,
        requested_out_sr=cfg.out_sr,
        source_spatial_reference=source_sr,
        expected_ids=expected_ids,
        received_ids=received_ids,
        missing_ids=missing_ids,
        duplicate_ids=tuple(sorted(duplicates | inventory_duplicates)),
        rejected_ids=rejected_ids,
        extra_ids=tuple(sorted(extra)),
        invalid_feature_count=invalid_count,
        batch_errors=tuple(batch_errors),
        schema_metadata=schema_metadata,
        source_metadata=source_metadata,
        content_hash=sha256_json(raw_for_hash) if raw_for_hash or not received_ids else "",
    )
    checkpoint_out = SnapshotCheckpoint(
        expected_ids=expected_ids,
        completed_ids=received_ids,
        rejected_ids=rejected_ids,
    )
    retained_ids = tuple(sorted(received))
    return SnapshotIngestionResult(tuple(received[oid] for oid in retained_ids), manifest, checkpoint_out)


__all__ = [
    "SnapshotIngestionConfig",
    "ingest_layer13_snapshot",
]
