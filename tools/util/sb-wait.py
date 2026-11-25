#!/usr/bin/env python3
"""The queue of decisions waiting on you: rebuilds attese-owner.md from the registry and the ledger, adds, closes and reopens items."""



























































from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path








CODICE = Path(__file__).resolve().parents[2]



PROJECT = Path(os.environ.get("SB_PROJECT") or CODICE).resolve()
CTX = Path(os.environ.get("SB_ATTESE_DIR") or PROJECT / "sbk" / "context").resolve()
REGISTRO = CTX / "attese-owner.json"
LEDGER = CTX / "attese-esiti.jsonl"
CODA_MD = CTX / "attese-owner.md"

if str(CODICE / "tools") not in sys.path:
    sys.path.insert(0, str(CODICE / "tools"))
import sbk_config as cfg  # noqa: E402

WAIT_START = cfg.SB_WAIT_START
WAIT_END = cfg.SB_WAIT_END

ESITI = ("fatta", "annullata", "non-piu-applicabile", "delegata")

PROVA_MIN = 12





def _git_show(rev_path: str) -> str | None:
    ""
    try:
        out = subprocess.run(
            ["git", "-C", str(PROJECT), "show", rev_path],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout if out.returncode == 0 else None


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(PROJECT).as_posix()
    except ValueError:
        return str(p)


def leggi_ledger(testo: str | None = None) -> tuple[list[dict], list[str]]:
    ""

    problemi: list[str] = []
    righe: list[dict] = []
    if testo is None:
        if not LEDGER.exists():
            return righe, problemi
        testo = LEDGER.read_text(errors="replace")
    for n, ln in enumerate(testo.splitlines(), 1):
        if not ln.strip():
            continue
        try:
            righe.append(json.loads(ln))
        except json.JSONDecodeError:
            problemi.append(
                f"ledger line {n}: unreadable JSON — ignored, NEVER delete it "
                "(it's a closure with proof that no one can reconstruct)"
            )
    return righe, problemi


def chiusi(ledger: list[dict]) -> dict[str, dict]:
    ""





    out: dict[str, dict] = {}
    for r in ledger:
        g = r.get("gruppo")
        if not g:
            continue
        if r.get("tipo") == "chiusura":
            out[g] = r
        elif r.get("tipo") == "riapertura":
            out.pop(g, None)
    return out


def leggi_registro(testo: str | None = None) -> tuple[dict | None, str | None]:
    if testo is None:
        if not REGISTRO.exists():
            return None, "missing"
        try:
            testo = REGISTRO.read_text(errors="replace")
        except OSError as exc:
            return None, f"unreadable ({exc})"
    try:
        d = json.loads(testo)
    except json.JSONDecodeError as exc:
        return None, f"invalid or truncated JSON ({exc})"
    if not isinstance(d, dict) or "gruppi" not in d or "voci" not in d:
        return None, "unknown structure ('gruppi' or 'voci' missing)"
    return d, None





def _appendi_ledger(riga: dict) -> None:
    ""
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(riga, ensure_ascii=False) + "\n")


def _slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    pezzi = [p for p in t.split("-") if p][:3]
    return "-".join(pezzi) or "voce"


def _id_libero(reg: dict, base: str) -> str:
    presi = {g["id"] for g in reg["gruppi"]}
    cand, n = f"G-{base}", 2
    while cand in presi:
        cand, n = f"G-{base}-{n}", n + 1
    return cand


def _scrivi_registro(reg: dict) -> None:
    cfg.scrivi_atomico(REGISTRO, json.dumps(reg, ensure_ascii=False, indent=1))


def aperture_orfane(ledger: list[dict], reg: dict, ch: dict[str, dict]) -> list[str]:
    ""







    nel_registro = {g["id"] for g in reg["gruppi"]}
    return [
        r["gruppo"]
        for r in ledger
        if r.get("tipo") == "apertura"
        and r.get("gruppo")
        and r["gruppo"] not in nel_registro
        and r["gruppo"] not in ch
    ]






