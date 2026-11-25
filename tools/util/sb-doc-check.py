#!/usr/bin/env python3
"""Checks that the docs have not gone false: compares the verifiable claims in CLAUDE.md and the skills with this machine."""



































from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
HOME = Path.home()
# Claude Code keeps a project's memory under ~/.claude/projects/<path with "-" for "/" and ".">.
MEMORY_DIR = HOME / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(PROJECT)) / "memory"


DOCS = [
    PROJECT / "CLAUDE.md",
    HOME / ".claude" / "CLAUDE.md",
]


IGNORE_LABELS = {
    "com.apple",
    "com.google",
    "com.docker",
    "com.cloudflare",
    "com.anthropic",
    "application.com",
}


SKIP_PATH_HINTS = ("{", "}", "<", ">", "*", "$", "…", "...", "esempio", "example")




NEGATION_MARKERS = (
    "non esiste",
    "non e' piu'",
    "non è più",
    "non c'e' piu'",
    "non c'è più",
    "rimosso",
    "rimossi",
    "eliminato",
    "eliminati",
    "cancellato",
    "cancellati",
    "dismesso",
    "deprecato",
    "non riproporlo",
    "non reperibile",
    "mai stato",
    "~~",
)


def _is_negated(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in NEGATION_MARKERS)


def _launchd_labels_present() -> set[str]:
    ""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=20)
    except (subprocess.SubprocessError, OSError):
        return set()
    labels = set()
    for line in out.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3:
            labels.add(parts[2])
    return labels


def _plist_files() -> set[str]:
    ""
    out = set()
    for d in (HOME / "Library" / "LaunchAgents", Path("/Library/LaunchDaemons")):
        if not d.exists():
            continue
        for f in d.iterdir():
            n = f.name
            if ".plist" in n:
                out.add(n.split(".plist")[0])
    return out


SKILLS_DIR = PROJECT / ".claude" / "skills"
AGENTS_DIR = PROJECT / ".claude" / "agents"


def _iter_docs() -> list[Path]:
    docs = [d for d in DOCS if d.exists()]
    if MEMORY_DIR.exists():
        docs += sorted(MEMORY_DIR.glob("*.md"))

    if SKILLS_DIR.exists():
        docs += sorted(SKILLS_DIR.glob("*/SKILL.md"))

    if AGENTS_DIR.exists():
        docs += sorted(AGENTS_DIR.glob("*.md"))
    return docs


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(HOME).as_posix()).replace("Projects/SBK/", "")
    except ValueError:
        return str(p)


def check_launchd(docs: list[Path]) -> list[dict]:
    ""
    loaded = _launchd_labels_present()
    onfile = _plist_files()
    pat = re.compile(r"\bcom\.[a-z0-9]+\.[a-z0-9][a-z0-9._-]*\b", re.I)
    problems = []
    seen: dict[str, list[str]] = {}
    for d in docs:
        try:
            text = d.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _is_negated(line):
                continue
            for label in pat.findall(line):
                label = label.rstrip(".")
                if any(label.startswith(p) for p in IGNORE_LABELS):
                    continue
                if label.endswith((".plist", ".py", ".sh", ".md", ".json")):
                    label = label.rsplit(".", 1)[0]
                seen.setdefault(label, []).append(f"{_rel(d)}:{i}")
    for label, where in sorted(seen.items()):
        if label in loaded:
            continue
        if label in onfile:
            problems.append(
                {
                    "sev": "info",
                    "what": f"agent '{label}' exists but is NOT loaded in launchd",
                    "where": where[:3],
                }
            )
        else:
            problems.append(
                {
                    "sev": "stale",
                    "what": f"agent '{label}' NO longer exists (neither loaded nor as a file)",
                    "where": where[:3],
                }
            )
    return problems





SEARCH_ROOTS = [
    PROJECT,
    HOME / "Projects",
    HOME / ".other-ide" / "worktrees",
    HOME / ".sbk-data" / "work" / "personal",
    HOME / ".sbk-data" / "docs",
    HOME / ".claude",
    HOME / "Downloads",
    HOME / "Desktop",
    HOME / "Backups",
    HOME / ".config",



    HOME / ".sbk-credentials",
]



POLICY_EXCLUDED = (
    "~/.sbk-credentials",
    "Keychain",
)


def _repo_basenames() -> dict[str, int]:
    ""




    idx: dict[str, int] = {}
    skip_dirs = {
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        ".next",
        "dist",
        "build",
        "site-packages",
        ".cache",
        "Caches",
    }
    for root_dir in SEARCH_ROOTS:
        if not root_dir.exists():
            continue
        for root, dirs, files in os.walk(root_dir):

            if root.count(os.sep) - str(root_dir).count(os.sep) > 6:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                idx[f] = idx.get(f, 0) + 1
    return idx


def _is_example_path(raw: str, line: str) -> bool:
    ""







    if re.search(r"\.[0-9a-f]{6,}\.", raw):
        return True

    if re.search(r"del\s+repo\s+[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+", line):
        return True
    return False


