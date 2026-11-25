#!/usr/bin/env python3
""




















from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sbk_config import OWN_EMAILS  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "em_util_inbox_zero", _TOOLS / "email" / "em-util-inbox-zero.py"
)
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


QUERY_FIRME = (
    "from:(docusign.net OR hellosign.com OR dropboxsign.com OR adobesign.com OR echosign.com OR kopjra.com OR "
    "yousign.com OR yousign.app)"
)
GIORNI_GMAIL = 90
_CHIUSA = re.compile(
    r"^(completed|completata|completato|voided|annullat[ao]|declined|rifiutat[ao]|everyone has signed|"
    r"you just signed|.*\bhas been completed|.*\bis complete)",
    re.I,
)

_TESTA = re.compile(
    r"^(?:\s*(?:\[ext\]|reminder|promemoria|re|fwd?|please docusign|complete with docusign|completa con docusign|"
    r"completed|completata|completato|voided|annullat[ao]|declined|rifiutat[ao]|signature requested|firma richiesta|"
    r"everyone has signed|you just signed)\s*[:\-]?\s*)+",
    re.I,
)

_NON_CONTRATTO = re.compile(
    r"verify a new device|verify your identity|your docusign account|codice|code\b|password", re.I
)
# Your own addresses, from sbk.config.json "own_emails".
MIE = {e.lower() for e in OWN_EMAILS}
VALIDITA = timedelta(minutes=10)


TESTI = {
    "titolo": "To sign",
    "sottotitolo": "The contracts waiting for your signature, even if you archived the email",
    "tocca_a_te": "Your turn",
    "aiuto_tocca_a_te": "Contracts where your signature is next. They stay here until you sign or remove them.",
    "da_altri_account": "Started from other accounts",
    "aiuto_da_altri_account": (
        "Signature requests arrived by email from DocuSign accounts other than your DocuSign account, or from other signing "
        "services. They stay here until the email saying the document is closed arrives."
    ),
    "dopo_gli_altri": "They'll come to you",
    "aiuto_dopo_gli_altri": "Contracts you sign, but other people must sign first. There's nothing to do now.",
    "esclusi": "That you decided not to sign",
    "aiuto_esclusi": "You removed them from the list, with the reason. A new envelope for the same contract returns to the list on its own.",
    "apri": "Open the email",
    "aiuto_apri": "Opens the conversation in Gmail, in the browser. Inside is the DocuSign button to sign.",
    "senza_mail": "The email isn't found in the mailboxes.",
    "non_firmo": "I won't sign it",
    "aiuto_non_firmo": "You remove it from the list. I ask you the reason, it stays written.",
    "rimetti": "Put back in the list",
    "aiuto_rimetti": "Returns among the contracts to sign.",
    "foglio_titolo": "I won't sign",
    "foglio_perche": "Reason",
    "foglio_nota": "The contract leaves the list. Nothing changes on DocuSign, whoever sent it receives no notice.",
    "foglio_annulla": "Cancel",
    "foglio_conferma": "Remove from the list",
    "rileggi": "Re-read",
    "aiuto_rileggi": "Re-reads DocuSign and the mail now.",
    "nessuno": "No contract is waiting for your signature.",
    "aiuto_promemoria": "How many emails arrived for this contract, reminders included.",
}





def _giorno(d: datetime) -> str:
    oggi = datetime.now().astimezone().date()
    g = d.astimezone().date()
    if g == oggi:
        return "today"
    if g == oggi - timedelta(days=1):
        return "yesterday"
    return f"{MESI[g.month - 1]} {g.day}"


def _da_quando(d: datetime) -> str:
    giorni = (datetime.now().astimezone().date() - d.astimezone().date()).days
    if giorni <= 0:
        return "Arrived today."
    if giorni == 1:
        return "Arrived yesterday."
    return f"Waiting since {MESI[d.astimezone().month - 1]} {d.astimezone().day}, {giorni} days."



