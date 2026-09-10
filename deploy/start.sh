#!/bin/sh
# Container entrypoint: fetch geo DB if possible, then serve.
sh scripts/fetch-geo.sh || true
exec python run.py
