#!/usr/bin/env python3
"""Read-only, run by hand: who can reach the files of your shared drives with the link alone, and what they can do with them."""
































































from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("sc-permessi")

# Your own Drive login, the one stored by tools/gdrive/gd-l0-auth.py (Keychain
# service "sbk-gdrive"). The scan sees the shared drives you are a member of.
ACCOUNT_DEFAULT = "default"





SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]



CHE_SCRIVONO = {"writer", "fileOrganizer", "organizer", "owner"}



VISIBILITA_PUBBLICHE = ["anyoneWithLink", "anyoneCanFind"]


_ACCOUNT = {"nome": ACCOUNT_DEFAULT}


def _drive():
    import google_oauth
    from googleapiclient.discovery import build

    nome = _ACCOUNT["nome"]
    creds = google_oauth.stored_credentials("sbk-gdrive", nome)
    if creds is None:
        raise SystemExit(
            f"No Drive login for '{nome}'. Run: python3 tools/gdrive/gd-l0-auth.py --account {nome}"
        )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


_locale = threading.local()


def _drive_del_thread():
    ""

    if not hasattr(_locale, "svc"):
        _locale.svc = _drive()
    return _locale.svc


def _pagine(metodo, chiave: str, **kw):
    ""

    token = None
    while True:
        r = metodo(**({"pageToken": token} if token else {}), **kw).execute()
        yield from r.get(chiave) or []
        token = r.get("nextPageToken")
        if not token:
            return


def cartelle_del_drive(svc, drive_id: str) -> dict[str, tuple[str, str]]:
    ""




    fuori = {}
    for f in _pagine(
        svc.files().list,
        "files",
        q="mimeType='application/vnd.google-apps.folder' and trashed=false",
        corpora="drive",
        driveId=drive_id,
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="nextPageToken,files(id,name,parents)",
        pageSize=1000,
    ):
        gen = (f.get("parents") or [None])[0]
        fuori[f["id"]] = (f.get("name", ""), gen)
    return fuori


def percorso(pid: str, cartelle: dict) -> str:
    ""

    pezzi, visti = [], set()
    while pid and pid in cartelle and pid not in visti:
        visti.add(pid)
        nome, pid = cartelle[pid]
        pezzi.append(nome)
    return "/".join(reversed(pezzi)) or "(drive root)"


def file_pubblici(svc, drive_id: str) -> list[dict]:
    visti: dict[str, dict] = {}
    for vis in VISIBILITA_PUBBLICHE:
        for f in _pagine(
            svc.files().list,
            "files",
            q=f"visibility='{vis}' and trashed=false",
            corpora="drive",
            driveId=drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="nextPageToken,files(id,name,mimeType)",
            pageSize=1000,
        ):


            visti[f["id"]] = f
    return list(visti.values())


def analizza_drive(svc, drive_id: str, nome_drive: str, paralleli: int = 8) -> dict:
    pubblici = file_pubblici(svc, drive_id)
    log.info("  %s: %d files reachable by link", nome_drive, len(pubblici))
    if not pubblici:
        return {
            "drive": nome_drive,
            "drive_id": drive_id,
            "pubblici": 0,
            "ereditati": {},
            "diretti": [],
            "non_letti": [],
        }

    cartelle = cartelle_del_drive(svc, drive_id)
    ereditati: dict[tuple[str, str], int] = defaultdict(int)
    diretti: list[dict] = []
    non_letti: list[dict] = []

    def permessi_di(f: dict):
        try:
            return (
                f,
                (
                    _drive_del_thread()
                    .permissions()
                    .list(
                        fileId=f["id"],
                        supportsAllDrives=True,
                        fields="permissions(type,role,emailAddress,permissionDetails)",
                    )
                    .execute()
                    .get("permissions", [])
                ),
                None,
            )
        except Exception as e:  # noqa: BLE001
            return f, [], str(e)[:160]

    with ThreadPoolExecutor(max_workers=paralleli) as pool:
        for i, (f, perms, errore) in enumerate(pool.map(permessi_di, pubblici), 1):
            if errore:

                non_letti.append({"id": f["id"], "nome": f.get("name", ""), "motivo": errore})
                continue
            for p in perms:
                if p.get("type") != "anyone":
                    continue
                det = (p.get("permissionDetails") or [{}])[0]
                if det.get("inherited"):


                    ereditati[(det.get("inheritedFrom", ""), p.get("role", ""))] += 1
                else:
                    diretti.append(
                        {
                            "id": f["id"],
                            "nome": f.get("name", ""),
                            "ruolo": p.get("role", ""),
                            "mime": f.get("mimeType", ""),
                        }
                    )
            if i % 2000 == 0:
                log.info("    ...%d/%d", i, len(pubblici))

    return {
        "drive": nome_drive,
        "drive_id": drive_id,
        "pubblici": len(pubblici),
        "ereditati": {
            f"{src}|{ruolo}": {
                "quanti": n,
                "cartella": cartelle.get(src, ("(outside this drive)", None))[0],
                "percorso": percorso(src, cartelle),
                "id": src,
                "ruolo": ruolo,
            }
            for (src, ruolo), n in sorted(ereditati.items(), key=lambda kv: -kv[1])
        },
        "diretti": diretti,
        "non_letti": non_letti,
    }


