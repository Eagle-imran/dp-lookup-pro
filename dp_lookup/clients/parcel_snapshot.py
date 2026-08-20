"""Contracts and small helpers for immutable Layer 13 snapshots.

This module deliberately does not know how a snapshot is stored.  The ingestion
application returns these records to a caller which may write SQLite, an
archive, or both.  Keeping the source record intact is important: a normalized
parcel is useful, but it must always be possible to audit what MCGM returned.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from dp_lookup.core.constants import SERVER_URL

LAYER13_ID = 13
LAYER13_URL = f"{SERVER_URL}/{LAYER13_ID}"
DEFAULT_OUT_SR = 102100


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    """Encode JSON deterministically for manifests and content hashes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class SnapshotIngestionError(RuntimeError):
    """The source could not provide a safe inventory or a valid response."""


@dataclass(frozen=True)
class SnapshotFeature:
    """One accepted source feature, retaining the exact ArcGIS JSON members."""

    object_id: int
    attributes: Mapping[str, Any]
    geometry: Mapping[str, Any]
    raw_feature: Mapping[str, Any]


@dataclass(frozen=True)
class SnapshotCheckpoint:
    """Serializable progress contract for resuming a partially fetched run."""

    expected_ids: Tuple[int, ...]
    completed_ids: Tuple[int, ...] = ()
    rejected_ids: Tuple[int, ...] = ()
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_ids", tuple(sorted(set(int(i) for i in self.expected_ids))))
        object.__setattr__(self, "completed_ids", tuple(sorted(set(int(i) for i in self.completed_ids))))
        object.__setattr__(self, "rejected_ids", tuple(sorted(set(int(i) for i in self.rejected_ids))))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_ids": list(self.expected_ids),
            "completed_ids": list(self.completed_ids),
            "rejected_ids": list(self.rejected_ids),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SnapshotManifest:
    """Evidence and completeness information for an ingestion run."""

    source_url: str
    layer_id: int
    object_id_field: str
    requested_out_sr: int
    source_spatial_reference: Optional[Mapping[str, Any]]
    expected_ids: Tuple[int, ...]
    received_ids: Tuple[int, ...]
    missing_ids: Tuple[int, ...]
    duplicate_ids: Tuple[int, ...]
    rejected_ids: Tuple[int, ...]
    extra_ids: Tuple[int, ...] = ()
    invalid_feature_count: int = 0
    batch_errors: Tuple[str, ...] = ()
    schema_metadata: Mapping[str, Any] = field(default_factory=dict)
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=utc_now)
    content_hash: str = ""

    @property
    def complete(self) -> bool:
        """A snapshot is complete only when every inventory ID was received."""
        return not self.missing_ids and not self.rejected_ids and not self.batch_errors and not self.extra_ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_url": self.source_url,
            "layer_id": self.layer_id,
            "object_id_field": self.object_id_field,
            "requested_out_sr": self.requested_out_sr,
            "source_spatial_reference": self.source_spatial_reference,
            "expected_ids": list(self.expected_ids),
            "received_ids": list(self.received_ids),
            "missing_ids": list(self.missing_ids),
            "duplicate_ids": list(self.duplicate_ids),
            "rejected_ids": list(self.rejected_ids),
            "extra_ids": list(self.extra_ids),
            "invalid_feature_count": self.invalid_feature_count,
            "batch_errors": list(self.batch_errors),
            "schema_metadata": dict(self.schema_metadata),
            "source_metadata": dict(self.source_metadata),
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
            "complete": self.complete,
        }


@dataclass(frozen=True)
class SnapshotIngestionResult:
    """Accepted records plus a manifest and resume checkpoint."""

    features: Tuple[SnapshotFeature, ...]
    manifest: SnapshotManifest
    checkpoint: SnapshotCheckpoint

    @property
    def complete(self) -> bool:
        return self.manifest.complete


def resolve_object_id_field(metadata: Mapping[str, Any], fallback: str = "OBJECTID") -> str:
    """Resolve the OID despite MCGM currently reporting a null objectIdField.

    ArcGIS layer metadata may have ``objectIdField: null`` while the fields list
    correctly marks OBJECTID as ``esriFieldTypeOID``.  The field list therefore
    takes precedence over the advertised property.
    """
    fields = metadata.get("fields")
    if isinstance(fields, list):
        for field_item in fields:
            if isinstance(field_item, Mapping) and field_item.get("type") == "esriFieldTypeOID":
                name = field_item.get("name")
                if isinstance(name, str) and name.strip():
                    return name
    advertised = metadata.get("objectIdField")
    if isinstance(advertised, str) and advertised.strip():
        return advertised
    if isinstance(fields, list):
        for field_item in fields:
            if isinstance(field_item, Mapping) and str(field_item.get("name", "")).upper() in {"OBJECTID", "OID"}:
                return str(field_item["name"])
    return fallback


__all__ = [
    "DEFAULT_OUT_SR",
    "LAYER13_ID",
    "LAYER13_URL",
    "SnapshotCheckpoint",
    "SnapshotFeature",
    "SnapshotIngestionError",
    "SnapshotIngestionResult",
    "SnapshotManifest",
    "canonical_json",
    "resolve_object_id_field",
    "sha256_json",
]
