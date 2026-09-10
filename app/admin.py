"""CRM-lite admin panel (docs: this replaces a standalone CRM until ~50 paying
customers — the only questions that matter by then are who signed up, what plan
they're on, and whether they're getting value). Plan flips take effect
immediately: quotas are read fresh on campaign creation, and the scan-quota
cache expires within 60 s."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .svc import svc

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/")
@admin_required
def home():
    return render_template("admin.html", data=svc().store.admin_overview(),
                           plans=svc().store.all_plans())


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
