#!/usr/bin/env bash
# qrtr end-to-end smoke suite — full product verification against a live instance.
# Covers: auth, tenancy isolation, redirect semantics, tracking, bot filtering,
# analytics (groups/heatmap/log), admin/CRM-lite, invites, password flows,
# quotas, bulk creation, CSRF enforcement, rate limiting.
# Usage: BASE=http://localhost:8090 bash scripts/smoke.sh   (fresh DB per run)
set -u
BASE="${BASE:-http://localhost:8080}"
J1="$(mktemp)"; J2="$(mktemp)"; J3="$(mktemp)"
RUN_ID="$(date +%s)"
U1="ci-a-$RUN_ID@qrtr.test"; U2="ci-b-$RUN_ID@qrtr.test"
PW="ci-password-123"
FAIL=0

ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; FAIL=1; }
chk() { if echo "$3" | grep -qF "$2"; then ok "$1"; else bad "$1 (want '$2' in: $(echo "$3" | head -c 140))"; fi; }
csrf() { curl -s -b "$1" "$BASE/" | grep -oE 'name="csrf-token" content="[^"]+"' | head -1 | sed 's/.*content="//; s/"$//'; }
# POST helper: authed POST with csrf. usage: authpost JAR URL key=val key=val...
authpost() { local jar="$1" url="$2"; shift 2
  curl -s -b "$jar" -X POST "$BASE$url" --data-urlencode "csrf=$(csrf "$jar")" "$@"; }

echo "── qrtr smoke @ $BASE  ($RUN_ID)"

chk "healthz" "ok" "$(curl -s "$BASE/healthz")"
chk "anon / bounces to login" "302" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")"

# ── open-signup env: user A registers (pre-auth flow, no CSRF needed)
chk "user A signup" "302" "$(curl -s -o /dev/null -w '%{http_code}' -c "$J1" -X POST "$BASE/signup" \
      --data-urlencode "email=$U1" --data-urlencode "password=$PW" --data-urlencode "password2=$PW")"
chk "user A sees dashboard" "Your QR campaigns" "$(curl -s -b "$J1" "$BASE/")"

# ── CSRF enforcement: authed POST without token must 403
chk "campaign create WITHOUT csrf → 403" "403" \
    "$(curl -s -o /dev/null -w '%{http_code}' -b "$J1" -X POST "$BASE/campaigns/new" \
        --data-urlencode "name=csrf probe" --data-urlencode "destination_url=https://example.com/csrf")"

LOC="$(authpost "$J1" /campaigns/new -o /dev/null -w '%{redirect_url}' \
        --data-urlencode "name=CI campaign" --data-urlencode "destination_url=https://example.com/dest-ci")"
