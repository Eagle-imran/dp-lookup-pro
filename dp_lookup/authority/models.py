"""Typed contracts for manually supplied and certified parcel evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


class SourceType(str, Enum):
    PROPERTY_CARD = "property_card"
    CTS_FINAL_PLOT_PLAN = "cts_final_plot_plan"
    CITY_SURVEY_MEASUREMENT = "city_survey_measurement"
    TOTAL_STATION_SURVEY = "total_station_survey"
    DP_REMARKS = "dp_remarks"
    CERTIFIED_SURVEY_RECONCILIATION = "certified_survey_reconciliation"
    OTHER_OFFICIAL_DOCUMENT = "other_official_document"

    @classmethod
    def parse(cls, value: object) -> SourceType:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "propertycard": "property_card",
            "cts_fp": "cts_final_plot_plan",
            "cts_fp_plan": "cts_final_plot_plan",
            "final_plot_plan": "cts_final_plot_plan",
            "city_survey": "city_survey_measurement",
            "city_survey_record": "city_survey_measurement",
            "total_station": "total_station_survey",
            "dp_remarks_plan": "dp_remarks",
            "survey_reconciliation": "certified_survey_reconciliation",
        }
        normalized = aliases.get(normalized, normalized)
        try:
            return cls(normalized)
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            raise ValueError(f"source_type must be one of: {choices}") from exc


class SourceStatus(str, Enum):
    REGISTERED = "registered"
    VERIFIED = "verified"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"


class SelectionPurpose(str, Enum):
    AREA = "area"
    GEOMETRY = "geometry"
    PLANNING = "planning"

    @classmethod
    def parse(cls, value: object) -> SelectionPurpose:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().casefold())
        except ValueError as exc:
            raise ValueError("purpose must be area, geometry, or planning") from exc


def _mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _rings(value: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    if value is None:
        return ()
    return tuple(tuple((float(point[0]), float(point[1])) for point in ring) for ring in value)


@dataclass(frozen=True)
class AuthorityManifest:
    """Input to :meth:`AuthorityStore.register`.

    The manifest is intentionally independent of any PDF/OCR package.  A
    caller supplies the original source URI and checksum, with optional raw
    geometry and the officially recorded area.
    """

    village: str
    cts_no: str
    source_type: SourceType
    source_uri: str
    source_sha256: str
    issuer: str | None = None
    reference_no: str | None = None
    issue_date: str | None = None
    survey_date: str | None = None
    mime_type: str | None = None
    byte_size: int | None = None
    ward: str | None = None
    recorded_area_sqm: float | None = None
    original_geometry: Any = None
    original_crs: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    version: int | None = None
    supersedes_id: int | None = None
    created_by: str | None = None
    record_checksum: str | None = None

    def __post_init__(self) -> None:
        village = str(self.village).strip().upper()
        cts_no = str(self.cts_no).strip().upper()
        if not village or not cts_no:
            raise ValueError("village and cts_no are required")
        if not str(self.source_uri).strip():
            raise ValueError("source_uri is required")
        if not str(self.source_sha256).strip():
            raise ValueError("source_sha256 is required")
        object.__setattr__(self, "village", village)
        object.__setattr__(self, "cts_no", cts_no)
        object.__setattr__(self, "source_type", SourceType.parse(self.source_type))
        object.__setattr__(self, "metadata", _mapping(self.metadata))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AuthorityManifest:
        """Build a manifest from a JSON-shaped mapping with friendly aliases."""
        data = dict(value)
        aliases = {
            "uri": "source_uri",
            "url": "source_uri",
            "document_uri": "source_uri",
            "file": "source_uri",
            "file_path": "source_uri",
            "sha256": "source_sha256",
            "checksum": "source_sha256",
            "document_sha256": "source_sha256",
            "type": "source_type",
            "geometry": "original_geometry",
            "crs": "original_crs",
            "cts": "cts_no",
            "authority": "issuer",
            "issuing_authority": "issuer",
            "reference": "reference_no",
            "document_reference": "reference_no",
            "ref": "reference_no",
            "date": "issue_date",
            "issued_at": "issue_date",
            "surveyed_at": "survey_date",
            "content_type": "mime_type",
            "size": "byte_size",
            "file_size": "byte_size",
        }
        for old, new in aliases.items():
            if new not in data and old in data:
                data[new] = data[old]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass(frozen=True)
class AuthorityRecord:
    """An immutable source payload plus its lifecycle metadata."""

    record_id: int
    village: str
    cts_no: str
    source_type: SourceType
    status: SourceStatus
    version: int
    issuer: str | None
    reference_no: str | None
    issue_date: str | None
    survey_date: str | None
    source_uri: str
    source_sha256: str
    mime_type: str | None
    byte_size: int | None
    ward: str | None
    recorded_area_sqm: float | None
    original_geometry: Any
    original_crs: int | None
    normalized_epsg3857_rings: tuple[tuple[tuple[float, float], ...], ...]
    geometry_sha256: str | None
    calculated_area_sqm: float | None
    supersedes_id: int | None
    metadata: Mapping[str, Any]
    created_by: str | None
    reviewed_by: str | None
    created_at: str
    reviewed_at: str | None
    updated_at: str
    record_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType.parse(self.source_type))
        object.__setattr__(self, "status", SourceStatus(self.status))
        object.__setattr__(self, "metadata", _mapping(self.metadata))
        object.__setattr__(self, "normalized_epsg3857_rings", _rings(self.normalized_epsg3857_rings))

    @property
    def has_geometry(self) -> bool:
        return bool(self.normalized_epsg3857_rings) and self.calculated_area_sqm is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "village": self.village,
            "cts_no": self.cts_no,
            "ward": self.ward,
            "source_type": self.source_type.value,
            "status": self.status.value,
            "version": self.version,
            "issuer": self.issuer,
            "reference_no": self.reference_no,
            "issue_date": self.issue_date,
            "survey_date": self.survey_date,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "recorded_area_sqm": self.recorded_area_sqm,
            "original_geometry": self.original_geometry,
            "original_crs": self.original_crs,
            "normalized_epsg3857_rings": [[[x, y] for x, y in ring] for ring in self.normalized_epsg3857_rings],
            "geometry_sha256": self.geometry_sha256,
            "calculated_area_sqm": self.calculated_area_sqm,
            "supersedes_id": self.supersedes_id,
            "metadata": dict(self.metadata),
            "created_by": self.created_by,
            "reviewed_by": self.reviewed_by,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "updated_at": self.updated_at,
            "record_checksum": self.record_checksum,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


__all__ = [
    "AuthorityManifest",
    "AuthorityRecord",
    "SelectionPurpose",
    "SourceStatus",
    "SourceType",
    "canonical_json",
]
