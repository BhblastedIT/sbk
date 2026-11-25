#!/usr/bin/env python3
"""Backup level of every file in the data root, and the rule that gives it."""




































from __future__ import annotations

import argparse
import json
import os
import re
import stat as st
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

HOME = Path.home()
DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", HOME / ".sbk-data"))
WORK = DATA_ROOT / "work"
STATO = DATA_ROOT / "state" / "backup"
REGISTRO_SORGENTI = Path(__file__).resolve().parents[1] / "sorgenti.py"

MIB = 2**20
GIB = 2**30
GIORNO = 86400
APERTO_GIORNI = 7
ROSSO_RADICE_ORE = 72

PROVVISORIA_L1 = 1 * GIB
PROVVISORIA_ROSSO = 10 * GIB


@dataclass(frozen=True)
class Esito:
    livello: int
    regola: str
    solo_usb: bool = False
    delicato: bool = False


    abbassabile: bool = False

    copia: bool = False



DIR_ESCLUSE = frozenset(
    {
        "node_modules",
        ".venv",
        ".next",
        ".turbo",
        "__pycache__",
        ".backup",
        "pgdata",
        "dist",
        "__MACOSX",
        "secrets",
    }
)
FILE_ESCLUSI = frozenset({".DS_Store"})
SUFFISSI_ESCLUSI = (".tmp", ".lock", ".parziale")




RADICI: dict[str, tuple[int | str, str, bool, bool]] = {

    "knowledge": (
        1,
        "the KB: paid facts and merge decisions, not reconstructible",
        False,
        False,
    ),
    "docs": (1, "delivered documents, local git without remote", False, False),
    "enriched": (1, "entity resolution decisions (including manual)", False, False),
    "rq": (
        1,
        "scoring choices and configs; events.db is derived but small",
        False,
        False,
    ),
    "l3": (
        "l3",
        "paid responses in nlp/ (L1), the rest derived (L2), vectordb excluded",
        False,
        False,
    ),
    "manual-ingestion": (1, "facts entered by hand", False, False),
    "meetings": (1, "summaries made with the API, redone only by paying again", False, False),
    "person-context": (1, "per-person context made with a model", False, False),
    "commitments": (1, "consolidation of commitments with a model", False, False),
    "system": (1, "API spend log", False, False),
    "jobs": (1, "job results", False, False),
    "archivio-drive": (
        1,
        "record of what is on the Drive: without it, the files cannot be found",
        False,
        False,
    ),
    "security": (1, "injections log", False, False),
    "chat-uploads": (1, "files uploaded by the user in the chat", False, False),
    "content": (1, "ideas and texts", False, False),
    "common": (1, "shared configs", False, False),
    "conversations": (1, "conversation indexes", False, False),
    "decisions": (1, "decisions", False, False),
    "signals": (1, "signals", False, False),
    "insights": (1, "analyses", False, False),
    "entity-triage": (1, "entity triage", False, False),
    "scripts": (1, "scripts outside git", False, False),
    "alerts": (1, "small history, regenerated only as it is today", False, False),
    "briefs": (1, "small history", False, False),
    "briefings": (1, "small history", False, False),
    "state": (1, "backup and follow-up state, project assignments", False, False),

    "whatsapp": (1, "export and database from the phone", True, False),
    "contacts": (1, "address book and media from the phone", True, False),
    "voice-memos": (1, "voice memos from the phone", True, False),
    "clinical": (
        1,
        "health data: encrypted and only on local disk",
        True,
        True,
    ),
    "legal": (1, "legal documents", True, False),
    "chatgpt": (1, "closed source, not re-downloadable", False, False),
    "manus": (1, "closed source", False, False),
    "linkedin": (1, "official export only", True, False),
    "attio": (1, "sole copy: recordings deleted in Attio exist only here", True, False),
    "slack": (1, "sole copy: free workspaces lose history beyond a year", True, False),
    "docusign": (1, "sole copy: envelopes the API does not return", True, False),
    "plaud": (1, "registries built here (voices, fingerprints), small", True, False),

    "email-pdfs": (1, "PDFs sorted by topic", False, False),
    "financial": (1, "indexes and analyses", True, False),
    "sbk-analyses": (1, "analyses", False, False),
    "backups": (1, "snapshots and inventories, small and unique", False, False),
    "video-analyses": (3, "analysis of a video", False, False),

    "gdrive": (
        2,
        "re-downloadable (but files deleted on the Drive after download remain only here)",
        False,
        False,
    ),
    "emails": (
        2,
        "re-downloadable (additive downloader: messages deleted on the server remain here)",
        True,
        False,
    ),
    "tactiq": (2, "re-downloadable, fragile access", True, False),
    "clickup": (2, "re-downloadable (deleted tasks remain here)", False, False),

    "attivita": (1, "the user's tasks, born here: not re-downloadable anywhere", True, False),
    "notion": (1, "closed source, not re-downloadable", False, False),
    "personio": (2, "re-downloadable (contains pay data)", True, False),
    "calendars": (2, "re-downloadable", False, False),
    "whoop": (2, "re-downloadable", True, False),
    "github": (2, "inventory", False, False),
    "gsc": (2, "inventory", False, False),
    "analytics": (2, "inventory", False, False),
    "anthropic": (2, "export from the console", False, False),
    "exports": (2, "L2 derivatives, free", False, False),
    "cross-source": (2, "derivatives, free", False, False),
    "inventory": (2, "derivatives", False, False),
    "l1-checkpoints": (2, "watermark: without it, the next run is full", False, False),

    "backups-compaction": (
        3,
        "KB tars before compaction, read by sb-kb-ripara",
        False,
        False,
    ),
    "backups-reanchor": (
        3,
        "KB tars before re-anchoring, read by sb-kb-ripara",
        False,
        False,
    ),
    "cache": (4, "convenience indexes, free", False, False),
    "logs": (4, "ephemeral", False, False),
    "events": (4, "ephemeral", False, False),
    "locks": (4, "lock", False, False),
    ".locks": (4, "lock", False, False),
    "runtime": (4, "lease", False, False),
    "tmp-ignore": (4, "temporary", False, False),
    "browser": (
        4,
        "browser sessions: redone with login, never off the machine",
        True,
        False,
    ),
    "apple-health": (1, "health data from the phone", True, False),
    "investments": (1, "investment documents", True, False),
    "noise-audit": (1, "noise audit", False, False),
    "work": ("work", "session work: rules per file", False, False),
}

RADICI_SCHEMA: list[tuple[re.Pattern, int, str]] = [
    (
        re.compile(r"^(l0-sweep|l0-update|full-refresh)-?.*$"),
        4,
        "logs and pids of old pipeline runs",
    ),
]

PROTETTI: dict[str, int] = {
    "knowledge": 1,
    "docs": 1,
    "whatsapp": 1,
    "clinical": 1,
    "legal": 1,
    "attio": 1,
    "slack": 1,
    "docusign": 1,
    "backups-compaction": 3,
    "backups-reanchor": 3,
}

