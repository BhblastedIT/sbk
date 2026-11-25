#!/usr/bin/env python3
""




























from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import mmap
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
BASE = os.environ.get("SB_PAGINE_BASE") or os.path.join(
    HOME, "Library", "Application Support", "SBK", "pagine"
)
REGISTRO = os.path.join(BASE, "registro.jsonl")
EVENTI = os.path.join(BASE, "eventi.jsonl")
SCANSIONE = os.path.join(BASE, "scansione.json")
ERRORI = os.path.join(BASE, "errori.log")
LOCK = os.path.join(BASE, ".lock")

PROGETTI = os.path.join(HOME, ".claude", "projects")
QUOTA_DIR = os.path.join(HOME, ".config", "quota")
LIVE_HISTORY = os.path.join(QUOTA_DIR, "live-history.json")
LIVE_SESSIONS = os.path.join(QUOTA_DIR, "live-sessions.json")
PANE_MAP = os.path.join(QUOTA_DIR, "pane-accounts.json")
NOMI = os.path.join(QUOTA_DIR, "nomi-stato.json")


PRESTITI = os.path.join(QUOTA_DIR, "prestiti.json")
PRESTITI_STORIA = os.path.join(QUOTA_DIR, "prestiti-storia.jsonl")

LOG_SPOSTAMENTI = (os.path.join(QUOTA_DIR, "autorotate.log.1"), os.path.join(QUOTA_DIR, "autorotate.log"))
SNAPSHOT = os.path.join(
    HOME, "Library", "Group Containers", "XXXXXXXXXX.quota.shared", "quota-snapshot.json"
)
SLOT_PANNELLI = os.path.join(HOME, "Library", "Application Support", "AccountPool", "panes")


# Main account slug; override from user config/env. Empty means none highlighted.
ACCOUNT_PRINCIPALE = os.environ.get("SBK_ACCOUNT_PRINCIPALE", "")

TOLLERANZA_LETTURE = 30

TETTO_FILE = 20 * 1024 * 1024
TETTO_PAGINA = 300 * 1024 * 1024

VERSIONE_LETTORE = 3






RICOSTRUZIONE_OGNI_SEC = 600





VIVI_SEC = 3 * 86400
GIRO_INTERO_OGNI_SEC = 86400

FORMATO_SCANSIONE = 2



CODA_MIGRAZIONE = 2 * 1024 * 1024

PENDENTE_MAX_SEC = 2 * 86400
LOCK_RICOSTRUZIONE = os.path.join(BASE, ".ricostruzione.lock")
LOG_RICOSTRUZIONE = os.path.join(BASE, "ricostruzione.log")
UTC = datetime.timezone.utc  # noqa: UP017 runtime py3.9 (l'hook gira con /usr/bin/python3)


RX_PUBBLICATO = re.compile(
    r"Published (?P<path>.+?) at (?P<url>https://claude\.ai/(?:code/)?artifact/(?P<id>[A-Za-z0-9-]+))"
    r"(?: \(Version (?P<n>\d+), version id (?P<vid>[0-9A-Za-z-]+)\))?"
)
RX_GALLERIA = re.compile(
    r"^- \((?P<chi>[^)]*)\) (?P<titolo>.+?) — (?P<url>https://claude\.ai/(?:code/)?artifact/(?P<id>[A-Za-z0-9-]+))"
    r"(?: — updated (?P<data>\d{4}-\d\d-\d\d))?",
    re.M,
)
RX_URL = re.compile(r"https://claude\.ai/(?:code/)?artifact/(?P<id>[A-Za-z0-9-]+)")



MARCHE_FILE = (b'"name":"Artifact","input":', b'"name":"mcp__claude-artifacts__')
RX_MOSSA = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?:autoripara )?(tick|use) "
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) (.*?)→ ([A-Za-z0-9_.-]+)(.*)$"
)
STRUMENTI_PUBBLICA = {
    "mcp__claude-artifacts__publish_files",
    "mcp__claude-artifacts__publish_version",
    "mcp__claude-artifacts__edit_version",
}

MESI = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


TESTI = {
    "titolo": "Pages",
    "sottotitolo": "The pages I prepared for you, all in one place. In here they read without sign-in, online with the account written on each.",
    "per_data": "By date",
    "per_account": "By account",
    "aiuto_vista": "Groups the pages by when they were made or by the account needed to open them online.",
    "cerca": "Search a page",
    "apri_qui": "Open here",
    "aiuto_apri_qui": "The copy saved on the Mac, no sign-in needed.",
    "apri_online": "Open online",
    "aiuto_apri_online": "In the browser. Online the page opens only with the account written next to it.",
    "copia_link": "Copy link",
    "aiuto_copia_link": "Puts the link in the clipboard.",
    "copiato": "Link copied",
    "torna": "All pages",
    "rileggi": "Re-read",
    "aiuto_rileggi": "Re-reads the list and looks for pages made by older sessions, which do not register them on their own. New pages come in by themselves as soon as I publish them.",
    "nessuna": "No pages yet.",
    "nessuna_trovata": "No page with these words.",
    "senza_copia": "No copy on the Mac, it opens only online.",
    "aiuto_principale": "It's on your main account, the one where all the pages should be.",
    "principale": "your main account",
    "aiuto_account": "The account the page was published with. Online it opens only from there.",
    "aiuto_certezza": "How I know which account the page is on.",

    "raggruppa": "Group",
    "per_progetto": "By project",
    "senza_progetto": "No project",
    "nascondi_prove": "Hide the tests",
    "aiuto_prove": "The pages made to test something, like the loan tests. They all stay, here they are only hidden.",
    "su_altri": "{n} on other accounts",
    "aiuto_su_altri": "The pages that online open only with another account. Click to see only those, click again to go back to all.",
    "senza_account": "{n} with no known account",
    "aiuto_senza_account": "The pages where the account they were made with is no longer known. Click to see only those, click again to go back to all.",
    "tutte": "All pages",
    "nessuna_qui": "No pages yet. When I publish one it shows up here on its own.",
    "scegli": "Choose a page on the left.",
    "versione_di": "version {k} of {n}",
    "aiuto_versioni": "The same page published several times or on several accounts. The one at the top is the right one, the others online open only with the account written next to them.",
    "mostra_finder": "Show in Finder",
    "versioni": "Versions",
    "errore_rilettura": "I can't re-read the pages. What you see is from {ora}.",

    "errore_rilettura_senza_ora": "I can't re-read the pages. What you see is the last saved copy.",
    "riprova": "Retry",
}





RACCOLTE = {
    "inspiration": {


        "nome": "Inspiration",
        "cartelle": ("/inspiration/",),
        "nomi": (
            "inspiration.html",
        ),
    }
}


def _raccolta(r: dict) -> str:
    for nome, regola in RACCOLTE.items():
        for v in r.get("versioni") or []:
            p = str(v.get("principale") or "")
            if any(c in p for c in regola["cartelle"]) or os.path.basename(p) in regola["nomi"]:
                return nome
    return ""


def _famiglie(registro: list) -> dict:
    ""



    g = _Gruppi()
    legami: dict = {}
    for r in registro:
        g.trova(r["id"])
        raccolta = _raccolta(r)
        if raccolta:
            legami.setdefault(("raccolta", raccolta), []).append(r["id"])
        titolo = str(r.get("titolo") or "").strip().lower()
        for v in r.get("versioni") or []:
            if v.get("principale") and titolo:
                legami.setdefault(("file", os.path.realpath(v["principale"]), titolo), []).append(
                    r["id"]
                )
    for ids in legami.values():
        for x in ids[1:]:
            g.unisci(ids[0], x)
    return {r["id"]: g.trova(r["id"]) for r in registro}


