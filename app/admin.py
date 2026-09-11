"""Invite-only user management for the admin panel: admins create accounts
directly (with an optional explicit password for testing/support), owners
never rely on public signup."""
import secrets

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .auth import EMAIL_RE, admin_required
from .security import hash_password
from .svc import svc

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_app_request
def _rl_uid():
    request.user_id_for_rl = g.user["id"] if g.user else "anon"


@bp.get("/")
@admin_required
def home():
    return render_template("admin.html", data=svc().store.admin_overview(),
                           plans=svc().store.all_plans())


@bp.post("/users/add")
@admin_required
def add_user():
    if not svc().ratelimit.allow(f"invite:{request.user_id_for_rl}", 30, 300):
        flash("Invite rate limit hit — wait a few minutes.")
        return redirect(url_for("admin.home"))
    email = request.form.get("email", "").strip().lower()
    pw = request.form.get("password", "").strip()
    if not EMAIL_RE.match(email):
        flash("Enter a valid email address.")
    elif svc().store.user_by_email(email):
        flash(f"{email} already has an account.")
    else:
        if pw:
            if len(pw) < 8:
                flash("Password must be at least 8 characters.")
                return redirect(url_for("admin.home"))
            flash(f"Account created for {email} with the password you set.")
        else:
            pw = secrets.token_urlsafe(10)
            flash(f"Account created for {email} — temporary password: {pw} "
                  "(shown once — send it privately; they should change it under Account).")
        svc().store.create_user(email, hash_password(pw))
    return redirect(url_for("admin.home"))


@bp.post("/users/<uid>/reset")
@admin_required
def reset_password(uid: str):
    user = svc().store.user_by_id(uid)
    if not user:
        abort(404)
    temp = secrets.token_urlsafe(10)
    svc().store.update_password(uid, hash_password(temp))
    flash(f"Password for {user['email']} reset — temporary password: {temp} (shown once).")
    return redirect(url_for("admin.home"))


@bp.post("/users/<uid>/plan")
@admin_required
def set_plan(uid: str):
    plan = request.form.get("plan", "")
    if svc().store.set_user_plan(uid, plan):
        svc().scanlog.invalidate_quota_cache(uid)
        flash(f"Plan set to '{plan}' — limits apply immediately.")
    else:
        flash("Unknown plan.")
    return redirect(url_for("admin.home"))
