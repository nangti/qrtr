"""Trusted client-IP resolution — shared by the redirect hot path, the
rate limiter, and the privacy pipeline. TRUST_PROXY gates X-Forwarded-For:
only enable it behind a proxy that itself sets/strips that header."""
from flask import request

from .config import Config


def client_ip() -> str:
    if Config.TRUST_PROXY:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote_addr or ""
