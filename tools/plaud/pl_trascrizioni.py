""
















from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol


SOGLIA_SECONDI = 40


MINUTI_GIORNO = 1200

IN_VOLO = 3

ATTESA_MAX_S = 20 * 60

PASSO_S = 15

TENTATIVI_MAX = 3
ATTESA_RIFIUTATA = timedelta(hours=24)

INFO_APP = '{"language":"auto","diarization":1,"llm":"auto"}'


PRONTA, IN_CORSO, RIFIUTATA = "pronta", "in_corso", "rifiutata"
GIA_TRASCRITTA, AUDIO_CANCELLATO = "gia_trascritta", "audio_cancellato"



FINITA = "finita"

FALLITA = "fallita_su_plaud"


VUOTA = "vuota"


class ErroreHttp(Exception):
    ""

    def __init__(self, status: int, messaggio: str = ""):
        super().__init__(f"HTTP {status} {messaggio}".strip())
        self.status = status


class Plaud(Protocol):
    def dettaglio(self, file_id: str) -> tuple[dict, bytes]: ...

    def richiesta(self, file_id: str, corpo: dict) -> dict: ...


def ore_utc(adesso: datetime | None = None) -> int:
    ""
    adesso = adesso or datetime.now().astimezone()
    scarto = adesso.utcoffset()
    return round(scarto.total_seconds() / 3600) if scarto else 0


def corpo_richiesta(ore: int) -> dict:
    ""
    return {
        "is_reload": 0,
        "summ_type": "AUTO-SELECT",
        "summ_type_type": "system",
        "info": INFO_APP,
        "support_mul_summ": True,
        "timezone": ore,
    }


def intestazioni_app(versione: str, device_id: str, request_id: str, lingua: str = "en") -> dict:
    ""
    return {
        "edit-from": "desktop",
        "app-platform": "desktop",
        "app-versionNumber": versione,
        "app-language": lingua,
        "X-Device-Id": device_id,
        "X-Request-Id": request_id,
    }


def interpreta(risposta: dict) -> tuple[str, int | None, str]:
    ""




    codice = risposta.get("status")
    messaggio = str(risposta.get("msg") or "")
    if codice == 1:
        return PRONTA, 1, messaggio
    if codice == 0:
        if messaggio.strip().lower() == "success":
            return FINITA, 0, messaggio
        return IN_CORSO, 0, messaggio
    if codice == -419:
        return "token_scaduto", codice, messaggio
    if codice in (-1800907, -1800908):
        return "canale_fermo", codice, messaggio
    if codice == -7:
        return VUOTA, codice, messaggio
    if codice is None:
        return "errore", None, messaggio or "response without status"
    return RIFIUTATA, codice, messaggio


