#!/usr/bin/env python3
""











from __future__ import annotations

import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "email" / "em-util-inbox-zero.py"
_spec = importlib.util.spec_from_file_location("em_util_inbox_zero", _SRC)
IZ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IZ)

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

CATEGORIE = [
    (
        "PRINCIPALE",
        "Main",
        "tray.full.fill",
        "blue",
        "Stays in the inbox, in the Main tab, and you get the notification.",
    ),
    (
        "DA DECIDERE",
        "To decide",
        "questionmark.circle.fill",
        "gray",
        "No rule. The email stays where Gmail puts it until you choose a category.",
    ),
    (
        "@Newsletter",
        "Newsletter",
        "newspaper.fill",
        "teal",
        "Newsletters and promotions. They leave the inbox and stay in the @Newsletter label, never deleted.",
    ),
    (
        "@Notifiche",
        "Notifications",
        "bell.fill",
        "orange",
        "Automated service alerts, access codes, new sign-ins. They leave the inbox, @Notifiche label.",
    ),
    (
        "@Ricevute",
        "Receipts",
        "doc.text.fill",
        "green",
        "Receipts, invoices and payment confirmations. @Ricevute label, you find them there when needed.",
    ),
    (
        "@Eventi",
        "Events",
        "calendar",
        "pink",
        "Invitations to events, webinars and trade fairs. People's calendar invites stay in Main. @Eventi label.",
    ),
    (
        "@Cold",
        "Cold",
        "hand.raised.fill",
        "red",
        "Unsolicited sales pitches. They leave the inbox, @Cold label.",
    ),
    (
        "@PEC",
        "PEC",
        "checkmark.seal.fill",
        "indigo",
        "Certified email (PEC) from any provider. @PEC label.",
    ),
    (
        "@Firme",
        "Closed signatures",
        "signature",
        "purple",
        "Signature envelopes already completed or cancelled. Signature requests stay in Main.",
    ),
]


TESTI = {
    "titolo": "Mail",
    "sotto_verdetto": "The rules apply to incoming mail. Nothing is deleted, the mail ends up in a label.",
    "pulsante": "Push to Gmail",
    "aiuto_pulsante": "Writes the changed rules to Gmail and removes the ones no longer needed, after saving a copy of the current filters.",
    "aiuto_pulsante_fermo": "Gmail already has the rules from the list, there is nothing to push.",
    "conferma_titolo": "Push the rules to Gmail?",
    "aiuto_icona_ok": "Gmail has the same rules as the list.",
    "aiuto_icona_da_fare": "The list changed and Gmail does not know yet.",
    "aiuto_rotella": "I'm working on Gmail or on the list. The senders menu comes back when I'm done.",
    "caselle": "Mailboxes",
    "aiuto_conto_caselle": "The mailboxes with the rules.",
    "aiuto_pallino_ok": "Green, Gmail has exactly the rules from the list for this mailbox.",
    "aiuto_pallino_da_fare": "Orange, for this mailbox there is something to push to Gmail or to check.",
    "aiuto_conti": "How many senders there are in each category, for this mailbox.",
    "aiuto_tessera": "Click to see the senders of this mailbox below.",
    "mittenti_di": "Senders of",
    "aiuto_conto_mittenti": "How many senders match the chosen search and category.",
    "cerca": "Search a sender",
    "tutte": "All",
    "aiuto_filtro": "Shows only the senders of one category.",
    "nessuno": "No sender with these criteria.",
    "troppi": "You see {n} of {tot}, the most frequent first. Search a name or choose a category to narrow down.",
    "aiuto_mail": "The emails received from this sender in the last 90 days, counted when the list was made.",
    "aiuto_menu": "Click to move it to another category.",
    "aiuto_menu_fermo": "On this sender a rule on the email subject or on the domain decides, so it does not move from here.",
    "foglio_titolo": "Move",
    "foglio_va_in": "Goes to",
    "foglio_perche": "Why",
    "foglio_nota": "On Gmail it changes when you press «Push to Gmail». A moved sender can cause other rules of the same label to be rewritten, because senders sit in alphabetically ordered lists.",
    "foglio_annulla": "Cancel",
    "foglio_sposta": "Move",
    "storia": "Latest changes",
}


