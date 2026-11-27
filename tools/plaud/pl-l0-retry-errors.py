#!/usr/bin/env python3
"""Plaud: retries the transcripts that failed in the last download (<data root>/plaud/_errors.json) and keeps only
the ones still failing.
"""

import argparse
import json
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import importlib.util

from sbk_config import PLAUD_DIR, safe_write_json

OUTPUT_DIR = PLAUD_DIR
ERRORS_PATH = OUTPUT_DIR / "_errors.json"
INDEX_PATH = OUTPUT_DIR / "_file_index.json"


def _load_downloader():
    # Loaded only when there is something to retry, so --help has no side effects.
    spec = importlib.util.spec_from_file_location(
        "pl_l0_download", Path(__file__).parent / "pl-l0-download.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=(
            "Plaud: retry the transcripts that failed in the last download. It reads "
            "<data root>/plaud/_errors.json, fetches each failed transcript again, writes the "
            "ones it gets and keeps only the still-failing ones in _errors.json. "
            "Exit code 1 when some still fail."
        )
    )
    return p.parse_args(argv)


def main():
    _parse_args()
    if not ERRORS_PATH.exists():
        print("No _errors.json found. Nothing to retry.")
        return

    errors = json.loads(ERRORS_PATH.read_text())
    print(f"Errors to retry: {len(errors)}")
    mod = _load_downloader()

    index = json.loads(INDEX_PATH.read_text()) if INDEX_PATH.exists() else []
    index_by_id = {f["id"]: f for f in index}

    recovered = []
    still_failing = []

    for i, err in enumerate(errors):
        file_id = err["id"]
        name = err.get("name", file_id)

        f_info = index_by_id.get(file_id)
        if not f_info:
            print(f"  [{i + 1}/{len(errors)}] {name[:50]}... INDEX_MISSING")
            still_failing.append(err)
            continue

        date = f_info["date"]
        filename = f_info["filename"]
        safe_name = "".join(c if c.isalnum() or c in " -_." else "_" for c in filename)[:100]
        out_name = f"{date}_{safe_name}"
        out_json = OUTPUT_DIR / f"{out_name}.json"
        out_txt = OUTPUT_DIR / f"{out_name}.txt"

        if out_txt.exists() and out_txt.stat().st_size > 100:
            print(f"  [{i + 1}/{len(errors)}] {out_name[:50]}... ALREADY_EXISTS")
            recovered.append(err)
            continue

        print(f"  [{i + 1}/{len(errors)}] {out_name[:50]}...", end=" ", flush=True)

        try:
            trans = mod.fetch_transcript_from_browser(file_id)

            if trans and not (isinstance(trans, dict) and "_error" in trans):
                safe_write_json(out_json, trans)
                text = mod.format_transcript(trans)
                with open(out_txt, "w") as fp:
                    fp.write(f"# {filename}\n")
                    fp.write(f"# Date: {date}\n")
                    fp.write(f"# Duration: {f_info['duration_sec']:.0f}s\n")
                    fp.write(f"# ID: {file_id}\n\n")
                    fp.write(text)
                size_kb = len(text) / 1024
                print(f"OK ({size_kb:.1f}KB)")
                recovered.append(err)
            else:
                e = trans.get("_error", "unknown") if isinstance(trans, dict) else "empty"
                print(f"FAIL ({e})")
                err["last_error"] = e
                still_failing.append(err)
            time.sleep(0.4)

        except Exception as e:
            print(f"ERR: {str(e)[:80]}")
            err["last_error"] = str(e)[:200]
            still_failing.append(err)
            if "timeout" in str(e).lower():
                time.sleep(5)


    if still_failing:
        safe_write_json(ERRORS_PATH, still_failing)
    else:
        ERRORS_PATH.unlink(missing_ok=True)

    print()
    print("=" * 60)
    print(f"RECOVERED: {len(recovered)} / {len(errors)}")
    print(f"STILL FAILING: {len(still_failing)}")
    print("=" * 60)

    if still_failing:
        sys.exit(1)


if __name__ == "__main__":
    main()
