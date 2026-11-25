""




















from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from email.utils import getaddresses, parseaddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sbk_config import DATA_ROOT, ENRICHED_DIR, WHATSAPP_DIR  # noqa: E402

TABELLA_POSTA = ENRICHED_DIR / "mittenti-posta.parquet"

TABELLA_GRUPPI = WHATSAPP_DIR / "gruppi.parquet"


CORREZIONI = DATA_ROOT / "system" / "rumore-correzioni.json"


TIPI_RUMORE = frozenset(
    {"notifica-servizio", "newsletter-commerciale", "social", "liste-forum", "interno-automatico"}
)

TIPI_DUBBI = frozenset({"a-freddo", "in-copia", "collega-di-un-rapporto"})
TIPI_RAPPORTO = frozenset({"rapporto", "rapporto-altra-fonte", "rapporto-nel-thread", "interno"})




def addr_of(raw: str | None) -> str:
    ""
    if not raw:
        return ""
    a = parseaddr(str(raw))[1].strip().lower()
    return a if "@" in a else ""


def addrs_of(raw: str | None) -> list[str]:
    ""
    if not raw:
        return []
    out = []
    for _n, a in getaddresses([str(raw)]):
        a = a.strip().lower()
        if "@" in a:
            out.append(a)
    return out


_SLD2 = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.jp", "com.br", "com.mx", "co.za",
    "com.tr", "co.in", "com.sg", "com.hk", "co.kr", "com.cn", "com.ar", "co.nz", "com.es", "com.pt", "co.il",
    "com.my", "com.ph", "co.th", "com.vn", "com.co", "com.pe", "com.ua", "com.pl", "co.id", "com.ng", "com.eg",
}


def org_domain(domain: str) -> str:
    ""
    d = (domain or "").strip().lower().rstrip(".")
    parts = d.split(".")
    if len(parts) <= 2:
        return d
    if ".".join(parts[-2:]) in _SLD2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


GENERIC_PROVIDERS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.fr", "yahoo.es", "ymail.com",
    "hotmail.com", "hotmail.co.uk", "hotmail.fr", "hotmail.es", "outlook.com", "live.com",
    "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me", "pm.me", "gmx.com",
    "gmx.de", "gmx.net", "web.de", "mail.ru", "yandex.ru", "yandex.com", "qq.com", "163.com", "126.com",
})




UNSUB_RE = re.compile(
    r"unsubscrib|opt[\s-]?out\b|manage (your )?(e-?mail |subscription |notification )?(preferences|settings|subscriptions?)"
    r"|update your (e-?mail )?preferences|you (are )?receiv(e|ed|ing) this (e-?mail|message|newsletter|because)"
    r"|view (this e-?mail |it )?in (your |a )?(web )?browser|no longer wish to receive|stop receiving"
    r"|disiscriv|cancella(re|ti)?( la tua| l')? ?iscrizione|annulla(re)?( la tua| l')? ?iscrizione"
    r"|non (vuoi|desideri) pi[uù] ricevere|gestisci (le tue )?preferenze|ricevi questa (e-?mail|comunicazione)"
    r"|visualizza(la)? (nel|sul|in) (tuo )?(browser|web)|se non vuoi pi[uù] ricevere"
    r"|darse de baja|darte de baja|cancelar (la |tu )?suscripci|anular (la )?suscripci"
    r"|d[ée]sabonner|d[ée]sinscri|abmelden|abbestellen|afmelden|uitschrijven|descadastr",
    re.IGNORECASE,
)


NOREPLY_LOCAL_RE = re.compile(
    r"(^|[._+-])(no[._-]?reply|noreply|do[._-]?not[._-]?reply|donotreply|dont[._-]?reply)([._+-]|$)"
    r"|^(notifications?|notify|notifier|alerts?|alerting|mailer[._-]?daemon|postmaster|bounces?|bounce[._+-].*"
    r"|news|newsletters?|marketing|promo(tions?)?|offers?|deals|digest|updates?|automated|automailer|system"
    r"|robot|bot|messages[._-]noreply|calendar[._-]notification|drive[._-]shares[._-].*|comments[._-]noreply"
    r"|invitations?|reminders?|reply|replies|feedback|survey|surveys|events?|webinars?|community|members?)$",
    re.IGNORECASE,
)


