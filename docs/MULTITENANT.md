# qrtr v2 — Multi-tenant SaaS Pivot

**Status:** Implemented (reference implementation) · **Date:** 2026-09-11 · **Supersedes:** parts of [DESIGN.md](DESIGN.md) (v1 was single-tenant, personal use).

> **Implementation note (2026-09-11):** the first runnable build ships as **Python 3.11 + Flask + SQLite + waitress + segno** (zero-compiler stack, see `app/`), because the build sandbox had no Go toolchain and the priority was a working, verifiable product. All MG-A invariants are language-independent and are implemented unchanged (§3 invariants → `app/store.py`, `app/scanlog.py`; privacy pipeline → `app/track.py`). The Go static-binary variant remains the documented scale-up/hot-path option; `deploy/` runs either way via Docker.

**New goal:** qrtr becomes a sellable, multi-tenant SaaS — users sign up, create dynamic QRs, view analytics. Still: as-free-as-possible, open-source, privacy-respecting.

---

## 0. Review of the externally-proposed Cloudflare plan

The plan (Workers + D1 + Pages + Supabase) is directionally sane but has **7 specific defects** this document corrects:

| # | Defect in that plan | Correction |
|---|---|---|
| 1 | Claims "self-hosted" while building entirely on rented Cloudflare PaaS | Decide which requirement is real: **data sovereignty** (→ VPS) or **"cheap + I own the code"** (→ CF is fine, accepts lock-in). Cannot have both |
| 2 | Stores `scans` in D1 | Scan events are append-only time series; the canonical CF pattern is **Workers Analytics Engine** (write datapoints, query via SQL API, per-tenant tags). D1 = control plane only (users, campaigns). Verify AE free-tier availability — historically tied to Workers Paid ($5/mo) [†](https://costbench.com/software/cloud-infrastructure/cloudflare-pages-workers/free-plan/) |
| 3 | Auth in Supabase, data in D1 | Split-brain: two systems of record, and Postgres RLS cannot protect D1 rows. **Pick ONE system of record**; auth must live next to the data |
| 4 | Plans/billing "later" | Quota fields (`plan`, usage counters) belong in the schema **day 1**; retrofitting limits onto live tenants is the classic SaaS migration pain |
| 5 | Custom domains listed as a feature with no cost model | Cloudflare for SaaS: 100 hostnames free, then **$0.10/hostname/mo** [†](https://blog.cloudflare.com/waf-for-saas/). Self-hosted equivalent: **Caddy on-demand TLS — free at any count** |
| 6 | No stance on quota enforcement behavior | **Invariant: redirects NEVER fail.** Quota breach / lapsed subscription → stop *logging*, keep *redirecting*. A printed QR outlives every billing state |
| 7 | Short URLs shaped `/u/<user>/<campaign>` | Path length = QR density = harder printing. Use a **global 5–6 char base62 code**: `go.qrtr.app/c/a3K9x`. Vanity paths are a paid feature, not the default |

---

## 1. What survives from v1 (unchanged)

- Privacy pipeline: no raw IP, in-memory geo, `HMAC(ip‖ua, daily-rotating non-persisted salt)` → visitor_id, DNT→NULL, 90-day raw retention + `daily_stat` rollups, no cookies.
- Redirect discipline: 302/307 + `Cache-Control: no-store`, never 301; CI test asserts it.
- Link-preview/bot denylist; `is_bot=1` stored but excluded from stats.
- Print physics: EC level H, SVG for print shops, ≥ 2.5 cm + quiet zone.
- Deployment skeleton: Docker + Caddy auto-HTTPS + Litestream backups.

---

## 2. The two coherent paths

| | **MG-A: Multi-tenant VPS** (evolve v1 Option A) | **MG-B: Cloudflare edge SaaS** (corrected plan) |
|---|---|---|
| Stack | Go + SQLite + Caddy + HTMX/Chart.js **+ auth, plans, quotas** | Workers (Hono) redirect + Workers KV cache + **Analytics Engine** events + D1 control plane + better-auth + Pages dashboard + R2 exports |
| Self-hosted | ✅ truly | ❌ (owned code, rented runtime) |
| Cost @ 0 → 100 customers | €0 (Oracle free ARM) → €3.79 (CX22) | $0 until ~100k req/day free cap; then $5/mo + usage; custom domains $0.10/ea after 100 |
| Time to MVP | **~3–4 weeks** (adds tenancy to an already-specced v1 core) | ~4–6 weeks (tenancy **plus** learning Workers/D1/AE/Wrangler simultaneously) |
| Ops burden | One box, one file backup | Zero servers, but 5 CF primitives to wire and monitor |
| Lock-in / exit | None | High (KV, AE, D1, Pages APIs are CF-specific) |
| Scale ceiling | ~1M+ scans/day on €4 box → then move hot path | Practically unbounded |

**Recommendation: MG-A now, with an edge-ready hot path.** The redirect service is stateless by design — it is the *only* component that benefits from edge scale, and it can be re-implemented as a Worker in a weekend when (if) growth demands it. Control plane, auth, dashboard, and billing stay boring on the VPS. **Flip to MG-B only if:** sustained >1M scans/day, or >50 paying customers and ops time becomes the constraint, or the team goes TS-only.

---

## 3. MG-A architecture delta

```
                 ┌─ app.qrtr.app ─► [Caddy] ──► dashboard + auth + billing webhooks
                 │                                    │
                 │                                    ▼
 scanner phone ──┴─ go.qrtr.app ─► [Caddy] ──► qrtr app (Go)
                                              GET /c/{code}  (PUBLIC, no auth, cached lookup)
                                                ├─ 302 + no-store ──────────────► destination
                                                └─ async: geo / UA / HMAC(ip,salt) / bot?
                                                       └─ if plan.quota_ok → INSERT scan
                                                          else → skip log (redirect unaffected!)
                                              /api/*  (session auth, tenancy-scoped store)
                                              /billing/webhook (Razorpay/Stripe signature verify)
                                                       │
                                              SQLite (WAL) ◄── Litestream ──► B2
```

**Three invariants, enforced by tests:**

1. **Tenancy is a store-layer guarantee.** Every query signature takes `user_id`; there is no code path that returns campaigns/scans without it. Security test suite: create 2 users, assert cross-access = 404/403.
2. **The redirect hot path is unauthenticated, in-memory-cached, and quota-independent.** Lookup happens against a tiny process-local cache (code → destination, active) refreshed on write; SQLite is only a fallback. Billing/quota/login state can never 404 or 429 a printed QR.
3. **Quotas decay softly.** Campaign creation blocked at plan limit (hard). Scan cap: over-limit months stop logging + show dashboard banner ("upgrade to resume analytics"); redirects continue.

### Schema delta (additions to v1)

```sql
CREATE TABLE user (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,            -- argon2id
  plan TEXT NOT NULL DEFAULT 'free',      -- free | pro | business
  email_verified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE session (                    -- httponly cookie, 30d sliding
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES user(id),
  expires_at TEXT NOT NULL
);
CREATE TABLE plan_quota (                 -- seeded rows; single source of truth for limits
  plan TEXT PRIMARY KEY,
  max_campaigns INTEGER NOT NULL,         -- free: 3, pro: 50, business: 500
  max_scans_month INTEGER NOT NULL        -- free: 5k, pro: 200k, business: 2M
);
-- v1 `qr` becomes `campaign`: + user_id FK, `id` = global 5-6 char base62 code
CREATE INDEX idx_campaign_user ON campaign(user_id);
CREATE TABLE usage_counter (              -- maintained by nightly job from scan
  user_id TEXT NOT NULL, month TEXT NOT NULL,      -- '2026-10'
  scans INTEGER NOT NULL, PRIMARY KEY (user_id, month)
);
-- Phase "billing-on": subscription(id, user_id, provider, provider_sub_id, plan,
--   status, current_period_end) + invoice stubs. Schema now, Razorpay sandbox in Wk 3.
```

### Folder structure

```
cmd/qrtr/main.go
internal/
  httpapi/    # routes: redirect.go (public), auth.go, campaigns.go, dashboard.go, billing.go
  store/      # Store interface + sqlite impl; migrations/ embedded (go:embed)
  authn/      # argon2id, sessions, middleware, (later) OAuth
  track/      # geo MMDB, uap UA parse, salt rotation, botlist, HMAC visitor_id
  quota/      # plan lookups, usage job, soft-decay logic
  billing/    # provider interface; razorpay impl (webhook verify, plan flip)
  qrcode/     # PNG/SVG, EC-H, batch export
web/templates/ web/static/   # HTMX + Chart.js, zero build step
deploy/{Dockerfile, docker-compose.yml, Caddyfile}
docs/                         # DESIGN.md, MULTITENANT.md, PRIVACY.md
```

**Billing:** Razorpay first (India: UPI/cards, your market), Stripe behind the same provider interface for international. **Email:** Resend/Brevo free tier — verification + quota warnings only. **Admin alerts:** Telegram bot (signup, quota breach, error rate) — free, and yes, that suggestion from the other plan is good.

**Pricing placeholders** (validate with first 5 customers, don't over-think now): Free ₹0 — 3 campaigns / 5k scans-mo · Pro ₹299/mo — 50 / 200k · Business ₹999/mo — 500 / 2M + custom domain (Caddy on-demand TLS makes this cost us ₹0, vs $0.10/domain on CF).

---

## 4. MVP plan — 4 weeks

| Week | Deliverable | Exit test |
|---|---|---|
| **1** | v1 core (redirect, tracking, privacy pipeline, schema) + user signup/login (argon2id, sessions, email verify) | Unauthenticated scan logged + redirected; two users created |
| **2** | Tenancy: campaign CRUD scoped per user, per-user dashboard (v1's 5 queries + `WHERE user_id`), QR PNG/SVG download, `plan_quota` + campaign-count enforcement | User B cannot read User A's anything (automated test) |
| **3** | Usage counter job, soft-decay banner, Razorpay **sandbox** upgrade flow + signature-verified webhook flips plan, rate limits, Telegram admin alerts | Sandbox payment → plan flips → limits raise; over-quota month: logs stop, redirects don't |
| **4** | Hardening & launch: redirect-never-dies + cross-tenant test suite, restore drill, load test (≥1k rps CX22), PRIVACY.md + terms skeleton, onboard 5 manual beta users | 5 real QRs printed by beta users, live for a week |

**Cut from MVP:** teams/roles, custom domains, white-label, public API, OAuth logins, UTM builder, Analytics dashboards beyond the five views.

---

## 5. Decisions log (delta over v1)

- Tenancy in the **store layer**, not middleware vibes — cross-tenant bugs are existential for a paid product.
- **Redirect outlives billing** — invariant 2; the thing we sell is *analytics*, the thing that must never break is the *link*.
- Global short code, not `/u/user/campaign` — QR density is physics.
- Razorpay-before-Stripe — seller is IN-based; UPI converts.
- Stay on **VPS until the flip triggers in §2 fire** — then the stateless hot path, and only it, moves to Workers.
