"""Pure source identity shared by intelligence builders and health readers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from dp_lookup.intelligence.models import ALGORITHM_VERSION


def source_fingerprint(
    parcel_snapshot_id: int,
    parcel_metadata: Mapping[str, Any],
    planning_snapshot_id: int,
    planning_hash: str,
    authority_revision: Optional[int],
    *,
    algorithm_version: str = ALGORITHM_VERSION,
) -> str:
    manifest = parcel_metadata.get("manifest_summary")
    parcel_hash = manifest.get("content_hash") if isinstance(manifest, Mapping) else None
    payload = {
        "parcel_snapshot_id": parcel_snapshot_id,
        "parcel_content_hash": parcel_hash,
        "planning_snapshot_id": planning_snapshot_id,
        "planning_content_hash": planning_hash,
        "authority_registry_revision": authority_revision or 0,
        "algorithm_version": algorithm_version,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
