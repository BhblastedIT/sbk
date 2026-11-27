#!/usr/bin/env python3
"""Catalog of your scheduled jobs: the launchd agents in ~/Library/LaunchAgents that run code from this repo or
the data root, with their schedule and next expected run.

Job titles, purpose and owner can be added in <data root>/jobs/declared.json. It prints the jobs it finds;
--write saves the catalog to <data root>/jobs/catalog.json, which jb_status.py reads.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jb_model import CATALOG, JOBS_ROOT, OVERLAY, fuso_locale, now, stamp

UTC_TZ = UTC

LAUNCH_AGENTS = Path(os.path.expanduser("~/Library/LaunchAgents"))





# Project roots we consider "ours" when cataloguing jobs. Load extra roots
# from user config; the defaults below cover the core repo and its data dir.
OUR_ROOTS = tuple(
    os.path.expanduser(p)
    for p in (
        # the repo: wherever this file sits (tools/jobs/ -> two levels up)
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        os.environ.get("SBK_DATA_ROOT") or "~/.sbk-data",
    )
)


OVERLAY_FIELDS = frozenset(
    {"title", "purpose", "owner", "damage_if_missed", "proof_of_success", "mute"}
)


@dataclass
class Job:
    key: str
    where: str = "local"
    title: str = ""
    schedule: str = ""
    calendar: list[dict[str, int]] = field(default_factory=list)
    interval_seconds: int | None = None
    keepalive: bool = False
    program: list[str] = field(default_factory=list)
    log_path: str | None = None
    log_paths: list[str] = field(default_factory=list)
    pid: int | None = None
    last_exit: int | None = None
    loaded: bool = False
    ours: bool = True
    next_expected: str | None = None
    next_effective: str | None = None


    schedule_since: str | None = None



    plist_gone: bool = False


    crons: list[str] = field(default_factory=list)

    repo: str | None = None


    remote_path: str | None = None

    read_from: str | None = None

    purpose: str = ""
    owner: str = ""
    damage_if_missed: str = ""
    proof_of_success: str = ""
    mute: bool = False





def tz_skew() -> dict[str, Any]:
    ""






    out: dict[str, Any] = {"skewed": False, "tz_changed_at": None, "evaluator_started_at": None}
    try:
        tz_m = Path("/etc/localtime").lstat().st_mtime
    except OSError:
        return out
    try:
        ps = subprocess.run(
            ["ps", "-Ao", "lstart=,comm="], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return out
    if ps.returncode != 0:
        return out









    boot = None
    try:
        b = subprocess.run(
            ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5
        )
        if b.returncode == 0 and "sec = " in b.stdout:
            sec = int(b.stdout.split("sec = ")[1].split(",")[0])
            boot = datetime.fromtimestamp(sec).astimezone()
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        boot = None

    started = None
    for line in ps.stdout.splitlines():
        if not line.rstrip().endswith("/usr/libexec/UserEventAgent"):
            continue
        try:
            q = datetime.strptime(line[:24].strip(), "%a %b %d %H:%M:%S %Y").astimezone()
        except ValueError:
            continue
        if boot and q < boot - timedelta(minutes=5):
            continue
        if started is None or q > started:
            started = q
    if started is None:
        return out
    changed = datetime.fromtimestamp(tz_m).astimezone()
    out["tz_changed_at"] = stamp(changed)
    out["evaluator_started_at"] = stamp(started)
    out["skewed"] = changed > started
    return out





_WD = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
_MO = (
    "",
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


def describe(cal: list[dict[str, int]], interval: int | None, keepalive: bool) -> str:
    if keepalive:
        return "always on (daemon)"
    if interval:
        return f"every {interval}s (from the END of the previous run, not the start)"
    if not cal:
        return "no schedule"


    times = {(e.get("Hour"), e.get("Minute")) for e in cal}
    days = sorted({e["Weekday"] for e in cal if "Weekday" in e})
    if len(times) == 1 and days and all("Month" not in e for e in cal):
        h, m = times.pop()
        when = f"{h if h is not None else 0:02d}:{m or 0:02d}"
        if days == [1, 2, 3, 4, 5]:
            return f"Mon-Fri at {when}"
        if len(days) == 1:
            return f"{_WD[days[0]]}s at {when}"
        return f"{', '.join(_WD[d][:3] for d in days)} at {when}"




    parts = []
    daily: list[str] = []
    for e in cal:
        h, m = e.get("Hour"), e.get("Minute")
        t = f"{h:02d}:{m or 0:02d}" if h is not None else (f":{m:02d}" if m is not None else "")
        if "Month" in e and "Day" in e:
            parts.append(f"{e['Day']} {_MO[e['Month']]} at {t} (ONCE A YEAR)")
        elif "Day" in e:
            parts.append(f"day {e['Day']} of the month at {t}")
        elif "Weekday" in e:
            parts.append(f"{_WD[e['Weekday']]}s at {t}")
        elif h is not None:
            daily.append(t)
        else:
            parts.append(f"every hour at {t}")
    if daily:
        parts.insert(0, "daily at " + ", ".join(sorted(dict.fromkeys(daily))))
    uniq = list(dict.fromkeys(parts))
    if len(uniq) <= 6:
        return " and ".join(uniq)
    return f"{len(uniq)} slots: " + "; ".join(uniq[:6]) + f"; and {len(uniq) - 6} more"


def _tz():
    ""






    return fuso_locale() or now().tzinfo


def next_fire(cal: list[dict[str, int]], ref: datetime | None = None) -> datetime | None:
    ""
    if not cal:
        return None
    ref = (ref or now()).astimezone(_tz()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    best: datetime | None = None
    for entry in cal:


        cand = _next_for_entry(entry, ref)
        if cand and (best is None or cand < best):
            best = cand
    return best


def prev_fire(cal: list[dict[str, int]], ref: datetime | None = None) -> datetime | None:
    ""








    if not cal:
        return None
    ref = (ref or now()).astimezone(_tz()).replace(second=0, microsecond=0)
    best: datetime | None = None
    for entry in cal:
        probe = ref
        for _ in range(760):
            hh = entry.get("Hour")
            mm = entry.get("Minute") or 0
            ok = True
            if "Month" in entry and probe.month != entry["Month"]:
                ok = False
            if ok and "Day" in entry and probe.day != entry["Day"]:
                ok = False
            if ok and "Weekday" in entry and (probe.weekday() + 1) % 7 != entry["Weekday"]:
                ok = False
            if ok:
                cand = probe.replace(
                    hour=hh if hh is not None else probe.hour, minute=mm, second=0, microsecond=0
                )
                if cand <= ref and (best is None or cand > best):
                    best = cand
                    break
            probe = (probe - timedelta(days=1)).replace(hour=23, minute=59)
    return best


def _next_for_entry(e: dict[str, int], ref: datetime) -> datetime | None:
    minute, hour = e.get("Minute"), e.get("Hour")
    day, weekday, month = e.get("Day"), e.get("Weekday"), e.get("Month")


    probe = ref
    for _ in range(760):
        if month is not None and probe.month != month:
            probe = (probe.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0)
            continue
        if day is not None and probe.day != day:
            probe = (probe + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if weekday is not None and (probe.weekday() + 1) % 7 != weekday:
            probe = (probe + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        hh = hour if hour is not None else probe.hour
        mm = minute if minute is not None else 0
        cand = probe.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand >= ref:
            return cand

        if hour is None and minute is not None:
            nxt = probe.replace(minute=mm) + timedelta(hours=1)
            if nxt >= ref:
                return nxt
        probe = (probe + timedelta(days=1)).replace(hour=0, minute=0)
    return None





def _loaded() -> dict[str, dict[str, Any]]:
    ""













    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ln in r.stdout.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        pid, status, label = parts[0].strip(), parts[1].strip(), parts[2].strip()
        out[label] = {
            "pid": int(pid) if pid.isdigit() else None,
            "last_exit": int(status) if status.lstrip("-").isdigit() else None,
        }
    return out


def _log_vivo(out: str | None, err: str | None) -> str | None:
    ""







    best, best_key = None, (-1.0, -1)
    for p in (out, err):
        if not p:
            continue
        try:
            st = os.stat(os.path.expanduser(p))
        except OSError:
            continue
        key = (st.st_mtime if st.st_size > 0 else -1.0, st.st_size)
        if key > best_key:
            best, best_key = p, key
    return best or out or err


def discover_local() -> list[Job]:
    stato = _loaded()
    jobs: list[Job] = []
    for p in sorted(LAUNCH_AGENTS.glob("*.plist")):
        try:
            d = plistlib.loads(p.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        label = d.get("Label") or p.stem
        args = d.get("ProgramArguments") or ([d["Program"]] if d.get("Program") else [])
        ours = any(str(a).startswith(OUR_ROOTS) for a in args)
        cal = d.get("StartCalendarInterval")
        cal = [cal] if isinstance(cal, dict) else (list(cal) if cal else [])
        interval = d.get("StartInterval")
        keep = bool(d.get("KeepAlive"))
        jobs.append(
            Job(
                key=label,
                where="local",
                title=label.split(".")[-1].replace("-", " "),
                schedule=describe(cal, interval, keep),
                calendar=cal,
                interval_seconds=interval,
                keepalive=keep,
                program=[str(a) for a in args],
                log_path=_log_vivo(d.get("StandardOutPath"), d.get("StandardErrorPath")),


                log_paths=list(
                    dict.fromkeys(
                        x for x in (d.get("StandardOutPath"), d.get("StandardErrorPath")) if x
                    )
                ),
                loaded=label in stato,
                schedule_since=stamp(datetime.fromtimestamp(p.stat().st_mtime).astimezone()),
                pid=(stato.get(label) or {}).get("pid"),
                last_exit=(stato.get(label) or {}).get("last_exit"),
                ours=ours,
            )
        )
    jobs.extend(_orfani(stato, {j.key for j in jobs}))
    return jobs





_MAX_ORFANI = 40


def _print_servizio(label: str) -> str:
    ""
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _leggi_print(testo: str) -> dict[str, Any]:
    ""





    out: dict[str, Any] = {
        "path": None,
        "program": None,
        "arguments": [],
        "stdout": None,
        "stderr": None,
        "calendar": [],
        "interval": None,
    }
    pila: list[str] = []
    trigger: dict[str, Any] | None = None
    for raw in testo.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.endswith("{"):
            nome = s[:-1].strip()
            nome = nome[:-2].strip() if nome.endswith("=>") else nome.rstrip("=").strip()
            pila.append(nome)
            if len(pila) == 3 and pila[1] == "event triggers":
                trigger = {"stream": "", "descriptor": {}}
            continue
        if s == "}":
            if len(pila) == 3 and pila[1] == "event triggers" and trigger is not None:
                if (
                    trigger["stream"] == "com.apple.launchd.calendarinterval"
                    and trigger["descriptor"]
                ):
                    out["calendar"].append(trigger["descriptor"])
                trigger = None
            if pila:
                pila.pop()
            continue
        livello = len(pila)
        if livello == 1:
            k, sep, v = s.partition(" = ")
            if not sep:
                continue
            if k in ("path", "program"):
                out[k] = v
            elif k == "stdout path":
                out["stdout"] = v
            elif k == "stderr path":
                out["stderr"] = v
            elif k == "run interval":
                m = re.match(r"(\d+)", v)
                out["interval"] = int(m.group(1)) if m else None
        elif livello == 2 and pila[1] == "arguments":
            out["arguments"].append(s)
        elif livello == 3 and pila[1] == "event triggers" and trigger is not None:
            k, sep, v = s.partition(" = ")
            if sep and k == "stream":
                trigger["stream"] = v
        elif (
            livello == 4
            and pila[1] == "event triggers"
            and pila[3] == "descriptor"
            and trigger is not None
        ):
            m = re.match(r'"(\w+)"\s*=>\s*(-?\d+)', s)
            if m:
                trigger["descriptor"][m.group(1)] = int(m.group(2))
    return out


def _orfani(stato: dict[str, dict[str, Any]], noti: set[str]) -> list[Job]:
    ""










    jobs: list[Job] = []
    candidati = [
        lab
        for lab in sorted(stato)
        if lab not in noti and not lab.startswith(("com.apple.", "application."))
    ]
    for label in candidati[:_MAX_ORFANI]:
        info = _leggi_print(_print_servizio(label))
        args = info["arguments"] or ([info["program"]] if info["program"] else [])
        if not any(str(a).startswith(OUR_ROOTS) for a in args):
            continue
        path = info["path"]
        cal = info["calendar"]
        jobs.append(
            Job(
                key=label,
                where="local",
                title=label.split(".")[-1].replace("-", " "),
                schedule=describe(cal, info["interval"], False),
                calendar=cal,
                interval_seconds=info["interval"],
                program=[str(a) for a in args],
                log_path=_log_vivo(info["stdout"], info["stderr"]),
                log_paths=list(dict.fromkeys(x for x in (info["stdout"], info["stderr"]) if x)),
                loaded=True,
                pid=(stato.get(label) or {}).get("pid"),
                last_exit=(stato.get(label) or {}).get("last_exit"),
                ours=True,
                plist_gone=not (path and os.path.exists(path)),
            )
        )
    return jobs


def _git(repo: Path, *args: str) -> str | None:
    ""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _ramo_remoto(repo: Path) -> str | None:
    ""
    cand: list[str] = []
    ref = (_git(repo, "rev-parse", "--abbrev-ref", "origin/HEAD") or "").strip()
    if ref and ref != "origin/HEAD":
        cand.append(ref)
    cand += ["origin/main", "origin/master"]
    for c in dict.fromkeys(cand):
        if _git(repo, "rev-parse", "--verify", "--quiet", f"{c}^{{commit}}") is not None:
            return c
    return None


def _leggi_definizioni(repo: Path) -> tuple[str | None, list[tuple[str, str]], str]:
    ""







    ramo = _ramo_remoto(repo)
    if ramo:
        vj = _git(repo, "show", f"{ramo}:vercel.json")
        flussi: list[tuple[str, str]] = []
        elenco = _git(repo, "ls-tree", "--name-only", f"{ramo}:.github/workflows") or ""
        for nome in sorted(x.strip() for x in elenco.splitlines() if x.strip()):
            if not nome.endswith((".yml", ".yaml")):
                continue
            testo = _git(repo, "show", f"{ramo}:.github/workflows/{nome}")
            if testo is not None:
                flussi.append((nome, testo))
        return vj, flussi, ramo
    vj_path = repo / "vercel.json"
    vj_txt = None
    if vj_path.exists():
        try:
            vj_txt = vj_path.read_text()
        except OSError:
            vj_txt = None
    flussi = []
    wf_dir = repo / ".github" / "workflows"
    for wf in sorted(wf_dir.glob("*.y*ml")) if wf_dir.exists() else []:
        try:
            flussi.append((wf.name, wf.read_text()))
        except OSError:
            continue
    return vj_txt, flussi, "working tree (no origin branch)"


def discover_remote() -> list[Job]:
    ""






    jobs: list[Job] = []
    # Repos whose Vercel crons we watch. Load from user config; empty by default.
    _remote_repos: tuple[str, ...] = ()
    roots = [Path(os.path.expanduser(p)) for p in _remote_repos]
    for repo in roots:
        if not (repo / ".git").exists():
            continue
        name = repo.name
        vj_txt, flussi, da_dove = _leggi_definizioni(repo)
        if vj_txt:
            try:
                for c in json.loads(vj_txt).get("crons") or []:
                    expr = c.get("schedule", "")
                    nxt = next_cron(expr)
                    jobs.append(
                        Job(
                            key=f"vercel:{name}:{c.get('path', '?')}",
                            where="vercel",
                            title=f"{name} {c.get('path', '')}",
                            schedule=f"cron {expr} (UTC)",
                            next_expected=stamp(nxt) if nxt else None,
                            crons=[expr] if expr else [],
                            repo=str(repo),
                            remote_path=c.get("path"),
                            read_from=da_dove,
                        )
                    )
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        for wf_name, text in flussi:
            crons = [
                c
                for ln in text.splitlines()
                if "cron:" in ln
                if (c := _clean_cron(ln.split("cron:", 1)[1]))
            ]
            if crons:
                nxt = min((n for c in crons if (n := next_cron(c))), default=None)
                jobs.append(
                    Job(
                        key=f"github:{name}:{wf_name}",
                        where="github",
                        title=f"{name} {Path(wf_name).stem}",
                        schedule=" and ".join(f"cron {c} (UTC)" for c in crons),
                        next_expected=stamp(nxt) if nxt else None,
                        crons=crons,
                        repo=str(repo),
                        remote_path=f".github/workflows/{wf_name}",
                        read_from=da_dove,
                    )
                )
    return jobs


def _clean_cron(raw: str) -> str:
    ""






    raw = raw.strip()
    if raw[:1] in "'\"":
        q = raw[0]
        end = raw.find(q, 1)
        return raw[1:end].strip() if end > 0 else raw[1:].strip()
    return raw.split("#", 1)[0].strip()


def next_cron(expr: str, ref: datetime | None = None) -> datetime | None:
    ""







    parts = expr.split()
    if len(parts) != 5:
        return None
    try:
        fields = [
            _cron_field(p, lo, hi)
            for p, (lo, hi) in zip(parts, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6)), strict=True)
        ]
    except ValueError:
        return None
    mins, hours, days, months, wdays = fields
    probe = (ref or now()).astimezone(UTC_TZ).replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    for _ in range(366 * 24 * 60 // 30):
        if (
            probe.month in months
            and probe.day in days
            and ((probe.weekday() + 1) % 7) in wdays
            and probe.hour in hours
            and probe.minute in mins
        ):
            return probe
        probe += timedelta(minutes=1)
        if probe.minute == 0 and probe.hour not in hours:
            probe += timedelta(minutes=59)
    return None


def _cron_field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for piece in spec.split(","):
        step = 1
        if "/" in piece:
            piece, s = piece.split("/", 1)
            step = int(s)
        if piece in ("*", ""):
            out |= set(range(lo, hi + 1, step))
        elif "-" in piece:
            a, b = piece.split("-", 1)
            out |= set(range(int(a), int(b) + 1, step))
        else:
            out.add(int(piece))
    if not out:
        raise ValueError(spec)
    return out





def load_overlay() -> tuple[dict[str, dict[str, Any]], list[str]]:
    ""
    if not OVERLAY.exists():
        return {}, []
    try:
        raw = json.loads(OVERLAY.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {}, [f"declared.json unreadable ({e}); ignored"]
    complaints: list[str] = []
    clean: dict[str, dict[str, Any]] = {}
    for key, val in raw.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        bad = set(val) - OVERLAY_FIELDS
        if bad:
            complaints.append(
                f"{key}: refused {sorted(bad)} -- the machine produces these, "
                "a hand-written copy would drift"
            )
        clean[key] = {k: v for k, v in val.items() if k in OVERLAY_FIELDS}
    return clean, complaints


def _norm_vercel(key: str) -> str:
    ""



    parti = key.split(":", 2)
    if len(parti) != 3 or parti[0] != "vercel":
        return key
    base, q, query = parti[2].partition("?")
    if len(base) > 1 and base.endswith("/"):
        base = base.rstrip("/") or "/"
    return f"vercel:{parti[1]}:{base}{q}{query}"


def _abbina_overlay(
    jobs: list[Job], overlay: dict[str, dict[str, Any]]
) -> tuple[dict[str, str], list[str]]:
    ""

















    avvisi: list[str] = []
    abbinati: dict[str, str] = {j.key: j.key for j in jobs if j.key in overlay}
    usate = set(abbinati.values())
    per_forma_lavori: dict[str, list[str]] = {}
    for j in jobs:
        if j.key.startswith("vercel:"):
            per_forma_lavori.setdefault(_norm_vercel(j.key), []).append(j.key)
    per_forma_dich: dict[str, list[str]] = {}
    for k in overlay:
        if k.startswith("vercel:"):
            per_forma_dich.setdefault(_norm_vercel(k), []).append(k)
    for chiavi in per_forma_lavori.values():
        if len(chiavi) > 1:
            avvisi.append(
                f"jobs {chiavi} differ only by a trailing slash: kept apart, "
                "and no declared name is attached to them by guessing"
            )
    for chiavi in per_forma_dich.values():
        if len(chiavi) > 1:
            avvisi.append(
                f"declared {chiavi} differ only by a trailing slash: kept apart, "
                "each one is used only for the job it matches exactly"
            )
    for j in jobs:
        if j.key in abbinati or not j.key.startswith("vercel:"):
            continue
        forma = _norm_vercel(j.key)
        dich = per_forma_dich.get(forma, [])
        if len(per_forma_lavori.get(forma, [])) != 1 or len(dich) != 1 or dich[0] in usate:
            continue
        abbinati[j.key] = dich[0]
        usate.add(dich[0])
        avvisi.append(
            f"declared {dich[0]!r} matched {j.key!r} only after dropping the trailing slash: "
            "the cron path changed, rewrite the key in declared.json"
        )
    for k in overlay:
        if k not in usate:
            avvisi.append(
                f"declared {k!r} matches no job: its name and notes are shown nowhere "
                "(the job is gone, or its key changed)"
            )
    return abbinati, avvisi


def build() -> dict[str, Any]:
    jobs = discover_local() + discover_remote()
    overlay, complaints = load_overlay()
    skew = tz_skew()
    abbinati, avvisi = _abbina_overlay(jobs, overlay)
    complaints = complaints + avvisi
    for j in jobs:
        for k, v in overlay.get(abbinati.get(j.key, ""), {}).items():
            setattr(j, k, v)
        nf = next_fire(j.calendar)
        if nf:
            j.next_expected = stamp(nf)



            j.next_effective = (
                None if not skew["skewed"] else "unknown: evaluator on a stale timezone"
            )
    return {
        "generated_at": stamp(),
        "generator": "tools/jobs/jb_catalog.py",
        "tz_skew": skew,
        "overlay_complaints": complaints,
        "jobs": [asdict(j) for j in jobs],
    }


def write() -> dict[str, Any]:
    cat = build()
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = CATALOG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cat, ensure_ascii=False, indent=2))
    os.replace(tmp, CATALOG)
    return cat


if __name__ == "__main__":
    import argparse

    _ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ap.add_argument("--write", action="store_true", help="save the catalog to <data root>/jobs/catalog.json")
    _write = _ap.parse_args().write
    cat = write() if _write else build()
    ours = [j for j in cat["jobs"] if j["ours"]]
    print(f"{len(cat['jobs'])} jobs discovered, {len(ours)} ours")
    if cat["tz_skew"]["skewed"]:
        print(
            f"  !! calendar evaluator on a stale timezone "
            f"(tz changed {cat['tz_skew']['tz_changed_at']}, "
            f"evaluator up since {cat['tz_skew']['evaluator_started_at']})"
        )
    for c in cat["overlay_complaints"]:
        print(f"  overlay: {c}")
    for j in ours:
        nxt = (j["next_expected"] or "")[:16].replace("T", " ")
        print(f"  {j['where']:7} {j['key'][:42]:44} {j['schedule'][:38]:40} next {nxt}")
    if _write:
        print(f"\nwritten to {CATALOG}")
