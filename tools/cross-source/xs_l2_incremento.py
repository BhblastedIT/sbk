#!/usr/bin/env python3
""


































































from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    KNOWLEDGE_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_META_DIR,
    safe_write_json,
)

log = logging.getLogger("sbk.knowledge-extract.incremento")












WATERMARK_FILE = KNOWLEDGE_META_DIR / "l2-ingestione-watermarks.json"





_ARCHIVIO_DIR = KNOWLEDGE_DIR / "archive"




_MAX_SALTI = 10

VUOTI = frozenset({"", "none", "nan", "nat", "null", "<na>"})


def _e_vuoto(v: object) -> bool:
    return str(v or "").strip().lower() in VUOTI




_SCHEMA_CONTATORI = {

    "id_offerti": 0,
    "id_usati": 0,
    "id_rediretti": 0,
    "id_scartati_inesistenti": 0,
    "nome_fallback": 0,

    "conio_redirette": 0,
    "conio_senza_uscita": 0,
    "conio_cicli": 0,
    "conio_split_ambiguo": 0,

    "righe_totali": 0,
    "righe_lette": 0,
    "righe_saltate": 0,
    "senza_marca": 0,
    "senza_marca_saltate": 0,
    "senza_marca_senza_chiave": 0,
    "senza_colonna": 0,

    "conio_rifiutato_ignoto": 0,
    "conio_rifiutato_relazione": 0,


    "conio_rifiutato_registro": 0,

    "conio_rifiutato_organizzazione": 0,

    "conio_rinascita_fermata": 0,
    "deposito_righe": 0,
    "deposito_fatti": 0,
}

CONTATORI: dict[str, int] = dict(_SCHEMA_CONTATORI)


def azzera_contatori() -> None:
    ""
    CONTATORI.clear()
    CONTATORI.update(_SCHEMA_CONTATORI)


def stats() -> dict[str, int]:
    ""
    return dict(CONTATORI)


def riga_di_log() -> str:
    ""
    c = CONTATORI
    return (
        f"increment: {c['righe_lette']}/{c['righe_totali']} rows read "
        f"(skipped {c['righe_saltate']}, unmarked {c['senza_marca']}) · "
        f"ids {c['id_offerti']} offered → {c['id_usati']} used, "
        f"{c['id_rediretti']} redirected, {c['id_scartati_inesistenti']} discarded, "
        f"{c['nome_fallback']} by name · coining: {c['conio_redirette']} rebirths "
        f"avoided, {c['conio_rinascita_fermata']} stopped (deposit), "
        f"{c['conio_senza_uscita']} without exit · "
        f"rejected {c['conio_rifiutato_ignoto']} unknown + "
        f"{c['conio_rifiutato_relazione']} relationship + "
        f"{c['conio_rifiutato_registro']} registry + "
        f"{c['conio_rifiutato_organizzazione']} organization → deposit "
        f"{c['deposito_righe']} rows / {c['deposito_fatti']} facts"
    )





class RegistroVivi:
    ""






    def __init__(self, radice: Path | None = None) -> None:
        self._radice = radice or KNOWLEDGE_ENTITIES_DIR
        self._per_tipo: dict[str, set[str]] = {}

    def _ids(self, tipo: str) -> set[str]:
        if tipo not in self._per_tipo:
            d = self._radice / tipo
            try:
                self._per_tipo[tipo] = {f[:-5] for f in os.listdir(d) if f.endswith(".json")}
            except OSError:
                self._per_tipo[tipo] = set()
            log.info("store %s/: %d live entities", tipo, len(self._per_tipo[tipo]))
        return self._per_tipo[tipo]

    def vivo(self, entity_id: str, tipo: str = "person") -> bool:
        if _e_vuoto(entity_id):
            return False
        return entity_id in self._ids(tipo)





