"""Versioned authority-source selection for parcel evidence."""

from .models import AuthorityManifest, AuthorityRecord, SelectionPurpose, SourceStatus, SourceType
from .selection import (
    AUTHORITY_POLICY_VERSION,
    AuthorityCandidate,
    AuthorityResolution,
    recommend_authority,
    recommend_authority_sources,
    source_type_label,
)
from .store import (
    AUTHORITY_SCHEMA_VERSION,
    AuthorityStateError,
    AuthorityStore,
    AuthorityStoreError,
    AuthorityValidationError,
)

__all__ = [
    "AUTHORITY_POLICY_VERSION",
    "AUTHORITY_SCHEMA_VERSION",
    "AuthorityCandidate",
    "AuthorityManifest",
    "AuthorityRecord",
    "AuthorityResolution",
    "AuthorityStateError",
    "AuthorityStore",
    "AuthorityStoreError",
    "AuthorityValidationError",
    "SelectionPurpose",
    "SourceStatus",
    "SourceType",
    "recommend_authority",
    "recommend_authority_sources",
    "source_type_label",
]
