"""Small, dependency-free run diagnostics for CLI and automation consumers."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, Iterator, TypeVar

T = TypeVar("T")


def _json_logging_enabled() -> bool:
    return os.getenv("DP_LOOKUP_LOG_JSON", "").strip().casefold() in {"1", "true", "yes", "on"}


@dataclass
class RunDiagnostics:
    """Collect stage timings and optionally emit one JSON event per stage."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _started: float = field(default_factory=time.perf_counter, init=False, repr=False)
    _last_mark: float = field(default_factory=time.perf_counter, init=False, repr=False)
    stages_ms: Dict[str, float] = field(default_factory=dict)
    spans_ms: Dict[str, float] = field(default_factory=dict)

    def mark(self, stage: str, **details: Any) -> None:
        now = time.perf_counter()
        duration_ms = round((now - self._last_mark) * 1000, 1)
        self._last_mark = now
        self.stages_ms[stage] = duration_ms
        if _json_logging_enabled():
            event = {
                "event": "dp_lookup.stage_completed",
                "run_id": self.run_id,
                "stage": stage,
                "duration_ms": duration_ms,
                **details,
            }
            print(json.dumps(event, sort_keys=True, default=str), file=sys.stderr)

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        """Measure one nested operation without changing stage boundaries."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record_span(name, started)

    def record_span(self, name: str, started: float) -> None:
        """Record elapsed time from a caller-owned monotonic start value."""
        self.spans_ms[name] = round((time.perf_counter() - started) * 1000, 1)

    async def wait(self, name: str, operation: Awaitable[T]) -> T:
        """Measure one async adapter operation without shifting stage marks."""
        started = time.perf_counter()
        try:
            return await operation
        finally:
            self.record_span(name, started)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "elapsed_ms": round((time.perf_counter() - self._started) * 1000, 1),
            "stages_ms": dict(self.stages_ms),
            "spans_ms": dict(self.spans_ms),
        }
