"""Bounded, resumable download of the canonical MCGM planning layers.

This module is deliberately storage-agnostic.  The downloader owns the
ArcGIS protocol, retry policy, inventory reconciliation, and audit manifest;
an application or storage adapter owns where accepted features are written.
That separation lets a SQLite, object-store, or test sink stream batches
without keeping a city-wide planning corpus in memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import httpx

from dp_lookup.planning_evidence.models import EvidenceContext, LayerSpec
from dp_lookup.planning_evidence.registry import LAYER_SPECS, SERVER_URL, deduplicate_layer_specs

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class PlanningSnapshotError(RuntimeError):
    """The planning-layer source or a durable sink could not be used safely."""


@dataclass(frozen=True)
class PlanningFeature:
    """One accepted feature, retaining the source attributes and geometry."""

    layer_id: int
    object_id: int
    attributes: Mapping[str, Any]
    geometry: Any
    raw_feature: Mapping[str, Any]


@dataclass(frozen=True)
class PlanningLayerCheckpoint:
    """Durable progress for one layer and one exact source inventory."""

    layer_id: int
    expected_ids: Tuple[int, ...]
    completed_ids: Tuple[int, ...] = ()
    rejected_ids: Tuple[int, ...] = ()
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_ids", tuple(sorted(set(int(item) for item in self.expected_ids))))
        object.__setattr__(self, "completed_ids", tuple(sorted(set(int(item) for item in self.completed_ids))))
        object.__setattr__(self, "rejected_ids", tuple(sorted(set(int(item) for item in self.rejected_ids))))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "expected_ids": list(self.expected_ids),
            "completed_ids": list(self.completed_ids),
            "rejected_ids": list(self.rejected_ids),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanningLayerCheckpoint":
        """Restore a checkpoint written by :meth:`to_dict`."""

        return cls(
            layer_id=int(payload["layer_id"]),
            expected_ids=tuple(payload.get("expected_ids", ())),
            completed_ids=tuple(payload.get("completed_ids", ())),
            rejected_ids=tuple(payload.get("rejected_ids", ())),
            updated_at=str(payload.get("updated_at") or utc_now()),
        )


@dataclass(frozen=True)
class PlanningSnapshotCheckpoint:
    """Serializable checkpoint for all canonical layers in a build."""

    layers: Tuple[PlanningLayerCheckpoint, ...] = ()
    registry_layer_ids: Tuple[int, ...] = ()
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "layers", tuple(self.layers))
        object.__setattr__(self, "registry_layer_ids", tuple(int(item) for item in self.registry_layer_ids))

    def for_layer(self, layer_id: int) -> Optional[PlanningLayerCheckpoint]:
        return next((item for item in self.layers if item.layer_id == layer_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "registry_layer_ids": list(self.registry_layer_ids),
            "layers": [item.to_dict() for item in self.layers],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanningSnapshotCheckpoint":
        """Restore a checkpoint written by :meth:`to_dict`."""

        raw_layers = payload.get("layers", ())
        if not isinstance(raw_layers, (list, tuple)):
            raise ValueError("checkpoint layers must be a list")
        return cls(
            layers=tuple(
                PlanningLayerCheckpoint.from_dict(item)
                for item in raw_layers
                if isinstance(item, Mapping)
            ),
            registry_layer_ids=tuple(payload.get("registry_layer_ids", ())),
            updated_at=str(payload.get("updated_at") or utc_now()),
        )


@dataclass(frozen=True)
class PlanningIngestionConfig:
    """Safety limits for city-wide ArcGIS pulls.

    ``max_batch_size`` is an explicit guardrail against accidentally issuing a
    request larger than the service's transfer limits.  Retries are per HTTP
    request and never multiply through the shared transport adapter.
    """

    batch_size: int = 500
    max_batch_size: int = 2000
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    request_delay_seconds: float = 0.0
    out_sr: int = 102100
    fetch_layer_metadata: bool = True
    # Runtime evidence queries deliberately request an audited field subset;
    # the durable source archive keeps every published attribute so future
    # features do not require a destructive re-download just to expose a field.
    all_fields: bool = False

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")
        if self.batch_size > self.max_batch_size:
            raise ValueError("batch_size cannot exceed max_batch_size")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0 or self.request_delay_seconds < 0:
            raise ValueError("delays must not be negative")


@dataclass(frozen=True)
class PlanningLayerManifest:
    """Audit and completeness record for one canonical source layer."""

    layer_id: int
    name: str
    source_url: str
    object_id_field: str
    geometry_type: str
    out_fields: Tuple[str, ...]
    expected_ids: Tuple[int, ...]
    received_ids: Tuple[int, ...]
    missing_ids: Tuple[int, ...]
    duplicate_ids: Tuple[int, ...] = ()
    rejected_ids: Tuple[int, ...] = ()
    extra_ids: Tuple[int, ...] = ()
    invalid_feature_count: int = 0
    non_spatial_feature_count: int = 0
    inventory_error: Optional[str] = None
    batch_errors: Tuple[str, ...] = ()
    schema_metadata: Mapping[str, Any] = field(default_factory=dict)
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=utc_now)
    content_hash: str = ""

    @property
    def complete(self) -> bool:
        return not (
            self.inventory_error
            or self.missing_ids
            or self.rejected_ids
            or self.extra_ids
            or self.batch_errors
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "name": self.name,
            "source_url": self.source_url,
            "object_id_field": self.object_id_field,
            "geometry_type": self.geometry_type,
            "out_fields": list(self.out_fields),
            "expected_ids": list(self.expected_ids),
            "received_ids": list(self.received_ids),
            "missing_ids": list(self.missing_ids),
            "duplicate_ids": list(self.duplicate_ids),
            "rejected_ids": list(self.rejected_ids),
            "extra_ids": list(self.extra_ids),
            "invalid_feature_count": self.invalid_feature_count,
            "non_spatial_feature_count": self.non_spatial_feature_count,
            "inventory_error": self.inventory_error,
            "batch_errors": list(self.batch_errors),
            "schema_metadata": dict(self.schema_metadata),
            "source_metadata": dict(self.source_metadata),
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
            "complete": self.complete,
        }


@dataclass(frozen=True)
class PlanningSnapshotManifest:
    """Top-level audit manifest for a canonical planning snapshot."""

    service_url: str
    registry_layer_ids: Tuple[int, ...]
    layers: Tuple[PlanningLayerManifest, ...]
    retrieved_at: str = field(default_factory=utc_now)
    registry_hash: str = ""
    warnings: Tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return len(self.layers) == len(self.registry_layer_ids) and all(item.complete for item in self.layers)

    @property
    def content_hash(self) -> str:
        payload = [item.content_hash for item in self.layers]
        return _sha256_json(payload) if all(payload) else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_url": self.service_url,
            "registry_layer_ids": list(self.registry_layer_ids),
            "registry_hash": self.registry_hash,
            "retrieved_at": self.retrieved_at,
            "layers": [item.to_dict() for item in self.layers],
            "complete": self.complete,
            "content_hash": self.content_hash,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PlanningSnapshotResult:
    """Accepted features, audit manifest, and resume checkpoint."""

    features: Tuple[PlanningFeature, ...]
    manifest: PlanningSnapshotManifest
    checkpoint: PlanningSnapshotCheckpoint

    @property
    def complete(self) -> bool:
        return self.manifest.complete


InventoryConsumer = Callable[[LayerSpec, Tuple[int, ...], Mapping[str, Any]], Any]
BatchConsumer = Callable[[LayerSpec, Tuple[PlanningFeature, ...]], Any]


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def canonical_planning_specs(
    specs: Optional[Iterable[LayerSpec]] = None,
    *,
    context: Optional[EvidenceContext] = None,
    include_layer13: bool = False,
) -> Tuple[LayerSpec, ...]:
    """Return one spec per canonical planning source, in registry order.

    Layer 13 is the cadastral identity anchor and has its own mature builder;
    planning snapshots therefore exclude it by default.  ``include_layer13``
    exists for callers building a combined source archive.
    """

    selected: Tuple[LayerSpec, ...] = deduplicate_layer_specs(tuple(LAYER_SPECS if specs is None else specs))
    if not include_layer13:
        selected = tuple(spec for spec in selected if spec.layer_id != 13)
    if context is not None:
        selected = tuple(spec for spec in selected if spec.is_applicable(context))
    return selected


def _int_id(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 and str(value).strip() not in {"", "None", "null"} else None


def _sorted_ids(values: Iterable[Any]) -> Tuple[int, ...]:
    return tuple(sorted({parsed for parsed in (_int_id(value) for value in values) if parsed is not None}))


def _chunks(values: Sequence[int], size: int) -> Iterable[Tuple[int, ...]]:
    for offset in range(0, len(values), size):
        yield tuple(values[offset : offset + size])


def _retry_delay(config: PlanningIngestionConfig, attempt: int, response: Any = None) -> float:
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    if retry_after is not None:
        try:
            return min(config.max_delay_seconds, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    return min(config.max_delay_seconds, config.base_delay_seconds * float(2 ** max(0, attempt - 1)))


def _response_payload(response: Any) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        status = 200
        payload: Any = response
    else:
        status = int(getattr(response, "status_code", 0) or 0)
        try:
            payload = response.json()
        except Exception as exc:
            raise PlanningSnapshotError(f"planning layer returned non-JSON response (status {status})") from exc
    if not isinstance(payload, Mapping):
        raise PlanningSnapshotError(f"planning layer returned a non-object JSON response (status {status})")
    if "error" in payload:
        error = payload.get("error")
        detail = error.get("message") if isinstance(error, Mapping) else str(error)
        raise PlanningSnapshotError(f"ArcGIS planning-layer error (status {status}): {detail or error}")
    if status != 200:
        raise PlanningSnapshotError(f"planning layer HTTP error (status {status})")
    return payload


async def _get_json(
    client: Any,
    url: str,
    params: Mapping[str, Any],
    config: PlanningIngestionConfig,
    sleep: Callable[[float], Awaitable[Any]],
    *,
    post_form: bool = False,
) -> Mapping[str, Any]:
    last_error: Optional[BaseException] = None
    for attempt in range(1, config.max_attempts + 1):
        response: Any = None
        try:
            if post_form and getattr(client, "post", None) is not None:
                response = await client.post(url, data=dict(params))
            else:
                response = await client.get(url, params=dict(params))
            status = int(getattr(response, "status_code", 200) or 0) if not isinstance(response, Mapping) else 200
            try:
                return _response_payload(response)
            except PlanningSnapshotError as exc:
                last_error = exc
                if status not in (0, 200) and status not in RETRYABLE_STATUS_CODES:
                    raise
                if attempt == config.max_attempts:
                    raise
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == config.max_attempts:
                raise PlanningSnapshotError(f"planning-layer request failed after {attempt} attempts: {exc}") from exc
        except PlanningSnapshotError:
            if (
                status not in (0, 200)
                and status not in RETRYABLE_STATUS_CODES
            ) or attempt == config.max_attempts:
                raise
        except Exception as exc:
            last_error = exc
            if attempt == config.max_attempts:
                raise PlanningSnapshotError(f"planning-layer request failed after {attempt} attempts: {exc}") from exc
        await sleep(_retry_delay(config, attempt, response))
    raise PlanningSnapshotError("planning-layer request failed without a response") from last_error


def _usable_geometry(geometry: Any, geometry_type: str) -> bool:
    if not isinstance(geometry, Mapping):
        return False
    if geometry_type == "esriGeometryPolygon":
        rings = geometry.get("rings")
        return isinstance(rings, list) and bool(rings)
    if geometry_type == "esriGeometryPolyline":
        paths = geometry.get("paths")
        return isinstance(paths, list) and bool(paths)
    if geometry_type == "esriGeometryPoint":
        return geometry.get("x") is not None and geometry.get("y") is not None
    return bool(geometry)


def _feature_from_raw(
    spec: LayerSpec,
    raw_feature: Any,
    *,
    object_id_field: Optional[str] = None,
    geometry_type: Optional[str] = None,
) -> Tuple[Optional[PlanningFeature], Optional[str]]:
    if not isinstance(raw_feature, Mapping):
        return None, "feature is not an object"
    attrs = raw_feature.get("attributes")
    geometry = raw_feature.get("geometry")
    if not isinstance(attrs, Mapping):
        return None, "feature attributes are missing or malformed"
    resolved_object_id_field = object_id_field or spec.object_id_field
    resolved_geometry_type = geometry_type or spec.geometry_type
    object_id = _int_id(attrs.get(resolved_object_id_field))
    if object_id is None:
        object_id = _int_id(attrs.get("OBJECTID"))
    if object_id is None:
        return None, f"feature has no usable {resolved_object_id_field}"
    spatial_warning = None
    if not _usable_geometry(geometry, resolved_geometry_type):
        # An authoritative inventory can legitimately contain a record with
        # empty source geometry. Preserve it exactly and keep it out of spatial
        # hits instead of silently dropping the source ObjectID.
        spatial_warning = f"feature geometry is empty or not usable as {resolved_geometry_type}"
    return PlanningFeature(
        spec.layer_id,
        object_id,
        dict(attrs),
        dict(geometry) if isinstance(geometry, Mapping) else geometry,
        dict(raw_feature),
    ), spatial_warning


def planning_registry_hash(specs: Sequence[LayerSpec]) -> str:
    return _sha256_json(
        [
            {
                "layer_id": spec.layer_id,
                "name": spec.name,
                "object_id_field": spec.object_id_field,
                "geometry_type": spec.geometry_type,
                "out_fields": list(spec.out_fields),
                "role": spec.role,
            }
            for spec in specs
        ]
    )


async def ingest_planning_snapshot(
    client: Any,
    *,
    specs: Optional[Iterable[LayerSpec]] = None,
    context: Optional[EvidenceContext] = None,
    config: Optional[PlanningIngestionConfig] = None,
    checkpoint: Optional[PlanningSnapshotCheckpoint] = None,
    on_inventory: Optional[InventoryConsumer] = None,
    on_batch: Optional[BatchConsumer] = None,
    retain_features: bool = True,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> PlanningSnapshotResult:
    """Download every selected canonical layer with resumable streaming.

    Inventory requests are always issued first and each layer is fetched
    sequentially with bounded POST batches.  A failed layer is retained in the
    returned manifest so callers can persist the checkpoint and retry safely;
    a durable sink callback failure is raised immediately because accepting a
    batch without persistence would make resume unsafe.
    """

    cfg = config or PlanningIngestionConfig()
    selected_specs = canonical_planning_specs(specs, context=context)
    selected_ids = tuple(spec.layer_id for spec in selected_specs)
    if checkpoint is not None and checkpoint.registry_layer_ids and checkpoint.registry_layer_ids != selected_ids:
        raise PlanningSnapshotError("resume checkpoint belongs to a different canonical planning registry")

    received_features: Dict[Tuple[int, int], PlanningFeature] = {}
    layer_manifests: List[PlanningLayerManifest] = []
    layer_checkpoints: List[PlanningLayerCheckpoint] = []
    warnings: List[str] = []

    for spec in selected_specs:
        layer_url = f"{SERVER_URL}/{spec.layer_id}"
        inventory_params = {
            "where": "1=1",
            "returnIdsOnly": "true",
            "returnGeometry": "false",
            "f": "json",
        }
        previous = checkpoint.for_layer(spec.layer_id) if checkpoint is not None else None
        expected_ids: Tuple[int, ...] = ()
        completed: set[int] = set()
        rejected: set[int] = set(previous.rejected_ids if previous else ())
        duplicates: set[int] = set()
        extras: set[int] = set()
        invalid_count = 0
        non_spatial_count = 0
        batch_errors: List[str] = []
        inventory_error: Optional[str] = None
        observed_fields: set[str] = set()
        observed_geometry: Optional[str] = None
        source_metadata: Dict[str, Any] = {
            "service_url": SERVER_URL,
            "layer_id": spec.layer_id,
            "inventory_request": inventory_params,
            "batch_request_method": "POST",
            "batch_out_fields": "*" if cfg.all_fields else list(spec.out_fields),
            "requested_out_sr": cfg.out_sr,
            "query_policy": spec.query_policy.value,
            "evidence_class": spec.evidence_class.value,
            "role": spec.role,
            "audit_note": spec.audit_note,
        }
        metadata: Mapping[str, Any] = {}
        resolved_object_id_field = spec.object_id_field
        resolved_geometry_type = spec.geometry_type
        raw_for_hash: List[Mapping[str, Any]] = []
        try:
            inventory = await _get_json(client, f"{layer_url}/query", inventory_params, cfg, sleep)
            raw_ids = inventory.get("objectIds")
            if not isinstance(raw_ids, list):
                raise PlanningSnapshotError("inventory did not contain an objectIds list")
            expected_ids = _sorted_ids(raw_ids)
            parsed_ids = [_int_id(item) for item in raw_ids]
            duplicates.update(
                item
                for item in set(parsed_ids)
                if item is not None and parsed_ids.count(item) > 1
            )
            source_metadata["inventory_spatial_reference"] = inventory.get("spatialReference")
            if cfg.fetch_layer_metadata:
                metadata = await _get_json(client, layer_url, {"f": "json"}, cfg, sleep)
                source_metadata["metadata_request"] = {"f": "json"}
                source_metadata["object_id_field_advertised"] = metadata.get("objectIdField")
                source_metadata["source_spatial_reference"] = metadata.get("spatialReference")
                advertised_object_id = metadata.get("objectIdField")
                metadata_fields = metadata.get("fields")
                oid_fields = [
                    str(field.get("name"))
                    for field in metadata_fields
                    if isinstance(field, Mapping)
                    and field.get("type") == "esriFieldTypeOID"
                    and field.get("name")
                ] if isinstance(metadata_fields, list) else []
                if oid_fields:
                    resolved_object_id_field = oid_fields[0]
                elif isinstance(advertised_object_id, str) and advertised_object_id.strip():
                    resolved_object_id_field = advertised_object_id.strip()
                advertised_geometry = metadata.get("geometryType")
                if isinstance(advertised_geometry, str) and advertised_geometry.strip():
                    resolved_geometry_type = advertised_geometry.strip()
                source_metadata["object_id_field_resolved"] = resolved_object_id_field
                source_metadata["geometry_type_resolved"] = resolved_geometry_type
            if previous is not None and tuple(previous.expected_ids) != expected_ids:
                raise PlanningSnapshotError(f"resume checkpoint for layer {spec.layer_id} has a different inventory")
            if on_inventory is not None:
                context_payload = {
                    "source_url": layer_url,
                    "service_url": SERVER_URL,
                    "layer_id": spec.layer_id,
                    "object_id_field": resolved_object_id_field,
                    "geometry_type": resolved_geometry_type,
                    "out_fields": spec.out_fields,
                    "expected_ids": expected_ids,
                    "layer_metadata": dict(metadata),
                }
                persisted = await _maybe_await(on_inventory(spec, expected_ids, context_payload))
                persisted_ids = _sorted_ids(persisted or ())
                if not set(persisted_ids).issubset(expected_ids):
                    raise PlanningSnapshotError(f"durable sink contains IDs outside layer {spec.layer_id} inventory")
                completed.update(persisted_ids)
            elif previous is not None:
                completed.update(item for item in previous.completed_ids if item in expected_ids)
            rejected.difference_update(completed)
        except PlanningSnapshotError as exc:
            if "resume checkpoint" in str(exc):
                raise
            inventory_error = str(exc)

        if inventory_error is None:
            for batch in _chunks([item for item in expected_ids if item not in completed], cfg.batch_size):
                params = {
                    "objectIds": ",".join(str(item) for item in batch),
                    "outFields": "*" if cfg.all_fields else ",".join(spec.out_fields),
                    "returnGeometry": "true",
                    "outSR": str(cfg.out_sr),
                    "f": "json",
                }
                try:
                    payload = await _get_json(client, f"{layer_url}/query", params, cfg, sleep, post_form=True)
                except PlanningSnapshotError as exc:
                    batch_errors.append(f"objectIds={','.join(map(str, batch))}: {exc}")
                    rejected.update(batch)
                    continue
                features = payload.get("features")
                if not isinstance(features, list):
                    batch_errors.append(f"objectIds={','.join(map(str, batch))}: missing features list")
                    rejected.update(batch)
                    continue
                accepted: List[PlanningFeature] = []
                for raw_feature in features:
                    parsed, feature_warning = _feature_from_raw(
                        spec,
                        raw_feature,
                        object_id_field=resolved_object_id_field,
                        geometry_type=resolved_geometry_type,
                    )
                    if parsed is None:
                        invalid_count += 1
                        continue
                    if feature_warning:
                        non_spatial_count += 1
                    observed_fields.update(str(key) for key in parsed.attributes)
                    observed_geometry = resolved_geometry_type
                    if parsed.object_id not in expected_ids:
                        extras.add(parsed.object_id)
                        continue
                    if parsed.object_id in completed:
                        duplicates.add(parsed.object_id)
                        continue
                    accepted.append(parsed)
                    completed.add(parsed.object_id)
                    rejected.discard(parsed.object_id)
                    raw_for_hash.append(parsed.raw_feature)
                    if retain_features:
                        received_features[(spec.layer_id, parsed.object_id)] = parsed
                if on_batch is not None and accepted:
                    try:
                        await _maybe_await(on_batch(spec, tuple(accepted)))
                    except Exception as exc:
                        raise PlanningSnapshotError(f"durable planning sink rejected layer {spec.layer_id} batch: {exc}") from exc
                if cfg.request_delay_seconds:
                    await sleep(cfg.request_delay_seconds)

        received_ids = tuple(sorted(completed))
        missing_ids = tuple(sorted(set(expected_ids) - set(received_ids)))
        if previous is not None and tuple(previous.expected_ids) != expected_ids and inventory_error is None:
            inventory_error = f"resume checkpoint for layer {spec.layer_id} has a different inventory"
        source_metadata["content_hash_scope"] = "complete_features_in_run" if raw_for_hash else "durable_sink_or_empty"
        source_metadata["batch_limit"] = cfg.batch_size
        layer_manifest = PlanningLayerManifest(
            layer_id=spec.layer_id,
            name=spec.name,
            source_url=layer_url,
            object_id_field=resolved_object_id_field,
            geometry_type=resolved_geometry_type,
            out_fields=("*",) if cfg.all_fields else spec.out_fields,
            expected_ids=expected_ids,
            received_ids=received_ids,
            missing_ids=missing_ids,
            duplicate_ids=tuple(sorted(duplicates)),
            rejected_ids=tuple(sorted(rejected)),
            extra_ids=tuple(sorted(extras)),
            invalid_feature_count=invalid_count,
            non_spatial_feature_count=non_spatial_count,
            inventory_error=inventory_error,
            batch_errors=tuple(batch_errors),
            schema_metadata={
                "fields_observed": sorted(observed_fields),
                "geometry_type_observed": observed_geometry,
                "layer_metadata": dict(metadata),
            },
            source_metadata=source_metadata,
            content_hash=_sha256_json(sorted(raw_for_hash, key=lambda item: _int_id((item.get("attributes") or {}).get(resolved_object_id_field)) or 0)) if raw_for_hash else "",
        )
        layer_manifests.append(layer_manifest)
        layer_checkpoints.append(
            PlanningLayerCheckpoint(
                layer_id=spec.layer_id,
                expected_ids=expected_ids,
                completed_ids=received_ids,
                rejected_ids=tuple(sorted(rejected)),
            )
        )
        if not layer_manifest.complete:
            warnings.append(
                f"layer {spec.layer_id} incomplete: missing={len(missing_ids)}, "
                f"rejected={len(rejected)}, errors={len(batch_errors) + (1 if inventory_error else 0)}"
            )

    manifest = PlanningSnapshotManifest(
        service_url=SERVER_URL,
        registry_layer_ids=selected_ids,
        layers=tuple(layer_manifests),
        registry_hash=planning_registry_hash(selected_specs),
        warnings=tuple(warnings),
    )
    checkpoint_out = PlanningSnapshotCheckpoint(
        layers=tuple(layer_checkpoints),
        registry_layer_ids=selected_ids,
    )
    return PlanningSnapshotResult(tuple(received_features.values()), manifest, checkpoint_out)


__all__ = [
    "PlanningFeature",
    "PlanningIngestionConfig",
    "PlanningLayerCheckpoint",
    "PlanningLayerManifest",
    "PlanningSnapshotCheckpoint",
    "PlanningSnapshotError",
    "PlanningSnapshotManifest",
    "PlanningSnapshotResult",
    "canonical_planning_specs",
    "ingest_planning_snapshot",
    "planning_registry_hash",
]