def _resolve_bare_name_in_context(raw: str, doc_lines: list, line_idx: int) -> bool:
    ""






    dir_pat = re.compile(r"`(~?/[~\w./-]+/)`|`(~?/[~\w./-]+)`")
    start = max(0, line_idx - 5)
    for li in range(start, line_idx):
        if li >= len(doc_lines):
            break
        for m in dir_pat.finditer(doc_lines[li]):
            d = m.group(1) or m.group(2)
            if d:
                d = d.rstrip("/")
                expanded = os.path.expanduser(d)
                candidate = os.path.join(expanded, raw)
                if os.path.exists(candidate):
                    return True
    return False


def check_paths(docs: list[Path]) -> list[dict]:
    ""









    pat = re.compile(r"`([~\w./-]+\.(?:py|sh|md|json|js|ts|yml|yaml|toml|parquet|db))`")
    basenames = _repo_basenames()
    problems = []
    seen: dict[str, list[str]] = {}

    resolved_ok: set = set()

    doc_lines_cache: dict = {}

    raw_context: dict = {}

    for d in docs:
        try:
            text = d.read_text(errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        doc_lines_cache[str(d)] = lines
        for i, line in enumerate(lines):
            if _is_negated(line):
                continue
            for raw in pat.findall(line):
                if any(h in raw for h in SKIP_PATH_HINTS):
                    continue

                if _is_example_path(raw, line):
                    continue
                seen.setdefault(raw, []).append(f"{_rel(d)}:{i + 1}")
                raw_context.setdefault(raw, []).append((str(d), i, line))

    for raw, where in sorted(seen.items()):

        if raw.startswith(("/tmp/", "/private/tmp/")):
            continue

        if any(x in raw for x in POLICY_EXCLUDED):
            continue

        cands = []
        if raw.startswith("~"):
            cands.append(Path(os.path.expanduser(raw)))
        elif raw.startswith("/"):
            cands.append(Path(raw))
        else:
            cands += [PROJECT / raw, HOME / raw, PROJECT / "tools" / raw, PROJECT / "docs" / raw]
        if any(c.exists() for c in cands):
            resolved_ok.add(raw)
            continue


        if "/" not in raw and basenames.get(raw):
            resolved_ok.add(raw)
            continue


        if "/" not in raw:
            ctx_list = raw_context.get(raw, [])
            found_in_context = False
            for doc_path, line_idx, _line_text in ctx_list:
                doc_lines = doc_lines_cache.get(doc_path, [])
                if _resolve_bare_name_in_context(raw, doc_lines, line_idx):
                    found_in_context = True
                    break
            if found_in_context:
                resolved_ok.add(raw)
                continue


        base = raw.rsplit("/", 1)[-1]
        if basenames.get(base):
            problems.append(
                {
                    "sev": "info",
                    "what": f"path maybe moved: {raw} (the file '{base}' exists, but not there)",
                    "where": where[:3],
                }
            )
            continue



        if "/" not in raw and any(r.endswith("/" + raw) for r in resolved_ok):
            continue

        sev = "info" if raw.endswith((".parquet", ".db", ".json")) else "stale"
        problems.append(
            {"sev": sev, "what": f"path cited but nonexistent: {raw}", "where": where[:3]}
        )
    return problems








MODULI_CONDIVISI = ("secrets_adapter.py", "sbk_config.py", "sbk_resources.py")


def check_python39() -> list[dict]:
    ""
    sysp = "/usr/bin/python3"
    if not Path(sysp).exists():
        return []
    problemi = []
    tools_dir = PROJECT / "tools"
    for nome in MODULI_CONDIVISI:
        f = tools_dir / nome
        if not f.exists():
            continue
        r = subprocess.run(
            [sysp, "-c", f"import sys; sys.path.insert(0, {str(tools_dir)!r}); import {f.stem}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            ultima = (r.stderr or "").strip().splitlines()[-1:] or [""]
            problemi.append(
                {
                    "sev": "stale",
                    "what": f"`{nome}` does NOT import on {sysp}: {ultima[0][:90]}",
                    "where": [f"tools/{nome}  → whoever uses it with `python3` crashes"],
                }
            )
    return problemi















LIVESTATE = Path(os.environ.get("SB_LIVE_STATE", PROJECT / "sbk" / "context" / "live-state.md"))
SESSIONLOG = Path(
    os.environ.get("SB_SESSION_LOG", PROJECT / "sbk" / "context" / "sessions" / "SESSION-LOG.md")
)











if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))
import sbk_config as cfg  # noqa: E402




LIVESTATE_MAX_LINES = cfg.LIVESTATE_MAX_LINES
LIVESTATE_MAX_BYTES = cfg.LIVESTATE_MAX_BYTES


LIVESTATE_MAX_AGE_DAYS = cfg.LIVESTATE_MAX_AGE_DAYS



NOW_START = cfg.SB_NOW_START
NOW_END = cfg.SB_NOW_END




KEEP_START = cfg.SB_KEEP_START
KEEP_END = cfg.SB_KEEP_END

DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


























WAIT_START = cfg.SB_WAIT_START
WAIT_END = cfg.SB_WAIT_END
TEMP_RE = re.compile(r"<!--\s*SB-TEMP\s+scade=(20\d{2}-\d{2}-\d{2})\s*-->")






KEEP_MAX_AGE_DAYS = cfg.LIVESTATE_KEEP_MAX_AGE_DAYS




# Temporariness lexicon: extend from user config as needed.
TEMPORANEITA_RE = re.compile(
    r"(?i)(\bper ora\b|fino a nuovo ordine|finch[eé] (?:non arriva|non esce)"
    r"|in attesa (?:di |dell')?ok\b|questa sessione non)"
)


# Permanence lexicon: extend from user config as needed.
PERMANENZA_RE = re.compile(
    r"(?i)(\bmai\b|\bsempre\b|non negoziabile|scade[:=])"
)


def _strip_region(lines: list[str], start: str, end: str) -> list[str]:
    ""






    out, inside = [], False
    for ln in lines:
        if ln.strip() == start:
            inside = True
            continue
        if ln.strip() == end:
            inside = False
            continue
        if not inside:
            out.append(ln)
    return out





ACK_FILE = PROJECT / "sbk" / "context" / ".rimozioni-volute"


def _mask(line: str) -> str:
    ""






    out = re.sub(r"`[^`]{4,60}`", "`«mascherato»`", line)
    out = re.sub(r"\b[A-Z][a-z]{2,10}[._-]20[0-9]{2}\b", "«mascherato»", out)
    return out


def _rimozioni_ack() -> set[str]:
    ""






    if not ACK_FILE.exists():
        return set()
    out = set()
    for ln in ACK_FILE.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.add(ln.split()[0])
    return out


def _significant(line: str) -> str | None:
    ""





    s = line.strip()





    s = re.sub(r"^#{1,6}\s+", "", s)
    if len(s) < 12:
        return None
    if not re.search(r"[A-Za-zÀ-ÿ0-9]", s):
        return None
    return " ".join(s.split())


def _git_show(rev_path: str, repo: Path | None = None) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo or PROJECT), "show", rev_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_top(start: Path) -> Path | None:
    ""





    try:
        r = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def check_livestate_size() -> list[dict]:
    ""
    if not LIVESTATE.exists():
        return [{"sev": "stale", "what": "live-state.md does not exist", "where": [_rel(LIVESTATE)]}]
    problems: list[dict] = []


    n_righe, n_byte, quota, stato_tetto = cfg.livestate_misura(LIVESTATE)

    if stato_tetto == "fuori":
        problems.append(
            {
                "sev": "stale",
                "what": (
                    f"live-state.md has REGROWN: {n_righe} lines / {n_byte:,} bytes "
                    f"(cap {LIVESTATE_MAX_LINES} lines / {LIVESTATE_MAX_BYTES:,} bytes). "
                    "Closed blocks are MOVED verbatim to sessions/SESSION-LOG.md "
                    "(not summarized, not deleted): "
                    "`uv run python tools/infrastructure/sb-state-rotate.py --apply --stub-recent`."
                ),
                "where": [f"{_rel(LIVESTATE)}:1"],
            }
        )
    elif stato_tetto == "avviso":
        problems.append(
            {
                "sev": "info",








                "what": (
                    f"live-state.md: {quota:.0%} of the cap "
                    f"({n_righe} lines / {n_byte:,} bytes, "
                    f"{cfg.LIVESTATE_MAX_BYTES - n_byte:,} left). "
                    "When needed: `uv run python tools/infrastructure/sb-state-rotate.py --apply --stub-recent`."
                ),
                "where": [f"{_rel(LIVESTATE)}:1"],
            }
        )

    return problems


