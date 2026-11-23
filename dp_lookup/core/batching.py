"""Fixed-size batching for ingestion loops."""

from collections.abc import Iterator, Sequence
from typing import TypeVar

T = TypeVar("T")


def batched(values: Sequence[T], size: int) -> Iterator[tuple[T, ...]]:
    """Yield consecutive tuples of at most ``size`` items, like ``itertools.batched`` on 3.12."""
    if size < 1:
        raise ValueError("batch size must be at least 1")
    for offset in range(0, len(values), size):
        yield tuple(values[offset : offset + size])
