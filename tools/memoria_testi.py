""










from __future__ import annotations

import os
import sqlite3
import zlib
from pathlib import Path


SCHEDA = (
    "chiave",
    "modified",
    "md5",
    "percorso",
    "stato",
    "tipo",
    "lettore",
    "versione",
    "motivo",
    "letto_il",
    "caratteri",
)


def apri(percorso: Path, *, sola_lettura: bool = False) -> sqlite3.Connection:
    ""
    if sola_lettura:
        return sqlite3.connect(f"file:{percorso}?mode=ro", uri=True)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    nuovo = not percorso.exists()
    con = sqlite3.connect(percorso)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS testi (chiave TEXT PRIMARY KEY, modified TEXT, md5 TEXT, percorso TEXT, "
        "stato TEXT, tipo TEXT, lettore TEXT, versione TEXT, motivo TEXT, letto_il TEXT, caratteri INTEGER, "
        "testo BLOB)"
    )
    if nuovo:
        os.chmod(percorso, 0o600)
    return con


def _riga(r: dict) -> tuple:
    testo = r.get("testo") or ""
    return (
        r.get("chiave", ""),
        str(r.get("modified") or ""),
        r.get("md5") or "",
        r.get("percorso") or "",
        r.get("stato") or "",
        r.get("tipo") or "",
        r.get("lettore") or "",
        str(r.get("versione") or ""),
        r.get("motivo") or "",
        r.get("letto_il") or "",
        len(testo),
        zlib.compress(testo.encode("utf-8"), 6) if testo else None,
    )


def scrivi(con: sqlite3.Connection, righe: list[dict]) -> None:
    con.executemany(
        f"INSERT OR REPLACE INTO testi VALUES ({', '.join('?' * 12)})", [_riga(r) for r in righe]
    )
    con.commit()


def schede(con: sqlite3.Connection) -> dict[str, dict]:
    ""
    cur = con.execute(f"SELECT {', '.join(SCHEDA)} FROM testi")
    return {r[0]: dict(zip(SCHEDA, r, strict=True)) for r in cur}


def scheda(riga: dict) -> dict:
    ""
    return {
        **{k: riga.get(k) for k in SCHEDA if k != "caratteri"},
        "caratteri": len(riga.get("testo") or ""),
    }


def _testo(blob: bytes | None) -> str:
    return zlib.decompress(blob).decode("utf-8") if blob else ""


def testo_di(con: sqlite3.Connection, chiave: str) -> str:
    r = con.execute("SELECT testo FROM testi WHERE chiave = ?", (chiave,)).fetchone()
    return _testo(r[0]) if r else ""


def testi_per_chiave(
    con: sqlite3.Connection, chiavi: list[str], max_caratteri: int
) -> dict[str, str]:
    ""
    fuori: dict[str, str] = {}
    for i in range(0, len(chiavi), 500):
        gruppo = chiavi[i : i + 500]
        cur = con.execute(
            f"SELECT chiave, testo FROM testi WHERE chiave IN ({', '.join('?' * len(gruppo))})",
            gruppo,
        )
        for k, blob in cur:
            fuori[k] = _testo(blob)[:max_caratteri]
    return fuori
