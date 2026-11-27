#!/usr/bin/env python3
"""Inbox-zero rules engine for Gmail: keeps sender-to-label rules in a JSON file, compiles them into Gmail filters, applies them (plan/execute), cleans up the inbox and can undo a cleanup from its log."""



















from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

DIR = Path(
    os.environ.get("SBK_INBOX_ZERO_DIR")
    or Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data") / "work/sbk/inbox-zero/rules"
)
LIMITE_QUERY = 1300
LIMITE_GMAIL = 1500
# Email label taxonomy: load from user config. Demo defaults below.
OWN_LABELS = ["@Newsletter", "@Receipts", "@Events"]
SENZA_REGOLA = {"PRINCIPALE", "DA DECIDERE"}
SCHEDE = ["CATEGORY_UPDATES", "CATEGORY_FORUMS", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS"]


class Fermo(Exception):
    """Raised to stop work on a mailbox when continuing would be unsafe."""





def carica(percorso: Path | None = None) -> dict:
    return json.loads((percorso or DIR / "regole.json").read_text())


def _scrivi_atomico(p: Path, testo: str) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(testo)
    tmp.replace(p)


@contextlib.contextmanager
def lucchetto():
    """Exclusive file lock on the rules directory."""
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / ".lucchetto", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def scrivi_storia(voce: dict) -> None:
    with open(DIR / "storia.jsonl", "a") as f:
        f.write(
            json.dumps(
                {"quando": datetime.now().isoformat(timespec="seconds"), **voce}, ensure_ascii=False
            )
            + "\n"
        )


def leggi_storia(quante: int) -> list[dict]:
    if not (DIR / "storia.jsonl").exists():
        return []
    out = []
    for riga in (DIR / "storia.jsonl").read_text().splitlines():
        try:
            out.append(json.loads(riga))
        except json.JSONDecodeError:
            continue
    return out[-quante:]


def _domini_della_query(q: str) -> list[str]:
    """Domains/handles listed in the from: clauses of a Gmail query."""
    out = []
    for m in re.finditer(r"(?<!-)from:(\([^)]*\)|\S+)", q):
        out += [
            t for t in re.split(r"[\s()]+", m.group(1)) if t and t.upper() != "OR" and "@" not in t
        ]
    return out


def legate(dato: dict, casella: str, mittente: str) -> list[str]:
    """Ids of the special rules (subject/domain based) that already cover this sender."""

    ids = []
    for s in dato["speciali"]:
        if s["casella"] != casella:
            continue

        q = re.sub(r"-from:(\([^)]*\)|\S+)", "", s["query"]).lower()
        if (
            s.get("mittente") == mittente
            or mittente in q
            or any(
                mittente.endswith(d) or d in mittente.split("@")[0] for d in _domini_della_query(q)
            )
        ):
            ids.append(s["id"])
    return ids


def sposta(
    casella: str, mittente: str, categoria: str, perche: str, principale: bool = False
) -> dict:
    """Move a sender to a category, recording why; refuses senders governed by special rules."""

    mittente = mittente.lower().strip()
    if not perche.strip():
        raise ValueError("A reason is required.")
    with lucchetto():
        dato = carica()
        if casella not in dato["caselle"].values():
            raise ValueError(f"Mailbox {casella} is not among the mailboxes of the rules.")
        if categoria not in dato["categorie"]:
            raise ValueError(f"Category {categoria} does not exist.")
        e = next(
            (m for m in dato["mittenti"] if m["casella"] == casella and m["mittente"] == mittente),
            None,
        )
        speciali = legate(dato, casella, mittente)
        if speciali or (e and e["categoria"] not in SENZA_REGOLA and not e.get("lista")):
            raise ValueError(
                "This sender is governed by a rule on the mail subject or on the domain. Moving it from here would "
                "contradict that rule, so the rule has to be changed together with the sender."
            )
        prima = None
        if e is None:
            e = {"casella": casella, "mittente": mittente, "mail_90gg": 0, "motivo": ""}
            dato["mittenti"].append(e)
        else:
            prima = {
                k: e.get(k) for k in ("categoria", "lista", "in_principale", "motivo", "deciso_da")
            }
            e.setdefault("prima", []).append(
                {"fino_al": datetime.now().isoformat(timespec="seconds"), **prima}
            )
        e.update(
            categoria=categoria,
            lista=categoria not in SENZA_REGOLA,
            in_principale=bool(principale and categoria == "PRINCIPALE"),
            motivo=perche,
            deciso_da="sposta",
        )
        _scrivi_atomico(DIR / "regole.json", json.dumps(dato, indent=1, ensure_ascii=False))
        scrivi_storia(
            {
                "azione": "sposta",
                "casella": casella,
                "mittente": mittente,
                "prima": prima and prima["categoria"],
                "dopo": categoria,
                "perche": perche,
                "com_era": prima,
            }
        )
    return {"mittente": mittente, "prima": prima and prima["categoria"], "dopo": categoria}


def compila(dato: dict, casella: str) -> list[dict]:
    """Compile the rules of a mailbox into the Gmail filter queries that should exist."""

    gruppi: dict[str, list[str]] = {}
    for e in dato["mittenti"]:
        if e["casella"] != casella:
            continue
        if e["categoria"] == "PRINCIPALE" and e.get("in_principale"):
            gruppi.setdefault("PRINCIPALE", []).append(e["mittente"])
        elif e.get("lista") and e["categoria"] not in SENZA_REGOLA:
            gruppi.setdefault(e["categoria"], []).append(e["mittente"])
    voluti = []

    def pezzo_fatto(cat: str, pezzo: list[str]) -> None:
        voluti.append(
            {
                "categoria": cat,
                "query": "from:(" + " OR ".join(pezzo) + ")",
                "origine": "mittenti",
                "mittenti": pezzo,
            }
        )

    for cat in sorted(gruppi):
        pezzo: list[str] = []
        for s in sorted(set(gruppi[cat])):
            if pezzo and len("from:(" + " OR ".join(pezzo + [s]) + ")") > LIMITE_QUERY:
                pezzo_fatto(cat, pezzo)
                pezzo = []
            pezzo.append(s)
        if pezzo:
            pezzo_fatto(cat, pezzo)
    for s in dato["speciali"]:
        if s["casella"] == casella:
            voluti.append(
                {
                    "categoria": s["categoria"],
                    "query": s["query"],
                    "origine": s["id"],
                    "mittenti": [s["mittente"]] if s.get("mittente") else [],
                }
            )
    for v in voluti:
        if len(v["query"]) > LIMITE_GMAIL:
            raise Fermo(
                f"Rule {v['origine']} is too long for Gmail ({len(v['query'])} characters)."
            )
        v["chiave"] = hashlib.sha1(f"{v['categoria']}|{v['query']}".encode()).hexdigest()[:16]
    return voluti


def azione(categoria: str, etichette: dict[str, str]) -> dict:
    if categoria == "PRINCIPALE":
        return {"addLabelIds": ["CATEGORY_PERSONAL"]}
    return {"addLabelIds": [etichette[categoria]], "removeLabelIds": ["INBOX"]}


def _record(x) -> dict:
    """Normalise a managed-filter entry to a dict with an id."""
    return x if isinstance(x, dict) else {"id": x}


def _uguale(f: dict, criteria: dict, action: dict) -> bool:
    return f.get("criteria") == criteria and f.get("action") == action


def piano(
    dato: dict,
    casella: str,
    filtri_vivi: list[dict],
    etichette: dict[str, str],
    gestiti: dict,
) -> dict:
    """Diff the wanted filters against the live ones: what to create, delete, leave or flag."""

    voluti = compila(dato, casella)
    vivi = {f["id"]: f for f in filtri_vivi}
    da_creare, presenti = [], {}
    for v in voluti:
        if v["categoria"] != "PRINCIPALE" and v["categoria"] not in etichette:
            da_creare.append(v)
            continue
        att = {"query": v["query"]}, azione(v["categoria"], etichette)
        trovato = next((fid for fid, f in vivi.items() if _uguale(f, *att)), None)
        if trovato:
            presenti[v["chiave"]] = trovato
        else:
            da_creare.append(v)
    da_cancellare, a_mano = [], []
    for r in map(_record, gestiti.values()):
        if r["id"] not in vivi or r["id"] in presenti.values():
            continue
        f = vivi[r["id"]]
        if "criteria" in r and not _uguale(f, r["criteria"], r["action"]):
            a_mano.append(r["id"])
        else:
            da_cancellare.append(r["id"])
    vecchi, bloccati = [], []
    for t in dato.get("da_togliere", []):
        if t["casella"] != casella or t["id"] not in vivi:
            continue
        (vecchi if _uguale(vivi[t["id"]], t["criteria"], t["action"]) else bloccati).append(t)
    mancano = sorted(
        {
            v["categoria"]
            for v in voluti
            if v["categoria"] != "PRINCIPALE" and v["categoria"] not in etichette
        }
    )
    return {
        "casella": casella,
        "voluti": len(voluti),
        "presenti": presenti,
        "da_creare": da_creare,
        "da_cancellare": sorted(da_cancellare),
        "cambiati_a_mano": sorted(a_mano),
        "vecchi_da_togliere": vecchi,
        "bloccati": bloccati,
        "etichette_da_creare": mancano,
    }





def gmail(casella: str, scope: str):
    """Gmail client of your mailbox `casella` (address or label), from its own login.

    Filters (scope gmail.settings.*) use the extra login made by
    `em-l0-auth.py <label> --settings`; labels and messages use the mailbox login
    made by `em-l0-auth.py <label>`.
    """
    tools = str(Path(__file__).resolve().parent.parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import google_oauth

    service = "sbk-gmail-settings" if scope.startswith("gmail.settings") else "sbk-gmail"
    return google_oauth.gmail_service(casella, keychain_service=service).users()


def riprova(chiamata, tentativi: int = 6):
    from googleapiclient.errors import HttpError

    for i in range(tentativi):
        try:
            return chiamata.execute()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and i < tentativi - 1:
                time.sleep(2**i)
                continue
            raise
        except (TimeoutError, ConnectionError, OSError):
            if i < tentativi - 1:
                time.sleep(2**i)
                continue
            raise


def leggi_vivo(casella: str, letture: int = 3) -> tuple[list[dict], dict[str, str], list[dict]]:
    """Read live filters and labels of a mailbox (filters read several times to be sure)."""

    fs = gmail(casella, "gmail.settings.basic").settings().filters()
    per_id: dict[str, dict] = {}
    for _ in range(letture):
        for f in riprova(fs.list(userId="me")).get("filter", []):
            per_id[f["id"]] = f
    filtri = list(per_id.values())
    labs = riprova(gmail(casella, "gmail.labels").labels().list(userId="me")).get("labels", [])
    return filtri, {e["name"]: e["id"] for e in labs}, labs


def gia_vivo(fs, fid: str, body: dict) -> bool:
    from googleapiclient.errors import HttpError

    try:
        f = riprova(fs.get(userId="me", id=fid))
    except HttpError as e:
        if e.resp.status == 404:
            return False
        raise
    return _uguale(f, body["criteria"], body["action"])


def gestiti_di(casella: str) -> dict:
    p = DIR / "gestiti.json"
    return json.loads(p.read_text()).get(casella, {}) if p.exists() else {}


def salva_gestiti(casella: str, g: dict) -> None:
    p = DIR / "gestiti.json"
    tutti = json.loads(p.read_text()) if p.exists() else {}
    tutti[casella] = g
    _scrivi_atomico(p, json.dumps(tutti, indent=1))


def cmd_stato(dato: dict) -> dict:
    out = []
    for casella in dato["caselle"].values():
        filtri, etichette, _ = leggi_vivo(casella)
        p = piano(dato, casella, filtri, etichette, gestiti_di(casella))
        cats: dict[str, int] = {}
        for e in dato["mittenti"]:
            if e["casella"] == casella:
                cats[e["categoria"]] = cats.get(e["categoria"], 0) + 1
        out.append(
            {
                "casella": casella,
                "mittenti_per_categoria": cats,
                "filtri_vivi": len(filtri),
                "voluti": p["voluti"],
                "gia_a_posto": len(p["presenti"]),
                "da_creare": len(p["da_creare"]),
                "da_cancellare": len(p["da_cancellare"]),
                "cambiati_a_mano": p["cambiati_a_mano"],
                "vecchi_da_togliere": len(p["vecchi_da_togliere"]),
                "bloccati": [t["id"] for t in p["bloccati"]],
                "etichette_da_creare": p["etichette_da_creare"],
            }
        )
    return {"caselle": out}


def _applica_casella(dato: dict, casella: str, esegui: bool, ora: str) -> dict:
    filtri, etichette, labs = leggi_vivo(casella)
    g = {k: _record(x) for k, x in gestiti_di(casella).items()}
    p = piano(dato, casella, filtri, etichette, g)
    riga = {
        "casella": casella,
        "crea": len(p["da_creare"]),
        "cancella_nostri": len(p["da_cancellare"]),
        "togli_vecchi": [t["id"] for t in p["vecchi_da_togliere"]],
        "etichette": p["etichette_da_creare"],
        "cambiati_a_mano": p["cambiati_a_mano"],
    }
    if p["bloccati"]:
        raise Fermo(
            "A previous filter changed in Gmail compared with the one to remove. Not touching this mailbox."
        )
    if not esegui or not (p["da_creare"] or p["da_cancellare"] or p["vecchi_da_togliere"]):
        return riga
    (DIR / "backup").mkdir(exist_ok=True)
    bk = DIR / "backup" / f"{ora}-{casella}.json"
    bk.write_text(json.dumps({"filtri": filtri, "etichette": labs}, indent=1))
    riga["backup"] = str(bk)
    riga["backup_sha256"] = hashlib.sha256(bk.read_bytes()).hexdigest()
    lab = gmail(casella, "gmail.labels").labels()
    for nome in p["etichette_da_creare"]:
        etichette[nome] = riprova(
            lab.create(
                userId="me",
                body={
                    "name": nome,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
        )["id"]
    fs = gmail(casella, "gmail.settings.basic").settings().filters()
    voluti = {v["chiave"]: v for v in compila(dato, casella)}
    for chiave, fid in p["presenti"].items():
        v = voluti[chiave]
        g[chiave] = {
            "id": fid,
            "criteria": {"query": v["query"]},
            "action": azione(v["categoria"], etichette),
        }
    salva_gestiti(casella, g)

    riga["creati"] = 0
    for v in p["da_creare"]:
        body = {"criteria": {"query": v["query"]}, "action": azione(v["categoria"], etichette)}

        if v["chiave"] in g and gia_vivo(fs, g[v["chiave"]]["id"], body):
            continue
        nuovo = riprova(fs.create(userId="me", body=body))
        if not gia_vivo(fs, nuovo["id"], body):
            raise Fermo(
                "A filter just written, read back from Gmail, is not the one written. Stopping on this mailbox."
            )
        g[v["chiave"]] = {"id": nuovo["id"], **body}
        salva_gestiti(casella, g)
        riga["creati"] += 1
        time.sleep(0.3)
    for fid in p["da_cancellare"]:
        riprova(fs.delete(userId="me", id=fid))
        g = {k: x for k, x in g.items() if x["id"] != fid}
        salva_gestiti(casella, g)
    for t in p["vecchi_da_togliere"]:
        riprova(fs.delete(userId="me", id=t["id"]))

    salva_gestiti(
        casella, {k: x for k, x in g.items() if k in voluti or x["id"] in p["cambiati_a_mano"]}
    )
    return riga


def cmd_applica(dato: dict, esegui: bool) -> dict:
    """Apply the plan to every mailbox (dry run unless esegui is True)."""
    esito = []
    ora = datetime.now().strftime("%Y%m%d-%H%M%S")
    for casella in dato["caselle"].values():
        try:
            riga = _applica_casella(dato, casella, esegui, ora)
        except Fermo as e:
            riga = {"casella": casella, "errore": str(e)}
        except Exception as e:
            riga = {
                "casella": casella,
                "errore": f"Gmail did not answer as expected ({type(e).__name__}).",
            }
        esito.append(riga)
        if esegui and (
            riga.get("creati")
            or riga.get("cancella_nostri")
            or riga.get("togli_vecchi")
            or riga.get("errore")
        ):
            scrivi_storia({"azione": "applica", "esito": [riga]})
    return {"eseguito": esegui, "caselle": esito}


def cerca_ids(m, q: str) -> list[str]:
    ids, tok = [], None
    while True:
        r = riprova(m.list(userId="me", q=q, pageToken=tok, maxResults=500))
        ids += [x["id"] for x in r.get("messages", [])]
        tok = r.get("nextPageToken")
        if not tok:
            return ids


def cmd_pulizia(dato: dict, solo: str | None, esegui: bool) -> dict:
    """Apply the rules to the mail already in the inbox, logging every change for undo."""

    esito = []
    ora = datetime.now().strftime("%Y%m%d-%H%M%S")
    for casella in dato["caselle"].values():
        if solo and casella != solo:
            continue
        _, etichette, _ = leggi_vivo(casella)
        m = gmail(casella, "gmail.modify").messages()
        regole = compila(dato, casella) + [
            x for x in dato.get("solo_pulizia", []) if x["casella"] == casella
        ]
        visti: set[str] = set()
        conta: dict[str, int] = {}
        modificate = 0
        reg = None
        if esegui:
            (DIR / "pulizie").mkdir(exist_ok=True)
            reg = DIR / "pulizie" / f"{ora}-{casella}.jsonl"
        for v in regole:
            cat = v["categoria"]
            if cat != "PRINCIPALE" and cat not in etichette:
                conta[cat] = conta.get(cat, 0)
                continue
            ids = [i for i in cerca_ids(m, f"({v['query']}) in:inbox") if i not in visti]
            visti.update(ids)
            conta[cat] = conta.get(cat, 0) + len(ids)
            if not esegui:
                continue
            for i in ids:
                prima = riprova(m.get(userId="me", id=i, format="minimal")).get("labelIds", [])
                if cat == "PRINCIPALE":
                    aggiungi = [] if "CATEGORY_PERSONAL" in prima else ["CATEGORY_PERSONAL"]
                    togli = [x for x in SCHEDE if x in prima]
                else:
                    aggiungi = [] if etichette[cat] in prima else [etichette[cat]]
                    togli = ["INBOX"] if "INBOX" in prima else []
                if not (aggiungi or togli):
                    continue

                with open(reg, "a") as f:
                    f.write(
                        json.dumps(
                            {
                                "id": i,
                                "aggiunte": aggiungi,
                                "tolte": togli,
                                "regola": v.get("origine"),
                            }
                        )
                        + "\n"
                    )
                riprova(
                    m.modify(
                        userId="me", id=i, body={"addLabelIds": aggiungi, "removeLabelIds": togli}
                    )
                )
                modificate += 1
        riga = {"casella": casella, "per_categoria": conta, "totale": sum(conta.values())}
        if esegui:
            riga["registro"] = str(reg)
            riga["modificate"] = modificate
            scrivi_storia({"azione": "pulizia", "esito": [riga]})
        esito.append(riga)
    return {"eseguito": esegui, "caselle": esito}


def leggi_registro(registro: Path) -> tuple[str, list[dict]]:
    """Read a cleanup log: (mailbox, rows)."""
    if registro.suffix == ".jsonl":
        casella = registro.stem.split("-", 2)[2]
        righe = [json.loads(r) for r in registro.read_text().splitlines() if r.strip()]
        return casella, righe
    r = json.loads(registro.read_text())
    return r["casella"], r["mail"]


def cmd_annulla(registro: Path, esegui: bool) -> dict:
    from googleapiclient.errors import HttpError

    casella, righe = leggi_registro(registro)
    m = gmail(casella, "gmail.modify").messages()
    rimesse, sparite = 0, []
    if esegui:
        for x in righe:
            try:
                riprova(
                    m.modify(
                        userId="me",
                        id=x["id"],
                        body={"addLabelIds": x["tolte"], "removeLabelIds": x["aggiunte"]},
                    )
                )
                rimesse += 1
            except HttpError as e:
                if e.resp.status != 404:
                    raise
                sparite.append(x["id"])
        scrivi_storia(
            {
                "azione": "annulla",
                "casella": casella,
                "registro": str(registro),
                "rimesse": rimesse,
                "sparite": len(sparite),
            }
        )
    return {
        "eseguito": esegui,
        "casella": casella,
        "mail": len(righe),
        "rimesse": rimesse,
        "sparite": sparite,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json", action="store_true", help="compact JSON output")
    # English subcommands; the older Italian names stay as hidden aliases (not in the help).
    canonical = {
        "stato": "status",
        "elenco": "list",
        "sposta": "move",
        "applica": "apply",
        "pulizia": "cleanup",
        "annulla": "undo",
    }
    italian = {v: k for k, v in canonical.items()}
    sub = ap.add_subparsers(
        dest="cmd", required=True, metavar="{status,list,move,apply,cleanup,undo}"
    )

    def command(name: str, text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, aliases=[italian[name]], description=text)

    def execute_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--execute", dest="esegui", action="store_true", help="do it (default: plan only)"
        )
        p.add_argument("--esegui", dest="esegui", action="store_true", help=argparse.SUPPRESS)

    def mailbox_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument("--mailbox", dest="casella", metavar="LABEL", help="only this mailbox label")
        p.add_argument("--casella", dest="casella", help=argparse.SUPPRESS)

    command(
        "status",
        "Read-only: for each mailbox, senders per category and the plan against the live Gmail filters.",
    )
    el = command("list", "List the sender rules and the special rules.")
    mailbox_flag(el)
    sp = command("move", "Move a sender to a category (label) in one mailbox.")
    sp.add_argument("casella", metavar="mailbox")
    sp.add_argument("mittente", metavar="sender")
    sp.add_argument("categoria", metavar="category")
    sp.add_argument("--reason", dest="perche", metavar="TEXT", help="why (kept in the history)")
    sp.add_argument("--perche", dest="perche", help=argparse.SUPPRESS)
    sp.add_argument(
        "--main",
        dest="principale",
        action="store_true",
        help="with the PRINCIPALE category, keep it in the inbox",
    )
    sp.add_argument("--principale", dest="principale", action="store_true", help=argparse.SUPPRESS)
    a = command("apply", "Compile the rules into Gmail filters and apply them.")
    execute_flag(a)
    pu = command(
        "cleanup",
        "Apply the rules to the mail already in the inbox, logging every change for undo.",
    )
    mailbox_flag(pu)
    execute_flag(pu)
    an = command("undo", "Undo a cleanup from the log file it wrote.")
    an.add_argument("registro", type=Path, metavar="log")
    execute_flag(an)
    args = ap.parse_args()
    args.cmd = canonical.get(args.cmd, args.cmd)
    if args.cmd == "move" and not args.perche:
        ap.error("move: --reason is required")
    if args.cmd == "move":
        out = sposta(args.casella, args.mittente, args.categoria, args.perche, args.principale)
    elif args.cmd == "undo":
        out = cmd_annulla(args.registro, args.esegui)
    else:
        dato = carica()
        if args.cmd == "status":
            out = cmd_stato(dato)
        elif args.cmd == "list":
            out = {
                "mittenti": [
                    e for e in dato["mittenti"] if not args.casella or e["casella"] == args.casella
                ],
                "speciali": [
                    s for s in dato["speciali"] if not args.casella or s["casella"] == args.casella
                ],
            }
        elif args.cmd == "apply":
            out = cmd_applica(dato, args.esegui)
        else:
            out = cmd_pulizia(dato, args.casella, args.esegui)
    print(json.dumps(out, indent=None if args.json else 1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