_CODA = re.compile(
    r"\s*(?:-\s*signature requested by .*|is awaiting your signature|has been signed.*|è in attesa della tua firma)$",
    re.I,
)


def _tempo(d: datetime | None, tipo: str) -> str:
    if not d:
        return ""
    return f"Sent {_giorno(d)}." if tipo == "dopo" else _da_quando(d)


def chiave(oggetto: str) -> str:
    ""
    return re.sub(r"\s+", " ", _CODA.sub("", _TESTA.sub("", oggetto or ""))).strip().lower()


def _titolo(oggetto: str) -> str:
    t = _CODA.sub("", _TESTA.sub("", oggetto or "")).strip()
    t = re.sub(r"\.(pdf|docx?)$", "", t, flags=re.I)
    t = re.sub(r"(\s*\(\d\))+$", "", t)
    return t.replace("_", " ").strip() or (oggetto or "")


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None





def _file_esclusi() -> Path:
    return IZ.DIR / "firme-escluse.json"


def esclusi() -> list[dict]:
    p = _file_esclusi()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return []


def escludi(busta: str, titolo: str, perche: str) -> dict:
    if not perche.strip():
        return {"ok": False, "frase": "The reason is required."}
    with IZ.lucchetto():
        voci = [v for v in esclusi() if v["busta"] != busta]
        voci.append(
            {
                "busta": busta,
                "titolo": titolo,
                "perche": perche.strip(),
                "quando": datetime.now().isoformat(timespec="seconds"),
            }
        )
        IZ._scrivi_atomico(_file_esclusi(), json.dumps(voci, indent=1, ensure_ascii=False))
        IZ.scrivi_storia(
            {"azione": "firme-escludi", "busta": busta, "titolo": titolo, "perche": perche}
        )
    _cache().unlink(missing_ok=True)
    return {"ok": True, "frase": f"{titolo} leaves the list."}


def riammetti(busta: str) -> dict:
    with IZ.lucchetto():
        prima = esclusi()
        voci = [v for v in prima if v["busta"] != busta]
        if len(voci) == len(prima):
            return {"ok": False, "frase": "This contract wasn't among the removed ones."}
        IZ._scrivi_atomico(_file_esclusi(), json.dumps(voci, indent=1, ensure_ascii=False))
        IZ.scrivi_storia({"azione": "firme-riammetti", "busta": busta})
    _cache().unlink(missing_ok=True)
    return {"ok": True, "frase": "The contract is back in the list."}





def _docusign_modulo():
    spec = importlib.util.spec_from_file_location("ds_l0_api", _TOOLS / "docusign" / "ds-l0-api.py")
    ds = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ds)
    return ds


def buste_docusign(dal: str) -> list[dict]:
    ""
    ds = _docusign_modulo()
    ik = ds._cred("integration-key", "DOCUSIGN_INTEGRATION_KEY")
    uid = ds._cred("user-id", "DOCUSIGN_USER_ID")
    tok = ds.access_token(ik, uid)
    acct, base = ds.account_di(
        ds.userinfo(tok),
        os.environ.get("DOCUSIGN_ACCOUNT_ID") or ds.get_secret(ds.SERVICE, "account-id"),
    )
    return ds.elenca_buste(tok, base, acct, dal)


