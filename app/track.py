"""Scan tracking: User-Agent parsing, bot detection, optional MMDB geo, and the
privacy pipeline (docs/DESIGN.md §5): raw IPs are used in-memory only — for a
geo lookup and an HMAC with a daily-rotating salt that is never persisted —
then discarded. Nothing in this module ever writes an IP anywhere."""
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
from datetime import date

# Preview/crawler agents that fetch links without a human scanning anything.
BOT_MARKERS = (
    "whatsapp", "slackbot", "applebot", "facebookexternalhit", "facebot",
    "twitterbot", "discordbot", "telegrambot", "googlebot", "bingbot",
    "slurp", "duckduckbot", "baiduspider", "yandexbot", "pinterest",
    "linkedinbot", "skypeuripreview", "embedly", "outbrain", "vkshare",
    "ia_archiver", "crawler", "spider", "bot/", "preview", "curl",
    "wget", "python-requests", "headless", "lighthouse",
)


def is_bot_ua(ua: str) -> bool:
    low = ua.lower()
    return any(m in low for m in BOT_MARKERS)


def parse_ua(ua: str) -> dict:
    """Compact UA parser covering what printed-QR traffic actually is: mobile
    browsers, in-app scanners, and the mess above. Unknowns degrade honestly."""
    low = ua.lower()
    if not ua:
        return {"device": "desktop", "os": "Unknown", "browser": "Unknown", "bot": False}
    bot = is_bot_ua(ua)

    if bot:
        device = "bot"
    elif "ipad" in low or ("tablet" in low and "mobi" not in low):
        device = "tablet"
    elif "mobi" in low or "iphone" in low or "ipod" in low or "android" in low:
        device = "mobile"
    else:
        device = "desktop"

    if "windows nt" in low:
        os_ = "Windows"
    elif "android" in low:
        os_ = "Android"
    elif "cros" in low:
        os_ = "ChromeOS"
    elif "iphone" in low or "ipod" in low:
        os_ = "iOS"
    elif "ipad" in low:
        os_ = "iPadOS"
    elif "mac os x" in low or "macintosh" in low:
        os_ = "macOS"
    elif "linux" in low:
        os_ = "Linux"
    else:
        os_ = "Other"

    if "micromessenger" in low:
        browser = "WeChat"
    elif "instagram" in low:
        browser = "Instagram"
    elif "fbav" in low or "fban" in low:
        browser = "Facebook"
    elif "line/" in low:
        browser = "LINE"
    elif "edg/" in low or "edga/" in low or "edgios/" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "samsungbrowser" in low:
        browser = "Samsung Internet"
    elif "yabrowser" in low:
        browser = "Yandex"
    elif "crios/" in low:
        browser = "Chrome (iOS)"
    elif "fxios/" in low:
        browser = "Firefox (iOS)"
    elif "chrome/" in low and "; wv" in low:
        browser = "Android WebView"
    elif "chrome/" in low:
        browser = "Chrome"
    elif "firefox/" in low:
        browser = "Firefox"
    elif "safari/" in low and "version/" in low:
        browser = "Safari"
    elif "safari/" in low:
        browser = "Safari"
    elif bot:
        browser = "Bot"
    else:
        browser = "Other"

    return {"device": device, "os": os_, "browser": browser, "bot": bot}


class Geo:
    """Optional MMDB-backed resolver. If the file or library is missing, every
    lookup returns ('', '') and stats simply show 'Unknown' — geo is best-effort
    by design (docs/DESIGN.md risk #3). Private/reserved IPs never hit the DB."""

    def __init__(self, path: str):
        self.reader = None
        if path and os.path.exists(path):
            try:
                import maxminddb
                self.reader = maxminddb.open_database(path)
            except Exception as e:  # corrupt file, missing lib — degrade, don't crash
                print(f"[geo] disabled: {e}")

    def lookup(self, ip: str) -> tuple[str, str]:
        if not self.reader or not ip:
            return "", ""
        try:
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_reserved:
                return "", ""
            data = self.reader.get(ip) or {}
            country = (data.get("country") or {}).get("iso_code", "") or ""
            city = ((data.get("city") or {}).get("names") or {}).get("en", "") or ""
            return country, city
        except (ValueError, Exception):
            return "", ""


class Salter:
    """Daily-rotating HMAC key held in memory only. Rotation on first use after
    midnight UTC; restarting the app also rotates it. Yesterday's visitor_ids
    can never be recomputed — that is the privacy feature (design doc §5.3)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._day: date | None = None
        self._salt = b""

    def _current(self) -> bytes:
        today = date.today()
        with self._lock:
            if self._day != today:
                self._salt = secrets.token_bytes(32)
                self._day = today
            return self._salt

    def visitor_id(self, ip: str, ua: str) -> str:
        msg = f"{ip}|{ua}".encode(errors="replace")
        return hmac.new(self._current(), msg, hashlib.sha256).hexdigest()[:32]


class Tracker:
    def __init__(self, geo_path: str):
        self.geo = Geo(geo_path)
        self.salt = Salter()

    def build_scan(self, ip: str, ua: str, dnt: bool) -> dict:
        parsed = parse_ua(ua)
        country, city = ("", "") if parsed["bot"] else self.geo.lookup(ip)
        return {
            "country": country, "city": city,
            "device": parsed["device"], "os": parsed["os"], "browser": parsed["browser"],
            "is_bot": parsed["bot"],
            # DNT/GPC: count the scan, but grant no identity (design doc §5.6)
            "visitor_id": None if dnt else self.salt.visitor_id(ip, ua),
        }