CID="${LOC##*/}"
case "$CID" in */*|"") bad "campaign create with csrf (got '$LOC')";; *)
  ok "campaign create with csrf ($CID)"
  chk "detail renders" "Scans over time" "$(curl -s -b "$J1" "$BASE/campaigns/$CID")"

  # ── redirect hot path + tracking
  H="$(curl -s -D - -o /dev/null -A "Mozilla/5.0 (Linux; Android 14) Chrome/126.0 Mobile Safari/537.36" "$BASE/c/$CID")"
  chk "scan redirects 302" "302" "$(echo "$H" | head -1)"
  chk "redirect target" "ocation: https://example.com/dest-ci" "$H"
  chk "no-store cache control" "no-store" "$H"
  curl -s -o /dev/null -A "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1" "$BASE/c/$CID"
  curl -s -o /dev/null -A "WhatsApp/2.24.1 A" "$BASE/c/$CID"
  sleep 2
  DET="$(curl -s -b "$J1" "$BASE/campaigns/$CID")"
  chk "2 human scans counted"   '>2</span><span class="statlbl">scans · 30d' "$DET"
  chk "est. uniques counted"    '>2</span><span class="statlbl">est. uniques · 30d' "$DET"
  chk "bot preview filtered"    '>1</span><span class="statlbl">bot hits filtered' "$DET"

  # ── analytics views
  chk "group=month buckets" "$(date -u +%Y-%m)" "$(curl -s -b "$J1" "$BASE/campaigns/$CID?days=30&group=month")"
  chk "group=week accepted (200)" "200" "$(curl -s -o /dev/null -w '%{http_code}' -b "$J1" "$BASE/campaigns/$CID?days=30&group=week")"
  chk "heatmap renders" "Scan heatmap" "$DET"
  chk "heatmap has max-intensity cell" "rgba(109,94,240,1.00)" "$DET"
  SL="$(curl -s -b "$J1" "$BASE/campaigns/$CID/scans")"
  chk "full scan log (Page 1)" "Page 1" "$SL"
  chk "scan log tags bot rows" 'pill off">bot' "$SL"
  chk "scan log tags human rows" 'pill on">human' "$SL"

  # ── misc endpoints
  chk "404 for unknown code" "404" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/c/nope99")"
  chk "QR PNG served" "image/png" "$(curl -s -o /dev/null -w '%{content_type}' -b "$J1" "$BASE/campaigns/$CID/qr.png")"
  chk "QR SVG served" "image/svg" "$(curl -s -o /dev/null -w '%{content_type}' -b "$J1" "$BASE/campaigns/$CID/qr.svg")"
  chk "CSV export" "ts_utc,country,city" "$(curl -s -b "$J1" "$BASE/campaigns/$CID/scans.csv")"

  # ── tenancy isolation
  curl -s -o /dev/null -c "$J2" -X POST "$BASE/signup" \
    --data-urlencode "email=$U2" --data-urlencode "password=$PW" --data-urlencode "password2=$PW"
  chk "user B cannot read A's campaign" "404" "$(curl -s -o /dev/null -w '%{http_code}' -b "$J2" "$BASE/campaigns/$CID")"
  chk "user B cannot fetch A's QR" "404" "$(curl -s -o /dev/null -w '%{http_code}' -b "$J2" "$BASE/campaigns/$CID/qr.png")"

  # ── admin (CRM-lite): panel, guards, plan flip, reset password
  ADM="$(curl -s -b "$J1" "$BASE/admin/")"
  chk "admin panel loads for user A (auto-admin)" "All users" "$ADM"
  chk "non-admin blocked from /admin" "403" "$(curl -s -o /dev/null -w '%{http_code}' -b "$J2" "$BASE/admin/")"
  chk "non-admin cannot flip plans" "403" "$(authpost "$J2" /admin/users/whoever/plan -o /dev/null -w '%{http_code}' --data-urlencode "plan=pro")"
  UID_B="$(echo "$ADM" | grep -oE '/admin/users/[^/]+/plan' | tail -1 | sed 's#/admin/users/##; s#/plan##')"
  authpost "$J1" "/admin/users/$UID_B/plan" -o /dev/null --data-urlencode "plan=pro"
  chk "admin plan flip sticks (B -> pro)" 'value="pro" selected' "$(curl -s -b "$J1" "$BASE/admin/")"

  # ── invites + password flows
  U3="ci-c-$RUN_ID@qrtr.test"
  chk "admin invites user C" "302" "$(authpost "$J1" /admin/users/add -o /dev/null -w '%{http_code}' --data-urlencode "email=$U3" --data-urlencode "password=$PW")"
  chk "invited user C can log in" "302" "$(curl -s -o /dev/null -w '%{http_code}' -c "$J3" -X POST "$BASE/login" --data-urlencode "email=$U3" --data-urlencode "password=$PW")"
  chk "user C sees dashboard" "Your QR campaigns" "$(curl -s -b "$J3" "$BASE/")"
  chk "user C changes password" "302" "$(authpost "$J3" /account -o /dev/null -w '%{http_code}' --data-urlencode "current_password=$PW" --data-urlencode "password=${PW}x" --data-urlencode "password2=${PW}x")"
  chk "user C logs in with NEW password" "302" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/login" --data-urlencode "email=$U3" --data-urlencode "password=${PW}x")"
  UID_C="$(curl -s -b "$J1" "$BASE/admin/" | grep -oE '/admin/users/[^/]+/reset' | tail -1 | sed 's#/admin/users/##; s#/reset##')"
  authpost "$J1" "/admin/users/$UID_C/reset" -c "$J1" -o /dev/null
  TMPW="$(curl -s -b "$J1" "$BASE/admin/" | grep -oE 'temporary password: [A-Za-z0-9_-]+' | head -1 | awk '{print $NF}')"
  chk "admin reset produced temp password" "1" "$([ -n "$TMPW" ] && echo 1 || echo 0)"
  chk "user C logs in with reset temp" "302" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/login" --data-urlencode "email=$U3" --data-urlencode "password=$TMPW")"

  # ── bulk creation (user B, pro plan: 50 campaign cap)
  BULKP="$(printf 'Bulk One,https://example.com/b1\nBulk Two,https://example.com/b2')"
  BULK="$(authpost "$J2" /campaigns/bulk --data-urlencode "csv=$BULKP")"
  NC="$(echo "$BULK" | grep -oE '/c/[A-Za-z0-9]{6}' | sort -u | sed 's#/c/##')"
  chk "bulk created 2 campaigns" "2" "$(echo "$NC" | grep -c .)"
  ZCT="$(authpost "$J2" /campaigns/qr.zip -o /tmp/qz.zip -w '%{content_type}' --data-urlencode "codes=$(echo "$NC" | paste -sd,)")"
  chk "zip content-type" "application/zip" "$ZCT"
  chk "zip magic bytes" "PK" "$(head -c 2 /tmp/qz.zip)"

  # ── quota (user A, free plan: CID + 2 more allowed, 4th refused)
  authpost "$J1" /campaigns/new -o /dev/null --data-urlencode "name=q2" --data-urlencode "destination_url=https://example.com/2" >/dev/null
  authpost "$J1" /campaigns/new -o /dev/null --data-urlencode "name=q3" --data-urlencode "destination_url=https://example.com/3" >/dev/null
  Q4="$(authpost "$J1" /campaigns/new -o /dev/null -w '%{redirect_url}' --data-urlencode "name=q4" --data-urlencode "destination_url=https://example.com/4")"
  chk "4th campaign refused (quota)" "$BASE/" "${Q4%/}/"

  # logout then rate limiting (login limiter must be LAST — it poisons the IP window)
  chk "logout" "302" "$(authpost "$J1" /logout -o /dev/null -w '%{http_code}')"
  N429=0
  for i in $(seq 12); do
    C="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/login" \
         --data-urlencode "email=nobody-$RUN_ID@qrtr.test" --data-urlencode "password=wrong")"
    [ "$C" = "429" ] && N429=$((N429+1))
  done
  chk "login rate limit trips (429)" "1" "$([ $N429 -ge 1 ] && echo 1 || echo 0)"
;; esac

echo "── result: $([ "$FAIL" = 0 ] && echo ALL GREEN || echo FAILURES)"
exit "$FAIL"