_VOLATILE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?m)^> Regenerated on .*$"), "> Regenerated on <date>"),
    (
        re.compile(
            r"🔴 \*\*(?:overdue since \d{4}-\d{2}-\d{2}, \d+ days ago"
            r"|due in \d+ days \(\d{4}-\d{2}-\d{2}\)"
            r"|due TODAY \(\d{4}-\d{2}-\d{2}\))\*\*"
        ),
        "🔴 **<deadline>**",
    ),
    (re.compile(r"\b\d+ days\b"), "<n> days"),
)


def _impronta(md: str) -> str:
    ""





    md = unicodedata.normalize("NFC", md)
    for rx, sost in _VOLATILE:
        md = rx.sub(sost, md)
    return md





def stato_coda(oggi: dt.date | None = None) -> dict:
    ""



    oggi = oggi or dt.date.today()
    rossi: list[str] = []
    gialli: list[str] = []

    reg, err = leggi_registro()
    head_txt = _git_show(f"HEAD:{_rel(REGISTRO)}")
    head_reg, _ = leggi_registro(head_txt) if head_txt is not None else (None, None)

    if reg is None:
        if head_reg is None:

            return {"installata": False, "aperte": 0, "chiuse": 0, "rossi": [], "gialli": []}
        rossi.append(
            f"the queue is NOT empty: it is UNREACHABLE — {_rel(REGISTRO)} {err}, "
            f"but in HEAD it has {len(head_reg['gruppi'])} items. "
            "Recover it (`git checkout HEAD -- " + _rel(REGISTRO) + "`) before committing."
        )
        return {"installata": True, "aperte": 0, "chiuse": 0, "rossi": rossi, "gialli": gialli}

    ledger, probs = leggi_ledger()
    gialli.extend(probs)
    if not LEDGER.exists():
        rossi.append(
            f"registry present but ledger {_rel(LEDGER)} missing: without the ledger a vanished "
            "item and a closed item are indistinguishable — the queue is not verifiable"
        )
    ch = chiusi(ledger)
    aperti = [g for g in reg["gruppi"] if g["id"] not in ch]






    if not aperti:
        prima = len(head_reg["gruppi"]) if head_reg else 0
        if prima > 0 and len(ch) < prima:
            rossi.append(
                f"the queue is NOT empty: it is UNREACHABLE — 0 open items and only "
                f"{len(ch)} closures with proof in the ledger, but in HEAD there were {prima}. "
                "A queue empties by closing with proof, not on its own."
            )
        elif prima == 0 and not ch:
            gialli.append("empty queue and empty ledger: credible only if it never started")


    if head_reg:
        ora = {g["id"] for g in reg["gruppi"]}
        perse = [g for g in head_reg["gruppi"] if g["id"] not in ora and g["id"] not in ch]
        if perse:
            rossi.append(
                f"{len(perse)} items vanished from the registry with no outcome in the ledger: "
                "vanishing is not closing. "
                + " · ".join(f"{g['id']} ({g['riga'][:50]}…)" for g in perse[:3])
            )
        vora = {v["id"] for v in reg["voci"]}
        vperse = [v for v in head_reg["voci"] if v["id"] not in vora]
        if vperse:
            rossi.append(
                f"{len(vperse)} detail lines vanished from the registry: "
                + " · ".join(f"{v['id']}" for v in vperse[:5])
            )


    if aperti and not CODA_MD.exists():
        rossi.append(
            f"{len(aperti)} open items but {_rel(CODA_MD)} does not exist: "
            "you see nothing. Regenerate it with `sb-wait.py genera`."
        )
    elif CODA_MD.exists():







        if _impronta(CODA_MD.read_text(errors="replace")) != _impronta(rendi_md(reg, ch, oggi)):
            gialli.append(
                f"{_rel(CODA_MD)} differs from how it regenerates (a CONTENT difference, "
                "not a date one): it is a DERIVED file, not edited by hand "
                "(`sb-wait.py genera` realigns it)"
            )


    for r in ch.values():
        if len(str(r.get("prova") or "")) < PROVA_MIN:
            rossi.append(f"closure without useful proof: {r.get('gruppo')} → «{r.get('prova')}»")


    orfane = aperture_orfane(ledger, reg, ch)
    if orfane:
        rossi.append(
            f"{len(orfane)} items OPEN in the ledger but absent from the registry "
            f"({' · '.join(orfane[:3])}): the entry was recorded and the item was not — "
            "rewrite it in the registry, it was never closed"
        )

    return {
        "installata": True,
        "aperte": len(aperti),
        "chiuse": len(ch),
        "rossi": rossi,
        "gialli": gialli,
    }