ESP_MARKERS = (
    "mailchimp", "mcsv.net", "mcdlv.net", "list-manage", "sendgrid", "hubspotemail", "hs-email", "hubspotstarter",
    "mktomail", "marketo", "mailgun", "amazonses", "sparkpost", "mandrillapp", "createsend", "cmail", "exacttarget",
    "klaviyo", "sendinblue", "brevo", "mailjet", "mailerlite", "substack", "beehiiv", "convertkit", "activehosted",
    "getresponse", "aweber", "constantcontact", "campaign-archive", "lemlist", "instantly", "smartlead", "woodpecker",
    "mailshake", "salesloft", "outreach.io", "apollo.io", "heyapollo", "customer.io", "intercom-mail",
)


MKT_SUBDOMAIN = frozenset({
    "e", "em", "email", "emails", "mail", "mails", "mailer", "mailing", "news", "newsletter", "newsletters", "info",
    "marketing", "mkt", "go", "hello", "send", "notify", "notification", "notifications", "updates", "alerts",
    "comms", "engage", "t", "m", "mg", "sg", "crm", "offers", "promo", "promos", "eu", "us", "mail2", "edm", "e2",
    "reply", "mta", "bounce", "communication", "communications", "contact", "connect", "learn", "events", "service",
})


TICKET_SYSTEMS = (
    "zendesk.com", "freshdesk.com", "helpscout.net", "intercom-mail.com", "intercom.io", "frontapp.com", "gorgias.com",
    "zohodesk.com", "kayako.com", "servicenow.com", "desk.com", "tawk.to", "crisp.chat", "livechatinc.com",
    "docusign.net", "docusign.com", "echosign.com", "adobesign.com", "pandadoc.net", "hellosign.com", "yousign.com",
)


RUOLO_LOCAL = frozenset({
    "info", "support", "help", "hello", "team", "billing", "invoice",
    "invoices", "accounts", "accounting", "admin", "administration",
    "sales", "marketing", "hr", "jobs", "careers", "recruiting", "office", "contact",
    "service", "customerservice", "customer.service", "care", "orders", "shop",
    "store", "booking", "reservations", "press", "media", "legal", "privacy", "security", "finance",
    "partners", "partnership", "events", "noreply", "staff", "general", "enquiries", "inquiries",
})

CATEGORIE = (
    "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
    "CATEGORY_PERSONAL",
)


def tipo_local(addr: str) -> str:
    ""
    local = addr.partition("@")[0]
    if NOREPLY_LOCAL_RE.search(local) or "noreply" in local or "no-reply" in local:
        return "noreply"
    base = re.split(r"[+]", local)[0]
    if (
        base in RUOLO_LOCAL
        or base.split(".")[0] in RUOLO_LOCAL
        or base.split("-")[0] in RUOLO_LOCAL
    ):
        return "ruolo"
    if re.fullmatch(r"[a-z]{2,}[._-][a-z]{2,}([._-][a-z]{2,})?\d{0,2}", base):
        return "persona"
    return "altro"


def categoria(labels: str | None) -> str:
    ""
    if not isinstance(labels, str):
        return "NONE"
    ls = set(labels.split(","))
    for c in CATEGORIE:
        if c in ls:
            return c.removeprefix("CATEGORY_")
    return "NONE"


def segnali_mittente(addr: str) -> dict:
    ""
    local, _, dom = addr.partition("@")
    first = dom.split(".")[0] if dom.count(".") >= 2 else ""
    return {
        "noreply": bool(NOREPLY_LOCAL_RE.search(local))
        or "noreply" in local
        or "no-reply" in local,
        "esp": any(m in dom for m in ESP_MARKERS),
        "mkt_sub": first in MKT_SUBDOMAIN,
        "lungo": len(local) > 40 or ("=" in local and "." in local.split("=", 1)[1]),
    }


