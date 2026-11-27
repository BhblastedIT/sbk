#!/usr/bin/env python3
"""L0 refresh: downloads every connected source in the registry (tools/sorgenti.py) one after the other, with a
diary per run that a later run resumes from; --dry-run prints the plan, --check only checks that every live source
is in the plan, --then-ingest runs the ingest afterwards. When enabled_sources (sbk.config.json) is set, only the
sources it lists are planned; empty = every source.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import sorgenti  # noqa: E402

from sbk_config import DATA_ROOT, ENABLED_SOURCES, source_enabled, source_listed  # noqa: E402

PY = ["uv", "run", "python"]


@dataclass(frozen=True)
class Passo:
    sorgente: str
    nome: str
    args: tuple[str, ...]
    timeout_s: int = 3600




PIANO: tuple[Passo, ...] = (



    Passo("calendar", "calendar", ("tools/calendar/ca-l0-download.py",)),
    # every mailbox you signed in with tools/email/em-l0-auth.py <label>
    Passo("email", "email", ("tools/email/em-l0-download.py", "--all"), 4 * 3600),

    Passo("email", "email-allegati", ("tools/email/em-l0-allegati.py",), 3 * 3600),
    # every mailbox you signed in with tools/microsoft365/ms-l0-auth.py --account <label>
    # and listed in microsoft365.accounts (sbk.config.json)
    Passo(
        "microsoft365", "microsoft365", ("tools/microsoft365/ms-l0-download.py", "--all"), 4 * 3600
    ),
    # every account in imap_caldav.accounts (sbk.config.json)
    Passo("imap-caldav", "imap-caldav", ("tools/imap-caldav/ic-l0-download.py",), 4 * 3600),
    # every label in teams.accounts, signed in with tools/teams/tm-l0-auth.py --account <label>
    Passo("teams", "teams", ("tools/teams/tm-l0-download.py", "--all"), 2 * 3600),
    # every label in contacts.google_accounts; none listed = nothing to do (exit 0). The exports
    # you make are imported by hand with tools/contacts/ct-l0-import.py
    Passo("contacts", "contacts-google", ("tools/contacts/ct-l0-download.py", "--all"), 1800),
    Passo("slack", "slack-index", ("tools/slack/sl-l0-channel-index.py",)),
    Passo(
        "slack", "slack-canali", ("tools/slack/sl-l0-download.py", "--refresh-channels"), 4 * 3600
    ),
    Passo("slack", "slack-dm", ("tools/slack/sl-l0-download-dm.py",)),
    Passo(
        "attio",
        "attio",
        ("tools/attio/at-l0-download.py", "--workspace", "all", "--retry-stubs"),
        2 * 3600,
    ),
    Passo("hubspot", "hubspot", ("tools/hubspot/hs-l0-download.py",), 2 * 3600),
    # a run that reaches pipedrive.max_requests_per_run stops and the next run continues
    Passo("pipedrive", "pipedrive", ("tools/pipedrive/pd-l0-download.py", "--quiet"), 1800),
    Passo(
        "clickup",
        "clickup",
        ("tools/clickup/cu-l0-backup.py", "--team", "all", "--incremental"),
        8 * 3600,
    ),
    Passo("atlassian", "atlassian", ("tools/atlassian/as-l0-download.py", "--quiet"), 1800),
    Passo("linear", "linear", ("tools/linear/ln-l0-download.py", "--quiet"), 1800),
    Passo("personio", "personio", ("tools/personio/pe-l0-download.py",)),
    Passo("whoop", "whoop", ("tools/whoop/wp-l0-download.py", "--days", "30"), 1800),


    Passo("plaud", "plaud", ("tools/plaud/pl-l0-download.py", "--direct"), 2 * 3600),
    Passo("tactiq", "tactiq", ("tools/tactiq/tq-l0-download.py", "--direct"), 2 * 3600),
    Passo("zoom", "zoom", ("tools/zoom/zm-l0-download.py",), 2 * 3600),
    Passo("fireflies", "fireflies", ("tools/fireflies/ff-l0-download.py",), 2 * 3600),
    Passo("fathom", "fathom", ("tools/fathom/fa-l0-download.py",), 2 * 3600),
    # the API route (personal key, Business plan); the free plan's CSV export is imported by hand
    Passo("granola", "granola", ("tools/granola/gr-l0-download.py",), 2 * 3600),
    Passo("docusign", "docusign", ("tools/docusign/ds-l0-api.py",)),

    Passo("docusign", "docusign-pdf", ("tools/docusign/ds-l0-pdf.py",), 2 * 3600),
    # repositories (repos.json, read by the inventory L1), collaborators, issues, PRs and
    # reviews; folders and README too when github.trees is true in sbk.config.json
    Passo("github", "inv-github", ("tools/github/gh-l0-download.py",), 1800),
    Passo("gsc", "inv-gsc", ("tools/gsc/gs-l0-inventory.py",), 1800),
    Passo("analytics", "inv-analytics", ("tools/analytics/ga-l0-inventory.py",), 1800),



    Passo(
        "gdrive",
        "gdrive",
        ("tools/gdrive/gd-l0-download.py", "--mode", "full-sync", "--days", "0"),
        8 * 3600,
    ),
)


# Downloads that read a login session of an app or a browser on this Mac. They are planned and
# run only when the source is written in enabled_sources (sbk.config.json): an empty list does
# not switch them on. The text says exactly what each one reads.
SESSIONE: dict[str, str] = {
    "plaud": "reads the session token of the Plaud desktop app on this Mac "
    "(tools/plaud/pl_auth_refresh.py; a copy in <data root>/secrets/plaud-wt.json)",
    "tactiq": "reads the Tactiq refresh token from Chrome's storage for app.tactiq.io "
    "(Chrome IndexedDB; a copy in the Keychain entry sbk-tactiq/refresh-token)",
}


def solo_se_elencate(piano: list[Passo]) -> tuple[list[Passo], list[str]]:
    """Drop the session-based downloads whose source is not in enabled_sources."""
    fuori = sorted(
        {p.sorgente for p in piano if p.sorgente in SESSIONE and not source_listed(p.sorgente)}
    )
    return [p for p in piano if p.sorgente not in fuori], fuori


def solo_abilitate(piano: list[Passo]) -> tuple[list[Passo], list[str]]:
    """When enabled_sources is set, drop the downloads of the sources it does not list.

    An empty or missing enabled_sources keeps every download (as before the field was read),
    except the session-based ones, which solo_se_elencate() handles.
    """
    if not ENABLED_SOURCES:
        return piano, []
    fuori = sorted({p.sorgente for p in piano if not source_enabled(p.sorgente)})
    return [p for p in piano if p.sorgente not in fuori], fuori


MANUALI: dict[str, str] = {
    "whatsapp": "L0 = chat exports you make on the phone (imported by wa-l0l3-full.py, or wa-l0-import-history.py for a bulk text export)",
    "voicememos": "L0 = copy of the .m4a files into voice-memos/: the system folder is TCC-protected",
    "linkedin": "no bulk automation (rate-limit / ToS risk): manual export only",
    "ai-history": "on request: you run ai-l0-claude-code.py and import your AI chat exports; "
    "the identity step that calls a model needs your --yes, so it never runs in the full run",
    "databases": "on request: it runs the queries you declared in sbk.config.json against your own "
    "database; run db-l0-download.py (then db-l1-enrich.py) when you want it read",
    "telegram": "L0 = the data export you make in Telegram Desktop (Machine-readable JSON), imported "
    "by tg-l0-import.py <export folder>; nothing to download",
}


def controlla_copertura() -> list[str]:
    ""
    nel_piano = {p.sorgente for p in PIANO}
    return sorted(
        sid
        for sid, s in sorgenti.SORGENTI.items()
        if s.natura in ("continua", "periodica", "a_richiesta", "spot")
        and sid not in nel_piano
        and sid not in MANUALI
    )


def _cartella_di_default() -> Path:
    # The callers create it (mkdir parents=True).
    return DATA_ROOT / "work" / "sbk" / "default" / f"{datetime.now():%Y-%m-%d}-l0-refresh"


# Words of the run diary (esiti.tsv) and of the attempt header of a step log. Diaries and logs
# written before these English words used "INIZIO", "FINE", "tent.N", "── tentativo N",
# "solo L0" and "poi-ingest"/"poi-tutto": the readers (sb_ripresa, sb_errori, sb-app) accept both.
DIARIO_INIZIO = "START"
DIARIO_FINE = "END"
DIARIO_SOLO_L0 = "L0 only"
DIARIO_POI_INGEST = "then-ingest"
DIARIO_POI_TUTTO = "then-all"
# Status words of a diary row. Older diaries wrote FERMATO, INTERROTTO, NON PARTITO, "non partita" and
# "ripreso": the readers accept both (sb_ripresa SEGNI_*, sb_errori, sb-app).
DIARIO_FERMATO = "STOPPED"  # END row of a run stopped on request
DIARIO_INTERROTTO = "INTERRUPTED"  # an attempt cut off before its exit code
DIARIO_NON_PARTITO = "NOT STARTED"  # END row of a download that another process already holds
DIARIO_NON_PARTITA = "not started"  # a lane that could not start
DIARIO_RIPRESO = "resumed"  # a step closed in the run being resumed


def tentativo_campo(n: int) -> str:
    """The attempt field of a diary row: "attempt.N" ("tent.N" in older diaries)."""
    return f"attempt.{n}"


def tentativo_testa(n: int, comando: list[str]) -> str:
    """The line that opens one attempt in a step log: "── attempt N · dd/mm HH:MM:SS · <command>"."""
    return f"── attempt {n} · {datetime.now():%d/%m %H:%M:%S} · {' '.join(comando)}\n"


def _esito(esiti: Path, *campi: object) -> None:
    with esiti.open("a", encoding="utf-8") as f:
        f.write("\t".join([datetime.now().strftime("%d/%m %H:%M:%S"), *map(str, campi)]) + "\n")


def _lancia(cmd: list[str], f, timeout_s: int) -> int:
    ""






    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={**os.environ, "SBK_PASSO_LOG": str(getattr(f, "name", ""))},
    )
    try:
        return proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=60)
                break
            except subprocess.TimeoutExpired:
                continue
        return 124


def _ingest_chiuso(log: Path, inizio: int) -> bool:
    ""





    testo = log.read_bytes()[inizio:].decode("utf-8", errors="replace")
    esiti = _righe_esito(testo)
    if not esiti:
        return False
    ultima = esiti[-1]
    return (
        any(x in ultima for x in ("INCOMPLETE", "INCOMPLETA"))
        and not any(x in ultima for x in ("vanished", "spariti", "skipped:", "saltati:"))
    )



# The runner's outcome line is English ("Outcome: ... sources not closed: a, b, skipped: ...");
# the Italian words of older logs ("Esito:", "fonti non chiuse", "saltati:") are still read.
_RE_FONTI_NON_CHIUSE = re.compile(
    r"(?:sources not closed|fonti non chiuse): (.*?)"
    r"(?:, (?:skipped|saltati):|, (?:warnings|avvisi):| \(exit|$)"
)


def _righe_esito(testo: str) -> list[str]:
    """The runner's outcome lines in a log ("Outcome:", or "Esito:" in older logs)."""
    return [r for r in testo.splitlines() if "Outcome:" in r or "Esito:" in r]