def _eta(data: str | None, oggi: dt.date) -> int | None:
    if not data:
        return None
    try:
        return (oggi - dt.date.fromisoformat(data)).days
    except ValueError:
        return None


def _giorni_scadenza(g: dict, oggi: dt.date) -> int | None:
    ""
    sc = g.get("scadenza")
    if not sc:
        return None
    try:
        return (oggi - dt.date.fromisoformat(sc)).days
    except ValueError:
        return None


def ordina(gruppi: list[dict], oggi: dt.date) -> list[dict]:
    ""



    def chiave(g: dict) -> tuple[int, str, int]:
        sc = g.get("scadenza")
        if sc:
            return (0, sc, 0)
        e = _eta(g.get("data"), oggi)

        return (1, "", -(e if e is not None else 10_000))

    return sorted(gruppi, key=chiave)


def rendi_md(reg: dict, ch: dict[str, dict], oggi: dt.date) -> str:
    aperti = [g for g in reg["gruppi"] if g["id"] not in ch]
    con_scadenza = [g for g in aperti if g.get("scadenza")]
    inev = [g for g in aperti if g.get("classe") != "INCERTO" and not g.get("scadenza")]
    inc = [g for g in aperti if g.get("classe") == "INCERTO" and not g.get("scadenza")]
    n_inev = sum(1 for g in aperti if g.get("classe") != "INCERTO")
    n_inc = len(aperti) - n_inev
    n_voci = sum(len(g.get("voci") or []) for g in aperti)

    def _max_eta(gs: list[dict]) -> int:
        return max((e for e in (_eta(g.get("data"), oggi) for g in gs) if e is not None), default=0)

    eta_certa = _max_eta([g for g in aperti if g.get("classe") != "INCERTO"])
    eta_tutte = _max_eta(aperti)

    def riga(g: dict) -> str:
        eta = _eta(g.get("data"), oggi)
        d = _giorni_scadenza(g, oggi)
        testa = ""
        if d is not None:


            if d > 0:
                testa = f"🔴 **overdue since {g['scadenza']}, {d} days ago** — "
            elif d == 0:
                testa = f"🔴 **due TODAY ({g['scadenza']})** — "
            else:
                testa = f"🔴 **due in {-d} days ({g['scadenza']})** — "
        if g.get("classe") == "INCERTO" and g.get("scadenza"):
            testa += "*(to confirm)* "
        eta_s = f" · idle for **{eta} days**" if eta is not None else " · **no date**"

        return f"- {testa}{g['riga']}{eta_s}\n  <sub>`{g['id']}` · {g['fonte']}</sub>\n"

    out = [
        "<!-- GENERATED by tools/util/sb-wait.py — do not edit by hand: it is regenerated -->\n",
        "# ⛔ Awaiting\n\n",
        "> Items awaiting a decision, not work to do. This list does not expire and is not\n",
        "> archived: an item leaves only with an outcome written in the ledger\n",
        "> (`sbk/context/attese-esiti.jsonl`), never by moving it and never because it's old.\n",
        "> The age is **computed**, not written: a hand-written number ages in silence.\n",
        '> Missing one? `sb-wait.py aggiungi --riga "…" --fonte "file:riga"` — the entry\n',
        "> door is open, otherwise in two weeks this is the archive again.\n",
        f"> Regenerated on {oggi.isoformat()} · **{n_inev} open** + {n_inc} to confirm "
        f"· the oldest from **{eta_certa} days** (among the to-confirm ones there's one from "
        f"{eta_tutte}) · {n_voci} source lines\n"
        "> ⚠️ **This list is not everything.** It comes from a census of `live-state.md` and "
        "`SESSION-LOG.md`: decisions that live in the memory topic files, in the "
        "dossiers under `docs/` or in the chats are not here. **If something isn't here it does "
        "not mean it doesn't exist**: look elsewhere too, and if you find it add it with "
        "`sb-wait.py aggiungi`. An authoritative list that stays silent about its own scope turns off "
        "the search elsewhere, and that's worse than no list.\n"
        "> Registry: `sbk/context/attese-owner.json` · full audit history: "
        "`~/.sbk-data/docs/sbk/audits/example-audit/registro-canonico.md`\n\n",
        "## ⏰ With a deadline\n\n",
    ]
    out += [riga(g) for g in ordina(con_scadenza, oggi)]
    out += ["\n## Awaiting a decision\n\n"]
    out += [riga(g) for g in ordina(inev, oggi)]
    out += [
        "\n## To confirm (unclear whether they're open)\n\n",
        "> The live ones rise above, the others are closed with an outcome.\n\n",
    ]
    out += [riga(g) for g in ordina(inc, oggi)]
    if ch:
        out.append("\n## Closed, with proof\n\n")
        for r in sorted(ch.values(), key=lambda x: x.get("data", "")):
            g = next((x for x in reg["gruppi"] if x["id"] == r["gruppo"]), None)
            titolo = g["riga"] if g else r["gruppo"]
            out.append(f"- ~~{titolo}~~ → **{r.get('esito')}** ({r.get('data')})\n")
            out.append(f"  <sub>proof: {r.get('prova')}</sub>\n")
    return "".join(out)