FILE_RADICE_LOG = re.compile(r"\.log(\.\d+)?$")


COPIA_SICUREZZA = re.compile(r"\.bak($|[.\-_])|\.good-|\.pre-fix|\.partial-")

NOMI_DELICATI = re.compile(
    r"clinical|medic|legal|litig|financ|tax|identity|passport|whatsapp|slack|contacts|"
    r"browser|credential|secret|token|cookie",
    re.I,
)



TESTO = {".md", ".txt"}
CODICE = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".sh", ".sql"}
DATI = {".json", ".jsonl", ".tsv", ".csv", ".xml", ".eml", ".yaml", ".yml", ".toml", ".srt", ".vtt"}
UFFICIO = {
    ".docx",
    ".xlsx",
    ".pptx",
    ".doc",
    ".xls",
    ".ppt",
    ".key",
    ".numbers",
    ".pages",
    ".odt",
    ".ods",
}
MEDIA = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".avif",
    ".gif",
    ".heic",
    ".tif",
    ".tiff",
    ".psd",
    ".mp4",
    ".mov",
    ".webm",
    ".m4v",
    ".wav",
    ".m4a",
    ".mp3",
    ".opus",
    ".ogg",
    ".aac",
    ".flac",
    ".audio",
}
AUDIO_ORIG = {".audio", ".m4a", ".mp3", ".opus", ".ogg", ".aac", ".mp4", ".mov", ".webm"}
ARCHIVIO = {".zip", ".gz", ".tgz", ".tar", ".bundle", ".7z"}

SEG_RITORNO = re.compile(
    r"^(backup.*|snapshot.*|.*-prima(-.*)?|prima|pre-.*|foto-live|backup-live.*|copia-congelata|archivio|originali)$",
    re.I,
)
FILE_RITORNO = re.compile(r"(\.prima-|\.bak$|\.bak[-.]|live-backup|-prima\.)", re.I)
SEG_CONSEGNA = re.compile(
    r"^(deliverables?|consegna(-.*)?|finale?|final[-_].*|invio.*|pubblicato|rilascio|approvat[ei]|scelte)$",
    re.I,
)
SEG_GREZZO = re.compile(r"^(raw|grezz[oi]|_?scarti|tmp.*|scratch.*|cache|_l2|web2|pkg)$", re.I)
# work-folder segments; extend from user config if needed
SEG_LAVORO = re.compile(
    r"^(schermate|screenshots?|shots|scatti.*|gate|sweeps?|prove|.*-prove|test-results|playwright-report|e2e.*|trace.*|"
    r"round\d+|batch\d+|esiti.*|verifica|build|statico.*|_anteprime|anteprime|frames?|riprova.*|uscite|"
    r"consegne|lavoro|agents|teams|phase\d+|task\d+)$"
)
# folder/file naming for agent I/O; neutral defaults, override from user config
INPUT_OWNER_SEG = re.compile(r"^(owner-refs|from-owner|owner-input)$", re.I)
INPUT_OWNER_FILE = re.compile(
    r"(OWNER-ANSWERS|OWNER-DECISIONS|REQUEST|OWNER-INPUT)", re.I
)
SINTESI = re.compile(r"(SINTESI|RESOCONTO|ESITO|REPORT|STATO|RIEPILOGO|CONSEGNA|FOR-OWNER)", re.I)
PROFILO_BROWSER = {"Local State", "Cookies", "Login Data", "Preferences", "Web Data"}
SALVATAGGIO = re.compile(r"(scratchpad|bundle|backup|salvat|prima|rami)", re.I)
IMG_SEG = re.compile(
    r"^(immagini.*|images?|img|foto.*|lotto.*|jobs?|generazion.*|generat.*|gen-.*|approvat[ei]|scelte|render.*|varianti.*)$",
    re.I,
)
GENERATORE = re.compile(
    r"^(genera|lancia)[_-]?.*\.(py|sh|mjs|js)$|^(prompt\.txt|codex\.log|job\.json)$"
)
COPIA_REPO = {"package.json", "next.config.js", "next.config.mjs", "next.config.ts"}
# force offline-only backup for finance folders; extend via user config
FINANZE_PERSONALI = re.compile(r"(^|/)personal-finance(/|$)", re.I)


def _registro_place() -> dict:
    # No organization registry ships with the kit, so every work/<organization>/<project>
    # folder is treated as sensitive (the safe default of progetto_delicato).
    return {}


def progetto_delicato(org: str, progetto: str, reg: dict | None = None) -> bool:
    ""
    reg = reg if reg is not None else _registro_place()
    for o in reg.get("organizations", []):
        if o.get("slug") == org:
            return bool(o.get("sensitive")) or progetto in set(o.get("sensitive_projects", []))
    return True


def _leggi_marcatore(cartella: Path) -> dict | None:
    ""
    f = cartella / ".livello"
    try:
        righe = f.read_text().splitlines()
    except OSError:
        return None
    out = {}
    for r in righe:
        if ":" in r:
            k, v = r.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _prova_definitiva(cartella: Path, definitiva: str) -> bool:
    ""


    if not definitiva.strip():
        return False
    p = Path(definitiva).expanduser()
    candidati = [p] if p.is_absolute() else [DATA_ROOT / p, cartella / p]
    dentro = cartella.resolve()
    for c in candidati:
        try:
            c = c.resolve()
        except OSError:
            continue
        if c.exists() and c != dentro and dentro not in c.parents:
            return True
    return False


def _marcatore_valido(cartella: Path, m: dict, oggi: str) -> tuple[dict | None, str]:
    ""
    if m.get("livello", "") not in {"1", "2", "3", "4"}:
        return None, "marker without a level between 1 and 4: invalid"
    fino = m.get("fino-al", "")
    if fino and fino < oggi:
        return None, f"marker expired on {fino}: no longer valid"
    pronto = {
        **m,
        "livello": int(m["livello"]),
        "_prova": _prova_definitiva(cartella, m.get("definitiva-in", "")),
    }
    return pronto, "marker for the level"


def _applica_marcatore(es: Esito, m: dict) -> Esito:
    ""



    voluto, motivo = m["livello"], m.get("motivo", "")
    if voluto < es.livello:
        return replace(es, livello=voluto, regola=f"{es.regola}; raised by the marker: {motivo}")
    if voluto == es.livello:
        return es
    ok_owner = bool(m.get("ok-owner", "").strip())
    if not (es.abbassabile or ok_owner):
        return replace(es, regola=f"{es.regola}; the marker does not lower it without ok-owner")
    liv = voluto
    if liv == 4 and ((es.delicato and not ok_owner) or not m.get("_prova")):
        liv = 3
    if liv <= es.livello:
        return replace(
            es, regola=f"{es.regola}; the marker asks for {voluto} but the proof or owner's ok is missing"
        )
    return replace(es, livello=liv, regola=f"marker .livello: {motivo}")