def dalle_buste(buste: list[dict]) -> list[dict]:
    ""
    out = []
    for e in buste:
        if e.get("status") not in ("sent", "delivered"):
            continue
        tutti = [
            r
            for lista in (e.get("recipients") or {}).values()
            if isinstance(lista, list)
            for r in lista
        ]
        miei = [r for r in tutti if (r.get("email") or "").lower() in MIE]
        if not miei:
            continue
        mio = min(miei, key=lambda r: int(r.get("routingOrder") or 0))
        if mio.get("status") in ("completed", "signed", "declined"):
            continue
        prima_di_me = [
            r.get("name") or ""
            for r in tutti
            if (r.get("email") or "").lower() not in MIE
            and int(r.get("routingOrder") or 0) < int(mio.get("routingOrder") or 0)
            and r.get("status") not in ("completed", "signed")
        ]
        out.append(
            {
                "busta": e.get("envelopeId"),
                "oggetto": e.get("emailSubject") or "",
                "da": (e.get("sender") or {}).get("userName") or "",
                "inviata": e.get("sentDateTime") or e.get("createdDateTime"),
                "tocca_a_te": mio.get("status") in ("sent", "delivered"),
                "aperta": mio.get("status") == "delivered",
                "prima_di_te": prima_di_me,
            }
        )
    return out





def mail_firme(casella: str, giorni: int = GIORNI_GMAIL) -> list[dict]:
    m = IZ.gmail(casella, "gmail.readonly").messages()
    out = []
    for i in IZ.cerca_ids(m, f"{QUERY_FIRME} newer_than:{giorni}d"):
        r = IZ.riprova(
            m.get(userId="me", id=i, format="metadata", metadataHeaders=["From", "Subject"])
        )
        h = {x["name"]: x["value"] for x in r["payload"].get("headers", [])}
        out.append(
            {
                "casella": casella,
                "id": i,
                "thread": r["threadId"],
                "data": int(r["internalDate"]) // 1000,
                "da": h.get("From", ""),
                "oggetto": h.get("Subject", ""),
                "etichette": r.get("labelIds", []),
            }
        )
    return out


def per_documento(mail: list[dict]) -> dict[str, dict]:
    ""
    gruppi: dict[str, list[dict]] = {}
    for x in mail:
        if _NON_CONTRATTO.search(x["oggetto"]):
            continue
        gruppi.setdefault(chiave(x["oggetto"]), []).append(x)
    out = {}
    for k, xs in gruppi.items():
        xs.sort(key=lambda x: x["data"])
        oggetti = [re.sub(r"^\s*\[ext\]\s*", "", x["oggetto"], flags=re.I) for x in xs]
        out[k] = {
            "mail": len(xs),
            "prima": xs[0],
            "ultima": xs[-1],
            "chiusa": any(_CHIUSA.match(o) for o in oggetti),
        }
    return out


def _link(casella: str, thread: str) -> str:
    return f"https://mail.google.com/mail/u/?authuser={casella}#all/{thread}"


def _mittente_leggibile(da: str) -> str:
    nome = re.sub(r"\s*<[^>]*>\s*$", "", da).strip().strip('"')
    return re.sub(r"\s+via\s+\w+$", "", nome, flags=re.I).strip()





def _cache() -> Path:
    return IZ.DIR / "firme-cache.json"


def leggi(ora: datetime | None = None) -> dict:
    ""
    ora = ora or datetime.now(UTC)
    dal = (ora - timedelta(days=200)).strftime("%Y-%m-%d")
    caselle = list(IZ.carica()["caselle"].values())
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_ds = ex.submit(buste_docusign, dal)
        f_mail = {c: ex.submit(mail_firme, c) for c in caselle}
        errori = []
        try:
            buste = f_ds.result()
        except Exception as e:
            buste, errori = None, [f"DocuSign didn't respond ({type(e).__name__})."]
        mail = []
        for c, f in f_mail.items():
            try:
                mail += f.result()
            except Exception:
                errori.append(f"The mail of {c} couldn't be read.")
    return {
        "letto": ora.isoformat(timespec="seconds"),
        "buste": None if buste is None else dalle_buste(buste),

        "chiavi_docusign": None
        if buste is None
        else sorted({chiave(e.get("emailSubject") or "") for e in buste}),
        "mail": mail,
        "errori": errori,
    }


