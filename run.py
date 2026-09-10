#!/usr/bin/env python3
"""qrtr entrypoint. Dev: `python run.py`. Prod (docker): same, via deploy/start.sh."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "8080"))
    print(f"qrtr listening on 0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
