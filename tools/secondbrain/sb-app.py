#!/usr/bin/env python3
"""Engine of the SBK macOS app: each subcommand (status, runs, settings, mail, signatures, search and the rest) prints one JSON answer for the app."""





































from __future__ import annotations

import argparse
import ctypes
import fcntl
import functools
import importlib.util
import json
import os
import re
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
for _p in (TOOLS, TOOLS / "cross-source", TOOLS / "util", TOOLS / "secondbrain"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import impostazioni_pipeline as IMP  # noqa: E402
import sb_errori as ERR  # noqa: E402
import sb_impronta as SBI  # noqa: E402
import sb_parole as P  # noqa: E402
import sb_ripresa as RIPRESA  # noqa: E402
import sb_versioni as SBV  # noqa: E402
import sorgenti  # noqa: E402

import sbk_config  # noqa: E402
from sbk_config import DATA_ROOT  # noqa: E402


CONTRATTO = 2
PY = ["uv", "run", "python"]
SYSTEM = DATA_ROOT / "system"
RUNS = SYSTEM / "secondbrain-app-runs.jsonl"
FULLRUN = DATA_ROOT / "work" / "sbk" / "pipeline-fullrun"


FONTI_RUNS = SYSTEM / "secondbrain-app-fonti.jsonl"
SCARICHI = DATA_ROOT / "work" / "sbk" / "pipeline-scarichi"
MODI = ("tutto", "ingest", "propaga", "ricostruisci")






AMBIENTE_RUN = {"PYTHONUNBUFFERED": "1", "SBK_L1_SEQUENZIALE": "1", "LANG": "en_US.UTF-8"}


# Run diary markers (esiti.tsv): the English words, and the Italian ones of diaries written
# before them (INIZIO, FINE, tent.N, solo L0, poi-tutto).
_INIZIO = ("START", "INIZIO")
_FINE = ("END", "FINE")
_TENTATIVO = ("attempt.", "tent.")
_SOLO_L0 = ("L0 only", "solo L0")
_POI_TUTTO = ("then-all", "poi-tutto")
_FERMATO = ("STOPPED", "FERMATO")
_INTERROTTO = ("INTERRUPTED", "INTERROTTO")
_NON_PARTITA = ("not started", "non partita")
_RIPRESO = ("resumed", "ripreso")


def _carica(nome: str, percorso: Path):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    mod = importlib.util.module_from_spec(spec)

    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


XPR = _carica("xs_pipeline_run", TOOLS / "cross-source" / "xs-pipeline-run.py")
L0R = _carica("xs_l0_refresh", TOOLS / "cross-source" / "xs-l0-refresh.py")

CORSIE = _carica("sb_corsie", ROOT / "tools" / "secondbrain" / "sb_corsie.py")
CTL = _carica("sb_pipeline_ctl", TOOLS / "util" / "sb-pipeline-ctl.py")





def _locale_da_utc(ts: str | None) -> str | None:
    ""



    if not ts:
        return ts
    try:
        t = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return ts
    return t.astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def _dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S") if t else None


def quando(ts: str | None, adesso: datetime | None = None) -> str:
    ""
    t = _dt(ts)
    if t is None:
        return "never"
    adesso = adesso or datetime.now()
    giorni = (adesso.date() - t.date()).days
    if giorni == 0:
        return f"today at {t:%H:%M}"
    if giorni == 1:
        return f"yesterday at {t:%H:%M}"

    data = f"{P.MESI[t.month - 1]} {t.day}"
    return data if t.year == adesso.year else f"{data} {t.year}"


def _dal(ts: str | None) -> str:
    ""
    return "since " + quando(ts)


def _dal_breve(ts: str | None) -> str:
    ""
    return "since " + data_breve(ts)


def data_breve(ts: str | None, adesso: datetime | None = None) -> str:
    ""
    t = _dt(ts)
    if t is None:
        return "never"
    adesso = adesso or datetime.now()
    giorni = (adesso.date() - t.date()).days
    if giorni == 0:
        return f"today {t:%H:%M}"
    if giorni == 1:
        return "yesterday"
    breve = f"{P.MESI[t.month - 1][:3]} {t.day}"
    return breve if t.year == adesso.year else f"{breve} {t.year}"


def durata(s: float | None) -> str:
    ""
    if s is None:
        return ""
    s = int(s)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 2 * 86400:
        return f"{s // 3600} h {s % 3600 // 60} min" if s % 3600 // 60 else f"{s // 3600} h"
    return f"{s // 86400} days"


def _giorni_da(ts: str | None) -> float | None:
    t = _dt(ts)
    return (datetime.now() - t).total_seconds() / 86400 if t else None


def _piu_recente(*ts: str | None) -> str | None:
    vere = [t for t in ts if t]
    return max(vere) if vere else None


def _piu_vecchia(*ts: str | None) -> str | None:
    vere = [t for t in ts if t]
    return min(vere) if vere else None











VERSIONE_CACHE = 3

ETA_SCADENZA_S = 600





SCARICATORI = {
    "l0-calendar-download": ("calendar", "calendar"),
    "l0-slack-channel-index": ("slack", "slack-index"),
    "l0-slack-download": ("slack", "slack-canali"),
    "l0-slack-download-dm": ("slack", "slack-dm"),
    "l0-attio-download": ("attio", "attio"),
    "l0-personio-download": ("personio", "personio"),
    "l0-notion-download": ("notion", "notion"),
    "l0-plaud-download": ("plaud", "plaud"),
    "l0-tactiq-download": ("tactiq", "tactiq"),
    "l0-gdrive-download": ("gdrive", "gdrive"),
}

L1_NOMI = {
    "whatsapp": ("wa-l1",),
    "plaud": ("pl-l1",),
    "voicememos": ("vm-l1",),
    "linkedin": ("li-l1",),
    "chatgpt": ("cg-l1",),
}
INVENTARIO_L1 = "L1 Inventory (domains, repos, people)"


L1_USCITA = {
    "calendar": DATA_ROOT / "enriched" / "contacts-calendar.parquet",
    "attio": DATA_ROOT / "attio" / "processed" / "contacts-attio.parquet",
    "whoop": DATA_ROOT / "whoop" / "processed" / "daily.parquet",
    "clickup": DATA_ROOT / "clickup" / "processed" / "tasks.parquet",
}



MEMBRI_L1: dict[str, tuple[tuple[str, tuple[str, ...], Path | None], ...]] = {
    "l1_personio": (("Personio", ("personio-l1",), None),),
    "l1_personio_assenze": (
        (
            "Absences",
            ("personio_assenze", "personio-assenze"),
            DATA_ROOT / "personio" / "processed" / "absences-daily.parquet",
        ),
    ),
    "l1_phase1": (
        ("Attio", ("attio-l1",), L1_USCITA["attio"]),
        ("Calendar", ("calendar-l1",), L1_USCITA["calendar"]),
        ("ChatGPT", ("cg-l1",), None),
        ("ClickUp", (), L1_USCITA["clickup"]),
        ("DocuSign", ("docusign-l1",), None),

        ("DocuSign PDFs", ("docusign-pdf-l1",), None),
        ("Email", ("email-l1",), None),

        ("Mail attachments", ("email-allegati-l1",), None),
        ("Google Drive", ("gdrive-l1",), None),
        ("LinkedIn", ("li-l1",), None),
        ("Notion", ("notion-l1",), None),
        ("Slack", ("slack-l1",), None),
        ("Voice memos", ("vm-l1",), None),
        ("WhatsApp", ("wa-l1",), None),
        ("Whoop", (), L1_USCITA["whoop"]),
    ),
    "l1_speaker_analysis": (
        (
            "Plaud",
            ("plaud-speakers", "pl-speakers"),
            DATA_ROOT / "plaud" / "raw" / "_speaker_analysis.json",
        ),
    ),
    "l1_phase2": (("Plaud", ("pl-l1",), None), ("Tactiq", ("tactiq-l1",), None)),
    "l1_phase3_wa_deep": (("Documents", ("wa-l1-docs",), None), ("Photos", ("whatsapp",), None)),
}


CACHE_PAGATA = {
    "l3_extract": DATA_ROOT / "l3" / "nlp" / "batch-responses",
    "l3_extract_rel": DATA_ROOT / "l3" / "nlp" / "relationship-responses",
    "l3_deep_extract": DATA_ROOT / "l3" / "nlp" / "deep-responses",
}
RIPARAZIONI = {"l3_extract_rel": DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet.meta.json"}


def _esito_riga(d: dict) -> str:
    ""
    stato = d.get("status", "")
    if stato in ("success", "completed"):
        return "ok"
    if stato in ("exited", "dry_run"):
        return "senza_lavoro"

    if stato in ("lock", "yield_memoria"):
        return "non_partito"
    return "errore"


def _prova_di_lavoro(d: dict) -> bool:
    ""




    if _esito_riga(d) in ("senza_lavoro", "non_partito"):
        return False
    return not (d.get("stage") == "l0" and (d.get("duration_s") or 0) < 1.0)


class Indice:
    ""






    DURATE_TENUTE = 30
    SCARICHI_TENUTI = 60

    def __init__(self) -> None:
        self.seq = 0
        self.vince: dict[str, list] = {}
        self.durate: dict[str, list[float]] = {}

        self.scarichi: dict[str, list[str]] = {}

    def _metti(self, chiave: str, v: list) -> None:
        cur = self.vince.get(chiave)
        if cur is None or (v[0], v[1]) >= (cur[0], cur[1]):
            self.vince[chiave] = v

    def aggiungi(self, d: dict, ora_utc: str, seq: int | None = None) -> None:
        self.seq = self.seq + 1 if seq is None else seq
        v = [ora_utc, self.seq, d]
        stadio, fonte = d.get("stage"), str(d.get("source", ""))
        esito = _esito_riga(d)
        prova = _prova_di_lavoro(d)
        if stadio == "l0":
            sid, passo = None, None
            if d.get("caller") == "giro-l0":
                sid, passo = fonte, d.get("passo") or fonte
            elif d.get("script") in SCARICATORI:
                sid, passo = SCARICATORI[d["script"]]
                if sid != fonte:
                    sid = None
                else:


                    d.setdefault("passo", passo)
            if sid:
                if esito != "senza_lavoro":
                    self._metti(f"l0t|{sid}|{passo}", v)
                if esito == "ok" and prova:
                    self._metti(f"l0ok|{sid}|{passo}", v)
                    lista = self.scarichi.setdefault(sid, [])
                    lista.append(ora_utc)
                    del lista[: -self.SCARICHI_TENUTI]

                    if d.get("caller") == "giro-l0" and isinstance(
                        d.get("duration_s"), int | float
                    ):
                        chiave = f"l0:{passo}"
                        self.durate.setdefault(chiave, []).append(float(d["duration_s"]))
                        del self.durate[chiave][: -self.DURATE_TENUTE]
        elif prova:
            self._metti(f"src|{stadio}|{fonte}", v)
        if d.get("caller") == "orchestrator":
            self._metti(f"orch|{fonte}", v)
            if esito == "ok":
                self._metti(f"orchok|{fonte}", v)
                if isinstance(d.get("duration_s"), int | float):
                    self.durate.setdefault(fonte, []).append(float(d["duration_s"]))
                    del self.durate[fonte][: -self.DURATE_TENUTE]

    def righe(self) -> list[list]:
        ""
        uniche = {v[1]: v for v in self.vince.values()}
        return [uniche[s] for s in sorted(uniche)]

    def ricarica(
        self,
        righe: list[list],
        seq: int,
        durate: dict[str, list[float]],
        scarichi: dict[str, list[str]] | None = None,
    ) -> None:
        for ora, posizione, d in righe:
            self.aggiungi(d, ora, posizione)
        self.seq = seq

        self.durate = {k: list(v) for k, v in durate.items()}

        self.scarichi = {k: list(v) for k, v in (scarichi or {}).items()}

    def ultima(self, chiave: str) -> dict | None:
        v = self.vince.get(chiave)
        if v is None:
            return None
        d = v[2]

        return d if d.get("caller") == "giro-l0" else {**d, "ts": _locale_da_utc(d.get("ts"))}

    def durate_tipiche(self) -> dict[str, float]:
        ""
        return {n: statistics.median(v) for n, v in self.durate.items() if v}


def _file_vivo() -> Path:
    return SYSTEM / "pipeline-metrics.jsonl"


def _file_cache() -> Path:

    return SYSTEM / "secondbrain-app-cache.json"


def _leggi_metrics(idx: Indice, testo: bytes) -> None:
    for riga in testo.splitlines():
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        if isinstance(d, dict):
            idx.aggiungi(d, str(d.get("ts", "")))


def _indice(cache: dict) -> Indice:
    ""
    vivo = _file_vivo()
    archivi = [f for f in sorted(SYSTEM.glob("pipeline-metrics*.jsonl")) if f != vivo]
    firma = [
        VERSIONE_CACHE,
        Path(__file__).stat().st_mtime_ns,
        [[f.name, f.stat().st_size, f.stat().st_mtime_ns] for f in archivi],
    ]
    if cache.get("firma") != firma:
        tutto = Indice()
        for f in archivi:
            _leggi_metrics(tutto, f.read_bytes())
        cache.clear()
        cache.update(
            firma=firma,
            archivi=tutto.righe(),
            n_archivi=tutto.seq,
            durate=tutto.durate,
            scarichi=tutto.scarichi,
        )

    idx = Indice()
    st = vivo.stat() if vivo.exists() else None
    v = cache.get("vivo") or {}
    if st and v.get("ino") == st.st_ino and v.get("letti", 0) <= st.st_size:
        idx.ricarica(v["righe"], v["seq"], v.get("durate", {}), v.get("scarichi", {}))
        inizio = v["letti"]
    else:

        idx.ricarica(
            cache.get("archivi", []),
            cache.get("n_archivi", 0),
            cache.get("durate", {}),
            cache.get("scarichi", {}),
        )
        inizio = 0
    if st:
        with vivo.open("rb") as fh:
            fh.seek(inizio)
            nuovo = fh.read()

        fine = nuovo.rfind(b"\n") + 1
        _leggi_metrics(idx, nuovo[:fine])
        cache["vivo"] = {
            "ino": st.st_ino,
            "letti": inizio + fine,
            "seq": idx.seq,
            "righe": idx.righe(),


            "durate": {k: list(v) for k, v in idx.durate.items()},
            "scarichi": {k: list(v) for k, v in idx.scarichi.items()},
        }
    for d in _diari_l0():

        ora = datetime.strptime(d["ts"], "%Y-%m-%dT%H:%M:%S").astimezone(UTC)
        idx.aggiungi(d, ora.strftime("%Y-%m-%dT%H:%M:%S"))
    return idx


def _carica_cache() -> tuple[dict, str]:
    try:
        testo = _file_cache().read_text(encoding="utf-8")
        return json.loads(testo), testo
    except (OSError, ValueError):
        return {}, ""


def _salva_cache(cache: dict, prima: str) -> None:
    testo = json.dumps(cache, ensure_ascii=False)
    if testo == prima:
        return

    tmp = _file_cache().with_name(f"{_file_cache().name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(testo, encoding="utf-8")
        os.replace(tmp, _file_cache())
    except OSError:
        tmp.unlink(missing_ok=True)


def _diari_l0() -> list[dict]:
    ""





    nome_a_fonte = {p.nome: p.sorgente for p in L0R.PIANO}
    righe = []

    for diario in [*FULLRUN.glob("*/esiti.tsv"), *SCARICHI.glob("*/esiti.tsv")]:
        anno = (
            diario.parent.name[:4] if diario.parent.name[:4].isdigit() else f"{datetime.now():%Y}"
        )
        try:
            testo = diario.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for r in testo:
            campi = r.split("\t")
            if (
                len(campi) < 4
                or not campi[2].startswith(_TENTATIVO)
                or campi[1] not in nome_a_fonte
            ):
                continue
            try:
                ts = datetime.strptime(f"{anno}/{campi[0]}", "%Y/%d/%m %H:%M:%S")
            except ValueError:
                continue
            rc = campi[3].removeprefix("rc=")
            if not rc.lstrip("-").isdigit():

                continue
            durata_s = campi[4].removesuffix("s") if len(campi) > 4 else ""
            righe.append(
                {
                    "ts": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "stage": "l0",
                    "source": nome_a_fonte[campi[1]],
                    "passo": campi[1],
                    "status": "success" if rc == "0" else "failure",
                    "duration_s": float(durata_s) if durata_s.isdigit() else None,
                    "caller": "giro-l0",

                    "cartella": str(diario.parent),
                    "rc": int(rc),
                }
            )
    return righe








RICEVUTE: dict[str, str] = {}

NON_DATO_EXTRA = frozenset({"_speaker_analysis.json"})
_E_DATO_DELLA_PIPELINE = XPR._e_dato


def _e_dato_senza_l1(f: Path) -> bool:
    return f.name not in NON_DATO_EXTRA and _E_DATO_DELLA_PIPELINE(f)



XPR._e_dato = _e_dato_senza_l1


def _eta_fonte(sid: str) -> float | None:
    if sid == "whatsapp":
        return whatsapp_import(XPR._l0_dir(sid))["eta"]
    if sid in RICEVUTE:
        f = XPR._l0_dir(sid) / RICEVUTE[sid]
        return f.stat().st_mtime if f.exists() else None
    try:
        return XPR._eta_di(sid, sorgenti)
    except Exception:  # noqa: BLE001, a source without an L0 folder must not take down the state
        return None




ETA_RILANCIO_S = 60


def _file_eta() -> Path:


    return SYSTEM / "secondbrain-eta.json"


def _lucchetto_eta() -> Path:
    return SYSTEM / ".secondbrain-eta.lock"


def _misura_eta() -> dict:
    return {

        "valori": {sid: _eta_fonte(sid) for sid in sorgenti.SORGENTI if sid != "whatsapp"},


        "spesa": {pid: _ultima_spesa(pid) for pid in CACHE_PAGATA},
        "quando": time.time(),
    }


def _scrivi_eta(e: dict) -> None:
    f = _file_eta()
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        tmp.unlink(missing_ok=True)


def _misura_eta_in_sottofondo(cache: dict) -> bool:
    ""

    if time.time() - cache.get("eta_lanciata", 0) < ETA_RILANCIO_S:
        return False
    try:
        with _lucchetto_eta().open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        return False
    lanciatore = ROOT / "tools" / "secondbrain" / "sb-motore.py"
    try:
        subprocess.Popen(
            [sys.executable, str(lanciatore if lanciatore.exists() else Path(__file__)), "eta"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    cache["eta_lanciata"] = time.time()
    return True


def cmd_eta() -> dict:
    ""
    t0 = time.perf_counter()
    with _lucchetto_eta().open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"ok": True, "gia_in_corso": True}
        try:
            _scrivi_eta(_misura_eta())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return {"ok": True, "secondi": round(time.perf_counter() - t0, 2)}


def _eta_tutte(cache: dict, in_corso: list[dict], fresco: bool) -> dict[str, float | None]:
    ""









    vivi = sorted(p["pid"] for p in in_corso)
    try:
        e = json.loads(_file_eta().read_text(encoding="utf-8"))
    except (OSError, ValueError):

        e = cache.get("eta") or {}
    finito = bool(set(cache.get("eta_pid", e.get("pid", []))) - set(vivi))
    cache["eta_pid"] = vivi
    if "valori" not in e:
        e = _misura_eta()
        _scrivi_eta(e)
    elif fresco or finito or time.time() - e.get("quando", 0) > ETA_SCADENZA_S:
        _misura_eta_in_sottofondo(cache)
    cache["eta"] = {k: e.get(k) for k in ("valori", "spesa", "quando")}
    return e["valori"]














WA_RICEVUTE = "_ricevute-import.jsonl"


WA_SOGLIA_CHAT = 200
WA_SOGLIA_QUOTA = 0.5

WA_STESSO_CARICO_S = 2 * 3600



WA_STESSO_DUMP_S = 3600

WA_INTERROTTO_S = 2 * 3600

_WA_TMP = re.compile(r"whatsapp_extract_[A-Za-z0-9_]+")


def _wa_epoch(ts) -> float | None:
    ""



    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except ValueError:
        try:
            return datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except ValueError:
            return None


def _wa_e_completo(viste: int, chat_prima: int | None) -> bool:
    if viste >= WA_SOGLIA_CHAT:
        return True
    return bool(viste) and (not chat_prima or viste >= WA_SOGLIA_QUOTA * chat_prima)


def _wa_somma(valori) -> int | None:
    veri = [v for v in valori if isinstance(v, int)]
    return sum(veri) if veri else None


def _wa_dai_file(radice: Path) -> dict:
    ""










    chats = radice / "chats"
    out: dict = {"indice": None, "completi": [], "chat": []}
    try:
        st = (chats / "chats-index.json").stat()
    except OSError:
        return out
    out["indice"] = {"mtime": st.st_mtime, "leggibile": False, "chat": None}
    try:
        voci = json.loads((chats / "chats-index.json").read_text(encoding="utf-8")).get("chats")
    except (OSError, ValueError, AttributeError):
        return out
    if not isinstance(voci, list):
        return out
    out["indice"].update(leggibile=True, chat=len(voci))
    giri: dict[str, list[float]] = {}
    dump: list[tuple[float, float | None]] = []
    for v in voci:
        if not isinstance(v, dict):
            continue
        nome = v.get("sanitized_name") or Path(str(v.get("output_file") or "")).stem
        try:
            m = (chats / f"{nome}.json").stat().st_mtime if nome else None
        except OSError:
            m = None
        if m is None:
            continue

        tmp = _WA_TMP.search(str(v.get("source_file") or "").split(";")[-1])
        sp = str(v.get("source_path") or "")
        if tmp:
            if v.get("source_file_size_bytes"):
                giri.setdefault(tmp.group(0), []).append(m)
        elif not sp or sp.lower().endswith(".txt"):
            dump.append((m, _wa_epoch(v.get("date_end"))))
    n = len(voci)

    for inizio, scritte in sorted((min(t), len(t)) for t in giri.values()):
        ultimo = out["chat"][-1] if out["chat"] else None
        if ultimo and inizio - ultimo["fine"] <= WA_STESSO_CARICO_S:
            ultimo.update(fine=inizio, scritte=ultimo["scritte"] + scritte, giri=ultimo["giri"] + 1)
        else:
            out["chat"].append(
                {"fine": inizio, "dati": None, "scritte": scritte, "giri": 1, "fonte": "file"}
            )

    out["completi"] = [c for c in out["chat"] if _wa_e_completo(c["scritte"], n)]
    out["chat"] = [c for c in out["chat"] if not _wa_e_completo(c["scritte"], n)]
    sessioni: list[dict] = []
    for m, fine_dati in sorted(dump, key=lambda x: x[0]):
        if not sessioni or m - sessioni[-1]["fine"] > WA_STESSO_DUMP_S:
            sessioni.append({"fine": m, "scritte": 0, "date": []})
        s = sessioni[-1]
        s["fine"] = m
        s["scritte"] += 1
        if fine_dati is not None:
            s["date"].append(fine_dati)
    for s in sessioni:
        if _wa_e_completo(s["scritte"], n):

            buone = [d for d in s["date"] if d <= s["fine"]]
            out["completi"].append(
                {
                    "fine": s["fine"],
                    "dati": max(buone) if buone else None,
                    "scritte": s["scritte"],
                    "giri": None,
                    "fonte": "file",
                }
            )
    return out


def _wa_dalle_ricevute(radice: Path, adesso: float) -> dict:
    ""
    out: dict = {"completi": [], "chat": [], "in_corso": None, "interrotto": None, "primo": None}
    try:
        righe = (radice / WA_RICEVUTE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    inizi: dict[str, dict] = {}
    fini: dict[str, dict] = {}
    for n, r in enumerate(righe):
        try:
            d = json.loads(r)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("v") != 1 or not d.get("id"):
            continue
        t = _wa_epoch(d.get("ora"))
        if t is None:
            continue

        d["_t"], d["_n"] = t, n
        # Receipts say start/end (older ones inizio/fine): both are read.
        if d.get("evento") in ("start", "inizio"):
            inizi[d["id"]] = d
        elif d.get("evento") in ("end", "fine"):
            fini[d["id"]] = d
    tutte = [*inizi.values(), *fini.values()]
    if not tutte:
        return out
    out["primo"] = min(d["_t"] for d in tutte)
    for d in fini.values():
        if d.get("esito") != "ok":
            continue
        dati = _wa_epoch(d.get("dati_fino_al"))
        corsa = {
            "fine": d["_t"],
            "riga": d["_n"],

            "dati": min(dati, d["_t"]) if dati is not None else None,
            "scritte": (d.get("nuove") or 0) + (d.get("aggiornate") or 0),
            "viste": d.get("viste"),
            "nuove": d.get("nuove"),
            "aggiornate": d.get("aggiornate"),
            "uguali": d.get("uguali"),
            "giri": 1,
            "fonte": "ricevuta",
        }
        out["completi" if d.get("tipo") in ("complete", "completo") else "chat"].append(corsa)
    ultimo_ok = max((d["_t"] for d in fini.values() if d.get("esito") == "ok"), default=0.0)
    aperti = [d for k, d in inizi.items() if k not in fini and d["_t"] > ultimo_ok]
    falliti = [d for d in fini.values() if d.get("esito") != "ok" and d["_t"] > ultimo_ok]
    for d in sorted(aperti, key=lambda x: x["_t"]):
        if adesso - d["_t"] <= WA_INTERROTTO_S:
            out["in_corso"] = {"dal": d["_t"], "script": d.get("script")}
        else:
            out["interrotto"] = {
                "quando": d["_t"],
                "script": d.get("script"),
                "esito": "senza fine",
            }
    for d in falliti:
        if out["interrotto"] is None or d["_t"] > out["interrotto"]["quando"]:
            out["interrotto"] = {"quando": d["_t"], "script": d.get("script"), "esito": "errore"}
    return out


def _wa_firma(radice: Path) -> list:
    ""



    try:
        st = (radice / "chats" / "chats-index.json").stat()
        indice = [st.st_mtime_ns, st.st_size]
    except OSError:
        indice = None
    return [VERSIONE_CACHE, Path(__file__).stat().st_mtime_ns, indice]


def whatsapp_import(radice: Path, adesso: float | None = None, cache: dict | None = None) -> dict:
    ""





    adesso = time.time() if adesso is None else adesso
    ric = _wa_dalle_ricevute(radice, adesso)
    if cache is not None:
        firma = _wa_firma(radice)
        c = cache.get("whatsapp_file") or {}
        if c.get("firma") != firma:
            c = {"firma": firma, "valore": _wa_dai_file(radice)}
            cache["whatsapp_file"] = c
        fil = c["valore"]
    else:
        fil = _wa_dai_file(radice)
    taglio = ric["primo"]

    def di_prima(c: dict) -> bool:
        return taglio is None or c["fine"] < taglio

    completi = ric["completi"] + [c for c in fil["completi"] if di_prima(c)]
    chat = ric["chat"] + [c for c in fil["chat"] if di_prima(c)]

    def ordine(c: dict) -> tuple[float, int]:

        return c["fine"], c.get("riga", -1)


    decide = max(completi, key=lambda c: (c["dati"] or c["fine"], *ordine(c)), default=None)

    def piu_fresca(c: dict) -> bool:
        ""

        if decide is None:
            return True
        if decide["dati"] is not None:
            return c["fine"] > decide["dati"]
        return ordine(c) > ordine(decide)

    carico = None
    if chat:
        chat.sort(key=ordine)
        ultimo = chat[-1]
        stesso = [c for c in chat if ultimo["fine"] - c["fine"] <= WA_STESSO_CARICO_S]
        carico = {
            "quando": _iso(ultimo["fine"]),
            "chat": sum(c["scritte"] for c in stesso),
            "nuove": _wa_somma(c.get("nuove") for c in stesso),
            "aggiornate": _wa_somma(c.get("aggiornate") for c in stesso),
            "uguali": _wa_somma(c.get("uguali") for c in stesso),
            "giri": sum(c["giri"] for c in stesso),

            "dati_fino_al": _iso(max((c["dati"] for c in chat if c.get("dati")), default=None)),
            "dopo_il_completo": piu_fresca(ultimo),
            "fonte": "ricevuta" if any(c["fonte"] == "ricevuta" for c in stesso) else "file",
        }
    indice = fil["indice"]
    fini = [c["fine"] for c in completi + chat] + ([indice["mtime"]] if indice else [])
    fonti_usate = {c["fonte"] for c in completi + chat}
    if fonti_usate == {"ricevuta"}:
        da_dove = "import receipts"
    elif fonti_usate == {"file"}:
        da_dove = "chat index and dates, before the receipts"
    elif fonti_usate:
        da_dove = "import receipts and, for the earlier ones, chat index and dates"
    else:
        da_dove = "no trace of an import"
    return {
        "eta": (decide["dati"] or decide["fine"]) if decide else None,
        "completo": {
            "quando": _iso(decide["fine"]),
            "dati_fino_al": _iso(decide["dati"] or decide["fine"]),
            "chat": decide.get("viste") or decide["scritte"],
            "fonte": decide["fonte"],
        }
        if decide
        else None,
        "chat": carico,
        "ultimo_import": _iso(max(fini)) if fini else None,
        "in_corso": {"dal": _iso(ric["in_corso"]["dal"])} if ric["in_corso"] else None,
        "interrotto": {
            "quando": _iso(ric["interrotto"]["quando"]),
            "esito": ric["interrotto"]["esito"],
        }
        if ric["interrotto"]
        else None,
        "indice": {
            "quando": _iso(indice["mtime"]),
            "chat": indice["chat"],
            "leggibile": indice["leggibile"],
        }
        if indice
        else None,
        "da_dove": da_dove,
    }


def _wa_fino(ts: str | None) -> str:
    ""
    return "up to " + quando(ts)


def _wa_riga(wa: dict, ritmo: int | None, giorni: float | None) -> tuple[str, str, str]:
    ""
    if wa.get("in_corso"):
        return "in_corso", "Import in progress", f"It started {quando(wa['in_corso']['dal'])}."
    if wa.get("interrotto"):
        return (
            "errore",
            "Import stopped halfway",
            f"The import that started {quando(wa['interrotto']['quando'])} did not reach the end. "
            "Ask Claude to redo it.",
        )
    c, k = wa.get("completo"), wa.get("chat")
    frasi = [
        f"The last complete update has data {_wa_fino(c['dati_fino_al'])}."
        if c
        else "No complete update found."
    ]
    if k and k["dopo_il_completo"]:
        apri = "After that you" if c else "Last time you"
        if k["chat"]:
            quante = "one chat" if k["chat"] == 1 else f"{k['chat']} chats"
            frasi.append(f"{apri} loaded {quante}, {quando(k['quando'])}.")
        elif k.get("uguali"):
            quante = "one chat" if k["uguali"] == 1 else f"{k['uguali']} chats"
            frasi.append(
                f"{apri} reloaded {quante}, {quando(k['quando'])}, with no new messages."
            )
    if giorni is None:
        return "neutra", "Not measured", " ".join(frasi)
    if ritmo and giorni > ritmo:
        frasi.append(P.TOCCA_A_TE.get("whatsapp", "Your turn."))
        return "neutra", f"To bring in, {giorni:.0f} days behind", " ".join(frasi)
    return "ok", "Manual, up to date", " ".join(frasi)





def _ultimo_giro_l0() -> dict | None:
    ""





    diari = sorted(FULLRUN.glob("*/esiti.tsv"), key=lambda p: p.stat().st_mtime)
    if not diari:
        return None
    diario = diari[-1]
    righe = diario.read_text(encoding="utf-8", errors="replace").splitlines()

    def campo(r: str, i: int) -> str:
        return (r.split("\t") + ["", "", ""])[i]

    inizi = [i for i, r in enumerate(righe) if campo(r, 1).startswith(_INIZIO)]
    blocco = righe[inizi[-1] :] if inizi else righe
    fine = next(
        (r for r in reversed(blocco) if campo(r, 1).startswith((*_FINE, "FULL RUN CONCLUSO"))), None
    )
    log_vivo = max(
        (diario.parent / "log").glob("*.log"), key=lambda p: p.stat().st_mtime, default=None
    )
    anno = diario.parent.name[:4] if diario.parent.name[:4].isdigit() else f"{datetime.now():%Y}"

    def iso(r: str | None) -> str | None:
        if not r:
            return None
        try:
            return datetime.strptime(f"{anno}/{campo(r, 0)}", "%Y/%d/%m %H:%M:%S").strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        except ValueError:
            return None

    testa = blocco[0] if inizi else ""
    return {
        "cartella": str(diario.parent),
        "inizio": iso(testa) if inizi else None,
        "fine": iso(fine),


        "non_chiusi": next(
            (
                x.split(": ", 1)[1]
                for x in reversed(fine.split("\t"))
                if x.startswith(("not closed: ", "non chiusi: "))
            ),
            "",
        )
        if fine
        else None,
        "fermato": bool(fine) and campo(fine, 2) in _FERMATO,
        "poi_ingest": not any(s in testa for s in _SOLO_L0),

        "finale": "tutto" if any(s in testa for s in _POI_TUTTO) else "ingest",
        "passo_in_corso": log_vivo.stem if (fine is None and log_vivo) else None,
        "ultimo_segno_s": round(time.time() - log_vivo.stat().st_mtime) if log_vivo else None,
        "aggiornato": _iso(diario.stat().st_mtime),
    }



FULL_IN_DUE_PEZZI_S = 30 * 60


def _giro_intero(giro: dict, runs: list[dict]) -> dict:
    ""






    inizio, fine = giro.get("inizio"), giro.get("fine")
    nome, fine_intera, esito = "full run", fine, None
    rilettura = None  # the giro name "download" set below is also compared in _capsula
    if not giro.get("poi_ingest") and fine:
        limite = _dt(fine) + timedelta(seconds=FULL_IN_DUE_PEZZI_S)
        rilettura = next(
            (
                r
                for r in runs
                if " --ingest" in (r.get("comando") or "")
                and "--solo" not in (r.get("comando") or "")
                and _dt(r.get("inizio"))
                and _dt(fine) <= _dt(r["inizio"]) <= limite
            ),
            None,
        )
        if rilettura is None:
            nome = "download"
    if giro.get("vivo") or (rilettura and rilettura.get("vivo")):
        esito = "in_corso"
    elif rilettura is not None:
        fine_intera = rilettura.get("fine")
        esito = {
            "ok": "finito",
            "incompleto": "incompleto",
            "fermato": "fermato",
            "interrotto": "interrotto",
        }.get(rilettura.get("esito") or "", "non_finito")
    elif not fine:
        esito = "non_finito"
    elif giro.get("fermato"):
        esito = "fermato"
    elif (giro.get("non_chiusi") or "") not in _NESSUNO:
        esito = "incompleto"
    else:
        esito = "finito"
    parole = {
        "in_corso": ("in_corso", "in progress"),
        "finito": ("ok", "finished"),
        "incompleto": ("attenzione", "incomplete"),
        "fermato": ("neutra", "stopped"),
        "interrotto": ("attenzione", "interrupted"),
        "non_finito": ("attenzione", "not finished"),
    }
    salute, parola = parole[esito]
    durata_s = (_dt(fine_intera) - _dt(inizio)).total_seconds() if inizio and fine_intera else None
    titolo = "Last full run" if nome == "full run" else "Last download"
    if rilettura is not None and fine and fine_intera:
        pezzi = (_dt(fine) - _dt(inizio)).total_seconds()
        ultima = (
            f"Last time, {quando(inizio)}, the download took {durata(pezzi)} "
            f"and the re-read {durata(rilettura.get('durata_s'))}."
        )
    elif durata_s is not None:
        ultima = f"The last {nome} started {quando(inizio)} and took {durata(durata_s)}."
    else:
        ultima = f"The last {nome} started {quando(inizio)} and has no end line."
    return {
        "nome": nome,
        "esito": esito,
        "salute": salute,
        "parola": parola,
        "fine_intera": fine_intera,
        "durata_s": durata_s,
        "rilettura": rilettura.get("run_id") if rilettura else None,

        "frase": f"last {nome} {quando(inizio)}, {parola}",
        "titolo": titolo,
        "nota": f"{parola}, {durata(durata_s)}" if durata_s is not None else parola,
        "ultima_volta": ultima,
    }


def _capsula(giro: dict | None) -> dict:
    ""





    t = P.CAPSULA
    comuni = {k: t[k] for k in ("aiuto_run", "aiuto_terminale", "da_terminale")}
    if not giro or not giro.get("inizio"):
        return {
            "simbolo": "mai",
            "salute": "neutra",
            "frase": t["mai"],
            "aiuto": t["aiuto_mai"],
            **comuni,
        }
    esito = giro.get("esito") or "finito"
    scarico = giro.get("nome") == "download"
    frase = t["scarico" if scarico else "full_run"].format(quando=quando(giro["inizio"]))
    if esito == "finito":
        simbolo, salute, coda = (
            ("pallino", "neutra", "senza_rilettura") if scarico else ("spunta", "ok", None)
        )
    elif esito == "fermato":
        simbolo, salute, coda = "fermato", "neutra", "fermato"
    elif esito == "in_corso":
        simbolo, salute, coda = "in_corso", "in_corso", "in_corso"
    else:

        simbolo, salute = "attenzione", "attenzione"
        coda = esito if esito in t else "non_finito"
    if coda:
        frase = f"{frase}, {t[coda]}"
    aiuto = " ".join(x for x in (giro.get("ultima_volta"), t["aiuto"]) if x)
    return {"simbolo": simbolo, "salute": salute, "frase": frase, "aiuto": aiuto, **comuni}




SALUTI = ("ok", "neutra", "in_corso", "attenzione", "errore")


def _peggiore(*saluti: str) -> str:
    return max(saluti, key=SALUTI.index) if saluti else "neutra"


def _gruppo_fonte(sid: str, s) -> str:
    if s.natura == "chiusa":
        return "chiuse"

    if s.natura == "da_costruire" or sid in P.A_PARTE:
        return "da_collegare"
    if sid in L0R.MANUALI:
        return "a_mano"
    if s.genere == "inventario":
        return "inventari"
    return "da_sole"


def _entra_in(sid: str, s) -> str | None:
    ""
    if s.genere == "inventario":
        return "l1_inventario"
    if sid == "ai-history":  # feeds the identity files, not an L1 stage
        return None
    return {"plaud": "l1_phase2", "tactiq": "l1_phase2", "personio": "l1_personio"}.get(
        sid, "l1_phase1"
    )


def _l1_fonte(idx: Indice, sid: str, s) -> str | None:
    ""
    if s.genere == "inventario":
        d = idx.ultima(f"orchok|{INVENTARIO_L1}")
        return d["ts"] if d else None
    righe = [idx.ultima(f"src|l1|{n}") for n in L1_NOMI.get(sid, (f"{sid}-l1",))]
    ts = _piu_recente(*(d["ts"] for d in righe if d))
    uscita = L1_USCITA.get(sid)
    if uscita is not None and uscita.exists():
        u = _iso(uscita.stat().st_mtime)
        ts = _piu_vecchia(ts, u) if ts else u
    return ts






DATO_VERO = {
    "linkedin": ("linkedin/raw/export-*.parquet",),
}


def _dato_vero(sid: str) -> float | None:
    ""
    ore = [
        f.stat().st_mtime
        for schema in DATO_VERO.get(sid, ())
        for f in DATA_ROOT.glob(schema)
        if f.is_file() and not f.name.startswith(".")
    ]
    return max(ore) if ore else None


def _attesa_lettura(dato: str | None, lettura: str | None, scarichi: list[str]) -> str | None:
    ""





    if not dato or not lettura or dato <= lettura:
        return None
    dopo = [t for t in (_locale_da_utc(x) for x in scarichi) if t and t > lettura]
    return min([*dopo, dato])


def _in_fila(nomi: list[str]) -> str:
    ""
    if len(nomi) < 2:
        return "".join(nomi)
    return f"{', '.join(nomi[:-1])} and {nomi[-1]}"


@functools.cache
def _tetto_fonte(sid: str) -> int:
    ""
    return max(
        (p.timeout_s for p in IMP.applica_al_piano(L0R.PIANO) if p.sorgente == sid), default=0
    )


def _azione_scarica(sid: str, etichetta: str = "Download now") -> dict:
    ""






    azione = {
        "tipo": "da_sola" if sid in CORSIE.LEGGERE else "l0",
        "arg": sid,
        "etichetta": etichetta,
    }
    tetto = _tetto_fonte(sid)
    if azione["tipo"] == "l0" and tetto > 3600:
        azione |= {
            "lungo": True,
            "nome": f"Download {P.nome_fonte(sid)}",
            "frase": "While it downloads no other run starts, and the new files take up disk space.",
            "step": f"can take up to {round(tetto / 3600)} hours per attempt, and there are three attempts",
        }
    return azione


def _diagnosi_fonte(ultimo_t: dict, sid: str) -> dict | None:
    ""

    if ultimo_t.get("cartella"):
        return ERR.diagnosi_del_passo(Path(ultimo_t["cartella"]), ultimo_t.get("passo") or sid)
    try:

        locale = datetime.strptime(ultimo_t["ts"][:19], "%Y-%m-%dT%H:%M:%S").astimezone(UTC)
        dal = (locale - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
    except (KeyError, TypeError, ValueError):
        dal = None
    return ERR.diagnosi_dalla_coda(sid, dal)


def _azione_da_diagnosi(diagnosi: dict | None, sid: str) -> dict | None:
    ""


    if not diagnosi:
        return _azione_scarica(sid, "Retry")
    a = diagnosi.get("azione")
    if a and a["tipo"] == "l0" and a["arg"]:

        return _azione_scarica(a["arg"], a["etichetta"])
    return {"tipo": a["tipo"], "arg": a["arg"], "etichetta": a["etichetta"]} if a else None


def _vuota_non_rotta(ok_passo: dict, scaricata: str | None, ritmo: int, sid: str) -> bool:
    ""


    t = _dt(scaricata)
    if t is None or (datetime.now() - t).total_seconds() / 86400 > ritmo:
        return False
    ultimo = max((d for d in ok_passo.values() if d), key=lambda d: d["ts"], default=None)
    if ultimo and ultimo.get("cartella"):
        esame = ERR.esame_del_passo(Path(ultimo["cartella"]), ultimo.get("passo") or sid)
        if esame["avvisi"] or esame["diagnosi"]:
            return False
    return True


def fonti(
    idx: Indice, eta: dict[str, float | None], in_scarico: set[str], wa: dict | None = None
) -> list[dict]:
    ""



    out = []
    piano = list(L0R.PIANO)
    for sid, s in sorgenti.SORGENTI.items():
        gruppo = _gruppo_fonte(sid, s)
        passi = [p.nome for p in piano if p.sorgente == sid]
        dato = _iso(eta.get(sid))
        giorni = (time.time() - eta[sid]) / 86400 if eta.get(sid) else None
        ok_passo = {p: idx.ultima(f"l0ok|{sid}|{p}") for p in passi}
        tent_passo = {p: idx.ultima(f"l0t|{sid}|{p}") for p in passi}

        scaricata = (
            _piu_vecchia(*(d["ts"] for d in ok_passo.values() if d))
            if all(ok_passo.values())
            else None
        )
        senza_traccia = [p for p, d in ok_passo.items() if d is None]
        tentativi = [d for d in tent_passo.values() if d]
        ultimo_t = max(tentativi, key=lambda d: d["ts"]) if tentativi else None
        lettura = (
            _l1_fonte(idx, sid, s)
            if gruppo not in ("chiuse", "da_collegare") or sid in P.A_PARTE
            else None
        )
        da_leggere = (
            _attesa_lettura(dato, lettura, idx.scarichi.get(sid, []))
            if gruppo in ("da_sole", "inventari", "a_mano")
            else None
        )
        ritmo = s.ritmo_giorni
        nome = P.nome_fonte(sid)
        motivo = ""
        azione = None
        diagnosi = None
        vuota = False
        if gruppo == "chiuse":
            salute, parola = "neutra", "Closed"
            chiusa = _dt(f"{s.chiusa_il}T00:00:00") if s.chiusa_il else None
            motivo = f"Closed {quando(_iso(chiusa.timestamp())) if chiusa else ''}.".replace(
                " .", "."
            )
        elif sid in P.A_PARTE:
            salute, parola = "neutra", "Set apart"
            motivo = P.A_PARTE[sid]
            if sid == "whatsapp" and wa:


                fino = _piu_recente(
                    (wa.get("completo") or {}).get("dati_fino_al"),
                    (wa.get("chat") or {}).get("dati_fino_al"),
                )
                if fino:
                    motivo += f" The chats are there {_wa_fino(fino)}"
                    motivo += f", read {quando(lettura)}." if lettura else "."
        elif gruppo == "da_collegare":
            salute, parola = "neutra", "To connect"
            motivo = "It should be there and isn't yet."
        elif gruppo == "a_mano":
            if sid == "whatsapp" and wa is not None:
                salute, parola, motivo = _wa_riga(wa, ritmo, giorni)
            elif giorni is None:
                salute, parola, motivo = "neutra", "Not measured", "Cannot find the data date."
            elif ritmo and giorni > ritmo:
                salute, parola = "neutra", f"To bring in, {giorni:.0f} days behind"
                motivo = f"Behind by {giorni:.0f} days, the threshold is {ritmo}. {P.TOCCA_A_TE.get(sid, '')}".strip()
            elif not ritmo:


                salute, parola = "neutra", f"Manual, last data {data_breve(dato)}"
                motivo = (
                    f"From here you can't tell if there are new ones. The last data is {quando(dato)}."
                )
            else:
                salute, parola = "ok", "Manual, up to date"
            azione = {"tipo": "come_si_fa", "arg": sid, "etichetta": "How to do it"}


            if sid == "voicememos" and (memo := _memo_da_trascrivere()):
                if _trascrizione_viva():
                    salute, parola = "in_corso", "Being transcribed"
                    motivo = f"Whisper is transcribing {_memo_n(memo)} on the Mac."
                else:
                    salute, parola = "attenzione", f"{_memo_n(memo)} to transcribe"
                    motivo = (
                        f"In the folder there are {_memo_n(memo)} without a transcript, and the pipeline does not read them "
                        "until they are transcribed. Whisper transcribes them on the Mac, at no cost."
                    )
                    azione = {
                        "tipo": "trascrivi_memo",
                        "arg": sid,
                        "etichetta": f"Transcribe {_memo_n(memo)}",
                    }
        else:
            fallito = (
                ultimo_t is not None
                and _esito_riga(ultimo_t) == "errore"
                and not (ok_passo.get(ultimo_t.get("passo") or sid) or {}).get("ts", "")
                > ultimo_t["ts"]
            )



            if set(passi) & in_scarico:
                salute, parola = "in_corso", "Downloading"
            elif fallito:
                salute, parola = "errore", "Not downloading"
                motivo = f"The last attempt failed {quando(ultimo_t['ts'])}."

                diagnosi = _diagnosi_fonte(ultimo_t, sid)
                if diagnosi:
                    motivo = f"{diagnosi['causa']} {diagnosi['rimedio']}"
            elif giorni is None:
                salute, parola, motivo = "neutra", "Not measured", "Cannot find the data date."
            elif ritmo and giorni > ritmo and _vuota_non_rotta(ok_passo, scaricata, ritmo, sid):

                salute, parola, vuota = "neutra", "Nothing new", True
                motivo = (
                    f"Downloaded {quando(scaricata)}, but the last data is {giorni:.0f} days old. "
                    "The source responds, there simply was nothing new."
                )
            elif ritmo and giorni > ritmo:
                salute, parola = "attenzione", f"Behind by {giorni:.0f} days"
                motivo = f"No new data for {giorni:.0f} days, the threshold is {ritmo}."
            else:
                salute, parola = "ok", "Up to date"
            azione = _azione_scarica(sid)
        if gruppo in ("a_mano",):
            come = P.COME_A_MANO.get(sid, "By hand.")
        elif gruppo in ("da_sole", "inventari"):
            numero = next((i for i, p in enumerate(piano, 1) if p.sorgente == sid), None)
            come = (
                f"On its own, in the full run. It's download {numero} of {len(piano)}."
                if numero
                else "On its own."
            )
        elif gruppo == "chiuse":
            come = s.perche or "Closed."
        else:
            come = s.note or s.cosa_e
        entra = _entra_in(sid, s) if gruppo not in ("chiuse", "da_collegare") else None
        out.append(
            {
                "id": sid,
                "nome": nome,
                "descrizione": P.descrizione_fonte(sid, s.cosa_e),
                "gruppo": gruppo,
                "natura": P.NATURE.get(s.natura, s.natura),
                "salute": salute,
                "parola": parola,
                "motivo": motivo,

                "vuota": vuota,
                "dato_del": dato,
                "giorni": round(giorni, 2) if giorni is not None else None,
                "scaricata": scaricata,
                "passi_senza_traccia": senza_traccia,
                "ultimo_tentativo": {
                    "quando": ultimo_t["ts"],
                    "esito": _esito_riga(ultimo_t),
                    "passo": ultimo_t.get("passo"),
                }
                if ultimo_t
                else None,
                "lettura": lettura,

                "da_leggere": da_leggere,
                "soglia": f"new data within {ritmo} days"
                if ritmo and gruppo not in ("chiuse",)
                else "",
                "ritmo_giorni": ritmo,
                "come_si_aggiorna": come,
                "passi_a_mano": P.PASSI_A_MANO.get(sid) if gruppo == "a_mano" else None,
                "entra_in": {"id": entra, "nome": P.nome_stadio(entra, entra)} if entra else None,
                "azione": azione,
                "diagnosi": diagnosi,
                **(
                    {"import_whatsapp": {k: v for k, v in wa.items() if k != "eta"}}
                    if sid == "whatsapp" and wa
                    else {}
                ),
                "dettagli": {
                    "id": sid,
                    "passi": passi,
                    "da_dove": wa.get("da_dove", "chat index and dates")
                    if sid == "whatsapp" and wa
                    else "import receipt"
                    if sid in RICEVUTE
                    else "most recent file in the folder",
                },
            }
        )
    return out





def _output_di(pid: str) -> tuple[Path, ...]:
    nlp = DATA_ROOT / "l3" / "nlp"
    meta = DATA_ROOT / "knowledge" / "meta"
    return {
        "l2_entity_map_cleanup": (DATA_ROOT / "enriched" / "entity-map.json",),
        "l2_ricorrenze": (meta / "ricorrenze-stadio.json",),
        "l3_calendario_ricorrenze": (meta / "ricorrenze-calendario-stadio.json",),
        "l3_extract": (nlp / "decisions.parquet", nlp / "entities.parquet"),
        "l3_extract_rel": (nlp / "relationship-facts.parquet",),
        "l3_deep_extract": (nlp / "deep-facts.parquet",),
    }.get(pid, ())


def _da_file(*percorsi: Path) -> dict:
    ""
    esistenti = [p for p in percorsi if p.exists()]
    if not esistenti:
        return {"quando": None, "esito": "mai", "durata_s": None, "fonte": "no file produced"}
    p = max(esistenti, key=lambda x: x.stat().st_mtime)
    return {
        "quando": _iso(p.stat().st_mtime),
        "esito": "ok",
        "durata_s": None,
        "fonte": f"from the date of the file it produces ({p.name})",
    }


def _riassunto(d: dict | None, fonte: str) -> dict:
    if d is None:
        return {"quando": None, "esito": "mai", "durata_s": None, "fonte": fonte}
    esito = _esito_riga(d)
    return {
        "quando": d.get("ts"),
        "esito": "ok" if esito == "ok" else "errore",
        "durata_s": d.get("duration_s"),
        "fonte": fonte,
    }


def _checkpoint() -> tuple[str | None, set[str]]:
    ""
    try:
        d = json.loads(XPR.PIPELINE_CHECKPOINT.read_text())
    except (OSError, ValueError):
        return None, set()
    quando_fine = _locale_da_utc(str(d.get("timestamp", ""))[:19]) or None
    return quando_fine, set(d.get("stages_run", []))


def _ultima_spesa(pid: str) -> dict:
    ""
    cache = CACHE_PAGATA[pid]
    if not cache.exists():
        return {
            "quando": None,
            "esito": "mai",
            "durata_s": None,
            "fonte": "no paid response on disk",
        }

    with os.scandir(cache) as voci:
        t = max([cache.stat().st_mtime] + [v.stat().st_mtime for v in voci if v.is_dir()])
    ultimo = {
        "quando": _iso(t),
        "esito": "ok",
        "durata_s": None,
        "fonte": "from the last saved paid response",
    }
    meta = RIPARAZIONI.get(pid)
    if meta is not None and meta.exists():
        try:
            if json.loads(meta.read_text()).get("riparazione"):
                ultimo["nota"] = (
                    f"The file was rewritten {quando(_iso(meta.stat().st_mtime))} by a repair, at no cost."
                )
        except (OSError, ValueError):
            pass
    return ultimo


def _membri(idx: Indice, pid: str) -> dict:
    ""
    date: dict[str, str | None] = {}
    for nome, nomi, uscita in MEMBRI_L1[pid]:
        ts = _piu_recente(*(d["ts"] for d in (idx.ultima(f"src|l1|{n}") for n in nomi) if d))
        if uscita is not None and uscita.exists():
            u = _iso(uscita.stat().st_mtime)
            ts = _piu_vecchia(ts, u) if ts else u
        date[nome] = ts
    mancano = sorted(n for n, t in date.items() if t is None)
    vecchia = _piu_vecchia(*date.values())
    if vecchia is None:
        return {
            "quando": None,
            "esito": "mai",
            "durata_s": None,
            "fonte": "no trace of the read",
            "membri": date,
        }
    ultimo = {
        "quando": vecchia,
        "esito": "ok",
        "durata_s": None,
        "fonte": "from the most-behind member of the read",
        "membri": date,
    }
    if mancano:
        ultimo["nota"] = "No trace: " + ", ".join(mancano) + "."
    return ultimo


def _ultimo_stadio(
    idx: Indice,
    p,
    giro: dict | None,
    fine_run: str | None,
    girati: set[str],
    spesa: dict[str, dict] | None = None,
) -> dict:
    if p.id == "l0_download":
        if giro is None:
            return {
                "quando": None,
                "esito": "mai",
                "durata_s": None,
                "fonte": "no download run",
            }
        if giro.get("fine"):
            non_chiusi = giro.get("non_chiusi") or ""
            esito = "ok" if non_chiusi in _NESSUNO else "incompleto"
            ultimo = {
                "quando": giro["fine"],
                "esito": esito,
                "durata_s": None,
                "fonte": "from the download log",
            }
            if esito == "incompleto":
                ultimo["nota"] = f"Not closed {non_chiusi}."
            return ultimo
        return {
            "quando": giro.get("inizio"),
            "esito": "senza_fine",
            "durata_s": None,
            "fonte": "from the download log, without the end line",
        }
    if p.id in MEMBRI_L1:
        return _membri(idx, p.id)
    if p.tipo == "pagato" and p.id in CACHE_PAGATA:
        return (spesa or {}).get(p.id) or _ultima_spesa(p.id)
    d = idx.ultima(f"orch|{p.nome}")
    ultimo = _riassunto(d, "from the pipeline log")
    if d is not None and _esito_riga(d) != "ok":
        ok = idx.ultima(f"orchok|{p.nome}")
        ultimo["ultimo_ok"] = ok["ts"] if ok else None
    if d is None and p.id == "l2_entity_map_cleanup" and p.id in girati:
        merge = idx.ultima("orchok|L2 Merge")
        if merge:


            return {
                "quando": merge["ts"],
                "esito": "ok",
                "durata_s": None,
                "fonte": "together with the contacts merge, in the last run",
            }
    if d is None and p.id in girati and fine_run:
        return {
            "quando": fine_run,
            "esito": "ok",
            "durata_s": None,
            "fonte": "from the end of the last pipeline run",
        }
    if d is None and _output_di(p.id):
        return _da_file(*_output_di(p.id))
    return ultimo




LEGGE_ANCHE = {
    "l1_speaker_analysis": ("plaud",),
    "l1_personio_assenze": ("personio",),
    "l1_phase3_wa_deep": ("whatsapp",),
}


def _della_lettura(pid: str) -> bool:
    ""
    return pid.startswith("l1_")


def _ore_da(ts: str | None) -> float | None:
    giorni = _giorni_da(ts)
    return giorni * 24 if giorni is not None else None


def _da_quanto(ts: str | None, adesso: datetime | None = None) -> str:
    ""

    t = _dt(ts)
    if t is None:
        return ""
    ore = max(0.0, ((adesso or datetime.now()) - t).total_seconds() / 3600)
    if ore < 1:
        return "in less than an hour"
    if ore < 24:
        return "in an hour" if int(ore) == 1 else f"in {int(ore)} hours"
    giorni = int(ore // 24)
    return "in a day" if giorni == 1 else f"in {giorni} days"


def _attesa_in_parole(ore: float) -> str:
    ""
    if ore < 48:
        n = max(1, round(ore))
        return "for an hour" if n == 1 else f"for {n} hours"
    return f"for {round(ore / 24)} days"


def stadi(
    idx: Indice,
    giro: dict | None,
    fonti_out: list[dict] | None = None,
    correnti: dict[str, str] | None = None,
    spesa: dict[str, dict] | None = None,
    soglia_ore: float = 24,
) -> list[dict]:
    ""









    correnti = correnti or {}
    fonti_out = fonti_out or []
    fine_run, girati = _checkpoint()
    ultimi = {p.id: _ultimo_stadio(idx, p, giro, fine_run, girati, spesa) for p in XPR.CATENA}

    def nuove_di(pid: str) -> list[dict]:
        ids = {f["id"] for f in fonti_out if (f.get("entra_in") or {}).get("id") == pid}
        ids |= set(LEGGE_ANCHE.get(pid, ()))
        return [f for f in fonti_out if f["id"] in ids and f.get("da_leggere")]

    nuove = {p.id: nuove_di(p.id) for p in XPR.CATENA if _della_lettura(p.id)}
    nomi_nuove = sorted({f["nome"] for v in nuove.values() for f in v})

    lettura_piu_nuova = _piu_recente(
        *(
            t
            for pid, u in ultimi.items()
            if _della_lettura(pid)
            for t in [u.get("quando"), *(u.get("membri") or {}).values()]
        )
    )
    out = []
    for i, p in enumerate(XPR.CATENA, 1):
        ultimo = ultimi[p.id]
        q = ultimo["quando"]
        perche = perche_aiuto = ""
        fonti_nuove: list[str] = []
        if correnti.get(p.id) == "in_corso" or (
            p.id == "l0_download" and giro and giro.get("vivo")
        ):
            stato, salute, parola, breve = "in_corso", "in_corso", "In progress", "In progress"
        elif p.tipo == "pagato":
            stato, salute, breve = "pagato", "neutra", "You decide"
            parola = f"Idle {_dal_breve(q)}, you decide" if q else "Never done, you decide"
        elif ultimo["esito"] == "errore":
            stato, salute, breve = "errore", "errore", "Failed"
            parola = f"Failed {data_breve(q)}"
        elif ultimo["esito"] == "incompleto":
            stato, salute, breve = "incompleto", "attenzione", "Incomplete"
            parola = f"Incomplete {data_breve(q)}"
        elif q is None:
            stato, salute, parola, breve = "mai", "neutra", "Never done", "Never done"
        elif _della_lettura(p.id) and nuove.get(p.id):
            mie = nuove[p.id]
            da = min(f["da_leggere"] for f in mie)
            ore = _ore_da(da) or 0.0


            stato, breve = "da_rileggere", f"Not run {_da_quanto(q)}"
            salute = "attenzione" if ore >= soglia_ore else "neutra"
            parola = f"Not run {_da_quanto(q)}, last time {quando(q)}"
            fonti_nuove = [f["nome"] for f in mie]
            verbo = "has" if len(mie) == 1 else "have"
            perche = (
                f"{_in_fila(fonti_nuove)} {verbo} new data, arrived {quando(da)}. "
                f"The last read was {quando(q)}."
            )
            perche_aiuto = (
                f"{_in_fila(fonti_nuove)} {verbo} new data, arrived {quando(da)}. "
                "Re-read and update reads it, at no cost."
            )
        elif (
            p.id != "l0_download"
            and not _della_lettura(p.id)
            and (nomi_nuove or (lettura_piu_nuova and q < lettura_piu_nuova))
        ):
            stato, salute = "aspetta", "neutra"
            breve = f"Not run {_da_quanto(q)}"
            parola = f"Not run {_da_quanto(q)}, last time {quando(q)}"
            perche = (
                f"The new data from {_in_fila(nomi_nuove)} arrives here after Re-read and update."
                if nomi_nuove
                else "The read ran after this step. Re-read and update brings it back in step."
            )
        else:
            stato, salute, breve = "fatto", "ok", "Done"
            parola = f"Done {data_breve(q)}"
        aiuto = _aiuto_stadio(stato, parola, perche_aiuto or perche, q)
        da_solo = _da_solo(p)
        if stato == "aspetta" and da_solo.get("possibile"):

            da_solo = {
                **da_solo,
                "frase": "Redoing it now doesn't bring the new data, Re-read and update is needed first. "
                + da_solo["frase"],
            }
        out.append(
            {
                "id": p.id,
                "numero": i,
                "nome": P.nome_stadio(p.id, p.nome),
                "nome_tecnico": p.nome,
                "frase": P.frase_stadio(p.id),
                "strato": p.strato,
                "tipo": p.tipo,
                "pagato": p.tipo == "pagato",
                "ultimo": ultimo,
                "salute": salute,
                "parola": parola,

                "parola_breve": breve,

                "stato": stato,
                "data": data_breve(q) if q else "",

                "da_quanto": _da_quanto(q),
                "aiuto": aiuto,
                "perche": perche,
                "fonti_nuove": fonti_nuove,
                "gira_con": [
                    P.RUN[m]["nome"] for m in ("full", "full_completa", *MODI) if _nel_run(p, m)
                ],
                "consuma": list(p.consuma),
                "produce": list(p.produce),
                "da_solo": da_solo,
            }
        )
    return out


def _aiuto_fonte(f: dict) -> str:
    ""

    gruppo = f.get("gruppo")
    pezzi = [f"{f['parola']}."]
    if gruppo == "chiuse":
        return f"{f['parola']}. Nothing more comes from this source, and it's not a delay."
    if gruppo == "da_collegare":
        return f"{f['parola']}. It's among the sources to connect, it doesn't download today."
    if f.get("dato_del"):
        pezzi.append(f"The last data is {quando(f['dato_del'])}.")
    if gruppo == "a_mano":

        if f.get("motivo"):
            return " ".join([*pezzi[1:], f["motivo"].rstrip(".") + "."])
        pezzi.append("It's updated by hand, your turn. The detail shows how.")
    elif f.get("soglia"):
        pezzi.append(f"It downloads in the full run, and falls behind if {f['soglia']} doesn't arrive.")
    if f.get("motivo"):
        pezzi.append(f["motivo"].rstrip(".") + ".")
    if f.get("da_leggere"):
        pezzi.append(
            f"It has new data that arrived {quando(f['da_leggere'])} and not yet read. Re-read and update reads it."
        )
    return " ".join(pezzi)


def _aiuto_stadio(stato: str, parola: str, perche: str, q: str | None) -> str:
    ""

    if stato == "in_corso":
        return "Running now."
    if stato == "pagato":
        return (
            f"Paid. {parola}. It only starts with the Full run complete, when you choose its steps and confirm "
            "the spend twice."
        )
    if stato == "mai":
        return "It has never run."
    if stato == "errore":
        return f"The last run, {quando(q)}, failed. The detail shows why and how to redo it."
    if stato == "incompleto":
        return f"The last run, {quando(q)}, didn't close everything. The detail shows what's missing."
    if stato in ("da_rileggere", "aspetta"):
        return f"{parola}. {perche}".strip()
    return f"Done {quando(q)}, and in step with the data."


def _nel_run(p, run: str) -> bool:
    if run == "full":
        return p.id == "l0_download" or p.nel_perimetro("ingest")
    if run == "full_completa":
        return p.id == "l0_download" or p.nel_perimetro("tutto")
    return p.nel_perimetro(run)


def _da_solo(p) -> dict:
    ""


    if p.id == "l0_download":
        return {
            "possibile": True,
            "perche": "",
            "frase": "Downloads all sources, without re-reading them.",
            "azione": {"tipo": "l0", "arg": "", "etichetta": "Download all sources"},
        }
    if p.strato == "L1":
        return {
            "possibile": False,
            "perche": "The read steps are redone together, source by source, with Re-read and update.",
            "frase": "",
            "azione": {"tipo": "modo", "arg": "ingest", "etichetta": "Re-read and update"},
        }
    frase = (
        "Runs as inside the chain, with the same instructions and the same lock. During that time no other "
        "run starts. The other steps are untouched."
    )
    if p.tipo == "pagato":
        frase += " It's paid, so it only starts when you confirm the spend twice."
    return {
        "possibile": True,
        "perche": "",
        "frase": frase,
        "azione": {"tipo": "stadio", "arg": p.id, "etichetta": "Redo only this step…"},
    }


@functools.cache
def _fase_dello_stadio() -> dict[str, str]:
    ""
    primi = {f["primo"]: f["id"] for f in P.FASI}
    out, corrente = {}, P.FASI[0]["id"]
    for p in XPR.CATENA:
        corrente = primi.get(p.id, corrente)
        out[p.id] = corrente
    return out


def _aiuto_fase(stato: str, frase: str, perche: str, n: int, vecchia: str | None) -> str:
    ""
    if stato == "scarico":
        return f"Sources {frase}. The others are in Sources, each with its reason."
    if stato == "pagata":
        return (
            "Paid phase. It only starts with the Full run complete, when you choose its steps and confirm the "
            "spend twice."
        )
    if stato == "in_corso":
        return f"Running now, {frase.removeprefix('in progress, ')}."
    if stato == "aspetta":
        return f"This phase hasn't run {_da_quanto(vecchia)}, last time {quando(vecchia)}. {perche}".strip()
    if stato in ("da_rileggere", "errore", "incompleto") and perche:
        return perche
    if stato in ("errore", "incompleto"):
        return f"{frase.capitalize()}. The detail of each step shows why."
    return f"The steps of this phase are in step with the data, the last run {quando(vecchia)}."


def fasi(stadi_out: list[dict], fonti_out: list[dict]) -> list[dict]:
    ""

    primi = {f["primo"]: f for f in P.FASI}
    gruppi: list[tuple[dict, list[dict]]] = []
    for s in stadi_out:
        if s["id"] in primi or not gruppi:
            gruppi.append((primi.get(s["id"], P.FASI[0]), []))
        gruppi[-1][1].append(s)
    out = []
    for fase, membri in gruppi:
        n = len(membri)
        saluti = [s["salute"] for s in membri]
        salute = _peggiore(*saluti)
        date_ok = [s["ultimo"]["quando"] for s in membri if s["ultimo"]["quando"]]
        vecchia = min(date_ok) if date_ok else None
        pagata = all(s["pagato"] for s in membri)
        stati = [s.get("stato") for s in membri]
        perche, azione = "", None

        stato_fase = "fatti"
        if fase["id"] == "scarico":
            vive = [f for f in fonti_out if f["gruppo"] in ("a_mano", "da_sole", "inventari")]
            aggiornate = sum(f["salute"] in ("ok", "in_corso") for f in vive)
            frase = f"{aggiornate} of {len(vive)} up to date"
            stato_fase = "scarico"
            if salute == "in_corso":
                frase = "in progress · " + frase
        elif pagata:
            frase, stato_fase = "you decide", "pagata"
        elif salute == "in_corso":
            fatti = sum(s["salute"] == "ok" for s in membri)
            frase, stato_fase = f"in progress, {fatti} of {n} done", "in_corso"
        elif salute == "errore":
            frase, stato_fase = f"{saluti.count('errore')} failed of {n}", "errore"
        elif "incompleto" in stati:
            k = stati.count("incompleto")
            frase = "incomplete" if k == n else f"{k} of {n} incomplete"
            stato_fase = "incompleto"
        elif "da_rileggere" in stati:

            k = stati.count("da_rileggere")
            frase = "new data to read" if k == n else f"{k} of {n} with new data"
            stato_fase = "da_rileggere"
            nomi = sorted({nome for s in membri for nome in s.get("fonti_nuove") or []})
            verbo = "has" if len(nomi) == 1 else "have"
            perche = (
                f"{_in_fila(nomi)} {verbo} new data not yet read. "
                "Re-read and update brings it in, at no cost."
            )
            azione = {"tipo": "modo", "arg": "ingest", "etichetta": "Re-read and update"}
        elif "aspetta" in stati:

            frase, stato_fase = f"not run {_da_quanto(vecchia)}", "aspetta"
            perche = next((s["perche"] for s in membri if s.get("stato") == "aspetta"), "")
        else:
            k = saluti.count("ok")
            frase = "done" if k == n else f"{k} of {n} done"
        out.append(
            {
                "id": fase["id"],
                "nome": fase["nome"],
                "etichetta": fase["etichetta"],
                "descrizione": fase["descrizione"],
                "pagata": pagata,
                "stadi": [s["id"] for s in membri],
                "salute": "neutra" if pagata and salute != "in_corso" else salute,
                "frase": frase,
                "stato": stato_fase,

                "perche": perche,
                "azione": azione,
                "aiuto": _aiuto_fase(stato_fase, frase, perche, n, vecchia),
                "quando": vecchia,
                "data": data_breve(vecchia) if vecchia else "never",
            }
        )
    return out








LOCK_RUN = SYSTEM / "secondbrain-run.lock"
SB_RUN = ROOT / "tools" / "secondbrain" / "sb-run.py"

LOCKS_PIPELINE = ("pipeline-run", "l0-refresh")


def _adesso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _lock_tenuto(percorso: Path) -> bool:
    ""

    if not percorso.exists():
        return False
    richiesta = struct.pack("qqihh", 0, 0, 0, fcntl.F_WRLCK, os.SEEK_SET)
    try:
        with percorso.open("rb") as fh:
            risposta = fcntl.fcntl(fh, fcntl.F_GETLK, richiesta)
    except OSError:
        return False
    return struct.unpack("qqihh", risposta)[3] != fcntl.F_UNLCK


def _gira_dall_app() -> dict | None:
    ""
    if not _lock_tenuto(LOCK_RUN):
        return None
    try:
        return json.loads(LOCK_RUN.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}


def _avvio_processo(pid: int) -> str:
    ""
    try:
        return subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _avvio_del_mac() -> float | None:
    ""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5
        ).stdout
        return float(re.search(r"sec = (\d+)", out).group(1))
    except (subprocess.SubprocessError, OSError, AttributeError):
        return None


_LIBC = ctypes.CDLL("/usr/lib/libSystem.dylib", use_errno=True)


def _marcato(pid: int, marca: bytes) -> bool:
    ""
    mib = (ctypes.c_int * 3)(1, 49, pid)
    size = ctypes.c_size_t(0)
    if _LIBC.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or not size.value:
        return False
    buf = ctypes.create_string_buffer(size.value)
    if _LIBC.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return False
    return marca in buf.raw[: size.value]


def _coda(percorso: Path, byte: int = 65536) -> list[str]:
    try:
        with percorso.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - byte))
            return fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


# The runner and sb-run.py write English. The Italian words are still accepted, so logs written
# by older versions keep reading the same way.
# "Nothing left open" in the run diary: "none" now, "nessuno" in older diaries.
_NESSUNO = ("", "none", "nessuno")
_RE_FINE = re.compile(r"^── (?:exit|(?:end|fine) .*?· exit) (-?\d+)")
_RE_ESITO_MODO = re.compile(r"(?:Outcome|Esito): (.+?) \(exit (-?\d+)\)\s*$")
_RE_ESITO_SOLO = re.compile(r"── (?:outcome|esito): (OK|FAILED|FALLITO) ──")


_RE_CONTO_ESITO = re.compile(r"(\d+)/(\d+)")
_RE_MORTI = re.compile(r"(?:dead|morti): ([^(]+)")
# Words of the outcome line that mean "something did not close" (English first, then the old Italian).
_ESITO_SALTATI = ("skipped:", "saltati:")
_ESITO_MORTI = ("dead:", "morti")
_ESITO_NON_PULITO = ("sources not closed", "fonti non chiuse", "vanished", "spariti", *_ESITO_SALTATI, *_ESITO_MORTI)


def _racconto(esito: dict, comando: str, righe: list[str]) -> str:
    ""





    frase = esito.get("frase") or ""
    conto = _RE_CONTO_ESITO.search(frase)
    chiusi, totale = (int(conto[1]), int(conto[2])) if conto else (None, None)
    comando = _comando_interno(comando)
    i = comando.split().index("--solo-stadio") if "--solo-stadio" in comando.split() else -1
    stadio = comando.split()[i + 1] if 0 <= i < len(comando.split()) - 1 else None
    if esito["esito"] == "ok":
        if stadio:
            return f"It redid {P.nome_stadio(stadio, stadio)}."
        if not totale:
            return "It finished cleanly."

        n = _fonti_da_collegare(frase, righe)
        coda = f" {n} sources are not connected yet, nothing to redo." if n else ""
        return f"It closed all {totale} steps.{coda}"
    if esito["esito"] == "incompleto":
        if chiusi is not None and chiusi == totale:


            return f"It closed all {totale} steps, but a check on the result doesn't add up."
        if chiusi is not None:
            return f"It closed {chiusi} of {totale} steps."
        return "Some step didn't close."
    if esito["esito"] == "fallito":
        if m := _RE_MORTI.search(frase):
            per_nome = {p.nome: p.id for p in XPR.CATENA}
            nomi = [
                P.nome_stadio(per_nome.get(x.strip(), x.strip()), x.strip())
                for x in m[1].split(",")
                if x.strip()
            ]
            return f"It stopped at {_in_fila(nomi)}, the steps after didn't start."
        return "It didn't finish."
    if esito["esito"] == "fermato":
        return "Stopped before the end."
    if esito["esito"] == "non_partito":
        return "It didn't start, another run was already going."
    if esito["esito"] == "interrotto":
        if "restarted" in frase:
            return "Interrupted, the Mac restarted."
        return "Interrupted, the log doesn't say how it ended."
    return ""


def _esito_dal_log(r: dict) -> dict:
    ""

    righe = _coda(Path(r["log"]))
    esito = _esito_grezzo(r, righe)
    return {**esito, "racconto": _racconto(esito, r.get("comando", ""), righe)}


def _esito_grezzo(r: dict, righe: list[str]) -> dict:
    rc = None
    for riga in reversed(righe):
        m = _RE_FINE.match(riga)
        if m:
            rc = int(m.group(1))
            break
    frase = ""
    for riga in reversed(righe):
        m = _RE_ESITO_MODO.search(riga) or _RE_ESITO_SOLO.search(riga)
        if m:
            frase = m.group(1)
            break
    comando = _comando_interno(r.get("comando", ""))
    giro = "xs-l0-refresh.py" in comando or "sb-full.py" in comando
    if giro:
        fine = _fine_giro(Path(r.get("cartella", "")))
        if fine:
            frase = (
                f"{fine} still to close"
                if fine not in _NESSUNO
                else "all sources of the run closed"
            )
    if r.get("fermato"):
        return {"esito": "fermato", "frase": f"stopped ({r['fermato']})", "rc": rc}
    if rc is None:
        return {
            "esito": "interrotto",
            "frase": r.get("motivo") or "no end line in the log",
            "rc": None,
        }
    if rc == 0:
        return {"esito": "ok", "frase": frase or "closed", "rc": 0}
    if rc == 75:
        return {
            "esito": "non_partito",
            "frase": "the pipeline was already busy with another run and did not run",
            "rc": 75,
        }
    if rc < 0 or rc in (130, 143):
        return {"esito": "interrotto", "frase": f"killed by a signal (exit {rc})", "rc": rc}
    if "--solo-stadio" in comando and rc == 2:


        if not any(x in frase for x in (*_ESITO_SALTATI, *_ESITO_MORTI)):
            return {"esito": "ok", "frase": frase, "rc": 2}
        return {"esito": "non_partito", "frase": frase or "the step did not start", "rc": 2}
    argv = comando.split()
    if ("--solo" in argv or "--only" in argv) and "xs-pipeline-run.py" in comando and rc == 2:
        return {"esito": "non_partito", "frase": frase or "stage not launchable on its own", "rc": 2}
    if giro and rc == 2:
        return {
            "esito": "non_partito",
            "frase": "the run did not start (coverage or unknown source)",
            "rc": 2,
        }
    if giro and rc == 1:
        return {"esito": "incompleto", "frase": frase or "some step not closed", "rc": 1}
    if rc == 2:


        if _solo_note_di_stato(frase, righe):
            return {"esito": "ok", "frase": frase, "rc": 2}
        return {"esito": "incompleto", "frase": frase or "INCOMPLETE", "rc": 2}
    return {"esito": "fallito", "frase": frase or f"exit {rc}", "rc": rc}


_RE_AVVISI_ESITO = re.compile(r", (?:warnings|avvisi): (\d+)")
_RE_INNOCUI = re.compile(
    r"(\d+) (?:unchanged|resumed from the stopped run|resumed|outside this single run"
    r"|invariati|ripresi dal run fermato|fuori da questo run singolo)"
)


def _solo_note_di_stato(frase: str, righe: list[str]) -> bool:
    ""




    conto, avvisi = _RE_CONTO_ESITO.search(frase), _RE_AVVISI_ESITO.search(frase)
    if (
        not conto
        or not avvisi
        or any(x in frase for x in _ESITO_NON_PULITO)
    ):
        return False
    if int(conto[1]) + sum(int(n) for n in _RE_INNOCUI.findall(frase)) != int(conto[2]):
        return False
    n, inizi = int(avvisi[1]), (
        *XPR.NOTE_FONTI,
        *getattr(XPR, "NOTE_FONTI_VECCHIE", ()),
        XPR.AVVISO_PRIMA,
        *getattr(XPR, "AVVISI_PRIMA_VECCHI", ()),
    )
    for i in range(len(righe) - 1, -1, -1):
        if "completed_with_warnings" in righe[i]:
            sotto = [r.split(" - ", 1)[-1] for r in righe[i + 1 : i + 1 + n]]
            return len(sotto) == n and all(r.startswith(inizi) for r in sotto)
    return False


def _fonti_da_collegare(frase: str, righe: list[str]) -> int:
    ""
    if m := re.search(r"(?:sources to connect|fonti da collegare): (\d+)", frase):
        return int(m[1])
    segno = next(
        ((r, s) for r in reversed(righe) for s in ("never built", "mai costruite") if s in r),
        ("", ""),
    )
    mai = segno[0]
    elenco = mai.split(segno[1], 1)[-1].split(":", 1)[-1].split(" (", 1)[0] if mai else ""
    return len([x for x in elenco.split(",") if x.strip()]) if mai else 0


def _fine_giro(cartella: Path) -> str | None:
    ""
    diario = cartella / "esiti.tsv"
    for riga in reversed(_coda(diario, 16384)):
        campi = riga.split("\t")
        if len(campi) >= 3 and campi[1] in _FINE:

            return campi[-1].removeprefix("not closed: ").removeprefix("non chiusi: ")
    return None


def _chiusura_orfana(r: dict) -> dict:
    ""

    log = Path(r["log"])
    if any(_RE_FINE.match(x) for x in _coda(log, 4096)):
        quando = datetime.fromtimestamp(log.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        return {"fine": quando}
    battito = log.with_suffix(".battito")
    ultimo = next((p.stat().st_mtime for p in (battito, log) if p.exists()), None)
    avvio_mac = _avvio_del_mac()
    try:
        inizio = datetime.strptime(r["inizio"], "%Y-%m-%dT%H:%M:%S").timestamp()
    except (KeyError, ValueError):
        inizio = 0.0
    if avvio_mac and avvio_mac > inizio:
        motivo = f"the Mac restarted ({datetime.fromtimestamp(avvio_mac):%d/%m %H:%M})"
    else:
        motivo = "the run keeper closed without writing the end"
    quando = datetime.fromtimestamp(ultimo).strftime("%Y-%m-%dT%H:%M:%S") if ultimo else _adesso()

    rimasti = rimasti_del_run(r["run_id"])
    return {"fine": quando, "esito": "interrotto", "motivo": motivo, "rimasti": rimasti}


def _runs() -> list[dict]:
    if not RUNS.exists():
        return []
    per_id: dict[str, dict] = {}
    for riga in RUNS.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        per_id.setdefault(d["run_id"], {}).update(d)


    runs = sorted(
        (d for d in per_id.values() if "log" in d and "inizio" in d), key=lambda d: d["inizio"]
    )
    vivo_id = (_gira_dall_app() or {}).get("run_id")
    chiusure = []
    for r in runs:
        r["vivo"] = r.get("fine") is None and r["run_id"] == vivo_id
        if r.get("fine") is None and not r["vivo"]:
            c = _chiusura_orfana(r)
            r.update(c)
            chiusure.append({"run_id": r["run_id"], **c})
        if not r["vivo"]:
            r.update({k: v for k, v in _esito_dal_log(r).items() if k not in r or k == "frase"})
    if chiusure:
        with RUNS.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            for c in chiusure:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return runs






DIARIO_TERMINALE = SYSTEM / "runs-da-terminale.jsonl"
_SCRIPT_TERMINALE = {
    "giro": "tools/cross-source/xs-l0-refresh.py",
    "rilettura": "tools/cross-source/xs-pipeline-run.py",
}


def _pid_di(pid, script: str) -> bool:
    ""
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    try:
        comando = subprocess.run(
            ["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return True
    return Path(script).name in comando


def _esito_terminale(tipo: str, rc, cartella: str | None) -> tuple[str, str]:
    ""
    if rc is None:
        return "interrotto", "it closed without writing how"
    if rc == 75:
        return "non_partito", "it didn't start, another run was already going"
    if rc in (130, 143) or rc < 0:
        return "fermato", "stopped"
    if tipo == "giro":
        if rc == 0:
            return "ok", "all sources closed"

        fine = next(
            (
                r.split("\t")[-1]
                for r in reversed(_coda(Path(cartella or "") / "esiti.tsv", 8192))
                if r.split("\t")[1:2] in [[s] for s in _FINE]
            ),
            "",
        )
        quali = fine.removeprefix("non chiusi:").strip()
        return "incompleto", f"with sources not closed, {quali}" if quali else "with sources not closed"
    if rc == 0:
        return "ok", "finished"
    if rc == 2:
        return "incompleto", "finished, incomplete"
    return "fallito", f"it stopped with an error (exit {rc})"


def _runs_da_terminale() -> list[dict]:
    ""

    if not DIARIO_TERMINALE.exists():
        return []
    per_id: dict[str, dict] = {}
    for riga in DIARIO_TERMINALE.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        if d.get("run_id"):
            per_id.setdefault(d["run_id"], {}).update(d)

    cartella_del_giro = {
        str(d.get("pid")): d.get("cartella") for d in per_id.values() if d.get("tipo") == "giro"
    }
    out = []
    for d in per_id.values():
        tipo = d.get("tipo", "")
        if tipo not in _SCRIPT_TERMINALE or "inizio" not in d:
            continue
        if tipo == "giro" and d.get("cartella"):
            log = str(Path(d["cartella"]) / "esiti.tsv")
        elif cartella_del_giro.get(str(d.get("giro_pid"))):
            log = str(Path(cartella_del_giro[str(d.get("giro_pid"))]) / "log" / "ingest.log")
        else:

            log = str(DIARIO_TERMINALE.with_name(f"{d['run_id']}.log"))
        if d.get("fine") is None and _pid_di(d.get("pid"), _SCRIPT_TERMINALE[tipo]):
            continue
        esito, frase = _esito_terminale(tipo, d.get("rc"), d.get("cartella"))
        out.append(
            {
                "run_id": d["run_id"],
                "etichetta": f"terminale-{tipo}",
                "comando": " ".join([_SCRIPT_TERMINALE[tipo], *d.get("argomenti", [])]),
                "pid": d.get("pid"),
                "log": log,
                "cartella": d.get("cartella"),
                "inizio": d["inizio"],
                "fine": d.get("fine"),
                "esito": esito,
                "frase": frase,
                "rc": d.get("rc"),
                "vivo": False,
                "da_terminale": True,
            }
        )
    return out





_SOLO_LETTURA = {
    "--dry-run",
    "--controlla",
    "--check",
    "--sabota",
    "--self-test",
    "--help",
    "-h",
    "elenco",
    "list",
    "--json-only",
}


_CATENE = re.compile(r"full-run[\w.-]*\.sh|xs-l0-refresh\.py|xs-pipeline-run\.py|wa-l0l3-full\.py")
_INTERPRETI = ("python", "zsh", "bash", "sh", "dash")


def _eseguito(argv: list[str]) -> str | None:
    ""

    if not argv or not Path(argv[0]).name.lower().startswith(_INTERPRETI):
        return None
    for t in argv[1:]:
        if t == "-c":
            return None
        if not t.startswith("-"):
            return Path(t).name
    return None


def _processi_pipeline() -> list[dict]:
    ""







    vivo = _gira_dall_app() or {}
    marche = [f"SBK_RUN_ID={vivo['run_id']}".encode()] if vivo.get("run_id") else []

    marche += [f"SBK_RUN_ID={d['run_id']}".encode() for d in _scarichi_soli() if d["vivo"]]
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,etime=,command="], capture_output=True, text=True, timeout=15
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    io = os.getpid()
    vivi = []
    for riga in out.splitlines():
        parti = riga.split(None, 2)
        if len(parti) < 3 or not parti[0].isdigit() or int(parti[0]) == io:
            continue
        argv = parti[2].split()
        nome = _eseguito(argv)
        if (
            not nome
            or nome.startswith(("sb-app", "sb-run", "xs-util-"))

            or nome in ("xs-l3-search.py", "sb-cerca.py")
            or _SOLO_LETTURA & set(argv)
        ):
            continue
        script = nome.endswith(".py") and (
            nome.startswith(("xs-", "rq")) or "-l0-" in nome or "-l1-" in nome
        )
        if not (script or _CATENE.fullmatch(nome)):
            continue
        pid = int(parti[0])
        if any(_marcato(pid, m) for m in marche):
            continue
        vivi.append(
            {
                "pid": pid,
                "etime": parti[1],
                "script": nome,
                "footprint": CTL.phys_footprint(pid) or 0,
            }
        )
    return vivi


def _occupato_da_fuori() -> list[str]:
    motivi = [
        f"lock «{n}» held"
        for n in LOCKS_PIPELINE
        if _lock_tenuto(DATA_ROOT / ".locks" / f"{n}.lock")
    ]
    motivi += [f"{p['script']} (pid {p['pid']}, running for {p['etime']})" for p in _processi_pipeline()]
    return motivi





_FLAG_INTERNI = {
    "--all": "--tutto",
    "--propagate": "--propaga",
    "--rebuild": "--ricostruisci",
    "--then-ingest": "--poi-ingest",
    "--single-stage": "--solo-stadio",
    "--allow-spend": "--consenti-spesa",
}


def _comando_interno(comando: str) -> str:
    """A command typed with the English flags, rewritten with the internal names the app reads."""
    argv = comando.split()
    refresh = "xs-l0-refresh.py" in comando
    return " ".join(
        "--solo" if refresh and a == "--only" else _FLAG_INTERNI.get(a, a) for a in argv
    )


def _nome_run(r: dict) -> str:
    comando = _comando_interno(r.get("comando", ""))
    if "--solo-stadio" in comando:
        argv = comando.split()
        sid = (
            argv[argv.index("--solo-stadio") + 1]
            if argv.index("--solo-stadio") + 1 < len(argv)
            else ""
        )
        passo = XPR.CATENA_PER_ID.get(sid)
        return f"Only {P.nome_stadio(sid, passo.nome if passo else sid)}"
    if "--poi-ingest" in comando:
        return P.RUN["full"]["nome"]
    if "xs-l0-refresh.py" in comando or ("sb-full.py" in comando and "--solo-scarico" in comando):
        argv = comando.split()
        if "--solo" in argv and argv.index("--solo") + 1 < len(argv):
            return f"Download of {P.nome_fonte(argv[argv.index('--solo') + 1])}"
        return P.RUN["l0"]["nome"]
    if "sb-full.py" in comando:
        nome = P.RUN["full_completa" if "--modo tutto" in comando else "full"]["nome"]
        return f"{nome}, resumed" if "--riprendi" in comando else nome
    for m in MODI:
        if f"--{m}" in comando:
            return P.RUN[m]["nome"]
    return r.get("etichetta", "run")


def _riga_avanzamento(av: dict | None) -> str:
    ""
    if not av:
        return ""
    passi = av.get("passi") or []
    fatti = sum(p["stato"] in ("fatto", "fallito", "saltato") for p in passi)
    c = av.get("corrente")
    if av.get("tipo") == "giro":
        if av.get("pausa"):
            pausa = av["pausa"]
            return RIPRESA.frase_in_pausa(
                [_fonte_del_passo(p) for p in pausa["prima_di"]],
                pausa["dal"],
                [_fonte_del_passo(p) for p in pausa.get("attivi") or []],
            )
        dentro = (av.get("dentro") or [None])[0]
        if c and c.get("id") in ("ingest", "tutto") and dentro:
            riga = _riga_avanzamento(dentro)
            return "Read, " + riga[:1].lower() + riga[1:]
        if c:
            sorgente = next((p.get("sorgente") for p in passi if p["id"] == c.get("id")), None)
            nome = P.nome_fonte(sorgente) if sorgente else c["nome"]
            return f"Download {fatti + 1} of {len(passi)}, now {nome}."
        return f"Download, {fatti} steps of {len(passi)}."
    if c:
        riga = f"Step {fatti + 1} of {len(passi)}, now {P.nome_stadio(c['id'], c['nome'])}"

        return riga + (f", for {durata(c['da_s'])}." if c.get("da_s") is not None else ".")
    return f"{fatti} steps of {len(passi)}."


def verdetto(
    fonti_out: list[dict],
    stadi_out: list[dict],
    runs: list[dict],
    occupato: bool = False,
    spazio: dict | None = None,
    soglia_ore: float = 24,
) -> dict:
    ""









    per_id = {s["id"]: s for s in stadi_out}
    ke = per_id.get("l2_knowledge_extract", {}).get("ultimo", {})
    ke_q = ke.get("quando") if ke.get("esito") == "ok" else ke.get("ultimo_ok")
    automatiche = [f for f in fonti_out if f["gruppo"] in ("da_sole", "inventari")]
    scaricate = _piu_recente(*(f["scaricata"] for f in automatiche))
    orologi = f"Sources downloaded {quando(scaricate)}. Knowledge updated {quando(ke_q)}."

    def v(
        livello: str,
        titolo: str,
        frase: str = "",
        azione: dict | None = None,
        oggetto: dict | None = None,
    ) -> dict:
        if (
            occupato
            and azione
            and azione["tipo"] in ("l0", "modo", "full", "full_completa", "pulisci_lock")
        ):
            azione = None
        return {
            "livello": livello,
            "titolo": titolo,
            "frase": frase,
            "orologi": orologi,

            "scaricate": scaricate,
            "nel_cervello": ke_q,
            "azione": azione,
            "oggetto": oggetto,
        }

    if spazio and spazio.get("salute") == "errore":
        return v(
            "errore",
            "The disk is almost full.",
            spazio.get("frase", ""),
            {"tipo": "strumenti", "arg": "disco", "etichetta": "See the disk"},
            {"tipo": "strumenti", "id": "disco"},
        )
    ultimo = runs[-1] if runs else None
    if ultimo and not ultimo.get("vivo") and ultimo.get("esito") in ("fallito", "interrotto"):
        return v(
            "errore",
            "The last run didn't finish.",
            f"{_nome_run(ultimo)}, {ultimo.get('frase') or ultimo.get('esito')}.",
            {"tipo": "apri_run", "arg": ultimo["run_id"], "etichetta": "See"},
            {"tipo": "run", "id": ultimo["run_id"]},
        )
    rotte = [f for f in automatiche if f["salute"] == "errore"]
    if rotte:
        if len(rotte) == 1:
            f = rotte[0]
            return v(
                "errore",
                f"{f['nome']} isn't downloading.",
                f["motivo"],
                _azione_da_diagnosi(f.get("diagnosi"), f["id"]),
                {"tipo": "fonte", "id": f["id"]},
            )
        return v(
            "errore",
            f"{len(rotte)} sources aren't downloading.",
            ", ".join(f["nome"] for f in rotte) + ".",
        )
    # A stage whose last attempt failed (also in a run started from the terminal, which is not in `runs`):
    # the data is not in step, whatever the clocks say.
    falliti = [s for s in stadi_out if s.get("salute") == "errore"]
    if falliti:
        s = falliti[0]
        frase = f"Last attempt {quando((s.get('ultimo') or {}).get('quando'))}."
        if len(falliti) > 1:
            frase += f" Also failed: {', '.join(x['nome'] for x in falliti[1:])}."
        return v(
            "errore",
            f"{s['nome']} failed in the last run.",
            frase,
            (s.get("da_solo") or {}).get("azione"),
            {"tipo": "stadio", "id": s["id"]},
        )
    giorni_ke = _giorni_da(ke_q)
    soglia_ke = getattr(sbk_config, "KB_SILENZIO_GIORNI", 7)
    if giorni_ke is not None and giorni_ke > soglia_ke:
        return v(
            "errore", f"The knowledge has been idle for {giorni_ke:.0f} days.", "A full run is needed."
        )
    indietro = [f for f in automatiche if f["salute"] == "attenzione"]
    if indietro:
        f = indietro[0]
        frase = f"Usually they arrive within {f['ritmo_giorni']} days."
        if len(indietro) > 1:
            frase += f" Also behind: {', '.join(x['nome'] for x in indietro[1:])}."
        return v(
            "attenzione",
            f"{f['nome']} has brought no new data for {f['giorni']:.0f} days.",
            frase,
            _azione_scarica(f["id"]),
            {"tipo": "fonte", "id": f["id"]},
        )
    rileggi = {"tipo": "modo", "arg": "ingest", "etichetta": "Re-read and update"}
    nuove = [f for f in fonti_out if f.get("da_leggere")]
    if nuove:
        ore = _ore_da(min(f["da_leggere"] for f in nuove)) or 0.0
        nomi = _in_fila([f["nome"] for f in nuove])
        verbo = "has" if len(nuove) == 1 else "have"
        frase = f"{nomi} {verbo} new data. Re-read and update brings it in, at no cost."
        if ore >= soglia_ore:
            return v(
                "attenzione",
                f"The new data has been waiting {_attesa_in_parole(ore)}.",
                frase,
                rileggi,
                {"tipo": "fase", "id": "lettura"},
            )
        return v(
            "neutra",
            "There is new data to re-read.",
            frase,
            rileggi,
            {"tipo": "fase", "id": "lettura"},
        )

    letta = _piu_recente(*(s["ultimo"].get("quando") for s in stadi_out if _della_lettura(s["id"])))
    if letta and ke_q and letta > ke_q:
        return v(
            "neutra",
            "There is read data not yet in the brain.",
            "Re-read and update brings it in, at no cost.",
            rileggi,
            {"tipo": "fase", "id": "conoscenza"},
        )
    if not ke_q:
        # A fresh install: never read into the brain, so nothing can be "in step" yet. A source counts as
        # connected when it has any data: downloaded, imported by hand (WhatsApp, Telegram...) or already read.
        if not any(f.get(k) for f in fonti_out for k in ("scaricata", "dato_del", "lettura")):
            return v(
                "neutra",
                "Nothing is connected yet.",
                "Connect a source and download or import it (docs/CONNECTING.md), "
                "then Re-read and update builds the knowledge.",
            )
        return v(
            "neutra",
            "The knowledge is not built yet.",
            "Re-read and update builds it from what you downloaded, at no cost.",
            rileggi,
            {"tipo": "fase", "id": "conoscenza"},
        )
    return v("ok", "The data is in step.")








_FUORI_DAL_RUN = {
    "terminale": (":!tools/secondbrain",),
    "app": tuple(
        f":!tools/secondbrain/{x}"
        for x in ("app", "regole", "sb-app.py", "installa.py", "sb_parole.py", "sb_errori.py")
    ),
}


def cambi_durante(inizio: str | None, chi: str) -> dict | None:
    if not inizio:
        return None
    t0 = _dt(inizio)
    if t0 is None:
        return None
    escludi = _FUORI_DAL_RUN.get(chi, ())
    commit, file_ = [], []
    try:
        r = subprocess.run(
            [
                "git",
                "log",
                f"--since={inizio[:19]}",
                "--format=%h%x09%ct%x09%s",
                "--",
                "tools",
                *escludi,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        for riga in r.stdout.splitlines():
            h, ct, msg = (riga.split("\t", 2) + ["", ""])[:3]
            commit.append(
                {"hash": h, "quando": _iso(float(ct)) if ct.isdigit() else None, "messaggio": msg}
            )
        s = subprocess.run(
            ["git", "status", "--porcelain", "--", "tools", *escludi],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        for riga in s.stdout.splitlines():
            percorso = riga[3:].strip().split(" -> ")[-1]
            f = ROOT / percorso
            if (
                f.is_file()
                and f.suffix in (".py", ".sh", ".json")
                and f.stat().st_mtime > t0.timestamp()
            ):
                file_.append(
                    {"file": percorso, "quando": _iso(f.stat().st_mtime), "salvato": False}
                )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not commit and not file_:
        return None
    ultimo = max([c["quando"] or "" for c in commit] + [f["quando"] for f in file_])
    return {"commit": commit, "file": file_, "ultimo": ultimo}






COPIE_DIR = Path.home() / "Backups" / "sbk"
REGISTRO_COPIE = DATA_ROOT / "logs" / "backup-stderr.log"
SERVIZIO_COPIE = "com.sbk.backup"
_RE_SPAZIO_COPIE = re.compile(r"ratio: ([\d.]+) GB free, need ([\d.]+) GB")

_RE_SPAZIO_REGISTRO = re.compile(r"([\d.]+) GiB free, guard needs ([\d.]+) GiB")



NOMI_COPIE = {
    "l1": "The essentials (L1)",
    "completo": "Full copy",
    "l2": "Sources (L2)",
    "l3": "Closed work (L3)",
}


def _ultime_copie() -> dict[str, tuple[datetime, str]]:
    ""
    out: dict[str, tuple[datetime, str]] = {}
    for m in COPIE_DIR.glob("sbk-*.manifest.json") if COPIE_DIR.exists() else []:
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
            t = datetime.fromisoformat(d["timestamp"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if d.get("verificato") is False:
            continue
        nome = m.name.removesuffix(".manifest.json")
        tipo = f"l{d['livello']}" if "livello" in d else ("completo" if "-full-" in nome else None)
        t = t.astimezone().replace(tzinfo=None) if t.tzinfo else t
        if tipo and (tipo not in out or t > out[tipo][0]):
            out[tipo] = (t, nome)
    return out


def _archivi_fatti() -> list[datetime]:
    ""

    out: list[datetime] = []
    for m in COPIE_DIR.glob("sbk-*.manifest.json") if COPIE_DIR.exists() else []:
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
            t = datetime.fromisoformat(d["timestamp"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if d.get("verificato") is False:
            continue
        out.append(t if t.tzinfo else t.astimezone())
    return out


def _con_fuso(ts: str | None) -> datetime | None:
    ""
    try:
        t = datetime.fromisoformat(ts or "")
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def _esito_launchctl(servizio: str) -> int | None:
    ""

    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        for riga in r.stdout.splitlines():
            pezzi = riga.split("\t")
            if len(pezzi) == 3 and pezzi[2] == servizio and pezzi[1].lstrip("-").isdigit():
                return int(pezzi[1]) or None
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _giro_della_domenica(righe: list[dict] | None = None) -> dict:
    ""



    riga = next((r for r in righe or [] if r.get("key") == SERVIZIO_COPIE), None)
    non_partito = False
    if riga is not None:
        esito = _esito_da_riga(riga)
        non_partito = _non_partito(riga) and riga.get("outcome") != "failed"
    else:
        esito = 1 if _esito_launchctl(SERVIZIO_COPIE) else None
    frase, quando_err = "", None
    try:
        righe = REGISTRO_COPIE.read_text(encoding="utf-8", errors="replace").splitlines()
        errore = next((x for x in reversed(righe) if "[ERROR]" in x), "")
        quando_err = _iso(REGISTRO_COPIE.stat().st_mtime)
        m = _RE_SPAZIO_COPIE.search(errore)

        if riga is not None and riga.get("outcome") == "failed":
            if m2 := _RE_SPAZIO_REGISTRO.search(riga.get("detail") or ""):
                m, quando_err = m2, riga.get("last_run") or quando_err
        if m:

            libero, serve = (float(m.group(i)) * 1024**3 / 1e9 for i in (1, 2))


            try:
                oggi = f", oggi ne restano {shutil.disk_usage(DATA_ROOT).free / 1e9:.0f}"
            except OSError:
                oggi = ""

            giorno = quando(quando_err) if quando_err else ""
            frase = (
                f"On {giorno} space was missing, {serve:.0f} GB free were needed and there were "
                f"{libero:.0f}{oggi}."
                if giorno and not giorno.startswith(("today", "yesterday"))
                else f"The disk is out of space, {serve:.0f} GB needed and {libero:.0f} available{oggi}."
            )
        elif errore:
            frase = "It stopped with an error, the log says why."
    except OSError:
        pass
    if non_partito:

        frase = "The last run didn't start."
    if riga is not None and riga.get("last_run"):
        quando_err = riga["last_run"]
    return {"esito": esito, "frase": frase if esito not in (0, None) else "", "quando": quando_err}


def copie_di_sicurezza(righe: list[dict] | None = None) -> dict:
    ""



    if righe is None:
        righe = _righe_registro(None)
    ultime = _ultime_copie()
    soglia = 8  # days after which a backup level turns red
    livelli = [
        {
            "tipo": tipo,
            "nome": NOMI_COPIE.get(tipo, tipo),
            "quando": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "giorni": round((datetime.now() - t).total_seconds() / 86400, 1),
        }
        for tipo, (t, _) in sorted(
            ultime.items(),
            key=lambda kv: list(NOMI_COPIE).index(kv[0]) if kv[0] in NOMI_COPIE else 9,
        )
    ]
    l1 = max((ultime[k][0] for k in ("l1", "completo") if k in ultime), default=None)
    giorni_l1 = (datetime.now() - l1).total_seconds() / 86400 if l1 else None


    completa = ultime["completo"][0] if "completo" in ultime else None
    tipo_ultima = (
        None if l1 is None else ("completo" if completa is not None and completa >= l1 else "l1")
    )
    giro = _giro_della_domenica(righe)

    if l1 is None:
        salute, frase = "errore", "No backup copy found."
    elif giorni_l1 > soglia:
        salute = "errore"



        if tipo_ultima == "completo" or (completa is not None and completa.date() == l1.date()):
            giorni_c = (datetime.now() - (completa or l1)).total_seconds() / 86400
            frase = f"The last full backup copy is {giorni_c:.0f} days old."
        elif completa is not None:
            giorni_c = (datetime.now() - completa).total_seconds() / 86400
            frase = (
                f"The last full backup copy is {giorni_c:.0f} days old, then {giorni_l1:.0f} "
                "days ago a copy of just the essentials."
            )
        else:
            frase = (
                f"The last backup copy is {giorni_l1:.0f} days old and has only the essentials."
            )
    elif giro["frase"]:
        salute, frase = "attenzione", f"The Sunday run is failing. {giro['frase']}"
    else:
        salute, frase = "ok", "The copies are recent."
    return {
        "livelli": livelli,
        "giro_settimanale": giro,
        "fuori_dal_mac": False,
        "soglia_giorni": soglia,
        "salute": salute,
        "frase": f"{frase} All are on this Mac, none off-site.",

        "ultima": l1.strftime("%Y-%m-%dT%H:%M:%S") if l1 else None,

        "ultima_tipo": tipo_ultima,
        "ultima_completa": completa.strftime("%Y-%m-%dT%H:%M:%S") if completa else None,
    }


def _frase_ultima_copia(copie: dict, lungo: bool = True) -> str:
    ""






    ultima, tipo, completa = (
        copie.get("ultima"),
        copie.get("ultima_tipo"),
        copie.get("ultima_completa"),
    )
    if not ultima:
        return "There is no good copy."
    solo_mac = lungo and not copie.get("fuori_dal_mac")
    if tipo == "l1" and completa and completa[:10] == ultima[:10]:
        tipo, ultima = "completo", completa
    if tipo == "completo":
        return f"The last full copy is {_del(ultima)}" + (
            " and is only on this Mac." if solo_mac else "."
        )
    if tipo == "l1" and completa:
        poi = (
            f"then {quando(ultima)} a copy of just the essentials"
            if lungo
            else f"then {quando(ultima)} one of just the essentials"
        )
        return f"The last full copy is {_del(completa)}, {poi}." + (
            " None is off this Mac." if solo_mac else ""
        )
    if tipo == "l1":
        return f"The last copy is {_del(ultima)} and has only the essentials." + (
            " None is off this Mac." if solo_mac else ""
        )
    return f"The last good copy is {_del(ultima)}" + (
        " and is only on this Mac." if solo_mac else "."
    )









JOBS_DIR = TOOLS / "jobs"


LAVORI_TTL_S = 300


# Friendly names for job labels; only generic SBK jobs by default.
# Extend with the user's own jobs via config (sbk-settings.json / the user job catalog).
NOMI_LAVORI = {
    "com.sbk.backup": "The backup",
    "com.sbk.score-snapshot": "The nightly snapshot of relationship scores",
    "com.sbk.mem-telemetry": "The memory measurement",
}


# Generic failure causes; job-specific causes come from the user job catalog.
CAUSE_LAVORI = (
    ("not enough free disk", "out of disk space"),
)
_RIUSCITI = ("ok", "nothing")
_GIORNI_SETTIMANA = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_CAMPI_RIGA = (
    "key",
    "title",
    "outcome",
    "punctuality",
    "attention",
    "why",
    "detail",
    "last_run",
    "began_at",
    "history",
    "calendar",
    "schedule",
    "loaded",
)


def _jb_status():
    if str(JOBS_DIR) not in sys.path:
        sys.path.insert(0, str(JOBS_DIR))
    import jb_status

    return jb_status


def _firma_registro() -> str:
    ""
    try:
        cartella = _jb_status().JOBS_ROOT
        files = sorted(cartella.glob("events-*.jsonl"))[-2:]
        return "|".join(f"{f.name}:{f.stat().st_mtime_ns}" for f in files)
    except Exception:  # noqa: BLE001 -- without a registry there is no signature, it is recomputed
        return ""


def _serie_fallita(job: str, eventi: list[dict], archivi: list[datetime] | None = None) -> dict:
    ""












    fini, inizio, per_pid = [], None, {}
    for e in eventi:
        if e.get("job") != job or "[manuale]" in (e.get("detail") or ""):
            continue
        pid = e.get("pid")
        if e.get("phase") == "start":
            inizio = e.get("at")
            if pid is not None:
                per_pid[pid] = e.get("at")
        elif e.get("phase") == "end":
            da = per_pid.pop(pid, None) if pid is not None else inizio
            inizio = None
            if e.get("detail") != "dry run":
                fini.append((da, e))

    def fallita(inizio: str | None, e: dict) -> bool:
        if e.get("outcome") == "failed":
            return True
        if archivi is None or e.get("outcome") != "unknown":
            return False
        da, a = _con_fuso(inizio), _con_fuso(e.get("at"))
        if da is None or a is None:
            return False
        if any(da <= t <= a + timedelta(minutes=5) for t in archivi):
            return False
        return any(t < da for t in archivi)

    di_fila, dal = 0, None
    for inizio, e in reversed(fini):
        if not fallita(inizio, e):
            break
        di_fila += 1
        dal = e.get("at")
    return {"di_fila": di_fila, "dal": dal}


def _righe_registro(cache: dict | None) -> list[dict] | None:
    ""


    firma = _firma_registro()
    tenuto = (cache or {}).get("lavori") or {}
    if (
        tenuto.get("firma") == firma
        and firma
        and time.time() - float(tenuto.get("quando") or 0) < LAVORI_TTL_S
    ):
        return tenuto.get("righe")
    try:
        jb = _jb_status()
        st = jb.compute()


        eventi = jb.read_events(months=12)
    except Exception:  # noqa: BLE001 -- a broken registry must not take down the state
        return None
    if st.get("error"):
        return None


    try:
        archivi = _archivi_fatti()
    except Exception:  # noqa: BLE001 -- an unreadable folder must not take down the state
        archivi = None
    righe = [
        {
            **{k: r.get(k) for k in _CAMPI_RIGA},
            **_serie_fallita(
                r.get("key", ""), eventi, archivi if r.get("key") == SERVIZIO_COPIE else None
            ),
        }
        for r in st.get("jobs", [])
        if r.get("where", "local") == "local"
    ]
    if cache is not None:
        cache["lavori"] = {"firma": firma, "quando": time.time(), "righe": righe}
    return righe


def _esito_da_riga(riga: dict) -> int | None:
    ""
    if riga.get("outcome") == "failed" or _non_partito(riga):
        return 1
    if riga.get("outcome") in _RIUSCITI:
        return 0
    return None


def _non_partito(riga: dict) -> bool:
    return riga.get("punctuality") in ("stale", "missed")


def _causa_lavoro(detail: str) -> str | None:
    d = (detail or "").lower()
    return next((it for en, it in CAUSE_LAVORI if en in d), None)


def _minuscola(nome: str) -> str:
    return nome[:1].lower() + nome[1:]


def _del(ts: str | None) -> str:
    ""
    return "from " + quando(ts)


def _giorno_fisso(calendario: list[dict] | None) -> int | None:
    ""

    giorni = {v.get("Weekday") for v in calendario or [] if isinstance(v, dict)}
    if len(giorni) != 1 or None in giorni:
        return None
    w = giorni.pop()
    return 6 if w in (0, 7) else w - 1


def _della(calendario: list[dict] | None) -> str:
    ""
    g = _giorno_fisso(calendario)
    if g is None:
        return ""
    return f" on {_GIORNI_SETTIMANA[g]}"


def _ultimo_previsto(riga: dict) -> datetime | None:
    try:
        _jb_status()
        from jb_catalog import prev_fire

        t = prev_fire(riga.get("calendar") or [])
    except Exception:  # noqa: BLE001
        return None
    return t.astimezone().replace(tzinfo=None) if t and t.tzinfo else t


def _voce_lavoro(riga: dict, copie: dict | None) -> dict:
    ""

    chiave = riga.get("key") or ""
    nome = NOMI_LAVORI.get(chiave, riga.get("title") or chiave)
    backup = chiave == SERVIZIO_COPIE
    causa = _causa_lavoro(riga.get("detail") or "")
    fallito = riga.get("outcome") == "failed"
    tipo = "fallito" if fallito else ("non_partito" if _non_partito(riga) else "altro")
    if tipo == "fallito":
        if (riga.get("di_fila") or 0) > 1 and riga.get("dal"):
            titolo = f"{nome}{_della(riga.get('calendar'))} fails {_dal(riga['dal'])}"
        else:
            titolo = f"{nome}{_della(riga.get('calendar'))} failed {quando(riga.get('last_run'))}"
        salute = "errore"
    elif tipo == "non_partito":
        previsto = _ultimo_previsto(riga)
        g = _giorno_fisso(riga.get("calendar"))
        if previsto and g is not None and (datetime.now() - previsto).days < 7:
            titolo = f"{nome} on {_GIORNI_SETTIMANA[g]} didn't start"
        elif previsto:
            titolo = f"{nome} didn't start {quando(previsto.strftime('%Y-%m-%dT%H:%M:%S'))}"
        else:
            titolo = f"{nome} didn't start"
        causa = None
        salute = "errore" if backup else "attenzione"
    else:
        perche = riga.get("why") or ""
        if not riga.get("loaded"):
            titolo = f"{nome} isn't loaded, it won't start on its own"
        elif perche.startswith("loaded, but its plist is gone"):
            titolo = f"{nome} no longer has its file but still starts until reboot"
        elif perche.startswith("its log moved"):
            titolo = f"{nome} ran without saying how it went"
        else:
            titolo = f"{nome} needs a look"
        causa = None
        salute = "attenzione"
    dettaglio = []
    if causa:
        dettaglio.append(causa[:1].upper() + causa[1:] + ".")

    avviso_titolo = f"{nome} " + {"fallito": "failed", "non_partito": "didn't start"}.get(
        tipo, "needs a look"
    )
    avviso_testo = list(dettaglio)
    if backup and copie is not None and copie.get("ultima"):
        avviso_testo.append(_frase_ultima_copia(copie, lungo=False))
    if backup and copie is not None:


        dettaglio.append(_frase_ultima_copia(copie, lungo=tipo == "fallito"))
    frase = titolo + (f", {causa}." if causa else ".")
    resto = [d for d in dettaglio if not causa or not d.lower().startswith(causa[:12].lower())]
    frase = " ".join([frase, *resto]).strip()
    return {
        "id": chiave,
        "nome": nome,
        "tipo": tipo,
        "salute": salute,
        "titolo": titolo,
        "dettaglio": " ".join(dettaglio),
        "frase": frase,
        "ultimo": riga.get("last_run"),
        "di_fila": riga.get("di_fila") or 0,
        "dal": riga.get("dal"),

        "chiave_avviso": f"{chiave}@{riga.get('last_run') or ''}@{tipo}",
        "avviso": {"titolo": avviso_titolo, "testo": " ".join(avviso_testo) or titolo + "."},
        "oggetto": {"tipo": "copie", "id": "backup"}
        if backup
        else {"tipo": "strumenti", "id": chiave},
        "azione": {"tipo": "copie" if backup else "strumenti", "arg": "", "etichetta": "See"},
    }


def lavori_automatici(righe: list[dict] | None, copie: dict | None = None) -> dict:
    ""

    if righe is None:
        return {
            "letto": False,
            "salute": "neutra",
            "frase": "",
            "da_guardare": [],
            "non_collegati": [],
        }
    da_guardare, non_collegati = [], []
    for r in righe:
        generico = (r.get("why") or "").startswith("not wired up yet")
        if generico and r.get("outcome") != "failed":
            non_collegati.append(r.get("key") or "")
            continue
        if r.get("attention"):
            da_guardare.append(_voce_lavoro(r, copie))

    da_guardare.sort(key=lambda v: (v["salute"] != "errore", v["id"] != SERVIZIO_COPIE, v["id"]))
    errori = [v for v in da_guardare if v["salute"] == "errore"]
    if len(errori) == 1:
        frase = errori[0]["frase"]
    elif errori:
        quanti = {2: "Two", 3: "Three", 4: "Four"}.get(len(errori), str(len(errori)))
        frase = f"{quanti} automations failed, {_in_fila([_minuscola(v['nome']) for v in errori])}."
    else:
        frase = ""
    salute = "errore" if errori else ("attenzione" if da_guardare else "ok")
    return {
        "letto": True,
        "salute": salute,
        "frase": frase,
        "da_guardare": da_guardare,
        "non_collegati": non_collegati,
    }


def da_sistemare(
    fonti_out: list[dict],
    stadi_out: list[dict],
    verdetto_out: dict,
    runs: list[dict],
    occupato: bool,
    copie: dict | None = None,
    spazio: dict | None = None,
    soglia_ore: float = 24,
    verifiche: dict | None = None,
    lavori: dict | None = None,
) -> tuple[list[dict], int]:
    ""

    righe: list[dict] = []

    def riga(livello, titolo, frase, oggetto, azione=None) -> None:
        if occupato and azione and azione["tipo"] in ("l0", "modo", "full", "pulisci_lock"):
            azione = None
        righe.append(
            {
                "livello": livello,
                "titolo": titolo,
                "frase": frase,
                "oggetto": oggetto,
                "azione": azione,
            }
        )

    ultimo = runs[-1] if runs else None
    if ultimo and not ultimo.get("vivo") and ultimo.get("esito") in ("fallito", "interrotto"):
        riga(
            "errore",
            f"{_nome_run(ultimo)} didn't finish",
            (ultimo.get("frase") or "").capitalize() + ".",
            {"tipo": "run", "id": ultimo["run_id"]},
            {"tipo": "apri_run", "arg": ultimo["run_id"], "etichetta": "See"},
        )


    for v in (lavori or {}).get("da_guardare", []):
        if v["salute"] == "errore":
            riga("errore", v["titolo"], v["dettaglio"], v["oggetto"], v["azione"])
    for f in fonti_out:
        if f["gruppo"] in ("da_sole", "inventari") and f["salute"] == "errore":
            riga(
                "errore",
                f"{f['nome']} isn't downloading",
                f["motivo"],
                {"tipo": "fonte", "id": f["id"]},
                _azione_da_diagnosi(f.get("diagnosi"), f["id"]),
            )

    for f in fonti_out:
        if f["gruppo"] == "a_mano" and f["salute"] == "errore":
            riga(
                "errore",
                f"{f['nome']}, {f['parola'].lower()}",
                f["motivo"],
                {"tipo": "fonte", "id": f["id"]},
                {"tipo": "come_si_fa", "arg": f["id"], "etichetta": "How to do it"},
            )
    for s in stadi_out:
        if s["salute"] == "errore":
            riga(
                "errore",
                f"{s['nome']} failed",
                f"Last attempt {quando(s['ultimo']['quando'])}.",
                {"tipo": "stadio", "id": s["id"]},
                s["da_solo"]["azione"],
            )
    for f in fonti_out:
        if f["gruppo"] in ("da_sole", "inventari") and f["salute"] == "attenzione":
            riga(
                "attenzione",
                f"{f['nome']}, {f['parola'].lower()}",
                f["motivo"],
                {"tipo": "fonte", "id": f["id"]},
                _azione_scarica(f["id"]),
            )

    if spazio and spazio.get("salute") in ("errore", "attenzione"):
        riga(
            spazio["salute"],
            "The disk is filling up",
            spazio["frase"],
            {"tipo": "strumenti", "id": "disco"},
            {"tipo": "strumenti", "arg": "disco", "etichetta": "See"},
        )

    gia_detto = any(r["oggetto"] == {"tipo": "copie", "id": "backup"} for r in righe)
    if copie and copie.get("salute") in ("errore", "attenzione") and not gia_detto:
        riga(
            copie["salute"],
            "Backups",
            copie["frase"],
            {"tipo": "copie", "id": "backup"},
            {"tipo": "copie", "arg": "", "etichetta": "See the copies"},
        )


    nuove = [f for f in fonti_out if f.get("da_leggere")]
    ore = _ore_da(min(f["da_leggere"] for f in nuove)) if nuove else None
    if ore is not None and ore >= soglia_ore:
        riga(
            "attenzione",
            f"New data to re-read {_attesa_in_parole(ore)}",
            f"{_in_fila([f['nome'] for f in nuove])}. Re-read and update brings it in, at no cost.",
            {"tipo": "fase", "id": "lettura"},
            {"tipo": "modo", "arg": "ingest", "etichetta": "Re-read and update"},
        )
    da_portare = [
        f for f in fonti_out if f["gruppo"] == "a_mano" and f["parola"].startswith("To bring in")
    ]
    if len(da_portare) == 1:
        f = da_portare[0]
        riga(
            "neutra",
            f"{f['nome']}, {f['giorni']:.0f} days behind",
            P.TOCCA_A_TE.get(f["id"], "Your turn."),
            {"tipo": "fonte", "id": f["id"]},
            {"tipo": "come_si_fa", "arg": f["id"], "etichetta": "How to do it"},
        )
    elif da_portare:

        quanti = {2: "Two", 3: "Three", 4: "Four"}.get(len(da_portare), str(len(da_portare)))
        elenco = ", ".join(
            f"{f['nome']} {f['giorni']:.0f}" + (" days behind" if i == 0 else "")
            for i, f in enumerate(da_portare)
        )
        riga(
            "neutra",
            f"{quanti} sources to bring in by hand",
            f"{elenco}. Your turn.",
            {"tipo": "gruppo", "id": "a_mano"},
            {"tipo": "come_si_fa", "arg": "a_mano", "etichetta": "How to do it"},
        )


    if verifiche and verifiche.get("con_peso"):
        n = verifiche["con_peso"]
        riga(
            "neutra",
            f"{_cifra(n)} {'contact' if n == 1 else 'contacts'} to verify",
            "The merge doesn't link them by name until you say who they are. The ones with the most messages are at the top.",
            {"tipo": "stadio", "id": "l2_merge"},
            {"tipo": "verifiche", "arg": "", "etichetta": "Verify"},
        )
    pagati = [s for s in stadi_out if s["pagato"]]
    if pagati:
        vecchio = _piu_vecchia(*(s["ultimo"]["quando"] for s in pagati))
        riga(
            "neutra",
            f"Text extraction, idle {_dal(vecchio) if vecchio else 'forever'}",
            "It's paid, you decide.",
            {"tipo": "fase", "id": "estrazione"},
            {"tipo": "stima", "arg": "", "etichetta": "See the estimate"},
        )

    if verdetto_out.get("oggetto"):
        righe = [r for r in righe if r["oggetto"] != verdetto_out["oggetto"]]
    return righe[:5], max(0, len(righe) - 5)





def azioni(occupato_da: str | None, giro: dict | None) -> dict:
    ""
    piano = list(L0R.PIANO)
    automatiche = sorted({p.sorgente for p in piano})
    menu = [
        {
            "id": "full",
            "tipo": "full",
            "arg": "",
            **P.RUN["full"],
            "step": f"{1 + len(XPR.perimetro('ingest'))} step",
            "spesa": False,
        },
        {
            "id": "full_completa",
            "tipo": "full_completa",
            "arg": "",
            **P.RUN["full_completa"],
            "step": f"{1 + len(XPR.perimetro('tutto'))} step",
            "spesa": True,
        },
        {
            "id": "l0",
            "tipo": "l0",
            "arg": "",
            **P.RUN["l0"],
            "step": f"{len(automatiche)} sources",
            "spesa": False,
        },
    ]
    for m in ("ingest", "propaga", "ricostruisci", "tutto"):
        menu.append(
            {
                "id": m,
                "tipo": "modo",
                "arg": m,
                **P.RUN[m],
                "step": f"{len(XPR.perimetro(m))} step",
                "spesa": m == "tutto",
            }
        )
    fuori_pagati = [P.nome_stadio(p.id, p.nome) for p in XPR.CATENA if p.tipo == "pagato"]
    ultima = (giro or {}).get("ultima_volta") or ""
    if not ultima and giro and giro.get("inizio"):
        if giro.get("fine"):
            d = (_dt(giro["fine"]) - _dt(giro["inizio"])).total_seconds()
            ultima = (
                f"The last full run started {quando(giro['inizio'])} and took {durata(d)}."
            )
        else:
            ultima = (
                f"The last full run started {quando(giro['inizio'])} and has no end line."
            )
    return {
        "possibile": occupato_da is None,
        "perche": occupato_da or "",
        "menu": menu,
        "conferma_full": {
            "passi": [
                {

                    "titolo": f"Downloads {len(automatiche)} sources, some together",
                    "frase": "Slack, ClickUp and Google Drive in their own lanes, the others in line, if memory allows. "
                    "Each download has 3 attempts.",
                },
                {
                    "titolo": "Makes a backup of the brain",
                    "frase": "Before touching it, and checks the copy opens.",
                },
                {
                    "titolo": "Re-reads and updates",
                    "frase": f"{len(XPR.perimetro('ingest'))} steps at no cost, from the read to the indexes.",
                },
            ],
            "fuori": [
                f"The {len(fuori_pagati)} paid steps, {', '.join(fuori_pagati)}. You choose them one by one in the Full run complete.",
                f"The {len(L0R.MANUALI)} manual sources, {', '.join(P.nome_fonte(s) for s in L0R.MANUALI)}.",
            ],
            "ultima_volta": ultima,
        },
    }





def _testa_del_repo() -> str:
    ""

    try:
        testa = (ROOT / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if testa.startswith("ref: "):
            return (ROOT / ".git" / testa.removeprefix("ref: ")).read_text(encoding="utf-8").strip()
        return testa
    except OSError:
        return ""


def _impronta(cache: dict, fresco: bool) -> dict:
    ""



    imp = cache.get("impronta") or {}
    testa = _testa_del_repo()
    if (
        fresco
        or time.time() - imp.get("quando", 0) > ETA_SCADENZA_S
        or (testa and testa != imp.get("testa"))
        or "contenuto" not in imp
    ):

        def git(*args: str) -> str:
            try:
                return subprocess.run(
                    ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5
                ).stdout.strip()
            except (subprocess.SubprocessError, OSError):
                return ""

        imp = {
            "motore": git("rev-parse", "--short", "HEAD"),
            "app": git("log", "-1", "--format=%h", "--", "tools/secondbrain/app"),


            "contenuto": SBI.contenuto_app(ROOT / "tools" / "secondbrain" / "app"),
            "quando": time.time(),
            "testa": testa,
        }
        try:
            imp["versione"], imp["storia"] = SBV.corrente(), SBV.storia()
        except Exception:
            imp["versione"], imp["storia"] = "", []
        cache["impronta"] = imp
    return {
        "motore": imp.get("motore", ""),
        "app": imp.get("app", ""),
        "contenuto": imp.get("contenuto", ""),
        "versione": imp.get("versione", ""),
        "storia": imp.get("storia", []),
    }


def cmd_stato(fresco: bool = False) -> dict:
    t0 = time.perf_counter()
    cache, prima = _carica_cache()
    idx = _indice(cache)
    in_corso = _processi_pipeline()
    eta = _eta_tutte(cache, in_corso, fresco)
    for sid in DATO_VERO:
        if (vero := _dato_vero(sid)) is not None:
            eta[sid] = vero

    wa = whatsapp_import(XPR._l0_dir("whatsapp"), cache=cache)
    eta = {**eta, "whatsapp": wa["eta"]}
    impronta = _impronta(cache, fresco)
    chiavi = _chiavi()

    registro = _righe_registro(cache)
    _salva_cache(cache, prima)

    runs = _runs()
    run_app = next((r for r in reversed(runs) if r["vivo"]), None)
    av = avanzamento(run_app) if run_app else None
    giro = _ultimo_giro_l0()
    giro_app = bool(
        run_app and giro and Path(run_app.get("cartella") or "/") == Path(giro["cartella"])
    )
    if giro:
        recente = (giro.get("ultimo_segno_s") or 10**9) < 15 * 60
        giro["vivo"] = giro["fine"] is None and (giro_app or bool(in_corso) or recente)
        giro.update(_giro_intero(giro, runs))

    in_scarico: set[str] = set()
    correnti: dict[str, str] = {}
    if av and av.get("tipo") == "giro":
        if av.get("corrente"):
            in_scarico.add(av["corrente"]["id"])
        dentro = (av.get("dentro") or [None])[0]
        if dentro:
            correnti = {p["id"]: p["stato"] for p in dentro["passi"]}
        else:
            correnti = {"l0_download": "in_corso"}
    elif av:
        correnti = {p["id"]: p["stato"] for p in av["passi"]}
    elif giro and giro["vivo"] and giro.get("passo_in_corso"):
        in_scarico.add(giro["passo_in_corso"])
    scarichi = _scarichi_soli()
    sole = {d["sorgente"] for d in scarichi if d["vivo"]}
    in_scarico |= {p.nome for p in L0R.PIANO if p.sorgente in sole}

    fo = fonti(idx, eta, in_scarico, wa)
    for f in fo:
        f["aiuto"] = _aiuto_fonte(f)

    soglia_ore = IMP.leggi()["lettura"]["ore_attesa"]
    st = stadi(idx, giro, fo, correnti, (cache.get("eta") or {}).get("spesa"), soglia_ore)
    fa = fasi(st, fo)

    da_fuori = {"attivo": False, "processi": in_corso, "giro": None, "frase": ""}
    if not run_app and (in_corso or (giro and giro["vivo"])):
        da_fuori["attivo"] = True
        if giro and giro["vivo"]:
            da_fuori["giro"] = _leggi_giro(
                Path(giro["cartella"]),
                None,
                giro.get("poi_ingest", True),
                giro.get("finale", "ingest"),
            )
            passo = giro.get("passo_in_corso")
            nome = P.nome_fonte(
                next((p.sorgente for p in L0R.PIANO if p.nome == passo), passo or "")
            )
            segno = giro.get("ultimo_segno_s")
            chi = ((da_fuori["giro"] or {}).get("corrente") or {}).get("al_lavoro")


            da_fuori["frase"] = f"Now {nome or 'the download'}." + (
                (
                    f" Working {chi}, no new lines for {durata(segno)}."
                    if chi
                    else f" No new lines for {durata(segno)}."
                )
                if segno is not None and segno > 15 * 60
                else ""
            )
        elif in_corso:
            p = max(in_corso, key=lambda x: _secondi_etime(x["etime"]))
            da_fuori["frase"] = f"Now {p['script']}, for {durata(_secondi_etime(p['etime']))}."

    occupato_da = None
    if run_app:
        occupato_da = f"One run at a time. {_nome_run(run_app)} is already running."
    elif da_fuori["attivo"]:
        occupato_da = "One run at a time. A run launched from a terminal is already going."
    copie = copie_di_sicurezza(registro)
    lavori = lavori_automatici(registro, copie)
    spazio = spazio_disco()
    ver = verdetto(fo, st, runs, occupato_da is not None, spazio, soglia_ore)
    da_verificare = riassunto_verifiche()
    righe, altri = da_sistemare(
        fo, st, ver, runs, occupato_da is not None, copie, spazio, soglia_ore, da_verificare, lavori
    )
    try:
        pressione = CTL.pressure()
        memoria = {"livello": getattr(pressione, "level", None) or str(pressione)}
        if isinstance(getattr(pressione, "seg_ratio", None), int | float):

            memoria["pressione_pct"] = round(pressione.seg_ratio * 100)
    except Exception as e:  # noqa: BLE001
        memoria = {"livello": f"not measured ({type(e).__name__})"}
    try:
        disco = shutil.disk_usage(DATA_ROOT)

        memoria["disco_libero_gb"] = round(disco.free / 1e9)
        memoria["disco_totale_gb"] = round(disco.total / 1e9)
    except OSError:
        pass
    durate_tipiche = idx.durate_tipiche()
    if av is not None:
        av["previsione"] = previsione(av, durate_tipiche, inizio=run_app.get("inizio"))
    if da_fuori.get("giro"):
        da_fuori["giro"]["previsione"] = previsione(da_fuori["giro"], durate_tipiche)
    return {
        "contratto": CONTRATTO,
        "impronta": impronta,
        "generato": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "verdetto": ver,
        "da_sistemare": righe,
        "altri_da_sistemare": altri,
        "fasi": fa,
        "stadi": st,
        "fonti": fo,
        "gruppi_fonti": list(P.GRUPPI_FONTI),
        "run_app": {
            **run_app,
            "nome": _nome_run(run_app),
            "avanzamento": av,
            "riga": _riga_avanzamento(av),

            "comandi": comandi_del_run(run_app, av),
        }
        if run_app
        else None,
        "da_fuori": da_fuori,
        "ultimo_full_run": giro,

        "capsula": _capsula(giro),

        "completa": P.COMPLETA,

        "codice_cambiato": cambi_durante(run_app["inizio"], "app")
        if run_app
        else (
            cambi_durante((giro or {}).get("inizio"), "terminale") if da_fuori["attivo"] else None
        ),

        "vocabolario": P.VOCABOLARIO,
        "guida": P.GUIDA,
        "runs": [
            {**r, "nome": _nome_run(r) + (", from terminal" if r.get("da_terminale") else "")}
            for r in sorted([*runs, *_runs_da_terminale()], key=lambda r: r["inizio"])[-30:]
        ],
        "azioni": azioni(occupato_da, giro),
        "sonno": sonno_e_corrente(),
        "memoria": memoria,
        "durate_tipiche": {k: v for k, v in durate_tipiche.items() if not k.startswith("l0:")},
        "autopilota_spento": not CTL.automatic_cascades_on(),
        "chiavi": chiavi,

        "scarichi_soli": scarichi,
        "da_sola": _da_sola_tutte(in_corso, run_app, scarichi),

        "stima": cmd_stima(solo_ultima=True).get("stima"),

        "fuori_stima": fuori_dalla_stima(),

        "copie": copie,

        "lavori": lavori,
        "disco": spazio,

        "ripresa": ripresa_possibile(runs, giro, occupato_da),
        "lotti_in_sospeso": lotti_in_sospeso(eta),

        "verifiche": da_verificare,

        "tempo_ms": round((time.perf_counter() - t0) * 1000),
    }





CHIAVE_API = "ANTHROPIC_API_KEY"
_RIGA_CHIAVE_API = re.compile(r"\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*?)\s*$")


def _dove_chiave_api(env_file: Path | None = None) -> str | None:
    """Where ANTHROPIC_API_KEY is set: "the environment", ".env", or None. Never returns the value."""
    if os.environ.get(CHIAVE_API):
        return "the environment"
    f = env_file or ROOT / ".env"
    try:
        righe = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for r in righe:
        m = _RIGA_CHIAVE_API.match(r)
        if m and m.group(1).strip("\"'"):
            return ".env"
    return None


def _chiavi(env_file: Path | None = None) -> list[dict]:
    """The one key the paid steps use, for the app: its name, where it is set, whether it is there.

    One entry, never a queue: the paid steps use ANTHROPIC_API_KEY from the environment or .env.
    """
    dove = _dove_chiave_api(env_file)
    return [
        {
            "nome": CHIAVE_API,
            "origine": dove,
            "presente": dove is not None,
            "di_turno": True,
            "paga": dove is not None,
            "ultimo_uso": None,
            "errore": None,
            "errore_quando": None,
        }
    ]


def _secondi_etime(etime: str) -> int:
    ""
    giorni, _, resto = etime.rpartition("-")
    parti = [int(x) for x in resto.split(":") if x.isdigit()]
    while len(parti) < 3:
        parti.insert(0, 0)
    h, m, s = parti[-3:]
    return (int(giorni) if giorni.isdigit() else 0) * 86400 + h * 3600 + m * 60 + s


def _comando(
    tipo: str, arg: str, consenti_spesa: bool, cartella: Path | None = None
) -> tuple[list[str], str]:


    dove = ["--dir", str(cartella)] if cartella else []
    if tipo == "full":

        return [*PY, "tools/secondbrain/sb-full.py", "--modo", "ingest", *dove], "full-run"
    if tipo == "full_completa":


        if not consenti_spesa:
            raise ValueError("The full run complete spends: your confirmation is required.")
        cmd = [*PY, "tools/secondbrain/sb-full.py", "--modo", "tutto", "--consenti-spesa", *dove]
        return cmd, "full-run-completo"
    if tipo == "l0":


        cmd = [*PY, "tools/secondbrain/sb-full.py", "--solo-scarico"]
        if arg:
            if arg not in {p.sorgente for p in L0R.PIANO}:
                raise ValueError(f"«{arg}» is not in the L0 run (manual or unknown)")
            cmd += ["--solo", arg]
        return [*cmd, *dove], f"l0-{arg or 'tutte'}"
    if tipo == "modo":
        if arg not in MODI:
            raise ValueError(f"unknown mode: {arg}")
        cmd = [*PY, "tools/cross-source/xs-pipeline-run.py", f"--{arg}"]
        if arg == "tutto":
            if not consenti_spesa:
                raise ValueError("--tutto contains paid stages: your confirmation is required")
            cmd.append("--consenti-spesa")
        return cmd, f"modo-{arg}"
    if tipo == "riprendi":


        vecchio = RIPRESA.leggi_giro(Path(arg), [p.nome for p in L0R.PIANO])
        if not vecchio.trovato:
            raise ValueError("Can't find the log of the run to resume.")
        if vecchio.modo is None:
            raise ValueError("That run only downloaded: redo it with Download the sources.")
        cmd = [*PY, "tools/secondbrain/sb-full.py", "--modo", vecchio.modo]
        if vecchio.modo == "tutto":
            if not consenti_spesa:
                raise ValueError("The run to resume spends money: it needs your confirmation.")
            cmd.append("--consenti-spesa")
        return [*cmd, "--riprendi", str(arg), *dove], "full-run-ripreso"
    if tipo == "stadio":
        passo = XPR.CATENA_PER_ID.get(arg)
        if passo is None:
            raise ValueError(f"unknown stage: {arg}")
        if passo.id == "l0_download":
            return _comando("l0", "", consenti_spesa, cartella)
        if passo.strato == "L1":
            raise ValueError(
                "The read steps are redone together, source by source, with Re-read and update."
            )


        cmd = [*PY, "tools/cross-source/xs-pipeline-run.py"]
        if passo.tipo == "pagato":
            if not consenti_spesa:
                raise ValueError("This step is paid: your confirmation of the spend is required.")
            cmd += ["--tutto", "--consenti-spesa"]
        else:
            cmd.append("--propagate")
        return [*cmd, "--solo-stadio", passo.id], f"stadio-{passo.id}"
    raise ValueError(f"unknown type: {tipo}")


def _cartella_run(etichetta: str) -> Path:
    # The caller creates it (mkdir parents=True).
    return FULLRUN / f"{datetime.now():%Y-%m-%d}-app-{etichetta}"


def cmd_lancia(tipo: str, arg: str, consenti_spesa: bool, spesa: list[str] | None = None) -> dict:
    try:
        prova, etichetta = _comando(tipo, arg, consenti_spesa)
    except ValueError as e:
        return {"ok": False, "errore": str(e)}
    sole = _sole_in_mezzo(prova)
    if sole:
        return {
            "ok": False,
            "errore": f"{sole} is downloading on its own. This run launches when it's done. "
            "The full run instead starts right away and waits for that source.",
        }
    spende = tipo == "full_completa" or (tipo == "modo" and arg == "tutto")
    if tipo == "stadio" and getattr(XPR.CATENA_PER_ID.get(arg), "tipo", "") == "pagato":

        spende, spesa = True, [arg]
    if tipo == "riprendi":
        vecchio = RIPRESA.leggi_giro(Path(arg), [p.nome for p in L0R.PIANO])
        spende = vecchio.modo == "tutto"
        if spende and spesa is None:

            scelti = vecchio.spesa or "tutti"
            tutti = [p.id for p in XPR.CATENA if p.tipo == "pagato"]
            spesa = tutti if scelti == "tutti" else [s for s in scelti.split(",") if s]
    pagati = [p.id for p in XPR.CATENA if p.tipo == "pagato"]
    extra: dict[str, str] = {}
    if spesa is not None:
        ignoti = sorted(set(spesa) - set(pagati))
        if ignoti:
            return {"ok": False, "errore": f"unknown paid steps: {', '.join(ignoti)}"}
        if spende and not spesa:
            return {
                "ok": False,
                "errore": "Choose at least one paid step, or use the full run free.",
            }

        extra["SBK_SPESA_STADI"] = ",".join(pid for pid in pagati if pid in spesa)
    SYSTEM.mkdir(parents=True, exist_ok=True)



    lock = LOCK_RUN.open("a+")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            chi = _gira_dall_app() or {}
            return {
                "ok": False,
                "errore": f"{chi.get('etichetta', 'a run')} is already running, launched from here. One run at a time.",
            }
        altri = _occupato_da_fuori()
        if altri:
            return {
                "ok": False,
                "errore": f"the pipeline is already running somewhere else ({', '.join(altri[:4])}). "
                "One run at a time.",
            }
        adesso = datetime.now()
        run_id = f"{adesso:%Y%m%d-%H%M%S}-{etichetta}"
        cartella = _cartella_run(f"{etichetta}-{adesso:%H%M%S}")
        cartella.mkdir(parents=True, exist_ok=True)
        cmd, _ = _comando(tipo, arg, consenti_spesa, cartella)
        log = cartella / f"{run_id}.log"
        voce = {
            "run_id": run_id,
            "etichetta": etichetta,
            "comando": " ".join(cmd),
            "log": str(log),
            "cartella": str(cartella),
            "inizio": adesso.strftime("%Y-%m-%dT%H:%M:%S"),
            "fine": None,
        }
        if spende:
            voce["spesa"] = extra.get("SBK_SPESA_STADI", ",".join(pagati)).split(",")


            tetto = tetto_spesa(voce["spesa"])
            if tetto is not None:
                extra["SBK_BATCH_MAX_USD"] = f"{tetto:.2f}"
                voce["tetto_usd"] = tetto


        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps({"run_id": run_id, "etichetta": etichetta}))
        lock.flush()
        with RUNS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(voce, ensure_ascii=False) + "\n")


        proc = subprocess.Popen(
            [sys.executable, str(SB_RUN), run_id, str(cartella), "--", *cmd],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(lock.fileno(),),

            env=dict(
                os.environ,
                **AMBIENTE_RUN,
                **extra,
                SBK_RUN_LOCK_FD=str(lock.fileno()),
                SBK_RUN_REGISTRO=str(RUNS),
                SBK_RUN_LOCK=str(LOCK_RUN),
            ),
        )
        tenuto = {
            "run_id": run_id,
            "etichetta": etichetta,
            "custode_pid": proc.pid,
            "custode_avvio": _avvio_processo(proc.pid),
        }
        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps(tenuto))
        lock.flush()
        return {"ok": True, **voce, "pid": proc.pid, "vivo": True}
    finally:

        lock.close()


def cmd_ferma(run_id: str, forza: bool = False) -> dict:
    ""

    run = next((r for r in _runs() if r["run_id"] == run_id), None)
    if run is None:
        return {"ok": False, "errore": f"unknown run: {run_id}"}
    if not run["vivo"]:
        return {"ok": False, "errore": "the run isn't alive"}
    Path(run["log"]).with_suffix(".ferma").write_text(_adesso())
    if forza:
        tenuto = _gira_dall_app() or {}
        pid = tenuto.get("custode_pid")
        if not (
            tenuto.get("run_id") == run_id
            and pid
            and _avvio_processo(pid) == tenuto.get("custode_avvio")
        ):
            return {"ok": False, "errore": "the keeper doesn't match, no signal sent"}
        os.kill(pid, signal.SIGTERM)
    return {"ok": True, "richiesto": True}









def _fonte_del_passo(nome: str) -> str:
    ""

    sorgente = next((p.sorgente for p in L0R.PIANO if p.nome == nome), None)
    return P.nome_fonte(sorgente) if sorgente else P.PASSI_GIRO.get(nome, nome)


def cmd_pausa(run_id: str) -> dict:
    ""
    run = next((r for r in _runs() if r["run_id"] == run_id), None)
    if run is None:
        return {"ok": False, "errore": f"unknown run: {run_id}"}
    if not run["vivo"]:
        return {"ok": False, "errore": "the run isn't alive"}
    if "sb-full.py" not in run.get("comando", ""):
        return {"ok": False, "errore": RIPRESA.PAUSA["non_full"]}
    Path(run["log"]).with_suffix(".pausa").write_text(_adesso())
    return {"ok": True, "richiesta": True}


def cmd_continua(run_id: str) -> dict:
    ""
    run = next((r for r in _runs() if r["run_id"] == run_id), None)
    if run is None:
        return {"ok": False, "errore": f"unknown run: {run_id}"}
    Path(run["log"]).with_suffix(".pausa").unlink(missing_ok=True)
    return {"ok": True}


def _fase_del_run(av: dict | None) -> tuple[str, dict | None]:
    ""
    if not av or av.get("tipo") != "giro":
        return "altro", None
    correnti = av.get("correnti") or ([av["corrente"]] if av.get("corrente") else [])
    if av.get("pausa") and not correnti:
        return "in_pausa", None
    ids = {c["id"] for c in correnti}
    if ids & {"ingest", "tutto"}:
        if ((av.get("dentro") or [None])[0] or {}).get("pausa"):
            return "in_pausa", None
        dentro = ((av.get("dentro") or [None])[0] or {}).get("corrente")
        if dentro and dentro.get("pagato"):
            return ("pagato_attesa" if dentro.get("lotti_salvati") else "pagato_invio"), dentro
        return "rilettura", dentro
    if "backup-kb" in ids:
        return "copia", None
    if ids:
        return "scarico", None
    aperto = next((p for p in av.get("passi", []) if p["stato"] in ("da_fare", "ritento")), None)
    if aperto is None:
        return "altro", None
    if aperto["id"] in ("ingest", "tutto"):
        return "rilettura", None
    return ("copia" if aperto["id"] == "backup-kb" else "scarico"), None



_L1_DIZIONARI = (
    "L1_SCRIPTS_PRE",
    "L1_SCRIPTS_BASE",
    "L1_SCRIPTS_DEPENDENT",
    "L1_SCRIPTS_WA_DEEP",
    "L1_SCRIPTS_SPEAKERS",
)


def _chi_dal_nome(script: str) -> str:
    ""
    for nome_dict in _L1_DIZIONARI:
        for fonte, percorso in (getattr(XPR, nome_dict, None) or {}).items():
            if Path(str(percorso)).name == script:
                return f"the read of {P.nome_fonte(fonte)}"
    for sid, percorso in (getattr(XPR, "SCRIPTS", None) or {}).items():
        if Path(str(percorso)).name == script:
            return P.nome_stadio(sid, sid)
    return script


def _pipeline_al_lavoro() -> str | None:
    ""


    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,%cpu=,command="], capture_output=True, text=True, timeout=15
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    io = os.getpid()
    piu_attivo: tuple[float, str | None] = (0.0, None)
    for riga in out.splitlines():
        parti = riga.split(None, 2)
        if len(parti) < 3 or not parti[0].isdigit() or int(parti[0]) == io:
            continue
        try:
            cpu = float(parti[1].replace(",", "."))
        except ValueError:
            continue
        nome = _eseguito(parti[2].split())
        if not nome or not nome.endswith(".py") or nome.startswith(("sb-app", "sb-run")):
            continue
        if not (nome.startswith(("xs-", "rq")) or any(f"-l{n}-" in nome for n in "0123")):
            continue
        if cpu >= 2.0 and cpu > piu_attivo[0]:
            piu_attivo = (cpu, nome)
    return _chi_dal_nome(piu_attivo[1]) if piu_attivo[1] else None








_AL_LAVORO_MIN = 0.005


_PUNTO_INDICE = DATA_ROOT / "l3" / "vectordb" / "index-checkpoint.json"


def _secondi_cpu(testo: str) -> float | None:
    ""
    giorni = 0
    if "-" in testo:
        g, testo = testo.split("-", 1)
        giorni = int(g) if g.strip().isdigit() else 0
    try:
        parti = [float(x) for x in testo.strip().split(":")]
    except ValueError:
        return None
    s = 0.0
    for x in parti:
        s = s * 60 + x
    return s + giorni * 86400


def _cpu_dello_step(run_id: str) -> tuple[float, str] | None:
    ""




    marca = f"SBK_RUN_ID={run_id}".encode()
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,time=,command="], capture_output=True, text=True, timeout=15
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    io = os.getpid()
    totale, nome = 0.0, None
    for riga in out.splitlines():
        parti = riga.split(None, 2)
        if len(parti) < 3 or not parti[0].isdigit() or int(parti[0]) == io:
            continue
        script = _eseguito(parti[2].split())
        if not script or not script.endswith(".py"):
            continue
        if script.startswith(("sb-", "xs-pipeline-run", "xs-l0-refresh")):
            continue
        try:
            if not _custode().marcato(int(parti[0]), marca):
                continue
        except Exception:  # noqa: BLE001 -- the keeper is another file: an error of its own doesn't break the state
            return None
        s = _secondi_cpu(parti[1])
        if s is not None:
            totale += s
            nome = nome or script
    return (totale, nome) if nome else None


def _step_al_lavoro(run_id: str, adesso: float) -> str | None:
    ""




    ora = _cpu_dello_step(run_id)
    if ora is None:
        return None
    cpu, script = ora
    f = SYSTEM / "secondbrain-app-processore.json"
    try:
        prima = json.loads(f.read_text()).get(run_id) or {}
    except (OSError, ValueError, AttributeError):
        prima = {}
    passato = adesso - float(prima.get("t") or 0)
    if prima.get("script") != script or not 2 <= passato <= 15 * 60:

        time.sleep(1.0)
        dopo = _cpu_dello_step(run_id)
        if dopo is None or dopo[1] != script:
            return None
        prima, passato, adesso, cpu = {"cpu": cpu}, 1.0, adesso + 1.0, dopo[0]
    try:
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({run_id: {"t": adesso, "cpu": cpu, "script": script}}))
        os.replace(tmp, f)
    except OSError:
        pass
    lavora = (cpu - float(prima.get("cpu") or 0)) / passato >= _AL_LAVORO_MIN
    return _chi_dal_nome(script) if lavora else None


def _partito(dalle: str | None, adesso: float) -> float | None:
    ""

    if not dalle:
        return None
    try:
        h, m, s = (int(x) for x in dalle.strip().split(":"))
        t = datetime.fromtimestamp(adesso).replace(hour=h, minute=m, second=s, microsecond=0)
    except ValueError:
        return None
    if t.timestamp() > adesso + 60:
        t -= timedelta(days=1)
    return t.timestamp()


def _ts_utc(testo) -> float | None:
    try:
        t = datetime.fromisoformat(str(testo))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp()


def _avanzamento_indice(partito: float) -> dict | None:
    ""



    try:
        punto = json.loads(_PUNTO_INDICE.read_text())
        salvato = _PUNTO_INDICE.stat().st_mtime
    except (OSError, ValueError):
        return None
    if not isinstance(punto, dict):
        return None
    if salvato < partito:
        return {
            "frase": "Preparing the pieces to compute, it hasn't saved anything yet in this run."
        }
    pezzi, fonti = 0, 0
    for fonte, v in punto.items():
        if fonte.startswith("_") or not isinstance(v, dict):
            continue
        chiusa, parziale = _ts_utc(v.get("timestamp")), _ts_utc(v.get("partial_timestamp"))
        if chiusa and chiusa >= partito:
            fonti += 1
            pezzi += int(v.get("count") or 0)
        elif parziale and parziale >= partito:
            pezzi += int(v.get("partial_count") or 0)
    ora = datetime.fromtimestamp(salvato).strftime("%H:%M")
    quante = "one source" if fonti == 1 else f"{fonti} sources"
    numero = f"{pezzi:,}".replace(",", ".")
    return {
        "salvato": _iso(salvato),
        "salvato_ts": salvato,
        "pezzi": pezzi,
        "fonti": fonti,
        "frase": f"It has already computed {numero} pieces in {quante}, the last save at {ora}.",
    }



_SONDE = {"l3_index": _avanzamento_indice}


def _segni_dello_step(
    av: dict | None, run_id: str | None, registro: Path | None, adesso: float | None = None
) -> None:
    ""

    c = (av or {}).get("corrente")
    if not c or av.get("tipo") != "stadi":
        return
    adesso = time.time() if adesso is None else adesso
    partito = _partito(c.get("dalle"), adesso)
    if partito is None:
        return
    c["partito"] = _iso(partito)
    c["da_s"] = round(adesso - partito)
    sonda = _SONDE.get(c["id"])
    dove = sonda(partito) if sonda else None
    if dove:
        c["avanzamento"] = {k: v for k, v in dove.items() if k != "salvato_ts"}
    segni = [partito, dove.get("salvato_ts") if dove else None]
    try:
        segni.append(registro.stat().st_mtime if registro else None)
    except OSError:
        pass
    c["ultimo_segno_s"] = round(adesso - max(x for x in segni if x))
    c["al_lavoro"] = _step_al_lavoro(run_id, adesso) if run_id else None
    frase = (dove or {}).get("frase") or ""
    if c["al_lavoro"]:
        c["come_va"] = f"Working. {frase}".strip()
    elif c["ultimo_segno_s"] > 15 * 60:
        c["come_va"] = (
            f"No sign for {durata(c['ultimo_segno_s'])} and the processor is idle. {frase}".strip()
        )
    else:
        c["come_va"] = frase


def _nome_in_pausa(nome: str) -> str:
    ""

    if nome in P.STADI:
        return P.nome_stadio(nome, nome)
    return P.nome_fonte(nome)


def comandi_del_run(run: dict, av: dict | None) -> dict:
    ""
    full = "sb-full.py" in run.get("comando", "")
    fase, _stadio = _fase_del_run(av)
    in_pausa = fase == "in_pausa"
    richiesta = Path(run["log"]).with_suffix(".pausa").exists() or bool((av or {}).get("pausa"))
    if not full:
        pausa = {"possibile": False, "perche": RIPRESA.PAUSA["non_full"]}
    elif in_pausa or richiesta:
        pausa = {"possibile": False, "perche": "", "richiesta": richiesta, "in_pausa": in_pausa}
    elif fase in ("pagato_invio", "pagato_attesa"):
        pausa = {"possibile": False, "perche": RIPRESA.PAUSA["pagato"]}
    elif fase == "rilettura" and not RIPRESA.orchestratore_sa_la_pausa(
        TOOLS / "cross-source" / "xs-pipeline-run.py"
    ):
        pausa = {"possibile": False, "perche": RIPRESA.PAUSA["rilettura"]}
    elif fase == "rilettura":
        pausa = {"possibile": True, "frase": RIPRESA.PAUSA["rilettura_con_gancio"]}
    else:
        pausa = {
            "possibile": True,
            "frase": RIPRESA.PAUSA["copia" if fase == "copia" else "scarico"],
        }
    conseguenze = RIPRESA.FERMA.get(fase, "")
    if fase == "scarico" and any(c.get("id") == "gdrive" for c in (av or {}).get("correnti") or []):
        conseguenze += " " + RIPRESA.FERMA["drive"]
    out = {
        "fase": fase,
        "pausa": pausa,
        "continua": {"possibile": in_pausa or richiesta},
        "ferma": {"frase": conseguenze},
        "frase": "",
    }
    pausa_dentro = ((av or {}).get("dentro") or [None])[0] or {}
    if pausa_dentro.get("pausa"):
        out["frase"] = RIPRESA.frase_in_pausa(
            [_nome_in_pausa(pausa_dentro["pausa"]["prima_di"])],
            pausa_dentro["pausa"]["dal"],
        )
    elif av and av.get("pausa"):
        out["frase"] = RIPRESA.frase_in_pausa(
            [_fonte_del_passo(p) for p in av["pausa"]["prima_di"]],
            av["pausa"]["dal"],
            [_fonte_del_passo(p) for p in av["pausa"].get("attivi") or []],
        )
    elif richiesta:
        out["frase"] = "Pause requested, it arrives when the steps in progress finish."
    return out


def ripresa_possibile(runs: list[dict], giro: dict | None, occupato_da: str | None) -> dict | None:
    ""
    ultimo = runs[-1] if runs else None
    candidato = None
    if (
        ultimo
        and not ultimo.get("vivo")
        and "sb-full.py" in ultimo.get("comando", "")
        and ultimo.get("esito") in ("fermato", "interrotto", "incompleto", "fallito")
    ):
        candidato = (Path(ultimo.get("cartella") or Path(ultimo["log"]).parent), ultimo.get("fine"))
    elif (
        giro
        and not giro.get("vivo")
        and giro.get("poi_ingest")
        and (
            giro.get("fine") is None
            or giro.get("fermato")
            or giro.get("non_chiusi") not in _NESSUNO
        )
    ):
        candidato = (Path(giro["cartella"]), giro.get("fine") or giro.get("aggiornato"))
    if candidato is None:
        return None
    cartella, quando_fine = candidato
    vecchio = RIPRESA.leggi_giro(cartella, [p.nome for p in L0R.PIANO])
    if not vecchio.trovato or vecchio.modo is None:
        return None
    dove = RIPRESA.da_dove_si_riprende(vecchio, list(L0R.PIANO), vecchio.modo)
    if dove["niente_da_fare"]:
        return None
    giorni = _giorni_da(quando_fine)
    perche = occupato_da or (
        "The run seems still alive, it wrote recently and has no end line."
        if vecchio.forse_vivo()
        else ""
    )
    frase = RIPRESA.frase_ripresa(
        len(dove["salta"]),
        [_fonte_del_passo(n) for n in dove["rifa"]],
        dove["rilettura"],
        quando(quando_fine),
        giorni * 24 if giorni is not None else None,
    )
    if vecchio.modo == "tutto":
        frase += " It's a Full run complete, it restarts with the paid steps you had chosen."
    return {
        "cartella": str(cartella),
        "modo": vecchio.modo,
        "spende": vecchio.modo == "tutto",
        "spesa": vecchio.spesa,
        "salta": dove["salta"],
        "rifa": dove["rifa"],
        "possibile": not perche,
        "perche": perche,
        "frase": frase,
        "azione": {"tipo": "riprendi", "arg": str(cartella), "etichetta": "Resume where you left off"},
    }


def lotti_in_sospeso(eta: dict[str, float | None]) -> list[dict]:
    ""



    out = []
    dati = max((t for t in eta.values() if t), default=None)
    for pid, f in _STATO_LOTTI.items():
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            out.append({"id": pid, "nome": P.nome_stadio(pid, pid), "leggibile": False})
            continue
        inviati = d.get("submitted_at")
        out.append(
            {
                "id": pid,
                "nome": P.nome_stadio(pid, pid),
                "leggibile": True,
                "lotti": len(d.get("batch_ids") or []),
                "inviati": _iso(inviati),


                "dati_nuovi_dopo": bool(inviati and dati and dati > inviati),
            }
        )
    return out




_R_ORA = r"^(?P<ora>\d\d:\d\d:\d\d) \w+ +"
_RE_RUNNING = re.compile(
    _R_ORA + r"RUNNING: (?P<nome>.+?)(?: \((?P<script>[^ )]+\.py)[^)]*\))?\s*$"
)
_RE_OK = re.compile(_R_ORA + r"OK in (?P<s>[\d.]+)s")
_RE_FAILED = re.compile(_R_ORA + r"FAILED \(exit (?P<rc>-?\d+)\) in (?P<s>[\d.]+)s")
# Lines of xs-pipeline-run.py's log. It writes English; the Italian of older logs is still accepted.
_RE_TIMEOUT = re.compile(_R_ORA + r"TIMEOUT (?:after|dopo)")
_RE_LOCK = re.compile(_R_ORA + r"LOCK (?:HELD|TENUTO)")
_RE_GUARDIA = re.compile(
    _R_ORA
    + r"\[(?:resources|risorse)\] '(?P<nome>.+?)' (?P<cosa>over budget .*|stays over budget .*"
    r"|pressure .*|oltre il budget .*|resta oltre budget .*|pressione .*)"
)
_RE_RIPROVA = re.compile(
    _R_ORA
    + r"🔁 (?:retry|line stop|fermata di linea): '(?P<nome>.+?)' (?:died|morto) \((?P<classe>[^)]+)\) — "
    r"(?:attempt|tentativo) (?P<t>\d+)/(?P<n>\d+)"
)
_RE_MORTO = re.compile(_R_ORA + r"⛔ '(?P<nome>.+?)' (?:did not close after|non ha chiuso dopo)")
_RE_LINEA = re.compile(_R_ORA + r"⛔ (?P<nome>.+?) (?:does NOT start: line stopped|NON parte: linea ferma)")

_RE_PAUSA_ORCH = re.compile(_R_ORA + r"⏸ (?:PAUSE before|PAUSA prima di) (?P<nome>.+?): ")
_RE_RIPRESA_ORCH = re.compile(_R_ORA + r"▶ (?:RESUME|RIPRESA) (?:after|dopo)")
_RE_PIANO = re.compile(
    _R_ORA
    + r"(?P<segno>[✓–]) (?P<nome>.+?)(?: \[PAID\].*?)?"
    r"(?: — (?:SKIPPED|SALTATO) \((?P<motivo>[^)]+)\).*)?$"
)
_RE_FASE_L1 = re.compile(_R_ORA + r"L1 (?P<fase>Phase [^:]+): running (?P<n>\d+) scripts")
_RE_FASE_L1_FINE = re.compile(
    _R_ORA + r"(?P<fase>Phase .+?) completed: (?P<ok>\d+)/(?P<n>\d+) OK(?: in (?P<s>[\d.]+)s)?"
)
_RE_L1_NON_CHIUSA = re.compile(
    _R_ORA + r"\[(?P<nome>.+?)\] (?:NOT CLOSED after the attempts|NON CHIUSO dopo i tentativi)"
)
_FASI_L1 = {
    "Phase 1-pre (personio)": ("l1_personio", "l1_personio_assenze"),
    "Phase 1 (base)": ("l1_phase1",),
    "Phase 2-pre (speaker list)": ("l1_speaker_analysis",),
    "Phase 2 (dependent)": ("l1_phase2",),
    "Phase 3 (WA deep)": ("l1_phase3_wa_deep",),
}

_LETTURE_CON_STADIO = {"personio": "l1_personio", "personio_assenze": "l1_personio_assenze"}



_STATO_LOTTI = {
    "l3_extract": DATA_ROOT / "l3" / "nlp" / "batch-responses" / "batch-state-extract.json",
    "l3_extract_rel": DATA_ROOT
    / "l3"
    / "nlp"
    / "relationship-responses"
    / "batch-state-extract-rel.json",
    "l3_deep_extract": DATA_ROOT
    / "l3"
    / "nlp"
    / "deep-responses"
    / "batch-state-deep-extract.json",
}


def _leggi_orchestratore(
    righe: list[str], modo: str | None, solo: str | None, tipiche: dict[str, float] | None = None
) -> dict:
    ""

    if solo:
        catena = [XPR.CATENA_PER_ID[solo]]
    else:
        catena = list(XPR.perimetro(modo or "propaga"))
    per_nome = {p.nome: p.id for p in XPR.CATENA}

    passi = {
        p.id: {
            "id": p.id,
            "nome": p.nome,
            "stato": "da_fare",
            "pagato": p.tipo == "pagato",
            "fase": _fase_dello_stadio().get(p.id),
        }
        for p in catena
    }
    eventi, corrente, esito = [], None, None
    pausa = None


    fase_l1 = None
    for riga in righe:
        if m := _RE_PAUSA_ORCH.match(riga):
            pausa = {
                "dal": m["ora"],
                "prima_di": per_nome.get(m["nome"].strip(), m["nome"].strip()),
            }
            continue
        if _RE_RIPRESA_ORCH.match(riga):
            pausa = None
            continue
        if m := _RE_FASE_L1.match(riga):
            pids = [pid for pid in _FASI_L1.get(m["fase"].strip(), ()) if pid in passi]

            if len(pids) == 1:
                passi[pids[0]].update(stato="in_corso", inizio=m["ora"])
                corrente = pids[0]
            fase_l1 = None
            if len(pids) == 1 and int(m["n"]) > 1:
                fase_l1 = {"n": int(m["n"]), "chiuse": 0, "non_chiuse": []}
                passi[pids[0]]["nota"] = f"0 reads closed of {m['n']}"
        elif m := _RE_FASE_L1_FINE.match(riga):
            pids = [pid for pid in _FASI_L1.get(m["fase"].strip(), ()) if pid in passi]
            for pid in pids:
                ok = m["ok"] == m["n"]
                nota = f"{m['ok']}/{m['n']} sources"
                if fase_l1 and fase_l1["non_chiuse"]:
                    nota += ", not closed: " + ", ".join(fase_l1["non_chiuse"])
                passi[pid].update(stato="fatto" if ok else "fallito", nota=nota)
                if len(pids) == 1 and m["s"]:
                    passi[pid]["durata_s"] = float(m["s"])
            fase_l1 = None
        elif m := _RE_PIANO.match(riga):
            pid = per_nome.get(m["nome"].strip())
            if pid in passi and m["segno"] == "–":
                passi[pid].update(stato="saltato", nota=m["motivo"] or "")
        elif m := _RE_RUNNING.match(riga):
            nome = m["nome"].strip()
            pid = per_nome.get(nome) or _LETTURE_CON_STADIO.get(nome)
            if fase_l1 and pid is None and corrente in passi:
                passi[corrente]["nota"] = (
                    f"{fase_l1['chiuse']} reads closed of {fase_l1['n']}, now {nome}"
                )
                continue
            if corrente and corrente != pid and passi[corrente]["stato"] == "ritento":
                passi[corrente]["stato"] = (
                    "fallito"
                )
            if pid in passi:
                tentativo = passi[pid].get("tentativo", 0) + 1
                passi[pid].update(stato="in_corso", inizio=m["ora"], tentativo=tentativo)
                corrente = pid
        elif fase_l1 and corrente in passi and (m := _RE_OK.match(riga)):
            fase_l1["chiuse"] += 1
            passi[corrente]["nota"] = f"{fase_l1['chiuse']} reads closed of {fase_l1['n']}"
        elif fase_l1 and (m := _RE_L1_NON_CHIUSA.match(riga)):
            fase_l1["non_chiuse"].append(m["nome"])
        elif fase_l1 and (
            _RE_FAILED.match(riga) or _RE_TIMEOUT.match(riga) or _RE_LOCK.match(riga)
        ):

            pass
        elif corrente and (m := _RE_OK.match(riga)):
            passi[corrente].update(stato="fatto", durata_s=float(m["s"]))
        elif corrente and (m := _RE_FAILED.match(riga)):
            passi[corrente].update(stato="ritento", nota=f"exit {m['rc']}", durata_s=float(m["s"]))
        elif corrente and _RE_TIMEOUT.match(riga):
            passi[corrente].update(stato="ritento", nota="over the time cap")
        elif corrente and _RE_LOCK.match(riga):
            passi[corrente].update(stato="ritento", nota="lock held by another instance")
        elif m := _RE_GUARDIA.match(riga):
            eventi.append(f"{m['ora']} memory guard on {m['nome']}: {m['cosa']}")
        elif m := _RE_RIPROVA.match(riga):
            eventi.append(f"{m['ora']} {m['nome']}: retry {m['t']} of {m['n']} ({m['classe']})")
        elif m := _RE_MORTO.match(riga):
            pid = per_nome.get(m["nome"])
            if pid in passi:
                passi[pid]["stato"] = "fallito"
        elif m := _RE_LINEA.match(riga):
            pid = per_nome.get(m["nome"])
            if pid in passi:
                passi[pid].update(stato="saltato", nota="line stopped upstream")
        elif m := (_RE_ESITO_MODO.search(riga) or _RE_ESITO_SOLO.search(riga)):
            esito = m.group(1)
    if esito:

        for p in passi.values():
            if p["stato"] in ("in_corso", "ritento"):
                p["stato"] = "fallito"
            elif p["stato"] == "da_fare":
                p.update(stato="saltato", nota=p.get("nota") or "not started in this run")
        corrente = None
    lista = list(passi.values())
    fatti = sum(1 for p in lista if p["stato"] in ("fatto", "saltato", "fallito"))
    out = {
        "tipo": "stadi",
        "passi": lista,
        "eventi": eventi[-20:],
        "denominatore": f"{fatti} of {len(lista)}",
        "esito": esito,
    }


    if esito or any(p["stato"] in ("fallito", "ritento") for p in lista):
        del_run = []
        for s in ERR.diagnosi_della_rilettura(righe):
            pid = per_nome.get(s["stadio"])
            if pid in passi and passi[pid]["stato"] in ("fallito", "ritento"):
                passi[pid]["diagnosi"] = s["diagnosi"]
            elif pid not in passi:
                del_run.append(s)
        if del_run:
            out["diagnosi_run"] = del_run
    if pausa and not esito:
        out["pausa"] = pausa
    if corrente and passi[corrente]["stato"] in ("in_corso", "ritento"):
        p = passi[corrente]
        tipiche = tipiche or {}
        out["corrente"] = {
            "id": corrente,
            "nome": p["nome"],
            "dalle": p.get("inizio"),
            "di_solito_s": tipiche.get(p["nome"]),

            "tetto_s": None if corrente.startswith("l1_") else XPR._timeout_step(p["nome"]),
            "tentativo": p.get("tentativo", 1),
        }
        if corrente in _STATO_LOTTI:
            out["corrente"]["pagato"] = True
            out["corrente"]["lotti_salvati"] = _STATO_LOTTI[corrente].exists()
    return out


def _leggi_giro(cartella: Path, solo: str | None, poi_ingest: bool, finale: str = "ingest") -> dict:
    ""



    piano = [p for p in L0R.PIANO if not solo or p.sorgente in solo.split(",")]
    passi = {
        p.nome: {
            "id": p.nome,

            "nome": P.PASSI_GIRO.get(p.nome) or P.nome_fonte(p.sorgente),
            "sorgente": p.sorgente,
            "stato": "da_fare",
            "tentativi": 0,

            "fase": "scarico",
        }
        for p in piano
    }
    if poi_ingest:
        passi["backup-kb"] = {
            "id": "backup-kb",
            "nome": P.PASSI_GIRO["backup-kb"],
            "stato": "da_fare",
            "tentativi": 0,
        }
        passi[finale] = {
            "id": finale,
            "nome": P.PASSI_GIRO[finale],
            "stato": "da_fare",
            "tentativi": 0,
        }
    fine = None

    pause: dict[str, str] = {}

    corsie: dict[str, list[str]] = {}
    non_partite: list[str] = []
    for riga in _coda(cartella / "esiti.tsv", 1 << 20):
        campi = riga.split("\t")
        if len(campi) < 3:
            continue
        nome = campi[1]
        if nome.startswith("corsia:"):
            corsia = nome.split(":", 1)[1]
            if campi[2] in _NON_PARTITA:
                non_partite.append(corsia)
            else:
                corsie[corsia] = [s.strip() for s in campi[2].split(",") if s.strip()]
            continue
        if nome in _FINE:
            fine = campi[2]
        elif nome == "PAUSA":
            prima = (
                campi[3].removeprefix("before ").removeprefix("prima di ") if len(campi) > 3 else ""
            )
            if campi[2] in ("paused", "in pausa"):
                pause[prima] = campi[0]
            else:
                pause.pop(prima, None)
        elif nome in passi and campi[2] in _RIPRESO:

            passi[nome].update(stato="fatto", ripreso=True, nota=campi[3] if len(campi) > 3 else "")
        elif nome in passi and campi[2].startswith(_TENTATIVO):
            rc = campi[3].removeprefix("rc=") if len(campi) > 3 else ""
            p = passi[nome]
            p["tentativi"] = int(campi[2].split(".", 1)[1])
            durata = campi[4].rstrip("s") if len(campi) > 4 else ""
            if rc in _INTERROTTO:
                p.update(stato="interrotto", durata_s=float(durata or 0))
                continue
            ok = rc == "0" or (nome == finale and rc == "2" and not (len(campi) > 5 and campi[5]))
            p.update(stato="fatto" if ok else "ritento", rc=rc, durata_s=float(durata or 0))
        elif nome in passi and campi[2].startswith(("NOT CLOSED AFTER", "NON CHIUSO DOPO")):
            passi[nome]["stato"] = "fallito"
        elif nome == "backup-kb" and "backup-kb" in passi:

            passi[nome]["stato"] = {
                "rc=0": "fatto",
                "INTERRUPTED": "interrotto",
                "INTERROTTO": "interrotto",
            }.get(campi[2], "fallito")
        elif nome == finale and finale in passi and campi[2].startswith(("NOT LAUNCHED", "NON LANCIATO")):
            passi[nome].update(stato="saltato", nota=campi[2])
    lista = list(passi.values())
    aperti = ("da_fare", "ritento")


    correnti: list[tuple[str | None, dict]] = []
    if fine is None:
        for corsia, ids in corsie.items():
            cur = next((passi[i] for i in ids if i in passi and passi[i]["stato"] in aperti), None)
            if cur:
                correnti.append((corsia, cur))
        if not correnti:
            cur = next((p for p in lista if p["stato"] in aperti), None)
            if cur:
                correnti.append((None, cur))
    out = {"tipo": "giro", "passi": lista, "fine": fine}
    fatti = sum(1 for p in lista if p["stato"] in ("fatto", "fallito", "saltato"))
    out["denominatore"] = f"{fatti} of {len(lista)} steps"
    descritti = []
    for corsia, cur in correnti:
        log = cartella / "log" / f"{cur['id']}.log"

        if not log.exists() or cur["id"] in pause:
            continue
        cur["stato"] = "in_corso"
        testa = [x for x in _coda(log, 1 << 16) if x.startswith(("── attempt ", "── tentativo "))]
        dalle = testa[-1].split(" · ")[1] if testa else None
        descritti.append(
            {
                "id": cur["id"],
                "nome": cur["nome"],
                "corsia": corsia,
                "dalle": dalle,

                "da_s": round(_trascorso(dalle, time.time())) if dalle else None,
                "tentativo": cur["tentativi"] + 1,

                "ultimo_segno_s": round(time.time() - log.stat().st_mtime),
            }
        )


    if any(d["ultimo_segno_s"] > 15 * 60 for d in descritti):
        chi = _pipeline_al_lavoro()
        for d in descritti:
            if d["ultimo_segno_s"] > 15 * 60:
                d["al_lavoro"] = chi
    if descritti:

        out["corrente"] = min(descritti, key=lambda d: d.get("dalle") or "99")
        out["correnti"] = descritti
        if out["corrente"]["id"] == finale:
            righe = _coda(cartella / "log" / f"{finale}.log", 1 << 21)

            out["dentro"] = [_leggi_orchestratore(righe, finale, None)]


    in_corso = {d["id"] for d in descritti}
    for p in lista:
        if p["id"] in in_corso or p["stato"] in ("da_fare", "interrotto", "saltato"):
            continue
        esame = ERR.esame_del_passo(cartella, p["id"])
        if esame["diagnosi"]:
            p["diagnosi"] = esame["diagnosi"]
        if esame["avvisi"]:
            p["avvisi"] = esame["avvisi"]
    if corsie:
        out["corsie"] = [
            {
                "nome": corsia,
                "passi": ids,
                "fatti": sum(
                    1
                    for i in ids
                    if i in passi and passi[i]["stato"] in ("fatto", "fallito", "saltato")
                ),
                "totale": len(ids),
                "corrente": next((d["id"] for d in descritti if d["corsia"] == corsia), None),
            }
            for corsia, ids in corsie.items()
        ]
        out["corsie_non_partite"] = non_partite
    if pause and fine is None:

        out["pausa"] = {
            "dal": min(pause.values()),
            "prima_di": sorted(pause),
            "attivi": [d["id"] for d in descritti],
        }
    return out


_CHIUSI = ("fatto", "fallito", "saltato", "interrotto")


def _secondi_dall_iso(iso: str | None, adesso: float) -> float | None:
    ""
    try:
        return max(0.0, adesso - datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S").timestamp())
    except (TypeError, ValueError):
        return None


def _trascorso(dalle: str | None, adesso: float) -> float:
    ""
    if not dalle:
        return 0.0
    anno = datetime.fromtimestamp(adesso).year
    try:
        t = datetime.strptime(f"{anno}/{dalle}", "%Y/%d/%m %H:%M:%S").timestamp()
    except ValueError:
        return 0.0
    if t > adesso + 86400:

        t = datetime.strptime(f"{anno - 1}/{dalle}", "%Y/%d/%m %H:%M:%S").timestamp()
    return max(0.0, adesso - t)


def previsione(
    av: dict | None,
    durate: dict[str, float],
    adesso: float | None = None,
    inizio: str | None = None,
) -> dict | None:
    ""






    if not av:
        return None
    adesso = time.time() if adesso is None else adesso
    senza: list[str] = []



    oltre: list[dict] = []
    dopo: float | None = None
    scarico = None
    passi = {p["id"]: p for p in av.get("passi", [])}
    finale = None
    if av.get("tipo") == "giro":
        correnti = {c["id"]: c for c in av.get("correnti") or []}
        if not correnti and av.get("corrente"):
            correnti = {av["corrente"]["id"]: av["corrente"]}
        ids_l0 = [p["id"] for p in av.get("passi", []) if p.get("sorgente")]
        corsie = [c["passi"] for c in av.get("corsie") or []] or [ids_l0]
        resti: list[float | None] = []
        for ids in corsie:
            resto: float | None = 0.0
            for i in ids:
                p = passi.get(i)
                if not p or p["stato"] in _CHIUSI:
                    continue
                tipica = durate.get(f"l0:{i}")
                if tipica is None:
                    senza.append(p["nome"])
                    resto = None
                    continue
                gia = _trascorso((correnti.get(i) or {}).get("dalle"), adesso)
                if gia > _oltre_il_solito(tipica):
                    oltre.append(
                        {"nome": p["nome"], "da_s": round(gia), "di_solito_s": round(tipica)}
                    )
                    resto = None
                    continue
                if resto is not None:
                    resto += max(0.0, tipica - gia)
            resti.append(resto)
        scarico = (
            None
            if any(r is None for r in resti)
            else max((r for r in resti if r is not None), default=0.0)
        )
        finale = next((passi[i] for i in ("tutto", "ingest") if i in passi), None)
        dentro = (av.get("dentro") or [None])[0]
    else:
        dentro = av
    rilettura = None


    per_fase: dict[str, float | None] = {}
    fase_di = _fase_dello_stadio()
    modo = (finale or {}).get("id")
    if (finale is None and av.get("tipo") != "giro") or (finale and finale["stato"] not in _CHIUSI):
        fatti = {p["id"] for p in (dentro or {}).get("passi", []) if p.get("stato") in _CHIUSI}
        perimetro = (
            XPR.perimetro(modo)
            if modo in MODI
            else [
                XPR.CATENA_PER_ID[p["id"]]
                for p in (dentro or {}).get("passi", [])
                if p["id"] in XPR.CATENA_PER_ID
            ]
        )
        corrente = (dentro or {}).get("corrente") or {}
        rilettura, dopo = 0.0, 0.0
        for s in perimetro:
            if s.id in fatti:
                continue
            fase = fase_di.get(s.id, "")
            per_fase.setdefault(fase, 0.0)
            tipica = durate.get(s.nome)
            if s.id == corrente.get("id") and corrente.get("da_s") is not None and tipica:

                gia = float(corrente["da_s"])
                if gia > _oltre_il_solito(tipica):
                    oltre.append(
                        {
                            "nome": P.nome_stadio(s.id, s.nome),
                            "da_s": round(gia),
                            "di_solito_s": round(tipica),
                        }
                    )
                    rilettura = None
                    per_fase[fase] = None
                    continue
                tipica = max(0.0, tipica - gia)
            elif tipica is not None:
                dopo += tipica
            if tipica is None:
                if s.tipo == "pagato":
                    senza.append(P.nome_stadio(s.id, s.nome))
                    rilettura = None
                    per_fase[fase] = None
                continue
            if rilettura is not None:
                rilettura += tipica
            if per_fase[fase] is not None:
                per_fase[fase] += tipica
    noti = [x for x in (scarico, rilettura) if x is not None]
    completa = not senza and not oltre
    restano = sum(noti) if noti and completa else None


    passato = _secondi_dall_iso(inizio, adesso)
    frazione = (
        round(passato / (passato + restano), 3)
        if restano is not None and passato is not None and passato + restano > 0
        else None
    )
    nomi_fase = {f["id"]: f["nome"] for f in P.FASI}
    out = {
        "scarico_s": round(scarico) if scarico is not None else None,
        "rilettura_s": round(rilettura) if rilettura is not None else None,
        "restano_s": round(restano) if restano is not None else None,
        "fine_prevista": _iso(adesso + restano) if restano is not None else None,
        "senza_stima": sorted(set(senza)),
        "come": "from the typical durations of past runs",
        "frazione_tempo": frazione,
        "fasi": [
            {"fase": nomi_fase.get(f, f), "restano_s": round(r) if r is not None else None}
            for f, r in per_fase.items()
        ],
    }
    if oltre:
        o = oltre[0]
        frase = (
            f"End not predictable. {o['nome']} has been running for {durata(o['da_s'])}, usually takes "
            f"{durata(o['di_solito_s'])}."
        )
        if dopo and not senza:
            frase += f" The steps after usually take {durata(dopo)}."
        if senza:
            frase += f" Also {' and '.join(sorted(set(senza)))} doesn't have a measured duration yet."
        out["oltre_il_solito"] = oltre
        out["frase"] = frase
    return out


def _oltre_il_solito(tipica: float) -> float:
    ""
    return tipica * 1.5 + 60


def _durate_per_previsione() -> dict[str, float]:
    ""
    cache, _testo = _carica_cache()

    durate: dict[str, list[float]] = {
        k: list(v)
        for k, v in ((cache.get("vivo") or {}).get("durate") or cache.get("durate") or {}).items()
    }
    for d in _diari_l0():
        if d["status"] == "success" and isinstance(d.get("duration_s"), int | float):
            durate.setdefault(f"l0:{d['passo']}", []).append(float(d["duration_s"]))
    return {k: statistics.median(v[-Indice.DURATE_TENUTE :]) for k, v in durate.items() if v}


def avanzamento(run: dict) -> dict:
    ""

    comando = _comando_interno(run.get("comando", ""))
    argv = comando.split()
    solo = (
        argv[argv.index("--solo") + 1]
        if "--solo" in argv and argv.index("--solo") + 1 < len(argv)
        else None
    )
    if "sb-full.py" in comando and "--solo-scarico" in comando:
        out = _leggi_giro(Path(run.get("cartella") or Path(run["log"]).parent), solo, False)
    elif "sb-full.py" in comando:
        finale = "tutto" if "--modo tutto" in comando else "ingest"
        out = _leggi_giro(Path(run.get("cartella") or Path(run["log"]).parent), None, True, finale)
    elif "xs-l0-refresh.py" in comando:
        out = _leggi_giro(
            Path(run.get("cartella") or Path(run["log"]).parent), solo, "--poi-ingest" in argv
        )
    else:
        modo = next((m for m in MODI if f"--{m}" in argv), None)


        i = argv.index("--solo-stadio") if "--solo-stadio" in argv else -1
        stadio = argv[i + 1] if 0 <= i < len(argv) - 1 else None
        if stadio not in XPR.CATENA_PER_ID:
            stadio = None
        out = _leggi_orchestratore(_coda(Path(run["log"]), 1 << 21), modo, stadio or solo)
    if run.get("vivo"):

        if out.get("tipo") == "stadi":
            _segni_dello_step(out, run.get("run_id"), Path(run["log"]))
        elif out.get("dentro"):
            finale = (out.get("corrente") or {}).get("id")
            cartella = Path(run.get("cartella") or Path(run["log"]).parent)
            _segni_dello_step(
                out["dentro"][0], run.get("run_id"), cartella / "log" / f"{finale}.log"
            )
    battito = Path(run["log"]).with_suffix(".battito")
    if battito.exists():
        try:
            b = json.loads(battito.read_text())
            out["custode"] = {
                "battito_s": round(time.time() - battito.stat().st_mtime),
                "dormito_s": b.get("dormito_s"),
            }
        except (OSError, ValueError):
            pass
    return out





def sonno_e_corrente() -> dict:
    ""

    out = {"coperchio": "not measured", "alimentazione": "not measured", "carica": None}
    try:
        g = subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"SleepDisabled\s+(\d)", g)
        out["coperchio"] = "awake" if m and m.group(1) == "1" else "asleep"
        b = subprocess.run(
            ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5
        ).stdout
        out["alimentazione"] = "mains" if "AC Power" in b else "battery"
        if m := re.search(r"(\d+)%", b):
            out["carica"] = int(m.group(1))
    except (subprocess.SubprocessError, OSError):
        pass
    return out





def _custode():
    ""
    return sys.modules.get("sb_run") or _carica("sb_run", SB_RUN)


def rimasti_del_run(run_id: str) -> list[int]:
    ""
    return sorted(_custode().albero(None, f"SBK_RUN_ID={run_id}".encode()))


def cmd_pulisci(run_id: str) -> dict:
    ""

    run = next((r for r in _runs() if r["run_id"] == run_id), None)
    if run is None or run["vivo"]:
        return {"ok": False, "errore": "only finished runs can be cleaned"}
    vivi = _custode().ferma_albero(f"SBK_RUN_ID={run_id}".encode())
    return {"ok": not vivi, "rimasti": vivi}


def cmd_run(run_id: str) -> dict:
    ""

    run = next((r for r in [*_runs(), *_runs_da_terminale()] if r["run_id"] == run_id), None)
    if run is None:
        return {"ok": False, "errore": f"unknown run: {run_id}"}
    av = avanzamento(run)
    if run.get("vivo"):
        av["previsione"] = previsione(av, _durate_per_previsione(), inizio=run.get("inizio"))
    return {
        "ok": True,
        "run": {**run, "nome": _nome_run(run)},
        "avanzamento": av,
        "riga": _riga_avanzamento(av),
        "comandi": comandi_del_run(run, av) if run.get("vivo") else None,
    }


def cmd_log(run_id: str, n: int) -> dict:
    run = next(
        (r for r in [*_runs(), *_scarichi_soli(), *_runs_da_terminale()] if r["run_id"] == run_id),
        None,
    )
    if run is None:
        return {"ok": False, "errore": f"unknown run: {run_id}"}
    try:
        testo = Path(run["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        if run.get("da_terminale"):
            return {
                "ok": True,
                "vivo": False,
                "righe": [
                    "Launched from a terminal. The log is where whoever launched it wrote it."
                ],
            }
        return {"ok": False, "errore": str(e)}
    return {"ok": True, "vivo": run["vivo"], "righe": [ERR.pulisci_registro(r) for r in testo[-n:]]}





STIMA_ARGOMENTI = {
    "l3_extract": ["--dry-run", "--all-sources", "--incremental", "--batch-api"],
    "l3_extract_rel": ["--dry-run", "--incremental", "--batch-api"],
    "l3_deep_extract": ["--dry-run", "--incremental", "--batch-api"],
}



_RE_DOLLARI = {
    "l3_extract": (re.compile(r"Est\. batch cost: \$([\d.]+)"),),
    "l3_extract_rel": (re.compile(r"Est\. batch cost: \$([\d.]+)"),),
    "l3_deep_extract": (re.compile(r"Est\. total cost:\s+\$([\d.]+)"),),
}
_RE_DOCUMENTI = {
    "l3_extract": (
        re.compile(r"Batch progress: \d+/\d+ processed, (\d+) remaining"),
        re.compile(r"^Documents: (\d+)"),
    ),
    "l3_extract_rel": (re.compile(r"New to process:\s+(\d+)"),),
    "l3_deep_extract": (re.compile(r"New to process:\s+(\d+)"),),
}


def _file_stima() -> Path:
    return SYSTEM / "secondbrain-app-stima.json"


def _primo(regole: tuple[re.Pattern, ...], righe: list[str]) -> str | None:
    for rx in regole:
        for r in righe:
            if m := rx.search(r.strip()):
                return m.group(1)
    return None


def _costante(file: Path, nome: str):
    ""
    import ast

    try:
        for nodo in ast.parse(file.read_text(encoding="utf-8")).body:
            if isinstance(nodo, ast.Assign) and any(
                getattr(x, "id", None) == nome for x in nodo.targets
            ):
                return ast.literal_eval(nodo.value)
    except (OSError, ValueError, SyntaxError):
        return None
    return None


_RE_RESTANTI_EXTRACT = re.compile(r"Batch progress: \d+/\d+ processed, (\d+) remaining")

_RE_INGRESSI_UGUALI = re.compile(r"Inputs unchanged since the last real run")
NOTE_STIMA = {
    "l3_extract": "Counted the requests the run would send, including the pieces of long transcripts, at the batch "
    "Sonnet price.",
    "l3_extract_rel": "Counted the requests the run would send, all the pieces of the long transcripts, at the batch "
    "Sonnet price.",
    "l3_deep_extract": "Counted the pieces still without a response at the batch Sonnet price, plus the merge of the "
    "long-transcript pieces at full price.",
}
NOTA_INGRESSI_UGUALI = (
    "The inputs are those of the last real run, the step would be skipped and spends nothing."
)


def _dollari_veri(pid: str, righe: list[str]) -> float | None:
    ""



    if pid == "l3_extract":
        restanti = _primo((_RE_RESTANTI_EXTRACT,), righe)
        if restanti is not None and int(restanti) == 0:
            return 0.0
    dollari = _primo(_RE_DOLLARI[pid], righe)
    return float(dollari) if dollari is not None else None


def _stima_di(pid: str, timeout_s: int = 600) -> dict:
    ""

    script = XPR.SCRIPTS.get(pid)
    nome = P.nome_stadio(pid, pid)
    if script is None or not Path(script).exists():
        return {"id": pid, "nome": nome, "errore": "the script is missing"}
    try:
        r = subprocess.run(
            [sys.executable, str(script), *STIMA_ARGOMENTI[pid]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=dict(os.environ, **AMBIENTE_RUN),
        )
    except subprocess.TimeoutExpired:
        return {
            "id": pid,
            "nome": nome,
            "errore": f"the count exceeded {timeout_s // 60} minutes",
        }
    righe = (r.stdout or "").splitlines()
    dollari, documenti = _dollari_veri(pid, righe), _primo(_RE_DOCUMENTI[pid], righe)
    if dollari is None:
        return {
            "id": pid,
            "nome": nome,
            "errore": f"the count did not give a figure (exit {r.returncode})",
        }
    uguali = any(_RE_INGRESSI_UGUALI.search(r) for r in righe)
    return {
        "id": pid,
        "nome": nome,
        "dollari": dollari,
        "documenti": int(documenti) if documenti else None,
        "nota": NOTA_INGRESSI_UGUALI if uguali else NOTE_STIMA.get(pid, ""),
    }


def fuori_dalla_stima() -> list[str]:
    ""


    return []


def margine_tetto() -> int:
    ""
    return int(IMP.leggi()["spesa"]["margine_tetto"])


def tetto_spesa(scelti: list[str]) -> float | None:
    ""


    try:
        stima = json.loads(_file_stima().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cifre = {s.get("id"): s.get("dollari") for s in stima.get("stadi") or [] if isinstance(s, dict)}
    if not scelti or any(not isinstance(cifre.get(pid), int | float) for pid in scelti):
        return None
    totale = sum(float(cifre[pid]) for pid in scelti)
    return round(max(1.0, totale * (1 + margine_tetto() / 100)), 2)


def cmd_stima(solo_ultima: bool = False) -> dict:
    ""





    try:
        ultima = json.loads(_file_stima().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ultima = None
    if isinstance(ultima, dict):


        ultima["fuori"] = fuori_dalla_stima()
        ultima["margine_tetto_pct"] = margine_tetto()
    if solo_ultima:
        return {"ok": ultima is not None, "stima": ultima}
    if _gira_dall_app() or _occupato_da_fuori():
        return {
            "ok": False,
            "errore": "The pipeline is already running: the estimate waits for it to finish.",
            "stima": ultima,
        }



    import fcntl

    SYSTEM.mkdir(parents=True, exist_ok=True)
    with open(SYSTEM / "secondbrain-app-stima.lock", "a") as lucchetto:
        try:
            fcntl.flock(lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            da = _adesso()
            fcntl.flock(lucchetto, fcntl.LOCK_EX)
            try:
                appena = json.loads(_file_stima().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                appena = None
            if isinstance(appena, dict) and str(appena.get("quando") or "") >= da:
                appena["fuori"] = fuori_dalla_stima()
                appena["margine_tetto_pct"] = margine_tetto()
                return {"ok": True, "stima": appena, "errore": ""}
        return _stima_adesso()


def _stima_adesso() -> dict:
    ""
    pagati = [p.id for p in XPR.CATENA if p.tipo == "pagato" and p.id in STIMA_ARGOMENTI]
    stadi_stima = [_stima_di(pid) for pid in pagati]
    completa = all("dollari" in s for s in stadi_stima)
    stima = {
        "quando": _adesso(),
        "stadi": stadi_stima,
        "totale": round(sum(s.get("dollari", 0) for s in stadi_stima), 2) if completa else None,
        "come": "Sonnet with the Batch API, at half price, with Anthropic's metered API key",
        "fuori": fuori_dalla_stima(),
        "margine_tetto_pct": margine_tetto(),
    }
    if completa:
        SYSTEM.mkdir(parents=True, exist_ok=True)
        tmp = _file_stima().with_name(f"{_file_stima().name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(stima, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _file_stima())
    return {
        "ok": completa,
        "stima": stima,
        "errore": "" if completa else "The estimate is not complete.",
    }






_LASCIANO_IL_POSTO = re.compile(r"sb-full\.py(?!.*--in-fila)")
_RE_NO = re.compile(r"⛔ (.+)")

_PERCHE_75 = (
    ("memoria", "There was no free memory for another job. Try again later."),
    ("rileggendo", "The full run was re-reading the data. Try again when it's done."),
    ("scaricando", "The full run or another process was already downloading it."),
)





TRASCRIVI_MEMO = ("tools/voice-memos/vm-l0-transcribe.py",)
ETICHETTA_TRASCRIZIONE = "trascrizione-memo"


def _memo_da_trascrivere() -> int:
    ""
    try:
        sys.path.insert(0, str(TOOLS / "voice-memos"))
        import vm_nomi

        return len(
            vm_nomi.da_trascrivere(
                sbk_config.VOICE_MEMOS_DIR, sbk_config.VOICE_MEMOS_TRANSCRIPTS_DIR
            )
        )
    except Exception:  # noqa: BLE001
        return 0


def _memo_n(n: int) -> str:
    return "one memo" if n == 1 else f"{n} memos"


def _trascrizione_viva() -> bool:
    return any(d["vivo"] and d.get("etichetta") == ETICHETTA_TRASCRIZIONE for d in _scarichi_soli())


def cmd_trascrivi_memo() -> dict:
    ""





    from sbk_resources import SEG_ADMIT_MAX, pressure

    if not _memo_da_trascrivere():
        return {"ok": False, "errore": "There are no memos to transcribe."}
    try:
        if pressure().seg_ratio >= SEG_ADMIT_MAX:
            return {
                "ok": False,
                "errore": "The Mac has no free memory for Whisper right now. Try again shortly.",
            }
    except Exception:  # noqa: BLE001
        pass
    SYSTEM.mkdir(parents=True, exist_ok=True)
    percorso_lock = _lock_fonte_app(ETICHETTA_TRASCRIZIONE)
    lock = percorso_lock.open("a+")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "errore": "The transcription is already running."}
        adesso = datetime.now()
        run_id = f"{adesso:%Y%m%d-%H%M%S}-{ETICHETTA_TRASCRIZIONE}"
        cartella = _cartella_scarico("voicememos", adesso)
        cartella.mkdir(parents=True, exist_ok=True)
        cmd = [*PY, *TRASCRIVI_MEMO]
        voce = {
            "run_id": run_id,
            "sorgente": "voicememos",
            "etichetta": ETICHETTA_TRASCRIZIONE,
            "comando": " ".join(cmd),
            "log": str(cartella / f"{run_id}.log"),
            "cartella": str(cartella),
            "inizio": adesso.strftime("%Y-%m-%dT%H:%M:%S"),
            "fine": None,
        }
        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps({"run_id": run_id}))
        lock.flush()
        with FONTI_RUNS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(voce, ensure_ascii=False) + "\n")
        proc = subprocess.Popen(
            [sys.executable, str(SB_RUN), run_id, str(cartella), "--", *cmd],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(lock.fileno(),),
            env=dict(
                os.environ,
                **AMBIENTE_RUN,
                SBK_RUN_LOCK_FD=str(lock.fileno()),
                SBK_RUN_REGISTRO=str(FONTI_RUNS),
                SBK_RUN_LOCK=str(percorso_lock),
            ),
        )
        return {
            "ok": True,
            **voce,
            "nome": "Voice memos, the transcription",
            "pid": proc.pid,
            "vivo": True,
        }
    finally:
        lock.close()


def _lock_fonte_app(sid: str) -> Path:
    return SYSTEM / f"secondbrain-fonte-{sid}.lock"


def _comando_fonte(sid: str, cartella: Path) -> list[str]:
    return [*PY, "tools/secondbrain/sb_corsie.py", "--fonte", sid, "--dir", str(cartella)]


def _cartella_scarico(sid: str, adesso: datetime) -> Path:
    ""
    # The callers create it (mkdir parents=True).
    return SCARICHI / f"{adesso:%Y-%m-%d}-{sid}-{adesso:%H%M%S}"


def _vivo_scarico(d: dict) -> bool:
    ""
    percorso = _lock_fonte_app(d.get("sorgente", ""))
    if not _lock_tenuto(percorso):
        return False
    try:
        return json.loads(percorso.read_text(encoding="utf-8") or "{}").get("run_id") == d["run_id"]
    except (OSError, ValueError):
        return False


def _esito_scarico(d: dict) -> dict:
    ""
    trascrizione = d.get("etichetta") == ETICHETTA_TRASCRIZIONE
    if d["vivo"]:
        return {
            "esito": "in_corso",
            "frase": "being transcribed" if trascrizione else "downloading",
        }
    if d.get("fermato"):
        dall_app = "dall'app" in d["fermato"]
        return {
            "esito": "fermato",
            "frase": "stopped by you" if dall_app else f"stopped ({d['fermato']})",
        }
    rc = d.get("rc")
    if d.get("fine") is None or rc is None:
        return {"esito": "interrotto", "frase": "it closed without writing the end"}
    no = next(
        (m.group(1) for r in reversed(_coda(Path(d["log"]), 4096)) if (m := _RE_NO.search(r))), ""
    )
    if rc == 0:
        return {"esito": "ok", "frase": "transcribed" if trascrizione else "downloaded"}
    if rc == 75:
        frase = next((f for chiave, f in _PERCHE_75 if chiave in no), "It wasn't possible right now.")
        return {"esito": "non_partito", "frase": frase}
    if rc in (130, 143) or rc < 0:
        return {"esito": "fermato", "frase": "stopped"}
    if rc == 1 and _fine_giro(Path(d.get("cartella", ""))):
        return {"esito": "incompleto", "frase": "not closed after three attempts"}
    if rc == 2:
        return {"esito": "non_partito", "frase": no or "not a source that downloads on its own"}
    return {
        "esito": "fallito",
        "frase": f"it stopped with an error (exit {rc}), the log says where",
    }


def _scarichi_soli() -> list[dict]:
    ""
    if not FONTI_RUNS.exists():
        return []
    per_id: dict[str, dict] = {}
    for riga in FONTI_RUNS.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        if d.get("run_id"):
            per_id.setdefault(d["run_id"], {}).update(d)
    out = []
    for d in sorted(
        (d for d in per_id.values() if "inizio" in d and "log" in d), key=lambda d: d["inizio"]
    ):
        d["vivo"] = d.get("fine") is None and _vivo_scarico(d)
        d["nome"] = (
            "Voice memos, the transcription"
            if d.get("etichetta") == ETICHETTA_TRASCRIZIONE
            else f"{P.nome_fonte(d.get('sorgente', ''))} on its own"
        )
        d.update(_esito_scarico(d))
        out.append(d)
    return out[-20:]


def _sole_in_mezzo(cmd: list[str]) -> str:
    ""

    comando = " ".join(cmd)
    if _LASCIANO_IL_POSTO.search(comando):
        return ""
    sole = [d["sorgente"] for d in _scarichi_soli() if d["vivo"]]
    if "--solo" in cmd and "xs-l0-refresh.py" in comando:
        sole = [s for s in sole if s == cmd[cmd.index("--solo") + 1]]
    return ", ".join(P.nome_fonte(s) for s in sole)


def _posto_per_le_fonti(in_corso: list[dict], run_app: dict | None) -> str:
    ""
    if _lock_tenuto(CORSIE.LOCK_RILETTURA):
        return "The full run is copying and re-reading the brain. The source downloads when it's done."
    if run_app and not _LASCIANO_IL_POSTO.search(run_app.get("comando", "")):
        return f"«{_nome_run(run_app)}» is running and doesn't make room for sources. It downloads when it's done."
    if in_corso:
        return (
            f"The pipeline is running outside the app ({in_corso[0]['script']}), which doesn't make room for sources. "
            "It downloads when it's done."
        )
    return ""


def _da_sola_tutte(
    in_corso: list[dict], run_app: dict | None, scarichi: list[dict]
) -> dict[str, dict]:
    ""
    comune = _posto_per_le_fonti(in_corso, run_app)
    sole = {d["sorgente"] for d in scarichi if d["vivo"]}
    out = {}
    for sid in sorted(CORSIE.LEGGERE):
        if sid in sole or _lock_tenuto(_lock_fonte_app(sid)):
            perche = "It's already downloading on its own."
        elif _lock_tenuto(CORSIE.lock_fonte(sid)):
            perche = "The full run is downloading it now."
        else:
            perche = comune
        out[sid] = {"possibile": not perche, "perche": perche}
    return out


def si_scarica_da_sola(sid: str) -> dict:
    ""
    if sid not in CORSIE.LEGGERE:
        return {
            "possibile": False,
            "perche": "This source downloads in the full run, or on its own when nothing is running.",
        }
    run_app = next((r for r in reversed(_runs()) if r["vivo"]), None)
    return _da_sola_tutte(_processi_pipeline(), run_app, _scarichi_soli())[sid]


def cmd_scarica_fonte(sid: str) -> dict:
    ""


    possibile = si_scarica_da_sola(sid)
    if not possibile["possibile"]:
        return {"ok": False, "errore": possibile["perche"]}
    SYSTEM.mkdir(parents=True, exist_ok=True)
    percorso_lock = _lock_fonte_app(sid)
    lock = percorso_lock.open("a+")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "errore": "It's already downloading on its own."}
        adesso = datetime.now()
        run_id = f"{adesso:%Y%m%d-%H%M%S}-fonte-{sid}"
        cartella = _cartella_scarico(sid, adesso)
        cartella.mkdir(parents=True, exist_ok=True)
        cmd = _comando_fonte(sid, cartella)
        voce = {
            "run_id": run_id,
            "sorgente": sid,
            "etichetta": f"fonte-{sid}",
            "comando": " ".join(cmd),
            "log": str(cartella / f"{run_id}.log"),
            "cartella": str(cartella),
            "inizio": adesso.strftime("%Y-%m-%dT%H:%M:%S"),
            "fine": None,
        }

        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps({"run_id": run_id}))
        lock.flush()
        with FONTI_RUNS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(voce, ensure_ascii=False) + "\n")
        proc = subprocess.Popen(
            [sys.executable, str(SB_RUN), run_id, str(cartella), "--", *cmd],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(lock.fileno(),),
            env=dict(
                os.environ,
                **AMBIENTE_RUN,
                SBK_RUN_LOCK_FD=str(lock.fileno()),
                SBK_RUN_REGISTRO=str(FONTI_RUNS),
                SBK_RUN_LOCK=str(percorso_lock),
            ),
        )
        return {
            "ok": True,
            **voce,
            "nome": f"{P.nome_fonte(sid)} on its own",
            "pid": proc.pid,
            "vivo": True,
        }
    finally:

        lock.close()


def cmd_ferma_fonte(run_id: str) -> dict:
    ""
    voce = next((d for d in _scarichi_soli() if d["run_id"] == run_id), None)
    if voce is None or not voce["vivo"]:
        return {"ok": False, "errore": "the download isn't alive"}
    (Path(voce["cartella"]) / f"{run_id}.ferma").write_text(_adesso())
    return {"ok": True, "richiesto": True}


def cmd_aggiorna() -> dict:
    ""


    cartella = DATA_ROOT / "logs"
    cartella.mkdir(parents=True, exist_ok=True)
    log = cartella / f"secondbrain-aggiornamento-{datetime.now():%Y%m%d-%H%M%S}.log"
    with log.open("w", encoding="utf-8") as f:
        subprocess.Popen(
            [*PY, "tools/secondbrain/installa.py", "--update"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"ok": True, "log": str(log)}


def cmd_rollback(versione: str) -> dict:
    ""

    cartella = DATA_ROOT / "logs"
    cartella.mkdir(parents=True, exist_ok=True)
    log = cartella / f"secondbrain-aggiornamento-{datetime.now():%Y%m%d-%H%M%S}.log"
    with log.open("w", encoding="utf-8") as f:
        subprocess.Popen(
            [*PY, "tools/secondbrain/installa.py", "--roll-back-to", versione],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"ok": True, "log": str(log)}


def cmd_versioni() -> dict:
    ""
    try:
        return {"ok": True, "corrente": SBV.corrente(), "storia": SBV.storia()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errore": str(e), "corrente": "", "storia": []}


def cmd_pulisci_lock() -> dict:
    ""


    if _gira_dall_app() or _occupato_da_fuori():
        return {"ok": False, "perche": "A run is going, its locks are alive and must not be touched."}
    r = subprocess.run(
        [*PY, "tools/util/sb-pipeline-ctl.py", "cleanup"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    tolti = sum(1 for x in r.stdout.splitlines() if "→ removed" in x or "→ rimosso" in x)
    return {"ok": True, "tolti": tolti, "dettaglio": r.stdout[-2000:]}


def cmd_consenso_docusign() -> dict:
    ""

    r = subprocess.run(
        [*PY, "tools/docusign/ds-l0-api.py", "--consent-url"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    url = next((x.strip() for x in r.stdout.splitlines() if x.strip().startswith("https://")), "")
    if not url:
        return {"ok": False, "perche": "DocuSign didn't give the consent URL."}
    return {"ok": True, "url": url}









REGOLE = ROOT / "tools" / "secondbrain" / "regole"

TENTATIVI_L0 = 3
ESITI_REGOLA = ("sì", "in parte", "no")


def _leggi_regole(nome: str) -> dict:
    try:
        return json.loads((REGOLE / f"{nome}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _testo(v) -> str:
    ""
    if v is None:
        return ""
    if isinstance(v, list | tuple):
        return " · ".join(_testo(x) for x in v if x not in (None, ""))
    return str(v)


def _elenco(v) -> list[str]:
    if v in (None, ""):
        return []
    if isinstance(v, list | tuple):
        return [_testo(x) for x in v if x not in (None, "")]
    return [_testo(v)]



VOCI_SPESA = {
    "lotti": "How it pays",
    "stima": "The expected cost",
    "consenso": "Your confirmation",
    "scelta": "You choose it",
    "chiavi": "The keys",

    "cancello": "It must close everything first",
}


def _spesa(v) -> list[dict]:
    if not isinstance(v, dict):
        return [{"voce": "Spend", "testo": _testo(v)}] if v else []
    return [{"voce": VOCI_SPESA.get(k, k), "testo": _testo(x)} for k, x in v.items() if x]



_RE_RIF_PROVA = re.compile(
    r"(?<![\w/.~-])((?:tools|tests|docs|sbk|\.claude)/[\w./@-]*?"
    r"\.(?:py|jsonl|json|md|sh|yaml|yml|toml|swift|mjs|js|tsv|txt))(?![\w])"
    r"(?::(\d+)(?:-(\d+))?)?(?:\s*«([^»]{4,})»)?"
)


@functools.lru_cache(maxsize=256)
def _codice_di_oggi(rel: str) -> tuple[int, str] | None:
    ""
    try:
        testo = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return len(testo.splitlines()), " ".join(testo.split())


def _prova_da_riverificare(*testi: str) -> list[str]:
    ""





    rotte: list[str] = []
    for testo in testi:
        for m in _RE_RIF_PROVA.finditer(testo or ""):
            rel, riga, _, pezzo = m.groups()
            if "*" in rel:
                continue
            codice = _codice_di_oggi(rel)
            if codice is None:
                rotte.append(f"the file {rel}")
                continue
            righe, unito = codice
            if riga and int(riga) > righe:
                rotte.append(f"line {riga} of {rel}, which has {righe}")
            if (
                pezzo
                and "…" not in pezzo
                and "..." not in pezzo
                and " ".join(pezzo.split()) not in unito
            ):
                rotte.append(f"«{pezzo}» in {rel}")
    return list(dict.fromkeys(rotte))


def _regola(r: dict) -> dict:
    ""




    esito = _testo(r.get("rispettata")).strip().lower()
    prova = _testo(r.get("prova"))
    dove = _testo(r.get("dove_nel_codice"))
    rotte = _prova_da_riverificare(prova, dove)
    if rotte:
        esito = ""
        prova = f"To re-verify, in today's code there is no longer {'; '.join(rotte)}. {prova}"
    return {
        "id": _testo(r.get("id")),
        "regola": _testo(r.get("regola")),
        "perche": _testo(r.get("perche")),
        "quando": _testo(r.get("quando")),
        "fonte": _testo(r.get("fonte")),
        "rispettata": esito if esito in ESITI_REGOLA else "",
        "prova": prova,
        "dove_nel_codice": dove,
        "da_riverificare": rotte,
    }


def _conta_regole(regole: list[dict]) -> dict[str, int]:
    conto = dict.fromkeys(ESITI_REGOLA, 0)
    for r in regole:
        if r.get("rispettata") in conto:
            conto[r["rispettata"]] += 1
    return conto




SENZA_TETTO: frozenset[str] = frozenset()


def _tetto_stadio(p) -> int | None:
    ""
    if p.tipo == "fuori_ciclo" or p.id in SENZA_TETTO:
        return None
    if p.strato == "L1":
        return XPR.L1_PHASE_TIMEOUT_S
    return XPR._timeout_step(p.nome)


def cmd_regole() -> dict:
    testi_f, testi_s, testi_g = (_leggi_regole(n) for n in ("fonti", "stadi", "generali"))
    per_fonte = {f["sorgente"]: f for f in testi_f.get("fonti", [])}
    per_stadio = {s["id"]: s for s in testi_s.get("stadi", [])}
    passi_di: dict[str, list] = {}

    for p in IMP.applica_al_piano(L0R.PIANO):
        passi_di.setdefault(p.sorgente, []).append(p)
    corsia_di = {nome: c for c, nomi in CORSIE.CORSIE_IN_PIU.items() for nome in nomi}

    fonti_out = []

    chiuse = [
        sid
        for sid in per_fonte
        if sid not in passi_di
        and sid not in L0R.MANUALI
        and getattr(sorgenti.SORGENTI.get(sid), "natura", "") == "chiusa"
    ]
    for sid in [*passi_di, *L0R.MANUALI, *chiuse]:
        reg = sorgenti.SORGENTI.get(sid)
        passi = passi_di.get(sid, [])
        t = per_fonte.get(sid, {})
        regole = [_regola(r) for r in t.get("regole_di_owner", [])]
        fonti_out.append(
            {
                "id": sid,
                "nome": P.nome_fonte(sid),
                "a_mano": sid in L0R.MANUALI,
                "chiusa": sid in chiuse,
                "come_a_mano": P.COME_A_MANO.get(sid, ""),
                "natura": P.NATURE.get(reg.natura, reg.natura) if reg else "",
                "ritmo_giorni": reg.ritmo_giorni if reg else None,
                "passi": [
                    {
                        "nome": P.PASSI_GIRO.get(p.nome, P.nome_fonte(sid)),
                        "tetto_s": p.timeout_s,
                        "comando": " ".join([*PY, *p.args]),
                    }
                    for p in passi
                ],
                "tentativi": TENTATIVI_L0 if passi else 0,
                "corsia": next(
                    (corsia_di[p.nome] for p in passi if p.nome in corsia_di),
                    "base" if passi else "",
                ),
                "leggera": sid in CORSIE.LEGGERE,
                "cosa_scarica": _testo(t.get("cosa_scarica")),
                "incrementale": _testo(t.get("incrementale")),
                "cosa_salta": _elenco(t.get("cosa_salta")),
                "limiti": _elenco(t.get("limiti")),
                "dove_scrive": _elenco(t.get("dove_scrive")),
                "regole_di_owner": regole,
                "conteggio": _conta_regole(regole),
                "errori": _elenco(t.get("errori_catalogo")),
                "prove": _elenco(t.get("prove")),
                "note": _testo(t.get("note")),
                "con_regole": bool(t),
            }
        )

    stadi_out = []
    for numero, p in enumerate(XPR.CATENA, start=1):
        t = per_stadio.get(p.id, {})
        regole = [_regola(r) for r in t.get("regole_di_owner", [])]
        stadi_out.append(
            {
                "id": p.id,
                "numero": numero,
                "nome": P.nome_stadio(p.id, p.nome),
                "nome_tecnico": p.nome,
                "frase": P.frase_stadio(p.id),
                "strato": p.strato,
                "pagato": p.tipo == "pagato",
                "fuori_ciclo": p.tipo == "fuori_ciclo",
                "perimetri": [P.RUN[m]["nome"] for m in MODI if p.nel_perimetro(m)],
                "tetto_s": _tetto_stadio(p),
                "script": _testo(t.get("script")),
                "argomenti": _testo(t.get("argomenti")),
                "cosa_fa": _testo(t.get("cosa_fa")),
                "incrementale": _testo(t.get("incrementale")),
                "memoria": _testo(t.get("memoria")),
                "se_fallisce": _testo(t.get("se_fallisce")),
                "legge": _elenco(t.get("legge")),
                "scrive": _elenco(t.get("scrive")),
                "dipende_da": _testo(t.get("dipende_da")),
                "chi_lo_usa": _testo(t.get("chi_lo_usa")),
                "spesa": _spesa(t.get("spesa")),
                "regole_di_owner": regole,
                "conteggio": _conta_regole(regole),
                "prove": _elenco(t.get("prove")),
                "note": _testo(t.get("note")),
                "con_regole": bool(t),
            }
        )


    generali = [_regola(g) for g in testi_g.get("generali", [])]
    tutte = [r for x in (*fonti_out, *stadi_out) for r in x["regole_di_owner"]] + generali
    return {
        "ok": True,
        "contratto": CONTRATTO,
        "verificate": testi_f.get("verificate") or testi_s.get("verificate"),

        "ricontrollate": testi_f.get("ricontrollate") or testi_s.get("ricontrollate"),
        "come": testi_f.get("come") or testi_s.get("come", ""),
        "generali": generali,
        "fonti": fonti_out,
        "stadi": stadi_out,
        "senza_regole": {
            "fonti": [f["id"] for f in fonti_out if not f["con_regole"]],
            "stadi": [s["id"] for s in stadi_out if not s["con_regole"]],
        },
        "conteggio": _conta_regole(tutte),
    }





# Structural checks on user-facing text: it should not leak internals
# (file names, CLI options, filesystem paths).
_VIETATI_TESTO_UTENTE = (
    (re.compile(r"\b[\w-]+\.(py|json|parquet|jsonl|sh|md)\b"), "a file name"),
    (re.compile(r"(?<![\w-])--[a-z]"), "an option"),
    (re.compile(r"~/|/Users/"), "a path"),
)

# Optional writing-style rules, loaded from user config; empty by default so the
# product ships with no personal writing style. Each entry is (compiled_regex, label).
_REGOLE_STILE: tuple[tuple[re.Pattern, str], ...] = ()


def problemi_di_parole(dove: str, testo) -> list[str]:
    ""
    out = []
    for rx, cosa in (*_VIETATI_TESTO_UTENTE, *_REGOLE_STILE):
        if m := rx.search(str(testo)):
            out.append(f"{dove} has {cosa} in the user-facing text («{m.group(0)}»)")
    return out


def _stringhe(v):
    ""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _stringhe(x)
    elif isinstance(v, list | tuple):
        for x in v:
            yield from _stringhe(x)


def problemi_parole_motore(parole: list[tuple[str, str]] | None = None) -> list[str]:
    ""
    elenco = parole if parole is not None else parole_del_motore()
    return [x for dove, testo in elenco for x in problemi_di_parole(dove, testo)]


def parole_del_motore() -> list[tuple[str, str]]:
    ""

    out = []
    for nome in (
        "STADI",
        "FONTI",
        "COME_A_MANO",
        "PASSI_A_MANO",
        "A_PARTE",
        "TOCCA_A_TE",
        "PASSI_GIRO",
        "NATURE",
    ):
        for k, v in getattr(P, nome).items():
            out += [(f"sb_parole.{nome}[{k}]", x) for x in _stringhe(v)]
    for nome in ("GRUPPI_FONTI", "FASI"):
        for i, v in enumerate(getattr(P, nome)):
            out += [(f"sb_parole.{nome}[{i}]", x) for x in _stringhe(v)]
    for k, v in P.RUN.items():
        out += [(f"sb_parole.RUN[{k}]", x) for x in _stringhe(v)]
    for gruppo, voci in P.VOCABOLARIO.items():
        for k, v in voci.items():
            out += [
                (f"sb_parole.VOCABOLARIO[{gruppo}][{k}].{campo}", v.get(campo, ""))
                for campo in ("parola", "aiuto", "titolo")
            ]
    out += [(f"sb_parole.GUIDA[{k}]", x) for k, v in P.GUIDA.items() for x in _stringhe(v)]

    for nome in ("CAPSULA", "COMPLETA"):
        out += [(f"sb_parole.{nome}[{k}]", v) for k, v in getattr(P, nome).items()]
    import sb_inspiration
    import sb_pagine

    out += [(f"sb_pagine.TESTI[{k}]", v) for k, v in sb_pagine.TESTI.items()]

    for nome in ("TESTI", "FRASI"):
        out += [
            (f"sb_inspiration.{nome}[{k}]", v) for k, v in getattr(sb_inspiration, nome).items()
        ]
    for s in sb_inspiration.SCHEDE:
        out += [(f"sb_inspiration.SCHEDE[{s['id']}].{c}", s[c]) for c in ("nome", "aiuto", "vuota")]
    for k, v in sb_inspiration.TIPI.items():
        out += [(f"sb_inspiration.TIPI[{k}]", v[0]), (f"sb_inspiration.TIPI[{k}].segno", v[3])]
    for voce in (*ERR.CATALOGO, ERR.SCONOSCIUTO):
        out += [
            (f"sb_errori {voce.id}.causa", voce.causa),
            (f"sb_errori {voce.id}.rimedio", voce.rimedio),
        ]
    for k, v in RIPRESA.FERMA.items():
        out += [(f"sb_ripresa.FERMA[{k}]", x) for x in _stringhe(v)]

    out += [(f"AUTOMATISMI[{k}]", v) for k, v in AUTOMATISMI.items()]
    return out


def problemi_regole(testi: dict | None = None) -> list[str]:
    ""





    t = (
        testi
        if testi is not None
        else {n: _leggi_regole(n) for n in ("fonti", "stadi", "generali")}
    )
    fonti = t.get("fonti", {}).get("fonti", [])
    stadi = t.get("stadi", {}).get("stadi", [])
    generali = t.get("generali", {}).get("generali", [])
    problemi: list[str] = []


    chiuse = {sid for sid, s in sorgenti.SORGENTI.items() if s.natura == "chiusa"}
    for cosa, attesi, ammessi, scritti in (
        (
            "source",
            {p.sorgente for p in L0R.PIANO} | set(L0R.MANUALI),
            chiuse,
            [f.get("sorgente") for f in fonti],
        ),
        ("stage", {p.id for p in XPR.CATENA}, set(), [s.get("id") for s in stadi]),
    ):
        problemi += [
            f"{cosa} {x} written twice"
            for x in sorted({x for x in scritti if scritti.count(x) > 1})
        ]
        problemi += [f"{cosa} {x} without rules" for x in sorted(attesi - set(scritti))]
        problemi += [
            f"{cosa} {x} has rules but no longer exists"
            for x in sorted(set(scritti) - attesi - ammessi, key=str)
        ]

    regole = [
        *((f"source {f.get('sorgente')}", r) for f in fonti for r in f.get("regole_di_owner", [])),
        *((f"stage {s.get('id')}", r) for s in stadi for r in s.get("regole_di_owner", [])),
        *((f"general {g.get('id')}", g) for g in generali),
    ]
    for dove, r in regole:
        manca = [
            nome
            for nome, c in (
                ("the text", r.get("regola")),
                ("the outcome", r.get("rispettata") in ESITI_REGOLA),
                ("the date", re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("quando", "")))),
                ("the source", r.get("fonte")),
                ("the proof", r.get("prova") or r.get("dove_nel_codice")),
            )
            if not c
        ]
        if manca:
            problemi.append(f"{dove}, a rule without {', '.join(manca)}")

    parole = [
        *(
            (f"{f.get('sorgente')}.{c}", f.get(c, ""))
            for f in fonti
            for c in ("cosa_scarica", "incrementale")
        ),
        *(
            (f"{f.get('sorgente')}.{c}[{i}]", v)
            for f in fonti
            for c in ("cosa_salta", "limiti")
            for i, v in enumerate(f.get(c, []))
        ),
        *(
            (f"{s.get('id')}.{c}", s.get(c, ""))
            for s in stadi
            for c in ("cosa_fa", "incrementale", "memoria", "se_fallisce")
        ),
        *((f"{dove}, la regola", r.get("regola", "")) for dove, r in regole),
        *((f"{dove}, il perché", r.get("perche", "")) for dove, r in regole),
    ]
    for dove, testo in parole:
        problemi += problemi_di_parole(dove, testo)

    giro = (TOOLS / "cross-source" / "xs-l0-refresh.py").read_text(encoding="utf-8")
    if f"for tentativo in {tuple(range(1, TENTATIVI_L0 + 1))}" not in giro:
        problemi.append(
            f"the run's attempts are no longer {TENTATIVI_L0}: TENTATIVI_L0 must be aligned with the code"
        )
    return problemi


def _sabota_regole() -> list[str]:
    ""
    vere = {n: _leggi_regole(n) for n in ("fonti", "stadi", "generali")}

    def copia():
        return json.loads(json.dumps(vere))

    def stadio_tolto(t):
        t["stadi"]["stadi"].pop()

    def fonte_doppia(t):
        t["fonti"]["fonti"].append(t["fonti"]["fonti"][0])

    def regola_senza_esito(t):
        next(s for s in t["stadi"]["stadi"] if s.get("regole_di_owner"))["regole_di_owner"][0][
            "rispettata"
        ] = "forse"

    def file_nelle_parole(t):
        t["fonti"]["fonti"][0]["cosa_scarica"] += " Lo scrive in index.json"

    def due_punti(t):
        t["stadi"]["stadi"][0]["cosa_fa"] += " Attenzione: è lento"

    def punto_e_virgola(t):
        t["fonti"]["fonti"][0]["cosa_scarica"] += " Scarica tutto; poi si ferma."

    def apostrofo_per_accento(t):
        t["stadi"]["stadi"][0]["cosa_fa"] += " Il giro e' lento."

    def due_non_ma(t):
        t["generali"]["generali"][0]["perche"] = (
            "Non serve a te, ma al giro. Non lo fa il Mac, ma il server."
        )

    def perche_con_due_punti(t):
        next(s for s in t["stadi"]["stadi"] if s.get("regole_di_owner"))["regole_di_owner"][0][
            "perche"
        ] = "Perché: va"

    mancati = []
    guasti = (
        stadio_tolto,
        fonte_doppia,
        regola_senza_esito,
        file_nelle_parole,
        due_punti,
        punto_e_virgola,
        apostrofo_per_accento,
        due_non_ma,
        perche_con_due_punti,
    )
    for guasto in guasti:
        t = copia()
        guasto(t)
        if len(problemi_regole(t)) <= len(problemi_regole(vere)):
            mancati.append(guasto.__name__)

    if len(problemi_parole_motore([("sb_errori finto.causa", "Il servizio e' giù; riprova.")])) < 2:
        mancati.append("parole_del_motore")
    return mancati


def cmd_controlla_regole(sabota: bool) -> int:
    problemi = problemi_regole() + problemi_parole_motore()
    for p in problemi:
        print(f"✗ {p}")
    mancati = _sabota_regole() if sabota else []
    for g in mancati:
        print(f"✗ the guard doesn't see the planted fault «{g}»")
    if not problemi and not mancati:
        print(
            f"rules of the Rules section are fine: {len(L0R.PIANO)} run steps, {len(XPR.CATENA)} stages, "
            f"{len(parole_del_motore())} engine words"
            + (", ten planted faults seen" if sabota else "")
        )
    return 1 if problemi or mancati else 0





DISCO_STORIA = SYSTEM / "secondbrain-disco.jsonl"

DISCO_ATTENZIONE_GB = 60
DISCO_ERRORE_GB = 20


def spazio_disco(adesso: float | None = None, uso=None) -> dict:
    ""
    adesso = adesso or time.time()
    try:
        u = uso or shutil.disk_usage(DATA_ROOT)
    except OSError:
        return {}
    try:
        storia = [
            json.loads(r)
            for r in DISCO_STORIA.read_text(encoding="utf-8").splitlines()
            if r.strip()
        ]
    except (OSError, ValueError):
        storia = []
    if not storia or adesso - storia[-1]["t"] >= 600:
        storia = [*storia, {"t": round(adesso), "libero": u.free}][-48:]
        try:
            sbk_config.scrivi_atomico(
                DISCO_STORIA, "\n".join(json.dumps(s) for s in storia) + "\n"
            )
        except OSError:
            pass
    recenti = [s for s in storia if adesso - s["t"] <= 3 * 3600]
    ritmo = None
    if recenti and adesso - recenti[0]["t"] >= 1800:
        ritmo = (recenti[0]["libero"] - u.free) / 1e9 / ((adesso - recenti[0]["t"]) / 3600)
    libero = u.free / 1e9
    ore = libero / ritmo if ritmo and ritmo > 0.2 else None
    if libero < DISCO_ERRORE_GB or (ore is not None and ore < 6):
        salute = "errore"
    elif libero < DISCO_ATTENZIONE_GB or (ore is not None and ore < 24):
        salute = "attenzione"
    else:
        salute = "ok"
    frase = f"{libero:.0f} GB remaining."
    if ritmo is not None and ritmo > 0.2:
        frase += f" About {ritmo:.0f} disappear per hour"
        frase += f", at this rate it runs out in {durata(ore * 3600)}." if ore else "."
    if salute != "ok":
        frase += (
            " A full disk stops runs and takes from the Mac the space it needs for memory."
        )
    return {
        "libero_gb": round(libero),
        "totale_gb": round(u.total / 1e9),
        "ritmo_gb_ora": round(ritmo, 1) if ritmo is not None else None,
        "ore_alla_fine": round(ore, 1) if ore is not None else None,
        "salute": salute,
        "frase": frase,
    }





def cmd_impostazioni() -> dict:
    ""
    return {"ok": True, "contratto": CONTRATTO, "soglie": IMP.descrivi()}


def cmd_imposta(sezione: str, chiave: str, valore: str) -> dict:
    ""
    s = next((x for x in IMP.SOGLIE if (x.sezione, x.chiave) == (sezione, chiave)), None)
    if s is None:
        return {"ok": False, "errore": f"I don't know the threshold {sezione}.{chiave}."}
    if isinstance(s.partenza, bool):
        v: int | bool = valore.strip().lower() in ("1", "true", "yes", "on")
    else:
        try:
            v = int(valore)
        except ValueError:
            return {"ok": False, "errore": f"{s.nome} wants a whole number."}
    ok, perche = IMP.imposta(sezione, chiave, v)
    return {"ok": ok, "errore": perche or None, "soglie": IMP.descrivi()}



_RE_DRIVE_TENTATIVO = re.compile(r"^── (?:attempt|tentativo) (\d+) · (\d\d/\d\d \d\d:\d\d:\d\d)")
_RE_DRIVE_CASELLA = re.compile(r"INFO Account: (\S+)")
_RE_DRIVE_TROVATE = re.compile(r"\] Found (\d+) Shared Drives")
_RE_DRIVE_CARTELLA = re.compile(r"--- Shared Drive: (.+?) ---")
_RE_DRIVE_CERCA = re.compile(r"Searching files (shared with me|modified in last)")
_RE_DRIVE_FILE = re.compile(
    r"\[(\d+)/(\d+)\] Processing\.\.\. \((\d+) downloaded, (\d+) (?:unchanged|invariati), (\d+) skipped\)"
)
_RE_DRIVE_FATTO = re.compile(
    r"\] Done: (\d+) downloaded, (\d+) (?:unchanged|invariati), (\d+) skipped"
)
_RE_DRIVE_INDICE = re.compile(r"Master index: (\d+) total files tracked")


def _caselle_drive() -> list[str]:
    ""
    try:
        return list(
            json.loads((sbk_config.EMAILS_DIR / "accounts.json").read_text(encoding="utf-8"))
        )
    except (OSError, ValueError):
        return []


def _registro_drive() -> Path | None:
    ""
    return max(FULLRUN.glob("*/log/gdrive.log"), key=lambda p: p.stat().st_mtime, default=None)


def avanzamento_drive(righe: list[str], caselle: list[str]) -> dict | None:
    ""



    inizi = [i for i, r in enumerate(righe) if _RE_DRIVE_TENTATIVO.match(r)]
    if not inizi:
        return None
    m = _RE_DRIVE_TENTATIVO.match(righe[inizi[-1]])
    out: dict = {
        "tentativo": int(m.group(1)),
        "dalle": m.group(2),
        "casella": None,
        "caselle_prima": 0,
        "caselle_tot": len(caselle),
        "sezione": None,
        "cartella": None,
        "cartella_n": 0,
        "cartelle_tot": None,
        "file_i": None,
        "file_n": None,
        "scaricati": 0,
        "invariati": 0,
        "saltati": 0,
        "indice": None,
    }
    for r in righe[inizi[-1] + 1 :]:
        if mc := _RE_DRIVE_CASELLA.search(r):
            out.update(
                casella=mc.group(1), sezione=None, cartella=None, cartella_n=0, cartelle_tot=None
            )
            out["caselle_prima"] = (
                caselle.index(mc.group(1)) if mc.group(1) in caselle else out["caselle_prima"]
            )
            out.update(file_i=None, file_n=None)
        elif mt := _RE_DRIVE_TROVATE.search(r):
            out["cartelle_tot"] = int(mt.group(1))
        elif mk := _RE_DRIVE_CARTELLA.search(r):
            out.update(
                sezione="shared drives", cartella=mk.group(1).strip(), file_i=None, file_n=None
            )
            out["cartella_n"] += 1
        elif ms := _RE_DRIVE_CERCA.search(r):
            sezione = "shared with you" if ms.group(1) == "shared with me" else "your files"
            out.update(sezione=sezione, cartella=None, file_i=None, file_n=None)
        elif mf := _RE_DRIVE_FILE.search(r):
            out.update(file_i=int(mf.group(1)), file_n=int(mf.group(2)))
        elif md := _RE_DRIVE_FATTO.search(r):
            out["scaricati"] += int(md.group(1))
            out["invariati"] += int(md.group(2))
            out["saltati"] += int(md.group(3))
        elif mi := _RE_DRIVE_INDICE.search(r):
            out["indice"] = int(mi.group(1))
    return out


def cmd_drive() -> dict:
    ""
    testi = {f["sorgente"]: f for f in _leggi_regole("fonti").get("fonti", [])}.get("gdrive", {})
    caselle = _caselle_drive()
    log = _registro_drive()
    av = None
    vivo = False
    if log is not None:
        righe = log.read_text(encoding="utf-8", errors="replace").splitlines()
        av = avanzamento_drive(righe, caselle)
        segno = time.time() - log.stat().st_mtime
        vivo = segno < 300 and bool(_processi_pipeline_vivi("gd-l0-download.py"))
        if av is not None:
            av["vivo"] = vivo
            av["ultimo_segno_s"] = round(segno)
            av["registro"] = str(log)
    return {
        "ok": True,
        "contratto": CONTRATTO,
        "soglie": IMP.descrivi("drive"),
        "frase": IMP.frase("drive"),
        "tentativi": TENTATIVI_L0,
        "caselle": caselle,
        "incrementale": _testo(testi.get("incrementale")),
        "cosa_salta": _elenco(testi.get("cosa_salta")),
        "avanzamento": av,
    }


def _processi_pipeline_vivi(script: str) -> list[int]:
    ""
    try:
        r = subprocess.run(["pgrep", "-f", script], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    io = os.getpid()
    return [int(x) for x in r.stdout.split() if x.isdigit() and int(x) != io]




_RE_GUARDIANO = {
    "attesa_s": re.compile(r"wait_for_headroom\(timeout_s=(\d+)"),

    "attesa_senza_tetto": re.compile(r"while \(adesso := pressure\(\)\)\.seg_ratio >= SEG_YIELD:"),
    "fattore": re.compile(r"job_bytes \* ([\d.]+)\)\s*#\s*intervento"),


    "ponte_s": re.compile(r"^_PONTE_S = (\d+)", re.M),
    "rientro_frazione": re.compile(r"if seg < SEG_CRITICAL \* ([\d.]+):"),
    "pericolo_ponte": re.compile(
        r"elif waited > _PONTE_S:\n\s+log\.error\(\n\s+\"  \[(?:resources|risorse)\] "
        r"(?:pressure not back|pressione non rientra)"
    ),
    "passo_s": re.compile(r"^_GUARDIA_OGNI_S = (\d+)", re.M),
}


def _numeri_guardiano() -> dict:
    try:
        testo = (TOOLS / "cross-source" / "xs-pipeline-run.py").read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict = {}
    for k, rx in _RE_GUARDIANO.items():
        m = rx.search(testo)
        if not m:
            out[k] = None
        elif k in ("attesa_senza_tetto", "pericolo_ponte"):
            out[k] = True
        else:
            out[k] = float(m.group(1)) if k in ("fattore", "rientro_frazione") else int(m.group(1))
    return out


def _il(pct: int) -> str:
    ""
    return ""



SOGLIE_PRESSIONE = (
    ("SEG_OK", "Below, everything at full speed."),
    ("SEG_ADMIT_MAX", "Above, no new jobs start."),
    ("SEG_WARN", "Above, steps wait before starting, up to fifteen minutes."),
    (
        "SEG_YIELD",
        "Above, steps don't start until it drops, and those that can save their place and yield it.",
    ),
    ("SEG_CRITICAL", "Above, the guard freezes steps and closes them if it doesn't drop right away."),
    ("SEG_PANIC", "The wall beyond which the machine risks a reboot from exhausted memory."),
)


def guardiano() -> dict:
    ""

    import pipeline_dlq
    import sbk_resources as R

    try:
        p = R.pressure()
        pressione = {
            "pct": round(p.seg_ratio * 100),
            "livello": p.level,
            "grado": R.level_for(p.seg_ratio),
        }
    except Exception as e:  # noqa: BLE001
        pressione = {"pct": None, "livello": f"not measured ({type(e).__name__})", "grado": None}
    try:
        b = R.budget()
        st = R.shared_state()
        budget_job = {
            "job_gb": round(b.job_bytes / 1024**3, 1),
            "lavori": st.n_leases,
            "pool_pct": round(st.pool_frac * 100),
        }
    except Exception:  # noqa: BLE001
        budget_job = None
    soglie = [
        {"nome": n, "pct": round(getattr(R, n) * 100), "cosa": cosa}
        for n, cosa in SOGLIE_PRESSIONE
        if isinstance(getattr(R, n, None), int | float)
    ]
    n = _numeri_guardiano()
    scelta = IMP.leggi()["guardiano"]
    regole = []
    if n.get("attesa_s") and n.get("attesa_senza_tetto"):
        warn, resa = round(R.SEG_WARN * 100), round(R.SEG_YIELD * 100)
        regole.append(
            f"Before each step, if memory is under pressure, it waits up to {n['attesa_s'] // 60} minutes. "
            f"If pressure stays above {resa}% it waits until it drops; between {warn}% and "
            f"{resa}% it starts with a reduced budget."
        )
    elif n.get("attesa_s"):
        regole.append(
            f"Before each step, if memory is under pressure, it waits up to {n['attesa_s'] // 60} minutes. "
            "Then the step starts anyway, with a reduced budget."
        )
    if scelta["solo_pericolo"]:
        regole.append(
            "If a step exceeds its budget it lets it work and writes it to the log. It stops it only when the "
            "Mac reaches the critical threshold."
        )
    elif n.get("fattore") and n.get("ponte_s"):
        regole.append(
            f"If a step exceeds its budget by {n['fattore']} times, it freezes it and after "
            f"{n['ponte_s']} seconds closes it, even when the rest of the Mac is calm."
        )
    if scelta["memoria_minima"] and getattr(R, "SEG_OK", None):
        gb = R.total_ram_bytes() * scelta["memoria_minima"] / 100 / 1024**3
        regole.append(
            f"With memory below {round(R.SEG_OK * 100)}%, a step gets at least {scelta['memoria_minima']}% "
            f"of RAM, about {round(gb)} GB, even if the other apps hold a lot."
        )
    if n.get("pericolo_ponte") and n.get("ponte_s"):
        regole.append(
            "If the Mac reaches the critical threshold, it freezes the step. It resumes it as soon as pressure drops, "
            f"and if it doesn't drop within {n['ponte_s']} seconds it closes it and retries when there's space."
        )
    if n.get("passo_s"):
        regole.append(f"It checks the step's memory every {n['passo_s']} seconds.")
    interventi = []
    try:
        for f in pipeline_dlq.get_all_failures(include_resolved=True):
            if f.get("error_type") != "memory_kill":
                continue
            msg = f.get("error_message") or ""
            interventi.append(
                {

                    "quando": _locale_da_utc(f.get("timestamp")),
                    "step": f.get("source") or f.get("script_name"),
                    "perche": "quota"
                    if "budget" in msg
                    else ("pericolo" if "pressione" in msg else msg),
                }
            )
    except Exception:  # noqa: BLE001
        pass
    interventi.sort(key=lambda x: x["quando"] or "", reverse=True)
    return {
        "pressione": pressione,
        "soglie": soglie,
        "budget": budget_job,
        "regole": regole,
        "numeri_letti": all(v is not None for v in n.values()) and bool(n),
        "interventi": interventi[:20],
        "per_quota": sum(1 for x in interventi if x["perche"] == "quota"),
        "per_pericolo": sum(1 for x in interventi if x["perche"] == "pericolo"),
        "proposta": (
            "A step is stopped only when memory is at risk. Change this in the settings above."
            if scelta["solo_pericolo"]
            else "A step is also stopped on an idle machine when it exceeds 1.5x the budget. "
            "Switch to risk-only in the settings above."
        ),
        "deciso": bool(scelta["solo_pericolo"]),
    }




# Known automation labels; only generic SBK jobs by default.
# Extend with the user's own jobs via config.
AUTOMATISMI = {
    "com.sbk.daily-briefing": "A Slack briefing on weekdays at 8am.",
    "com.sbk.brief": "An earlier briefing job (disabled).",
    "com.sbk.followup-watch": "Watches a mailbox for a reply to a tracked thread.",
    "com.sbk.backup": "A full backup of the data, on Sundays.",
    "com.sbk.score-snapshot": "A nightly snapshot of relationship scores, for review.",
    "com.sbk.mem-telemetry": "Records memory pressure every 30 seconds.",
}
# Job label prefixes to show; the generic SBK family by default, extend via config
# (SBK_JOB_PREFIXES, comma-separated).
_FAMIGLIE = (
    "com.sbk.",
    *(s.strip() for s in os.environ.get("SBK_JOB_PREFIXES", "").split(",") if s.strip()),
)
_GIORNI = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def _quando_parte(plist: dict) -> str:
    ""
    if plist.get("KeepAlive"):
        return "always on"
    if iv := plist.get("StartInterval"):
        return f"every {iv // 60} minutes" if iv >= 60 else f"every {iv} seconds"
    cal = plist.get("StartCalendarInterval")
    if cal:
        voci = cal if isinstance(cal, list) else [cal]
        ore = sorted({f"{v.get('Hour', 0):02d}:{v.get('Minute', 0):02d}" for v in voci})
        giorni = sorted({v["Weekday"] for v in voci if "Weekday" in v})
        if "Month" in voci[0] or "Day" in voci[0]:
            return f"on {voci[0].get('Day', 1)}/{voci[0].get('Month', 1)} at {ore[0]}"
        if giorni == [1, 2, 3, 4, 5]:
            return f"Mon-Fri at {', '.join(ore)}"
        if giorni:
            return f"{', '.join(_GIORNI[g % 7] for g in giorni)} at {', '.join(ore)}"
        return f"every day at {', '.join(ore)}"
    if plist.get("RunAtLoad"):
        return "at startup"
    return ""


def _parola_registro(riga: dict | None) -> str | None:
    ""
    if riga is None:
        return None
    if (riga.get("why") or "").startswith("not wired up yet") and riga.get("outcome") != "failed":
        return "doesn't say how it ends"
    esito, ultimo = riga.get("outcome"), riga.get("last_run")
    if esito == "failed":
        causa = _causa_lavoro(riga.get("detail") or "")
        return f"the last run failed {quando(ultimo)}" + (f", {causa}" if causa else "")
    if _non_partito(riga):
        return (
            f"the last run was {quando(ultimo)}, then it stopped starting"
            if ultimo
            else "it never started"
        )
    if esito in _RIUSCITI and ultimo:
        return f"the last run went {quando(ultimo)}"
    return None


def automatismi(righe: list[dict] | None = None) -> list[dict]:
    ""



    import plistlib

    per_chiave = {r.get("key"): r for r in righe or []}

    vivi: dict[str, tuple[str, str]] = {}
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        for riga in r.stdout.splitlines()[1:]:
            parti = riga.split("\t")
            if len(parti) == 3:
                vivi[parti[2]] = (parti[0], parti[1])
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    cartella = Path.home() / "Library" / "LaunchAgents"
    for f in sorted(cartella.glob("*.plist*")):
        nome = f.name.split(".plist")[0]
        if not nome.startswith(_FAMIGLIE):
            continue
        spento_il = None
        if ".disabled-" in f.name:
            spento_il = f.name.rsplit(".disabled-", 1)[1]
        try:
            pl = plistlib.loads(f.read_bytes())
        except Exception:  # noqa: BLE001
            pl = {}
        pid, rc = vivi.get(nome, ("", ""))
        out.append(
            {
                "nome": nome,
                "cosa": AUTOMATISMI.get(nome, ""),
                "quando": _quando_parte(pl),
                "caricato": nome in vivi,
                "gira_adesso": pid not in ("", "-"),
                "ultimo_esito": int(rc) if rc.lstrip("-").isdigit() else None,
                "registro": _parola_registro(per_chiave.get(nome)),
                "spento_il": spento_il,
            }
        )

    return sorted(out, key=lambda a: (not a["caricato"], a["nome"]))


def cmd_strumenti() -> dict:
    ""

    cache, prima = _carica_cache()
    registro = _righe_registro(cache)
    _salva_cache(cache, prima)
    return {
        "ok": True,
        "contratto": CONTRATTO,
        "guardiano": guardiano(),
        "automatismi": automatismi(registro),
    }







CERCA = ROOT / "tools" / "util" / "sb-cerca.py"
_RE_RISULTATO = re.compile(r"^(\d+)\. \[([^\]]+)\] (\S+) \(score: ([\d.]+)\)$")

NOMI_FRAMMENTI = (
    ("email", "Email"),
    ("gmail", "Email"),
    ("slack", "Slack"),
    ("wa", "WhatsApp"),
    ("whatsapp", "WhatsApp"),
    ("plaud", "Plaud"),
    ("tactiq", "Tactiq"),
    ("attio", "Attio"),
    ("gdrive", "Google Drive"),
    ("calendar", "Calendar"),
    ("clickup", "ClickUp"),
    ("notion", "Notion"),
    ("linkedin", "LinkedIn"),
    ("voice", "Voice memos"),
    ("kb", "Brain"),
    ("entity", "Brain"),
    ("chatgpt", "ChatGPT"),
    ("manus", "Manus"),
    ("docusign", "DocuSign"),
    ("personio", "Personio"),
    ("session", "Work sessions"),
)


def _nome_frammento(tipo: str) -> str:
    return next((nome for pref, nome in NOMI_FRAMMENTI if tipo.startswith(pref)), tipo)


def leggi_risultati(testo: str) -> list[dict]:
    ""
    out: list[dict] = []
    for riga in testo.splitlines():
        if m := _RE_RISULTATO.match(riga.strip()):
            out.append(
                {
                    "fonte": m.group(2),
                    "nome_fonte": _nome_frammento(m.group(2)),
                    "data": m.group(3) if m.group(3) != "n/a" else "",
                    "punteggio": float(m.group(4)),
                    "contesto": "",
                    "testo": "",
                }
            )
        elif out and riga.startswith("   Context: "):
            out[-1]["contesto"] = riga.removeprefix("   Context: ").strip()
        elif out and riga.startswith("   ") and riga.strip():
            out[-1]["testo"] = (out[-1]["testo"] + " " + riga.strip()).strip()
    return out





MISURA_CERCA = SYSTEM / "cerca-memoria.json"

CERCA_PASSO_S = 0.5
CERCA_TETTO_S = 240


def _bisogno_cerca() -> float:
    ""

    from sbk_resources import total_ram_bytes

    try:
        picco = int(json.loads(MISURA_CERCA.read_text(encoding="utf-8")).get("picco_byte") or 0)
    except (OSError, ValueError, AttributeError, TypeError):
        picco = 0
    if picco <= 0:
        return 0.02
    return max(0.01, picco * 1.25 / total_ram_bytes())


def _scrivi_misura_cerca(picco: int, secondi: float) -> None:
    if picco <= 0:
        return
    try:
        MISURA_CERCA.parent.mkdir(parents=True, exist_ok=True)
        tmp = MISURA_CERCA.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"picco_byte": picco, "secondi": round(secondi, 1), "quando": _adesso()}),
            encoding="utf-8",
        )
        os.replace(tmp, MISURA_CERCA)
    except OSError:
        pass


def _posto_per_cercare():
    ""



    from sbk_resources import SEG_OK, Lease, pressure

    lz = Lease("app-cerca", need_frac=_bisogno_cerca(), klass="ricerca")
    try:
        if lz.acquire():
            return True, lz
    except OSError:
        pass
    try:
        return pressure().seg_ratio < SEG_OK, None
    except Exception:  # noqa: BLE001
        return False, None


def _gb(byte: int) -> str:
    return f"{byte / 1024**3:.1f}".replace(".", ",")


def cmd_cerca(
    domanda: str, fonte: str | None = None, dal: str | None = None, quanti: int = 12
) -> dict:
    domanda = domanda.strip()
    if not domanda or len(domanda) > 300:
        return {"ok": False, "errore": "Write a question, a few lines at most."}
    from sbk_resources import SEG_YIELD, pressure, tree_footprint

    entra, lz = _posto_per_cercare()
    if not entra:
        try:
            picco = int(json.loads(MISURA_CERCA.read_text(encoding="utf-8")).get("picco_byte") or 0)
        except (OSError, ValueError, AttributeError, TypeError):
            picco = 0
        quanto = f", which takes about {_gb(picco)} GB" if picco > 0 else ""
        return {
            "ok": False,
            "errore": f"The Mac has no free memory for the search right now{quanto}. Try again shortly.",
        }
    cmd = [*PY, str(CERCA), domanda, "--grezzo", "--quanti", str(max(1, min(int(quanti), 30)))]
    if fonte:
        cmd += ["--fonte", fonte]
    if dal:
        cmd += ["--dal", dal]
    t0 = time.time()
    picco = 0
    fermata = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        while True:
            try:
                out, _ = proc.communicate(timeout=CERCA_PASSO_S)
                break
            except subprocess.TimeoutExpired:

                picco = max(picco, tree_footprint(proc.pid))
                try:
                    pieno = pressure().seg_ratio >= SEG_YIELD
                except Exception:  # noqa: BLE001
                    pieno = False
                if pieno:
                    fermata = "memoria"
                elif time.time() - t0 > CERCA_TETTO_S:
                    fermata = "tempo"
                else:
                    continue
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
                out = ""
                break
    finally:
        if lz is not None:
            lz.release()
    secondi = time.time() - t0
    _scrivi_misura_cerca(picco, secondi)
    if fermata == "memoria":
        return {
            "ok": False,
            "errore": "I stopped the search because the Mac was running out of memory. Try again with fewer jobs open.",
        }
    if fermata == "tempo":
        return {"ok": False, "errore": "The search exceeded four minutes."}
    risultati = leggi_risultati(out or "")
    if proc.returncode != 0 and not risultati:
        return {
            "ok": False,
            "errore": "The search failed. The data index may be updating.",
        }
    return {"ok": True, "risultati": risultati, "secondi": round(secondi)}





DA_VERIFICARE = DATA_ROOT / "enriched" / "merge-da-verificare.jsonl"
VERIFICHE = DATA_ROOT / "system" / "merge-verifiche.json"
NOMI_FONTE_VERIFICA = {
    "linkedin": "LinkedIn",
    "slack": "Slack",
    "whatsapp": "WhatsApp",
    "docusign": "DocuSign",
    "iphone": "Phone contacts",
    "notion": "Notion",
    "chatgpt": "ChatGPT",
}


def _cifra(n: int) -> str:
    ""
    return f"{n:,}".replace(",", ".")


def _intero(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _peso_caso(c: dict) -> int:
    ""
    s = c.get("segnali") or {}
    return (
        _intero(s.get("messaggi")) + 10 * _intero(s.get("contratti")) + _intero(s.get("menzioni"))
    )


def _dettagli_caso(c: dict) -> str:
    ""
    s = c.get("segnali") or {}
    pezzi = []
    for chiave, plurale, singolare in (
        ("messaggi", "messages", "message"),
        ("contratti", "contracts", "contract"),
        ("menzioni", "mentions", "mention"),
    ):
        n = _intero(s.get(chiave))
        if n:
            pezzi.append(f"{_cifra(n)} {plurale if n != 1 else singolare}")
    for chiave in ("ruolo", "azienda", "telefono"):
        if str(s.get(chiave) or "").strip():
            pezzi.append(str(s[chiave]).strip())
    return " · ".join(pezzi)


def _risposte_verifiche() -> list[dict]:
    try:
        righe = json.loads(VERIFICHE.read_text(encoding="utf-8")).get("verifiche", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in righe if isinstance(r, dict)] if isinstance(righe, list) else []


def _casi_da_verificare() -> tuple[list[dict], str | None]:
    ""
    try:
        righe = DA_VERIFICARE.read_text(encoding="utf-8").splitlines()
        quando_file = _iso(DA_VERIFICARE.stat().st_mtime)
    except OSError:
        return [], None
    risposte = {(r.get("fonte"), r.get("chiave")) for r in _risposte_verifiche()}
    casi = []
    for riga in righe:
        try:
            c = json.loads(riga)
        except ValueError:
            continue
        if not isinstance(c, dict) or (c.get("fonte"), c.get("chiave")) in risposte:
            continue
        casi.append(c)
    casi.sort(key=lambda c: (-_peso_caso(c), -float(c.get("punteggio") or 0)))
    return casi, quando_file


def riassunto_verifiche() -> dict | None:
    ""
    casi, quando_file = _casi_da_verificare()
    if quando_file is None:
        return None
    con_peso = sum(1 for c in casi if _peso_caso(c) > 0)
    if not casi:
        frase = "No contacts to verify. The merge links by name only when it's sure."
    else:
        frase = (
            f"{_cifra(len(casi))} name links set aside by the merge {quando(quando_file)}, "
            f"{_cifra(con_peso)} with messages, contracts or mentions. They don't apply until you respond."
        )
    return {"totale": len(casi), "con_peso": con_peso, "quando": quando_file, "frase": frase}


def cmd_verifiche(quanti: int = 150) -> dict:
    ""
    casi, quando_file = _casi_da_verificare()
    if quando_file is None:
        return {
            "ok": True,
            "totale": 0,
            "con_peso": 0,
            "casi": [],
            "quando": None,
            "frase": "The contacts merge hasn't written the cases to verify yet. They arrive with the next run.",
        }
    fuori = []
    for c in casi[:quanti]:
        fuori.append(
            {
                "id": f"{c.get('fonte')}|{c.get('chiave')}",
                "fonte": str(c.get("fonte") or ""),
                "nome_fonte": NOMI_FONTE_VERIFICA.get(c.get("fonte"), str(c.get("fonte") or "")),
                "chiave": str(c.get("chiave") or ""),
                "nome": str(c.get("nome") or ""),
                "candidati": [
                    {"email": str(x.get("email") or ""), "nome": str(x.get("nome") or "")}
                    for x in c.get("candidati") or []
                    if isinstance(x, dict)
                ],
                "altri_candidati": _intero(c.get("altri_candidati")),
                "motivo": str(c.get("motivo") or "")[:1].upper() + str(c.get("motivo") or "")[1:],
                "dettagli": _dettagli_caso(c),
                "peso": _peso_caso(c),
            }
        )
    return {
        "ok": True,
        "totale": len(casi),
        "con_peso": sum(1 for c in casi if _peso_caso(c) > 0),
        "casi": fuori,
        "quando": quando_file,
        "frase": None,
    }


def cmd_verifica(fonte: str, chiave: str, esito: str, emails: list[str]) -> dict:
    ""

    emails = [e.strip().lower() for e in emails if "@" in e]
    if (
        esito not in ("si", "no")
        or not fonte
        or not chiave
        or not emails
        or (esito == "si" and len(emails) != 1)
    ):
        return {"ok": False, "errore": "Invalid response."}
    righe = _risposte_verifiche()
    adesso = _iso(time.time())
    righe += [
        {"fonte": fonte, "chiave": chiave, "email": e, "esito": esito, "quando": adesso}
        for e in emails
    ]
    VERIFICHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VERIFICHE.with_name(VERIFICHE.name + ".tmp")
    tmp.write_text(
        json.dumps({"versione": 1, "verifiche": righe}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    tmp.replace(VERIFICHE)
    return {"ok": True, "risposte": len(righe)}


def cmd_verifica_annulla() -> dict:
    ""
    righe = _risposte_verifiche()
    if not righe:
        return {"ok": False, "errore": "There is no response to undo."}
    ultima = righe[-1]
    stessa = (ultima.get("fonte"), ultima.get("chiave"), ultima.get("quando"))
    while (
        righe
        and (righe[-1].get("fonte"), righe[-1].get("chiave"), righe[-1].get("quando")) == stessa
    ):
        righe.pop()
    tmp = VERIFICHE.with_name(VERIFICHE.name + ".tmp")
    tmp.write_text(
        json.dumps({"versione": 1, "verifiche": righe}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    tmp.replace(VERIFICHE)
    return {"ok": True, "risposte": len(righe)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Engine of the SBK macOS app"])[0]
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stato").add_argument("--fresco", action="store_true")

    sub.add_parser("eta")
    sub.add_parser("aggiorna")
    sub.add_parser("rollback").add_argument("versione")
    sub.add_parser("versioni")
    sub.add_parser("scarica-fonte").add_argument("fonte")
    sub.add_parser("trascrivi-memo")
    sub.add_parser("ferma-fonte").add_argument("run_id")
    la = sub.add_parser("lancia")
    la.add_argument("tipo", choices=("full", "full_completa", "l0", "modo", "stadio", "riprendi"))
    la.add_argument("arg", nargs="?", default="")
    la.add_argument("--consenti-spesa", action="store_true")
    la.add_argument("--spesa", default=None, help="chosen paid steps, ids separated by commas")
    sub.add_parser("pausa").add_argument("run_id")
    sub.add_parser("continua").add_argument("run_id")
    fe = sub.add_parser("ferma")
    fe.add_argument("run_id")
    fe.add_argument("--forza", action="store_true")
    ru = sub.add_parser("run")
    ru.add_argument("run_id")
    pu = sub.add_parser("pulisci")
    pu.add_argument("run_id")
    lo = sub.add_parser("log")
    lo.add_argument("run_id")
    lo.add_argument("--righe", type=int, default=400)
    sub.add_parser("stima").add_argument("--ultima", action="store_true")
    sub.add_parser("pulisci-lock")
    sub.add_parser("consenso-docusign")
    sub.add_parser("impostazioni")
    im = sub.add_parser("imposta")
    im.add_argument("sezione")
    im.add_argument("chiave")
    im.add_argument("valore")
    sub.add_parser("drive")
    sub.add_parser("strumenti")

    sub.add_parser("posta")
    ps = sub.add_parser("posta-sposta")
    ps.add_argument("casella")
    ps.add_argument("mittente")
    ps.add_argument("categoria")
    ps.add_argument("--perche", required=True)
    sub.add_parser("posta-applica")

    pc = sub.add_parser("posta-conto")
    pc.add_argument("--rileggi", action="store_true")
    pn = sub.add_parser("posta-nuovo")
    pn.add_argument("casella")
    pn.add_argument("mittente")
    pn.add_argument("categoria")
    pn.add_argument("--perche", required=True)

    fi = sub.add_parser("firme")
    fi.add_argument("--rileggi", action="store_true")
    fe = sub.add_parser("firme-escludi")
    fe.add_argument("busta")
    fe.add_argument("titolo")
    fe.add_argument("--perche", required=True)
    fr = sub.add_parser("firme-riammetti")
    fr.add_argument("busta")


    sub.add_parser("pagine").add_argument("--rileggi", action="store_true")

    sub.add_parser("inspiration")
    re_ = sub.add_parser("regole")
    re_.add_argument(
        "--controlla", action="store_true", help="pre-commit guard, exits 1 if something is missing"
    )
    re_.add_argument(
        "--sabota",
        action="store_true",
        help="with --controlla, proves the planted faults are seen",
    )
    sub.add_parser("verifiche").add_argument("--quanti", type=int, default=150)
    ve = sub.add_parser("verifica")
    ve.add_argument("fonte")
    ve.add_argument("chiave")
    ve.add_argument("esito", choices=("si", "no"))
    ve.add_argument("emails", nargs="+")
    sub.add_parser("verifica-annulla")
    ce = sub.add_parser("cerca")
    ce.add_argument("domanda")
    ce.add_argument("--fonte", default=None)
    ce.add_argument("--dal", default=None)
    ce.add_argument("--quanti", type=int, default=12)
    args = ap.parse_args()

    if args.cmd == "stato":
        out = cmd_stato(args.fresco)
    elif args.cmd == "eta":
        out = cmd_eta()
    elif args.cmd == "aggiorna":
        out = cmd_aggiorna()
    elif args.cmd == "rollback":
        out = cmd_rollback(args.versione)
    elif args.cmd == "versioni":
        out = cmd_versioni()
    elif args.cmd == "scarica-fonte":
        out = cmd_scarica_fonte(args.fonte)
    elif args.cmd == "trascrivi-memo":
        out = cmd_trascrivi_memo()
    elif args.cmd == "ferma-fonte":
        out = cmd_ferma_fonte(args.run_id)
    elif args.cmd == "lancia":
        spesa = [s for s in args.spesa.split(",") if s] if args.spesa is not None else None
        out = cmd_lancia(args.tipo, args.arg, args.consenti_spesa, spesa)
    elif args.cmd == "pausa":
        out = cmd_pausa(args.run_id)
    elif args.cmd == "continua":
        out = cmd_continua(args.run_id)
    elif args.cmd == "ferma":
        out = cmd_ferma(args.run_id, args.forza)
    elif args.cmd == "run":
        out = cmd_run(args.run_id)
    elif args.cmd == "pulisci":
        out = cmd_pulisci(args.run_id)
    elif args.cmd == "log":
        out = cmd_log(args.run_id, args.righe)
    elif args.cmd == "pulisci-lock":
        out = cmd_pulisci_lock()
    elif args.cmd == "consenso-docusign":
        out = cmd_consenso_docusign()
    elif args.cmd == "impostazioni":
        out = cmd_impostazioni()
    elif args.cmd == "imposta":
        out = cmd_imposta(args.sezione, args.chiave, args.valore)
    elif args.cmd == "drive":
        out = cmd_drive()
    elif args.cmd == "strumenti":
        out = cmd_strumenti()
    elif args.cmd.startswith("posta"):
        import sb_posta

        if args.cmd == "posta":
            out = sb_posta.stato()
        elif args.cmd == "posta-sposta":
            out = sb_posta.sposta(args.casella, args.mittente, args.categoria, args.perche)
        elif args.cmd == "posta-conto":
            out = sb_posta.conto(rileggi=args.rileggi)
        elif args.cmd == "posta-nuovo":
            out = sb_posta.conferma_nuovo(args.casella, args.mittente, args.categoria, args.perche)
        else:
            out = sb_posta.applica()
    elif args.cmd.startswith("firme"):
        import sb_firme

        if args.cmd == "firme":
            out = sb_firme.stato(rileggi=args.rileggi)
        elif args.cmd == "firme-escludi":
            out = sb_firme.escludi(args.busta, args.titolo, args.perche)
        else:
            out = sb_firme.riammetti(args.busta)
    elif args.cmd == "pagine":
        import sb_pagine



        out = sb_pagine.per_app(args.rileggi)
    elif args.cmd == "inspiration":
        import sb_inspiration

        out = sb_inspiration.per_app()
    elif args.cmd == "regole" and args.controlla:
        return cmd_controlla_regole(args.sabota)
    elif args.cmd == "regole":
        out = cmd_regole()
    elif args.cmd == "cerca":
        out = cmd_cerca(args.domanda, args.fonte, args.dal, args.quanti)
    elif args.cmd == "verifiche":
        out = cmd_verifiche(args.quanti)
    elif args.cmd == "verifica":
        out = cmd_verifica(args.fonte, args.chiave, args.esito, args.emails)
    elif args.cmd == "verifica-annulla":
        out = cmd_verifica_annulla()
    else:
        out = cmd_stima(args.ultima)
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
