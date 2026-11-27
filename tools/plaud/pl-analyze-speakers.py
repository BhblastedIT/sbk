#!/usr/bin/env python3
"""Rebuilds _speaker_analysis.json from all the Plaud L0 recordings: which speakers are named and how much each one covers."""












































from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from sbk_config import OWNER_SPEAKER_LABELS, PLAUD_DIR, safe_write_json  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("pl-analyze-speakers")

OUT_FILE = PLAUD_DIR / "_speaker_analysis.json"



# Your names and speaker labels, from sbk.config.json (owner, own_names).
OWNER_NAMES = set(OWNER_SPEAKER_LABELS)


_GENERIC = re.compile(r"^Speaker \d+$")


COVERAGE_MIN = 0.05


CATEGORIE = ("monologue", "clean_multi", "partial_id", "no_id")


def _segmenti(raw: object) -> list[dict]:
    ""

    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    if isinstance(raw, dict):
        seg = raw.get("segments", [])
        return [s for s in seg if isinstance(s, dict)] if isinstance(seg, list) else []
    return []


def analizza_uno(path: Path) -> dict:
    ""

    seg = _segmenti(json.loads(path.read_text(encoding="utf-8")))

    speakers, original, named, generic = [], [], [], []
    seg_named = 0
    for s in seg:
        sp = (s.get("speaker") or "").strip()
        if sp:
            if sp not in speakers:
                speakers.append(sp)
            if _GENERIC.match(sp):
                if sp not in generic:
                    generic.append(sp)
            else:
                if sp not in named:
                    named.append(sp)
                seg_named += 1
        osp = s.get("original_speaker")
        if osp and osp not in original:
            original.append(osp)

    n = len(seg)

    transitions = 0
    prev = None
    for s in seg:
        cur = s.get("speaker")
        if prev is not None and cur != prev:
            transitions += 1
        prev = cur


    dur_ms = sum(max(0, (s.get("end_time") or 0) - (s.get("start_time") or 0)) for s in seg)
    duration_min = round(dur_ms / 60000, 3)

    coverage = (seg_named / n) if n else 0.0
    owner_present = any(name.lower() in OWNER_NAMES for name in named)
    has_original = bool(original)


    if n == 0 or not speakers:
        category = "no_id"
    elif len(speakers) == 1 and named:
        category = "monologue"
    elif named and coverage >= COVERAGE_MIN:
        category = "clean_multi"
    elif has_original:
        category = "partial_id"
    else:
        category = "no_id"

    return {
        "filename": path.name,
        "speakers": speakers,
        "original_speakers": original,
        "segments": n,
        "duration_min": duration_min,
        "category": category,
        "speaker_transitions": transitions,
        "owner_present": owner_present,
        "has_original_speaker": has_original,
        "named_speakers": named,
        "generic_speakers": generic,
    }


def costruisci() -> dict:
    ""

    files: list[dict] = []
    errors: list[dict] = []
    for path in sorted(PLAUD_DIR.glob("*.json")):



        if path.name.startswith("_") or path.name.startswith("."):
            continue
        try:
            files.append(analizza_uno(path))
        except Exception as e:  # noqa: BLE001
            errors.append({"filename": path.name, "error": str(e)[:200]})



    cats = {c: sum(1 for f in files if f["category"] == c) for c in CATEGORIE}
    return {
        "total_files": len(files),
        "errors": errors,
        "categories": cats,
        "files": files,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="categorise and count, write nothing")
    ap.add_argument(
        "--verify", action="store_true", help="compare with the existing file, write nothing"
    )
    a = ap.parse_args()



    try:
        from sbk_resources import budget

        b = budget()
        if b.pressure.should_abort():
            log.error("memory pressure too high (%s), not starting", b.pressure.level)
            return 75
    except Exception:  # noqa: BLE001
        pass

    dati = costruisci()
    tot, cats, errs = dati["total_files"], dati["categories"], len(dati["errors"])
    log.info("recordings analysed: %d · categories: %s · errors: %d", tot, cats, errs)
    if errs:
        for e in dati["errors"][:10]:
            log.warning("  error on %s: %s", e["filename"], e["error"])

    if a.verify:
        if not OUT_FILE.exists():
            log.info("verify: %s does not exist yet", OUT_FILE.name)
            return 0
        vecchio = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        log.info(
            "verify: %d files on disk, %d recomputed (delta %+d)",
            len(vecchio.get("files", [])),
            tot,
            tot - len(vecchio.get("files", [])),
        )
        return 0

    if a.dry_run:
        log.info("dry run: nothing written (it would write %s)", OUT_FILE)
        return 0


    safe_write_json(OUT_FILE, dati)
    log.info("written %s", OUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