@dataclass
class _Contesto:
    ""

    delicato: bool = False
    solo_usb_forzato: bool = False
    aperto: bool = True
    sintesi: bool = False
    copia_repo: bool = False
    repo_unico: bool = False
    profilo: bool = False
    generata: bool = False
    cartella_immagini_gen: bool = False
    marcatore: dict | None = None

    minimo: int | None = None
    destinazioni: str | None = None
    motivo_progetto: str = ""


def _info_dossier(dossier: Path, ora: float) -> tuple[bool, bool]:
    ""
    try:
        nomi = os.listdir(dossier)
    except OSError:
        return True, False
    sintesi = any(
        SINTESI.search(n) for n in nomi if n.lower().endswith((".md", ".txt", ".html", ".pdf"))
    )
    ultimo = 0.0
    for dp, dn, fn in os.walk(dossier):
        dn[:] = [d for d in dn if d not in DIR_ESCLUSE]
        for f in fn[:200]:
            try:
                ultimo = max(ultimo, os.lstat(os.path.join(dp, f)).st_mtime)
            except OSError:
                continue
        if ora - ultimo < APERTO_GIORNI * GIORNO:
            return True, sintesi
    return (ora - ultimo) < APERTO_GIORNI * GIORNO, sintesi


def _repo_senza_remoto(cartella: str) -> bool:
    cfg = Path(cartella) / ".git" / "config"
    try:
        if not cfg.is_file() or "[remote " in cfg.read_text(errors="ignore"):
            return False
    except OSError:
        return False
    import subprocess

    try:
        n = subprocess.run(
            ["git", "-C", cartella, "rev-list", "--all", "--count"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        return int(n or 0) >= 5
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def classifica_work(rel: str, size: int, nome: str, fratelli: set[str], ctx: _Contesto) -> Esito:
    ""
    es = _regole_work(rel, size, nome, fratelli, ctx)
    if ctx.profilo or es.copia:


        return es
    if ctx.marcatore:
        es = _applica_marcatore(es, ctx.marcatore)
    if ctx.minimo is not None and es.livello > ctx.minimo:
        es = replace(
            es,
            livello=ctx.minimo,
            regola=f"{es.regola}; alzato dal progetto: {ctx.motivo_progetto}",
        )
    if ctx.destinazioni == "tutte" and es.solo_usb and not ctx.solo_usb_forzato:
        regola = es.regola.replace(": disk only", "")
        es = replace(
            es, regola=f"{regola}; to all destinations for the project", solo_usb=False
        )
    elif ctx.destinazioni == "usb" and not es.solo_usb:
        es = replace(es, regola=f"{es.regola}; disk only for the project", solo_usb=True)
    return es


def _regole_work(rel: str, size: int, nome: str, fratelli: set[str], ctx: _Contesto) -> Esito:
    ""



    segs = rel.split("/")[:-1]
    ext = os.path.splitext(nome)[1].lower()
    deli = ctx.delicato

    def e(
        liv: int, regola: str, usb: bool = False, abbassabile: bool = False, copia: bool = False
    ) -> Esito:
        return Esito(
            liv,
            regola,
            solo_usb=usb or ctx.solo_usb_forzato,
            delicato=deli,
            abbassabile=abbassabile,
            copia=copia,
        )

    if ctx.profilo:
        return e(4, "browser session: redone with login, never off the Mac")
    if ctx.repo_unico:
        if size > 50 * MIB and ".git" not in segs:
            return e(3, "large file in a repo without remote")
        return e(1, "git repo without remote: unique code")
    if "congelate" in segs and size <= 5 * MIB:
        return e(1, "frozen delivery from an agent")
    if any(INPUT_OWNER_SEG.match(x) for x in segs) or INPUT_OWNER_FILE.search(nome):
        return e(1 if size <= 100 * MIB else 3, "owner input or decision")
    if any(SEG_RITORNO.match(x) for x in segs) or FILE_RITORNO.search(nome):
        if ctx.aperto:
            return e(1, "rollback point of an open dossier (prior state)")
        return e(3, "rollback point (prior state)")
    if ctx.copia_repo:

        return e(
            3,
            "repo copy: disk only until a marker declares it a copy",
            usb=True,
            abbassabile=True,
        )
    if ctx.generata and ext in MEDIA:
        return e(3, "generated media (generator alongside)")
    if ext == ".wav" and any(os.path.splitext(nome)[0] + x in fratelli for x in AUDIO_ORIG):
        return e(4, "decoded audio: the original is alongside", copia=True)
    grezzo = any(SEG_GREZZO.match(x) for x in segs)
    if not grezzo:
        if ext in TESTO and size <= 2 * MIB:
            return e(1, "dossier text")
        if ext in CODICE and size <= MIB:
            return e(1, "code written for the dossier")
        if ext in DATI and size <= 5 * MIB and not segs:
            return e(1, "log or table at the dossier root")
    lavoro = grezzo or any(SEG_LAVORO.match(x) for x in segs)
    consegna = any(SEG_CONSEGNA.match(x) for x in segs)
    if ext in UFFICIO and size <= 50 * MIB and (consegna or not lavoro):
        return e(1, "office document")
    if ext in ARCHIVIO and SALVATAGGIO.search(nome):
        return e(3, "archive set aside", abbassabile=True)
    if consegna:
        return e(3, "delivery", abbassabile=True)
    if lavoro:


        if deli:
            motivo = "work on a sensitive project: disk only"
        elif ctx.aperto:
            motivo = "work on an open dossier: disk only"
        elif not ctx.sintesi:
            motivo = "work on a dossier without a summary: disk only"
        else:
            motivo = "work on a closed dossier without a marker: disk only"
        return e(3, motivo, usb=True, abbassabile=True)
    return e(3, "unrecognized: kept", abbassabile=True)


def livello_radice(nome: str) -> tuple[int | str, str, bool, bool] | None:
    if nome in RADICI:
        return RADICI[nome]
    for rx, liv, motivo in RADICI_SCHEMA:
        if rx.match(nome):
            return (liv, motivo, False, False)
    return None


def _esito_radice(nome: str, rel_in_radice: str) -> Esito | None:
    ""
    r = livello_radice(nome)
    if r is None:
        return None
    liv, motivo, deli, usb = r
    if liv == "l3":
        if rel_in_radice.startswith(("vectordb/", "logs/")):
            return Esito(4, "l3: vector index or log, reconstructible")
        if rel_in_radice.startswith("nlp/"):
            if FILE_RADICE_LOG.search(rel_in_radice):
                return Esito(4, "log")
            if COPIA_SICUREZZA.search(os.path.basename(rel_in_radice)):
                return Esito(3, "backup of the paid responses")
            return Esito(1, "paid responses of the extraction")
        return Esito(2, "l3 derivative")
    assert isinstance(liv, int)
    if FILE_RADICE_LOG.search(rel_in_radice) and liv < 4:
        return Esito(4, "log", solo_usb=usb, delicato=deli)
    if COPIA_SICUREZZA.search(os.path.basename(rel_in_radice)) and liv < 3:
        return Esito(3, f"backup ({motivo})", solo_usb=usb, delicato=deli)
    return Esito(liv, motivo, solo_usb=usb, delicato=deli)


def _come_link(es: Esito) -> Esito:
    ""
    return replace(es, regola=f"symbolic link ({es.regola}): recorded, not followed")


def _albero(
    radice: str, escludi: frozenset[str] = frozenset()
) -> Iterator[tuple[str, os.stat_result]]:
    ""
    for dp, dn, fn in os.walk(radice, followlinks=False):
        tieni = []
        for d in sorted(dn):
            if d in DIR_ESCLUSE or d in escludi:
                continue
            p = os.path.join(dp, d)
            if os.path.islink(p):
                try:
                    yield p, os.lstat(p)
                except OSError:
                    pass
            else:
                tieni.append(d)
        dn[:] = tieni
        for f in sorted(fn):
            if f in FILE_ESCLUSI or f.endswith(SUFFISSI_ESCLUSI):
                continue
            p = os.path.join(dp, f)
            try:
                s = os.lstat(p)
            except OSError:
                continue
            if st.S_ISREG(s.st_mode) or st.S_ISLNK(s.st_mode):
                yield p, s


def _peso(path: str, tetto: int | None = None) -> int:
    ""
    tetto = tetto or PROVVISORIA_ROSSO
    tot = 0
    for _p, s in _albero(path):
        if st.S_ISREG(s.st_mode):
            tot += s.st_size
            if tot > tetto:
                break
    return tot


def _esito_provvisorio(peso: int) -> Esito:

    if peso <= PROVVISORIA_L1:
        return Esito(
            1, "new root without a level: provisional in L1 (up to 1 GiB)", delicato=True
        )
    return Esito(2, "new root without a level over 1 GiB: provisional in L2", delicato=True)


def _cammina_radice(nome: str, path: str) -> Iterator[tuple[Path, int, Esito]]:
    ""
    provvisorio = _esito_provvisorio(_peso(path)) if livello_radice(nome) is None else None
    for p, s in _albero(path):
        es = provvisorio or _esito_radice(nome, os.path.relpath(p, path))
        assert es is not None
        if st.S_ISLNK(s.st_mode):
            yield Path(p), 0, _come_link(es)
        else:
            yield Path(p), s.st_size, es


def cammina(
    base: Path | None = None, ora: float | None = None
) -> Iterator[tuple[Path, int, Esito]]:
    ""
    base = base or DATA_ROOT
    ora = ora or time.time()
    reg = _registro_place()
    progetti = _assegnazioni_progetti(base)
    try:
        voci = sorted(os.listdir(base))
    except OSError:
        return
    for nome in voci:
        yield from _voce_radice(base / nome, ora, reg, progetti)


def _voce_radice(
    p: Path, ora: float, reg: dict, progetti: dict, solo: tuple[str, ...] = ()
) -> Iterator[tuple[Path, int, Esito]]:
    ""
    if p.is_symlink():
        yield p, 0, _come_link(Esito(1, "entry at root"))
    elif p.is_file():
        if p.name in FILE_ESCLUSI or p.name.endswith(SUFFISSI_ESCLUSI):
            return
        if FILE_RADICE_LOG.search(p.name):
            es = Esito(4, "log")
        elif COPIA_SICUREZZA.search(p.name):
            es = Esito(3, "backup of a file at root")
        else:
            es = Esito(1, "file at root")
        yield p, p.stat().st_size, es
    elif p.is_dir() and p.name not in DIR_ESCLUSE:
        if p.name == "work":
            yield from _cammina_work(p, ora, reg, progetti, solo)
        else:
            yield from _cammina_radice(p.name, str(p))


def _contesto_progetto(org: str, prog: str, reg: dict, progetti: dict) -> _Contesto:
    ""
    ctx = _Contesto(
        delicato=progetto_delicato(org, prog, reg) or bool(NOMI_DELICATI.search(f"{org}/{prog}")),
        solo_usb_forzato=bool(FINANZE_PERSONALI.match(f"{org}/{prog}")),
    )
    assegnato = progetti.get(f"{org}/{prog}") or {}
    if "minimo" in assegnato:
        ctx.minimo = int(assegnato["minimo"])
    ctx.destinazioni = assegnato.get("destinazioni")
    ctx.motivo_progetto = assegnato.get("perche", "")
    return ctx


def _contesto_dossier(ctx_progetto: _Contesto, dossier: Path, ora: float) -> _Contesto:
    aperto, sintesi = _info_dossier(dossier, ora)
    delicato = ctx_progetto.delicato or bool(NOMI_DELICATI.search(dossier.name))
    return replace(ctx_progetto, aperto=aperto, sintesi=sintesi, delicato=delicato)


def _nomi(cartella: Path, solo: tuple[str, ...], i: int) -> list[str]:
    ""
    if len(solo) > i:
        p = cartella / solo[i]
        return [solo[i]] if p.exists() or p.is_symlink() else []
    try:
        return sorted(os.listdir(cartella))
    except OSError:
        return []


def _cammina_work(
    work: Path, ora: float, reg: dict, progetti: dict, solo: tuple[str, ...] = ()
) -> Iterator[tuple[Path, int, Esito]]:
    ""
    for org in _nomi(work, solo, 0):
        po = work / org
        if po.is_symlink() or not po.is_dir():
            yield from _fuori_dossier(po, _Contesto(delicato=True), ora)
            continue
        for prog in _nomi(po, solo, 1):
            pp = po / prog
            if pp.is_symlink() or not pp.is_dir():
                ctx_org = _Contesto(
                    delicato=progetto_delicato(org, "", reg) or bool(NOMI_DELICATI.search(org))
                )
                yield from _fuori_dossier(pp, ctx_org, ora)
                continue
            ctx_prog = _contesto_progetto(org, prog, reg, progetti)
            for dossier in _nomi(pp, solo, 2):
                pd = pp / dossier
                if pd.is_symlink() or not pd.is_dir():
                    yield from _fuori_dossier(pd, ctx_prog, ora)
                    continue
                yield from _cammina_dossier(pd, _contesto_dossier(ctx_prog, pd, ora), ora)


def _fuori_dossier(p: Path, ctx: _Contesto, ora: float) -> Iterator[tuple[Path, int, Esito]]:
    ""
    if p.name in FILE_ESCLUSI or p.name.endswith(SUFFISSI_ESCLUSI):
        return
    try:
        s = p.lstat()
    except OSError:
        return
    c = replace(ctx, aperto=ora - s.st_mtime < APERTO_GIORNI * GIORNO, sintesi=False)
    if st.S_ISLNK(s.st_mode):
        yield p, 0, _come_link(classifica_work(p.name, 0, p.name, set(), c))
    elif st.S_ISREG(s.st_mode):
        yield p, s.st_size, classifica_work(p.name, s.st_size, p.name, set(), c)


def _cammina_dossier(
    dossier: Path, ctx0: _Contesto, ora: float
) -> Iterator[tuple[Path, int, Esito]]:
    oggi = time.strftime("%Y-%m-%d", time.localtime(ora))
    contesti: dict[str, _Contesto] = {str(dossier): ctx0}
    for dp, dn, fn in os.walk(dossier, followlinks=False):
        ctx = contesti.pop(dp, None) or ctx0
        collegate = [d for d in dn if os.path.islink(os.path.join(dp, d))]
        dn[:] = [d for d in sorted(dn) if d not in DIR_ESCLUSE and d not in collegate]
        nomi = set(fn)

        stato_marcatore = ""
        if ".livello" in nomi:
            m = _leggi_marcatore(Path(dp))
            if m is not None:
                pronto, stato_marcatore = _marcatore_valido(Path(dp), m, oggi)
                if pronto:
                    ctx = replace(ctx, marcatore=pronto)
        copia_qui = bool(nomi & COPIA_REPO) or ".git" in dn or ".git" in nomi
        repo_unico = ctx.repo_unico or (copia_qui and _repo_senza_remoto(dp))
        profilo = (
            ctx.profilo
            or len(nomi & PROFILO_BROWSER) >= 2
            or ("Default" in dn and "Local State" in nomi)
        )
        gen_qui = any(GENERATORE.match(x) for x in nomi)
        seg = os.path.basename(dp)
        generata = (
            gen_qui or ctx.cartella_immagini_gen or (ctx.generata and bool(IMG_SEG.match(seg)))
        )
        ctx_qui = replace(
            ctx,
            copia_repo=ctx.copia_repo or (copia_qui and not repo_unico),
            repo_unico=repo_unico,
            profilo=profilo,
            generata=generata,
            cartella_immagini_gen=generata and (not gen_qui or bool(IMG_SEG.match(seg))),
        )
        for d in dn:
            contesti[os.path.join(dp, d)] = ctx_qui
        rel_dir = os.path.relpath(dp, dossier)
        rel_dir = "" if rel_dir == "." else rel_dir
        for d in collegate:
            if d in DIR_ESCLUSE:
                continue
            rel = (rel_dir + "/" if rel_dir else "") + d
            yield Path(dp, d), 0, _come_link(classifica_work(rel, 0, d, nomi, ctx_qui))
        for f in sorted(fn):
            if f in FILE_ESCLUSI or f.endswith(SUFFISSI_ESCLUSI):
                continue
            p = os.path.join(dp, f)
            try:
                s = os.lstat(p)
            except OSError:
                continue
            if f == ".livello":

                yield (
                    Path(p),
                    s.st_size,
                    Esito(1, stato_marcatore or "marker for the level", delicato=ctx.delicato),
                )
                continue
            rel = (rel_dir + "/" if rel_dir else "") + f
            if st.S_ISLNK(s.st_mode):
                yield Path(p), 0, _come_link(classifica_work(rel, 0, f, nomi, ctx_qui))
            elif st.S_ISREG(s.st_mode):
                yield Path(p), s.st_size, classifica_work(rel, s.st_size, f, nomi, ctx_qui)


def _assegnazioni_progetti(base: Path | None = None) -> dict:
    ""
    try:
        return json.loads(((base or DATA_ROOT) / "state" / "backup" / "progetti.json").read_text())
    except (OSError, ValueError):
        return {}



@dataclass(frozen=True)
class Fuori:
    ""

    nome: str
    base: Path
    livello: int
    motivo: str
    delicato: bool = False
    solo_usb: bool = False

    file: tuple[str, ...] = ()

    cartelle: tuple[str, ...] = ()

    escludi: frozenset[str] = frozenset()

    recenti_giorni: int | None = None


PROGETTO_CLAUDE = HOME / ".claude" / "projects" / "-Users-you-Projects-SBK"
SUBAGENTI_GIORNI = 60
FUORI: list[Fuori] = [
    Fuori(
        "memoria-claude",
        PROGETTO_CLAUDE / "memory",
        1,
        "Claude's persistent memory",
        delicato=True,
        cartelle=(".",),
    ),
    Fuori(
        "sessioni-claude",
        PROGETTO_CLAUDE,
        1,
        "main sessions: the history of decisions",
        delicato=True,
        file=("*.jsonl", "*/custom-title.json"),
    ),
    Fuori(
        "workflow-claude",
        PROGETTO_CLAUDE,
        1,
        "scripts and state of the sessions' workflows",
        delicato=True,
        cartelle=("*/workflows",),
    ),
    Fuori(
        "subagenti-claude",
        PROGETTO_CLAUDE,
        3,
        "transcripts of sub-agents and workflows with the .meta.json, last 60 days",
        delicato=True,
        solo_usb=True,
        cartelle=("*/subagents",),
        recenti_giorni=SUBAGENTI_GIORNI,
    ),
    Fuori(
        "risultati-strumenti",
        PROGETTO_CLAUDE,
        3,
        "long tool outputs the transcripts point to, last 60 days",
        delicato=True,
        solo_usb=True,
        cartelle=("*/tool-results",),
        recenti_giorni=SUBAGENTI_GIORNI,
    ),
    Fuori(
        "regole-claude",
        HOME / ".claude",
        1,
        "rules, settings, hooks, personal skills and Claude's status line",
        file=("CLAUDE.md", "settings.json", "keybindings.json", "status-line.sh"),
        cartelle=("hooks", "skills"),

        escludi=frozenset({".trash", "synced"}),
    ),
    Fuori(
        "prompt-claude",
        HOME / ".claude",
        1,
        "the prompts written by the user in all sessions",
        delicato=True,
        file=("history.jsonl",),
    ),
    Fuori(
        "storia-file-claude",
        HOME / ".claude" / "file-history",
        3,
        "prior versions of files changed by the sessions, last 60 days",
        delicato=True,
        solo_usb=True,
        cartelle=(".",),
        recenti_giorni=SUBAGENTI_GIORNI,
    ),
    Fuori(
        "vault",
        HOME / ".sbk-credentials",
        1,
        "credentials: encrypted, never in clear",
        delicato=True,
        cartelle=(".",),
    ),
    Fuori(
        "repo-sbk",
        HOME / "Projects" / "SBK" / "sbk",
        1,
        "repo context (live-state, errors, identity)",
        cartelle=(".",),
    ),
    Fuori(
        "tar-kb",
        HOME / ".sbk-backups",
        3,
        "KB tars before large operations, read by sb-kb-ripara",
        cartelle=(".",),
    ),
    Fuori(
        "tracciabilita",
        HOME / "Backups" / "sbk-safety",
        3,
        "sole witness of the fact files",
        cartelle=(".",),
    ),
    Fuori(
        "downloads",
        HOME / "Downloads",
        3,
        "personal documents that are nowhere else",
        delicato=True,
        solo_usb=True,
        cartelle=(".",),
    ),
]

SENZA_NOMI = {"vault"}


def _uno_fuori(
    f: Fuori, p: str, es: Esito, ora: float, s: os.stat_result | None = None
) -> Iterator[tuple[str, Path, int, Esito]]:
    if s is None:
        if os.path.basename(p) in FILE_ESCLUSI:
            return
        try:
            s = os.lstat(p)
        except OSError:
            return
    if f.recenti_giorni is not None and ora - s.st_mtime > f.recenti_giorni * GIORNO:
        return
    if st.S_ISLNK(s.st_mode):
        yield f.nome, Path(p), 0, _come_link(es)
    elif st.S_ISREG(s.st_mode):
        yield f.nome, Path(p), s.st_size, es


def cammina_fuori(
    ora: float | None = None, fonti: list[Fuori] | None = None
) -> Iterator[tuple[str, Path, int, Esito]]:
    ""
    ora = ora or time.time()
    for f in FUORI if fonti is None else fonti:
        if not f.base.is_dir():
            continue
        es = Esito(f.livello, f.motivo, solo_usb=f.solo_usb, delicato=f.delicato)
        for pat in f.file:
            for p in sorted(f.base.glob(pat)):
                yield from _uno_fuori(f, str(p), es, ora)
        for pat in f.cartelle:
            for r in [f.base] if pat == "." else sorted(f.base.glob(pat)):
                if r.is_symlink() or not r.is_dir():
                    continue
                for p, s in _albero(str(r), f.escludi):
                    yield from _uno_fuori(f, p, es, ora, s)



def _sorgenti_chiuse() -> list[str] | None:
    ""
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("_sorgenti_livelli", REGISTRO_SORGENTI)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_sorgenti_livelli"] = mod
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - the guardian must not fall over a broken registry: it says so in yellow
        return None
    finally:
        sys.modules.pop("_sorgenti_livelli", None)
    ids = []
    for nome in dir(mod):
        val = getattr(mod, nome)
        if isinstance(val, list):
            ids += [x.id for x in val if getattr(x, "natura", "") == "chiusa" and hasattr(x, "id")]
    return sorted(set(ids))


def _radici_della_sorgente(sid: str) -> list[str]:
    nomi = {sid, sid + "s", sid.replace("_", "-"), sid.replace("_", "-") + "s"}
    return sorted(n for n in nomi if n in RADICI)


def controlla(base: Path | None = None, ora: float | None = None) -> tuple[list[str], list[str]]:
    ""
    base = base or DATA_ROOT
    ora = ora or time.time()
    rossi: list[str] = []
    gialli: list[str] = []
    for nome, minimo in PROTETTI.items():
        r = livello_radice(nome)
        if r is None:
            rossi.append(f"protected {nome} without a row in the registry")
        elif isinstance(r[0], int) and r[0] > minimo:
            rossi.append(f"protected {nome} at level {r[0]}, below its minimum {minimo}")
    for nome, (liv, motivo, _d, _u) in RADICI.items():
        if liv not in (1, 2, 3, 4, "work", "l3"):
            rossi.append(f"{nome}: nonexistent level {liv!r}")
        if liv == 4 and not motivo.strip():
            rossi.append(f"{nome}: excluded without a reason")
    for f in FUORI:
        if f.livello not in (1, 2, 3, 4) or not f.motivo.strip():
            rossi.append(f"external source {f.nome}: level {f.livello!r} or reason missing")
    chiuse = _sorgenti_chiuse()
    if chiuse is None:
        gialli.append(
            f"sources registry unreadable ({REGISTRO_SORGENTI}): closed ones not checked"
        )
    else:
        for sid in chiuse:
            for nome in _radici_della_sorgente(sid):
                liv = RADICI[nome][0]
                if liv != 1:
                    rossi.append(
                        f"closed source {sid}: root {nome} is at level {liv}, a closed one belongs in L1"
                    )
    rossi_p, gialli_p = _controlla_assegnazioni(base)
    rossi += rossi_p
    gialli += gialli_p
    if not base.exists():
        gialli.append(f"{base} does not exist on this machine: check skipped")
        return rossi, gialli
    try:
        voci = [v for v in os.scandir(base) if v.is_dir() and not v.is_symlink()]
    except OSError as e:
        return rossi + [f"{base} cannot be read: {e}"], gialli
    for v in voci:
        if v.name in DIR_ESCLUSE or livello_radice(v.name) is not None:
            continue
        try:
            nata = v.stat().st_birthtime
        except (OSError, AttributeError):
            nata = v.stat().st_ctime
        ore = (ora - nata) / 3600
        peso = _peso(v.path)
        es = _esito_provvisorio(peso)
        if peso > PROVVISORIA_ROSSO:
            rossi.append(
                f"new folder without a level over {PROVVISORIA_ROSSO // GIB} GiB: {v.name} (meanwhile L{es.livello})"
            )
            continue
        msg = f"new folder without a level: {v.name} (born {ore:.0f} hours ago, {peso / GIB:.1f} GiB, meanwhile L{es.livello} provisional)"
        (rossi if ore > ROSSO_RADICE_ORE else gialli).append(msg)
    return rossi, gialli


def _controlla_assegnazioni(base: Path) -> tuple[list[str], list[str]]:
    ""
    f = base / "state" / "backup" / "progetti.json"
    if not f.exists():
        return [], []
    try:
        progetti = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        return [f"project assignments unreadable ({f}): {e}"], []
    rossi, gialli = [], []
    for chiave, a in progetti.items():
        if not isinstance(a, dict):
            rossi.append(f"assignment {chiave}: not an object")
            continue
        if "minimo" in a and a["minimo"] not in (1, 2, 3):
            rossi.append(f"assignment {chiave}: floor {a['minimo']!r}, must be 1 to 3")
        if a.get("destinazioni") not in (None, "tutte", "usb"):
            rossi.append(f"assignment {chiave}: destinations {a['destinazioni']!r} (tutte or usb)")
        if not str(a.get("perche", "")).strip():
            rossi.append(f"assignment {chiave}: without a reason")
        if not (base / "work" / chiave).is_dir():
            gialli.append(f"assignment {chiave}: the project is not in work/")
    return rossi, gialli


def sabota() -> bool:
    ""


    import tempfile

    presi: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "knowledge").mkdir()
        rossi, _ = controlla(base)
        presi.append(("clean with no reds", not rossi))
        nuova = base / "cartella-nuova"
        nuova.mkdir()
        r_vecchia, _g = controlla(base, ora=time.time() + 100 * 3600)
        presi.append(
            ("old new-root in red", any("cartella-nuova" in x for x in r_vecchia))
        )
        r_appena, g_appena = controlla(base)
        presi.append(
            (
                "freshly-born new-root in yellow",
                not any("cartella-nuova" in x for x in r_appena)
                and any("cartella-nuova" in x for x in g_appena),
            )
        )
        (base / "state" / "backup").mkdir(parents=True)
        (base / "state" / "backup" / "progetti.json").write_text(
            json.dumps({"x/y": {"minimo": 4, "perche": "test"}})
        )
        presi.append(("floor 4 in red", any("x/y" in x for x in controlla(base)[0])))
    salvo = dict(RADICI)
    try:
        RADICI["attio"] = (4, "moved by mistake", True, False)
        presi.append(("protected lowered", any("attio" in x for x in controlla()[0])))
        RADICI["attio"] = salvo["attio"]
        RADICI["finta"] = (7, "nonexistent level", False, False)
        presi.append(("nonexistent level", any("finta" in x for x in controlla()[0])))
        del RADICI["finta"]
        RADICI["finta4"] = (4, " ", False, False)
        presi.append(("excluded without a reason", any("finta4" in x for x in controlla()[0])))
        del RADICI["finta4"]
        RADICI["chatgpt"] = (2, "closed lowered by mistake", False, False)
        presi.append(("closed one outside L1", any("chatgpt" in x for x in controlla()[0])))
    finally:
        RADICI.clear()
        RADICI.update(salvo)

    wa = _esito_radice("whatsapp", "x/chat.db")
    presi.append(
        ("whatsapp sensitive and also on the Drive", bool(wa and wa.delicato and not wa.solo_usb))
    )
    cl = _esito_radice("clinical", "x.pdf")
    presi.append(("clinical disk only", bool(cl and cl.solo_usb)))

    ctx = _Contesto(aperto=False, sintesi=True)
    presi.append(
        (
            "user input never at 4",
            classifica_work("fase2/owner-refs/foto.png", 10, "foto.png", set(), ctx).livello
            < 4,
        )
    )
    presi.append(
        (
            "rollback point never at 4",
            classifica_work("fase4/TL2/backup-live-01-01/x.json", 10, "x.json", set(), ctx).livello
            < 4,
        )
    )
    presi.append(
        (
            "unrecognized never at 4",
            classifica_work(
                "teams/A1/strano.bin", 10, "strano.bin", set(), _Contesto(aperto=True)
            ).livello
            < 4,
        )
    )

    senza_prova = {"livello": 4, "motivo": "test", "_prova": False}
    con_prova = {"livello": 4, "motivo": "test", "_prova": True}
    lav = "verifica/x.png"
    presi.append(
        (
            "marker without proof",
            classifica_work(lav, 10, "x.png", set(), replace(ctx, marcatore=senza_prova)).livello
            == 3,
        )
    )
    presi.append(
        (
            "marker with proof",
            classifica_work(lav, 10, "x.png", set(), replace(ctx, marcatore=con_prova)).livello
            == 4,
        )
    )
    presi.append(
        (
            "marker and user input",
            classifica_work(
                "owner-refs/x.png", 10, "x.png", set(), replace(ctx, marcatore=con_prova)
            ).livello
            == 1,
        )
    )
    presi.append(
        (
            "marker and sensitive",
            classifica_work(
                lav, 10, "x.png", set(), replace(ctx, delicato=True, marcatore=con_prova)
            ).livello
            == 3,
        )
    )
    presi.append(("empty final is not a proof", not _prova_definitiva(Path("/"), "")))

    browser = replace(ctx, profilo=True, minimo=3, destinazioni="tutte")
    presi.append(
        (
            "browser outside even with the floor",
            classifica_work("p/Cookies", 10, "Cookies", set(), browser).livello == 4,
        )
    )
    mancati = [nome for nome, ok in presi if not ok]
    for nome in mancati:
        print(f"   fault not seen: {nome}")
    return not mancati



def collaudo(base: Path | None = None) -> tuple[int, list[str]]:
    ""
    base = base or DATA_ROOT
    f = base / "state" / "backup" / "collaudo.json"
    try:
        casi = json.loads(f.read_text())["casi"]
    except (OSError, ValueError, KeyError):
        return 0, [f"list of cases missing: {f}"]
    errori = []
    controllati = 0
    for caso in casi:
        cartella = base / "work" / caso["percorso"]
        if not cartella.exists():
            errori.append(f"case vanished from disk: {caso['percorso']}")
            continue
        controllati += 1
        quattro = [
            str(p)
            for p, _s, e in cammina_cartella(cartella, base)
            if e.livello >= 4 and _conta_nel_caso(p, caso)
        ]
        if quattro:
            errori.append(f"{caso['percorso']}: {len(quattro)} files at level 4, e.g. {quattro[0]}")
    return controllati, errori


def _conta_nel_caso(p: Path, caso: dict) -> bool:
    filtro = caso.get("solo_estensioni")
    return not filtro or p.suffix.lower() in filtro


def _dentro(p: Path, cartella: Path) -> bool:
    return p == cartella or str(p).startswith(str(cartella).rstrip(os.sep) + os.sep)


def cammina_cartella(cartella: Path, base: Path | None = None) -> Iterator[tuple[Path, int, Esito]]:
    ""


    base = base or DATA_ROOT
    ora = time.time()
    voluta = Path(os.path.abspath(cartella.expanduser()))
    try:
        rel = voluta.resolve().relative_to(base.resolve())
    except ValueError:
        for _n, p, s, e in cammina_fuori(ora):
            if _dentro(p, voluta):
                yield p, s, e
        return
    if not rel.parts:
        yield from cammina(base, ora)
        return
    dentro = base / rel
    solo = rel.parts[1:4] if rel.parts[0] == "work" else ()
    for p, s, e in _voce_radice(
        base / rel.parts[0], ora, _registro_place(), _assegnazioni_progetti(base), solo
    ):
        if _dentro(p, dentro):
            yield p, s, e


def esito_di(percorso: Path) -> Esito | None:
    ""


    voluto = Path(os.path.abspath(percorso.expanduser()))
    for p, _s, e in cammina_cartella(voluto):
        if p == voluto:
            return e
    return None


def elenco(
    livello: int, destinazione: str, ora: float | None = None
) -> Iterator[tuple[str, Path, int, Esito]]:
    ""


    if destinazione not in ("disco", "drive"):
        raise ValueError(f"destination {destinazione!r}: disco or drive")
    ora = ora or time.time()
    for p, s, e in cammina(DATA_ROOT, ora):
        if e.livello == livello and not (destinazione == "drive" and e.solo_usb):
            yield "sbk-data", p, s, e
    for nome, p, s, e in cammina_fuori(ora):
        if e.livello == livello and not (destinazione == "drive" and e.solo_usb):
            yield nome, p, s, e


def assegna(progetto: str, minimo: int | None, destinazioni: str | None, perche: str) -> dict:
    ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*", progetto):
        raise ValueError(
            f"project {progetto!r}: needs <organization>/<project>, a folder under work/"
        )
    if not (WORK / progetto).is_dir():
        raise ValueError(f"{WORK / progetto} does not exist")
    if minimo is not None and minimo not in (1, 2, 3):
        raise ValueError("the floor is 1 to 3 (there is no floor at 4)")
    if destinazioni not in (None, "tutte", "usb"):
        raise ValueError("destinations: tutte or usb")
    if not perche.strip():
        raise ValueError("a reason is required, in one sentence")
    progetti = _assegnazioni_progetti(STATO.parent.parent)
    voce = dict(progetti.get(progetto, {}))
    if minimo is not None:
        voce["minimo"] = minimo
    if destinazioni is not None:
        voce["destinazioni"] = destinazioni
    voce["perche"] = perche.strip()
    voce["data"] = time.strftime("%Y-%m-%d")
    progetti[progetto] = voce
    STATO.mkdir(parents=True, exist_ok=True)
    tmp = STATO / "progetti.json.parziale"
    tmp.write_text(json.dumps(progetti, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, STATO / "progetti.json")
    return voce


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Backup level of every file in the data root"])[0]
    )
    # English values on the command line; the code keeps its own (disco/drive, tutte/usb).
    dest_value = {"disk": "disco", "disco": "disco", "drive": "drive"}
    dests_value = {"all": "tutte", "tutte": "tutte", "usb": "usb"}
    ap.add_argument(
        "--check", dest="controlla", action="store_true", help="the rules: every data-root folder has a level"
    )
    ap.add_argument(
        "--self-test", dest="sabota", action="store_true", help="plant faults and prove --check sees them"
    )
    ap.add_argument("--where", dest="dove", type=Path, metavar="PATH", help="level and rule for a file or a folder")
    ap.add_argument(
        "--summary", dest="riepilogo", action="store_true", help="size per level and per source"
    )
    ap.add_argument("--test", dest="collaudo", action="store_true", help="the rules against known cases")
    ap.add_argument(
        "--list", dest="elenco", type=int, choices=(1, 2, 3), help="paths of one level, one per line"
    )
    ap.add_argument(
        "--destination",
        dest="destinazione",
        type=lambda v: dest_value.get(v, v),
        choices=("disco", "drive"),
        metavar="{disk,drive}",
        default="disco",
        help="with --list: disk (everything) or drive (leaves out USB-only files)",
    )
    ap.add_argument("-0", dest="nul", action="store_true", help="with --list: separated by NUL")
    ap.add_argument(
        "--assign", dest="assegna", metavar="ORG/PROJECT", help="give a work project its own backup rule"
    )
    ap.add_argument("--floor", dest="minimo", type=int, metavar="N", help="with --assign: the lowest level, 1 to 3")
    ap.add_argument(
        "--destinations",
        dest="destinazioni",
        type=lambda v: dests_value.get(v, v),
        choices=("tutte", "usb"),
        metavar="{all,usb}",
        help="with --assign: all destinations, or USB only",
    )
    ap.add_argument("--reason", dest="perche", default="", metavar="TEXT", help="with --assign: why, in one sentence")
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--controlla", dest="controlla", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--sabota", dest="sabota", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--dove", dest="dove", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--riepilogo", dest="riepilogo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--collaudo", dest="collaudo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--elenco", dest="elenco", type=int, choices=(1, 2, 3), help=argparse.SUPPRESS)
    ap.add_argument(
        "--destinazione",
        dest="destinazione",
        type=lambda v: dest_value.get(v, v),
        choices=("disco", "drive"),
        help=argparse.SUPPRESS,
    )
    ap.add_argument("--assegna", dest="assegna", help=argparse.SUPPRESS)
    ap.add_argument("--minimo", dest="minimo", type=int, help=argparse.SUPPRESS)
    ap.add_argument(
        "--destinazioni",
        dest="destinazioni",
        type=lambda v: dests_value.get(v, v),
        choices=("tutte", "usb"),
        help=argparse.SUPPRESS,
    )
    ap.add_argument("--perche", dest="perche", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.assegna:
        try:
            voce = assegna(args.assegna, args.minimo, args.destinazioni, args.perche)
        except ValueError as e:
            print(f"⛔ {e}")
            return 2
        print(f"✅ {args.assegna}: {json.dumps(voce, ensure_ascii=False)}")
        return 0
    if args.elenco:
        fine = "\0" if args.nul else "\n"
        for _n, p, _s, _e in elenco(args.elenco, args.destinazione):
            sys.stdout.write(f"{p}{fine}")
        return 0
    if args.sabota:
        ok = sabota()
        print(
            "✅ the levels guardian sees the planted faults"
            if ok
            else "⛔ the levels guardian does NOT see a fault"
        )
        if not ok:
            return 1
    if args.controlla or not any((args.sabota, args.dove, args.riepilogo, args.collaudo)):
        rossi, gialli = controlla()
        for g in gialli:
            print(f"🟡 {g}")
        for r in rossi:
            print(f"🔴 {r}")
        if rossi:
            print(
                "   add the row to RADICI in tools/infrastructure/sb_livelli.py (level and reason)"
            )
            return 2
        print(f"✅ backup levels: {len(RADICI)} roots in the registry, no reds")
    if args.dove:
        voluta = Path(os.path.abspath(args.dove.expanduser()))
        senza_nomi = any(
            f.nome in SENZA_NOMI and (_dentro(voluta, f.base) or _dentro(f.base, voluta))
            for f in FUORI
        )
        conta = defaultdict(lambda: [0, 0])
        esempio: dict[tuple, Path] = {}
        for p, s, e in cammina_cartella(args.dove):
            k = (e.livello, e.regola, e.solo_usb)
            conta[k][0] += s
            conta[k][1] += 1
            esempio.setdefault(k, p)
        for (liv, regola, usb), (b, n) in sorted(
            conta.items(), key=lambda kv: (kv[0][0], -kv[1][0])
        ):
            es = "names not shown" if senza_nomi else f"e.g. {esempio[(liv, regola, usb)].name}"
            print(
                f"L{liv}{' usb' if usb else '    '} {b / GIB:7.2f} GiB {n:7d} file  {regola}  ({es})"
            )
    if args.collaudo:
        n, errori = collaudo()
        for e in errori:
            print(f"⛔ {e}")
        print(f"test: {n} cases checked, {len(errori)} errors")
        if errori:
            return 1
    if args.riepilogo:
        tot = defaultdict(lambda: [0, 0])
        per_fonte = defaultdict(lambda: [0, 0])
        speciali = defaultdict(int)
        for _p, s, e in cammina():
            tot[(e.livello, e.solo_usb)][0] += s
            tot[(e.livello, e.solo_usb)][1] += 1
            per_fonte[("sbk-data", e.livello)][0] += s
            per_fonte[("sbk-data", e.livello)][1] += 1
            if e.regola.startswith("symbolic link"):
                speciali["symbolic links"] += 1
            elif e.regola.startswith("marker"):
                speciali[e.regola] += 1
            elif e.regola.startswith("new root"):
                speciali["files in new roots without a level"] += 1
        for n, _p, s, e in cammina_fuori():
            tot[(e.livello, e.solo_usb)][0] += s
            tot[(e.livello, e.solo_usb)][1] += 1
            per_fonte[(n, e.livello)][0] += s
            per_fonte[(n, e.livello)][1] += 1
        for (liv, usb), (b, n) in sorted(tot.items()):
            print(f"L{liv}{' disk only USB' if usb else ''}: {b / GIB:.1f} GiB, {n} files")
        print("per source:")
        for (fonte, liv), (b, n) in sorted(per_fonte.items()):
            print(f"  {fonte:<22} L{liv} {b / GIB:7.2f} GiB {n:8d} file")
        for k, n in sorted(speciali.items()):
            print(f"  {k}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
