#!/usr/bin/env python3
""
















from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))

from sbk_config import ENRICHED_DIR  # noqa: E402

log = logging.getLogger("sbk-xs-l2-entity-map-cleanup")


def _pulizia():
    ""
    spec = importlib.util.spec_from_file_location(
        "xs_l2_entity_resolve_pulizia", _THIS_DIR / "xs-l2-entity-resolve.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cleanup_entity_map


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    mappa = ENRICHED_DIR / "entity-map.json"
    rubrica = ENRICHED_DIR / "contacts-merged.parquet"
    mancano = [p.name for p in (mappa, rubrica) if not p.exists()]
    if mancano:
        log.error("Missing cleanup inputs: %s", ", ".join(mancano))
        sys.exit(1)
    prima = mappa.stat().st_mtime
    originali, _tenute, tolte = _pulizia()(mappa, rubrica)
    if tolte == 0:
        os.utime(mappa, (prima, prima))
        log.info("Entity map unchanged (0 removals) — mtime preserved")
    log.info("Map cleanup: %d entries, %d removed", originali, tolte)


from pipeline_decorator import pipeline_step  # noqa: E402

main = pipeline_step(name="xs-l2-entity-map-cleanup", source="cross-source", stage="l2")(main)

if __name__ == "__main__":
    main()