def stampa(r: dict) -> None:
    er = r["ereditati"]
    tot_er = sum(v["quanti"] for v in er.values())
    radici = {v["id"] for v in er.values()}


    diretti_veri = [d for d in r["diretti"] if d["id"] not in radici]
    scriv = sum(v["quanti"] for v in er.values() if v["ruolo"] in CHE_SCRIVONO)
    scriv += sum(1 for d in r["diretti"] if d["ruolo"] in CHE_SCRIVONO)

    print(f"\n{'=' * 78}\n{r['drive']}\n{'=' * 78}")
    print(f"  files reachable by link      : {r['pubblici']}")
    print(f"  of which WRITABLE by anyone  : {scriv}", end="")
    if r["pubblici"]:
        print(f"  ({100 * scriv / r['pubblici']:.1f}%)")
    else:
        print()
    print(f"\n  inherited from {len(radici)} folders : {tot_er}   -> {len(radici)} revocations")
    print(f"  direct permission on files  : {len(diretti_veri)}   -> one by one")
    if r["non_letti"]:
        print(f"  ⚠️ NOT READ                  : {len(r['non_letti'])}  (excluded from the counts above)")

    if er:
        print("\n  The folders, in order of effect:")
        for v in sorted(er.values(), key=lambda x: -x["quanti"]):
            avviso = "  ⚠️ WRITE" if v["ruolo"] in CHE_SCRIVONO else ""
            print(f"    {v['quanti']:6d}  {v['ruolo']:<14}{avviso}")
            print(f"            {v['percorso']}")
            print(f"            id={v['id']}")
    if diretti_veri:
        c = Counter(d["ruolo"] for d in diretti_veri)
        print(f"\n  The {len(diretti_veri)} direct ones, by role: {dict(c)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--account",
        default=ACCOUNT_DEFAULT,
        help="the Drive login saved by gd-l0-auth.py --account <name> (default: %(default)s)",
    )
    ap.add_argument("--drive", help="filter the drives by substring of the name")
    ap.add_argument("--json", type=Path, help="writes the raw data, drive by drive")
    ap.add_argument(
        "--paralleli",
        type=int,
        default=8,
        help="calls in flight together (default 8). These are network waits, not computation.",
    )
    a = ap.parse_args()
    _ACCOUNT["nome"] = a.account

    svc = _drive()
    drives = list(
        _pagine(svc.drives().list, "drives", fields="nextPageToken,drives(id,name)", pageSize=100)
    )
    if a.drive:
        drives = [d for d in drives if a.drive.lower() in d["name"].lower()]
    log.info("Shared drives to examine: %d", len(drives))

    def deposita():
        ""

        if not a.json:
            return
        a.json.write_text(
            json.dumps(
                {"misurato_il": datetime.now(UTC).isoformat(), "drive": fuori},
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    fuori = []
    for d in drives:
        try:
            fuori.append(analizza_drive(svc, d["id"], d["name"], a.paralleli))
        except Exception as e:  # noqa: BLE001
            log.warning("  %s: NOT examined (%s)", d["name"], str(e)[:120])
            fuori.append({"drive": d["name"], "drive_id": d["id"], "errore": str(e)[:200]})
        deposita()

    for r in fuori:
        if "errore" in r:
            print(f"\n{r['drive']}: NOT EXAMINED — {r['errore']}")
        else:
            stampa(r)

    esaminati = [r for r in fuori if "errore" not in r]
    saltati = len(fuori) - len(esaminati)
    tot = sum(r["pubblici"] for r in esaminati)
    non_letti = sum(len(r["non_letti"]) for r in esaminati)
    print(f"\n{'=' * 78}")
    print(f"TOTAL: {tot} public files across {len(esaminati)} drives examined")
    if saltati:
        print(f"⚠️ {saltati} drives NOT examined: the total above does not include them")
    if non_letti:
        print(f"⚠️ {non_letti} unreadable files: excluded from the total")

    if a.json:
        log.info("raw data in %s", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
