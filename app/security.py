"""Password hashing (scrypt, stdlib) and token utilities.

Format: $scrypt$N,r,p$<salt-b64>$<hash-b64> — self-describing so parameters can
be raised later without breaking existing hashes."""
import base64
import hashlib
import hmac as hmac_mod
import secrets

N, R, P, DKLEN = 32768, 8, 1, 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN,
                        maxmem=128 * 1024 * 1024)  # OpenSSL's 32MiB default is <128*N*r
    b64 = lambda b: base64.b64encode(b).decode()
    return f"$scrypt${N},{R},{P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, _, params, salt_b64, hash_b64 = stored.split("$")
        n, r, p = (int(x) for x in params.split(","))
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p,
                            dklen=len(expected), maxmem=128 * 1024 * 1024)
        return hmac_mod.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_user_id() -> str:
    return secrets.token_urlsafe(12)


def new_short_code(length: int = 6) -> str:
    # base62 minus visually-ambiguous chars (0/O, 1/l/I) for QR/print contexts
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
