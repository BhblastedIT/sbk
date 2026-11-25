#!/bin/bash
# Runs the SBK monitor (tools/monitoring/sbk-monitor.py).
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

cd "$SBK_PROJECT" || {
    echo "ERROR: cannot access $SBK_PROJECT." >&2
    exit 1
}
exec "$UV" run python3 tools/monitoring/sbk-monitor.py "$@"
