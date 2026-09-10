"""App factory: wires DB, tracking, async scan pipeline, redirect cache,
blueprints, security headers, and the hourly retention job."""
import logging
import os
import threading
import time
from types import SimpleNamespace

from flask import Flask, request

from .config import Config
from .db import DB
from .scanlog import ScanLog
from .store import Store
from .track import Tracker

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qrtr")


class RedirectCache:
    """Process-local slug→destination cache (design doc: hot path never waits
    on SQL). All campaign writes go through this app and invalidate it, so no
    TTL is needed at one replica; add a TTL if you ever scale horizontally."""

    def __init__(self, store: Store):
        self.store = store
        self._cache: dict[str, dict | None] = {}
        self._lock = threading.Lock()

    def get(self, code: str):
        with self._lock:
            if code in self._cache:
                return self._cache[code]
        row = self.store.campaign_by_code(code)
        entry = dict(row) if row else None
        with self._lock:
            self._cache[code] = entry
        return entry

    def invalidate(self, code: str):
        with self._lock:
            self._cache.pop(code, None)


def _retention_loop(store: Store, days: int):
    while True:
        time.sleep(3600)
        try:
            pruned = store.rollup_and_prune(days)
            if pruned:
                print(f"[retention] rolled up + pruned {pruned} raw scans")
        except Exception as e:
            print(f"[retention] {e}")


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET") or os.urandom(32)  # flashes only

    # Behind any TLS-terminating proxy (Caddy, the sandbox preview), trust the
    # forwarded headers so scheme/host are right. WITHOUT this, Flask thinks
    # every request is plain http and 302-redirects to http://… after a POST —
    # the browser then follows over http, the Secure session cookie is not sent,
    # and the user appears "not signed up / logged out". That was the signup bug.
    if Config.TRUST_PROXY:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    db = DB(Config.DATA_DIR, Config.DB_NAME)
    store = Store(db)
    geo_path = Config.GEO_MMDB or os.path.join(Config.DATA_DIR, "geo.mmdb")
    tracker = Tracker(geo_path)
    scanlog = ScanLog(store, tracker)
    redir_cache = RedirectCache(store)
    app.extensions["qrtr"] = SimpleNamespace(
        db=db, store=store, tracker=tracker, scanlog=scanlog, redir_cache=redir_cache)

    from . import admin as admin_mod, auth, dash, redirect as redir
    app.register_blueprint(auth.bp)
    app.register_blueprint(dash.bp)
    app.register_blueprint(redir.bp)
    app.register_blueprint(admin_mod.bp)

    @app.before_request
    def csrf_guard():
        """Session cookie is SameSite=None (iframe embeddable) — so enforce CSRF
        protection via the Fetch Metadata header every modern browser sends.
        Absent header (old browser, curl) → allowed through; 'cross-site' POST
        → rejected. TODO: add per-form tokens before OAuth/third-party embeds.
        """
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            site = request.headers.get("Sec-Fetch-Site")
            if site == "cross-site":
                log.warning("blocked cross-site %s on %s", request.method, request.path)
                return "Forbidden", 403

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.path.startswith("/c/"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        if not request.path.startswith("/static/"):
            log.info("%s %s -> %s", request.method, request.path, resp.status_code)
        return resp

    @app.template_filter("num")
    def fmt_num(n):
        return f"{int(n or 0):,}"

    @app.template_filter("ts")
    def fmt_ts(value):
        if not value:
            return "—"
        return value[:16].replace("T", " ") + " UTC"

    threading.Thread(target=_retention_loop, args=(store, Config.SCAN_RETENTION_DAYS),
                     daemon=True, name="retention").start()
    return app
