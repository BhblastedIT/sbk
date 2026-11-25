#!/bin/sh





set -e
name="$1"; shift
f="$HOME/.sbk-credentials/files/sbk/mcp/$name.env"
if [ ! -r "$f" ]; then echo "sb-mcp-run: $f is missing (the secrets of the MCP server '$name')" >&2; exit 78; fi
set -a; . "$f"; set +a
exec "$@"
