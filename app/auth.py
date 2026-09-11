"""Email/password auth: signup, login, logout, session cookie, login_required.
Session tokens live in the DB (revocable, sliding expiry) — no JWT, no cookies
for tracking, just the one auth cookie."""
import functools
import re

from flask import (Blueprint, abort, flash, g, make_response, redirect,
                   render_template, request, url_for)

from .config import Config
from .security import (hash_password, new_session_token, verify_password)
from .svc import svc

bp = Blueprint("auth", __name__)
SESSION_COOKIE = "qrtr_sid"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.before_app_request
def load_user():
    g.user = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        g.user = svc().store.user_for_session(token, Config.SESSION_DAYS)
        if not g.user:
            g.user = None


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """login_required + is_admin. The first registered user is auto-admin
    (migration in db.py); promote others via SQL or a future UI."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        if not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _user_count() -> int:
    return svc().store.db.one("SELECT COUNT(*) AS c FROM user")["c"]


def signup_open() -> bool:
    """Open signup, OR nobody exists yet (owner bootstrap on fresh installs)."""
    return Config.ALLOW_SIGNUP or _user_count() == 0


def bootstrap_mode() -> bool:
    """Fresh install, invite-only config → first form is the owner's account."""
    return not Config.ALLOW_SIGNUP and _user_count() == 0


def _start_session(user_id: str, target: str):
    token = new_session_token()
    svc().store.create_session(token, user_id, Config.SESSION_DAYS)
    resp = make_response(redirect(target))
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=Config.SESSION_DAYS * 86400,
        httponly=True, secure=Config.COOKIE_SECURE,
        # None (not Lax): the dashboard may be rendered inside a cross-origin
        # iframe (hosted panels embedding the preview), where Lax cookies are
        # blocked and login silently fails. Secure is always on, so None is
        # accepted; CSRF exposure is closed by the Sec-Fetch-Site guard in
        # create_app.
        samesite="None",
    )
    return resp


def _safe_next() -> str:
    nxt = request.args.get("next") or request.form.get("next") or ""
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dash.home")


@bp.get("/login")
def login():
    if g.user:
        return redirect(url_for("dash.home"))
    return render_template("login.html", error=None,
                           signup_open=signup_open(), bootstrap=bootstrap_mode())


@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = svc().store.user_by_email(email)
    if user and verify_password(password, user["password_hash"]):
        return _start_session(user["id"], _safe_next())
    return render_template("login.html", error="Invalid email or password.",
                           signup_open=signup_open(), bootstrap=bootstrap_mode(),
                           email=email), 401


@bp.get("/signup")
def signup():
    if g.user:
        return redirect(url_for("dash.home"))
    if not signup_open():
        flash("This deployment is invite-only — ask the owner for an account.")
        return redirect(url_for("auth.login"))
    return render_template("signup.html", error=None, bootstrap=bootstrap_mode())


@bp.post("/signup")
def signup_post():
    if not signup_open():
        flash("This deployment is invite-only — ask the owner for an account.")
        return redirect(url_for("auth.login"))
    email = request.form.get("email", "").strip().lower()
    pw = request.form.get("password", "")
    pw2 = request.form.get("password2", "")

    def fail(msg):
        return render_template("signup.html", error=msg, email=email,
                               bootstrap=bootstrap_mode()), 400

    if not EMAIL_RE.match(email):
        return fail("Enter a valid email address.")
    if len(pw) < 8:
        return fail("Password must be at least 8 characters.")
    if pw != pw2:
        return fail("Passwords do not match.")
    if svc().store.user_by_email(email):
        return fail("An account with this email already exists.")
    uid = svc().store.create_user(email, hash_password(pw))
    return _start_session(uid, url_for("dash.home"))


@bp.post("/logout")
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        svc().store.delete_session(token)
    resp = make_response(redirect(url_for("auth.login")))
    resp.delete_cookie(SESSION_COOKIE)
    return resp
