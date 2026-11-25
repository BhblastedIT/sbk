#!/usr/bin/env python3
"""Drive cleanup: delete local copies of Drive files older than the Drive period whose text is already read and stored, after checking each one against Drive (dry run unless --esegui)."""

























from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

GDRIVE = DATA_ROOT / "gdrive"
INDICE = GDRIVE / "gdrive-index.json"
MEMORIA = GDRIVE / "processed" / "testi.sqlite"
TOLTI = GDRIVE / "processed" / "tolti.jsonl"

SEGRETI = re.compile(
    r"password|passw|filevault|chiavi|credenzial|utenze|\bpec\b|\bseed\b", re.IGNORECASE
)
CAMPI = "id,md5Checksum,modifiedTime,trashed"


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


def candidati(
    voci: list[dict], memoria: dict[str, tuple], limite_iso: str
) -> tuple[list[tuple[dict, str]], Counter]:
    ""

    fuori, conti = [], Counter()
    for v in voci:
        p = v.get("local_path")
        if not (v.get("downloaded") and p and os.path.exists(p)):
            continue
        if str(v.get("modifiedTime", "")) >= limite_iso:
            conti["within the retention period"] += 1
            continue
        if SEGRETI.search(f"{v.get('folder_path', '')}/{v.get('name', '')}"):
            conti["password/keys folder"] += 1
            continue
        m = memoria.get(v["id"])
        if m is None:
            conti["not in the text memory"] += 1
            continue
        modified, md5_letto, percorso, stato, caratteri = m
        if stato != "letto" or not caratteri:
            conti[f"no text, {stato}"] += 1
            continue
        if modified != str(v.get("modifiedTime", "")) or percorso != p:
            conti["memory is of another version or another file"] += 1
            continue
        md5 = md5_file(Path(p))
        if md5_letto != md5:
            conti["the file on disk is not the one that was read"] += 1
            continue
        fuori.append((v, md5))
    return fuori, conti


def per_file(
    via: list[tuple[dict, str]], voci: list[dict]
) -> tuple[dict[str, list[tuple[dict, str]]], int]:
    ""

    usano = Counter(v["local_path"] for v in voci if v.get("downloaded") and v.get("local_path"))
    gruppi: dict[str, list[tuple[dict, str]]] = {}
    for v, md5 in via:
        gruppi.setdefault(v["local_path"], []).append((v, md5))
    restano = 0
    for percorso in list(gruppi):
        if len(gruppi[percorso]) < usano[percorso]:
            restano += len(gruppi.pop(percorso))
    return gruppi, restano


def togli(
    gruppi: dict[str, list[tuple[dict, str]]], registro: Path, oggi: str
) -> tuple[int, int, int]:
    ""

    file_tolti = voci_marcate = byte = 0
    with registro.open("a", encoding="utf-8") as f:
        for percorso, gruppo in gruppi.items():
            p = Path(percorso)
            peso = p.stat().st_size if p.exists() else 0
            for i, (v, md5) in enumerate(gruppo):
                riga = {
                    "id": v["id"],
                    "percorso": percorso,
                    "byte": peso if i == 0 else 0,
                    "md5": md5,
                    "modified": v.get("modifiedTime"),
                    "tolto_il": datetime.now(UTC).isoformat(timespec="seconds"),
                    "perche": "read into the text memory, outside the retention period, confirmed by Drive",
                }
                if i:
                    riga["stesso_file_di"] = gruppo[0][0]["id"]
                f.write(json.dumps(riga, ensure_ascii=False) + "\n")
            f.flush()
            if p.exists():
                p.unlink()
                file_tolti += 1
                byte += peso
            for v, _ in gruppo:
                v["tolto_il"] = oggi
                voci_marcate += 1
    os.chmod(registro, 0o600)
    return file_tolti, voci_marcate, byte


def riallinea(voci: list[dict], registro: Path) -> int:
    ""

    if not registro.exists():
        return 0
    quando = {}
    for r in registro.read_text(encoding="utf-8").splitlines():
        if r.strip():
            d = json.loads(r)
            quando[d["id"]] = d["tolto_il"][:10]
    n = 0
    for v in voci:
        fid = v.get("id")
        if (
            fid in quando
            and not v.get("tolto_il")
            and not os.path.exists(v.get("local_path") or "")
        ):
            v["tolto_il"] = quando[fid]
            n += 1
    return n


def confermato(voce: dict, scheda: dict | None, md5_locale: str) -> bool:
    ""
    if not scheda or scheda.get("trashed"):
        return False
    if scheda.get("md5Checksum"):
        return scheda["md5Checksum"] == md5_locale
    return bool(voce.get("export_format")) and scheda.get("modifiedTime") == voce.get(
        "modifiedTime"
    )