def fonti_non_chiuse(log: Path, inizio: int) -> str:
    ""




    testo = log.read_bytes()[inizio:].decode("utf-8", errors="replace")
    esiti = _righe_esito(testo)
    m = _RE_FONTI_NON_CHIUSE.search(esiti[-1]) if esiti else None
    return m.group(1).strip() if m else ""


def _con_ripresa(cmd: list[str], stadio: str) -> list[str]:
    ""
    fuori = {i for i, x in enumerate(cmd) if x == "--riprendi-da"}
    fuori |= {i + 1 for i in fuori}
    return [x for i, x in enumerate(cmd) if i not in fuori] + ["--riprendi-da", stadio]


def _precondizione_falsa(log: Path, inizio: int) -> str:
    ""




    testo = log.read_bytes()[inizio:].decode("utf-8", errors="replace")
    esiti = _righe_esito(testo)
    # The skip code stays "precondizione" (an internal code); "precondition" is accepted too.
    m = re.search(r"(\w+) \((?:precondizione|precondition)\)", esiti[-1]) if esiti else None
    return m.group(1) if m else ""


def esegui(
    nome: str,
    cmd: list[str],
    timeout_s: int,
    cartella: Path,
    rc_ok: tuple[int, ...] = (0,),
    riprendi: Callable[[Path], str | None] | None = None,
) -> bool:
    ""








    log = cartella / "log" / f"{nome}.log"
    esiti = cartella / "esiti.tsv"
    for tentativo in (1, 2, 3):
        comando = cmd
        if riprendi and tentativo > 1:
            try:
                stadio = riprendi(log)
            except Exception as e:  # noqa: BLE001 — without a resume point it starts over, and we say so
                stadio = None
                _esito(esiti, nome, "resume not computed", f"{type(e).__name__}: {e}")
            if stadio:
                comando = _con_ripresa(cmd, stadio)
                _esito(esiti, nome, "resume", f"{tentativo_campo(tentativo)} from {stadio}")
        t0 = time.time()
        inizio = log.stat().st_size if log.exists() else 0
        with log.open("a", encoding="utf-8") as f:
            f.write(tentativo_testa(tentativo, comando))
            f.flush()
            rc = _lancia(comando, f, timeout_s)
        nota = ""
        if rc == 2 and 2 in rc_ok and not _ingest_chiuso(log, inizio):
            nota = "rc 2 but the outcome is not only advisories (vanished or seriously skipped stages)"
        _esito(
            esiti, nome, tentativo_campo(tentativo), f"rc={rc}", f"{int(time.time() - t0)}s", nota
        )
        if rc in rc_ok and not nota:
            if rc == 2 and (ferme := fonti_non_chiuse(log, inizio)):
                _esito(esiti, nome, "sources not closed", ferme)
            return True
        if rc == 2 and (fermo := _precondizione_falsa(log, inizio)):
            _esito(
                esiti,
                nome,
                f"NOT CLOSED AFTER {tentativo} ATTEMPT{'' if tentativo == 1 else 'S'}",
                f"false precondition on {fermo}, not retrying: the fix is in the log",
            )
            return False
        if tentativo < 3:
            time.sleep(120 if rc == 75 else 60)
    _esito(esiti, nome, "NOT CLOSED AFTER 3 ATTEMPTS")
    return False