class Archivio:
    ""






    def __init__(self, vivi: RegistroVivi, radice: Path | None = None) -> None:
        self._vivi = vivi
        self._radice = radice or _ARCHIVIO_DIR
        self._succ: dict[str, object] | None = None

    def _carica(self) -> dict[str, object]:
        if self._succ is not None:
            return self._succ
        succ: dict[str, object] = {}
        n = 0
        if self._radice.is_dir():
            for f in sorted(self._radice.rglob("*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(d, dict):
                    continue
                aid = str(d.get("entity_id") or f.stem)
                tgt = d.get("merged_into") or d.get("split_into")
                if not tgt:
                    continue
                n += 1
                succ[aid] = tgt
        self._succ = succ
        log.info("archive: %d records with a successor, %d distinct ids", n, len(succ))
        return succ

    def vive_qui(self, entity_id: str) -> bool:
        ""
        return entity_id in self._carica()

    def successore(self, entity_id: str, tipo: str = "person") -> str | None:
        ""



        succ = self._carica()
        visti: set[str] = set()
        cur = entity_id
        for _ in range(_MAX_SALTI):
            if cur in visti:
                CONTATORI["conio_cicli"] += 1
                return None
            visti.add(cur)
            tgt = succ.get(cur)
            if tgt is None:
                return None
            if isinstance(tgt, list):


                vivi = [str(t) for t in tgt if self._vivi.vivo(str(t), tipo)]
                if len(vivi) == 1:
                    return vivi[0]
                CONTATORI["conio_split_ambiguo"] += 1
                return None
            cur = str(tgt)
            if self._vivi.vivo(cur, tipo):
                return cur
        return None





def id_da_riga(
    entity_id: str | None,
    vivi: RegistroVivi,
    archivio: Archivio | None = None,
    tipo: str = "person",
) -> str | None:
    ""





    if _e_vuoto(entity_id):
        return None
    eid = str(entity_id).strip()
    CONTATORI["id_offerti"] += 1
    if vivi.vivo(eid, tipo):
        CONTATORI["id_usati"] += 1
        return eid
    if archivio is not None:
        s = archivio.successore(eid, tipo)
        if s:
            CONTATORI["id_rediretti"] += 1
            return s
    CONTATORI["id_scartati_inesistenti"] += 1
    return None


def redirige_al_conio(
    entity_id: str,
    vivi: RegistroVivi,
    archivio: Archivio,
    tipo: str = "person",
) -> str:
    ""











    if vivi.vivo(entity_id, tipo):
        return entity_id
    if not archivio.vive_qui(entity_id):
        return entity_id
    s = archivio.successore(entity_id, tipo)
    if s:
        CONTATORI["conio_redirette"] += 1
        return s
    CONTATORI["conio_senza_uscita"] += 1
    log.warning(
        "ARCHIVE: %s is archived and the chain doesn't lead to a live id: coined "
        "again (rebirth unavoidable without a deposit)",
        entity_id,
    )
    return entity_id





def puo_avanzare(dry_run: bool, entity_id: str | None, domain: str | None) -> bool:
    ""







    return not dry_run and not entity_id and not domain


class Watermark:
    ""











    COLONNA = "extracted_at"






    CHIAVE = "fact_id"

    def __init__(self, percorso: Path | None = None) -> None:
        self._percorso = percorso or WATERMARK_FILE
        self._stato = self._leggi()
        self._proposte: dict[str, str] = {}
        self._proposte_impronta: dict[str, str] = {}

    def _leggi(self) -> dict:
        try:
            d = json.loads(self._percorso.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("sorgenti"), dict):
                return d
        except (OSError, ValueError):
            pass
        return {"version": 1, "sorgenti": {}}

    def ultimo(self, sorgente: str) -> str | None:
        v = self._stato["sorgenti"].get(sorgente, {}).get("ultimo_extracted_at")
        return v if isinstance(v, str) and v else None

    def impronta(self, sorgente: str) -> str | None:
        ""
        v = self._stato["sorgenti"].get(sorgente, {}).get("impronta_senza_marca")
        return v if isinstance(v, str) and v else None

    def _impronta_di(self, df: pd.DataFrame, senza: pd.Series) -> str | None:
        ""






        if self.CHIAVE not in df.columns:
            return None
        chiavi = df.loc[senza, self.CHIAVE].astype(str)
        h = hashlib.sha256()
        h.update(f"{len(chiavi)}|".encode())
        for k in sorted(chiavi.tolist()):
            h.update(k.encode("utf-8", "replace"))
            h.update(b"\x00")
        return h.hexdigest()

    def filtra(self, df: pd.DataFrame, sorgente: str) -> pd.DataFrame:
        ""











        CONTATORI["righe_totali"] += len(df)
        if self.COLONNA not in df.columns:
            CONTATORI["senza_colonna"] += len(df)
            CONTATORI["righe_lette"] += len(df)
            log.warning(
                "watermark %s: column %s absent — reading everything (%d rows)",
                sorgente,
                self.COLONNA,
                len(df),
            )
            return df

        marca = pd.to_datetime(df[self.COLONNA], utc=True, errors="coerce", format="mixed")
        senza = marca.isna()
        ultimo = self.ultimo(sorgente)
        if ultimo is None:
            tieni = pd.Series(True, index=df.index)
        else:
            try:
                soglia = pd.Timestamp(ultimo)
                if soglia.tzinfo is None:
                    soglia = soglia.tz_localize("UTC")
            except (ValueError, TypeError):
                log.warning(
                    "watermark %s: threshold unreadable (%r) — reading everything", sorgente, ultimo
                )
                soglia = None
            tieni = pd.Series(True, index=df.index) if soglia is None else (marca > soglia)












        n_senza = int(senza.sum())
        n_senza_saltate = 0
        impronta_ora = None
        if n_senza:
            impronta_ora = self._impronta_di(df, senza)
            if impronta_ora is None:
                CONTATORI["senza_marca_senza_chiave"] += n_senza
            elif impronta_ora == self.impronta(sorgente):
                n_senza_saltate = n_senza
                senza = pd.Series(False, index=df.index)
        tieni = tieni | senza



        if marca.notna().any():
            self._proposte[sorgente] = marca.max().isoformat()
        if impronta_ora is not None:
            self._proposte_impronta[sorgente] = impronta_ora

        n_tieni = int(tieni.sum())
        CONTATORI["senza_marca"] += n_senza - n_senza_saltate
        CONTATORI["senza_marca_saltate"] += n_senza_saltate
        CONTATORI["righe_lette"] += n_tieni
        CONTATORI["righe_saltate"] += len(df) - n_tieni
        log.info(
            "watermark %s: %d rows → %d to read (%d skipped, %d unmarked "
            "passed, %d unmarked already seen), threshold %s",
            sorgente,
            len(df),
            n_tieni,
            len(df) - n_tieni,
            n_senza - n_senza_saltate,
            n_senza_saltate,
            ultimo or "none (first run)",
        )
        return df[tieni]

    def salva(self) -> None:
        ""
        if not self._proposte and not self._proposte_impronta:
            return
        now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
        for sorgente, proposto in self._proposte.items():
            voce = self._stato["sorgenti"].setdefault(sorgente, {})
            prec = voce.get("ultimo_extracted_at")
            if isinstance(prec, str) and prec >= proposto:
                continue
            voce["ultimo_extracted_at"] = proposto
            voce["aggiornato"] = now


        for sorgente, imp in self._proposte_impronta.items():
            voce = self._stato["sorgenti"].setdefault(sorgente, {})
            voce["impronta_senza_marca"] = imp
            voce["aggiornato"] = now
        self._stato["version"] = 1
        KNOWLEDGE_META_DIR.mkdir(parents=True, exist_ok=True)
        safe_write_json(self._percorso, self._stato, indent=2, ensure_ascii=True, fsync=True)
        log.info("watermark saved: %s", self._percorso)
