#!/usr/bin/env python3
"""Plaud recording details: fetch the detail of every transcribed recording (device, platform, edit time) into the plaud/dettagli folder."""












from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.plaud.pl_write import WriteError, _http, get_auth  # noqa: E402

DATA = Path(os.environ.get("SBK_DATA", Path.home() / ".sbk-data"))
RAW = DATA / "plaud" / "raw"
OUT = DATA / "plaud" / "dettagli"
PIATTAFORME = {
    "IOS": "iPhone",
    "ANDROID": "Android",
    "DESKTOP": "Mac",
    "WEB": "web",
    "WORKFLOW": "flusso automatico",
}


def dispositivi(wt: str, api: str) -> dict[str, str]:
    d = _http("GET", api, "/device/list", wt) or {}
    return {
        x.get("sn"): f"{x.get('name') or x.get('model')} ({str(x.get('sn'))[-4:]})"
        for x in d.get("data_devices") or []
    }


def riassunto(fid: str, data: dict, devs: dict[str, str], edit_time) -> dict:
    ed = data.get("extra_data") or {}
    tc = ed.get("tranConfig") or {} if isinstance(ed, dict) else {}
    sn = str(data.get("serial_number") or "")
    nome_dev = devs.get(sn) or devs.get(sn.split("-")[0])
    tipo_dev = nome_dev or (
        "app (telefono o Mac)" if sn.isdigit() and len(sn) == 13 else "sconosciuto"
    )
    plat = ed.get("last_trans_app_platform") if isinstance(ed, dict) else None
    return {
        "id": fid,
        "edit_time": edit_time,
        "letto": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial_number": sn,
        "dispositivo": tipo_dev,
        "piattaforma": PIATTAFORME.get(plat or "", plat),
        "trascritta_il": (tc.get("created_at") or "")[:19],
        "tipo_riassunto": tc.get("type"),
        "diarizzazione": tc.get("diarization"),
        "lingua": tc.get("language"),
        "speaker_sostituiti": ed.get("has_replaced_speaker") if isinstance(ed, dict) else None,
        "modello": ed.get("model") if isinstance(ed, dict) else None,
        "scene": data.get("scene"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud recording details"])[0]
    )
    ap.add_argument(
        "--limit", dest="limite", type=int, default=0,
        help="stop after this many recordings (0 = all)",
    )
    ap.add_argument(
        "--pause", dest="pausa", type=float, default=0.4,
        help="seconds between two requests (default 0.4)",
    )
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--limite", dest="limite", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--pausa", dest="pausa", type=float, help=argparse.SUPPRESS)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    indice = json.loads((RAW / "_file_index.json").read_text())
    wt, api = get_auth()
    devs = dispositivi(wt, api)
    (OUT / "_dispositivi.json").write_text(json.dumps(devs, ensure_ascii=False, indent=1))
    fatti = errori = 0
    for x in sorted(indice, key=lambda x: -(x.get("st") or 0)):
        if x.get("is_trash") or not x.get("has_transcript"):
            continue
        p = OUT / f"{x['id']}.json"
        if p.exists():
            try:
                if json.loads(p.read_text()).get("edit_time") == x.get("edit_time"):
                    continue
            except json.JSONDecodeError:
                pass
        try:
            data = (_http("GET", api, f"/file/detail/{x['id']}", wt) or {}).get("data") or {}
        except WriteError as e:
            errori += 1
            print("error", x["id"][:8], str(e)[:80])
            if errori >= 5:
                print("five errors: stopping")
                break
            continue
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(riassunto(x["id"], data, devs, x.get("edit_time")), ensure_ascii=False)
        )
        tmp.replace(p)
        fatti += 1
        if args.limite and fatti >= args.limite:
            break
        time.sleep(args.pausa)
    print(
        f"details read {fatti}, errors {errori}, in the folder {len(list(OUT.glob('*.json'))) - 1}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
