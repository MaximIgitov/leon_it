"""Circuit breaker для внешних провайдеров.

Когда провайдер лежит, каждый запрос к нему — это таймаут в десятки секунд и
занятый слот воркера. Автомат ``closed → open → half-open`` после серии отказов
отвечает мгновенно (fail-fast), а по истечении паузы пропускает один пробный
запрос: успех закрывает контур, отказ снова открывает.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Literal

BreakerState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        half_open_max_calls: int = 1,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.half_open_max_calls = half_open_max_calls
        self._clock = clock
        self._state: BreakerState = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> BreakerState:
        if self._state == "open" and self._clock() - self._opened_at >= self.recovery_timeout_s:
            self._state = "half_open"
            self._half_open_calls = 0
        return self._state

    @property
    def failures(self) -> int:
        return self._failures

    def allow(self) -> bool:
        """Можно ли сейчас делать запрос."""
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and self._half_open_calls < self.half_open_max_calls:
            self._half_open_calls += 1
            return True
        return False

    def record_success(self) -> None:
        self._state = "closed"
        self._failures = 0
        self._half_open_calls = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == "half_open" or self._failures >= self.failure_threshold:
            self._trip()

    def reset(self) -> None:
        self.record_success()

    def _trip(self) -> None:
        self._state = "open"
        self._opened_at = self._clock()
        self._half_open_calls = 0