def rendi_blocco(reg: dict, ch: dict[str, dict], oggi: dt.date) -> str:
    ""



    aperti = [g for g in reg["gruppi"] if g["id"] not in ch]
    inev = [g for g in aperti if g.get("classe") != "INCERTO"]
    inc = [g for g in aperti if g.get("classe") == "INCERTO"]
    eta = [
        e
        for e in (_eta(g.get("data"), oggi) for g in aperti if g.get("classe") != "INCERTO")
        if e is not None
    ]
    vecchia = max(eta) if eta else 0





    _d = {g["id"]: _giorni_scadenza(g, oggi) for g in aperti}
    fut = sorted(
        (g for g in aperti if _d[g["id"]] is not None and _d[g["id"]] < 0),
        key=lambda g: g["scadenza"],
    )
    scadute = sorted(
        (g for g in aperti if _d[g["id"]] is not None and _d[g["id"]] >= 0),
        key=lambda g: g["scadenza"],
    )
    coda_riga = ""
    if fut:
        coda_riga = f" · **next deadline {fut[0]['scadenza']}**"
    if scadute:
        oggi_n = sum(1 for g in scadute if _d[g["id"]] == 0)
        etichetta = "overdue" if not oggi_n else f"overdue ({oggi_n} TODAY)"
        coda_riga += f" · **{len(scadute)} already {etichetta}** (since {scadute[0]['scadenza']})"
    return (
        f"{WAIT_START}\n"
        f"## ⛔ {len(inev)} decisions await you — the oldest from {vecchia} days{coda_riga}\n"
        f"> Full list: `sbk/context/attese-owner.md` "
        f"(+{len(inc)} to confirm). You leave only with an outcome: "
        f"`uv run python tools/util/sb-wait.py chiudi --gruppo … --prova …`\n"
        f"{WAIT_END}\n"
    )


