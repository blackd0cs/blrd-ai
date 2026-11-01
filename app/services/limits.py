from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Простой скользящий лимит в памяти процесса. Для одного инстанса достаточно."""

    def __init__(self, per_minute: int = 20) -> None:
        self.per_minute = per_minute
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, key: int, per_minute: int | None = None) -> bool:
        limit = per_minute or self.per_minute
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def retry_after(self, key: int) -> int:
        q = self._hits.get(key)
        if not q:
            return 0
        return max(1, int(60 - (time.monotonic() - q[0])))


limiter = RateLimiter()
busy_users: set[int] = set()  # кто уже генерирует: второй параллельный запрос отклоняем
