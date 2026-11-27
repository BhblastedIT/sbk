#!/usr/bin/env python3
"""Refreshes the entity map (enriched/entity-map.json) from the merged contact book, then cleans it.

Every --ingest, --propagate and --rebuild that runs the merge runs this step after it. It rebuilds the map with
xs-l2-entity-resolve.py (skipped when the book did not change since the last build), so people who arrive in a
later run (a card with a second email, a database with a work email) join the same person as they would in one
run. When the rebuilt map differs from the one the merge used, it runs the merge once more, so the book and its
person ids follow the fresh map in this same run. Last, it drops map entries that no longer point to a contact,
and keeps the file's date when nothing was removed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))

from sbk_config import ENRICHED_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-xs-l2-entity-map-cleanup")


def _pulizia():
    ""
    spec = importlib.util.spec_from_file_location(
        "xs_l2_entity_resolve_pulizia", _THIS_DIR / "xs-l2-entity-resolve.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.cleanup_entity_map


def _leggi_mappa(mappa: Path) -> dict | None:
    """The entity map as a dict, None when it is missing or unreadable."""
    try:
        d = json.loads(mappa.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _righe(rubrica: Path) -> int:
    """How many rows the merged book has (0 when it cannot be read)."""
    try:
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(rubrica).metadata.num_rows)
    except Exception:
        return 0


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    ).parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    mappa = ENRICHED_DIR / "entity-map.json"
    rubrica = ENRICHED_DIR / "contacts-merged.parquet"
    if not rubrica.exists():
        log.info("No merged contacts yet: no entity map to build, nothing to clean")
        return

    # Refresh: rebuild the map from the book on every run, not only on the first one. The
    # resolver skips the work itself when the book did not change since its last build.
    prima = _leggi_mappa(mappa)
    primo = prima is None
    log.info(
        "No entity map yet: building the first one (xs-l2-entity-resolve.py)"
        if primo
        else "Refreshing the entity map from the merged book (xs-l2-entity-resolve.py)"
    )
    args = [sys.executable, str(_THIS_DIR / "xs-l2-entity-resolve.py")]
    if not primo:
        args.append("--incremental")
    rc = subprocess.run(args).returncode
    dopo = _leggi_mappa(mappa)
    if rc != 0 or dopo is None:
        if primo:
            log.error("The first entity map was not built (xs-l2-entity-resolve.py exit %s)", rc)
            sys.exit(1)
        log.warning(
            "The entity map was not refreshed (xs-l2-entity-resolve.py exit %s): the previous one stays",
            rc,
        )
        dopo = prima

    if (prima or {}) == (dopo or {}):
        log.info("Entity map refreshed: no change")
    elif _righe(rubrica) == 0:
        log.info("Entity map refreshed; the merged book has no one yet, nothing to merge again")
    else:
        # The merge applied the old map (or none): apply the fresh one now, so the book's
        # person ids and all_emails are the ones every later run will give.
        log.info(
            "The entity map changed: merging the book again with the fresh map (xs-l2-merge.py)"
        )
        rc = subprocess.run([sys.executable, str(_THIS_DIR / "xs-l2-merge.py")]).returncode
        if rc != 0:
            # The book still follows the map the merge used: put that one back, so book and map
            # agree; the next run tries again.
            if prima is not None:
                safe_write_json(mappa, prima)
            log.warning(
                "The book was not merged again with the fresh entity map (xs-l2-merge.py exit %s): "
                "%s; the next run tries again",
                rc,
                "the previous map is back" if prima is not None else "the first map stays",
            )

    prima_mtime = mappa.stat().st_mtime
    originali, _tenute, tolte = _pulizia()(mappa, rubrica)
    if tolte == 0:
        os.utime(mappa, (prima_mtime, prima_mtime))
        log.info("Entity map unchanged by the cleanup (0 removals) — mtime preserved")
    log.info("Map cleanup: %d entries, %d removed", originali, tolte)


from pipeline_decorator import pipeline_step  # noqa: E402

main = pipeline_step(name="xs-l2-entity-map-cleanup", source="cross-source", stage="l2")(main)

if __name__ == "__main__":
    main()
