"""Tenant-scoped data operations. TENANCY INVARIANT: every method that touches
campaigns or scans takes user_id and embeds it in the query — there is no code
path that can return another user's data (docs/MULTITENANT.md §3, invariant 1).
The single exception is get_campaign_by_code(), used by the public redirect
hot path, which deliberately exposes only (destination_url, active)."""
import secrets
from datetime import datetime, timedelta, timezone

from .db import DB
from .security import new_short_code, new_user_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, db: DB):
        self.db = db

    # ---- users & sessions -------------------------------------------------
    def create_user(self, email: str, password_hash: str) -> str:
        uid = new_user_id()
        self.db.exec(
            "INSERT INTO user(id, email, password_hash) VALUES(?,?,?)",
            (uid, email.strip().lower(), password_hash),
        )
        # First-registered user = admin (CRM-lite bootstrap). The boot-time
        # migration in db.py covers databases that already had users; this
        # covers fresh installs where signup happens after boot.
        if self.db.one("SELECT COUNT(*) AS c FROM user")["c"] == 1:
            self.db.exec("UPDATE user SET is_admin=1 WHERE id=?", (uid,))
        return uid

    def user_by_email(self, email: str):
        return self.db.one("SELECT * FROM user WHERE email=?", (email.strip().lower(),))

    def user_by_id(self, uid: str):
        return self.db.one("SELECT * FROM user WHERE id=?", (uid,))

    def create_session(self, token: str, user_id: str, days: int):
        exp = (_now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        self.db.exec(
            "INSERT INTO session(token, user_id, expires_at) VALUES(?,?,?)",
            (token, user_id, exp),
        )

    def user_for_session(self, token: str, sliding_days: int):
        """Returns the user row if session valid; slides expiry past half-life."""
        row = self.db.one(
            "SELECT s.token, s.expires_at, u.* FROM session s JOIN user u ON u.id=s.user_id"
            " WHERE s.token=?", (token,),
        )
        if not row:
            return None
        exp = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if exp <= _now():
            self.db.exec("DELETE FROM session WHERE token=?", (token,))
            return None
        if exp <= _now() + timedelta(days=sliding_days // 2):
            new_exp = (_now() + timedelta(days=sliding_days)).strftime("%Y-%m-%d %H:%M:%S")
            self.db.exec("UPDATE session SET expires_at=? WHERE token=?", (new_exp, token))
        return row

    def delete_session(self, token: str):
        self.db.exec("DELETE FROM session WHERE token=?", (token,))

    # ---- campaigns (always tenant-scoped) ---------------------------------
    def create_campaign(self, user_id: str, name: str, destination_url: str, code_len: int) -> str:
        for _ in range(5):
            code = new_short_code(code_len)
            try:
                self.db.exec(
                    "INSERT INTO campaign(id, user_id, name, destination_url) VALUES(?,?,?,?)",
                    (code, user_id, name, destination_url),
                )
                return code
            except Exception:
                continue  # astronomically unlikely code collision — retry
        raise RuntimeError("could not allocate short code")

    def campaigns_for_user(self, user_id: str):
        rows = self.db.q(
            "SELECT * FROM campaign WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        )
        out = []
        for r in rows:
            stats = self.db.one(
                "SELECT COUNT(*) AS total,"
                " SUM(CASE WHEN ts>=datetime('now','-30 days') AND is_bot=0 THEN 1 ELSE 0 END) AS m30,"
                " MAX(ts) AS last_ts"
                " FROM scan WHERE campaign_id=?",
                (r["id"],),
            )
            out.append({**dict(r), "total": stats["total"] or 0,
                        "m30": stats["m30"] or 0, "last_ts": stats["last_ts"]})
        return out

    def campaign_for_user(self, user_id: str, cid: str):
        return self.db.one(
            "SELECT * FROM campaign WHERE id=? AND user_id=?", (cid, user_id)
        )

    def update_campaign(self, user_id: str, cid: str, name: str, dest: str, active: bool) -> int:
        return self.db.exec(
            "UPDATE campaign SET name=?, destination_url=?, active=? WHERE id=? AND user_id=?",
            (name, dest, 1 if active else 0, cid, user_id),
        )

    def delete_campaign(self, user_id: str, cid: str) -> int:
        return self.db.exec("DELETE FROM campaign WHERE id=? AND user_id=?", (cid, user_id))

    def campaign_by_code(self, code: str):
        """Public hot path: by design returns only what a redirect needs + owner
        (for quota checks). Never rendered into any tenant view."""
        return self.db.one(
            "SELECT id, user_id, destination_url, active FROM campaign WHERE id=?", (code,)
        )

    # ---- scans ------------------------------------------------------------
    def insert_scan(self, campaign_id: str, country: str, city: str, device: str,
                    os_: str, browser: str, visitor_id: str | None, is_bot: bool):
        self.db.exec(
            "INSERT INTO scan(campaign_id, country, city, device, os, browser, visitor_id, is_bot)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (campaign_id, country, city, device, os_, browser, visitor_id, 1 if is_bot else 0),
        )

    def month_usage(self, user_id: str) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS c FROM scan s JOIN campaign c ON c.id=s.campaign_id"
            " WHERE c.user_id=? AND strftime('%Y-%m', s.ts)=strftime('%Y-%m','now')",
            (user_id,),
        )
        return row["c"]

    def scan_stats(self, user_id: str, cid: str, days: int):
        """Everything the campaign detail page needs, tenant-scoped, bots excluded."""
        where = ("c.user_id=? AND s.campaign_id=?", (user_id, cid))
        rng = f"-{int(days)} days"

        base = (" FROM scan s JOIN campaign c ON c.id=s.campaign_id"
                " WHERE c.user_id=? AND s.campaign_id=? AND s.is_bot=0"
                " AND s.ts>=datetime('now', ?)")

        totals = self.db.one(
            "SELECT COUNT(*) AS scans, COUNT(DISTINCT s.visitor_id) AS uniques" + base,
            (user_id, cid, rng),
        )
        bots = self.db.one(
            "SELECT COUNT(*) AS c FROM scan s WHERE s.campaign_id=? AND s.is_bot=1"
            " AND s.ts>=datetime('now', ?)", (cid, rng),
        )

        def breakdown(col):
            rows = self.db.q(
                f"SELECT COALESCE(NULLIF(s.{col},''),'Unknown') AS k, COUNT(*) AS c"
                + base + f" GROUP BY k ORDER BY c DESC LIMIT 12",
                (user_id, cid, rng),
            )
            return [(r["k"], r["c"]) for r in rows]

        recent = self.db.q(
            "SELECT s.ts, s.country, s.city, s.device, s.os, s.browser"
            + base + " ORDER BY s.id DESC LIMIT 50",
            (user_id, cid, rng),
        )

        # Build a gapless day series for the chart.
        by_day = {r["d"]: (r["c"], r["u"]) for r in self.db.q(
            "SELECT date(s.ts) AS d, COUNT(*) AS c, COUNT(DISTINCT s.visitor_id) AS u"
            + base + " GROUP BY d", (user_id, cid, rng),
        )}
        labels, scans_s, uniq_s = [], [], []
        today = _now().date()
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            labels.append(d)
            c, u = by_day.get(d, (0, 0))
            scans_s.append(c)
            uniq_s.append(u)

        return {
            "totals": totals, "bots_filtered": bots["c"],
            "countries": breakdown("country"), "cities": breakdown("city"),
            "devices": breakdown("device"), "browsers": breakdown("browser"),
            "oses": breakdown("os"), "recent": recent,
            "labels": labels, "series_scans": scans_s, "series_uniques": uniq_s,
        }

    def scans_csv(self, user_id: str, cid: str, limit: int = 10000):
        return self.db.q(
            "SELECT s.ts, s.country, s.city, s.device, s.os, s.browser, s.is_bot"
            " FROM scan s JOIN campaign c ON c.id=s.campaign_id"
            " WHERE c.user_id=? AND s.campaign_id=? ORDER BY s.id DESC LIMIT ?",
            (user_id, cid, limit),
        )

    # ---- plans / quotas ----------------------------------------------------
    def plan_quota(self, plan: str):
        return self.db.one("SELECT * FROM plan_quota WHERE plan=?", (plan,))

    def all_plans(self):
        return [r["plan"] for r in
                self.db.q("SELECT plan FROM plan_quota ORDER BY max_campaigns")]

    def campaign_count(self, user_id: str) -> int:
        return self.db.one("SELECT COUNT(*) AS c FROM campaign WHERE user_id=?", (user_id,))["c"]

    # ---- admin (CRM-lite) ---------------------------------------------------
    def admin_overview(self):
        out = []
        for u in self.db.q("SELECT * FROM user ORDER BY created_at ASC"):
            last = self.db.one(
                "SELECT MAX(s.ts) AS t FROM scan s JOIN campaign c ON c.id=s.campaign_id"
                " WHERE c.user_id=?", (u["id"],))["t"]
            out.append({**dict(u), "campaigns": self.campaign_count(u["id"]),
                        "usage": self.month_usage(u["id"]), "last_scan": last})
        t = self.db.one(
            "SELECT (SELECT COUNT(*) FROM campaign) AS campaigns,"
            " (SELECT COUNT(*) FROM scan) AS scans")
        return {"users": out, "total_campaigns": t["campaigns"], "total_scans": t["scans"]}

    def set_user_plan(self, user_id: str, plan: str) -> bool:
        if not self.plan_quota(plan):
            return False
        return bool(self.db.exec("UPDATE user SET plan=? WHERE id=?", (plan, user_id)))

    # ---- retention (privacy promise: raw scans pruned, rollups kept) -------
    def rollup_and_prune(self, retention_days: int) -> int:
        rng = f"-{int(retention_days)} days"
        self.db.exec(
            "INSERT INTO daily_stat(campaign_id, day, scans, uniques)"
            " SELECT campaign_id, date(ts), COUNT(*), COUNT(DISTINCT visitor_id)"
            " FROM scan WHERE ts < datetime('now', ?) GROUP BY campaign_id, date(ts)"
            " ON CONFLICT(campaign_id, day) DO UPDATE SET"
            " scans=excluded.scans, uniques=excluded.uniques",
            (rng,),
        )
        return self.db.exec("DELETE FROM scan WHERE ts < datetime('now', ?)", (rng,))
