# qrtr — Dynamic QR-Code Tracking System: Design Proposal

**Status:** v1 single-tenant design · **Date:** 2026-09-10 · **⚠ Goal has since pivoted to a sellable multi-tenant SaaS — see [MULTITENANT.md](MULTITENANT.md) (v2), which supersedes §2–§4's single-user framing while keeping this document's privacy pipeline, redirect discipline, and infra skeleton.**

---

## 1. Requirements (restated)

| # | Requirement | Design consequence |
|---|---|---|
| R1 | One printed QR per display/shop/poster | Short-URL redirect service: `qr.example.com/r/{slug}` |
| R2 | Record time, city/country, device, browser, OS | In-process MMDB geo lookup + User-Agent parsing at scan time |
| R3 | Redirect to a final URL (portfolio, WhatsApp, Maps, catalogue, form) | HTTP **302/307** (never 301), editable destination per slug |
| R4 | Dashboard: totals, est. uniques, by day/week/month, by location, by device | Aggregation queries over a `scan` table + daily rollups |
| R5 | Free/OSS, low-cost, privacy-respecting (no GPS, anonymised IPs) | No cookies, no raw IP stored, daily-rotating salt for uniques |
| R6 | Small VPS with Docker | ≤ 500 MB RAM total, `docker compose up` = running |

Non-goals for v1: multi-tenant SaaS, user accounts per customer, exact GPS, A/B routing, scheduled destinations.

