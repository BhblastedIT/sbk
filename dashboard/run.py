#!/usr/bin/env python3
"""Starts the SBK dashboard (FastAPI) on http://127.0.0.1:8000, reloading when the code changes.

PORT overrides the default port. In a container (SBK_CONTAINERIZED=1) it listens on 0.0.0.0, without reload,
with UVICORN_WORKERS workers.

Usage: uv run python dashboard/run.py [--host HOST] [--port PORT] [--no-reload]
"""

import argparse
import os
import sys
from pathlib import Path


_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import uvicorn

if __name__ == "__main__":
    _containerized = os.environ.get("SBK_CONTAINERIZED", "0") == "1"
    _ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ap.add_argument("--host", default="0.0.0.0" if _containerized else "127.0.0.1",
                     help="address to listen on (default: %(default)s)")
    _ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")),
                     help="port (default: %(default)s, or PORT)")
    _ap.add_argument("--no-reload", action="store_true", help="do not restart when the code changes")
    _args = _ap.parse_args()
    _reload = not _containerized and not _args.no_reload
    uvicorn.run(
        "app.main:app",
        host=_args.host,
        port=_args.port,
        reload=_reload,
        reload_dirs=[str(_APP_DIR / "app")] if _reload else None,
        workers=int(os.environ.get("UVICORN_WORKERS", "1")) if _containerized else None,
    )