def check_livestate_age(today: datetime.date | None = None) -> list[dict]:
    ""
    if not LIVESTATE.exists():
        return []
    today = today or datetime.date.today()
    lines = LIVESTATE.read_text(errors="replace").splitlines()
    lines = _strip_region(lines, NOW_START, NOW_END)
    lines = _strip_region(lines, KEEP_START, KEEP_END)

    lines = _strip_region(lines, WAIT_START, WAIT_END)
    vecchi: list[tuple[str, str]] = []
    for i, ln in enumerate(lines, 1):
        if not ln.startswith("## "):
            continue
        m = DATE_RE.search(ln)
        if not m:
            continue
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        age = (today - d).days
        if age > LIVESTATE_MAX_AGE_DAYS:
            vecchi.append((f"{ln[:80]} — {age} days ago", f"{_rel(LIVESTATE)}:~{i}"))
    if not vecchi:
        return []
    return [
        {
            "sev": "stale",
            "what": (
                f"{len(vecchi)} blocks older than {LIVESTATE_MAX_AGE_DAYS} days still in "
                "live-state.md. Move them VERBATIM to sessions/SESSION-LOG.md. "
                f"(If a decision is still OPEN, it goes between {KEEP_START} and {KEEP_END}, "
                "not archived.)"
            ),
            "where": [f"{w} · {t}" for t, w in vecchi[:6]],
        }
    ]


