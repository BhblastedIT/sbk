#!/bin/bash
# Scheduled L3 cleanup: tools/cross-source/xs-l3-compact.py --apply on files older than 72 hours.
# No model call. Works from any folder and from launchd: the repo is found from where this
# script sits, uv from your PATH. On failure it writes a .notify file and shows a macOS notice.

set -uo pipefail

SBK_PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SBK_PROJECT" || exit 1

# launchd starts jobs with a minimal PATH: add the usual install folders of uv.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
command -v uv >/dev/null 2>&1 || {
    echo "ERROR: uv not found in PATH. Install it: https://docs.astral.sh/uv/" >&2
    exit 1
}

set -a
source .env 2>/dev/null || true
set +a

DATA_ROOT="${SBK_DATA_ROOT:-$HOME/.sbk-data}"
LOG="$DATA_ROOT/l3/logs/compact-cron.log"
NOTIFY="$DATA_ROOT/l3/logs/compact-cron.notify"
mkdir -p "$(dirname "$LOG")"
echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') scheduled L3 cleanup ===" >> "$LOG"

if uv run python3 tools/cross-source/xs-l3-compact.py \
      --apply --skip-if-running --no-compact --older-than-hours 72 >> "$LOG" 2>&1; then
    echo "[$(date '+%H:%M:%S')] OK" >> "$LOG"
    rm -f "$NOTIFY" 2>/dev/null || true
else
    rc=$?
    echo "[$(date '+%H:%M:%S')] FAIL (exit $rc)" >> "$LOG"

    echo "$(date '+%Y-%m-%d %H:%M:%S') L3 cleanup job FAILED exit=$rc, see compact-cron.log" > "$NOTIFY"

    osascript -e 'display notification "L3 cleanup job failed" with title "SBK L3"' 2>/dev/null || true
fi