TETTO_RILETTURA_S = 24 * 3600


def ripresa_della_rilettura(modo: str) -> Callable[[Path], str | None]:
    ""




    import importlib.util

    def _carica(nome: str, percorso: Path):
        spec = importlib.util.spec_from_file_location(nome, percorso)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[nome] = mod
        spec.loader.exec_module(mod)
        return mod

    orchestratore = ROOT / "tools" / "cross-source" / "xs-pipeline-run.py"

    def _stadio(log: Path) -> str | None:
        ripresa = sys.modules.get("sb_ripresa") or _carica(
            "sb_ripresa", ROOT / "tools" / "secondbrain" / "sb_ripresa.py"
        )
        if not ripresa.orchestratore_sa_riprendere(orchestratore):
            return None
        xpr = _carica("xs_pipeline_run_per_la_ripresa", orchestratore)
        catena = [(p.id, p.nome) for p in xpr.perimetro(modo) if p.strato != "L1"]
        return ripresa.punto_di_ripresa(log, catena)

    return _stadio


# The brain copies (tars of <data root>/knowledge) live under the data root, next to the other
# KB tars that tools/util/sb-kb-ripara.py reads.
COPIE_KB = DATA_ROOT / "backups-knowledge"


def knowledge_da_proteggere() -> bool:
    """True if <data root>/knowledge holds at least one file (a store to protect)."""
    kb = DATA_ROOT / "knowledge"
    try:
        return kb.is_dir() and any(p.is_file() for p in kb.rglob("*"))
    except OSError:
        return True


