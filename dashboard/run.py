#!/usr/bin/env python3
""






import os
import sys
from pathlib import Path


_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import uvicorn

if __name__ == "__main__":
    _containerized = os.environ.get("SBK_CONTAINERIZED", "0") == "1"
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0" if _containerized else "127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        reload=not _containerized,
        reload_dirs=[str(_APP_DIR / "app")] if not _containerized else None,
        workers=int(os.environ.get("UVICORN_WORKERS", "1")) if _containerized else None,
    )