### Buy-vs-build benchmark
[Shlink](https://shlink.io) (MIT, PHP/Symfony + Postgres/MariaDB) already does short links + QR generation + device/location/referrer tracking + IP anonymisation, and deploys via Docker. It is the bar any custom build must beat. Verdict below: Shlink is Option C and the fallback if the custom MVP slips.

---

## 2. Candidate stacks

### Option A — "Single binary" ★ (recommended)

| Layer | Choice | Why |
|---|---|---|
| Backend | **Go 1.24+** (`net/http` + `chi`) | Redirect logic is ~150 LOC; compiles to one static binary (~20 MB image, ~30–50 MB RAM) |
| Database | **SQLite** (`modernc.org/sqlite`, CGO-free, WAL mode) | Zero DB server to run/patch/tune; backup = one file; handles this workload 100× over |
| Analytics | **SQL rollups in-app** (daily_stat table) + server-rendered charts | The dashboard is 5 fixed queries; no external BI tool needed |
| Geo / UA | DB-IP Lite City MMDB (CC BY 4.0) via `maxminddb-golang`; `uap-go` (uap-core rules incl. bot detection) | Both run in-memory inside the process: µs per scan, no network calls, no third-party data leaves the box |
| Frontend | Go templates + **HTMX + Chart.js** (vendored, no JS build step) | No npm/toolchain to maintain; dashboard = tables + 3 charts |
| QR generation | `skip2/go-qrcode` (PNG/SVG, error-correction H) | SVG for print shops, PNG for quick tests |
| Deployment | `docker compose`: **app + Caddy** (auto-HTTPS) + optional **Litestream** sidecar → B2/S3 backups | Two containers, ~300 MB RAM total |

### Option B — "Batteries-included JS"

| Layer | Choice | Why |
|---|---|---|
| Backend + Frontend | **Next.js (TypeScript, App Router)** — route handler `app/r/[slug]/route.ts` logs + redirects; dashboard pages with Tremor/Recharts | One language end-to-end; huge hiring/knowledge pool |
| Database | **PostgreSQL 17** | Boring default; best date/aggregation ergonomics (`date_trunc`) |
| Analytics | **Metabase OSS** (Docker, JVM) pointed at Postgres | Free-form, no-code analytics: any future question is a GUI query, not a deploy |
| Geo / UA | `maxmind` Node lib + GeoLite2; `ua-parser-js` + `isbot` | Same data, Node flavours |
| Deployment | compose: **next + postgres + metabase + caddy** | 4 containers, realistically **2.5–4 GB RAM** (Metabase alone wants ~1–1.5 GB) |

### Option C — "Don't build, assemble"

| Layer | Choice | Why |
|---|---|---|
| Backend | **Shlink** (OSS, MIT) | Mature: short links, dynamic destinations, visit tracking (device, geo, referrer), IP anonymisation, REST API |
| Frontend | **shlink-web-client** | Ready-made admin UI |
| Database | **PostgreSQL** (or MariaDB) | Shlink's supported stores |
| Analytics | Shlink built-in stats (+ optional Matomo for deeper analysis) | Zero code |
| QR generation | Built into Shlink | PNG per short URL |
| Deployment | compose: **shlink + web-client + postgres + caddy** | ~0.7–1.2 GB RAM |

---

## 3. Comparison

| Criterion | A: Go + SQLite | B: Next.js + PG + Metabase | C: Shlink |
|---|---|---|---|
| **Infra cost / month** | €0–4 (fits 1 GB free/cheap tier; CX22 €3.79 has 7× headroom) | €4–7 (needs the 4 GB CX22, Metabase pushes it) | €4 (comfortable on CX22) |
| **RAM / containers** | ~300 MB / 2 (+backup) | ~3 GB / 4 | ~1 GB / 4 |
| **Dev effort to MVP** | ~10 working days (one dev) | ~10–14 days (dashboard is hand-built too; Metabase only helps *after*) | ~1–2 days (config, not code) |
| **Feature completeness day 1** | Exactly R1–R6, nothing else | Exactly R1–R6 + Metabase ad-hoc | Far beyond R1–R6 (tags, multi-domain, API keys, import) |
| **Dashboard flexibility** | Fixed 5 views (you own the SQL) | High (Metabase GUI) | Medium (fixed views; API for more) |
| **Privacy control** | **Total** — anon pipeline is ~50 lines you audit | Good, but spread across app code | Good (built-in anonymisation) but it's *their* model; changing it means PHP/Symfony |
| **Scaling ceiling** | ~10⁷–10⁸ scans total on one box; single node only | High; Postgres scales, Metabase drags | High; proven in prod, horizontal via external DB |
| **Maintainability (solo dev)** | 1 binary, 1 file to back up | Node churn (Next majors), JVM to babysit | Upgrade treadmill of a large PHP app you didn't write |
| **Lock-in/exit** | Your schema, trivial export | Your schema | Shlink's schema (export via API) |

**Scoring for *this* use case:** A wins on cost, ops simplicity, privacy control; C wins on time-to-value and features; B is the middle that inherits the worst ops weight (JVM) without beating A on simplicity or C on speed.

---

## 4. Recommendation: **Option A — Go + SQLite + Caddy**

1. **The workload is tiny.** A redirect = 1 slug lookup + 1 insert. Even 1M scans/month ≈ 0.4 req/s average. Go + SQLite on a €3.79 box tolerates ~1000× bursts. Postgres + Metabase would be 1.5 GB of JVM to render three charts.
2. **Ops surface ≈ zero.** One static binary + one database file. Backups are a streamed file copy (Litestream). No DB server, no migrations tooling, no JVM. Exact fit for "small VPS, run it and forget it."
3. **Privacy is your differentiator — own it.** The anonymisation (no raw IP, daily-rotating HMAC salt, city-only geo, DNT handling, retention sweep) is ~50 lines you can audit and defend, not plugin configuration inside a 200k-LOC PHP app.
4. **The dashboard is finite.** Totals, uniques, per-day/week/month, location, device — five SQL GROUP BYs and Chart.js. Server-rendered HTML + HTMX gets there without a JS build chain.
5. **Honest upgrade path.** The repository pattern isolates storage; if scans ever outgrow SQLite (they won't before tens of millions of rows — and by then revenue justifies it), swap the store implementation to Postgres without touching the redirect path.

Choose **C (Shlink)** instead if the 2-week build slips or you decide you don't want to own code at all. Choose **B** only if you already run Next.js + Postgres infra and want Metabase for other projects anyway.

---

## 5. Architecture (Option A)

```
                         ┌─────────────────────────────────────────────┐
   📱 phone camera ─────►│  https://qr.example.com   (Caddy container) │
   📱 in-app scanner     │  • auto-HTTPS (Let's Encrypt)               │
                         │  • security headers, gzip, rate-limit /r/*  │
                         └───────────────────┬─────────────────────────┘
                                             ▼
                         ┌─────────────────────────────────────────────┐
                         │        qrtr app (single Go binary)          │
                         │                                             │
   POST-scan flow ──────►│  GET /r/{slug}                              │
   (target: < 50 ms)     │   1. slug lookup ─► destination URL         │
                         │   2. respond 302 + Cache-Control: no-store ─┼──► 🌐 final URL
                         │   3. async (goroutine after response):      │     (portfolio /
                         │      • geo: IP ──MMDB──► country, city      │      WhatsApp /
                         │      • UA ──uap-core──► device, os, browser │      Maps / form)
                         │      • visitor_id = HMAC(ip‖ua, salt_today) │
                         │      • bot? (preview/crawler list)          │
                         │      • INSERT INTO scan — raw IP DISCARDED  │
                         │                                             │
                         │  /admin   (session auth)  CRUD + QR PNG/SVG │
                         │  /        (session auth)  dashboard         │
                         └───────────────────┬─────────────────────────┘
                                             ▼
                               SQLite (WAL)  data/qrtr.db      ◄── geo.mmdb (monthly update)
                                             ▲
                               Litestream sidecar ──► Backblaze B2 / S3  (continuous backup)
```

### Data model

```sql
CREATE TABLE qr (
  id              TEXT PRIMARY KEY,          -- slug, e.g. 'shop-a-window'
  name            TEXT NOT NULL,             -- human label
  destination_url TEXT NOT NULL,
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE scan (
  id         INTEGER PRIMARY KEY,
  qr_id      TEXT NOT NULL REFERENCES qr(id),
  ts         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  country    TEXT,                            -- ISO code, city-level max
  city       TEXT,
  device     TEXT,                            -- mobile | tablet | desktop | bot
  os         TEXT, browser TEXT,
  visitor_id TEXT,                            -- HMAC(ip‖ua, daily salt); NULL when DNT/GPC
  is_bot     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_scan_qr_ts ON scan(qr_id, ts);

CREATE TABLE daily_stat (                     -- rollup kept after raw retention sweep
  qr_id TEXT NOT NULL, day TEXT NOT NULL,
  scans INTEGER NOT NULL, uniques INTEGER NOT NULL,
  PRIMARY KEY (qr_id, day)
);
```

### Privacy pipeline (the auditable ~50 lines)

1. Client IP comes only from the trusted proxy header (Caddy).
2. Geo lookup happens **in memory** from the local MMDB; only `country` + `city` are persisted.
3. `visitor_id = HMAC-SHA256(salt_today, ip ‖ user_agent)`. `salt_today` is generated at boot and rotated every 24 h, **never written to disk** → yesterday's hashes can never be recomputed or reversed, and cross-day tracking is impossible by construction.
4. Raw IP is **never stored, logged, or sent anywhere** (explicit `log` scrub; Caddy access log uses a `${ip_anonymised}`-style masked field).
5. No cookies → no consent banner in most jurisdictions.
6. DNT/GPC header → log the scan (aggregates stay correct) but store `visitor_id = NULL` (excluded from uniques).
7. Retention job: raw `scan` rows deleted after **90 days** (config), `daily_stat` rollups kept forever.
8. Shipped with `docs/PRIVACY.md` explaining exactly what is collected — link it from your printed material if you want maximal trust.

**Uniques caveat, stated honestly:** exact per-day uniques via `COUNT(DISTINCT visitor_id)`. Weekly/monthly figures are *estimated* as the sum of daily uniques (overcounts people who scan on multiple days) — labelled "estimated" in the UI. Carrier-grade NAT also merges distinct people onto one IP, which UA-mixing only partially offsets. This is the price of the privacy model, and it is the right price.

### Dashboard queries (all of R4)

```sql
-- totals & daily uniques          -- by day/week/month
SELECT COUNT(*), COUNT(DISTINCT visitor_id)
FROM scan WHERE qr_id=? AND ts>=? AND is_bot=0;

SELECT strftime('%Y-%m-%d', ts) d, COUNT(*)      -- week: '%Y-W%W', month: '%Y-%m'
FROM scan WHERE qr_id=? AND is_bot=0 GROUP BY d;

-- by location / device             -- time series feeds Chart.js directly
SELECT country, city, COUNT(*) c FROM scan WHERE qr_id=? AND is_bot=0
GROUP BY country, city ORDER BY c DESC LIMIT 20;
```

---

## 6. Risks & mitigations

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Link-preview bots inflate counts** — sharing the QR URL in WhatsApp/iMessage/Slack triggers server-side preview fetches that are not human scans | Stats become fiction | uap-core bot list + maintained preview-UA denylist (WhatsApp, Slackbot, Applebot, facebookexternalhit…); store `is_bot=1` but exclude from dashboard; report "filtered X bot hits" so it's transparent |
| 2 | **301 redirect cached by browsers** → tracking dies and destinations become uneditable ("dynamic" broken) | Fatal | Only ever 302/307 + `Cache-Control: no-store`; automated test asserts status & headers |
| 3 | **City-level geo is only ~70–80 % accurate** (all free DBs); city's "location" claim overpromises | Wrong expectations | UI says "approximate"; lead with country (very accurate), city as secondary; monthly MMDB update cron (DB-IP ships monthly) |
| 4 | **Carrier NAT merges users**; daily salt inflates weekly uniques | Uniques are estimates either way | Document the estimation method on the dashboard itself; never present uniques as exact |
| 5 | **SQLite = single node**; corruption/disk loss | Data loss | WAL mode, Litestream continuous replication to B2 (~€0.05/mo), documented + *rehearsed* restore |
| 6 | **QR outlives the server** — domain renewal lapses or VPS dies; printed posters become dead ink | Fatal, irreversible | Auto-renew domain 2+ years ahead; Caddy renews TLS; uptime monitor (healthchecks.io free) pages you; whole stack redeploys from `compose + backup` in < 10 min; DR note in README |
| 7 | **GDPR/privacy exposure** | Legal/trust | Design above (no cookies, no raw IP, rotation, retention) + PRIVACY.md; still get a local legal sanity check |
| 8 | **Admin/dashboard compromise** | Data leak, defaced links | bcrypt session auth, random 24-char initial password, optional Caddy basic-auth/IP allowlist in front of `/admin`, per-IP rate limits, SSH keys only + ufw default-deny |
| 9 | **Broken/typo'd destination URLs** quietly kill campaigns | Silent failure | Validate URL at save time (HEAD request, show status); nightly job re-checks all destinations and flags dead ones on the dashboard |
| 10 | **Print physics**: blurry/low-contrast/too-small QR, bad placement | Nobody scans — software never runs | Error-correction level H; SVG output for print shops; ≥ 2.5 cm + quiet zone; field-test with iOS Camera, Android, WeChat under real lighting *before* mass printing |

---

## 7. MVP in 1–2 weeks (Option A)

**Definition of done:** three QRs printed on paper; scanned by iOS Safari, Android Chrome, and one in-app scanner; three *human* scans appear on the dashboard within ~1 s (the WhatsApp preview fetch does not); each redirects to a different destination; destination changed post-print works without reprinting; whole thing deployed with `docker compose up -d`.

| Days | Work package | Output |
|---|---|---|
| 1–2 | Redirect core | `GET /r/{slug}` → 302 + async scan insert; SQLite schema; MMDB geo; UA parse; 30 ms end-to-end |
| 3–4 | Admin CRUD + QR factory | Session login; create/edit slugs with destination validation; PNG+SVG download (EC level H); CSV export of slug→URL for the printer |
| 5–6 | Dashboard v1 | Totals, uniques/day, scans-by-day chart (Chart.js), top countries/cities, device/OS/browser tables; date-range + per-QR filter; bot-toggle |
| 7 | Privacy hardening | Salt rotation, IP scrub (app + Caddy logs), bot denylist, retention job, DNT handling, PRIVACY.md |
| 8–9 | Ship it | Multi-stage Dockerfile (≈20 MB), compose (app + Caddy + Litestream), deploy README; restore drill |
| 10 | Prove it | `hey`/k6 burst test (target ≥ 1k rps on CX22), uptime monitor, security headers check, mobile field test |
| 11–14 | Buffer | Polish from real usage: dark mode, CSV export of stats, empty-states, the inevitable day-9 discovery |

**Explicitly cut from MVP (Phase 2 candidates, only after 4 weeks of real scan data):** multi-user/teams, tags & folders, A/B or time-based destinations, link passwords/expiry, public API tokens, scheduled email reports, per-customer domains, exact weekly-uniques (HLL), PWA/i18n.

### Recurring cost (recommended setup)

| Item | Cost |
|---|---|
| Hetzner CX22 (2 vCPU / 4 GB) — or €0 on Oracle Always-Free ARM | **€3.79–4.35 /mo** |
| Backblaze B2 backups (~1 GB) | ~€0.05 /mo |
| Domain (`qr.example.com` parent) | ~€10–15 /yr |
| **Total** | **≈ €55–70 /yr** |

---

## 8. Decisions log (so future-you remembers)

- **302, never 301** — see Risk 2.
- **SQLite, not Postgres** — workload math in §4.1; swap later behind the store interface if ever needed.
- **Daily-rotating, non-persisted salt** — uniques are *estimated*; that's a feature (privacy), not a bug.
- **db-ip Lite over MaxMind GeoLite2** — CC-BY, no account/license plumbing; either works via the same reader API.
- **No JS build step** — HTMX + vendored Chart.js deletes the entire class of frontend tooling maintenance.
