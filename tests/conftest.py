""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "tools", ROOT / "tools" / "cross-source"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