def _prova(r: dict) -> bool:
    ""

    return (r.get("progetto") or "").strip().lower() == "prova" or str(
        r.get("titolo") or ""
    ).strip().lower().startswith("prova")





def _errore(msg: str) -> None:
    ""
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(ERRORI, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M:%S} {msg[:2000]}\n")
    except Exception:
        pass


def _leggi_json(percorso: str, vuoto):
    try:
        with open(percorso, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return vuoto


def _scrivi_json(percorso: str, dati) -> None:
    tmp = percorso + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dati, fh, ensure_ascii=False)
    os.replace(tmp, percorso)


def _leggi_jsonl(percorso: str) -> list:
    out = []
    try:
        with open(percorso, encoding="utf-8") as fh:
            for riga in fh:
                riga = riga.strip()
                if not riga:
                    continue
                try:
                    out.append(json.loads(riga))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def _scrivi_jsonl(percorso: str, righe: list) -> None:
    tmp = percorso + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in righe:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, percorso)


class _Lucchetto:
    ""

    def __enter__(self):
        os.makedirs(BASE, exist_ok=True)
        self.fh = open(LOCK, "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        try:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _epoch_da_vid(vid: str | None) -> float | None:
    ""
    m = re.match(r"^(\d{10})-", vid or "")
    return float(m.group(1)) if m else None


def _testo(contenuto) -> str:
    ""
    if contenuto is None:
        return ""
    if isinstance(contenuto, str):
        return contenuto
    if isinstance(contenuto, list):
        parti = []
        for x in contenuto:
            if isinstance(x, dict):
                if isinstance(x.get("text"), str):
                    parti.append(x["text"])
            elif isinstance(x, str):
                parti.append(x)
        return "\n".join(parti)
    if isinstance(contenuto, dict):
        for k in ("text", "content", "result", "output"):
            if k in contenuto:
                return _testo(contenuto[k])
        return json.dumps(contenuto, ensure_ascii=False)
    return str(contenuto)





def _files_pubblicati(inp: dict, cwd: str | None) -> dict:
    ""
    out = {}
    if not isinstance(inp, dict):
        return out
    radice = inp.get("root") or ""
    if radice and not os.path.isabs(radice) and cwd:
        radice = os.path.join(cwd, radice)
    base = radice or cwd or ""

    def assoluto(p: str) -> str:
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(base, p)

    files = inp.get("files")
    if isinstance(files, dict):
        for pub, src in files.items():
            if src is None:
                out[str(pub)] = None
            elif isinstance(src, str):
                out[str(pub)] = assoluto(src)
            elif isinstance(src, dict) and isinstance(src.get("from"), str):
                out[str(pub)] = assoluto(src["from"])
    elif isinstance(files, list):
        for f in files:
            if isinstance(f, dict):
                src = f.get("path") or f.get("from")
                pub = f.get("as") or f.get("path")
                if isinstance(src, str) and isinstance(pub, str):
                    out[pub if not os.path.isabs(pub) else os.path.basename(pub)] = assoluto(src)
            elif isinstance(f, str):
                out[f] = assoluto(f)
    return out


def _evento_pubblica(
    nome: str, inp: dict, testo: str, quando: float | None, sid: str, cwd: str | None, fonte: str
) -> dict | None:
    ""

    inp = inp if isinstance(inp, dict) else {}
    if nome == "Artifact":
        if (inp.get("action") or "publish") != "publish" or inp.get("asset"):
            return None
        m = RX_PUBBLICATO.search(testo or "")
        if not m:
            return _pubblicazione_strutturata(inp, testo, quando, sid, cwd, fonte)
        principale = m.group("path").strip()
        if inp.get("file_path"):
            principale = os.path.expanduser(str(inp["file_path"]))
            if not os.path.isabs(principale) and cwd:
                principale = os.path.join(cwd, principale)
        vid = m.group("vid") or ""
        quando = _epoch_da_vid(vid) or quando
        return {
            "tipo": "pubblica",
            "chiave": f"p:{m.group('id')}:{vid or _iso(quando)}",
            "id": m.group("id"),
            "url": m.group("url"),
            "versione": int(m.group("n")) if m.group("n") else None,
            "vid": vid,
            "quando": _iso(quando),
            "sessione": sid,
            "cwd": cwd,
            "principale": principale,
            "files": _files_pubblicati(inp, cwd),
            "titolo_input": inp.get("title") or inp.get("label") or "",
            "descrizione": inp.get("description") or "",
            "fonte": fonte,
        }
    if nome in STRUMENTI_PUBBLICA:
        try:
            dati, _ = json.JSONDecoder().raw_decode((testo or "").lstrip())
        except Exception:
            return None
        if not isinstance(dati, dict) or not isinstance(dati.get("url"), str):
            return None
        m = RX_URL.search(dati["url"])
        if not m:
            return None
        vid = str(dati.get("version") or "")
        quando = _epoch(dati.get("updated_at")) or quando or _epoch_da_vid(vid)
        files = _files_pubblicati(inp, cwd)
        principale = files.get("index.html") or next((v for v in files.values() if v), None)
        return {
            "tipo": "pubblica",
            "chiave": f"p:{m.group('id')}:{vid or _iso(quando)}",
            "id": m.group("id"),
            "url": dati["url"],
            "versione": int(dati.get("seq") or 0) or None,
            "vid": vid,
            "quando": _iso(quando),
            "sessione": sid,
            "cwd": cwd,
            "principale": principale,
            "files": files,
            "titolo_input": dati.get("title") or inp.get("title") or "",
            "descrizione": inp.get("description") or "",
            "fonte": fonte,
        }
    return None


def _pubblicazione_strutturata(
    inp: dict, testo: str, quando: float | None, sid: str, cwd: str | None, fonte: str
) -> dict | None:
    ""

    try:
        dati = json.loads(testo or "")
    except Exception:
        return None
    if not isinstance(dati, dict):
        return None
    url = next(
        (
            v
            for k, v in dati.items()
            if k in ("url", "artifactUrl", "artifact_url") and isinstance(v, str)
        ),
        "",
    )
    m = RX_URL.search(url)
    if not m or re.search(r"(?i)refused|nothing was published|not found|denied|error", testo or ""):
        return None
    vid = str(next((dati[k] for k in ("versionId", "version_id", "vid") if dati.get(k)), "") or "")
    n = dati.get("version") if isinstance(dati.get("version"), int) else None
    quando = _epoch_da_vid(vid) or quando
    principale = os.path.expanduser(str(inp.get("file_path") or "")) or None
    if principale and not os.path.isabs(principale) and cwd:
        principale = os.path.join(cwd, principale)
    return {
        "tipo": "pubblica",
        "chiave": f"p:{m.group('id')}:{vid or _iso(quando)}",
        "id": m.group("id"),
        "url": url,
        "versione": n,
        "vid": vid,
        "quando": _iso(quando),
        "sessione": sid,
        "cwd": cwd,
        "principale": principale,
        "files": _files_pubblicati(inp, cwd),
        "titolo_input": inp.get("title") or inp.get("label") or "",
        "descrizione": inp.get("description") or "",
        "fonte": fonte,
    }


def _evento_galleria(
    nome: str, inp: dict, testo: str, quando: float | None, sid: str, cwd: str | None, fonte: str
) -> dict | None:
    ""
    inp = inp if isinstance(inp, dict) else {}
    if nome != "Artifact" or inp.get("action") != "list":
        return None
    if (inp.get("scope") or "mine") not in ("mine", "all"):
        return None
    titoli = {}
    for m in RX_GALLERIA.finditer(testo or ""):
        if m.group("chi").strip().lower() == "mine":
            titoli[m.group("id")] = {
                "titolo": m.group("titolo").strip(),
                "url": m.group("url"),
                "aggiornata": m.group("data") or "",
            }
    if not titoli:
        return None
    impronta = hashlib.sha1(",".join(sorted(titoli)).encode()).hexdigest()[:10]
    return {
        "tipo": "galleria",
        "chiave": f"g:{sid}:{_iso(quando)}:{impronta}",
        "quando": _iso(quando),
        "sessione": sid,
        "cwd": cwd,
        "pagine": titoli,
        "fonte": fonte,
    }





def _account_slot() -> tuple[str | None, str]:
    ""

    candidati = []
    cfg = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR") or ""
    if cfg:
        candidati.append(os.path.join(cfg, ".brokered"))
    chiave = os.environ.get("SB_PANE_KEY") or ""
    foglia = chiave.split(":")[-1] if chiave else ""
    if foglia and re.match(r"^[0-9A-Za-z-]{8,}$", foglia):
        candidati.append(os.path.join(SLOT_PANNELLI, foglia, ".brokered"))
    for p in candidati:
        d = _leggi_json(p, {})
        acct = d.get("account") if isinstance(d, dict) else None
        if isinstance(acct, str) and acct:
            return acct, "read from the subscription in use at publication"
    if foglia:
        mappa = _leggi_json(PANE_MAP, {})
        if isinstance(mappa, dict):
            for k in (chiave, foglia):
                v = mappa.get(k)
                if isinstance(v, str) and v:
                    return v, "from the subscription assigned to the terminal at publication"
    return None, ""





class Storia:
    ""

    def __init__(self) -> None:
        self.letture = _leggi_json(LIVE_HISTORY, {})
        self.sessioni = _leggi_json(LIVE_SESSIONS, {})
        self.mosse: dict[str, list[tuple[float, str]]] = {}

        self.prestiti: list[tuple[str | None, str | None, str, float, float]] = []
        aperti = _leggi_json(PRESTITI, {})
        voci = [v for v in _leggi_jsonl(PRESTITI_STORIA) if isinstance(v, dict)]
        voci += [
            v for v in (aperti.values() if isinstance(aperti, dict) else []) if isinstance(v, dict)
        ]
        for v in voci:
            da = v.get("da")
            if not isinstance(v.get("account"), str) or not isinstance(da, (int, float)):  # noqa: UP038
                continue
            fine = v.get("rientro") if isinstance(v.get("rientro"), (int, float)) else time.time()  # noqa: UP038
            self.prestiti.append(
                (v.get("sessione"), v.get("leaf"), v["account"], float(da), float(fine))
            )
        try:
            from zoneinfo import ZoneInfo

            roma = ZoneInfo("UTC")
        except Exception:
            roma = None
        for p in LOG_SPOSTAMENTI:
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    righe = fh.readlines()
            except FileNotFoundError:
                continue
            for riga in righe:
                if "→" not in riga:
                    continue
                m = RX_MOSSA.match(riga.rstrip("\n"))
                if not m:
                    continue
                if m.group(2) == "tick" and "ok=True" not in m.group(6):
                    continue
                if "ok=False" in m.group(6):
                    continue
                try:
                    t = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    t = t.replace(tzinfo=roma) if roma else t.astimezone()
                except Exception:
                    continue
                self.mosse.setdefault(m.group(3), []).append((t.timestamp(), m.group(5)))
        for v in self.mosse.values():
            v.sort()

    def foglia(self, sid: str) -> str | None:
        for fonte in (self.letture, self.sessioni):
            v = fonte.get(sid) if isinstance(fonte, dict) else None
            if isinstance(v, dict) and v.get("leaf"):
                return v["leaf"]
        return None

    def account(self, sid: str, t: float | None) -> tuple[str | None, str, str]:
        ""
        if not sid or t is None:
            return None, "non_noto", ""


        foglia_sid = None
        for sessione, leaf, acct, da, fine in self.prestiti:
            if not da - 2 <= t <= fine + 2:
                continue
            if sessione != sid:
                if not leaf:
                    continue
                if foglia_sid is None:
                    foglia_sid = self.foglia(sid) or ""
                if leaf != foglia_sid:
                    continue
            return acct, "certo", f"loaded on loan on {acct}"
        prova = None
        v = self.letture.get(sid) if isinstance(self.letture, dict) else None
        if isinstance(v, dict):



            iniziati = [
                (inizio, fine, acct) for acct, inizio, fine in v.get("iv") or [] if inizio <= t + 2
            ]
            if iniziati:
                inizio, fine, acct = max(iniziati)
                if t <= fine + TOLLERANZA_LETTURE:
                    return acct, "certo", "read from the session at the time of publication"
                prova = (fine, acct, "last read of the session before publication")
        foglia = self.foglia(sid)
        if foglia:
            mosse = [m for m in self.mosse.get(foglia, []) if m[0] <= t]
            if mosse:
                quando, acct = mosse[-1]
                if prova is None or quando > prova[0]:
                    prova = (quando, acct, "reconstructed from the terminal's subscription changes")
        if prova:
            return prova[1], "storico", prova[2]
        return None, "non_noto", ""





def _sessione_del_file(percorso: str) -> str:
    parti = percorso.split(os.sep)
    if "subagents" in parti:
        i = parti.index("subagents")
        if i > 0:
            return parti[i - 1]
    return os.path.splitext(os.path.basename(percorso))[0]


def _eventi_dal_file(
    percorso: str, da: int = 0, pendenti: dict | None = None
) -> tuple[list, int, dict]:
    ""



    eventi = []
    usi: dict[str, list] = dict(pendenti or {})
    sid_file = _sessione_del_file(percorso)
    letto = da
    with open(percorso, "rb") as fh:
        fh.seek(da)
        for grezza in fh:
            if not grezza.endswith(b"\n"):
                break
            letto += len(grezza)
            if b"rtifact" not in grezza:
                continue
            try:
                o = json.loads(grezza)
            except Exception:
                continue
            if not isinstance(o, dict):
                continue
            msg = o.get("message")
            blocchi = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(blocchi, list):
                continue
            ts = _epoch(o.get("timestamp"))
            sid = o.get("sessionId") or sid_file
            cwd = o.get("cwd")
            for b in blocchi:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    nome = b.get("name") or ""
                    if nome == "Artifact" or nome in STRUMENTI_PUBBLICA:
                        usi[b.get("id")] = [nome, b.get("input") or {}, ts, sid, cwd]
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in usi:
                    nome, inp, ts_uso, sid_uso, cwd_uso = usi.pop(b["tool_use_id"])
                    if b.get("is_error"):
                        continue
                    testo = _testo(b.get("content"))
                    quando = ts or ts_uso
                    for fabbrica in (_evento_pubblica, _evento_galleria):
                        e = fabbrica(
                            nome, inp, testo, quando, sid_uso or sid, cwd_uso or cwd, "transcript"
                        )
                        if e:
                            e["transcript"] = percorso
                            eventi.append(e)

    ultima = max([u[2] for u in usi.values() if isinstance(u[2], (int, float))] or [0])  # noqa: UP038 py3.9
    usi = {
        k: u
        for k, u in usi.items()
        if not isinstance(u[2], (int, float)) or ultima - u[2] < PENDENTE_MAX_SEC  # noqa: UP038
    }
    return eventi, letto, usi


def _transcript():
    for radice, _cartelle, file in os.walk(PROGETTI):
        for nome in file:
            if nome.endswith(".jsonl"):
                yield os.path.join(radice, nome)


def _giro_completo() -> tuple[dict, list]:
    ""

    cartelle: dict[str, int] = {}
    file: list[str] = []
    pila = [PROGETTI]
    while pila:
        d = pila.pop()
        try:
            m = os.stat(d).st_mtime_ns
            voci = list(os.scandir(d))
        except OSError:
            continue
        cartelle[d] = m
        for e in voci:
            if e.is_dir(follow_symlinks=False):
                pila.append(e.path)
            elif e.name.endswith(".jsonl"):
                file.append(e.path)
    return cartelle, file


def _giro_veloce(prima: dict, noti: list) -> tuple[dict, list, set, int]:
    ""


    cartelle: dict[str, int] = {}
    da_elencare: list[str] = []
    for d, m in prima.items():
        try:
            ora_m = os.stat(d).st_mtime_ns
        except OSError:
            continue
        cartelle[d] = ora_m
        if ora_m != m:
            da_elencare.append(d)
    if PROGETTI not in cartelle and os.path.isdir(PROGETTI):
        cartelle[PROGETTI] = os.stat(PROGETTI).st_mtime_ns
        da_elencare.append(PROGETTI)
    elencate: dict[str, set] = {}
    while da_elencare:
        d = da_elencare.pop()
        try:
            voci = list(os.scandir(d))
        except OSError:
            cartelle.pop(d, None)
            continue
        nomi = set()
        for e in voci:
            if e.is_dir(follow_symlinks=False):
                if e.path not in cartelle:

                    try:
                        cartelle[e.path] = os.stat(e.path).st_mtime_ns
                    except OSError:
                        continue
                    da_elencare.append(e.path)
            elif e.name.endswith(".jsonl"):
                nomi.add(e.path)
        elencate[d] = nomi
    file: list[str] = []
    for p in noti:
        d = os.path.dirname(p)
        if d not in cartelle or (d in elencate and p not in elencate[d]):
            continue
        file.append(p)
    gia = set(file)
    nuovi = {p for nomi in elencate.values() for p in nomi if p not in gia}
    file.extend(sorted(nuovi))
    return cartelle, file, nuovi, len(elencate)


def _voce(v) -> dict | None:
    ""

    if not isinstance(v, list) or len(v) < 3:
        return None
    return {
        "misura": v[0],
        "data": v[1],
        "ha": bool(v[2]),
        "letto": v[3] if len(v) > 3 and isinstance(v[3], int) else None,
        "ino": v[4] if len(v) > 4 and isinstance(v[4], int) else None,
        "pendenti": v[5] if len(v) > 5 and isinstance(v[5], dict) else {},
    }


def _inizio_riga(fh, pos: int) -> int:
    ""
    if pos <= 0:
        return 0
    fh.seek(pos - 1)
    return pos - 1 + len(fh.readline())


def scansiona(tutto: bool = False, ora: float | None = None) -> tuple[list, dict]:
    ""




    ora = time.time() if ora is None else ora
    cache = {} if tutto else _leggi_json(SCANSIONE, {})
    stessa_versione = cache.get("_versione") == VERSIONE_LETTORE
    cartelle_prima = cache.get("_cartelle") if cache.get("_formato") == FORMATO_SCANSIONE else None
    giro_intero_prima = cache.get("_giro_intero")
    intero = (
        tutto
        or not stessa_versione
        or not isinstance(cartelle_prima, dict)
        or not isinstance(giro_intero_prima, (int, float))  # noqa: UP038 py3.9
        or ora - giro_intero_prima > GIRO_INTERO_OGNI_SEC
    )
    noti = [k for k in cache if not k.startswith("_")]
    if intero:
        cartelle, file = _giro_completo()
        nuovi: set = set()
        elencate = len(cartelle)
    else:
        cartelle, file, nuovi, elencate = _giro_veloce(cartelle_prima, noti)
    nuova: dict = {
        "_versione": VERSIONE_LETTORE,
        "_formato": FORMATO_SCANSIONE,
        "_cartelle": cartelle,
        "_giro_intero": ora if intero else giro_intero_prima,
    }
    eventi: list = []
    conti = {
        "transcript": len(file),
        "guardati": 0,
        "letti": 0,
        "con_artifact": 0,
        "saltati": 0,
        "da_capo": 0,
        "byte_letti": 0,
        "cartelle_elencate": elencate,
        "giro_intero": intero,
    }
    riletti: list[str] = []
    da_capo: list[str] = []
    for p in file:
        grezza = cache.get(p)
        if (
            not intero
            and p not in nuovi
            and isinstance(grezza, list)
            and len(grezza) >= 3
            and isinstance(grezza[1], int)
            and ora - grezza[1] / 1e9 > VIVI_SEC
        ):

            nuova[p] = grezza
            conti["saltati"] += 1
            continue
        v = _voce(grezza)
        conti["guardati"] += 1
        try:
            st = os.stat(p)
        except OSError:
            continue
        misura, data, ino = st.st_size, st.st_mtime_ns, st.st_ino
        if (
            v is not None
            and v["misura"] == misura
            and v["data"] == data
            and v["ino"] in (None, ino)
            and (stessa_versione or not v["ha"])
        ):
            nuova[p] = cache[p]
            conti["saltati"] += 1
            continue
        if (
            v is None
            or (v["ino"] is not None and v["ino"] != ino)
            or misura < (v["letto"] if v["letto"] is not None else v["misura"])
            or (not stessa_versione and v["ha"])
        ):

            da, pendenti, ha = 0, {}, False
            da_capo.append(p)
            conti["da_capo"] += 1
        else:
            da, pendenti, ha = v["letto"], v["pendenti"], v["ha"]
        riletti.append(p)
        conti["letti"] += 1
        letto = da
        try:
            with open(p, "rb") as fh:
                if da is None:

                    da = _inizio_riga(fh, max(0, v["misura"] - CODA_MIGRAZIONE))
                    letto = da
                if misura > da:
                    with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        dentro = bool(pendenti) or any(mm.find(m, da) != -1 for m in MARCHE_FILE)
                        if not dentro:

                            letto = max(da, mm.rfind(b"\n", da) + 1)
            if misura > da and dentro:
                nuovi_eventi, letto, pendenti = _eventi_dal_file(p, da, pendenti)
                eventi.extend(nuovi_eventi)
                ha = True
                conti["con_artifact"] += 1
            conti["byte_letti"] += max(0, misura - da)
        except (OSError, ValueError) as e:
            _errore(f"scansione {p}: {e!r}")
            continue
        except Exception as e:
            _errore(f"scansione {p}: {e!r}")
        riga = [misura, data, ha, letto, ino]
        if pendenti:
            riga.append(pendenti)
        nuova[p] = riga
    return eventi, {"cache": nuova, "conti": conti, "riletti": riletti, "da_capo": da_capo}




_RANGO = {"certo": 2, "storico": 1, "non_noto": 0}


def _unisci_eventi(vecchi: list, nuovi: list) -> list:
    ""
    per_chiave = {}
    for e in vecchi + nuovi:
        k = e.get("chiave")
        if not k:
            continue
        prima = per_chiave.get(k)
        if prima is None:
            per_chiave[k] = e
            continue
        unito = dict(prima)
        for campo, valore in e.items():
            if unito.get(campo) in (None, "", {}, []) and valore not in (None, "", {}, []):
                unito[campo] = valore
        if prima.get("slot") or e.get("slot"):
            unito["slot"] = prima.get("slot") or e.get("slot")
        per_chiave[k] = unito
    return sorted(per_chiave.values(), key=lambda e: (e.get("quando") or "", e.get("chiave")))


def _titolo_dal_nome(percorso: str | None) -> str:
    ""
    if not percorso:
        return ""
    nome = os.path.splitext(os.path.basename(percorso))[0]
    nome = re.sub(r"[-_]+", " ", nome).strip()
    return nome[:1].upper() + nome[1:] if nome else ""


def _giorno_iso(giorno: str) -> str | None:
    ""
    return f"{giorno}T12:00:00Z" if re.match(r"^\d{4}-\d\d-\d\d$", giorno or "") else None


def _titolo_html(percorso: str | None) -> str:
    if not percorso:
        return ""
    try:
        with open(percorso, "rb") as fh:
            testa = fh.read(65536).decode("utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", testa, re.S | re.I)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return (
        t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
    )[:160]


def _progetto(cwd: str | None) -> str:
    ""
    if not cwd:
        return ""
    p = cwd.rstrip("/")
    for segno in ("/.worktrees/", "/worktrees/", "/workspaces/", "/Projects/"):
        if segno in p:
            nome = p.split(segno, 1)[1].split("/")[0]
            break
    else:
        nome = os.path.basename(p)
    if nome.startswith("SBK"):
        return "SBK"
    return nome


class _Gruppi:
    ""

    def __init__(self) -> None:
        self.padre: dict[str, str] = {}

    def trova(self, x: str) -> str:
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def unisci(self, a: str, b: str) -> None:
        ra, rb = self.trova(a), self.trova(b)
        if ra != rb:
            self.padre[rb] = ra


def componi_registro(eventi: list, storia: Storia | None) -> list:
    ""
    nomi = _leggi_json(NOMI, {})
    pagine: dict[str, dict] = {}
    gallerie = []
    for e in eventi:
        if e.get("tipo") == "pubblica" and e.get("id"):
            p = pagine.setdefault(e["id"], {"id": e["id"], "url": e.get("url"), "versioni": []})
            p["url"] = e.get("url") or p["url"]
            t = _epoch(e.get("quando"))
            if e.get("slot", {}).get("account"):
                acct, certezza, come = e["slot"]["account"], "certo", e["slot"].get("come") or ""
            elif storia is not None:
                acct, certezza, come = storia.account(e.get("sessione") or "", t)
            else:
                acct, certezza, come = None, "non_noto", ""
            p["versioni"].append(
                {
                    "n": e.get("versione"),
                    "vid": e.get("vid"),
                    "quando": e.get("quando"),
                    "sessione": e.get("sessione"),
                    "cwd": e.get("cwd"),
                    "principale": e.get("principale"),
                    "files": e.get("files") or {},
                    "titolo_input": e.get("titolo_input") or "",
                    "descrizione": e.get("descrizione") or "",
                    "account": acct,
                    "certezza": certezza,
                    "come": come,
                    "fonte": e.get("fonte"),
                }
            )
        elif e.get("tipo") == "galleria":
            t = _epoch(e.get("quando"))
            if e.get("slot", {}).get("account"):
                acct, certezza, come = (
                    e["slot"]["account"],
                    "certo",
                    "read from the subscription in use when the gallery was viewed",
                )
            elif storia is not None:
                acct, certezza, come = storia.account(e.get("sessione") or "", t)
            else:
                acct, certezza, come = None, "non_noto", ""
            gallerie.append((e, acct, certezza, come))
            for pid, info in (e.get("pagine") or {}).items():
                p = pagine.setdefault(pid, {"id": pid, "url": info.get("url"), "versioni": []})
                p.setdefault("titoli_galleria", []).append(
                    (e.get("quando") or "", info.get("titolo"))
                )
                if info.get("aggiornata"):
                    p.setdefault("aggiornate", []).append(info["aggiornata"])

    gruppi = _Gruppi()
    for e, *_ in gallerie:
        ids = list((e.get("pagine") or {}).keys())
        for x in ids[1:]:
            gruppi.unisci(ids[0], x)


    titoli: dict[str, str] = {}
    for pid, p in pagine.items():
        p["versioni"].sort(key=lambda v: (v.get("quando") or "", v.get("n") or 0))
        vers = p["versioni"]
        ultima = vers[-1] if vers else {}
        prima = vers[0] if vers else {}
        titoli_gal = sorted(p.get("titoli_galleria") or [])
        p["_titoli_gal"] = titoli_gal
        titoli[pid] = (
            (titoli_gal[-1][1] if titoli_gal else "")
            or _titolo_html(ultima.get("principale"))
            or ultima.get("titolo_input")
            or prima.get("titolo_input")
            or _titolo_dal_nome(ultima.get("principale") or prima.get("principale"))
            or pid
        )


    prove_gruppo: dict[str, list] = {}
    for e, acct, certezza, come in gallerie:
        ids = list((e.get("pagine") or {}).keys())
        if acct and ids:
            prove_gruppo.setdefault(gruppi.trova(ids[0]), []).append(
                (
                    _RANGO[certezza],
                    acct,
                    f"that account's gallery viewed from a session, {come}",
                    None,
                )
            )
    for pid, p in pagine.items():
        v0 = p["versioni"][0] if p["versioni"] else None
        if v0 and v0.get("account"):
            prove_gruppo.setdefault(gruppi.trova(pid), []).append(
                (
                    _RANGO[v0["certezza"]],
                    v0["account"],
                    f"it's in the same gallery as «{titoli[pid]}»",
                    pid,
                )
            )

    out = []
    for pid, p in pagine.items():
        vers = p["versioni"]
        prima = vers[0] if vers else {}
        ultima = vers[-1] if vers else {}
        titoli_gal = p["_titoli_gal"]

        acct = prima.get("account")
        certezza = prima.get("certezza") or "non_noto"
        come = prima.get("come") or ""
        if not acct:
            for v in vers[1:]:
                if v.get("account"):
                    acct, certezza, come = v["account"], v["certezza"], v["come"]
                    break

        prove = [x for x in prove_gruppo.get(gruppi.trova(pid), []) if x[3] != pid]
        certi = {x[1] for x in prove if x[0] == 2}
        if len(certi) == 1 and _RANGO.get(certezza, 0) < 2:
            a = next(iter(certi))
            if acct in (None, a):
                motivo = next(x[2] for x in prove if x[0] == 2 and x[1] == a)
                acct, certezza, come = a, "certo", motivo
        elif len(certi) > 1:
            p["conflitto"] = sorted(certi)
        if not acct and prove:
            r, a, c, _ref = max(prove, key=lambda x: x[0])
            acct, certezza, come = a, ("storico" if r < 2 else "certo"), c
        sid = ultima.get("sessione") or prima.get("sessione") or ""
        nome_sess = nomi.get(sid, {}).get("voluto") if isinstance(nomi.get(sid), dict) else None
        riga = {
            "id": pid,
            "url": p.get("url") or f"https://claude.ai/artifact/{pid}",
            "titolo": titoli[pid],
            "descrizione": ultima.get("descrizione") or prima.get("descrizione") or "",
            "progetto": _progetto(ultima.get("cwd") or prima.get("cwd")),
            "conversazione": nome_sess or "",
            "sessione": sid,
            "account": acct,
            "certezza": certezza if acct else "non_noto",
            "come": come if acct else "",

            "prima": prima.get("quando")
            or _giorno_iso(min(p.get("aggiornate") or [""]))
            or (titoli_gal[0][0] if titoli_gal else None),
            "ultima": ultima.get("quando")
            or _giorno_iso(max(p.get("aggiornate") or [""]))
            or (titoli_gal[-1][0] if titoli_gal else None),
            "n_versioni": len(vers),
            "versioni": vers,
            "solo_galleria": not vers,
        }
        if p.get("conflitto"):
            riga["conflitto"] = p["conflitto"]
        out.append(riga)
    out.sort(key=lambda r: r.get("ultima") or "", reverse=True)
    return out





def _stato_dei_file(versioni: list) -> tuple[str | None, dict]:
    ""
    files: dict[str, str | None] = {}
    principale = None
    for v in versioni:
        for pub, src in (v.get("files") or {}).items():
            files[pub] = src
        if v.get("principale"):
            principale = v["principale"]
    return principale, {k: v for k, v in files.items() if v}


def _scheletro(contenuto: bytes) -> bytes:
    ""
    testa = contenuto[:2048].lstrip().lower()
    if testa.startswith(b"<!doctype") or testa.startswith(b"<html"):
        return contenuto
    return (
        b'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        b'<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n'
        + contenuto
        + b"\n</body>\n</html>\n"
    )


def copia_pagina(riga: dict, ultimo_uso: dict) -> dict:
    ""

    vers = riga.get("versioni") or []
    if not vers:
        return {}
    principale, files = _stato_dei_file(vers)
    ultima = vers[-1]
    if not principale:
        return {}
    cartella = os.path.join(BASE, riga["id"])
    meta_p = os.path.join(cartella, "copia.json")
    meta = _leggi_json(meta_p, {})
    pagina_locale = os.path.join(cartella, "_pagina.html")
    if meta.get("vid") == ultima.get("vid") and os.path.exists(pagina_locale):
        return {k: meta.get(k) for k in ("copia", "copia_vid", "copia_quando", "copia_dopo")}

    def nostro(src: str) -> bool:
        u = ultimo_uso.get(os.path.realpath(src))
        return u is None or u == riga["id"]

    if not os.path.isfile(principale) or not nostro(principale):
        return {}
    try:
        if os.path.getsize(principale) > TETTO_FILE:
            return {}
        os.makedirs(cartella, exist_ok=True)
        with open(principale, "rb") as fh:
            grezzo = fh.read()
        nome = os.path.basename(principale)
        with open(os.path.join(cartella, nome), "wb") as fh:
            fh.write(grezzo)
        with open(pagina_locale, "wb") as fh:
            fh.write(_scheletro(grezzo))
        totale = len(grezzo)
        for pub, src in files.items():
            if not src or not os.path.isfile(src) or not nostro(src):
                continue
            rel = os.path.normpath(pub).lstrip("/")
            if rel.startswith(".."):
                continue
            dim = os.path.getsize(src)
            if dim > TETTO_FILE or totale + dim > TETTO_PAGINA:
                continue
            dest = os.path.join(cartella, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
            totale += dim
        mtime = os.path.getmtime(principale)
        pubblicata = _epoch(ultima.get("quando")) or 0
        campi = {
            "copia": os.path.relpath(pagina_locale, BASE),
            "copia_vid": ultima.get("vid"),
            "copia_quando": _iso(time.time()),

            "copia_dopo": bool(pubblicata and mtime > pubblicata + 120),
        }
        _scrivi_json(meta_p, {"vid": ultima.get("vid"), **campi})
        return campi
    except Exception as e:
        _errore(f"copia {riga.get('id')}: {e!r}")
        return {}


def _ultimo_uso(registro: list) -> dict:
    ""
    usi = []
    for r in registro:
        for v in r.get("versioni") or []:
            for src in [v.get("principale"), *(v.get("files") or {}).values()]:
                if src:
                    usi.append((v.get("quando") or "", os.path.realpath(src), r["id"]))
    out = {}
    for _q, src, pid in sorted(usi):
        out[src] = pid
    return out


def _applica_copie(registro: list) -> None:
    usi = _ultimo_uso(registro)
    for r in registro:
        r.update(copia_pagina(r, usi))
        if not r.get("copia"):
            locale = os.path.join(BASE, r["id"], "_pagina.html")
            meta = _leggi_json(os.path.join(BASE, r["id"], "copia.json"), {})
            if os.path.exists(locale) and meta:

                r.update({k: meta.get(k) for k in ("copia", "copia_vid", "copia_quando")})
                r["copia_vecchia"] = meta.get("vid") != (r.get("versioni") or [{}])[-1].get("vid")





def ricostruisci(tutto: bool = False, copie: bool = True) -> dict:
    t0 = time.time()
    nuovi, scan = scansiona(tutto=tutto)
    da_capo = set(scan["da_capo"])
    with _Lucchetto():



        vecchi = [e for e in _leggi_jsonl(EVENTI) if e.get("transcript") not in da_capo]
        eventi = _unisci_eventi(vecchi, nuovi)
        _scrivi_jsonl(EVENTI, eventi)
        registro = componi_registro(eventi, Storia())
        if copie:
            _applica_copie(registro)
        _scrivi_jsonl(REGISTRO, registro)
        _scrivi_json(SCANSIONE, scan["cache"])
    conti_cert: dict[str, int] = {}
    conti_acct: dict[str, int] = {}
    for r in registro:
        conti_cert[r["certezza"]] = conti_cert.get(r["certezza"], 0) + 1
        conti_acct[r.get("account") or "unknown"] = (
            conti_acct.get(r.get("account") or "unknown", 0) + 1
        )
    return {
        "ok": True,
        "secondi": round(time.time() - t0, 1),
        "scansione": scan["conti"],
        "eventi_nuovi": len(nuovi),
        "eventi": len(eventi),
        "pagine": len(registro),
        "per_certezza": conti_cert,
        "per_account": dict(sorted(conti_acct.items(), key=lambda x: -x[1])),
        "con_copia": sum(1 for r in registro if r.get("copia")),
        "solo_galleria": sum(1 for r in registro if r.get("solo_galleria")),
        "conflitti": [r["id"] for r in registro if r.get("conflitto")],
    }


def ricostruisci_in_sottofondo(
    ora: float | None = None, minimo: float = RICOSTRUZIONE_OGNI_SEC
) -> bool:
    ""

    ora = time.time() if ora is None else ora
    try:
        if ora - os.path.getmtime(SCANSIONE) < minimo:
            return False
    except OSError:
        pass
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(LOG_RICOSTRUZIONE, "a") as log:
            subprocess.Popen(
                ["/usr/bin/python3", os.path.abspath(__file__), "ricostruisci-staccata"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
            )
        return True
    except Exception as e:
        _errore(f"ricostruzione in sottofondo: {e!r}")
        return False


def _ricostruisci_staccata() -> int:
    ""
    os.makedirs(BASE, exist_ok=True)
    with open(LOCK_RICOSTRUZIONE, "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        try:
            out = ricostruisci(copie=True)
            scan = out.get("scansione") or {}
            dettaglio = ""
            if scan:
                dettaglio = (
                    f", {'giro intero' if scan.get('giro_intero') else 'giro veloce'}, "
                    f"{scan.get('guardati', 0)} file guardati, {scan.get('letti', 0)} letti, "
                    f"{round(scan.get('byte_letti', 0) / 1e6, 1)} MB"
                )
            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} ricostruzione: {out['pagine']} pagine, "
                f"{out['eventi_nuovi']} eventi nuovi, {out['secondi']} s{dettaglio}",
                flush=True,
            )
        except Exception as e:
            _errore(f"ricostruzione staccata: {e!r}")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return 0


def registra(grezzo: str) -> None:
    ""
    try:
        d = json.loads(grezzo)
    except Exception:
        return
    if not isinstance(d, dict):
        return
    nome = d.get("tool_name") or ""
    if nome != "Artifact" and nome not in STRUMENTI_PUBBLICA:
        return
    inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    testo = _testo(d.get("tool_response"))
    sid = d.get("session_id") or ""
    cwd = d.get("cwd") or None
    ora = time.time()
    e = _evento_pubblica(nome, inp, testo, ora, sid, cwd, "hook") or _evento_galleria(
        nome, inp, testo, ora, sid, cwd, "hook"
    )
    if not e:
        return
    acct, come = _account_slot()
    if acct:
        e["slot"] = {"account": acct, "come": come}
    with _Lucchetto():
        eventi = _unisci_eventi(_leggi_jsonl(EVENTI), [e])
        _scrivi_jsonl(EVENTI, eventi)

        vecchio = {r["id"]: r for r in _leggi_jsonl(REGISTRO)}
        nuovo = componi_registro(eventi, None)
        toccati = {e["id"]} if e.get("tipo") == "pubblica" else set((e.get("pagine") or {}).keys())
        for r in nuovo:
            v = vecchio.get(r["id"])
            if r["id"] not in toccati and v:
                continue
            if v and _RANGO.get(v.get("certezza"), 0) > _RANGO.get(r.get("certezza"), 0):
                for k in ("account", "certezza", "come"):
                    r[k] = v.get(k)
            if e.get("tipo") == "pubblica" and r["id"] == e["id"]:
                r.update(copia_pagina(r, _ultimo_uso(nuovo)))
            else:
                for k in ("copia", "copia_vid", "copia_quando", "copia_dopo", "copia_vecchia"):
                    if v and v.get(k) is not None:
                        r[k] = v[k]
            vecchio[r["id"]] = r
        righe = sorted(vecchio.values(), key=lambda r: r.get("ultima") or "", reverse=True)
        _scrivi_jsonl(REGISTRO, righe)





def _locale(iso: str | None) -> datetime.datetime | None:
    t = _epoch(iso)
    return datetime.datetime.fromtimestamp(t).astimezone() if t is not None else None


def _quando_testo(d: datetime.datetime | None) -> str:
    if not d:
        return ""
    oggi = datetime.datetime.now().astimezone().date()
    g = d.date()
    if g == oggi:
        return f"today at {d:%H:%M}"
    if g == oggi - datetime.timedelta(days=1):
        return f"yesterday at {d:%H:%M}"
    return f"{MESI[g.month - 1]} {g.day}"


def _gruppo_data(d: datetime.datetime | None) -> tuple[int, str]:
    if not d:
        return 9, "No date"
    giorni = (datetime.datetime.now().astimezone().date() - d.date()).days
    if giorni <= 0:
        return 0, "Today"
    if giorni == 1:
        return 1, "Yesterday"
    if giorni < 7:
        return 2, "This week"
    if giorni < 31:
        return 3, "This month"
    return 4, "Earlier"


def _del(d: datetime.datetime | None) -> str:
    ""
    if not d:
        return "no date"
    giorni = (datetime.datetime.now().astimezone().date() - d.date()).days
    if giorni == 0:
        return f"from today at {d:%H:%M}"
    if giorni == 1:
        return f"from yesterday at {d:%H:%M}"
    return f"from {MESI[d.month - 1]} {d.day} at {d:%H:%M}"


def _metti_famiglie(pagine: list, famiglia_di: dict) -> None:
    ""


    gruppi: dict[str, list] = {}
    for p in pagine:
        gruppi.setdefault(famiglia_di.get(p["id"], p["id"]), []).append(p)
    for membri in gruppi.values():
        capo = max(membri, key=lambda p: (p["principale"], p["quando"]))
        for p in membri:
            p["famiglia"] = capo["id"] if len(membri) > 1 else ""
            p["capofamiglia"] = p is capo
            p["versioni_famiglia"] = []
        contano = len(membri) if len(membri) > 1 else capo["versioni"]
        if len(membri) > 1:
            capo["versioni_famiglia"] = [
                {
                    "id": p["id"],
                    "url": p["url"],
                    "titolo": p["titolo"],
                    "quando": p["quando"],
                    "account": p["account"],
                    "principale": p["principale"],
                    "copia": p["copia"],
                    "frase": f"Version {_del(p['_d'])}, "
                    + (
                        "on your main account"
                        if p["principale"]
                        else (p["dove"] or "unknown account")
                    ),
                }
                for p in sorted(membri, key=lambda p: p["quando"], reverse=True)
            ]

            if capo["raccolta"]:
                capo["titolo"] = RACCOLTE[capo["raccolta"]]["nome"]
        for p in membri:
            n = contano if p is capo else p["versioni"]
            p["contesto"] = ", ".join(p["_contesto"] + ([f"{n} versions"] if n > 1 else []))

            p["riga"] = " · ".join(
                p["_breve"]
                + ([f"{n} versions"] if n > 1 else [])
                + ([p["dove"]] if p["dove"] else [])
            )

            p["testa"] = " · ".join(p["_contesto"] + [p["dove"] or "on your main account"])
    for p in pagine:
        for k in ("_contesto", "_breve", "_d"):
            p.pop(k, None)


def _quando_breve(d: datetime.datetime | None) -> str:
    ""
    if not d:
        return ""
    oggi = datetime.datetime.now().astimezone().date()
    if d.date() == oggi:
        return f"{d:%H:%M}"
    if d.date() == oggi - datetime.timedelta(days=1):
        return f"yesterday {d:%H:%M}"
    breve = f"{MESI[d.month - 1][:3]} {d.day}"
    return breve if d.year == oggi.year else f"{breve} {d.year}"


def _solo_online(chi: str) -> str:
    ""
    if chi:
        return f"This page opens only online, with {chi}."
    return "This page opens only online, and it's no longer known with which account."


def _frase_certezza(certezza: str, come: str) -> str:
    if certezza == "certo":
        return ""
    if certezza == "storico":
        return "Account reconstructed from the subscription moves, not read at the time."
    return "Account unknown. If it doesn't open online, try the other accounts."


def stato() -> dict:
    ""
    registro = _leggi_jsonl(REGISTRO)
    snap = _leggi_json(SNAPSHOT, {})
    conti = {}
    for a in snap.get("accounts") or [] if isinstance(snap, dict) else []:
        if isinstance(a, dict) and a.get("id"):
            conti[a["id"]] = {"email": a.get("email") or "", "nome": a.get("label") or a["id"]}


    doppi = {}
    for info in conti.values():
        if info["email"]:
            doppi[info["email"]] = doppi.get(info["email"], 0) + 1
    for chi, info in conti.items():
        if chi != ACCOUNT_PRINCIPALE and info["email"] and doppi[info["email"]] > 1:
            nome = re.sub(r"^\d+\s*|\s*★\s*", "", str(info["nome"])).strip()
            info["email"] = f"{info['email']} ({nome})" if nome else info["email"]
    pagine = []
    per_account: dict[str, int] = {}
    for r in registro:
        acct = r.get("account")
        info = conti.get(acct or "", {})
        email = info.get("email") or ""
        d = _locale(r.get("ultima"))
        ordine, gruppo = _gruppo_data(d)
        copia = os.path.join(BASE, r["copia"]) if r.get("copia") else None
        if copia and not os.path.exists(copia):
            copia = None
        if acct:
            if email:
                frase_account = f"Online with {email}"
            else:
                frase_account = f"Online with the account {acct}"
        else:
            frase_account = "Account unknown"
        principale = acct == ACCOUNT_PRINCIPALE
        vers = r.get("versioni") or []
        n_copia = next(
            (v.get("n") for v in vers if v.get("vid") and v.get("vid") == r.get("copia_vid")), None
        )
        n_online = vers[-1].get("n") if vers else None
        if copia and r.get("copia_vecchia") and n_copia and n_online:
            frase_copia = f"This is the copy of version {n_copia}. Online there is {n_online}."
        elif copia and r.get("copia_vecchia"):
            frase_copia = "The copy on the Mac is of an earlier version."
        elif copia and r.get("copia_dopo"):
            frase_copia = "The copy on the Mac may be newer than the online one."
        elif copia:
            frase_copia = ""
        else:
            frase_copia = TESTI["senza_copia"]
        contesto = [x for x in (r.get("conversazione") or r.get("progetto"), _quando_testo(d)) if x]
        chiave_acct = acct or ""
        per_account[chiave_acct] = per_account.get(chiave_acct, 0) + 1

        if principale:
            dove = ""
        elif acct:
            dove = f"on {email or acct}"
        else:
            dove = "unknown account"
        pagine.append(
            {
                "id": r["id"],
                "url": r.get("url") or "",
                "titolo": r.get("titolo") or r["id"],
                "contesto": ", ".join(contesto),
                "descrizione": r.get("descrizione") or "",
                "quando": r.get("ultima") or "",
                "gruppo_data": gruppo,
                "ordine_data": ordine,
                "account": chiave_acct,
                "email": email,
                "frase_account": frase_account,
                "principale": principale,
                "certezza": r.get("certezza") or "non_noto",
                "frase_certezza": _frase_certezza(r.get("certezza") or "", r.get("come") or ""),
                "come": r.get("come") or "",
                "copia": copia,
                "frase_copia": frase_copia,
                "versioni": r.get("n_versioni") or 0,
                "raccolta": _raccolta(r),
                "giusta": False,
                "progetto": r.get("progetto") or "",
                "prova": _prova(r),
                "dove": dove,

                "copia_vecchia": bool(copia and r.get("copia_vecchia")),
                "solo_online": "" if copia else _solo_online(email or acct),
                "_contesto": contesto,
                "_breve": [
                    x for x in (r.get("conversazione") or r.get("progetto"), _quando_breve(d)) if x
                ],
                "_d": d,
            }
        )

    for nome in RACCOLTE:
        voci = [p for p in pagine if p["raccolta"] == nome]
        if voci:
            max(voci, key=lambda p: (p["principale"], p["quando"]))["giusta"] = True
    _metti_famiglie(pagine, _famiglie(registro))
    account = []

    for acct, quante in sorted(
        per_account.items(), key=lambda x: (x[0] != ACCOUNT_PRINCIPALE, not x[0], -x[1], x[0])
    ):
        info = conti.get(acct, {})
        email = info.get("email") or ""
        if not acct:
            titolo = "Account unknown"
        elif acct == ACCOUNT_PRINCIPALE:
            titolo = f"On {email or acct}, {TESTI['principale']}"
        else:
            titolo = f"On {email or acct}"
        account.append({"id": acct, "titolo": titolo, "email": email, "pagine": quante})
    n = len(pagine)
    k = len([a for a in per_account if a])
    if n == 0:
        verdetto = TESTI["nessuna"]
    elif n == 1:
        verdetto = "One page."
    else:
        verdetto = (
            f"{n} pages on {k} accounts." if k > 1 else f"{n} pages, all on the same account."
        )
    altri = sum(1 for p in pagine if p["account"] and not p["principale"])
    ignoti = sum(1 for p in pagine if not p["account"])
    con_copia = sum(1 for p in pagine if p["copia"])
    frasi = []
    if altri == 1:
        frasi.append("One is on another account, online it opens only with the one written next to it.")
    elif altri > 1:
        frasi.append(
            f"{altri} are on other accounts, online they open only with the one written next to them."
        )
    if ignoti == 1:
        frasi.append("For one it's no longer known which account it was made with.")
    elif ignoti > 1:
        frasi.append(f"For {ignoti} it's no longer known which account they were made with.")
    if n and con_copia == n:
        frasi.append("All have the copy on the Mac and read here without sign-in.")
    elif con_copia == 1:
        frasi.append("One has the copy on the Mac and reads here without sign-in.")
    elif con_copia:
        frasi.append(f"{con_copia} have the copy on the Mac and read here without sign-in.")
    spiegazione = " ".join(frasi)
    try:
        letto = datetime.datetime.fromtimestamp(os.path.getmtime(REGISTRO)).astimezone()
        letto_testo = f"Registry updated {_quando_testo(letto)}."
        if letto.date() != datetime.datetime.now().astimezone().date():
            letto_testo = f"Registry updated {_quando_testo(letto)} at {letto:%H:%M}."
    except OSError:
        letto_testo = "The registry isn't there yet."
    return {
        "ok": True,
        "verdetto": verdetto,
        "spiegazione": spiegazione,
        "letto": letto_testo,
        "pagine": pagine,
        "account": account,
        "errori": [],
        "testi": TESTI,


        "cartella": BASE,
        "registro": REGISTRO,
    }


def per_app(rileggi: bool = False) -> dict:
    ""

    if rileggi:
        ricostruisci_in_sottofondo(minimo=0)
    return stato()


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "registra":
        try:
            registra(sys.stdin.read(5 * 1024 * 1024))
        except Exception as e:
            _errore(f"registra: {e!r}")
        return 0
    if cmd == "ricostruisci":
        out = ricostruisci(tutto="--tutto" in argv, copie="--senza-copie" not in argv)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if cmd == "ricostruisci-staccata":
        return _ricostruisci_staccata()
    if cmd == "json":
        print(json.dumps(per_app("--rileggi" in argv), ensure_ascii=False))
        return 0
    print(
        "usage: sb_pagine.py registra < hook.json | ricostruisci [--tutto] [--senza-copie] | json [--rileggi]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
