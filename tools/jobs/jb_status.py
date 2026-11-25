#!/usr/bin/env python3
""


























from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jb_catalog import _loaded, next_cron, next_fire, prev_fire  # noqa: E402
from jb_model import (  # noqa: E402
    CATALOG,
    JOBS_ROOT,
    MANUALE,
    PRESENCE,
    STATUS,
    fermato_da_fuori,
    nome_segnale,
    now,
    parse,
    read_events,
    stamp,
)




GENERICO_AUTO = "ran and did not declare how it went"





GRACE_LOCAL = timedelta(minutes=20)






GRACE_REMOTE = timedelta(minutes=60)


def _presence() -> list[tuple[Any, Any]]:
    ""
    out = []
    if not PRESENCE.exists():
        return out
    for raw in PRESENCE.read_text(errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
            out.append((parse(d["from"]), parse(d["to"])))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def _was_present(at: Any, windows: list[tuple[Any, Any]]) -> bool | None:
    if not windows:
        return None
    return any(a <= at <= b for a, b in windows)


def _misura_sfasamento(cat, events) -> tuple[float | None, int]:
    ""























    scarti: list[float] = []
    for j in cat["jobs"]:
        if not j.get("ours") or j.get("where") != "local" or j.get("keepalive"):
            continue
        cal = j.get("calendar") or []
        if not cal:
            continue





        istante = None
        if log := j.get("log_path"):
            try:
                istante = datetime.fromtimestamp(
                    os.path.getmtime(os.path.expanduser(log))
                ).astimezone()
            except OSError:
                istante = None
        if istante is None or (now() - istante) > timedelta(days=4):
            continue
        nominale = prev_fire(cal, istante)
        if not nominale:
            continue
        ore = (istante - nominale).total_seconds() / 3600








        if 0.25 <= ore <= 23:
            scarti.append(ore)
    if len(scarti) < 3:
        return None, len(scarti)
    minimo = min(scarti)


    concordi = sum(1 for s in scarti if s - minimo <= 0.5)
    if concordi < 3:
        return None, concordi
    return round(minimo * 4) / 4, concordi


def _rinfresca(cat: dict[str, Any]) -> None:
    ""















    for j in cat.get("jobs", []):
        if j.get("where", "local") != "local":
            prossimo = _prossimo_remoto(j)
            if prossimo:
                j["next_expected"] = prossimo
    vivi = _loaded()
    if not vivi:
        return
    for j in cat.get("jobs", []):
        if j.get("where", "local") != "local":
            continue
        v = vivi.get(j.get("key"))
        j["loaded"] = v is not None
        j["pid"] = v["pid"] if v else None
        j["last_exit"] = v["last_exit"] if v else None
        if j.get("calendar"):
            nf = next_fire(j["calendar"])
            j["next_expected"] = stamp(nf) if nf else None
    cat["volatile_refreshed_at"] = stamp()


def _prossimo_remoto(j: dict[str, Any]) -> str | None:
    ""




    crons = j.get("crons") or re.findall(r"cron (.+?) \(UTC\)", j.get("schedule") or "")
    prossimi = [n for c in crons if (n := next_cron(c))]
    return stamp(min(prossimi)) if prossimi else None









_GH_ESITO = {
    "success": "ok",
    "failure": "failed",
    "timed_out": "failed",
    "startup_failure": "failed",
    "cancelled": "skipped",
    "skipped": "skipped",
    "neutral": "nothing",
}


def _iso_locale(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return stamp(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone())
    except ValueError:
        return None


def _esiti_github(chiave: str, repo: str | None, workflow: str) -> list[dict[str, Any]]:
    ""





    if not repo or not workflow or not os.path.isdir(repo):
        return []
    try:
        r = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--limit",
                "14",
                "--json",
                "status,conclusion,createdAt,updatedAt,event",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    try:
        giri = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    eventi: list[dict[str, Any]] = []
    for g in reversed(giri if isinstance(giri, list) else []):
        inizio = _iso_locale(g.get("createdAt"))
        if not inizio:
            continue
        segno = "" if g.get("event") == "schedule" else "[manuale]"
        eventi.append({"job": chiave, "phase": "start", "at": inizio, "detail": segno})
        if g.get("status") == "completed":
            conclusione = g.get("conclusion") or "unknown"
            eventi.append(
                {
                    "job": chiave,
                    "phase": "end",
                    "at": _iso_locale(g.get("updatedAt")) or inizio,
                    "outcome": _GH_ESITO.get(conclusione, "unknown"),
                    "detail": f"GitHub run: {conclusione} {segno}".strip(),
                }
            )
    return eventi











_CODA_LOG = 16_384
_ERRORE = re.compile(
    r"\[ERROR\]|\bERROR\b|\bHTTP [45]\d\d\b|\b\w*(?:Error|Exception)\b:|\bFATAL\b|\bfatal:"
    r"|\bTraceback\b"
)
_ISTANTE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)(?:[.,]\d+)?\s?(Z|[+-]\d{2}:?\d{2})?"
)
_SEGRETI = [
    re.compile(x)
    for x in (
        r"sk-ant-[A-Za-z0-9_-]{8,}",
        r"sk-[A-Za-z0-9]{16,}",
        r"gh[pousr]_[A-Za-z0-9]{16,}",
        r"xox[baprs]-[A-Za-z0-9-]{8,}",
        r"ph[xc]_[A-Za-z0-9]{16,}",
        r"AIza[A-Za-z0-9_-]{20,}",
        r"AKIA[A-Z0-9]{12,}",
        r"1//[A-Za-z0-9_-]{20,}",
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}",
        r"(?i)(authorization|bearer)[: ]+[A-Za-z0-9._-]{12,}",
        r"(?i)(api[_-]?key|token|secret|password)[\"' ]*[:=][\"' ]*[A-Za-z0-9/+_-]{12,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
]


