#!/bin/sh
# Entrypoint for the profile-analyst image.
# Usage:
#   api               → start the FastAPI server (long-running service)
#   <anything else>   → pass through to profile_analyst.py (one-shot CLI)
#
# Never chowns host mounts — projects/ is managed by the host.
set -e

if [ "${1}" = "api" ]; then
    exec uvicorn api.main:app --host 0.0.0.0 --port "${API_PORT:-8000}"
else
    exec python profile_analyst.py "$@"
fi