def check_livestate_pavimento() -> list[dict]:
    ""










    if not LIVESTATE.exists():
        return []
    top = _git_top(LIVESTATE)
    if not top:
        return []
    try:
        rel = str(LIVESTATE.relative_to(top))
    except ValueError:
        return []
    head = _git_show(f"HEAD:{rel}", repo=top)
    if head is None:
        return []
    prima, dopo = len(head), LIVESTATE.stat().st_size
    if prima < 2000 or dopo >= prima * 0.7:
        return []
    return [
        {
            "sev": "stale",
            "what": (
                f"live-state.md has COLLAPSED: {prima:,} → {dopo:,} bytes "
                f"({100 * (prima - dopo) // prima}% less than HEAD). A real prune "
                "goes through rotation, which has its own gate: this looks like a truncation. "
                f"Check with `git diff {rel}` before committing."
            ),
            "where": [_rel(LIVESTATE)],
        }
    ]


def check_livestate_no_loss() -> list[dict]:
    ""






    problems: list[dict] = []
    top = _git_top(LIVESTATE.parent if LIVESTATE.exists() else PROJECT)
    if top is None:
        return []
    pairs: list[tuple[Path, str]] = []
    for path in (LIVESTATE, SESSIONLOG):
        try:
            pairs.append((path, path.resolve().relative_to(top).as_posix()))
        except ValueError:
            return []
    now: dict[str, set[str]] = {}
    old: dict[str, set[str]] = {}
    for path, rel in pairs:
        head = _git_show(f"HEAD:{rel}", repo=top)
        if head is None or not path.exists():
            return []






        def _vive(righe: list[str]) -> set[str]:
            righe = _strip_region(righe, NOW_START, NOW_END)
            righe = _strip_region(righe, WAIT_START, WAIT_END)
            return {s for s in (_significant(x) for x in righe) if s}

        old[rel] = _vive(head.splitlines())
        cur = path.read_text(errors="replace").splitlines()
        now[rel] = _vive(cur)

    tutto_ora = set().union(*now.values())
    for _path, rel in pairs:
        ack = _rimozioni_ack()








        TRONCA = " […]"




        IMPALCATURA = ("<!-- SB-STUB ", "⤷ testo integrale in")

        def _e_uno_stub_ricomposto(riga: str) -> bool:
            if riga.lstrip().startswith(IMPALCATURA):
                return True
            if not riga.endswith(TRONCA):
                return False
            inizio = riga[: -len(TRONCA)].rstrip()
            if len(inizio) < 40:
                return False
            return any(intera.startswith(inizio) for intera in tutto_ora)

        perse = {
            x
            for x in (old[rel] - tutto_ora)
            if hashlib.sha256(x.encode()).hexdigest() not in ack and not _e_uno_stub_ricomposto(x)
        }
        if perse:
            dove = "SESSION-LOG.md" if rel.endswith("live-state.md") else "no other file"
            problems.append(
                {
                    "sev": "stale",
                    "what": (
                        f"{len(perse)} lines vanished from {rel.rsplit('/', 1)[-1]} without "
                        f"reappearing in {dove}: rotation MOVES, it does not delete. "
                        "Put them back or revert before committing."
                    ),
                    "where": [f"   lost: {_mask(p)[:100]}" for p in sorted(perse)[:5]],
                }
            )
    return problems






ASSENTE: list[tuple[int, str]] = []


def _regione(lines: list[str], start: str, end: str) -> list[tuple[int, str]] | None:
    ""





    n_start = sum(1 for ln in lines if start in ln)
    n_end = sum(1 for ln in lines if end in ln)
    if n_start != n_end or n_start > 1:
        return None
    if n_start == 0:
        return ASSENTE
    out, inside = [], False
    for i, ln in enumerate(lines, 1):
        if start in ln:
            inside = True
            continue
        if end in ln:
            inside = False
            continue
        if inside:
            out.append((i, ln))
    return out