def _scaricatore():
    nome = "gd_l0_download_pulizia"
    spec = importlib.util.spec_from_file_location(nome, _TOOLS_DIR / "gdrive" / "gd-l0-download.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


def schede_da_drive(servizio, ids: list[str], log) -> dict[str, dict | None]:
    ""

    from googleapiclient.errors import HttpError

    schede: dict[str, dict | None] = {}
    da_rifare: list[str] = []

    def risposta(rid, resp, err):
        if err is None:
            schede[rid] = resp
            return
        stato = int(getattr(getattr(err, "resp", None), "status", 0) or 0)
        if stato == 404:
            schede[rid] = None
        else:
            da_rifare.append(rid)

    for giro in (1, 2):
        lista = ids if giro == 1 else list(da_rifare)
        da_rifare.clear()
        for i in range(0, len(lista), 100):
            lotto = servizio.new_batch_http_request(callback=risposta)
            for fid in lista[i : i + 100]:
                lotto.add(
                    servizio.files().get(fileId=fid, fields=CAMPI, supportsAllDrives=True),
                    request_id=fid,
                )
            try:
                lotto.execute()
            except HttpError as e:
                log(f"  batch failed ({e}), retrying later")
                da_rifare.extend(lista[i : i + 100])
        if not da_rifare:
            break
        time.sleep(60)
    if da_rifare:
        log(f"  {len(da_rifare)} files with no response from Drive: kept on disk")
    return schede


def _al_lavoro() -> bool:
    ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
    return any(
        any(s in r for s in ("gd-l0-download.py", "gd-l1-enrich.py", "gd-collisioni.py"))
        for r in ps.splitlines()
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Drive cleanup of files outside the period"])[0]
    )
    ap.add_argument(
        "--esegui", action="store_true", help="remove the files and write the index (without it: dry run)"
    )
    args = ap.parse_args()
    if _al_lavoro():
        print(
            "⛔ Drive downloader, reader or collision tool is running: retry when they have finished"
        )
        return 2

    import impostazioni_pipeline

    giorni = impostazioni_pipeline.leggi()["drive"]["giorni"]
    if giorni <= 0:
        print(
            "⛔ the Drive period is \"full history\": nothing is outside the period, nothing is removed"
        )
        return 2
    limite = (datetime.now(UTC) - timedelta(days=giorni)).strftime("%Y-%m-%dT%H:%M:%S")
    voci = json.loads(INDICE.read_text(encoding="utf-8"))
    senza_marca = riallinea(voci, TOLTI)
    if senza_marca:
        quando = "will be marked" if args.esegui else "will be marked with --esegui"
        print(f"entries already removed that the index did not know: {senza_marca} ({quando})")
    con = sqlite3.connect(f"file:{MEMORIA}?mode=ro", uri=True)
    memoria = {
        r[0]: r[1:]
        for r in con.execute("SELECT file_id, modified, md5, percorso, stato, caratteri FROM testi")
    }
    con.close()
    fuori, conti = candidati(voci, memoria, limite)
    peso = sum(os.path.getsize(p) for p in {v["local_path"] for v, _ in fuori})
    print(
        f"period {giorni} days (until {limite[:10]}): {len(fuori)} candidates, {peso / 1e9:.2f} GB"
    )
    for k, n in conti.most_common():
        print(f"  kept, {k}: {n}")

    dl = _scaricatore()
    conosciuti = dl.get_known_accounts()
    per_account: dict[str, list[tuple[dict, str]]] = {}
    for v, md5 in fuori:
        per_account.setdefault(account_di(v), []).append((v, md5))
    via: list[tuple[dict, str]] = []
    esiti: Counter = Counter()
    for account, gruppo in per_account.items():
        servizio = dl.build_service(account, conosciuti.get(account, ""))
        if servizio is None:
            esiti[f"account {account} without credentials, kept"] += len(gruppo)
            continue
        schede = schede_da_drive(servizio, [v["id"] for v, _ in gruppo], print)
        for v, md5 in gruppo:
            if v["id"] not in schede:
                esiti["Drive did not respond, kept"] += 1
            elif confermato(v, schede[v["id"]], md5):
                via.append((v, md5))
            else:
                esiti["Drive does not confirm (changed, trashed or gone), kept"] += 1
    gruppi, restano = per_file(via, voci)
    peso_via = sum(os.path.getsize(p) for p in gruppi)
    print(
        f"confirmed by Drive: {sum(len(g) for g in gruppi.values())} entries, {len(gruppi)} files, "
        f"{peso_via / 1e9:.2f} GB"
    )
    for k, n in esiti.most_common():
        print(f"  {k}: {n}")
    if restano:
        print(f"  the file is also used by an entry that stays, kept: {restano}")
    if not args.esegui:
        print("dry run: nothing removed, nothing written. To do it, pass --esegui")
        return 0

    copia = INDICE.with_name(f"gdrive-index.json.bak-pulizia-{datetime.now():%Y%m%d-%H%M}")
    shutil.copy2(INDICE, copia)
    try:
        file_tolti, marcate, byte = togli(gruppi, TOLTI, datetime.now().strftime("%Y-%m-%d"))
    finally:

        safe_write_json(INDICE, voci)
    print(
        f"✅ removed {file_tolti} files ({byte / 1e9:.2f} GB), {marcate} entries marked; log {TOLTI.name}; "
        f"previous index {copia.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