def leggi_coda(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    dati = json.loads(path.read_text(encoding="utf-8"))
    return dati if isinstance(dati, dict) else {}


def scrivi_coda(path: Path, coda: dict[str, dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(coda, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def candidati(
    indice: list[dict],
    coda: dict[str, dict],
    soglia_s: int = SOGLIA_SECONDI,
    adesso: datetime | None = None,
) -> list[dict]:
    ""



    adesso = adesso or datetime.now()
    fuori = []
    for r in indice:
        if r.get("has_transcript") or r.get("is_trash"):
            continue
        if float(r.get("duration_sec") or 0) < soglia_s:
            continue
        voce = coda.get(r["id"]) or {}
        stato = voce.get("stato")
        if stato in (PRONTA, IN_CORSO, GIA_TRASCRITTA, AUDIO_CANCELLATO, FALLITA, VUOTA):
            continue
        if stato == RIFIUTATA:
            if int(voce.get("tentativi") or 0) >= TENTATIVI_MAX:
                continue
            ultima = voce.get("ultima_richiesta")
            if ultima and adesso - datetime.fromisoformat(ultima) < ATTESA_RIFIUTATA:
                continue
        fuori.append(r)
    return sorted(fuori, key=lambda r: -(r.get("st") or 0))


def _ora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dal_dettaglio(dettaglio: dict) -> str | None:
    ""

    voce = next(
        (c for c in dettaglio.get("content_list") or [] if c.get("data_type") == "transaction"),
        None,
    )
    if voce is None:
        return None
    if voce.get("data_link"):
        return PRONTA
    stato = voce.get("task_status")
    if isinstance(stato, int) and stato < 0:
        return FALLITA
    return IN_CORSO


def gestisci(
    client: Plaud,
    indice: list[dict],
    coda_path: Path,
    copie_dir: Path,
    *,
    minuti_giorno: int = MINUTI_GIORNO,
    soglia_s: int = SOGLIA_SECONDI,
    in_volo_max: int = IN_VOLO,
    attesa_max_s: int = ATTESA_MAX_S,
    passo_s: int = PASSO_S,
    solo: set[str] | None = None,
    prova: bool = False,
    dormi: Callable[[float], None] | None = None,
    orologio: Callable[[], float] | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    ""




    dormi = dormi or time.sleep
    orologio = orologio or time.monotonic
    coda = leggi_coda(coda_path)
    corpo = corpo_richiesta(ore_utc())
    per_id = {r["id"]: r for r in indice}
    esito: dict = {
        "pronte": [],
        "in_corso": [],
        "rifiutate": [],
        "fallite": [],
        "chieste": [],
        "fermato": None,
    }

    tutti = candidati(indice, coda, soglia_s)
    if solo is not None:
        tutti = [r for r in tutti if r["id"] in solo]
    esito["candidati"] = len(tutti)
    esito["minuti_candidati"] = round(sum(float(r.get("duration_sec") or 0) for r in tutti) / 60)
    if prova:
        return esito

    def aggiorna(file_id: str, risposta: dict | None, **altro) -> str:
        voce = coda.setdefault(file_id, {})
        voce.update(altro)
        stato = altro.get("stato")
        if risposta is not None:
            stato, codice, messaggio = interpreta(risposta)
            voce.update(stato=stato, codice=codice, messaggio=messaggio)
            voce["controlli"] = int(voce.get("controlli") or 0) + 1
        voce["aggiornata_il"] = _ora()
        scrivi_coda(coda_path, coda)
        return stato

    def chiedi(file_id: str, **prima) -> str:
        ""
        stato = aggiorna(file_id, client.richiesta(file_id, corpo), **prima)
        if stato != FINITA:
            return stato
        dettaglio, _ = client.dettaglio(file_id)
        stato = dal_dettaglio(dettaglio) or IN_CORSO
        return aggiorna(file_id, None, stato=stato)

    def conta(file_id: str, stato: str) -> bool:
        ""
        if stato == PRONTA:
            esito["pronte"].append(file_id)
        elif stato in (RIFIUTATA, VUOTA):
            esito["rifiutate"].append(file_id)
        elif stato == FALLITA:
            esito["fallite"].append(file_id)
        else:
            return False
        return True

    def ferma(motivo: str) -> dict:
        esito["fermato"] = motivo
        esito["in_corso"] = [k for k, v in coda.items() if v.get("stato") == IN_CORSO]
        log(f"  transcription requests stopped: {motivo}")
        return esito


    in_volo: dict[str, float] = {}
    for file_id, voce in list(coda.items()):
        if voce.get("stato") != IN_CORSO or (solo is not None and file_id not in solo):
            continue
        try:
            stato = chiedi(file_id)
        except ErroreHttp as e:
            return ferma(str(e))
        if stato == IN_CORSO:
            in_volo[file_id] = orologio()
        elif not conta(file_id, stato):
            return ferma(stato)


    oggi = datetime.now().date().isoformat()
    usati = sum(
        float(v.get("durata_s") or 0) / 60
        for v in coda.values()
        if str(v.get("chiesta_il") or "").startswith(oggi)
    )
    da_fare = list(tutti)
    while da_fare or in_volo:
        while da_fare and len(in_volo) < in_volo_max:
            r = da_fare.pop(0)
            durata_min = float(r.get("duration_sec") or 0) / 60
            if usati + durata_min > minuti_giorno:
                continue
            file_id = r["id"]
            try:
                dettaglio, grezzo = client.dettaglio(file_id)
            except ErroreHttp as e:
                return ferma(str(e))
            contenuti = dettaglio.get("content_list") or []
            gia = dal_dettaglio(dettaglio)
            if gia is not None:

                aggiorna(file_id, None, stato={PRONTA: GIA_TRASCRITTA}.get(gia, gia))
                if gia == IN_CORSO:
                    in_volo[file_id] = orologio()
                continue
            if dettaglio.get("audio_deleted"):
                aggiorna(file_id, None, stato=AUDIO_CANCELLATO)
                continue
            if contenuti:
                copie_dir.mkdir(parents=True, exist_ok=True)
                (
                    copie_dir / f"{file_id}-dettaglio-{datetime.now():%Y%m%d-%H%M%S}.json"
                ).write_bytes(grezzo)
            voce = coda.get(file_id) or {}
            prima = {
                "chiesta_il": voce.get("chiesta_il") or _ora(),
                "ultima_richiesta": _ora(),
                "titolo_prima": voce.get("titolo_prima") or r.get("filename"),
                "durata_s": float(r.get("duration_sec") or 0),
                "tentativi": int(voce.get("tentativi") or 0) + 1,
                "canale": "api",
            }
            try:
                stato = chiedi(file_id, **prima)
            except ErroreHttp as e:
                return ferma(str(e))
            usati += durata_min
            esito["chieste"].append(file_id)
            log(
                f"  requested the transcription of {per_id[file_id].get('date')} ({durata_min:.0f} min): {stato}"
            )
            if stato == IN_CORSO:
                in_volo[file_id] = orologio()
            elif not conta(file_id, stato):
                return ferma(stato)
        if not in_volo:
            continue
        dormi(passo_s)
        for file_id, partita in list(in_volo.items()):
            try:
                stato = chiedi(file_id)
            except ErroreHttp as e:
                return ferma(str(e))
            if stato != IN_CORSO:
                if not conta(file_id, stato):
                    return ferma(stato)
                del in_volo[file_id]
            elif orologio() - partita > attesa_max_s:
                del in_volo[file_id]
    esito["in_corso"] = [k for k, v in coda.items() if v.get("stato") == IN_CORSO]
    return esito
