from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitSnapshot:
    state: CircuitState
    failures: int
    opened_at: float | None


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 30):
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def allow_request(self) -> bool:
        async with self._lock:
            if self._state is CircuitState.CLOSED:
                return True
            if self._state is CircuitState.OPEN and self._opened_at is not None:
                if time.monotonic() - self._opened_at >= self.recovery_seconds:
                    self._state = CircuitState.HALF_OPEN
                    return True
            return self._state is CircuitState.HALF_OPEN

    async def record_success(self) -> None:
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._state is CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    def snapshot(self) -> CircuitSnapshot:
        return CircuitSnapshot(self._state, self._failures, self._opened_at)