def di_massa(labels: str | None, body: str | None, list_unsubscribe: str | None = None) -> bool:
    ""

    if isinstance(list_unsubscribe, str) and list_unsubscribe:
        return True
    if categoria(labels) in ("PROMOTIONS", "SOCIAL", "FORUMS"):
        return True
    if not isinstance(body, str) or not body:
        return False
    s = body if len(body) <= 9000 else body[:3000] + body[-6000:]
    return bool(UNSUB_RE.search(s))


def classifica(r: dict, interni: set, sistemi=TICKET_SYSTEMS) -> str:
    ""




    dom, org = r["dominio"], r["org"]
    if dom in interni or org in interni:
        return (
            "interno-automatico"
            if r["local_tipo"] in ("noreply", "ruolo") or r["lungo"]
            else "interno"
        )
    if any(dom == s or dom.endswith("." + s) for s in sistemi):

        return "notifica-servizio"
    if r["owner_scrive_indirizzo"] > 0:

        massa = (
            (r["q_promo"] + r["q_updates"] + r["q_social"] + r["q_forums"]) >= 0.8
            or r["noreply"]
            or r["esp"]
        )
        if not (massa and r["owner_scrive_indirizzo"] <= 2):
            return "rapporto"
    if r["generico"] and r["q_unsub"] < 0.5 and not (r["noreply"] or r["esp"] or r["lungo"]):


        if r.get("altrove"):
            return "rapporto-altra-fonte"
        if r["thread_risposti"] > 0:
            return "rapporto-nel-thread"
        return "in-copia" if r["a_owner_diretto"] == 0 else "a-freddo"
    if r["q_social"] >= 0.5:
        return "social"
    if r["q_promo"] >= 0.5 or (r["q_unsub"] >= 0.5 and r["q_updates"] < 0.5) or r["esp"]:
        return "newsletter-commerciale"
    if r["q_updates"] >= 0.5 or r["noreply"] or r["lungo"]:
        return "notifica-servizio"
    if r["q_forums"] >= 0.5:
        return "liste-forum"
    if r["q_unsub"] >= 0.5 or r["mkt_sub"]:
        return "newsletter-commerciale"
    if r["n"] >= 20 and r["thread_risposti"] == 0 and not r.get("altrove"):
        return "notifica-servizio"
    if r.get("altrove"):



        return "rapporto-altra-fonte"
    if r["thread_risposti"] > 0:
        return "rapporto-nel-thread"
    if not r["generico"] and r["owner_scrive_org"] > 0:
        return "collega-di-un-rapporto"
    if r["a_owner_diretto"] == 0:
        return "in-copia"
    return "a-freddo"





def altrove_da_merge(percorso: Path | None = None) -> set[str]:
    ""
    import pandas as pd

    percorso = percorso or (ENRICHED_DIR / "contacts-merged.parquet")
    colonne = [
        "all_emails",
        "cal_events",
        "has_personio",
        "has_slack",
        "has_tactiq",
        "has_docusign",
    ]
    try:
        cm = pd.read_parquet(percorso, columns=colonne)
    except (OSError, ValueError, KeyError):
        return set()
    fuori: set[str] = set()
    for ems, cal, pe, sl, tq, ds in cm.itertuples(index=False, name=None):
        if not ((cal or 0) > 0 or pe or sl or tq or ds):
            continue
        if isinstance(ems, str):
            try:
                ems = json.loads(ems) if ems.startswith("[") else ems.split(",")
            except ValueError:
                ems = ems.split(",")
        for em in list(ems if ems is not None else []):
            em = (em or "").strip().lower()
            if "@" in em:
                fuori.add(em)
    return fuori


