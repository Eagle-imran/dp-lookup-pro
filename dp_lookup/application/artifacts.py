"""Failure-isolated execution helpers for optional output artifacts."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional, TypeVar

T = TypeVar("T")


def run_artifact(
    label: str,
    warnings: List[str],
    writer: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> bool:
    """Run one artifact writer and turn its failure into a visible warning."""
    try:
        writer(*args, **kwargs)
        return True
    except Exception as exc:
        warnings.append(f"{label} generation failed: {type(exc).__name__}: {exc}")
        return False


def run_artifact_result(
    label: str,
    warnings: List[str],
    writer: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> Optional[T]:
    """Run one artifact writer while retaining its typed success value."""
    try:
        return writer(*args, **kwargs)
    except Exception as exc:
        warnings.append(f"{label} generation failed: {type(exc).__name__}: {exc}")
        return None


async def run_artifact_in_thread(
    label: str,
    warnings: List[str],
    writer: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> bool:
    """Thread offload variant for CPU-heavy PDF/image writers."""
    try:
        await asyncio.to_thread(writer, *args, **kwargs)
        return True
    except Exception as exc:
        warnings.append(f"{label} generation failed: {type(exc).__name__}: {exc}")
        return False
