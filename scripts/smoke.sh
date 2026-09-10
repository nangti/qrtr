#!/usr/bin/env bash
# qrtr end-to-end smoke test — runs against a live instance.
# Usage: BASE=http://localhost:8090 bash scripts/smoke.sh
# Requires a fresh-ish DB (uses unique emails per run). Exit 1 on any failure.
set -u
BASE="${BASE:-http://localhost:8080}"
J1="$(mktemp)"; J2="$(mktemp)"
RUN_ID="$(date +%s)"
U1="ci-a-$RUN_ID@qrtr.test"; U2="ci-b-$RUN_ID@qrtr.test"
PW="ci-password-123"
FAIL=0

ok()   { echo "  PASS  $1"; }
bad()  { echo "  FAIL  $1"; FAIL=1; }
chk()  { # chk <desc> <expected-substring> <haystack>
  if echo "$3" | grep -qF "$2"; then ok "$1"; else bad "$1 (want '$2' in: $(echo "$3" | head -c 160))"; fi; }

echo "── qrtr smoke @ $BASE"

chk "healthz" "ok" "$(curl -s "$BASE/healthz")"
chk "anon / bounces to login" "302" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")"

R="$(curl -s -o /dev/null -w '%{http_code}' -c "$J1" -X POST "$BASE/signup" \
      --data-urlencode "email=$U1" --data-urlencode "password=$PW" --data-urlencode "password2=$PW")"
chk "user A signup" "302" "$R"
chk "user A sees dashboard" "Your QR campaigns" "$(curl -s -b "$J1" "$BASE/")"

LOC="$(curl -s -o /dev/null -w '%{redirect_url}' -b "$J1" -X POST "$BASE/campaigns/new" \
        --data-urlencode "name=CI campaign" --data-urlencode "destination_url=https://example.com/dest-ci")"
CID="${LOC##*/}"
case "$CID" in */*|"") bad "campaign create (no code, got '$LOC')";; *)
  ok "campaign create ($CID)"
  chk "detail renders" "Scans over time" "$(curl -s -b "$J1" "$BASE/campaigns/$CID")"

  H="$(curl -s -D - -o /dev/null -A "Mozilla/5.0 (Linux; Android 14) Chrome/126.0 Mobile Safari/537.36" "$BASE/c/$CID")"
  chk "scan redirects 302" "302" "$(echo "$H" | head -1)"
  chk "redirect target" "ocation: https://example.com/dest-ci" "$H"
  chk "no-store cache control" "no-store" "$H"

  curl -s -o /dev/null -A "WhatsApp/2.24.1 A" "$BASE/c/$CID"           # preview bot
  sleep 2                                                              # async workers flush
  DET="$(curl -s -b "$J1" "$BASE/campaigns/$CID")"
  chk "1 human scan counted"    '>1</span><span class="statlbl">scans · 30d' "$DET"
  chk "bot preview filtered"    '>1</span><span class="statlbl">bot hits filtered' "$DET"
  chk "404 for unknown code" "404" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/c/nope99")"
  chk "QR PNG served" "image/png" "$(curl -s -o /dev/null -w '%{content_type}' -b "$J1" "$BASE/campaigns/$CID/qr.png")"
  chk "QR SVG served" "image/svg" "$(curl -s -o /dev/null -w '%{content_type}' -b "$J1" "$BASE/campaigns/$CID/qr.svg")"
  chk "CSV export" "ts_utc,country,city" "$(curl -s -b "$J1" "$BASE/campaigns/$CID/scans.csv")"

  # tenancy isolation
  curl -s -o /dev/null -c "$J2" -X POST "$BASE/signup" \
    --data-urlencode "email=$U2" --data-urlencode "password=$PW" --data-urlencode "password2=$PW"
  chk "user B cannot read A's campaign" "404" \
      "$(curl -s -o /dev/null -w '%{http_code}' -b "$J2" "$BASE/campaigns/$CID")"
  chk "user B cannot fetch A's QR" "404" \
      "$(curl -s -o /dev/null -w '%{http_code}' -b "$J2" "$BASE/campaigns/$CID/qr.png")"

  # quota (free plan = 3): CID already 1; create 2 more, 4th refuses
  curl -s -o /dev/null -b "$J1" -X POST "$BASE/campaigns/new" --data-urlencode "name=q2" --data-urlencode "destination_url=https://example.com/2"
  curl -s -o /dev/null -b "$J1" -X POST "$BASE/campaigns/new" --data-urlencode "name=q3" --data-urlencode "destination_url=https://example.com/3"
  Q4="$(curl -s -o /dev/null -w '%{redirect_url}' -b "$J1" -X POST "$BASE/campaigns/new" --data-urlencode "name=q4" --data-urlencode "destination_url=https://example.com/4")"
  chk "4th campaign refused (quota)" "$BASE/" "${Q4%/}/"

  R="$(curl -s -o /dev/null -w '%{http_code}' -b "$J1" -X POST "$BASE/logout")"
  chk "logout" "302" "$R"
;; esac

echo "── result: $([ "$FAIL" = 0 ] && echo ALL GREEN || echo FAILURES)"
exit "$FAIL"
