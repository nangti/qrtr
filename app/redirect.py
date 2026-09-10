"""THE hot path. Public, unauthenticated, cached, quota-independent
(docs/MULTITENANT.md invariant 2): nothing — not billing, not login state,
not a full scan queue — may prevent a printed QR from redirecting.
Always 302 + no-store: a 301 would be cached by browsers and would kill both
tracking and destination edits (docs/DESIGN.md risk #2)."""
from flask import Blueprint, Response, redirect, render_template, request

from .config import Config
from .svc import svc

bp = Blueprint("redirect", __name__)


def client_ip() -> str:
    if Config.TRUST_PROXY:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote_addr or ""


@bp.get("/c/<code>")
def go(code: str):
    campaign = svc().redir_cache.get(code)
    if not campaign or not campaign["active"]:
        return render_template("redirect_404.html"), 404

    ua = request.headers.get("User-Agent", "")[:512]
    dnt = request.headers.get("DNT") == "1" or request.headers.get("Sec-GPC") == "1"
    svc().scanlog.enqueue(campaign, client_ip(), ua, dnt)  # async — never blocks

    resp = redirect(campaign["destination_url"], code=302)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp
