# qrtr

**Self-hosted, multi-tenant, privacy-respecting dynamic QR-code tracker.**
Print one QR per poster/shop/display → every scan records time, approximate city/country,
device/OS/browser → 302-redirects to any destination you can edit any time **without reprinting**.

Stack: **Python 3.11+ · Flask · SQLite (WAL) · waitress · segno** — zero-compiler, zero build step.
Docs: [design (v1)](docs/DESIGN.md) · [multi-tenant SaaS spec (v2)](docs/MULTITENANT.md) · [privacy design](docs/PRIVACY.md).

## Quickstart (local, 60 seconds)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/fetch-geo.sh        # optional: city-level geo (db-ip Lite, CC BY 4.0)
.venv/bin/python run.py       # → http://localhost:8080
```

Open the URL → **Sign up** → **+ New QR** → paste any destination (portfolio,
`https://wa.me/<number>`, Maps share link, catalogue PDF, form) → download **SVG** (print) or PNG.
Scan the code with your phone → watch **Stats**.

Print-shops: **Bulk create** pastes `Name,https://url` lines (one per QR, quota-aware) and returns
a pageful of ready links, then **Download ZIP** hands back print-named PNGs (`<slug>-<code>.png`)
plus an `index.csv` mapping. Admins can invite users, flip plans, and **reset a user's password**
(one-time temporary password shown in a flash).

## Deploy on your VPS (Docker, one command)

**No domain / no budget? → [docs/DEPLOY-NODOMAIN.md](docs/DEPLOY-NODOMAIN.md): free Oracle VM +
free DuckDNS name + GitHub CI/CD = ₹0/month.** GitHub itself hosts the code, CI (`.github/workflows/test.yml`),
Docker images (GHCR), this repo's landing page (`landing/` → GitHub Pages), and auto-deploy —
but **not** the app runtime (Pages is static-only; that's what the free VM is for).

```bash
# DNS first: A records for go.example.com + app.example.com → your VPS IP
DOMAIN=go.example.com APP_DOMAIN=app.example.com \
  BASE_URL=https://go.example.com \
  docker compose -f deploy/docker-compose.yml up -d --build
```

Caddy obtains/renews TLS automatically. SQLite lives in the `qrtr-data` volume.
A €3.79 Hetzner CX22 (or Oracle's free ARM tier — see docs/MULTITENANT.md §2) is plenty.

## Everyday ops

| Task | How |
|---|---|
| Upgrade a user's plan | `docker exec -it <app> sqlite3 /data/qrtr.db "UPDATE user SET plan='pro' WHERE email='x@y.z';"` |
| Turn signup off (invite-only) | set `ALLOW_SIGNUP=0`, restart |
| Health check / uptime monitor | `GET /healthz` |
| Backups | copy `/data/qrtr.db*` (WAL-safe: run `PRAGMA wal_checkpoint;` first) or uncomment Litestream in compose |

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `BASE_URL` | *(request host)* | URL written into QRs — set to your short domain in production |
| `DATA_DIR` | `./data` | SQLite + geo.mmdb location |
| `ALLOW_SIGNUP` | `0` | **invite-only by default**: the first-ever signup (the owner/admin) is always allowed on a fresh install, then signup closes; admins invite more users from the Admin panel. `1` = open public signup |
| `COOKIE_SECURE` | `1` | set `0` only for plain-http local dev |
| `SCAN_RETENTION_DAYS` | `90` | raw scans pruned after this; daily aggregates kept |
| `PORT` | `8080` | listen port |

## Architecture invariants (tested, see `app/`)

1. **Tenancy is a store-layer guarantee** — every campaign/scan query is `user_id`-scoped; cross-tenant access → 404.
2. **Redirects never die** — the `/c/<code>` hot path is public, in-memory-cached, and quota-independent.
   Over-quota months stop *logging*; redirects keep working.
3. **Privacy pipeline** — no raw IPs stored (city lookup + daily-rotating HMAC salt in RAM only),
   no cookies for scanners, DNT/GPC respected, link-preview bots filtered, 90-day retention with rollups.
4. **302 + `Cache-Control: no-store`, always** — a 301 would be cached by browsers and kill both tracking and edits.
5. **CSRF on every authed mutation** — stateless per-session HMAC token (`HMAC(session_cookie, 'qrtr-csrf')[:32]`,
   stateless = survives restarts) + `Sec-Fetch-Site` cross-site block. Login/signup (pre-auth) rely on
   Sec-Fetch + per-IP rate limits.
6. **Rate limits where abuse hurts** (in-memory sliding window, zero deps) — login 10/min/IP,
   signup 5/5min/IP, invites 30/5min, bulk create 10/5min, account changes 10/5min. 429s on breach.

**Traceable analytics:** dashboard stats exclude bots (dekha = sach), while **Full scan log**
(`/campaigns/<code>/scans`) shows *every* hit tagged human/bot for reconciliation, plus a
weekday×hour heatmap (UTC) for posting-timing decisions. Group trends by day / week (Mon-start) / month.

## Roadmap (post-MVP, in priority order)

Razorpay/Stripe plan upgrades (schema-ready: `plan_quota`) → custom domains (Caddy on-demand TLS) →
teams/roles → public API. Flip the redirect hot path to Cloudflare Workers only when
>1M scans/day demands it (spec: docs/MULTITENANT.md §5).
