"""Скользящее окно для ручек, уязвимых к перебору (вход, регистрация, публичные ссылки).

Лимитер живёт в памяти процесса намеренно: это первая линия защиты от
credential stuffing, а не биллинговая квота. Интерфейс позволяет позже подменить
хранилище на общее, не трогая вызывающий код.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass
class RateDecision:
    allowed: bool
    retry_after_s: int = 0


class SlidingWindowRateLimiter:
    def __init__(self, *, max_attempts: int, window_s: float, max_keys: int = 50_000):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self.max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}

    def check(self, key: str) -> RateDecision:
        """Зафиксировать попытку для ``key`` и решить, разрешена ли она."""
        now = monotonic()
        bucket = self._attempts.get(key)
        if bucket is None:
            self._evict_if_needed()
            bucket = deque()
            self._attempts[key] = bucket
        decision = self._decide(bucket, now)
        if decision.allowed:
            bucket.append(now)
        return decision

    def peek(self, key: str) -> RateDecision:
        """Решить, не исчерпан ли лимит для ``key``, не засчитывая попытку.

        Нужен там, где считаются только неудачи: сначала смотрим, не заблокирован
        ли ключ, а ``check`` вызываем лишь после провала.
        """
        bucket = self._attempts.get(key)
        if bucket is None:
            return RateDecision(allowed=True)
        return self._decide(bucket, monotonic())

    def _decide(self, bucket: deque[float], now: float) -> RateDecision:
        while bucket and now - bucket[0] > self.window_s:
            bucket.popleft()
        if len(bucket) >= self.max_attempts:
            retry_after = int(self.window_s - (now - bucket[0])) + 1
            return RateDecision(allowed=False, retry_after_s=max(retry_after, 1))
        return RateDecision(allowed=True)

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)

    def clear(self) -> None:
        self._attempts.clear()

    def _evict_if_needed(self) -> None:
        # Защита памяти от спрея ключей: при переполнении выбрасываем старшую половину.
        if len(self._attempts) < self.max_keys:
            return
        by_recency = sorted(
            self._attempts.items(), key=lambda item: item[1][-1] if item[1] else 0.0
        )
        for key, _ in by_recency[: len(by_recency) // 2]:
            self._attempts.pop(key, None)