def _stato_coda() -> dict | None:
    ""





    import importlib.util

    p = PROJECT / "tools" / "util" / "sb-wait.py"
    if not p.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("sb_wait", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.stato_coda()
    except Exception as exc:  # noqa: BLE001 — a guardian does not die with the guarded
        return {
            "installata": True,
            "aperte": 0,
            "chiuse": 0,
            "rossi": [f"sb-wait broken: {exc}"],
            "gialli": [],
        }


def _problemi_coda() -> list[dict]:
    ""





    st = _stato_coda()
    if not st or not st.get("installata"):
        return []
    out = [
        {"sev": "stale", "what": r, "where": ["sbk/context/attese-owner.json"]}
        for r in st.get("rossi", [])
    ]
    out += [
        {"sev": "info", "what": g, "where": ["sbk/context/attese-owner.md"]}
        for g in st.get("gialli", [])
    ]
    if not st.get("rossi"):
        out.append(
            {
                "sev": "info",
                "what": (
                    f"⏳ {st['aperte']} decisions are waiting on you "
                    f"({st['chiuse']} closed with proof) — `sbk/context/attese-owner.md`"
                ),
                "where": ["sbk/context/attese-owner.md"],
            }
        )
    return out


def check_ordini_livestate(today: datetime.date | None = None) -> list[dict]:
    ""







    if not LIVESTATE.exists():
        return []
    today = today or datetime.date.today()
    lines = LIVESTATE.read_text(errors="replace").splitlines()
    problems: list[dict] = []


    for i, ln in enumerate(lines, 1):
        m = TEMP_RE.search(ln)
        if not m:
            continue
        try:
            scad = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            problems.append(
                {
                    "sev": "stale",
                    "what": f"SB-TEMP with invalid date '{m.group(1)}'",
                    "where": [f"{_rel(LIVESTATE)}:{i}"],
                }
            )
            continue
        if scad < today:
            problems.append(
                {
                    "sev": "stale",
                    "what": (
                        f"temporary order EXPIRED on {scad} ({(today - scad).days} days ago) "
                        "still in the live file: archive the block in SESSION-LOG "
                        "or renew the date (renewing is a decision, not inertia)"
                    ),
                    "where": [f"{_rel(LIVESTATE)}:{i}"],
                }
            )


    regione = _regione(lines, WAIT_START, WAIT_END)
    if regione is None:
        problems.append(
            {
                "sev": "stale",
                "what": (
                    "SB-WAIT markers broken (unpaired or doubled): the 'waiting on you' queue "
                    "is no longer delimited — the entries risk ending up in the archive"
                ),
                "where": [_rel(LIVESTATE)],
            }
        )
        return problems
    if regione is ASSENTE:



        st = _stato_coda()
        if st and st.get("installata") and st.get("aperte"):
            problems.append(
                {
                    "sev": "stale",
                    "what": (
                        f"the SB-WAIT block has VANISHED from live-state.md, but the queue has "
                        f"{st['aperte']} open decisions: regenerate it with "
                        "`uv run python tools/util/sb-wait.py blocco`. "
                        "A queue that is not visible is a queue that does not exist."
                    ),
                    "where": [_rel(LIVESTATE)],
                }
            )
        return problems + _problemi_coda()
    senza_data = [
        (i, ln) for i, ln in regione if ln.strip().startswith(("-", "*")) and not DATE_RE.search(ln)
    ]
    if senza_data:
        problems.append(
            {
                "sev": "stale",
                "what": (
                    f"{len(senza_data)} SB-WAIT entries with no date: without a date you cannot measure "
                    "how long you have been waiting (write YYYY-MM-DD on each line)"
                ),
                "where": [
                    f"{_rel(LIVESTATE)}:{i} · {_mask(ln.strip())[:70]}" for i, ln in senza_data[:4]
                ],
            }
        )








    st_ins = _stato_coda()
    if st_ins is not None and not st_ins.get("installata"):
        problems.append(
            {
                "sev": "stale",
                "what": (
                    "the SB-WAIT block is in live-state.md but the register "
                    "`sbk/context/attese-owner.json` does not exist on disk or in HEAD: "
                    "the queue is not empty, it VANISHED. Recover it "
                    "(`git checkout HEAD~1 -- sbk/context/attese-owner.json`) — "
                    "a queue is emptied by closing with proof, not by deleting the file"
                ),
                "where": [_rel(LIVESTATE), "sbk/context/attese-owner.json"],
            }
        )







    if st_ins is None and _regione(lines, WAIT_START, WAIT_END) is not None:
        problems.append(
            {
                "sev": "stale",
                "what": (
                    "the SB-WAIT block is in live-state.md but `tools/util/sb-wait.py` "
                    "does not exist: without it the queue cannot be read, cannot be closed and "
                    "no one notices it is stuck. Recover it "
                    "(`git checkout HEAD~1 -- tools/util/sb-wait.py`) — the queue is "
                    "dismantled by removing the block, not the tool"
                ),
                "where": [_rel(LIVESTATE), "tools/util/sb-wait.py"],
            }
        )


    problems += _problemi_coda()



    keep = _regione(lines, KEEP_START, KEEP_END)

    blocco: list[tuple[int, str]] = []
    inside = False
    keep_blocks: list[list[tuple[int, str]]] = []
    for i, ln in enumerate(lines, 1):
        if KEEP_START in ln:
            inside, blocco = True, []
            continue
        if KEEP_END in ln:
            inside = False
            keep_blocks.append(blocco)
            continue
        if inside:
            blocco.append((i, ln))
    del keep
    for blk in keep_blocks:
        date_blk = [
            datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            for _, ln in blk
            for m in DATE_RE.finditer(ln)
        ]
        if not date_blk:
            continue
        age = (today - max(date_blk)).days
        if age > KEEP_MAX_AGE_DAYS:
            titolo = next((ln.strip() for _, ln in blk if ln.startswith("#")), "(no title)")
            problems.append(
                {
                    "sev": "info",
                    "what": (
                        f"SB-KEEP block stuck for {age} days: is it still the LIVE rule or the "
                        "old version? (re-verify the source, update or archive with an outcome)"
                    ),
                    "where": [f"{_rel(LIVESTATE)}:{blk[0][0]} · {titolo[:70]}"],
                }
            )
    return problems


def check_ordini_docs(docs: list[Path], today: datetime.date | None = None) -> list[dict]:
    ""





    today = today or datetime.date.today()
    problems: list[dict] = []
    for d in docs:
        if d.name != "CLAUDE.md":
            continue
        try:
            text = d.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = TEMP_RE.search(line)
            if m:
                try:
                    scad = datetime.date.fromisoformat(m.group(1))
                except ValueError:
                    continue
                if scad < today:
                    problems.append(
                        {
                            "sev": "stale",
                            "what": (
                                f"temporary order in CLAUDE.md EXPIRED on {scad}: "
                                "remove the block or renew the date"
                            ),
                            "where": [f"{_rel(d)}:{i}"],
                        }
                    )
                continue
            if _is_negated(line):
                continue
            if TEMPORANEITA_RE.search(line) and not PERMANENZA_RE.search(line):
                if DATE_RE.search(line):
                    continue
                problems.append(
                    {
                        "sev": "info",
                        "what": (
                            "instruction that looks temporary but has no deadline: "
                            "give it `<!-- SB-TEMP scade=YYYY-MM-DD -->`, move it to SB-WAIT, "
                            "or rewrite it as a permanent rule"
                        ),
                        "where": [f"{_rel(d)}:{i} · {_mask(line.strip())[:80]}"],
                    }
                )
    return problems










ORDINI_LARGO_RE = re.compile(
    r"(?i)("
    r"\bowner\b[^.\n]{0,40}\b(?:deve|decide|dovr[àa]|sceglie|conferma|approva)\b"
    r"|\b(?:decide|decisione|decisioni|input|greenlight|ok|via libera|approvazione|firma)\b"
    r"[^.\n]{0,25}\bowner\b"
    r"|\b(?:serve|richiede|servono|aspetto|aspettiamo|in attesa d[iel]|gated su|"
    r"bloccat[oiae]+ su)\b[^.\n]{0,30}\bowner\b"
    r"|\bwaiting on owner\b|\battesa owner\b|\bper ora\b|\bfinch[eé]\b|\btemporane\w+\b"
    r"|\bnon toccare\b|\bfino a nuovo ordine\b|\bserve ok\b|\bsolo dopo ok\b"
    r")"
)


def _diff_aggiunte(path: Path) -> list[str]:
    ""
    top = _git_top(path.parent if path.exists() else PROJECT)
    if top is None:
        return []
    try:
        rel = path.resolve().relative_to(top).as_posix()
    except ValueError:
        return []
    righe: list[str] = []
    for args in (["diff", "--cached", "-U0", "--", rel], ["diff", "-U0", "--", rel]):
        try:
            out = subprocess.run(
                ["git", "-C", str(top), *args], capture_output=True, text=True, timeout=20
            )
        except (subprocess.SubprocessError, OSError):
            continue
        righe += [
            ln[1:]
            for ln in out.stdout.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")
        ]



        dentro = False
        fuori: list[str] = []
        for ln in righe:
            if WAIT_START in ln:
                dentro = True
            if not dentro:
                fuori.append(ln)
            if WAIT_END in ln:
                dentro = False
        return fuori


def check_ordini_diff() -> list[dict]:
    ""









    righe = [
        ln
        for ln in _diff_aggiunte(LIVESTATE)
        if ORDINI_LARGO_RE.search(ln)
        and not TEMP_RE.search(ln)
        and WAIT_START not in ln
        and "SB-WAIT" not in ln
        and not _is_negated(ln)
    ]
    if not righe:
        return []
    return [
        {
            "sev": "info",
            "what": (
                f"{len(righe)} new lines in live-state.md look like a wait or a temporary "
                "order: if it waits on you it goes in the queue "
                "(`sb-wait.py`), if it expires give it a "
                "`<!-- SB-TEMP scade=YYYY-MM-DD -->`, if it is permanent rewrite it as a rule"
            ),
            "where": [f"   + {_mask(r.strip())[:90]}" for r in righe[:3]]
            + ([f"   … and {len(righe) - 3} more"] if len(righe) > 3 else []),
        }
    ]








DIR_RE = re.compile(r"`((?:docs|tools|sbk|tests|\.claude|\.github)/[\w./-]*/)`")


def check_dirs(docs: list[Path]) -> list[dict]:
    seen: dict[str, list[str]] = {}
    for d in docs:
        try:
            text = d.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _is_negated(line):
                continue
            for raw in DIR_RE.findall(line):
                if any(h in raw for h in SKIP_PATH_HINTS):
                    continue
                seen.setdefault(raw, []).append(f"{_rel(d)}:{i}")
    return [
        {
            "sev": "info",
            "what": f"folder cited that does not exist in the repo: `{raw}`",
            "where": where[:3],
        }
        for raw, where in sorted(seen.items())
        if not (PROJECT / raw).exists()
    ]











































CONTRATTO_RADICI = ("tools",)
CONTRATTO_FONTE = "tools/sbk_config.py"

FONTI = ("cfg", "sbk_config", "config")


def _file_da_guardare() -> list[Path]:
    ""











    basi = [r for r in CONTRATTO_RADICI if (PROJECT / r).is_dir()]
    if not basi:
        return []
    try:
        r = subprocess.run(
            ["git", "-C", str(PROJECT), "ls-files", "--cached", "--others", "--exclude-standard"]
            + basi,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode == 0:
            return [PROJECT / x for x in r.stdout.split("\n") if x.endswith(".py")]
    except (OSError, subprocess.SubprocessError):
        pass
    return [p for b in basi for p in (PROJECT / b).rglob("*.py")]


def _py_nel_dominio() -> list[tuple[str, str]]:
    ""
    spie = tuple(d.encode() for d in cfg.LIVESTATE_DOMINIO)
    fuori = []
    for p in sorted(set(_file_da_guardare())):
        try:
            rel = str(p.resolve().relative_to(PROJECT))
        except ValueError:
            continue
        if rel == CONTRATTO_FONTE:
            continue
        try:
            grezzo = p.read_bytes()
        except OSError:
            continue

        if any(d in grezzo for d in spie):
            fuori.append((rel, grezzo.decode("utf-8", errors="replace")))
    return fuori


def _assegnazioni_modulo(src: str):
    ""
    import ast

    try:
        albero = ast.parse(src)
    except SyntaxError:
        return






    for nodo in ast.walk(albero):
        if not isinstance(nodo, (ast.Assign, ast.AnnAssign)):  # noqa: UP038 — see below
            continue
        bersagli = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]

        espansi = []
        for b in bersagli:
            espansi.extend(b.elts if isinstance(b, (ast.Tuple, ast.List)) else [b])  # noqa: UP038
        bersagli = espansi

        val = nodo.value
        da_contratto = False
        if isinstance(val, ast.Attribute) and isinstance(val.value, ast.Name):
            da_contratto = val.value.id in FONTI
        elif isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute):
            base = val.func.value
            da_contratto = isinstance(base, ast.Name) and base.id in FONTI
        elif isinstance(val, ast.Name):
            da_contratto = True
        for t in bersagli:
            if isinstance(t, ast.Name):
                yield t.id, nodo.lineno, da_contratto


