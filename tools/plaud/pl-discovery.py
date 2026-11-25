#!/usr/bin/env python3
""












import gzip
import json
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


import importlib.util

_dl_path = _TOOLS_DIR / "plaud" / "pl-l0-download.py"
_spec = importlib.util.spec_from_file_location("pl_l0_download", _dl_path)
_dl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dl)

API_BASE = _dl.API_BASE  # sbk.config.json plaud.api_base (see pl-l0-download.py)


def api_get(token, path, timeout=60):
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Authorization": token,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b" or resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def main():
    print("=" * 64)
    print("PLAUD DISCOVERY (read-only)")
    print("=" * 64)

    print("Decifro token via Electron safeStorage...")
    token = _dl.get_token_direct()
    print(f"  Token OK ({token[:24]}...)\n")

    print("Scarico file list completa (read-only)...")
    data = api_get(
        token,
        "/file/simple/web?skip=0&limit=9999&is_trash=2&sort_by=start_time&is_desc=true",
    )
    files = data.get("data_file_list", [])
    total = data.get("data_file_total", len(files))
    print(f"  {len(files)} file (total dichiarato: {total})\n")


    if files:
        print("Chiavi disponibili per file (primo record):")
        print("  " + ", ".join(sorted(files[0].keys())))
        print()


    by_month = Counter()
    by_year = Counter()
    long_files = []
    very_long = []
    durations = []
    trans_count = 0

    for f in files:
        st = f.get("start_time")
        dur_ms = f.get("duration") or 0
        dur_h = dur_ms / 3600000.0
        durations.append(dur_h)
        if f.get("is_trans"):
            trans_count += 1
        if st:
            dt = datetime.fromtimestamp(st / 1000, tz=UTC)
            by_year[dt.year] += 1
            by_month[f"{dt.year}-{dt.month:02d}"] += 1
        if dur_h >= 3.0:
            long_files.append((f.get("id"), f.get("filename", "")[:50], round(dur_h, 2), st))
        if dur_h >= 5.0:
            very_long.append((f.get("id"), round(dur_h, 2)))

    print("Distribuzione per ANNO:")
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]} file")
    print()

    anno_corrente = datetime.now(tz=UTC).year
    print(f"Distribuzione {anno_corrente} per MESE:")
    for m in sorted(k for k in by_month if k.startswith(str(anno_corrente))):
        print(f"  {m}: {by_month[m]} file")
    print()

    files_anno = [
        f
        for f in files
        if f.get("start_time")
        and datetime.fromtimestamp(f["start_time"] / 1000, tz=UTC).year == anno_corrente
    ]
    print(
        f"TOTALE {anno_corrente}: {len(files_anno)} file, di cui con transcript: {sum(1 for f in files_anno if f.get('is_trans'))}"
    )
    print()

    print(f"Registrazioni >= 3h (degrado diarization atteso): {len(long_files)}")
    for fid, fn, h, st in sorted(long_files, key=lambda x: -x[2])[:15]:
        y = datetime.fromtimestamp(st / 1000, tz=UTC).year if st else "?"
        print(f"  [{y}] {h}h  {fn}  (id={fid})")
    print(f"  ... di cui >= 5h (split meccanico Plaud): {len(very_long)}")
    print()

    if durations:
        durations.sort()
        print(
            f"Durata: media {sum(durations) / len(durations):.2f}h, max {max(durations):.2f}h, mediana {durations[len(durations) // 2]:.2f}h"
        )
    print()


    print("=" * 64)
    print("CAMPIONE /file/detail (struttura content_list + audio)")
    print("=" * 64)
    sample = [f for f in files_anno if f.get("is_trans")][:3]
    for f in sample:
        fid = f.get("id")
        print(
            f"\n--- {f.get('filename', '')[:55]} (id={fid}, {(f.get('duration') or 0) / 3600000:.2f}h) ---"
        )
        try:
            detail = api_get(token, f"/file/detail/{fid}", timeout=30)
            body = detail.get("data") or detail
            cl = body.get("content_list") or []
            print(f"  content_list data_type: {[c.get('data_type') for c in cl]}")

            for c in cl:
                if c.get("data_type") in ("audio", "origin_audio", "media"):
                    print(
                        f"  AUDIO data_type={c.get('data_type')} link_present={bool(c.get('data_link'))}"
                    )

        except Exception as e:
            print(f"  detail ERR: {str(e)[:80]}")


        try:
            tu = api_get(token, f"/file/temp-url/{fid}", timeout=20)
            keys = list(tu.keys()) if isinstance(tu, dict) else type(tu).__name__
            print(f"  temp-url OK, keys: {keys}")
        except Exception as e:
            print(f"  temp-url: {str(e)[:80]}")

    print("\n" + "=" * 64)
    print("DISCOVERY COMPLETATA (nessuna scrittura, nessun download massivo)")
    print("=" * 64)


if __name__ == "__main__":
    main()
