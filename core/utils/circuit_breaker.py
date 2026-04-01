from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

from loguru import logger

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when the circuit is open and calls are blocked."""


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    half_open_max_calls: int = 1
    name: str = "circuit"

    state: str = field(default="CLOSED", init=False)
    failure_count: int = field(default=0, init=False)
    opened_at: float | None = field(default=None, init=False)
    half_open_calls: int = field(default=0, init=False)

    def _transition_to_open(self) -> None:
        self.state = "OPEN"
        self.opened_at = time.time()
        self.half_open_calls = 0
        logger.warning("{} breaker OPEN", self.name)

    def _transition_to_half_open(self) -> None:
        self.state = "HALF_OPEN"
        self.half_open_calls = 0
        logger.info("{} breaker HALF_OPEN", self.name)

    def _transition_to_closed(self) -> None:
        self.state = "CLOSED"
        self.failure_count = 0
        self.opened_at = None
        self.half_open_calls = 0
        logger.info("{} breaker CLOSED", self.name)

    def _can_attempt(self) -> bool:
        if self.state == "OPEN":
            assert self.opened_at is not None
            if (time.time() - self.opened_at) >= self.recovery_timeout_s:
                self._transition_to_half_open()
                return True
            return False
        if self.state == "HALF_OPEN":
            return self.half_open_calls < self.half_open_max_calls
        return True

    def _record_success(self) -> None:
        if self.state in {"OPEN", "HALF_OPEN"}:
            self._transition_to_closed()
        else:
            self.failure_count = 0

    def _record_failure(self) -> None:
        self.failure_count += 1
        if self.state == "HALF_OPEN" or self.failure_count >= self.failure_threshold:
            self._transition_to_open()

    async def call_async(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        timeout_s: float = 5.0,
        max_attempts: int = 3,
        backoff_base_s: float = 0.5,
    ) -> T:
        if not self._can_attempt():
            raise CircuitOpenError(f"{self.name} breaker open")

        attempt = 0
        last_exc: Exception | None = None

        while attempt < max_attempts:
            attempt += 1
            if self.state == "HALF_OPEN":
                self.half_open_calls += 1
            try:
                result = await asyncio.wait_for(fn(), timeout=timeout_s)
            except asyncio.TimeoutError as exc:
                last_exc = exc
                self._record_failure()
                logger.warning(
                    "{} timeout attempt {}/{} (timeout_s={})",
                    self.name,
                    attempt,
                    max_attempts,
                    timeout_s,
                )
            except Exception as exc:  # pragma: no cover - runtime safety
                last_exc = exc
                self._record_failure()
                logger.warning(
                    "{} transient error attempt {}/{}: {}",
                    self.name,
                    attempt,
                    max_attempts,
                    (str(exc) or "")[:200],
                )
            else:
                # success
                self._record_success()
                return result

            if attempt >= max_attempts:
                break
            delay = min(timeout_s, backoff_base_s * (2 ** (attempt - 1)))
            await asyncio.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError(f"{self.name} breaker failed without exception")


__all__ = ["CircuitBreaker", "CircuitOpenError"]
