#!/bin/bash
# Plaud companion window: opens the SBK Plaud page as an app window on the Mac.
#
# It is a dedicated window without browser bars (like the Plaud app), served by the SBK
# dashboard. It uses a SEPARATE Chrome profile (~/.plaud-superpoteri-chrome), so it does not
# touch your own Chrome or its sessions.
#
# Double-click this file to open it. To keep it in the Dock: drag it there, or make an app
# with Automator ("Run Shell Script" -> the path of this file).

set -e

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
URL="http://127.0.0.1:8000/plaud-mini"
PROFILE="$HOME/.plaud-superpoteri-chrome"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 1. Is the SBK dashboard up? If not, start it.
if ! curl -s -o /dev/null --max-time 3 "$URL"; then
    echo "Starting the SBK dashboard (port 8000)..."
    ( cd "$REPO/dashboard" && nohup bash "$REPO/tools/infrastructure/run-dashboard.sh" >/dev/null 2>&1 & )
    for i in $(seq 1 40); do
        curl -s -o /dev/null --max-time 2 "$URL" && break
        sleep 1
    done
fi

if ! curl -s -o /dev/null --max-time 3 "$URL"; then
    echo "Could not start the dashboard. Start it by hand: bash $REPO/tools/infrastructure/run-dashboard.sh"
    read -r -p "Press Enter to close."
    exit 1
fi

# 2. Open it as an app window (separate profile, your own Chrome is not touched)
if [ -x "$CHROME" ]; then
    "$CHROME" --user-data-dir="$PROFILE" --app="$URL" \
        --window-size=460,700 --no-first-run --no-default-browser-check >/dev/null 2>&1 &
else
    # Fallback: your default browser (opens as a normal tab)
    open "$URL"
fi
