"""In-memory sliding-window rate limiter. Deliberately NOT applied to the
redirect hot path (a printed QR must never be 429'd by us — that layer is
Caddy's job in production). Applied to credential + mutation endpoints that
bots hammer: login, signup, password changes, invites, bulk ops."""
import threading
import time
from collections import defaultdict, deque


class RateLimit:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: int) -> bool:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True