def _redigi(testo: str) -> str:
    ""
    for s in _SEGRETI:
        testo = s.sub("[redacted]", testo)
    return testo


def _istante_riga(riga: str) -> datetime | None:
    ""
    m = _ISTANTE.search(riga[:60])
    if not m:
        return None
    data, ora, fuso = m.group(1), m.group(2), m.group(3)
    if len(ora) == 5:
        ora += ":00"
    try:
        if not fuso:
            return datetime.fromisoformat(f"{data}T{ora}").astimezone()
        if fuso == "Z":
            return datetime.fromisoformat(f"{data}T{ora}").replace(tzinfo=UTC)
        if ":" not in fuso:
            fuso = f"{fuso[:3]}:{fuso[3:]}"
        return datetime.fromisoformat(f"{data}T{ora}{fuso}")
    except ValueError:
        return None


def _riga_errore(path: str | None, dal: datetime | None) -> str:
    ""








    if not path:
        return ""
    p = os.path.expanduser(path)
    try:
        st = os.stat(p)
    except OSError:
        return ""
    margine = timedelta(minutes=1)
    if dal is not None and datetime.fromtimestamp(st.st_mtime).astimezone() < dal - margine:
        return ""
    try:
        with open(p, "rb") as f:
            if st.st_size > _CODA_LOG:
                f.seek(st.st_size - _CODA_LOG)
            dati = f.read()
    except OSError:
        return ""
    righe = dati.decode("utf-8", errors="replace").splitlines()
    if st.st_size > _CODA_LOG and righe:
        righe = righe[1:]
    blocco: list[str] = []
    corrente: datetime | None = None
    for riga in righe:
        t = _istante_riga(riga)
        if t is not None:
            corrente = t
        if dal is not None and corrente is not None and corrente < dal - margine:
            blocco = []
            continue
        blocco.append(riga)
    trovate = [r.strip() for r in blocco if _ERRORE.search(r)]
    if not trovate:
        return ""
    scelta = trovate[-1]
    if scelta.startswith("Traceback"):

        coda = [r.strip() for r in blocco if r.strip()]
        scelta = coda[-1] if coda else scelta
    return _redigi(scelta)[:220]


def _workflow(j: dict[str, Any]) -> str:
    return os.path.basename(j.get("remote_path") or str(j.get("key", "")).split(":", 2)[-1])


def compute() -> dict[str, Any]:
    if not CATALOG.exists():
        return {"error": "no catalog: run jb_catalog.py --write", "jobs": []}
    cat = json.loads(CATALOG.read_text())
    _rinfresca(cat)
    events = read_events(months=3)
    windows = _presence()
    by_job: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        by_job.setdefault(e.get("job", "?"), []).append(e)

    rows = []
    for j in cat["jobs"]:



        if not j.get("ours", True):
            continue
        evs = by_job.get(j["key"], [])
        if j.get("where") == "github":
            evs = sorted(
                evs + _esiti_github(j["key"], j.get("repo"), _workflow(j)),
                key=lambda e: e.get("at") or "",
            )
        rows.append(_one(j, evs, windows))
    fatto = (cat.get("tz_skew") or {}).get("skewed") is True
    sfas, campioni = _misura_sfasamento(cat, events) if fatto else (None, 0)
    if sfas:



        for r in rows:
            if r["where"] == "local" and r["next_expected"]:
                try:
                    r["next_effective"] = stamp(parse(r["next_expected"]) + timedelta(hours=sfas))
                except ValueError:
                    pass
    rows.sort(key=lambda r: (not r["attention"], r["where"] != "local", r["key"]))
    return {
        "computed_at": stamp(),
        "tz_skew": cat.get("tz_skew", {}),
        "catalog_generated_at": cat.get("generated_at"),
        "skew_hours": sfas,
        "skew_samples": campioni,
        "attention": sum(1 for r in rows if r["attention"]),


        "overlay_complaints": cat.get("overlay_complaints") or [],
        "jobs": rows,
    }


