#!/usr/bin/env python3
"""ClickUp L1: rereads the local ClickUp backup and writes tasks, people and documents as parquet files."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("cu-l1")

BACKUP = cfg.DATA_ROOT / "clickup" / "backup" / "spaces"



BACKUPS = [BACKUP, cfg.DATA_ROOT / "clickup" / "backup-confidential" / "spaces"]
# the other workspaces of a multi-workspace backup (clickup/backup-<id>/, see cu-l0-backup.py)
BACKUPS += sorted(
    p / "spaces"
    for p in (cfg.DATA_ROOT / "clickup").glob("backup-*")
    if p.is_dir() and p.name != "backup-confidential"
)
DEST = cfg.DATA_ROOT / "clickup" / "processed"


def _ms(v) -> str:
    ""




    if v in (None, "", 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(v) / 1000, UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _persona(d: dict | None) -> dict:
    if not isinstance(d, dict):
        return {}
    return {
        "id": str(d.get("id") or ""),
        "nome": d.get("username") or "",
        "email": (d.get("email") or "").lower(),
    }





TETTO_TESTO = 100_000


def _commenti(t: dict) -> str:
    ""
    righe = []
    for c in sorted(t.get("_comments") or [], key=lambda c: int(c.get("date") or 0)):
        testo = (c.get("comment_text") or "").strip()
        if testo:
            autore = _persona(c.get("user")).get("nome") or "?"
            righe.append(f"[{_ms(c.get('date'))[:10]} {autore}] {testo}")
        for r in sorted(c.get("_risposte") or [], key=lambda r: int(r.get("date") or 0)):
            testo_r = (r.get("comment_text") or "").strip()
            if testo_r:
                autore_r = _persona(r.get("user")).get("nome") or "?"
                righe.append(f"  ↳ [{_ms(r.get('date'))[:10]} {autore_r}] {testo_r}")
    return "\n".join(righe)[:TETTO_TESTO]


def leggi_task(f: Path) -> dict | None:
    try:
        t = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(t, dict) or not t.get("id"):
        return None
    stato = t.get("status") or {}
    creatore = _persona(t.get("creator"))
    assegnati = [_persona(a) for a in (t.get("assignees") or [])]
    return {
        "task_id": str(t.get("id")),
        "nome": t.get("name") or "",
        "testo": (t.get("text_content") or t.get("description") or "")[:TETTO_TESTO],
        "commenti_testo": _commenti(t),
        "stato": (stato.get("status") or "").lower(),




        "stato_tipo": (stato.get("type") or "").lower(),
        "archiviato": bool(t.get("archived")),
        "creato": _ms(t.get("date_created")),
        "aggiornato": _ms(t.get("date_updated")),
        "chiuso": _ms(t.get("date_closed")) or _ms(t.get("date_done")),
        "scadenza": _ms(t.get("due_date")),
        "inizio": _ms(t.get("start_date")),
        "priorita": ((t.get("priority") or {}) or {}).get("priority") or "",
        "creatore_id": creatore.get("id", ""),
        "creatore_nome": creatore.get("nome", ""),
        "creatore_email": creatore.get("email", ""),
        "assegnatari": [a["nome"] for a in assegnati if a.get("nome")],
        "assegnatari_email": [a["email"] for a in assegnati if a.get("email")],
        "n_assegnatari": len(assegnati),
        "lista": (t.get("list") or {}).get("name") or "",
        "lista_id": str((t.get("list") or {}).get("id") or ""),
        "cartella": (t.get("folder") or {}).get("name") or "",
        "space_id": str((t.get("space") or {}).get("id") or ""),
        "tag": [x.get("name") for x in (t.get("tags") or []) if isinstance(x, dict)],
        "url": t.get("url") or "",
        "padre": str(t.get("parent") or ""),
        "n_commenti": len(t.get("_comments") or []),

        "n_risposte": sum(int(c.get("reply_count") or 0) for c in t.get("_comments") or []),
        "n_tempi": len(t.get("_time_entries") or []),
    }



DOCS = [b.parent / "docs" for b in BACKUPS]


def _testo_pagine(pagine: list, livello: int = 0) -> list[str]:
    ""
    fuori = []
    for pg in pagine or []:
        if not isinstance(pg, dict):
            continue
        titolo = (pg.get("name") or "").strip()
        contenuto = (pg.get("content") or "").strip()
        if titolo:
            fuori.append(f"{'#' * min(livello + 1, 6)} {titolo}")
        if contenuto:
            fuori.append(contenuto)
        fuori += _testo_pagine(pg.get("pages") or [], livello + 1)
    return fuori


def leggi_documenti() -> list[dict]:
    ""
    righe = []
    for cartella in DOCS:
        if not cartella.exists():
            continue
        for f in cartella.glob("*.pages.json"):
            try:
                pagine = json.loads(f.read_text(encoding="utf-8")).get("pages")
                scheda_f = f.with_name(f.name.replace(".pages.json", ".json"))
                scheda = (
                    json.loads(scheda_f.read_text(encoding="utf-8")) if scheda_f.exists() else {}
                )
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(pagine, dict):
                pagine = pagine.get("pages") or []
            testo = "\n\n".join(_testo_pagine(pagine))
            creatore = scheda.get("creator")
            righe.append(
                {
                    "doc_id": f.name.removesuffix(".pages.json"),
                    "nome": scheda.get("name") or "",
                    "testo": testo[:TETTO_TESTO],
                    "creato": _ms(scheda.get("date_created")),
                    "aggiornato": _ms(scheda.get("date_updated")),
                    "creatore_id": str(creatore.get("id") or "")
                    if isinstance(creatore, dict)
                    else str(creatore or ""),
                    "archiviato": bool(scheda.get("archived")),
                    "workspace": cartella.parent.name,
                }
            )
    return righe


def nomi_degli_space() -> dict[str, str]:
    ""
    fuori = {}
    for d in (d for b in BACKUPS if b.exists() for d in b.iterdir()):
        f = d / "space.json"
        if f.is_file():
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                fuori[str(s.get("id") or d.name)] = s.get("name") or ""
            except (OSError, ValueError):
                continue
    return fuori


def rileggi(solo_aperti: bool = False) -> dict:
    import pandas as pd

    if not BACKUP.exists():
        log.error("no backup in %s, first run `cu-l0-backup.py --incremental`", BACKUP)
        return {}
    DEST.mkdir(parents=True, exist_ok=True)
    spaces = nomi_degli_space()

    righe, illeggibili = [], 0
    for f in (f for b in BACKUPS if b.exists() for f in b.rglob("tasks/*.json")):
        t = leggi_task(f)
        if t is None:
            illeggibili += 1
            continue
        t["space"] = spaces.get(t["space_id"], "")
        righe.append(t)

    if not righe:
        log.error("the backup exists but contains no readable tasks")
        return {}

    df = pd.DataFrame(righe)



    df["aperto"] = (~df["archiviato"]) & (~df["stato_tipo"].isin(["closed", "done"]))
    if solo_aperti:
        df = df[df["aperto"]].copy()

    cfg.safe_write_parquet(df, DEST / "tasks.parquet")



    conta: dict[str, dict] = {}
    for r in righe:
        if r["creatore_email"]:
            v = conta.setdefault(
                r["creatore_email"],
                {
                    "email": r["creatore_email"],
                    "nome": r["creatore_nome"],
                    "creati": 0,
                    "assegnati": 0,
                },
            )
            v["creati"] += 1
        for nome, mail in zip(r["assegnatari"], r["assegnatari_email"], strict=False):
            if not mail:
                continue
            v = conta.setdefault(mail, {"email": mail, "nome": nome, "creati": 0, "assegnati": 0})
            v["assegnati"] += 1
            if not v["nome"]:
                v["nome"] = nome
    persone = pd.DataFrame(list(conta.values()))
    cfg.safe_write_parquet(persone, DEST / "people.parquet")

    documenti = leggi_documenti()
    if documenti:
        cfg.safe_write_parquet(pd.DataFrame(documenti), DEST / "documents.parquet")

    aperti = int(df["aperto"].sum())
    return {
        "task": len(df),
        "aperti": aperti,
        "chiusi": len(df) - aperti,
        "con_assegnatario": int((df["n_assegnatari"] > 0).sum()),
        "con_scadenza": int((df["scadenza"] != "").sum()),
        "persone": len(persone),
        "documenti": len(documenti),
        "documenti_con_testo": sum(1 for d in documenti if d["testo"]),
        "space": df["space"].nunique(),
        "illeggibili": illeggibili,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "ClickUp L1: rereads the local ClickUp backup (cu-l0-backup.py) and writes tasks, "
            "people and documents as parquet files"
        )
    )
    ap.add_argument(
        "--open-only",
        action="store_true",
        dest="solo_aperti",
        help="keep only open tasks (not closed, not done, not archived) in tasks.parquet",
    )
    # Older Italian name, kept as a hidden alias.
    ap.add_argument("--solo-aperti", action="store_true", dest="solo_aperti", help=argparse.SUPPRESS)
    a = ap.parse_args()
    e = rileggi(solo_aperti=a.solo_aperti)
    if not e:
        return 1
    etichette = {
        "task": "tasks",
        "aperti": "open",
        "chiusi": "closed",
        "con_assegnatario": "with_assignee",
        "con_scadenza": "with_due_date",
        "persone": "people",
        "documenti": "documents",
        "documenti_con_testo": "documents_with_text",
        "space": "spaces",
        "illeggibili": "unreadable",
    }
    for k, v in e.items():
        log.info("  %-20s %s", etichette.get(k, k), f"{v:,}")
    log.info("  written to %s", DEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
