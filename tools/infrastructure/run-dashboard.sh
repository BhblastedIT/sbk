#!/bin/bash
# Starts the SBK web dashboard on 127.0.0.1:8000. SBK_DASHBOARD_DEV=1 turns on --reload.
# Works from any folder and from launchd: the repo is found from where this script sits,
# uv from your PATH.

SBK_PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# launchd starts jobs with a minimal PATH: add the usual install folders of uv.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
UV="$(command -v uv)" || {
    echo "ERROR: uv not found in PATH. Install it: https://docs.astral.sh/uv/" >&2
    exit 1
}

set -a
source "$SBK_PROJECT/.env" 2>/dev/null || true
set +a

cd "$SBK_PROJECT/dashboard" || {
    echo "ERROR: cannot access $SBK_PROJECT/dashboard." >&2
    exit 1
}

if [ "${SBK_DASHBOARD_DEV:-0}" = "1" ]; then
    echo "Dashboard in development mode (--reload on)." >&2
    exec "$UV" run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
fi

exec "$UV" run uvicorn app.main:app --host 127.0.0.1 --port 8000
