"""Read-only ArcGIS change detection for local parcel and planning snapshots."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, cast

from dp_lookup.application.planning_snapshot import canonical_planning_specs
from dp_lookup.clients.parcel_snapshot import LAYER13_URL, resolve_object_id_field, sha256_json


class UpstreamCheckError(RuntimeError):
    """The local baseline or upstream ArcGIS response could not be checked."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_response(response: Any, source_url: str) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        payload = response
        status = 200
    else:
        status = int(getattr(response, "status_code", 0) or 0)
        try:
            payload = response.json()
        except Exception as exc:
            raise UpstreamCheckError(f"{source_url} returned a non-JSON response") from exc
    if status != 200:
        raise UpstreamCheckError(f"{source_url} returned HTTP {status}")
    if not isinstance(payload, Mapping):
        raise UpstreamCheckError(f"{source_url} returned a non-object JSON response")
    if payload.get("error"):
        error = payload["error"]
        detail = error.get("message") if isinstance(error, Mapping) else str(error)
        raise UpstreamCheckError(f"{source_url} returned an ArcGIS error: {detail}")
    return payload


async def _get_json(client: Any, url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        return _decode_response(await client.get(url, params=dict(params)), url)
    except UpstreamCheckError:
        raise
    except Exception as exc:
        raise UpstreamCheckError(f"{url} could not be checked: {exc}") from exc


def _field_contract(field: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "name": field.get("name"),
        "type": field.get("type"),
        "length": field.get("length"),
        "nullable": field.get("nullable"),
    }


def metadata_contract(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return only data-contract fields; renderers and labels are irrelevant."""
    fields = metadata.get("fields")
    return {
        "id": metadata.get("id"),
        "name": metadata.get("name"),
        "type": metadata.get("type"),
        "geometry_type": metadata.get("geometryType"),
        "object_id_field": resolve_object_id_field(metadata),
        "source_spatial_reference": metadata.get("sourceSpatialReference") or metadata.get("spatialReference"),
        "fields": [_field_contract(item) for item in fields if isinstance(item, Mapping)]
        if isinstance(fields, list)
        else [],
    }


def metadata_hash(metadata: Mapping[str, Any]) -> str:
    return str(sha256_json(metadata_contract(metadata)))


def inventory_hash(object_ids: Sequence[Any]) -> str:
    parsed = sorted({int(value) for value in object_ids if not isinstance(value, bool)})
    return str(sha256_json(parsed))


def _edit_timestamp(metadata: Mapping[str, Any]) -> Any:
    editing = metadata.get("editingInfo")
    if isinstance(editing, Mapping):
        return editing.get("lastEditDate")
    return None


def _edit_field(metadata: Mapping[str, Any]) -> Optional[str]:
    fields = metadata.get("fields")
    if not isinstance(fields, list):
        return None
    dated: list[str] = []
    for item in fields:
        if not isinstance(item, Mapping) or item.get("type") != "esriFieldTypeDate":
            continue
        name = str(item.get("name") or "")
        if name.upper() == "LAST_EDITED_DATE":
            return name
        if "EDIT" in name.upper():
            dated.append(name)
    return dated[0] if dated else None


def _normalized_signal(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


async def _remote_layer_probe(client: Any, source_url: str) -> Dict[str, Any]:
    metadata = await _get_json(client, source_url, {"f": "json"})
    inventory = await _get_json(
        client,
        f"{source_url}/query",
        {"where": "1=1", "returnIdsOnly": "true", "returnGeometry": "false", "f": "json"},
    )
    raw_ids = inventory.get("objectIds")
    if not isinstance(raw_ids, list):
        raise UpstreamCheckError(f"{source_url} inventory did not contain objectIds")
    edit_field = _edit_field(metadata)
    max_edited = _edit_timestamp(metadata)
    if edit_field:
        statistics = json.dumps(
            [
                {
                    "statisticType": "max",
                    "onStatisticField": edit_field,
                    "outStatisticFieldName": "max_last_edited_date",
                }
            ],
            separators=(",", ":"),
        )
        try:
            payload = await _get_json(
                client,
                f"{source_url}/query",
                {
                    "where": "1=1",
                    "outStatistics": statistics,
                    "returnGeometry": "false",
                    "f": "json",
                },
            )
            features = payload.get("features")
            if isinstance(features, list) and features and isinstance(features[0], Mapping):
                attrs = features[0].get("attributes")
                if isinstance(attrs, Mapping):
                    for key, value in attrs.items():
                        if str(key).casefold() == "max_last_edited_date":
                            max_edited = value
                            break
        except UpstreamCheckError:
            # Inventory and schema still provide a useful check. The result
            # explicitly records that edit-time evidence was unavailable.
            max_edited = _edit_timestamp(metadata)
    return {
        "source_url": source_url,
        "record_count": len(set(int(value) for value in raw_ids)),
        "inventory_hash": inventory_hash(raw_ids),
        "metadata_hash": metadata_hash(metadata),
        "edit_field": edit_field,
        "max_last_edited_date": _normalized_signal(max_edited),
    }


def _extract_parcel_metadata(raw: Any) -> Mapping[str, Any]:
    value = json.loads(raw or "{}")
    if not isinstance(value, Mapping):
        return {}
    manifest = value.get("manifest")
    if isinstance(manifest, Mapping):
        schema = manifest.get("schema_metadata")
        if isinstance(schema, Mapping) and isinstance(schema.get("layer_metadata"), Mapping):
            return cast(Mapping[str, Any], schema["layer_metadata"])
    source_context = value.get("source_context")
    if isinstance(source_context, Mapping) and isinstance(source_context.get("layer_metadata"), Mapping):
        return cast(Mapping[str, Any], source_context["layer_metadata"])
    return {}


def _local_edit_max(
    connection: sqlite3.Connection,
    *,
    table: str,
    snapshot_id: int,
    json_column: str,
    field: Optional[str],
    layer_id: Optional[int] = None,
) -> Any:
    if not field or '"' in field:
        return None
    path = f'$."{field}"'
    if layer_id is None:
        row = connection.execute(
            f"SELECT MAX(json_extract({json_column},?)) FROM {table} WHERE snapshot_id=?",
            (path, snapshot_id),
        ).fetchone()
    else:
        row = connection.execute(
            f"SELECT MAX(json_extract({json_column},?)) FROM {table} WHERE snapshot_id=? AND canonical_layer_id=?",
            (path, snapshot_id, layer_id),
        ).fetchone()
    return _normalized_signal(row[0]) if row and row[0] is not None else None


def _local_parcel_baseline(connection: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = connection.execute(
        "SELECT snapshot_id,source,metadata_json FROM snapshots WHERE state='active' ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    snapshot_id = int(row["snapshot_id"])
    metadata = _extract_parcel_metadata(row["metadata_json"])
    object_ids = [
        int(item[0])
        for item in connection.execute(
            "SELECT objectid FROM snapshot_inventory WHERE snapshot_id=? ORDER BY objectid", (snapshot_id,)
        )
    ]
    edit_field = _edit_field(metadata)
    return {
        "snapshot_id": snapshot_id,
        "source_url": row["source"] or LAYER13_URL,
        "record_count": len(object_ids),
        "inventory_hash": inventory_hash(object_ids),
        "metadata_hash": metadata_hash(metadata) if metadata else None,
        "edit_field": edit_field,
        "max_last_edited_date": _local_edit_max(
            connection,
            table="parcels",
            snapshot_id=snapshot_id,
            json_column="raw_attrs_json",
            field=edit_field,
        ),
    }


def _local_planning_baselines(connection: sqlite3.Connection) -> Tuple[Dict[str, Any], ...]:
    row = connection.execute(
        "SELECT snapshot_id FROM planning_snapshots WHERE state='active' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return ()
    snapshot_id = int(row[0])
    baselines = []
    for layer in connection.execute(
        "SELECT layer_id,canonical_layer_id,name,metadata_json FROM planning_layers "
        "WHERE snapshot_id=? ORDER BY canonical_layer_id",
        (snapshot_id,),
    ):
        metadata_value = json.loads(layer["metadata_json"] or "{}")
        source_context = metadata_value.get("source_context", {}) if isinstance(metadata_value, Mapping) else {}
        metadata = source_context.get("layer_metadata", {}) if isinstance(source_context, Mapping) else {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        canonical_id = int(layer["canonical_layer_id"])
        object_ids = [
            int(item[0])
            for item in connection.execute(
                "SELECT object_id FROM planning_layer_inventory WHERE snapshot_id=? "
                "AND canonical_layer_id=? ORDER BY object_id",
                (snapshot_id, canonical_id),
            )
        ]
        edit_field = _edit_field(metadata)
        configured_source_url = str(source_context.get("source_url") or "").rstrip("/")
        source_url = (
            configured_source_url
            if configured_source_url
            else f"{LAYER13_URL.rsplit('/', 1)[0]}/{int(layer['layer_id'])}"
        )
        baselines.append(
            {
                "snapshot_id": snapshot_id,
                "layer_id": int(layer["layer_id"]),
                "canonical_layer_id": canonical_id,
                "name": str(layer["name"]),
                "source_url": source_url,
                "record_count": len(object_ids),
                "inventory_hash": inventory_hash(object_ids),
                "metadata_hash": metadata_hash(metadata) if metadata else None,
                "edit_field": edit_field,
                "max_last_edited_date": _local_edit_max(
                    connection,
                    table="planning_features",
                    snapshot_id=snapshot_id,
                    json_column="attributes_json",
                    field=edit_field,
                    layer_id=canonical_id,
                ),
            }
        )
    return tuple(baselines)


def _compare(local: Mapping[str, Any], remote: Mapping[str, Any]) -> Dict[str, Any]:
    signals: Dict[str, str] = {}
    for key in ("record_count", "inventory_hash", "metadata_hash"):
        if local.get(key) is None or remote.get(key) is None:
            signals[key] = "unknown"
        else:
            signals[key] = "match" if local.get(key) == remote.get(key) else "changed"
    if local.get("max_last_edited_date") is None or remote.get("max_last_edited_date") is None:
        signals["max_last_edited_date"] = "unavailable"
    else:
        signals["max_last_edited_date"] = (
            "match"
            if _normalized_signal(local.get("max_last_edited_date"))
            == _normalized_signal(remote.get("max_last_edited_date"))
            else "changed"
        )
    decisive = ("record_count", "inventory_hash", "metadata_hash")
    if any(signals[key] == "changed" for key in (*decisive, "max_last_edited_date")):
        status = "changed"
    elif any(signals[key] == "unknown" for key in decisive):
        status = "unknown"
    else:
        status = "unchanged"
    return {
        "status": status,
        "refresh_required": status != "unchanged",
        "signals": signals,
        "local": dict(local),
        "upstream": dict(remote),
        "limitations": [
            "A matching ObjectID inventory cannot prove that coordinates or attributes under an existing ObjectID are unchanged.",
            *(
                ["No comparable edit timestamp was available; schedule a periodic full verification."]
                if signals["max_last_edited_date"] == "unavailable"
                else []
            ),
        ],
    }


async def check_database_upstream(client: Any, database: Path) -> Dict[str, Any]:
    """Compare local active snapshots with ArcGIS without downloading geometry."""
    path = Path(database).expanduser()
    if not path.is_file():
        raise UpstreamCheckError(f"database does not exist: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"snapshots", "snapshot_inventory", "parcels"}.issubset(tables):
            raise UpstreamCheckError("database does not contain parcel snapshot tables")
        parcel_local = _local_parcel_baseline(connection)
        planning_local = (
            _local_planning_baselines(connection)
            if {"planning_snapshots", "planning_layers", "planning_layer_inventory", "planning_features"}.issubset(
                tables
            )
            else ()
        )
    finally:
        connection.close()

    if parcel_local is None:
        parcels: Dict[str, Any] = {
            "status": "unknown",
            "refresh_required": True,
            "error": "no active parcel snapshot is available for comparison",
        }
    else:
        try:
            parcels = _compare(parcel_local, await _remote_layer_probe(client, str(parcel_local["source_url"])))
        except UpstreamCheckError as exc:
            parcels = {"status": "unknown", "refresh_required": True, "error": str(exc)}

    semaphore = asyncio.Semaphore(4)

    async def check_planning_layer(local: Mapping[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            try:
                result = _compare(local, await _remote_layer_probe(client, str(local["source_url"])))
            except UpstreamCheckError as exc:
                result = {"status": "unknown", "refresh_required": True, "error": str(exc)}
            return {
                "layer_id": local["layer_id"],
                "canonical_layer_id": local["canonical_layer_id"],
                "name": local["name"],
                **result,
            }

    planning_layers = list(await asyncio.gather(*(check_planning_layer(item) for item in planning_local)))
    expected_ids = {spec.layer_id for spec in canonical_planning_specs()}
    local_ids = {int(item["canonical_layer_id"]) for item in planning_local}
    missing_layers = sorted(expected_ids - local_ids)
    if not planning_local:
        planning_status = "unknown"
    elif any(item["status"] == "changed" for item in planning_layers) or missing_layers:
        planning_status = "changed"
    elif any(item["status"] == "unknown" for item in planning_layers):
        planning_status = "unknown"
    else:
        planning_status = "unchanged"
    planning = {
        "status": planning_status,
        "refresh_required": planning_status != "unchanged",
        "layer_count": len(planning_layers),
        "missing_canonical_layer_ids": missing_layers,
        "changed_layer_ids": [item["canonical_layer_id"] for item in planning_layers if item["status"] == "changed"],
        "unknown_layer_ids": [item["canonical_layer_id"] for item in planning_layers if item["status"] == "unknown"],
        "layers": planning_layers,
    }
    statuses = (str(parcels["status"]), planning_status)
    overall = "changed" if "changed" in statuses else ("unknown" if "unknown" in statuses else "unchanged")
    return {
        "checked_at": _utc_now(),
        "database": str(path),
        "overall_status": overall,
        "refresh_required": overall != "unchanged",
        "geometry_downloaded": False,
        "parcels": parcels,
        "planning": planning,
        "next_action": (
            "stage and verify a new snapshot; do not activate automatically"
            if overall != "unchanged"
            else "keep the active snapshots; no download is currently indicated"
        ),
    }


__all__ = [
    "UpstreamCheckError",
    "check_database_upstream",
    "inventory_hash",
    "metadata_contract",
    "metadata_hash",
]
