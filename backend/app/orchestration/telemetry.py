"""Dependency-free request stage telemetry for Ask Kriton."""
from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")
_current_metrics: ContextVar["StageMetrics | None"] = ContextVar("kriton_stage_metrics", default=None)


class StageMetrics:
    """Collect elapsed time and failures without changing pipeline semantics."""

    def __init__(self) -> None:
        self._observations: dict[str, dict[str, Any]] = {}
        _current_metrics.set(self)

    async def run(self, stage: str, operation: Awaitable[T]) -> T:
        started = time.monotonic()
        try:
            result = await operation
        except BaseException as exc:
            self.record(stage, started, error=exc)
            raise
        self.record(stage, started)
        return result

    def run_sync(self, stage: str, operation: Callable[[], T]) -> T:
        started = time.monotonic()
        try:
            result = operation()
        except BaseException as exc:
            self.record(stage, started, error=exc)
            raise
        self.record(stage, started)
        return result

    def record(self, stage: str, started: float, *, error: BaseException | None = None) -> None:
        observation: dict[str, Any] = {
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "status": "error" if error else "ok",
        }
        if error:
            observation["error_type"] = type(error).__name__
        self._observations[stage] = observation
        logger.info(
            "kriton_stage stage=%s duration_ms=%s status=%s error_type=%s",
            stage, observation["duration_ms"], observation["status"],
            observation.get("error_type", ""),
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: values.copy() for name, values in self._observations.items()}


def current_stage_metrics() -> StageMetrics | None:
    return _current_metrics.get()