def rendi_ambient(reg: dict, ch: dict[str, dict], oggi: dt.date) -> str:
    ""

    aperti = [g for g in reg["gruppi"] if g["id"] not in ch]
    inev = [g for g in aperti if g.get("classe") != "INCERTO"]
    top = ordina(inev, oggi)[:5]
    eta = [e for e in (_eta(g.get("data"), oggi) for g in inev) if e is not None]
    out = [
        f"## ⛔ {len(inev)} decisions await you "
        f"(the oldest from {max(eta) if eta else 0} days · updated {oggi.isoformat()})\n\n"
    ]
    for g in top:
        e = _eta(g.get("data"), oggi)
        d = _giorni_scadenza(g, oggi)
        testa = ""
        if d is not None:
            if d > 0:
                testa = f"[OVERDUE by {d} days] "
            elif d == 0:
                testa = "[DUE TODAY] "
            else:
                testa = f"[due in {-d} days] "
        pulita = g["riga"].replace("**", "").replace("`", "")
        out.append(
            f"- {testa}{pulita[:150]}" + (f" — idle for {e} days" if e is not None else "") + "\n"
        )
    out.append("\nFull list: `sbk/context/attese-owner.md`\n")
    return "".join(out)



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("genera", help="rewrites attese-owner.md from the registry + ledger")
    sub.add_parser("check", help="the guard: exit 1 if the queue is unreachable")
    sub.add_parser("blocco", help="prints the 3 lines for live-state.md")
    sub.add_parser("ambient", help="prints the block for ambient-context.md")
    c = sub.add_parser("chiudi", help="closes an item, ONLY with proof")
    c.add_argument("--gruppo", required=True)
    c.add_argument("--esito", required=True, choices=ESITI)
    c.add_argument("--prova", required=True, help="file:line, link, task id — not an empty sentence")
    a = sub.add_parser("aggiungi", help="adds a NEW item to the queue (registry + ledger)")
    a.add_argument("--riga", required=True, help="what it awaits from you, in one line")
    a.add_argument("--fonte", required=True, help="where it comes from: file:line, link, who said it")
    a.add_argument("--classe", default="INEVASO", choices=("INEVASO", "INCERTO"))
    a.add_argument("--data", default=None, help="when the item was created (default: today)")
    a.add_argument("--scadenza", default=None, help="YYYY-MM-DD, if it has one")
    a.add_argument("--id", dest="gid", default=None, help="group id (default: from the text)")
    rr = sub.add_parser("riapri", help="puts back in the queue an item closed by mistake")
    rr.add_argument("--gruppo", required=True)
    rr.add_argument("--motivo", required=True, help="why the closure didn't hold")
    args = ap.parse_args()
    oggi = dt.date.today()

    if args.cmd == "check":
        st = stato_coda(oggi)
        if not st["installata"]:
            print("🟡 queue not installed (sbk/context/attese-owner.json does not exist)")
            return 0
        for r in st["rossi"]:
            print("🔴 " + r)
        for g in st["gialli"]:
            print("🟡 " + g)
        if not st["rossi"]:
            print(f"✅ queue reachable: {st['aperte']} open · {st['chiuse']} closed with proof")
        return 1 if st["rossi"] else 0

    reg, err = leggi_registro()
    if reg is None:
        print(f"🔴 registry not readable: {err}", file=sys.stderr)
        return 1
    ledger, probs = leggi_ledger()
    for p in probs:
        print("🟡 " + p, file=sys.stderr)
    ch = chiusi(ledger)

    if args.cmd == "genera":
        cfg.scrivi_atomico(CODA_MD, rendi_md(reg, ch, oggi))
        st = stato_coda(oggi)
        print(f"written {_rel(CODA_MD)} — {st['aperte']} open, {st['chiuse']} closed")
        return 1 if st["rossi"] else 0
    if args.cmd == "blocco":
        print(rendi_blocco(reg, ch, oggi), end="")
        return 0
    if args.cmd == "ambient":
        print(rendi_ambient(reg, ch, oggi), end="")
        return 0
    if args.cmd == "aggiungi":
        for campo, val in (("--riga", args.riga), ("--fonte", args.fonte)):
            if not val.strip():
                print(f"🔴 {campo} empty", file=sys.stderr)
                return 1
        for campo, val in (("--data", args.data), ("--scadenza", args.scadenza)):
            if val:
                try:
                    dt.date.fromisoformat(val)
                except ValueError:
                    print(f"🔴 {campo} is not a YYYY-MM-DD date: {val}", file=sys.stderr)
                    return 1
        gid = args.gid or _id_libero(reg, _slug(args.riga))
        if gid in {g["id"] for g in reg["gruppi"]}:
            print(
                f"🔴 id already used: {gid} (the item already exists, reopen it if anything)", file=sys.stderr
            )
            return 1
        nuovo = {
            "id": gid,
            "scadenza": args.scadenza,
            "data": args.data or oggi.isoformat(),
            "classe": args.classe,
            "riga": args.riga.strip(),
            "fonte": args.fonte.strip(),
            "voci": [],
        }

        _appendi_ledger(
            {
                "data": oggi.isoformat(),
                "tipo": "apertura",
                "gruppo": gid,
                "classe": nuovo["classe"],
                "riga": nuovo["riga"],
                "fonte": nuovo["fonte"],
                "scadenza": nuovo["scadenza"],
                "data_attesa": nuovo["data"],
            }
        )
        reg["gruppi"].append(nuovo)
        _scrivi_registro(reg)
        ledger, _ = leggi_ledger()
        cfg.scrivi_atomico(CODA_MD, rendi_md(reg, chiusi(ledger), oggi))
        print(f"added {gid} ({nuovo['classe']}) — {_rel(CODA_MD)} regenerated")
        return 0

    if args.cmd == "riapri":
        if args.gruppo not in {g["id"] for g in reg["gruppi"]}:
            print(f"🔴 unknown group: {args.gruppo}", file=sys.stderr)
            return 1
        if args.gruppo not in ch:
            print(f"🟡 {args.gruppo} is already open: nothing to do")
            return 0


        _appendi_ledger(
            {
                "data": oggi.isoformat(),
                "tipo": "riapertura",
                "gruppo": args.gruppo,
                "motivo": args.motivo.strip(),
                "annulla_chiusura_del": ch[args.gruppo].get("data"),
            }
        )
        ledger, _ = leggi_ledger()
        cfg.scrivi_atomico(CODA_MD, rendi_md(reg, chiusi(ledger), oggi))
        print(f"reopened {args.gruppo} — {_rel(CODA_MD)} regenerated (the closure stays in the ledger)")
        return 0

    if args.cmd == "chiudi":
        if args.gruppo not in {g["id"] for g in reg["gruppi"]}:
            print(f"🔴 unknown group: {args.gruppo}", file=sys.stderr)
            return 1
        if len(args.prova) < PROVA_MIN:
            print(
                f"🔴 proof too short ({len(args.prova)} chars): need a file:line, "
                "a link or a task id, not a sentence",
                file=sys.stderr,
            )
            return 1
        _appendi_ledger(
            {
                "data": oggi.isoformat(),
                "tipo": "chiusura",
                "gruppo": args.gruppo,
                "esito": args.esito,
                "prova": args.prova,
            }
        )
        ledger, _ = leggi_ledger()
        cfg.scrivi_atomico(CODA_MD, rendi_md(reg, chiusi(ledger), oggi))
        print(f"closed {args.gruppo} ({args.esito}) — {_rel(CODA_MD)} regenerated")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
