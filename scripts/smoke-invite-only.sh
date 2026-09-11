#!/usr/bin/env bash
# Invite-only bootstrap regression: with ALLOW_SIGNUP=0 on a FRESH database,
# the first-ever signup (owner) must succeed, every later signup must be
# refused, and the owner's login keeps working.
# Usage: BASE=http://localhost:8091 bash scripts/smoke-invite-only.sh
set -u
BASE="${BASE:-http://localhost:8091}"
J="$(mktemp)"; FAIL=0
RUN_ID="$(date +%s)"
OWNER="owner-$RUN_ID@qrtr.test"; PW="owner-pass-123"

ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; FAIL=1; }
chk() { if echo "$3" | grep -qF "$2"; then ok "$1"; else bad "$1 (want '$2' in: $(echo "$3" | head -c 120))"; fi; }

echo "── invite-only smoke @ $BASE"
chk "healthz" "ok" "$(curl -s "$BASE/healthz")"

chk "bootstrap signup (owner) allowed" "302" \
    "$(curl -s -o /dev/null -w '%{http_code}' -c "$J" -X POST "$BASE/signup" \
        --data-urlencode "email=$OWNER" --data-urlencode "password=$PW" --data-urlencode "password2=$PW")"
chk "owner lands on dashboard" "Your QR campaigns" "$(curl -s -b "$J" "$BASE/")"
chk "owner is auto-admin" "All users" "$(curl -s -b "$J" "$BASE/admin/")"

LOC="$(curl -s -o /dev/null -w '%{redirect_url}' -X POST "$BASE/signup" \
        --data-urlencode "email=stranger-$RUN_ID@qrtr.test" \
        --data-urlencode "password=$PW" --data-urlencode "password2=$PW")"
chk "second signup refused → login" "/login" "$LOC"
chk "login page explains invite-only" "nvite-only" "$(curl -s "$BASE/login")"  # matches 'invite-only' and 'Invite-only'

chk "owner can still log in" "302" \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/login" \
        --data-urlencode "email=$OWNER" --data-urlencode "password=$PW")"

echo "── result: $([ "$FAIL" = 0 ] && echo ALL GREEN || echo FAILURES)"
exit "$FAIL"
