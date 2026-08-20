"""Pure, immutable contracts for planning-evidence queries.

This package deliberately models *source evidence*, not planning-law advice.  A
polygon intersection is a useful screening signal, but it is not by itself a
legal conclusion about title, sanction, developability, or an applicable
setback.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

SPATIAL_OVERLAP_DISCLAIMER = (
    "A spatial overlap is a screening signal only; it is not a legal conclusion "
    "about title, sanction, developability, or an applicable planning rule."
)


class EvidenceClass(str, Enum):
    """The evidentiary role of a source layer in a due-diligence result."""

    STATUTORY = "statutory"
    REGULATORY = "regulatory"
    CONTEXTUAL = "contextual"


class QueryPolicy(str, Enum):
    """When a layer is eligible for a parcel query."""

    ALWAYS = "always"
    COASTAL = "coastal"
    TPS = "tps"
    SPA = "spa"
    GORAI = "gorai"


class EvidenceMode(str, Enum):
    """Runtime profile for the optional evidence capability."""

    BASIC = "basic"
    SHADOW = "shadow"
    STANDARD = "standard"
    FULL = "full"

    @classmethod
    def parse(cls, value: object) -> "EvidenceMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().casefold())
        except ValueError as exc:
            choices = ", ".join(mode.value for mode in cls)
            raise ValueError(f"evidence mode must be one of: {choices}") from exc


class QueryState(str, Enum):
    """Auditable outcome of one source-layer query."""

    HIT = "hit"
    NOT_PRESENT = "not_present"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"
    MALFORMED = "malformed"
    TRUNCATED = "truncated"


@dataclass(frozen=True)
class EvidenceContext:
    """Pure applicability flags supplied by the caller's parcel context.

    The flags are intentionally facts, not guesses made by this package.  For
    example, ``coastal=True`` should come from a prior coastal screen or an
    authoritative site context, not from a layer intersection performed here.
    """

    coastal: bool = False
    tps: bool = False
    spa: bool = False
    gorai: bool = False


@dataclass(frozen=True)
class LayerSpec:
    """Audited description of one ArcGIS feature layer.

    ``out_fields`` is always an explicit tuple.  The wildcard ``"*"`` is
    rejected because uncontrolled source schemas make evidence reports hard to
    audit and can silently change request cost and response shape.
    """

    layer_id: int
    name: str
    evidence_class: EvidenceClass
    query_policy: QueryPolicy
    out_fields: Tuple[str, ...]
    role: str
    geometry_type: str = "esriGeometryPolygon"
    object_id_field: str = "OBJECTID"
    canonical_id: Optional[int] = None
    audit_note: str = SPATIAL_OVERLAP_DISCLAIMER

    def __post_init__(self) -> None:
        if self.layer_id < 0:
            raise ValueError("layer_id must be zero or greater")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if not self.role.strip():
            raise ValueError("role must not be blank")
        if not self.audit_note.strip():
            raise ValueError("audit_note must not be blank")
        fields = tuple(str(field).strip() for field in self.out_fields)
        if not fields or any(not field for field in fields):
            raise ValueError("out_fields must contain at least one non-blank field")
        if "*" in fields:
            raise ValueError('out_fields must be explicit; "*" is not allowed')
        if len(set(fields)) != len(fields):
            raise ValueError("out_fields must not contain duplicates")
        object.__setattr__(self, "out_fields", fields)
        if not self.object_id_field.strip():
            raise ValueError("object_id_field must not be blank")
        if self.object_id_field not in fields:
            raise ValueError("out_fields must include object_id_field")
        if self.canonical_id == self.layer_id:
            object.__setattr__(self, "canonical_id", None)

    @property
    def canonical_layer_id(self) -> int:
        """Return the source ID that should be queried for this specification."""

        return self.canonical_id if self.canonical_id is not None else self.layer_id

    def is_applicable(self, context: EvidenceContext) -> bool:
        """Return whether this spec is eligible under a supplied context."""

        if self.query_policy is QueryPolicy.ALWAYS:
            return True
        return {
            QueryPolicy.COASTAL: context.coastal,
            QueryPolicy.TPS: context.tps,
            QueryPolicy.SPA: context.spa,
            QueryPolicy.GORAI: context.gorai,
        }[self.query_policy]


@dataclass(frozen=True)
class EvidenceFinding:
    """One exact parcel intersection with one official source feature."""

    layer_id: int
    layer_name: str
    object_id: Optional[int]
    evidence_class: EvidenceClass
    role: str
    overlap_sqm: float
    overlap_percent: float
    source_url: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    warnings: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(deepcopy(dict(self.attributes))))
        object.__setattr__(self, "warnings", tuple(str(warning) for warning in self.warnings))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "object_id": self.object_id,
            "evidence_class": self.evidence_class.value,
            "role": self.role,
            "overlap_sqm": self.overlap_sqm,
            "overlap_percent": self.overlap_percent,
            "source_url": self.source_url,
            "attributes": deepcopy(dict(self.attributes)),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class LayerQueryOutcome:
    """The complete audit record for one attempted or skipped layer."""

    layer_id: int
    layer_name: str
    state: QueryState
    duration_ms: float
    returned_features: int = 0
    findings: Sequence[EvidenceFinding] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "warnings", tuple(str(warning) for warning in self.warnings))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "state": self.state.value,
            "duration_ms": self.duration_ms,
            "returned_features": self.returned_features,
            "findings": [finding.to_dict() for finding in self.findings],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PlanningEvidenceReport:
    """Typed, independently complete result of the optional evidence pass."""

    mode: EvidenceMode
    retrieved_at: str
    complete: bool
    outcomes: Sequence[LayerQueryOutcome] = field(default_factory=tuple)
    summary: Mapping[str, Any] = field(default_factory=dict)
    warnings: Sequence[str] = field(default_factory=tuple)
    registry_version: int = 1
    disclaimer: str = SPATIAL_OVERLAP_DISCLAIMER
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        object.__setattr__(self, "summary", MappingProxyType(deepcopy(dict(self.summary))))
        object.__setattr__(self, "warnings", tuple(str(warning) for warning in self.warnings))
        object.__setattr__(self, "provenance", MappingProxyType(deepcopy(dict(self.provenance))))

    @property
    def findings(self) -> Tuple[EvidenceFinding, ...]:
        return tuple(finding for outcome in self.outcomes for finding in outcome.findings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "retrieved_at": self.retrieved_at,
            "complete": self.complete,
            "registry_version": self.registry_version,
            "summary": deepcopy(dict(self.summary)),
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "warnings": list(self.warnings),
            "disclaimer": self.disclaimer,
            "provenance": deepcopy(dict(self.provenance)),
        }