def _letterali_stringa(src: str):
    ""
    import ast

    try:
        albero = ast.parse(src)
    except SyntaxError:
        return
    docstring_id = set()
    for nodo in ast.walk(albero):
        if isinstance(  # noqa: UP038 — see below
            nodo, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            corpo = getattr(nodo, "body", None)
            if (
                corpo
                and isinstance(corpo[0], ast.Expr)
                and isinstance(corpo[0].value, ast.Constant)
                and isinstance(corpo[0].value.value, str)
            ):
                docstring_id.add(id(corpo[0].value))
    for nodo in ast.walk(albero):
        if (
            isinstance(nodo, ast.Constant)
            and isinstance(nodo.value, str)
            and id(nodo) not in docstring_id
        ):
            yield nodo.value, nodo.lineno


def check_contratto() -> list[dict]:
    ""
    problemi: list[dict] = []
    nel_dominio = _py_nel_dominio()
    per_percorso = dict(nel_dominio)


    for rel in cfg.LIVESTATE_ABBONATI:
        p = PROJECT / rel
        if not p.exists():
            problemi.append(
                {
                    "sev": "stale",
                    "what": (
                        f"{rel} is in the contract subscribers list but does not exist: "
                        "either it was moved (update LIVESTATE_ABBONATI) or it vanished"
                    ),
                    "where": [rel, f"{CONTRATTO_FONTE} (LIVESTATE_ABBONATI)"],
                }
            )
            continue
        src = per_percorso.get(rel) or p.read_text(encoding="utf-8", errors="replace")
        if "sbk_config" not in src:
            problemi.append(
                {
                    "sev": "stale",
                    "what": (
                        f"{rel} no longer imports the contract (sbk_config): the cap, the "
                        "markers or the ruler are hand-written again."
                    ),
                    "where": [rel, f"{CONTRATTO_FONTE} (§ Live-state)"],
                }
            )


    concetti = set(cfg.LIVESTATE_CONCETTI)
    for rel, src in nel_dominio:
        for nome, riga, da_contratto in _assegnazioni_modulo(src):
            if nome not in concetti or da_contratto:
                continue
            problemi.append(
                {
                    "sev": "stale",
                    "what": (
                        f"second declaration of `{nome}`: the contract for the context files "
                        f"lives in {CONTRATTO_FONTE} and is imported, not recopied."
                    ),
                    "where": [f"{rel}:{riga}", f"{CONTRATTO_FONTE} (§ Live-state)"],
                }
            )


    marcatori = set(cfg.SB_MARCATORI)
    for rel, src in nel_dominio:
        if not any(m in src for m in marcatori):
            continue
        for valore, riga in _letterali_stringa(src):
            if valore in marcatori:
                problemi.append(
                    {
                        "sev": "stale",
                        "what": (
                            f"marker `{valore}` hand-written: if it changes in one place only, "
                            "the block that EVERY session reads breaks silently. "
                            f"It is imported from {CONTRATTO_FONTE}."
                        ),
                        "where": [f"{rel}:{riga}", f"{CONTRATTO_FONTE} (§ Live-state)"],
                    }
                )

    return problemi


def check_livestate() -> list[dict]:
    return (
        check_contratto()
        + check_livestate_size()
        + check_livestate_age()
        + check_livestate_pavimento()
        + check_livestate_no_loss()
        + check_ordini_livestate()
        + check_ordini_diff()
    )







SECRET_PATTERNS = [
    re.compile(r"(?:Password|Passwd|Pass)\s*[:=]", re.I),
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}"),
    re.compile(r"\bxox[bp]-[a-zA-Z0-9-]{10,}"),
    re.compile(r"\bAKIA[A-Z0-9]{12,}"),
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bghp_[a-zA-Z0-9]{36,}"),
    re.compile(r"\bglpat-[a-zA-Z0-9-]{20,}"),
]


