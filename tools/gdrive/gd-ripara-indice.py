#!/usr/bin/env python3
"""Relink Drive index entries whose local file moved inside the gdrive data folder (dry run unless --esegui)."""















from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

GDRIVE = DATA_ROOT / "gdrive"
INDICE = GDRIVE / "gdrive-index.json"
_RELATIVO = re.compile(r"/\.sbk-data/gdrive/(.+)$")


def candidati(percorso: str, base: Path) -> list[Path]:
    ""

    m = _RELATIVO.search(str(percorso))
    if not m:
        return []
    relativo = m.group(1)
    # the file may sit in one of the per-account subfolders of gdrive/, or at its top
    try:
        sotto = [p / relativo for p in sorted(base.iterdir()) if p.is_dir()]
    except OSError:
        sotto = []
    return [*sotto, base / relativo]


def ricollega(voci: list[dict], base: Path) -> Counter:
    ""
    conti: Counter = Counter()
    for v in voci:
        percorso = v.get("local_path")
        if not percorso or Path(percorso).exists():
            continue
        trovato = next((c for c in candidati(percorso, base) if c.exists()), None)
        if trovato is None:
            conti["not found"] += 1
            continue
        v["local_path"] = str(trovato)
        v["ricollegato_il"] = datetime.now().strftime("%Y-%m-%d")
        stessa = int(v.get("size") or -1) == trovato.stat().st_size
        conti[
            "relinked, same size" if stessa else "relinked, different size"
        ] += 1
    return conti


def _scaricatore_al_lavoro() -> bool:
    ""
    ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    return any(
        ("gd-l0-download.py" in r or "gd-l1-enrich.py" in r) and "gd-ripara-indice" not in r
        for r in ps.splitlines()
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Relink Drive index entries"])[0]
    )
    ap.add_argument(
        "--esegui", action="store_true", help="relink and write the index (without it: dry run)"
    )
    args = ap.parse_args()

    voci = json.loads(INDICE.read_text(encoding="utf-8"))
    conti = ricollega(voci, GDRIVE)
    for esito, n in conti.most_common():
        print(f"  {esito}: {n}")
    ricollegate = sum(n for k, n in conti.items() if k.startswith("relinked"))
    if not args.esegui:
        print(
            f"dry run: {ricollegate} entries to relink, nothing written. To write, pass --esegui"
        )
        return 0
    if _scaricatore_al_lavoro():
        print("⛔ the Drive downloader or reader is running: retry when they have finished")
        return 2
    if not ricollegate:
        print("nothing to relink")
        return 0
    copia = INDICE.with_name(f"gdrive-index.json.bak-ripara-{datetime.now():%Y%m%d-%H%M}")
    shutil.copy2(INDICE, copia)
    safe_write_json(INDICE, voci)
    print(f"✅ relinked {ricollegate} entries, previous index copy in {copia.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