def _quando(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if d.date() == datetime.now().date():
        giorno = "today"
    else:
        giorno = f"{MESI[d.month - 1]} {d.day}"
    return f"{giorno} at {d:%H:%M}"


def _regole(n: int) -> str:
    return "1 rule" if n == 1 else f"{n} rules"


def _cambi(n: int) -> str:
    return "one change" if n == 1 else f"{n} changes"


def _nome_categoria(cid: str | None) -> str:
    if not cid:
        return "no category"
    return next((c[1] for c in CATEGORIE if c[0] == cid), cid)


def _nome_casella(c: str) -> str:
    return c.split("@", 1)[1].split(".")[0]


def _nota(motivo: str) -> str:
    ""
    t = (motivo or "").replace(";", ".").replace(":", ",")
    t = re.sub(
        r"\s*\((?:era|prima) [^)]*\bper\s*\)", "", t
    )
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.")
    return (t[:1].upper() + t[1:] + ".") if t else ""


def _aiuto_mittente(e: dict, cat: tuple, spostabile: bool) -> str:
    if e["categoria"] == "PRINCIPALE":
        base = (
            (
                "Stays in Main and you get the notification. A rule brings it back there when Gmail would put it in "
                "another tab."
            )
            if e.get("in_principale")
            else ("No rule. Stays in the inbox, in the tab Gmail chooses.")
        )
    else:
        base = cat[4]
    nota = _nota(e.get("motivo", ""))
    out = base + (f" Why it is here. {nota}" if nota else "")
    if not spostabile:
        out += " " + TESTI["aiuto_menu_fermo"]
    return out


def _frase_storia(v: dict) -> str:
    a = v.get("azione")
    if a == "sposta":
        return f"{v['mittente']} from {_nome_categoria(v.get('prima'))} to {_nome_categoria(v['dopo'])}. {v.get('perche', '')}".strip()
    esito = v.get("esito", [])
    if a == "applica":
        nomi = ", ".join(_nome_casella(c["casella"]) for c in esito)
        if any(c.get("errore") for c in esito):
            return f"Rules on Gmail not finished for {nomi}. {' '.join(c['errore'] for c in esito if c.get('errore'))}"
        creati = sum(c.get("creati", 0) for c in esito)
        tolti = sum(len(c.get("togli_vecchi", [])) + c.get("cancella_nostri", 0) for c in esito)
        return f"Rules pushed to Gmail for {nomi}, {creati} written and {tolti} removed."
    if a == "pulizia":
        n = sum(c.get("modificate", 0) for c in esito)
        nomi = ", ".join(_nome_casella(c["casella"]) for c in esito)
        return f"Cleanup of the mail already in the inbox on {nomi}, {n} emails moved to labels or to Main."
    if a == "annulla":
        return f"Cleanup undone on {_nome_casella(v['casella'])}, {v.get('rimesse', 0)} emails put back as they were."
    return a or ""


def _leggi(c: str):
    try:
        return IZ.leggi_vivo(c)
    except Exception as e:
        return e


def stato() -> dict:
    dato = IZ.carica()
    caselle, da_fare, mute = [], 0, []
    with ThreadPoolExecutor(max_workers=5) as ex:
        vivi = dict(
            zip(dato["caselle"].values(), ex.map(_leggi, dato["caselle"].values()), strict=True)
        )
    for casella in dato["caselle"].values():
        conta = {}
        for e in dato["mittenti"]:
            if e["casella"] == casella:
                conta[e["categoria"]] = conta.get(e["categoria"], 0) + 1
        per_categoria = [
            {"categoria": c[0], "mittenti": conta[c[0]]} for c in CATEGORIE if conta.get(c[0])
        ]
        base = {
            "id": casella,
            "nome": _nome_casella(casella),
            "per_categoria": per_categoria,
            "da_scrivere": 0,
            "da_togliere": 0,
        }
        if isinstance(vivi[casella], Exception):
            mute.append(base["nome"])
            caselle.append(
                {
                    **base,
                    "allineata": False,
                    "frase": "Gmail did not respond for this mailbox. I'll retry at the next read.",
                }
            )
            continue
        filtri, etichette, _ = vivi[casella]
        try:
            p = IZ.piano(dato, casella, filtri, etichette, IZ.gestiti_di(casella))
        except IZ.Fermo as e:
            mute.append(base["nome"])
            caselle.append({**base, "allineata": False, "frase": str(e)})
            continue
        scrivere = len(p["da_creare"])
        togliere = len(p["da_cancellare"]) + len(p["vecchi_da_togliere"])
        da_fare += scrivere + togliere
        guarda = bool(p["bloccati"] or p["cambiati_a_mano"])
        if guarda:
            mute.append(base["nome"])
            frase = "A rule was changed by hand in Gmail. I won't touch it until we look at it together."
        elif scrivere or togliere:
            frase = (
                f"To push to Gmail, {_regole(scrivere)} to write and {togliere} to remove."
            )
        else:
            frase = f"Gmail has exactly these rules, {p['voluti']} in all."
        caselle.append(
            {
                **base,
                "allineata": not (scrivere or togliere or guarda),
                "da_scrivere": scrivere,
                "da_togliere": togliere,
                "frase": frase,
            }
        )
    storia = [
        {"quando": _quando(v.get("quando", "")), "frase": _frase_storia(v)}
        for v in IZ.leggi_storia(8)[::-1]
    ]
    cat_di = {c[0]: c for c in CATEGORIE}
    mittenti = []
    for e in dato["mittenti"]:
        spostabile = not IZ.legate(dato, e["casella"], e["mittente"]) and not (
            e["categoria"] not in IZ.SENZA_REGOLA and not e.get("lista")
        )
        mittenti.append(
            {
                "casella": e["casella"],
                "mittente": e["mittente"],
                "categoria": e["categoria"],
                "mail_90gg": e.get("mail_90gg", 0),
                "spostabile": spostabile,
                "aiuto": _aiuto_mittente(e, cat_di.get(e["categoria"], CATEGORIE[1]), spostabile),
            }
        )
    if mute:
        verdetto = f"To check, {', '.join(mute)}."
        if da_fare:
            verdetto += f" On the other mailboxes there are {_cambi(da_fare)} to push to Gmail."
    elif da_fare:
        verdetto = (
            f"There is {_cambi(da_fare)} to push to Gmail."
            if da_fare == 1
            else f"There are {_cambi(da_fare)} to push to Gmail."
        )
    else:
        verdetto = "The rules on Gmail match the list, on all mailboxes."
    testi = {
        **TESTI,
        "sottotitolo": f"Who stays in Main and who ends up in a label, across your {len(caselle)} mailboxes",
        "conferma": f"{_cambi(da_fare).capitalize()} on the mailboxes. First I save a copy of the current filters.",
        "speciali": (
            f"Besides the senders there are {len(dato['speciali'])} rules on the email subject or on the "
            "domain, such as access codes, certified email (PEC) and closed signatures. The senders that depend on "
            "these rules do not move from here."
        ),
    }
    return {
        "ok": True,
        "verdetto": verdetto,
        "da_fare": da_fare,
        "da_guardare": len(mute),
        "caselle": caselle,
        "categorie": [
            {"id": c[0], "nome": c[1], "simbolo": c[2], "colore": c[3], "aiuto": c[4]}
            for c in CATEGORIE
        ],
        "mittenti": mittenti,
        "storia": storia,
        "testi": testi,
    }


def sposta(casella: str, mittente: str, categoria: str, perche: str) -> dict:
    try:
        out = IZ.sposta(
            casella, mittente, categoria, perche, principale=(categoria == "PRINCIPALE")
        )
    except ValueError as e:
        return {"ok": False, "frase": str(e)}
    return {
        "ok": True,
        "frase": f"{out['mittente']} moves to {_nome_categoria(categoria)}. On Gmail it changes when you push the rules.",
    }


def applica() -> dict:
    try:
        out = IZ.cmd_applica(IZ.carica(), esegui=True)
    except (
        Exception
    ) as e:
        return {
            "ok": False,
            "frase": f"I stopped before finishing ({type(e).__name__}). The mailboxes done stay done, you see them in the latest changes.",
        }
    errori = [
        f"{_nome_casella(c['casella'])}, {c['errore']}" for c in out["caselle"] if c.get("errore")
    ]
    scritte = sum(c.get("creati", 0) for c in out["caselle"])
    tolte = sum(
        len(c.get("togli_vecchi", [])) + c.get("cancella_nostri", 0) for c in out["caselle"]
    )
    frase = f"On Gmail I wrote {_regole(scritte)} and removed {tolte}, after saving the earlier copy."
    if errori:
        return {"ok": False, "frase": frase + " I did not finish on " + " ".join(errori)}
    return {"ok": True, "frase": "Done. " + frase + " They apply to mail arriving from now on."}







VALIDITA_CONTO = 15 * 60


def _own_emails() -> set[str]:
    import sys

    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from sbk_config import OWN_EMAILS

    return {e.lower() for e in OWN_EMAILS}

# Your own mailboxes (sbk.config.json "own_emails"); team domains stay empty here.
MIE: set[str] = _own_emails()
DOMINI_TEAM: tuple[str, ...] = ()
_AUTOMATICO = re.compile(
    r"^(?:no-?reply|do-?not-?reply|notifications?|notify|alerts?|mailer(?:-daemon)?|bounces?|system|automated|"
    r"updates?|news(?:letter)?|marketing|hello|info|team|support|billing|accounts?|security)\b",
    re.I,
)
_RICEVUTA = re.compile(
    r"\b(fattura|invoice|receipt|ricevuta|payment|pagamento|order|ordine|abbonamento|subscription)\b",
    re.I,
)
_EVENTO = re.compile(
    r"\b(webinar|evento|event|invito|invitation|conference|summit|fiera|meetup|workshop|forum|save the date)\b",
    re.I,
)
_COLD = re.compile(
    r"\b(partnership|collaborat\w*|quick question|demo|opportunit\w*|proposal|proposta|leads?|seo|growth|"
    r"outreach|backlinks?|guest post|scale your|book a call|15 min|boost|rankings?|recognition|award)\b",
    re.I,
)

TESTI.update(
    {
        "posta_in_arrivo": "The inbox",
        "aiuto_posta_in_arrivo": "How many emails are in the inbox of each mailbox right now. These numbers tell you how far you are from zero.",
        "rileggi": "Re-read",
        "aiuto_rileggi": "Re-reads the inbox of the mailboxes now.",
        "aiuto_in_arrivo": "Emails in the inbox right now.",
        "aiuto_non_lette": "How many of these you have not opened yet.",
        "aiuto_vecchie": "How many have been there for more than a month.",
        "altre_schede": "{n} in the other tabs",
        "aiuto_altre_schede": "Incoming mail that Gmail put in the Updates, Forums, Social or Promotions tabs. If you use only the Main tab you see them in the same list.",
        "nuovi": "New senders",
        "aiuto_nuovi": "Senders that have mail in the inbox and that the rules list does not know. For each there is a suggestion, you confirm it.",
        "nessun_nuovo": "No new sender in the inbox.",
        "conferma_proposta": "Confirm",
        "aiuto_conferma_proposta": "You put it in the suggested category, with the reason written here. On Gmail it changes when you push the rules.",
        "aiuto_altra_categoria": "You choose another category.",
        "aiuto_mail_in_arrivo": "This sender's emails in the inbox right now.",
        "conto_non_letto": "The inbox was not read. Try again with Re-read.",
    }
)


def _indirizzo(da: str) -> str:
    m = re.search(r"<([^>]+)>", da or "")
    return (m.group(1) if m else (da or "")).strip().lower()


_SICUREZZA = re.compile(
    r"\b(sicurezza|security|password|sospett\w*|suspicious|verifica il tuo account|account (?:bloccato|locked))\b",
    re.I,
)
_AZIONE = re.compile(
    r"\b(unsuccessful|failed|non riuscit\w*|action required|azione richiesta|scadut\w*|overdue|declined)\b",
    re.I,
)
_FINTA_RISPOSTA = re.compile(r"^\s*(?:\[ext\]\s*)?(?:re|r|fwd?)\s*:", re.I)
_DOMINIO_AUTOMATICO = re.compile(
    r"^(?:notifications?|mail|email|em|news|info|updates?|alerts?)\.", re.I
)


def proposta(indirizzo: str, oggetto: str, lista: bool, scritto_da_owner: bool) -> tuple[str, str]:
    ""


    locale, _, dominio = indirizzo.partition("@")
    if scritto_da_owner:
        return "PRINCIPALE", "You wrote to them, so it stays visible."
    if dominio.endswith(DOMINI_TEAM):
        return "PRINCIPALE", "Writes from a domain of your team."
    if _SICUREZZA.search(oggetto):
        return "PRINCIPALE", "It's a security alert, it stays visible."
    if _AZIONE.search(oggetto):
        return (
            "PRINCIPALE",
            "Asks you to do something, for example a failed payment. It stays visible.",
        )
    if _FINTA_RISPOSTA.match(oggetto):
        return "@Cold", "The subject fakes a reply, but you never wrote to them."
    if _COLD.search(oggetto):
        return "@Cold", "You never wrote to them and the subject looks like a sales pitch."
    if _RICEVUTA.search(oggetto):
        return "@Ricevute", "The subject mentions an invoice, a payment or an order."
    if _EVENTO.search(oggetto):
        return "@Eventi", "The subject mentions an event or an invitation."
    if lista:
        return "@Newsletter", "The email has an unsubscribe link, it's a mailing list."
    if _AUTOMATICO.match(locale) or _DOMINIO_AUTOMATICO.match(dominio):
        return "@Notifiche", "Writes from an automated address."
    return (
        "PRINCIPALE",
        "Looks like a person and nothing puts it elsewhere. It stays visible until you decide.",
    )


def _servizio(casella: str):
    ""
    # Your own Gmail login, saved by tools/email/em-l0-auth.py <label> (label from
    # <data root>/emails/accounts.json, refresh token from the Keychain "sbk-gmail").
    import sys

    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import google_oauth

    try:
        return google_oauth.gmail_service(casella)
    except SystemExit as e:
        raise RuntimeError(str(e)) from None


_INTESTAZIONI = ["From", "Subject", "List-Unsubscribe", "List-Id"]


def _intestazioni(svc, ids: list[str]) -> list[dict]:
    ""
    msg = svc.users().messages()
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        pezzo = ids[i : i + 50]
        pacco: dict[str, dict] = {}

        def presa(rid, risposta, errore, pacco=pacco):
            if errore is None:
                pacco[rid] = risposta

        b = svc.new_batch_http_request(callback=presa)
        for x in pezzo:
            b.add(
                msg.get(userId="me", id=x, format="metadata", metadataHeaders=_INTESTAZIONI),
                request_id=x,
            )
        IZ.riprova(b)
        for x in pezzo:
            if x not in pacco:
                pacco[x] = IZ.riprova(
                    msg.get(userId="me", id=x, format="metadata", metadataHeaders=_INTESTAZIONI)
                )
        out += [pacco[x] for x in pezzo]
    return out


def leggi_casella(
    casella: str, conosciuti: dict[str, str], ora: float | None = None, svc=None
) -> dict:
    ""
    svc = svc or _servizio(casella)
    msg = svc.users().messages()
    righe = _intestazioni(svc, IZ.cerca_ids(msg, "in:inbox"))
    ora = ora or datetime.now().timestamp()
    conto = {
        "in_arrivo": len(righe),
        "non_lette": 0,
        "altre_schede": 0,
        "oltre_un_mese": 0,
        "da_decidere": 0,
    }
    nuovi: dict[str, dict] = {}
    for r in righe:
        et = r.get("labelIds", [])
        h = {x["name"].lower(): x["value"] for x in r.get("payload", {}).get("headers", [])}
        quando = int(r.get("internalDate", 0))
        conto["non_lette"] += "UNREAD" in et
        conto["altre_schede"] += any(x in et for x in IZ.SCHEDE)
        conto["oltre_un_mese"] += ora - quando / 1000 > 30 * 86400
        da = _indirizzo(h.get("from", ""))
        if not da or da in MIE or da == casella.lower():
            continue
        cat = conosciuti.get(da)
        if cat == "DA DECIDERE":
            conto["da_decidere"] += 1
        if cat is None:
            v = nuovi.setdefault(da, {"mail": 0, "oggetto": "", "data": 0, "lista": False})
            v["mail"] += 1
            v["lista"] = v["lista"] or bool(h.get("list-unsubscribe") or h.get("list-id"))
            if quando > v["data"]:
                v["data"], v["oggetto"] = quando, h.get("subject", "")
    for da, v in nuovi.items():
        v["scritto_da_owner"] = bool(
            IZ.riprova(msg.list(userId="me", q=f"in:sent to:{da}", maxResults=1)).get("messages")
        )
    return {"casella": casella, "conto": conto, "nuovi": nuovi}


def _file_conto():
    return IZ.DIR / "conto-posta.json"


def _leggi_o_errore(casella: str, conosciuti: dict[str, str]):
    try:
        return leggi_casella(casella, conosciuti)
    except Exception as e:
        return {"casella": casella, "errore": type(e).__name__}


def leggi_conto() -> dict:
    dato = IZ.carica()
    caselle = list(dato["caselle"].values())
    conosciuti = {c: {} for c in caselle}
    for e in dato["mittenti"]:
        conosciuti.setdefault(e["casella"], {})[e["mittente"]] = e["categoria"]
    with ThreadPoolExecutor(max_workers=5) as ex:
        letture = list(ex.map(lambda c: _leggi_o_errore(c, conosciuti[c]), caselle))
    return {"letto": datetime.now().isoformat(timespec="seconds"), "caselle": letture}


def _frase_casella(c: dict) -> str:
    n = c["in_arrivo"]
    if n == 0:
        return "Inbox at zero."
    parti = [f"{c['non_lette']} unread" if c["non_lette"] != 1 else "1 unread"]
    if c["oltre_un_mese"]:
        parti.append(f"{c['oltre_un_mese']} older than a month")
    if c["da_decidere"]:
        parti.append(f"{c['da_decidere']} from senders to decide")
    return ", ".join(parti).capitalize() + "."


def componi_conto(grezzo: dict, dato: dict) -> dict:
    caselle, nuovi = [], []
    for c in grezzo["caselle"]:
        nome = _nome_casella(c["casella"])
        if "errore" in c:
            caselle.append(
                {
                    "id": c["casella"],
                    "nome": nome,
                    "letta": False,
                    "in_arrivo": 0,
                    "non_lette": 0,
                    "oltre_un_mese": 0,
                    "altre_schede": 0,
                    "frase": "Gmail did not respond for this mailbox.",
                }
            )
            continue
        caselle.append(
            {
                "id": c["casella"],
                "nome": nome,
                "letta": True,
                **{
                    k: c["conto"][k]
                    for k in ("in_arrivo", "non_lette", "oltre_un_mese", "altre_schede")
                },
                "frase": _frase_casella(c["conto"]),
            }
        )
        for da, v in c["nuovi"].items():
            cat, perche = proposta(da, v["oggetto"], v["lista"], v.get("scritto_da_owner", False))
            nuovi.append(
                {
                    "casella": c["casella"],
                    "mittente": da,
                    "mail": v["mail"],
                    "oggetto": re.sub(r"^\s*\[ext\]\s*", "", v["oggetto"], flags=re.I),
                    "proposta": cat,
                    "perche": perche,
                    "data": v["data"],
                }
            )
    nuovi.sort(key=lambda x: (-x["mail"], -x["data"]))
    totale = sum(c["in_arrivo"] for c in caselle)
    letto = datetime.fromisoformat(grezzo["letto"])
    giorno = (
        "today"
        if letto.date() == datetime.now().date()
        else _quando(grezzo["letto"]).split(" at")[0]
    )
    return {
        "ok": True,
        "totale": totale,
        "frase": (
            "Inbox at zero on all mailboxes."
            if totale == 0
            else f"{totale} emails in the inbox of the {len(caselle)} mailboxes."
        ),
        "letto": f"Read {giorno} at {letto:%H:%M}.",
        "caselle": caselle,
        "nuovi": nuovi,
    }


def conto(rileggi: bool = False) -> dict:
    ""
    grezzo = None
    p = _file_conto()
    if not rileggi and p.exists():
        try:
            g = json.loads(p.read_text())
            if (
                datetime.now().timestamp() - datetime.fromisoformat(g["letto"]).timestamp()
                < VALIDITA_CONTO
            ):
                grezzo = g
        except (json.JSONDecodeError, KeyError, ValueError):
            grezzo = None
    if grezzo is None:
        grezzo = leggi_conto()
        IZ._scrivi_atomico(p, json.dumps(grezzo, ensure_ascii=False))
    return componi_conto(grezzo, IZ.carica())


def conferma_nuovo(casella: str, mittente: str, categoria: str, perche: str) -> dict:
    ""

    out = sposta(casella, mittente, categoria, perche)
    if out["ok"] and _file_conto().exists():
        try:
            g = json.loads(_file_conto().read_text())
            for c in g["caselle"]:
                if c["casella"] == casella and "nuovi" in c:
                    c["nuovi"].pop(mittente.lower().strip(), None)
            IZ._scrivi_atomico(_file_conto(), json.dumps(g, ensure_ascii=False))
        except (json.JSONDecodeError, KeyError):
            _file_conto().unlink(missing_ok=True)
    return out
