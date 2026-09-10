# qrtr — privacy design (operator-facing)

This document is what you can show a customer, a regulator, or a curious stranger.
The in-app `/privacy` page is the short public version of the same facts.

## What a scan records

| Field | How | Precision |
|---|---|---|
| Time | server clock, UTC | second |
| Which QR | the short code itself | exact |
| Country / city | local MMDB file (db-ip Lite, CC BY 4.0), lookup **in memory** | country: reliable · city: approximate |
| Device / OS / browser | parsed from User-Agent | class-level (e.g. "mobile / Android / Chrome") |
| Visitor pseudonym | `HMAC-SHA256(IP ‖ User-Agent, salt_today)` | identifies "same person, same device, same day" only |
| Bot flag | UA denylist (WhatsApp/iMessage previews, crawlers…) | excluded from all stats |

## What is deliberately impossible

- **Recovering an IP.** Raw IPs are used for the geo lookup and the HMAC, then discarded. The salt
  lives only in RAM, rotates every 24 h, and is replaced on restart — yesterday's pseudonyms cannot
  be recomputed even with full server access.
- **Tracking a person across days.** Rotation makes today's pseudonym unlinkable to yesterday's.
- **Tracking via cookies.** There are none for scanners; the only cookie is the dashboard login session.
- **Exact GPS.** Never requested. Browsers would require a JS permission prompt; we never run JS on
  the scan path — it's a plain 302 redirect.

## Choice & retention

- **DNT / Global Privacy Control** → scan is counted, pseudonym is not created (`visitor_id = NULL`).
- **Raw scan rows are deleted after 90 days** (`SCAN_RETENTION_DAYS`), replaced by per-day aggregate
  counts (scans/uniques per campaign) that contain no pseudonyms.
- **Geo failure mode is "Unknown"**, never "guess harder."

## Weekly/monthly uniques are estimates

Per-day uniques are `COUNT(DISTINCT visitor_id)` — accurate *for that day*. Weekly/monthly figures
are labelled estimates: a person scanning on 3 days counts as 3 (by construction, not by bug).
Carrier NAT additionally merges distinct people sharing an IP. This is the deliberate price of the
privacy model (docs/DESIGN.md §5).

## Compliance notes

- No cookies + no raw IPs + pseudonymized, coarse analytics is designed to fall comfortably inside
  legitimate-interest analytics in most jurisdictions (no consent banner needed) — **get a local
  legal sanity check before selling**, especially in the EU.
- Multi-tenant isolation is a store-layer invariant: every campaign/scan query is filtered by
  `user_id`; cross-tenant access is tested to return 404.