def backup_kb(cartella: Path) -> bool:
    """Tar <data root>/knowledge into <data root>/backups-knowledge before the re-read.

    A missing or empty knowledge folder (a new install) is nothing to protect: no tar,
    True. A failed or interrupted copy never leaves its .parziale file behind.
    """
    esiti = cartella / "esiti.tsv"
    if not knowledge_da_proteggere():
        _esito(esiti, "backup-kb", "rc=0", "nothing to protect: no knowledge store yet")
        return True
    dest = COPIE_KB / f"knowledge-{datetime.now():%Y%m%d-%H%M}-pre-ingest.tar.gz"
    parziale = dest.with_name(dest.name + ".parziale")
    ok = False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(parziale, "w:gz") as tar:
            tar.add(DATA_ROOT / "knowledge", arcname="knowledge")
        ok = subprocess.run(["gzip", "-t", str(parziale)], timeout=1800).returncode == 0
        if ok:
            os.replace(parziale, dest)
    except (OSError, subprocess.SubprocessError, tarfile.TarError):
        ok = False
    except BaseException:
        parziale.unlink(missing_ok=True)
        _esito(esiti, "backup-kb", "INTERRUPTED", f"half copy {parziale.name} removed")
        raise
    if not ok:
        parziale.unlink(missing_ok=True)
    _esito(esiti, "backup-kb", "rc=0" if ok else "rc=1", dest.name)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "L0 refresh: runs the download (L0) of every enabled source in the registry, one after the "
            "other, and writes a diary of the outcomes. With --then-ingest it then rereads them "
            "(xs-pipeline-run.py --ingest). When enabled_sources in sbk.config.json lists "
            "sources, only those are downloaded (empty = every source). The downloads that read "
            "an app or browser session (plaud, tactiq) run only when enabled_sources lists them."
        )
    )
    ap.add_argument("--dry-run", action="store_true", help="print the plan and do not run")
    ap.add_argument(
        "--check", action="store_true", dest="controlla", help="only the registry coverage check"
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        dest="sabota",
        help="prove the coverage check sees a fake source",
    )
    ap.add_argument(
        "--only", default="", dest="solo", metavar="SOURCES", help="sources separated by commas (registry ids)"
    )
    ap.add_argument(
        "--then-ingest",
        action="store_true",
        dest="poi_ingest",
        help="after L0: KB backup and xs-pipeline-run.py --ingest",
    )
    ap.add_argument("--dir", type=Path, help="diary folder (default: the data root's run folder)")
    ap.add_argument(
        "--brain-copy",
        action="store_true",
        dest="copia_del_cervello",
        help="only the KB copy into <data root>/backups-knowledge, the safety net the re-read "
        "requires before changing it (nothing to copy on a new install)",
    )
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--controlla", action="store_true", dest="controlla", help=argparse.SUPPRESS)
    ap.add_argument("--sabota", action="store_true", dest="sabota", help=argparse.SUPPRESS)
    ap.add_argument("--solo", dest="solo", help=argparse.SUPPRESS)
    ap.add_argument("--poi-ingest", action="store_true", dest="poi_ingest", help=argparse.SUPPRESS)
    ap.add_argument(
        "--copia-del-cervello", action="store_true", dest="copia_del_cervello", help=argparse.SUPPRESS
    )
    args = ap.parse_args()

    if args.copia_del_cervello:



        cartella = args.dir or _cartella_di_default()
        cartella.mkdir(parents=True, exist_ok=True)
        vuoto = not knowledge_da_proteggere()
        ok = backup_kb(cartella)
        print(
            (
                "✅ brain copy: nothing to protect yet (no knowledge store), diary "
                if ok and vuoto
                else "✅ brain copy done, diary "
                if ok
                else "⛔ brain copy FAILED, diary "
            )
            + str(cartella / "esiti.tsv")
        )
        return 0 if ok else 1

    if args.sabota:
        from dataclasses import replace


        sorgenti.SORGENTI["__finta__"] = replace(sorgenti.SORGENTI["whoop"], id="__finta__")
        visto = controlla_copertura() == ["__finta__"]
        del sorgenti.SORGENTI["__finta__"]
        print(
            "✅ the check sees the fake source"
            if visto
            else "⛔ the check does NOT see the fake source"
        )
        return 0 if visto else 1

    mancanti = controlla_copertura()
    if mancanti:
        print(f"⛔ live sources outside the run and not declared manual: {', '.join(mancanti)}")
        print(
            "   add them to PIANO or MANUALI (with the reason) in tools/cross-source/xs-l0-refresh.py"
        )
        return 2
    if args.controlla:
        print(
            f"✅ coverage: {len({p.sorgente for p in PIANO})} sources in the run, {len(MANUALI)} declared manual"
        )
        return 0

    solo = {s.strip() for s in args.solo.split(",") if s.strip()}
    ignote = solo - {p.sorgente for p in PIANO}
    if ignote:
        print(f"sources not in the plan: {', '.join(sorted(ignote))}")
        return 2
    piano = [p for p in PIANO if not solo or p.sorgente in solo]
    # Session-based downloads (Plaud app, Tactiq in Chrome): only when enabled_sources lists them,
    # also with --only.
    piano, sessione_fuori = solo_se_elencate(piano)
    # enabled_sources set: only the sources it lists (also with --only). Empty = every source.
    piano, non_abilitate = solo_abilitate(piano)


    import impostazioni_pipeline

    piano = impostazioni_pipeline.applica_al_piano(piano)

    if args.dry_run:
        for p in piano:
            print(f"{p.nome:16} {p.timeout_s // 60:4d} min  {' '.join(p.args)}")
        for sid in sessione_fuori:
            print(
                f"{'(not run) ' + sid:16}           {SESSIONE[sid]}: it runs only when "
                f'"{sid}" is in enabled_sources (sbk.config.json)'
            )
        for sid in non_abilitate:
            print(f"{'(not run) ' + sid:16}           not in enabled_sources (sbk.config.json)")
        for sid, perche in MANUALI.items():
            print(f"{'(manual) ' + sid:16}           {perche}")
        if args.poi_ingest:
            print(
                "then: KB backup, xs-pipeline-run.py --ingest (SBK_L1_SEQUENZIALE=1, paid stages left out)"
            )
        return 0



    import un_run_alla_volta

    from sbk_config import acquire_pid_lock

    if not os.environ.get("SBK_RUN_ID") and (chi := un_run_alla_volta.chi_gira()):
        print(
            f"⛔ not starting: {', '.join(chi)} already running. One run at a time: retry when it has finished (lock held)."
        )
        return 75
    if not acquire_pid_lock("l0-refresh"):
        print(
            "⛔ not starting: another download run holds the l0-refresh lock. Retry when it has finished."
        )
        return 75

    os.environ["SBK_GIRO_PID"] = str(os.getpid())


    if shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])

    cartella = args.dir or _cartella_di_default()
    (cartella / "log").mkdir(parents=True, exist_ok=True)
    esiti = cartella / "esiti.tsv"


    diario = un_run_alla_volta.diario_inizio("giro", cartella=str(cartella))
    _esito(
        esiti,
        DIARIO_INIZIO,
        f"{len(piano)} steps",
        DIARIO_POI_INGEST if args.poi_ingest else DIARIO_SOLO_L0,
    )
    for sid, perche in MANUALI.items():
        _esito(esiti, f"manual:{sid}", "outside the run", perche)
    for sid in sessione_fuori:
        _esito(esiti, f"session:{sid}", "not run, not in enabled_sources", SESSIONE[sid])
    for sid in non_abilitate:
        _esito(esiti, f"not-enabled:{sid}", "not run, not in enabled_sources")

    non_chiusi = [
        p.nome for p in piano if not esegui(p.nome, [*PY, *p.args], p.timeout_s, cartella)
    ]

    if args.poi_ingest:
        if not backup_kb(cartella):
            non_chiusi.append("backup-kb")
            _esito(esiti, "ingest", "NOT LAUNCHED: KB backup failed")
        else:
            os.environ["SBK_L1_SEQUENZIALE"] = "1"
            rilettura = [*PY, "tools/cross-source/xs-pipeline-run.py", "--ingest"]
            if non_chiusi:

                rilettura += ["--scarico-non-chiuso", ",".join(non_chiusi)]

            if not esegui(
                "ingest",
                rilettura,
                TETTO_RILETTURA_S,
                cartella,
                rc_ok=(0, 2),
                riprendi=ripresa_della_rilettura("ingest"),
            ):
                non_chiusi.append("ingest")

    _esito(esiti, DIARIO_FINE, "not closed: " + (", ".join(non_chiusi) or "none"))
    print(f"diary: {esiti}")
    rc = 1 if non_chiusi else 0
    un_run_alla_volta.diario_fine(diario, rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
