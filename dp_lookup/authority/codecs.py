"""Immutable authority-manifest, geometry, and SQLite row codecs."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlparse

from dp_lookup.authority.errors import AuthorityStoreError, AuthorityValidationError
from dp_lookup.authority.models import AuthorityManifest, AuthorityRecord, SourceStatus, SourceType, canonical_json
from dp_lookup.core.area_assessment import calculated_boundary_area_sqm
from dp_lookup.core.constants import WEB_MERCATOR_R
from dp_lookup.core.topology import arcgis_rings_to_geometry


def canonical(value: Any) -> str:
    return canonical_json(value)


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise AuthorityStoreError("authority database contains invalid JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def document_path(uri: str, manifest_dir: Optional[Path | str]) -> Optional[Path]:
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    path = Path(uri)
    return Path(manifest_dir) / path if not path.is_absolute() and manifest_dir is not None else path


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalised_identity(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise AuthorityValidationError("village and cts_no are required")
    return text


def sha256_value(value: str, field: str) -> str:
    result = str(value or "").strip().casefold()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise AuthorityValidationError(f"{field} must be a SHA-256 hexadecimal digest")
    return result


def positive_area(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AuthorityValidationError("recorded_area_sqm must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AuthorityValidationError("recorded_area_sqm must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise AuthorityValidationError("recorded_area_sqm must be positive and finite")
    return number


def crs_wkid(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        value = value.get("wkid", value.get("latestWkid"))
    text = str(value).strip().upper()
    if text.startswith("EPSG:"):
        text = text[5:]
    try:
        wkid = int(text)
    except (TypeError, ValueError) as exc:
        raise AuthorityValidationError("original_crs must be an EPSG/WKID integer") from exc
    if wkid not in {3857, 102100, 4326}:
        raise AuthorityValidationError("original_crs must be EPSG:3857/102100 or EPSG:4326")
    return wkid


def extract_rings(geometry: Any) -> Optional[List[List[List[float]]]]:
    if geometry is None:
        return None
    value = geometry
    if isinstance(value, Mapping):
        if "rings" in value:
            value = value["rings"]
        elif value.get("type") == "Polygon":
            value = value.get("coordinates")
        elif value.get("type") == "MultiPolygon":
            polygons = value.get("coordinates")
            if isinstance(polygons, list):
                value = [ring for polygon in polygons for ring in polygon]
    if not isinstance(value, list) or not value:
        raise AuthorityValidationError("original_geometry must contain polygon rings")
    result: List[List[List[float]]] = []
    for ring in value:
        if not isinstance(ring, list) or len(ring) < 4:
            raise AuthorityValidationError("each geometry ring must contain at least four points")
        normalized_ring: List[List[float]] = []
        for point in ring:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise AuthorityValidationError("geometry points must contain x and y")
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError) as exc:
                raise AuthorityValidationError("geometry coordinates must be numeric") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise AuthorityValidationError("geometry coordinates must be finite")
            normalized_ring.append([x, y])
        result.append(normalized_ring)
    return result


def normalise_geometry(
    geometry: Any, crs: Optional[int]
) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[float]]:
    rings = extract_rings(geometry)
    if rings is None:
        if crs is not None:
            raise AuthorityValidationError("original_crs cannot be supplied without geometry")
        return None, None, None, None
    if crs is None:
        raise AuthorityValidationError("original_crs is required when original_geometry is supplied")
    if crs == 4326:
        normalized = [[_wgs84_to_mercator(point[0], point[1]) for point in ring] for ring in rings]
    else:
        normalized = rings
    normalized_json = json_value(normalized)
    geometry_hash = sha256_text(normalized_json)
    try:
        topology = arcgis_rings_to_geometry(normalized)
    except (IndexError, TypeError, ValueError) as exc:
        raise AuthorityValidationError(f"geometry could not be interpreted: {exc}") from exc
    calculated = calculated_boundary_area_sqm(normalized)
    if topology.is_empty or calculated is None:
        raise AuthorityValidationError("geometry must have a positive calculated area")
    return normalized_json, 3857, geometry_hash, calculated


def _wgs84_to_mercator(lon: float, lat: float) -> List[float]:
    safe_lat = max(-85.05112878, min(85.05112878, lat))
    return [
        WEB_MERCATOR_R * math.radians(lon),
        WEB_MERCATOR_R * math.log(math.tan(math.pi / 4.0 + math.radians(safe_lat) / 2.0)),
    ]


def manifest_payload(
    manifest: AuthorityManifest,
    version: int,
    normalized_json: Optional[str],
    geometry_hash: Optional[str],
    calculated: Optional[float],
) -> Dict[str, Any]:
    return {
        "village": manifest.village,
        "cts_no": manifest.cts_no,
        "ward": manifest.ward,
        "source_type": manifest.source_type.value,
        "issuer": manifest.issuer,
        "reference_no": manifest.reference_no,
        "issue_date": manifest.issue_date,
        "survey_date": manifest.survey_date,
        "source_uri": manifest.source_uri,
        "source_sha256": manifest.source_sha256,
        "mime_type": manifest.mime_type,
        "byte_size": manifest.byte_size,
        "recorded_area_sqm": manifest.recorded_area_sqm,
        "original_geometry": manifest.original_geometry,
        "original_crs": manifest.original_crs,
        "normalized_rings_json": normalized_json,
        "geometry_sha256": geometry_hash,
        "calculated_area_sqm": calculated,
        "supersedes_id": manifest.supersedes_id,
        "metadata": dict(manifest.metadata),
    }


def record_from_row(row: Any) -> AuthorityRecord:
    return AuthorityRecord(
        record_id=int(row["record_id"]),
        village=str(row["village"]),
        cts_no=str(row["cts_no"]),
        ward=row["ward"],
        source_type=SourceType(row["source_type"]),
        status=SourceStatus(row["status"]),
        version=int(row["version"]),
        issuer=row["issuer"],
        reference_no=row["reference_no"],
        issue_date=row["issue_date"],
        survey_date=row["survey_date"],
        source_uri=str(row["source_uri"]),
        source_sha256=str(row["source_sha256"]),
        mime_type=row["mime_type"],
        byte_size=int(row["byte_size"]) if row["byte_size"] is not None else None,
        recorded_area_sqm=float(row["recorded_area_sqm"]) if row["recorded_area_sqm"] is not None else None,
        original_geometry=loads(row["original_geometry_json"], None),
        original_crs=int(row["original_crs"]) if row["original_crs"] is not None else None,
        normalized_epsg3857_rings=loads(row["normalized_rings_json"], []),
        geometry_sha256=row["geometry_sha256"],
        calculated_area_sqm=float(row["calculated_area_sqm"]) if row["calculated_area_sqm"] is not None else None,
        supersedes_id=int(row["supersedes_id"]) if row["supersedes_id"] is not None else None,
        metadata=loads(row["metadata_json"], {}),
        created_by=row["created_by"],
        reviewed_by=row["reviewed_by"],
        created_at=str(row["created_at"]),
        reviewed_at=row["reviewed_at"],
        updated_at=str(row["updated_at"]),
        record_checksum=str(row["record_checksum"]),
    )


__all__ = [
    "canonical",
    "crs_wkid",
    "digest",
    "document_path",
    "file_sha256",
    "json_value",
    "loads",
    "manifest_payload",
    "normalise_geometry",
    "normalised_identity",
    "positive_area",
    "record_from_row",
    "sha256_value",
]
