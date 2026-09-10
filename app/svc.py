"""Access to the per-app service container (set in create_app)."""
from flask import current_app


def svc():
    return current_app.extensions["qrtr"]
