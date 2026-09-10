"""Runtime configuration via environment variables. Every default is safe for
local dev; the shipped docker-compose sets the production values explicitly."""
import os


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    DATA_DIR = os.environ.get("DATA_DIR", "./data")
    DB_NAME = os.environ.get("DB_NAME", "qrtr.db")

    # Public base URL used inside generated QR codes. When empty we derive it
    # from the incoming request (works behind the preview proxy). Set this to
    # https://go.yourdomain.in in production so printed QRs are stable.
    BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

    # Cookies: Secure must be 1 whenever traffic is HTTPS (it is, behind Caddy
    # or the Arena preview). Set COOKIE_SECURE=0 only for plain-http local dev.
    COOKIE_SECURE = _flag("COOKIE_SECURE", "1")

    # Open self-service signup. Set to 0 to run invite-only (create users via CLI).
    ALLOW_SIGNUP = _flag("ALLOW_SIGNUP", "1")

    # We always run behind a reverse proxy (Caddy / preview edge) that sets
    # X-Forwarded-For. If you ever expose the app directly, set this to 0.
    TRUST_PROXY = _flag("TRUST_PROXY", "1")

    GEO_MMDB = os.environ.get("GEO_MMDB", "")  # default: <DATA_DIR>/geo.mmdb
    SCAN_RETENTION_DAYS = int(os.environ.get("SCAN_RETENTION_DAYS", "90"))
    SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
    CODE_LENGTH = int(os.environ.get("CODE_LENGTH", "6"))
