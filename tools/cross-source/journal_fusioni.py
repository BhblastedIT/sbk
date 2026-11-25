""













































from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

CARTELLA = cfg.DATA_ROOT / "knowledge" / "meta"


def impronta(fatto: dict) -> str:
    ""




    sorgente = (fatto.get("source") or {}).get("source_file") or ""
    grezzo = "|".join(
        [
            str(fatto.get("attribute") or ""),
            str(fatto.get("value") or "").strip().lower(),
            str(sorgente),
            str((fatto.get("source") or {}).get("record_id") or ""),
        ]
    )
    return hashlib.sha1(grezzo.encode()).hexdigest()[:16]  # noqa: S324


class Journal:
    ""

    def __init__(self, script: str, *, attivo: bool = True, cartella: Path | None = None):
        self.script = script
        self.attivo = attivo
        self.cartella = cartella or CARTELLA
        self.percorso: Path | None = None
        self._fh = None
        self.righe = 0

    def __enter__(self) -> Journal:
        if self.attivo:
            self.cartella.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            self.percorso = self.cartella / f"fusioni-{self.script}-{ts}.jsonl"
            self._fh = self.percorso.open("a", encoding="utf-8")
            self._scrivi({"tipo": "inizio", "script": self.script})
        return self

    def __exit__(self, *_) -> None:
        if self._fh:
            self._scrivi({"tipo": "fine", "righe": self.righe})
            self._fh.close()
            self._fh = None

    def _scrivi(self, record: dict) -> None:
        if not self._fh:
            return
        record["quando"] = datetime.now(UTC).isoformat()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")


        self._fh.flush()
        self.righe += 1

    def fusione(self, canonico: str, fuso: str, *, motivo: str, punteggi: dict | None = None):
        ""
        self._scrivi(
            {
                "tipo": "fusione",
                "canonico": canonico,
                "fuso": fuso,
                "motivo": motivo,
                "punteggi": punteggi or {},
            }
        )
        if self._fh:
            os.fsync(self._fh.fileno())

    def fatto(self, f: dict, *, da: str, a: str) -> None:
        ""
        self._scrivi(
            {
                "tipo": "fatto",
                "fact_id": f.get("fact_id") or "",
                "impronta": impronta(f),
                "attributo": f.get("attribute"),
                "da": da,
                "a": a,
            }
        )

    def fatto_scartato(self, f: dict, *, da: str, perche: str) -> None:
        ""


        self._scrivi(
            {
                "tipo": "scartato",
                "fact_id": f.get("fact_id") or "",
                "impronta": impronta(f),
                "attributo": f.get("attribute"),
                "valore": str(f.get("value") or "")[:200],
                "sorgente": (f.get("source") or {}).get("source_type"),
                "da": da,
                "perche": perche,
            }
        )

    def nota(self, **campi) -> None:
        self._scrivi({"tipo": "nota", **campi})
