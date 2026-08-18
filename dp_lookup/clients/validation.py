"""Validation at external-input boundaries."""

import re
from typing import Any


def sanitize_query_value(value: Any, pattern: "re.Pattern[str]", label: str, max_len: int = 64) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if len(text) > max_len:
        raise ValueError(f"{label} is too long (max {max_len} characters)")
    if not pattern.match(text):
        raise ValueError(f"{label} contains unsupported characters. Allowed: letters, digits, space, and ( ) . / -")
    return text
