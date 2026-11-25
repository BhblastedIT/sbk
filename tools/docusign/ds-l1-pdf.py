#!/usr/bin/env python3
"""Extract text from downloaded DocuSign PDFs (L1)."""











from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import memoria_testi as M  # noqa: E402

from sbk_config import DOCUSIGN_RAW_DIR, mark_last_run  # noqa: E402

log = logging.getLogger("ds-l1-pdf")

INDICE = DOCUSIGN_RAW_DIR / "pdf" / "indice.parquet"
BUSTE = DOCUSIGN_RAW_DIR / "raw" / "envelopes-api.json"
MEMORIA = DOCUSIGN_RAW_DIR / "processed" / "pdf-testi.sqlite"
USCITA = DOCUSIGN_RAW_DIR / "processed" / "contratti-testo.parquet"

TETTO_MEMORIA = 2_000_000
MAX_CHARS = 100_000
SCRIVI_OGNI = 100
IN_VOLO_PER_LETTORE = 4


def firma(p: Path) -> str:
    ""
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def _leggi_uno(percorso: str) -> dict:
    from lettura_documenti import leggi_bytes

    p = Path(percorso)
    dati = p.read_bytes()
    r = leggi_bytes(p.name, dati, 0, TETTO_MEMORIA)
    return {
        "chiave": percorso,
        "modified": firma(p),
        "md5": hashlib.md5(dati).hexdigest(),
        "percorso": percorso,
        "stato": r.esito,
        "tipo": r.tipo,
        "lettore": r.lettore,
        "versione": r.versione,
        "testo": r.testo,
        "motivo": r.motivo,
        "letto_il": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def da_leggere(percorsi: list[str], schede: dict[str, dict]) -> list[str]:
    ""
    from lettura_documenti import VERSIONI

    fuori = []
    for p in percorsi:
        if not os.path.exists(p):
            continue
        s = schede.get(p)
        if (
            s is None
            or s.get("stato") == "errore"
            or s.get("modified") != firma(Path(p))
            or s.get("versione") != VERSIONI.get(s.get("tipo") or "", "1")
        ):
            fuori.append(p)
    return fuori


def leggi(con, percorsi: list[str], schede: dict[str, dict], lavoratori: int) -> int:
    ""
    coda = iter(percorsi)
    in_volo: dict = {}
    righe: list[dict] = []
    letti = 0
    with ThreadPoolExecutor(max_workers=lavoratori) as pool:
        while True:
            while len(in_volo) < lavoratori * IN_VOLO_PER_LETTORE:
                p = next(coda, None)
                if p is None:
                    break
                in_volo[pool.submit(_leggi_uno, p)] = p
            if not in_volo:
                break
            finiti, _ = wait(in_volo, return_when=FIRST_COMPLETED)
            for f in finiti:
                p = in_volo.pop(f)
                try:
                    riga = f.result()
                except Exception as e:  # noqa: BLE001 - a file that crashes the reader does not stop the others
                    riga = {
                        "chiave": p,
                        "percorso": p,
                        "stato": "errore",
                        "motivo": type(e).__name__,
                    }
                righe.append(riga)
                schede[p] = M.scheda(riga)
                letti += 1
            if len(righe) >= SCRIVI_OGNI:
                M.scrivi(con, righe)
                righe = []
                log.info(f"  read {letti}/{len(percorsi)}")
    if righe:
        M.scrivi(con, righe)
    return letti


def firmatari(buste_path: Path = BUSTE) -> dict[str, str]:
    ""
    try:
        buste = json.loads(buste_path.read_text(encoding="utf-8")).get("envelopes") or []
    except (OSError, ValueError):
        return {}
    fuori = {}
    for b in buste:
        persone = []
        for gruppo in (b.get("recipients") or {}).values():
            if not isinstance(gruppo, list):
                continue
            for r in gruppo:
                nome, email = (r.get("name") or "").strip(), (r.get("email") or "").strip().lower()
                if nome or email:
                    persone.append(f"{nome} <{email}>" if email else nome)
        mittente = b.get("sender") or {}
        if mittente.get("email"):
            persone.insert(
                0, f"{mittente.get('userName', '')} <{mittente['email'].lower()}>".strip()
            )
        fuori[b.get("envelopeId")] = ", ".join(dict.fromkeys(persone))
    return fuori


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--incremental", action="store_true", help="skip if the PDF index has not changed"
    )
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )
    if not INDICE.exists():
        log.info("No DocuSign PDF downloaded yet: nothing to read")
        return 0
    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("docusign-pdf-l1", [INDICE]):
            log.info("Incremental: the PDF index has not changed, skipping")
            mark_last_run("docusign-pdf-l1")
            return 0

    indice = pd.read_parquet(INDICE)
    indice = indice[indice["stato"] == "scaricato"].copy()
    con = M.apri(MEMORIA)
    schede = M.schede(con)
    percorsi = sorted(set(indice["percorso"]))
    nuovi = da_leggere(percorsi, schede)
    try:
        from sbk_resources import cpu_workers

        lavoratori = cpu_workers()
    except ImportError:  # pragma: no cover
        lavoratori = 2
    log.info(f"Contracts: {len(percorsi)} PDF, to read {len(nuovi)}, {lavoratori} at a time")
    leggi(con, nuovi, schede, max(1, lavoratori))
    chi = firmatari()
    testi = M.testi_per_chiave(con, percorsi, MAX_CHARS)
    con.close()
    indice["partecipanti"] = indice["envelopeId"].map(chi).fillna("")
    indice["esito_lettura"] = indice["percorso"].map(
        lambda p: (schede.get(p) or {}).get("stato") or "non_letto"
    )
    indice["lettore"] = indice["percorso"].map(lambda p: (schede.get(p) or {}).get("lettore") or "")
    indice["content_text"] = indice["percorso"].map(testi).fillna("")
    colonne = [
        "envelopeId", "status", "oggetto", "inviata", "cambiata", "partecipanti", "percorso", "byte",
        "esito_lettura", "lettore", "content_text",
    ]
    from sbk_config import safe_write_parquet, save_input_checkpoint

    safe_write_parquet(indice[colonne], USCITA, index=False)
    os.chmod(USCITA, 0o600)
    log.info(
        f"Wrote {USCITA.name}: {len(indice)} contracts, {int((indice['content_text'] != '').sum())} with text"
    )
    save_input_checkpoint("docusign-pdf-l1", [INDICE])
    mark_last_run("docusign-pdf-l1")
    return 0


from pipeline_decorator import pipeline_step  # noqa: E402


@pipeline_step(name="l1-docusign-pdf", source="docusign-pdf-l1", stage="l1")
def run():

    codice = main()
    if codice:
        sys.exit(codice)


if __name__ == "__main__":
    run()