def _one(j: dict[str, Any], evs: list[dict[str, Any]], windows) -> dict[str, Any]:
    key = j["key"]
    row: dict[str, Any] = {
        "key": key,
        "title": j.get("title") or key,
        "where": j.get("where", "local"),
        "schedule": j.get("schedule", ""),
        "next_expected": j.get("next_expected"),
        "next_effective": None,
        "loaded": j.get("loaded", False),
        "keepalive": j.get("keepalive", False),
        "log_path": j.get("log_path"),
        "log_paths": j.get("log_paths") or [],
        "last_exit": j.get("last_exit"),
        "program": j.get("program") or [],
        "calendar": j.get("calendar") or [],
        "purpose": j.get("purpose", ""),
        "damage_if_missed": j.get("damage_if_missed", ""),


        "pid": j.get("pid"),
        "plist_gone": bool(j.get("plist_gone")),
        "remote_path": j.get("remote_path"),
        "read_from": j.get("read_from"),
        "outcome": "unknown",
        "punctuality": "unknown",
        "last_run": None,
        "began_at": None,
        "detail": "",
        "history": [],
        "attention": False,
        "why": "",
    }














    def _escluso(e: dict[str, Any]) -> bool:
        d = e.get("detail") or ""
        return "[manuale]" in d or d == "dry run"

    schedulati: list[dict[str, Any]] = []
    for e in sorted(evs, key=lambda x: x.get("at") or ""):
        if e.get("phase") == "end" and _escluso(e):

            for i in range(len(schedulati) - 1, -1, -1):
                if schedulati[i].get("phase") == "start":
                    del schedulati[i]
                    break
                if schedulati[i].get("phase") == "end":
                    break
            continue
        if not _escluso(e):
            schedulati.append(e)
    starts = [e for e in schedulati if e.get("phase") == "start"]
    ends = [e for e in schedulati if e.get("phase") == "end"]









    row["history"] = [
        (MANUALE if _escluso(e) else "") + (e.get("outcome") or "unknown")
        for e in evs
        if e.get("phase") == "end"
    ][-14:]

    if ends:
        last = ends[-1]
        row["outcome"] = last.get("outcome", "unknown")
        row["last_run"] = last.get("at")
        row["detail"] = last.get("detail") or ""









        prima = [s["at"] for s in starts if s["at"] <= last.get("at", "")]
        row["began_at"] = prima[-1] if prima else None
    if starts and (not ends or starts[-1]["at"] > ends[-1]["at"]):
        row["outcome"] = "running"
        row["last_run"] = starts[-1]["at"]
        row["began_at"] = starts[-1]["at"]
        began = parse(starts[-1]["at"])
        if now() - began > timedelta(hours=6):
            row["outcome"], row["attention"] = "failed", True
            row["why"] = f"started {began:%d/%m %H:%M} and never said how it ended"



    if row["plist_gone"]:
        row["attention"] = True
        quando = row["schedule"] if row["schedule"] != "no schedule" else "when launchd says"
        row["why"] = (
            f"loaded, but its plist is gone: it still fires ({quando}) until logout or restart"
        )


    if row["keepalive"]:
        row["punctuality"] = "on_time" if row["loaded"] else "missed"
        if not row["loaded"]:
            row["attention"], row["why"] = True, "daemon not loaded"
        elif row["pid"] is None:



            row["why"] = row["why"] or "loaded, but not running now (no pid)"
    elif not evs:


        row["punctuality"] = "unknown"
        row["why"] = row["why"] or "not wired up yet: it does not declare how it ends"
    else:
        row["punctuality"], late_by = _punctuality(row, j, windows)
        if row["punctuality"] in ("missed", "stale"):
            row["attention"] = True
            row["why"] = row["why"] or (
                _gap(late_by) if late_by else "the expected run never happened"
            )








    if row["last_run"] and row["log_path"]:
        try:
            log_m = datetime.fromtimestamp(os.path.getmtime(row["log_path"])).astimezone()
            if log_m > parse(row["last_run"]) + timedelta(minutes=2):
                row["outcome"] = "unknown"
                row["attention"] = True
                row["detail"] = ""
                row["why"] = (
                    f"its log moved at {log_m:%d/%m %H:%M} but it reported nothing: "
                    "it ran again and we do not know how it went"
                )
        except (OSError, ValueError):
            pass














    codice_lc = j.get("last_exit")
    generico = row["why"].startswith("not wired up yet")
    if codice_lc and codice_lc < 0 and fermato_da_fuori(-codice_lc):
        nota = (
            f"launchd: the last run was stopped by {nome_segnale(-codice_lc)} "
            "(by hand, launchctl, logout or shutdown), not a crash"
        )
        if row["outcome"] == "failed" and row["detail"] and not row["why"]:
            row["why"] = row["detail"]
        row["why"] = nota if (not row["why"] or generico) else f"{row['why']} · {nota}"
    elif codice_lc:
        row["attention"] = True
        if row["outcome"] in ("unknown", "nothing", "ok"):
            row["outcome"] = "failed"






        if codice_lc < 0:
            testo = f"launchd says the last run was killed by {nome_segnale(-codice_lc)}"
        else:
            testo = f"launchd says the last run ended with code {codice_lc}"



        if row["detail"].startswith(GENERICO_AUTO):
            row["detail"] = ""
        motivo = row["detail"]
        if not motivo:

            dal = None
            try:
                dal = parse(row["began_at"]) if row["began_at"] else None
            except ValueError:
                dal = None
            if dal is None and row["calendar"]:
                dal = prev_fire(row["calendar"])
            riga = _riga_errore(row["log_path"], dal)
            if riga:
                motivo = f"log: {riga}"
        codice = testo + (f" — {motivo}" if motivo else "")
        row["why"] = codice if (not row["why"] or generico) else f"{row['why']} · {codice}"

    if row["outcome"] == "failed":
        row["attention"] = True
        row["why"] = row["why"] or (row["detail"] or "last run failed")
    if not row["loaded"] and row["where"] == "local" and not row["keepalive"]:
        row["attention"] = True
        row["why"] = row["why"] or "on disk but not loaded: it will never fire"
    return row


