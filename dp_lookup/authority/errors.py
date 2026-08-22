"""Explicit error vocabulary for the authority registry."""


class AuthorityStoreError(RuntimeError):
    """Base error for authority registry failures."""


class AuthorityValidationError(AuthorityStoreError, ValueError):
    """An authority manifest or lifecycle operation is invalid."""


class AuthorityStateError(AuthorityStoreError):
    """An operation conflicts with immutable evidence lifecycle rules."""


__all__ = ["AuthorityStateError", "AuthorityStoreError", "AuthorityValidationError"]