def stato(rileggi: bool = False) -> dict:
    grezzo = None
    if not rileggi and _cache().exists():
        try:
            g = json.loads(_cache().read_text())
            if datetime.now(UTC) - datetime.fromisoformat(g["letto"]) < VALIDITA:
                grezzo = g
        except (json.JSONDecodeError, KeyError, ValueError):
            grezzo = None
    if grezzo is None:
        grezzo = leggi()
        IZ._scrivi_atomico(_cache(), json.dumps(grezzo, ensure_ascii=False))
    return componi(grezzo, esclusi())


def componi(grezzo: dict, tolti: list[dict]) -> dict:
    ""
    docs = per_documento(grezzo["mail"])
    id_tolti = {v["busta"] for v in tolti}
    voci, dopo = [], []
    chiavi_docusign = set(grezzo.get("chiavi_docusign") or [])

    def scheda(busta, oggetto, da, quando, mail_doc, frase_stato, tipo):
        d = _iso(quando) if isinstance(quando, str) else quando
        ultima = mail_doc["ultima"] if mail_doc else None
        return {
            "id": busta,
            "titolo": _titolo(oggetto),
            "da": da,
            "tipo": tipo,
            "quando": _giorno(d) if d else "",
            "frase": " ".join(x for x in (frase_stato, _tempo(d, tipo)) if x),
            "mail": mail_doc["mail"] if mail_doc else 0,
            "link": _link(ultima["casella"], ultima["thread"]) if ultima else None,
            "ordine": d.timestamp() if d else 0,
        }

    for b in grezzo["buste"] or []:
        k = chiave(b["oggetto"])
        if b["busta"] in id_tolti:
            continue
        doc = docs.get(k)
        if b["tocca_a_te"]:
            frase = "You opened it but didn't sign." if b["aperta"] else "You haven't opened it yet."
            voci.append(
                scheda(b["busta"], b["oggetto"], b["da"], b["inviata"], doc, frase, "docusign")
            )
        else:
            chi = ", ".join(n for n in b["prima_di_te"] if n) or "other people"
            dopo.append(
                scheda(
                    b["busta"],
                    b["oggetto"],
                    b["da"],
                    b["inviata"],
                    doc,
                    f"{chi} signs first.",
                    "dopo",
                )
            )

    altri = []
    for k, doc in docs.items():

        if doc["chiusa"] or k in chiavi_docusign:
            continue
        busta = "mail-" + doc["prima"]["thread"]
        if busta in id_tolti:
            continue
        quando = datetime.fromtimestamp(doc["prima"]["data"], UTC)
        altri.append(
            scheda(
                busta,
                doc["prima"]["oggetto"],
                _mittente_leggibile(doc["prima"]["da"]),
                quando,
                doc,
                "No closing email.",
                "mail",
            )
        )

    for lista in (voci, altri, dopo):
        lista.sort(key=lambda v: v["ordine"])
    n = len(voci) + len(altri)
    if grezzo["buste"] is None:
        verdetto = "DocuSign didn't respond. You only see the requests found in the mail."
    elif n == 0:
        verdetto = TESTI["nessuno"]
    elif n == 1:
        verdetto = "One contract is waiting for your signature."
    else:
        verdetto = f"{n} contracts are waiting for your signature."
    letto = _iso(grezzo["letto"])
    return {
        "ok": True,
        "verdetto": verdetto,
        "da_firmare": n,
        "letto": f"Read {_giorno(letto)} at {letto.astimezone():%H:%M}." if letto else "",
        "tocca_a_te": voci,
        "da_altri_account": altri,
        "dopo_gli_altri": dopo,
        "esclusi": [
            {
                "id": v["busta"],
                "titolo": v["titolo"],
                "frase": f"Removed {_giorno(_iso(v['quando']))}. {v['perche'].rstrip('.')}.",
            }
            for v in tolti
            if _iso(v.get("quando"))
        ],
        "errori": grezzo.get("errori", []),
        "testi": TESTI,
    }


if __name__ == "__main__":
    print(json.dumps(stato(rileggi="--rileggi" in sys.argv), ensure_ascii=False, indent=1))
