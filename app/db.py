"""SQLite access layer. One shared connection (WAL mode, busy timeout) guarded
by a lock — QR-scan volumes make this trivially sufficient, and it removes a
whole class of thread-safety bugs. Swap this module for Postgres later without
touching the rest of the app (see docs/DESIGN.md §4)."""
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
  id            TEXT PRIMARY KEY,
  email         TEXT UNIQUE NOT NULL COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  plan          TEXT NOT NULL DEFAULT 'free',
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS session (
  token      TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);

CREATE TABLE IF NOT EXISTS plan_quota (
  plan             TEXT PRIMARY KEY,
  max_campaigns    INTEGER NOT NULL,
  max_scans_month  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign (
  id              TEXT PRIMARY KEY,          -- global short code, e.g. 'a3K9xQ'
  user_id         TEXT NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  destination_url TEXT NOT NULL,
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_campaign_user ON campaign(user_id);

CREATE TABLE IF NOT EXISTS scan (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
  ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  country     TEXT,                           -- ISO code or NULL; city-level max
  city        TEXT,
  device      TEXT,                           -- mobile | tablet | desktop | bot
  os          TEXT,
  browser     TEXT,
  visitor_id  TEXT,                           -- HMAC(ip|ua, daily salt); NULL on DNT
  is_bot      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_scan_campaign_ts ON scan(campaign_id, ts);

CREATE TABLE IF NOT EXISTS daily_stat (       -- rollups kept after retention sweep
  campaign_id TEXT NOT NULL,
  day         TEXT NOT NULL,
  scans       INTEGER NOT NULL,
  uniques     INTEGER NOT NULL,
  PRIMARY KEY (campaign_id, day)
);
"""

PLANS = [
    ("free", 3, 5_000),
    ("pro", 50, 200_000),
    ("business", 500, 2_000_000),
]


class DB:
    def __init__(self, data_dir: str, name: str):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, name)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self):
        with self._lock:
            self._conn.executescript(SCHEMA)
            for plan, max_c, max_s in PLANS:
                self._conn.execute(
                    "INSERT INTO plan_quota(plan, max_campaigns, max_scans_month)"
                    " VALUES(?,?,?) ON CONFLICT(plan) DO NOTHING",
                    (plan, max_c, max_s),
                )
            self._conn.commit()

    # All access goes through these two helpers so the lock can never be forgotten.
    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def exec(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur.rowcount

    def close(self):
        with self._lock:
            self._conn.close()
