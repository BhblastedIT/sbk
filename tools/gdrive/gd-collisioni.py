#!/usr/bin/env python3
"""Drive path collisions: when several index entries share one local file, check each against Drive and re-download or detach the wrong ones (dry run unless --esegui)."""

















from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

GDRIVE = DATA_ROOT / "gdrive"
INDICE = GDRIVE / "gdrive-index.json"
CAMPI = "id,name,mimeType,md5Checksum,size,modifiedTime,createdTime,trashed,owners(emailAddress),webViewLink"


def gruppi(voci: list[dict]) -> dict[str, list[dict]]:
    ""
    per_percorso: dict[str, list[dict]] = defaultdict(list)
    for v in voci:
        if v.get("downloaded") and v.get("local_path"):
            per_percorso[v["local_path"]].append(v)
    return {p: vs for p, vs in per_percorso.items() if len(vs) > 1}


def account_di(voce: dict, base: Path = GDRIVE) -> str:
    ""
    if voce.get("account"):
        return voce["account"]
    try:
        return Path(voce.get("local_path", "")).relative_to(base).parts[0]
    except (ValueError, IndexError):
        return ""


def md5_file(percorso: Path) -> str:
    h = hashlib.md5()
    with percorso.open("rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            h.update(pezzo)
    return h.hexdigest()


def decidi(
    gruppo: list[dict], schede: dict[str, dict | None], md5_locale: str, dimensione: int
) -> dict:
    ""
    tiene, rifare, staccare = [], [], []
    for v in gruppo:
        scheda = schede.get(v["id"])
        if scheda is None:

            (tiene if int(v.get("size") or -1) == dimensione else staccare).append(v["id"])
        elif scheda.get("md5Checksum") and scheda["md5Checksum"] == md5_locale:
            tiene.append(v["id"])
        else:
            rifare.append(v["id"])
    return {"tiene": tiene, "rifare": rifare, "staccare": staccare}


def _ritenta(chiamata, attese=(5, 15, 45, 90)):
    ""
    from googleapiclient.errors import HttpError

    for attesa in (*attese, None):
        try:
            return chiamata()
        except HttpError as e:
            stato = int(getattr(getattr(e, "resp", None), "status", 0) or 0)
            if attesa is None or not (stato == 429 or 500 <= stato < 600):
                raise
            time.sleep(attesa)


def _scaricatore():
    ""
    nome = "gd_l0_download_collisioni"
    spec = importlib.util.spec_from_file_location(nome, _TOOLS_DIR / "gdrive" / "gd-l0-download.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


def _scaricatore_al_lavoro() -> bool:
    ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    return any("gd-l0-download.py" in r for r in ps.splitlines())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Drive path collisions"])[0]
    )
    ap.add_argument(
        "--esegui", action="store_true", help="re-download and write the index (without it: dry run)"
    )
    args = ap.parse_args()
    if args.esegui and _scaricatore_al_lavoro():
        print("⛔ the Drive downloader is running: retry when it has finished")
        return 2

    from googleapiclient.errors import HttpError

    dl = _scaricatore()
    conosciuti = dl.get_known_accounts()
    voci = json.loads(INDICE.read_text(encoding="utf-8"))
    per_id = {v["id"]: v for v in voci}
    tutti = gruppi(voci)
    print(f"{len(tutti)} paths with {sum(map(len, tutti.values()))} entries")

    servizi: dict[str, object] = {}

    def servizio(account: str):
        if account not in servizi:
            servizi[account] = dl.build_service(account, conosciuti.get(account, ""))
        return servizi[account]

    schede: dict[str, dict | None] = {}
    conti: Counter = Counter()
    for percorso, gruppo in tutti.items():
        for v in gruppo:
            s = servizio(account_di(v))
            if s is None:
                conti["account without credentials"] += 1
                continue
            try:
                schede[v["id"]] = _ritenta(
                    lambda s=s, fid=v["id"]: (
                        s.files().get(fileId=fid, fields=CAMPI, supportsAllDrives=True).execute()
                    )
                )
            except HttpError as e:
                if int(getattr(e.resp, "status", 0) or 0) == 404:
                    schede[v["id"]] = None
                else:
                    conti[f"error {getattr(e.resp, 'status', '?')}"] += 1

    decisioni = {}
    for percorso, gruppo in tutti.items():
        p = Path(percorso)
        if not p.exists():
            conti["file missing on disk"] += len(gruppo)
            continue
        noti = [v for v in gruppo if v["id"] in schede]
        d = decidi(noti, schede, md5_file(p), p.stat().st_size)
        decisioni[percorso] = d
        for chi, ids in d.items():
            conti[chi] += len(ids)
    for k, n in conti.most_common():
        print(f"  {k}: {n}")
    if not args.esegui:
        print("dry run: nothing downloaded, nothing written. To do it, pass --esegui")
        return 0

    oggi = datetime.now().strftime("%Y-%m-%d")
    esiti: Counter = Counter()
    for percorso, d in decisioni.items():
        cartella = Path(percorso).parent
        for fid in d["staccare"]:
            v = per_id[fid]
            v.update(
                downloaded=False,
                local_path="",
                skip_reason="collision: the file on disk is not its own",
            )
            v["collisione_sciolta_il"] = oggi
            esiti["detached"] += 1
        for fid in d["rifare"]:
            v, scheda = per_id[fid], schede[fid]
            if scheda.get("trashed"):
                v.update(downloaded=False, local_path="", skip_reason="trashed")
                v["collisione_sciolta_il"] = oggi
                esiti["in Drive trash"] += 1
                continue
            limite = max(int(scheda.get("size") or 0), dl.MAX_FILE_SIZE)
            r = dl.download_file(
                servizio(account_di(v)), scheda, cartella, include_media=False, max_size=limite
            )
            v["collisione_sciolta_il"] = oggi
            if r.get("downloaded"):
                v.update(
                    downloaded=True,
                    local_path=r["local_path"],
                    size=r.get("size", v.get("size")),
                    export_format=r.get("export_format"),
                    modifiedTime=scheda.get("modifiedTime", v.get("modifiedTime")),
                    skip_reason="",
                )
                esiti["re-downloaded"] += 1
            else:
                v.update(downloaded=False, local_path="", skip_reason=r.get("skip_reason") or "")
                esiti[f"not re-downloaded ({(r.get('skip_reason') or '?').split(':')[0]})"] += 1
    copia = INDICE.with_name(f"gdrive-index.json.bak-collisioni-{datetime.now():%Y%m%d-%H%M}")
    shutil.copy2(INDICE, copia)
    safe_write_json(INDICE, voci)
    for k, n in esiti.most_common():
        print(f"  {k}: {n}")
    print(f"✅ index written, the previous copy is {copia.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
