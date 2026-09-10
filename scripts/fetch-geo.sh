#!/bin/sh
# Best-effort download of the free db-ip Lite city database (CC BY 4.0).
# Tries current month then previous. Missing/blocked → app runs with geo="Unknown".
# DB-IP attribution: IP geolocation by DB-IP, https://db-ip.com
set -u

DATA_DIR="${DATA_DIR:-./data}"
DEST="$DATA_DIR/geo.mmdb"
[ -s "$DEST" ] && { echo "[geo] already present"; exit 0; }
mkdir -p "$DATA_DIR"

THIS_MONTH="$(date -u +%Y-%m)"
LAST_MONTH="$(date -u -d "$(date -u +%Y-%m-01) -1 day" +%Y-%m 2>/dev/null || date -u -v-1m +%Y-%m)"

for ym in "$THIS_MONTH" "$LAST_MONTH"; do
  url="https://download.db-ip.com/free/dbip-city-lite-$ym.mmdb.gz"
  echo "[geo] trying $url"
  if curl -fsSL --max-time 120 "$url" -o "$DEST.gz" 2>/dev/null \
     && gunzip -f "$DEST.gz" \
     && [ "$(stat -c%s "$DEST" 2>/dev/null || stat -f%z "$DEST")" -gt 2000000 ]; then
    echo "[geo] installed $DEST"
    exit 0
  fi
  rm -f "$DEST.gz" "$DEST"
done

echo "[geo] download failed (blocked?) — continuing without geolocation"
exit 0