def check_memory_secrets() -> list[dict]:
    ""



    problems = []
    if not MEMORY_DIR.exists():
        return problems
    for f in sorted(MEMORY_DIR.glob("*.md")):
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    problems.append(
                        {
                            "sev": "stale",
                            "what": f"possible secret in memory: {_rel(f)}:{i} (pattern: {pat.pattern[:30]}...)",
                            "where": [f"{_rel(f)}:{i}  (value NOT printed)"],
                        }
                    )
                    break
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--quiet", action="store_true", help="print only the problems")
    ap.add_argument(
        "--only",
        choices=["all", "livestate", "docs", "contratto"],
        default="all",
        help="livestate = only the anti-regrowth checks (fast, used by the pre-commit)",
    )
    ap.add_argument("files", nargs="*", help="ignored (pre-commit compat)")
    args = ap.parse_args()

    if args.only == "contratto":
        problems = check_contratto()
        for p in problems:
            print(("🔴 " if p["sev"] == "stale" else "🟡 ") + p["what"])
            for w in p["where"]:
                print(f"       └ {w}")
        if any(p["sev"] == "stale" for p in problems):
            print(
                "\nRule: the contract for the context files lives in tools/sbk_config.py "
                "(§ Live-state). It is imported, not recopied."
            )
            return 1
        print("✅ contract: a single source, no copies")
        return 0

    if args.only == "livestate":
        problems = check_livestate()
        stale = [p for p in problems if p["sev"] == "stale"]
        for p in problems:
            if p["sev"] == "stale" or not args.quiet:
                print(("🔴 " if p["sev"] == "stale" else "🟡 ") + p["what"])
                for w in p["where"]:
                    print(f"       └ {w}")
        if stale:
            print("\nRule: live-state = only NOW. History is MOVED to SESSION-LOG.md.")
            return 1
        if not args.quiet:
            print("✅ live-state within the cap, no history lost")
        return 0

    docs = _iter_docs()
    if not args.quiet:
        print(f"── sb-doc-check · {len(docs)} documents watched ──")
        n_skills = len(list(SKILLS_DIR.glob("*/SKILL.md"))) if SKILLS_DIR.exists() else 0
        n_agents = len(list(AGENTS_DIR.glob("*.md"))) if AGENTS_DIR.exists() else 0
        n_memory = len(list(MEMORY_DIR.glob("*.md"))) if MEMORY_DIR.exists() else 0
        print(
            f"   CLAUDE.md project + global + {n_memory} memories"
            f" + {n_skills} skills + {n_agents} agents\n"
        )

    problems = (
        check_launchd(docs)
        + check_paths(docs)
        + check_dirs(docs)
        + check_python39()
        + check_livestate()
        + check_ordini_docs(docs)
        + check_memory_secrets()
    )
    stale = [p for p in problems if p["sev"] == "stale"]
    info = [p for p in problems if p["sev"] == "info"]

    if stale:
        print(
            f"🔴 {len(stale)} FALSE CLAIMS (the documentation says things that are no longer true)"
        )
        for p in stale:
            print(f"   • {p['what']}")
            for w in p["where"]:
                print(f"       └ {w}")
        print()
    if info and not args.quiet:
        print(f"🟡 {len(info)} to look at (not necessarily errors)")
        for p in info:
            print(f"   • {p['what']}")
            for w in p["where"][:2]:
                print(f"       └ {w}")
        print()

    if not stale:
        print("✅ no false claim found in the documents")
        return 0
    print("Fix the listed lines, then rerun this command.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
