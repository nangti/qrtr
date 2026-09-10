"""Dashboard + campaign management (all behind login, all tenant-scoped),
plus public utility routes (/privacy, /healthz)."""
import csv
import io
import re

from flask import (Blueprint, Response, abort, flash, g, redirect,
                   render_template, request, url_for)

from .auth import login_required
from .config import Config
from .qr import qr_png, qr_svg
from .svc import svc

bp = Blueprint("dash", __name__)
RANGES = (7, 30, 90)
DEST_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def short_url(code: str) -> str:
    base = Config.BASE_URL or request.url_root.rstrip("/")
    return f"{base}/c/{code}"


def _validate_campaign_form():
    name = request.form.get("name", "").strip()
    dest = request.form.get("destination_url", "").strip()
    if not (1 <= len(name) <= 80):
        return None, None, "Name is required (max 80 characters)."
    if not DEST_RE.match(dest) or len(dest) > 2048:
        return None, None, ("Destination must be a valid http(s) URL. "
                            "For WhatsApp use https://wa.me/<number> — Maps, PDFs and forms all work.")
    return name, dest, None


@bp.get("/healthz")
def healthz():
    return Response("ok", mimetype="text/plain")


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.get("/")
@login_required
def home():
    st = svc().store
    campaigns = st.campaigns_for_user(g.user["id"])
    quota = st.plan_quota(g.user["plan"])
    usage = st.month_usage(g.user["id"])
    limited = usage >= quota["max_scans_month"]
    return render_template(
        "dashboard.html", campaigns=campaigns, quota=quota, usage=usage,
        limited=limited, short_url=short_url,
        total=sum(c["total"] for c in campaigns), m30=sum(c["m30"] for c in campaigns),
    )


@bp.route("/campaigns/new", methods=["GET", "POST"])
@login_required
def new_campaign():
    st = svc().store
    quota = st.plan_quota(g.user["plan"])
    if request.method == "POST":
        if st.campaign_count(g.user["id"]) >= quota["max_campaigns"]:
            flash(f"Your '{g.user['plan']}' plan allows {quota['max_campaigns']} QR campaigns. "
                  "Delete one or ask the admin to upgrade your plan.")
            return redirect(url_for("dash.home"))
        name, dest, err = _validate_campaign_form()
        if err:
            return render_template("campaign_form.html", error=err, campaign=None,
                                   form=request.form), 400
        cid = st.create_campaign(g.user["id"], name, dest, Config.CODE_LENGTH)
        flash("QR campaign created — download the code below and print it.")
        return redirect(url_for("dash.campaign_detail", cid=cid))
    return render_template("campaign_form.html", error=None, campaign=None, form={})


@bp.get("/campaigns/<cid>")
@login_required
def campaign_detail(cid: str):
    st = svc().store
    campaign = st.campaign_for_user(g.user["id"], cid)
    if not campaign:  # never leak existence across tenants — 404, not 403
        abort(404)
    days = request.args.get("days", 30, type=int)
    days = days if days in RANGES else 30
    stats = st.scan_stats(g.user["id"], cid, days)
    return render_template("campaign_detail.html", campaign=campaign, stats=stats,
                           days=days, ranges=RANGES, short_url=short_url(cid))


@bp.route("/campaigns/<cid>/edit", methods=["GET", "POST"])
@login_required
def edit_campaign(cid: str):
    st = svc().store
    campaign = st.campaign_for_user(g.user["id"], cid)
    if not campaign:
        abort(404)
    if request.method == "POST":
        name, dest, err = _validate_campaign_form()
        if err:
            return render_template("campaign_form.html", error=err,
                                   campaign=campaign, form=request.form), 400
        active = request.form.get("active") == "on"
        st.update_campaign(g.user["id"], cid, name, dest, active)
        svc().redir_cache.invalidate(cid)  # hot path sees changes immediately
        flash("Campaign updated. Printed QRs pick up the change instantly — no reprint needed.")
        return redirect(url_for("dash.campaign_detail", cid=cid))
    return render_template("campaign_form.html", error=None, campaign=campaign, form=dict(campaign))


@bp.post("/campaigns/<cid>/delete")
@login_required
def delete_campaign(cid: str):
    st = svc().store
    if st.delete_campaign(g.user["id"], cid):
        svc().redir_cache.invalidate(cid)
        flash("Campaign and its scan history deleted. The printed QR will now 404.")
    return redirect(url_for("dash.home"))


@bp.get("/campaigns/<cid>/qr.<fmt>")
@login_required
def campaign_qr(cid: str, fmt: str):
    campaign = svc().store.campaign_for_user(g.user["id"], cid)
    if not campaign:
        abort(404)
    target = short_url(cid)
    if fmt == "png":
        scale = max(2, min(request.args.get("scale", 12, type=int), 40))
        body, mime, ext = qr_png(target, scale), "image/png", "png"
    elif fmt == "svg":
        body, mime, ext = qr_svg(target), "image/svg+xml", "svg"
    else:
        abort(404)
    resp = Response(body, mimetype=mime)
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = f'attachment; filename="qrtr-{cid}.{ext}"'
    return resp


@bp.get("/campaigns/<cid>/scans.csv")
@login_required
def campaign_csv(cid: str):
    if not svc().store.campaign_for_user(g.user["id"], cid):
        abort(404)
    rows = svc().store.scans_csv(g.user["id"], cid)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_utc", "country", "city", "device", "os", "browser", "is_bot"])
    for r in rows:
        w.writerow([r["ts"], r["country"] or "", r["city"] or "", r["device"],
                    r["os"], r["browser"], r["is_bot"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="qrtr-{cid}-scans.csv"'})
