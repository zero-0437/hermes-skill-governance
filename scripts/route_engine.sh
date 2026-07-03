#!/usr/bin/env bash
# Route engine wrapper — uses venv with yaml installed
exec /tmp/route-env/bin/python /opt/data/scripts/route_engine.py "$@"
