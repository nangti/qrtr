"""Async scan pipeline (design doc: logging must never delay or break the
redirect). Redirect handlers enqueue a plain dict; worker threads do quota
checks + insert. If the queue bursts past capacity, we drop logs — redirects
are unaffected. Quota state is cached 60s per user so the hot path never waits
on COUNT queries (soft-decay: over-quota users keep redirecting; only logging
pauses — docs/MULTITENANT.md invariant 2 & 3)."""
import queue
import threading
import time

from .store import Store
from .track import Tracker


class ScanLog:
    def __init__(self, store: Store, tracker: Tracker):
        self.store = store
        self.tracker = tracker
        self.queue: queue.Queue = queue.Queue(maxsize=20_000)
        self.dropped = 0
        self._quota_cache: dict[str, tuple[bool, float]] = {}  # user_id -> (limited, expires)
        self._cache_lock = threading.Lock()
        self._stop = threading.Event()
        self.workers = [threading.Thread(target=self._run, daemon=True, name=f"scan-{i}")
                        for i in range(2)]
        for w in self.workers:
            w.start()

    def is_limited(self, user_id: str) -> bool:
        with self._cache_lock:
            hit = self._quota_cache.get(user_id)
            if hit and hit[1] > time.time():
                return hit[0]
        user = self.store.user_by_id(user_id)
        quota = self.store.plan_quota(user["plan"] if user else "free")
        cap = quota["max_scans_month"] if quota else 5_000
        limited = self.store.month_usage(user_id) >= cap
        with self._cache_lock:
            self._quota_cache[user_id] = (limited, time.time() + 60)
        return limited

    def enqueue(self, campaign_row: dict, ip: str, ua: str, dnt: bool):
        try:
            self.queue.put_nowait((campaign_row, ip, ua, dnt))
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while not self._stop.is_set():
            try:
                campaign, ip, ua, dnt = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if not self.is_limited(campaign["user_id"]):
                    scan = self.tracker.build_scan(ip, ua, dnt)
                    self.store.insert_scan(
                        campaign["id"], scan["country"], scan["city"], scan["device"],
                        scan["os"], scan["browser"], scan["visitor_id"], scan["is_bot"],
                    )
            except Exception as e:
                print(f"[scanlog] {e}")
            finally:
                self.queue.task_done()

    def drain(self, timeout: float = 2.0):
        deadline = time.time() + timeout
        while not self.queue.empty() and time.time() < deadline:
            time.sleep(0.05)
