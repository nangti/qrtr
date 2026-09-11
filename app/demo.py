"""Demo mode (DEMO_MODE=1): ephemeral-preview convenience ONLY.

Whoever opens the app is auto-logged-in as a seeded demo user (first user in
the DB → auto-admin, so the full product incl. /admin is visible), with one
sample campaign ready. Login/signup are bypassed by auth.py. Never enable on
any deployment that real strangers can reach — there is no auth at all."""
import secrets

from .config import Config
from .security import hash_password
from .svc import svc

DEMO_EMAIL = "demo@qrtr.local"
DEMO_CAMPAIGN = ("Demo · Shop window", "https://wa.me/910000000000")


def ensure_demo_state():
    """Idempotent demo bootstrap; returns the demo user row."""
    st = svc().store
    u = st.user_by_email(DEMO_EMAIL)
    if u is None:
        st.create_user(DEMO_EMAIL, hash_password(secrets.token_urlsafe(12)))
        u = st.user_by_email(DEMO_EMAIL)
        st.create_campaign(u["id"], DEMO_CAMPAIGN[0], DEMO_CAMPAIGN[1], Config.CODE_LENGTH)
    return u