def _punctuality(row, j, windows):
    ""










    quando = row.get("began_at") or row["last_run"]
    last = parse(quando) if quando else None
    cal = j.get("calendar") or []
    if not last:
        return "unknown", None
    prev_due = prev_fire(cal) if cal else None
    if prev_due is None:


        return "unknown", None



    since = j.get("schedule_since")
    if since and prev_due < parse(since):
        return "unknown", None
    grace = GRACE_LOCAL if row["where"] == "local" else GRACE_REMOTE
    if last >= prev_due:
        return ("on_time" if last <= prev_due + grace else "late"), None
    gap = now() - last
    if gap > timedelta(days=3):
        return "stale", gap
    if _was_present(prev_due, windows) is False:
        return "missed", gap
    return "missed", gap


def write() -> dict[str, Any]:
    ""








    st = compute()
    if st.get("error") or "computed_at" not in st:
        return st
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = STATUS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    os.replace(tmp, STATUS)
    return st


def _gap(d) -> str:
    ""
    h = d.total_seconds() / 3600
    return f"no run for {h:.0f}h" if h < 48 else f"no run for {h / 24:.0f} days"


_GLYPH = {"ok": "v", "nothing": "-", "failed": "X", "skipped": "s", "running": ">", "unknown": "?"}

if __name__ == "__main__":
    st = write() if "--write" in sys.argv else compute()
    if st.get("error"):
        print(st["error"])
        raise SystemExit(1)
    skew = st.get("tz_skew") or {}
    print(f"{len(st['jobs'])} jobs - {st['attention']} need attention")
    if skew.get("skewed"):
        print(
            "  !! scheduled hours are skewed: the timezone changed at "
            f"{skew['tz_changed_at']} but the calendar evaluator is up since "
            f"{skew['evaluator_started_at']}. Logout or reboot fixes it."
        )
    print()
    for r in st["jobs"]:
        mark = "!!" if r["attention"] else "  "

        hist = (
            "".join("m" if h.startswith(MANUALE) else _GLYPH.get(h, "?") for h in r["history"])
            or "-"
        )
        nxt = (r["next_expected"] or "")[:16].replace("T", " ")
        print(
            f"{mark} {r['title'][:30]:32} {r['outcome']:8} {r['punctuality']:9} "
            f"{hist:>14}  next {nxt}"
        )
        if r["why"]:
            print(f"     {r['why'][:96]}")