def correzioni() -> dict:
    ""
    try:
        d = json.loads(CORREZIONI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def tabella_mittenti(
    msgs,
    own: set[str],
    interni: set[str],
    altrove: set[str] | None = None,
    corrette: dict[str, str] | None = None,
):
    ""

    import pandas as pd

    own = {e.lower() for e in own}
    interni = {d.lower() for d in interni}
    altrove = altrove or set()
    corrette = {k.lower(): v for k, v in (corrette or {}).items()}

    def col(nome):
        return (
            msgs[nome] if nome in msgs.columns else pd.Series([None] * len(msgs), index=msgs.index)
        )

    account = col("account").fillna("")
    thread = col("thread_id").fillna("")
    da = col("from_addr")


    owner_a: Counter = Counter()
    owner_org: Counter = Counter()
    owner_thread: set = set()
    for fa, ta, cc, bc, acc, th in zip(
        da, col("to_addr"), col("cc"), col("bcc"), account, thread, strict=True
    ):
        if addr_of(fa) not in own:
            continue
        owner_thread.add((acc, th))
        for a in addrs_of(ta) + addrs_of(cc) + addrs_of(bc):
            if a in own:
                continue
            owner_a[a] += 1
            dom = a.split("@")[1]
            if dom not in GENERIC_PROVIDERS:
                owner_org[org_domain(dom)] += 1


    agg: dict[str, dict] = defaultdict(
        lambda: {
            "n": 0,
            "cat": Counter(),
            "unsub": 0,
            "a_owner": 0,
            "risposti": set(),
            "ultimo": None,
        }
    )
    for fa, ta, lab, body, lu, acc, th, dt in zip(
        da,
        col("to_addr"),
        col("labels"),
        col("body_text"),
        col("list_unsubscribe"),
        account,
        thread,
        col("date"),
        strict=True,
    ):
        a = addr_of(fa)
        if not a or a in own:
            continue
        r = agg[a]
        r["n"] += 1
        r["cat"][categoria(lab)] += 1

        if isinstance(lu, str) and lu:
            r["unsub"] += 1
        elif isinstance(body, str) and body:
            s = body if len(body) <= 9000 else body[:3000] + body[-6000:]
            r["unsub"] += bool(UNSUB_RE.search(s))
        if any(x in own for x in addrs_of(ta)):
            r["a_owner"] += 1
        if (acc, th) in owner_thread:
            r["risposti"].add((acc, th))
        if dt is not None and not pd.isna(dt) and (r["ultimo"] is None or dt > r["ultimo"]):
            r["ultimo"] = dt

    righe = []
    for a, r in agg.items():
        dom = a.partition("@")[2]
        org = org_domain(dom)
        sm = segnali_mittente(a)
        n = r["n"]
        q = {k: r["cat"][k] / n for k in ("PROMOTIONS", "UPDATES", "SOCIAL", "FORUMS")}
        base = {
            "dominio": dom,
            "org": org,
            "generico": dom in GENERIC_PROVIDERS,
            "n": n,
            "q_promo": q["PROMOTIONS"],
            "q_updates": q["UPDATES"],
            "q_social": q["SOCIAL"],
            "q_forums": q["FORUMS"],
            "q_unsub": r["unsub"] / n,
            **sm,
            "local_tipo": tipo_local(a),
            "owner_scrive_indirizzo": owner_a.get(a, 0),
            "owner_scrive_org": owner_org.get(org, 0),
            "thread_risposti": len(r["risposti"]),
            "a_owner_diretto": r["a_owner"],
            "altrove": a in altrove,
        }
        tipo = classifica(base, interni)
        corretto = a in corrette
        righe.append(
            {
                "indirizzo": a,
                **base,
                "tipo": corrette.get(a, tipo),
                "tipo_calcolato": tipo,
                "corretto": corretto,
                "ultimo": str(r["ultimo"])[:10] if r["ultimo"] is not None else "",
            }
        )
    return pd.DataFrame(righe)


_CACHE: dict = {}


def tipi_mittenti(percorso: Path | None = None) -> dict[str, str]:
    ""
    import pandas as pd

    percorso = percorso or TABELLA_POSTA
    try:
        firma = (str(percorso), percorso.stat().st_mtime_ns)
    except OSError:
        return {}
    if _CACHE.get("firma") != firma:
        try:
            df = pd.read_parquet(percorso, columns=["indirizzo", "tipo"])
        except (OSError, ValueError, KeyError):
            return {}
        _CACHE.update(firma=firma, tipi=dict(zip(df["indirizzo"], df["tipo"], strict=True)))
    return _CACHE["tipi"]


def regolazioni() -> dict:
    ""
    try:
        import impostazioni_pipeline

        return impostazioni_pipeline.leggi().get("rumore", {})
    except Exception:  # noqa: BLE001 - without the settings, it stays as it was
        return {}


def e_rumore(indirizzo: str, tipi: dict[str, str] | None = None) -> bool:
    ""
    tipi = tipi_mittenti() if tipi is None else tipi
    return tipi.get((indirizzo or "").strip().lower()) in TIPI_RUMORE


def e_rapporto(indirizzo: str, tipi: dict[str, str] | None = None) -> bool:
    tipi = tipi_mittenti() if tipi is None else tipi
    return tipi.get((indirizzo or "").strip().lower()) in TIPI_RAPPORTO


def conta_nei_punteggi(indirizzo: str, tipi: dict[str, str] | None = None) -> bool:
    ""
    tipi = tipi_mittenti() if tipi is None else tipi
    tipo = tipi.get((indirizzo or "").strip().lower())
    if tipo in TIPI_RUMORE:
        return False
    if tipo in TIPI_DUBBI:
        return bool(regolazioni().get("dubbi_contano", True))
    return True





def tipo_gruppo_finale(chiave: str, calcolato: str, corr: dict | None = None) -> tuple[str, str]:
    ""

    corr = correzioni() if corr is None else corr
    if chiave in (corr.get("whatsapp") or {}):
        return corr["whatsapp"][chiave], "manual correction"
    attesa = ((corr.get("in_attesa") or {}).get("whatsapp") or {}).get(chiave)
    if attesa and calcolato == "rumore":
        return "dubbio", f"awaiting review: {attesa}"
    return calcolato, "rule"


def gruppi_rumore(percorso: Path | None = None) -> set[str]:
    ""
    import pandas as pd

    try:
        df = pd.read_parquet(percorso or TABELLA_GRUPPI, columns=["chiave", "tipo"])
    except (OSError, ValueError, KeyError):
        return set()
    return set(df.loc[df["tipo"] == "rumore", "chiave"])


def classifica_gruppo(
    *,
    membri: int,
    messaggi: int,
    tuoi: int,
    mesi_dall_ultimo_tuo: float | None,
    silenziato: bool = False,
    archiviato: bool = False,
    speciale: bool = False,
    di_lavoro: bool = False,
) -> str:
    ""






    if speciale:
        return "rumore"
    quota = tuoi / messaggi if messaggi else 0.0
    r1 = (
        membri >= 30
        and quota < 0.01
        and (mesi_dall_ultimo_tuo is None or mesi_dall_ultimo_tuo > 24)
    )
    r2 = (silenziato or archiviato) and membri >= 20 and quota < 0.01
    if r1 or r2:
        return "dubbio" if di_lavoro else "rumore"
    return "conversazione"


if __name__ == "__main__":
    tipi = tipi_mittenti()
    if not tipi:
        print(f"the table does not exist yet: {TABELLA_POSTA}")
        raise SystemExit(0)
    conti = Counter(tipi.values())
    for t, n in conti.most_common():
        segno = "rumore" if t in TIPI_RUMORE else "dubbio" if t in TIPI_DUBBI else "rapporto"
        print(f"  {t:<24} {n:6}  {segno}")
