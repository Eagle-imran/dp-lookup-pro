"""Contracts for audited, versioned planning-layer snapshots.

The models in this module are deliberately source shaped.  They do not turn a
GIS feature into a legal or planning conclusion; they record what a source
returned so that later consumers can make and explain those decisions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class PlanningFeature:
    """One raw feature, retaining attributes and geometry independently."""

    object_id: int
    attributes: Mapping[str, Any]
    geometry: Any
    raw_feature: Optional[Any] = None
    source_layer_id: Optional[int] = None

    def __post_init__(self) -> None:
        if isinstance(self.object_id, bool) or int(self.object_id) < 0:
            raise ValueError("object_id must be a non-negative integer")
        object.__setattr__(self, "object_id", int(self.object_id))
        if not isinstance(self.attributes, Mapping):
            raise ValueError("attributes must be a mapping")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "geometry": self.geometry,
        }


@dataclass(frozen=True)
class PlanningLayerSnapshot:
    snapshot_id: int
    layer_id: int
    canonical_layer_id: int
    name: str
    geometry_type: Optional[str]
    object_id_field: str
    expected_count: Optional[int]
    received_count: int
    content_hash: str
    complete: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "layer_id": self.layer_id,
            "canonical_layer_id": self.canonical_layer_id,
            "name": self.name,
            "geometry_type": self.geometry_type,
            "object_id_field": self.object_id_field,
            "expected_count": self.expected_count,
            "received_count": self.received_count,
            "content_hash": self.content_hash,
            "complete": self.complete,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlanningSnapshot:
    snapshot_id: int
    version: int
    state: str
    source_url: Optional[str]
    created_at: str
    finalized_at: Optional[str]
    content_hash: str
    complete: bool
    layers: Tuple[PlanningLayerSnapshot, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "state": self.state,
            "source_url": self.source_url,
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
            "content_hash": self.content_hash,
            "complete": self.complete,
            "layers": [layer.to_dict() for layer in self.layers],
            "metadata": dict(self.metadata),
        }


class PlanningSnapshotError(RuntimeError):
    """Base class for explicit planning snapshot failures."""


class PlanningSnapshotStateError(PlanningSnapshotError):
    pass


class PlanningSnapshotValidationError(PlanningSnapshotError):
    pass


__all__ = [
    "PlanningFeature",
    "PlanningLayerSnapshot",
    "PlanningSnapshot",
    "PlanningSnapshotError",
    "PlanningSnapshotStateError",
    "PlanningSnapshotValidationError",
    "canonical_json",
    "sha256_json",
    "utc_now",
]
