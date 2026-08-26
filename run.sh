#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
elif [[ -x venv/bin/python ]]; then
  PY=venv/bin/python
else
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  PY=.venv/bin/python
fi
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
export MAPGAP_HOST="${MAPGAP_HOST:-0.0.0.0}"
export MAPGAP_PORT="${MAPGAP_PORT:-8787}"
exec "$PY" app.py
