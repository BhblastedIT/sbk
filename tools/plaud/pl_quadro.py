#!/usr/bin/env python3
"""Plaud speaker overview: who speaks in each recording, the minutes still without a name and how solid each name is; writes quadro.json (--stampa only prints)."""






















from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.plaud.pl_context_emit import emit_all  # noqa: E402
from tools.plaud.regole.nomi import OWNER_CANONICO, OWNER_PRIMO, OWNER_TOKENS  # noqa: E402

DATA = Path(os.environ.get("SBK_DATA", Path.home() / ".sbk-data"))
RAW = DATA / "plaud" / "raw"
QUADRO = DATA / "plaud" / "quadro"
DETTAGLI = DATA / "plaud" / "dettagli"
WRITE_HISTORY = DATA / "plaud" / "write_history.jsonl"
BACKUP_LEDGER = DATA / "plaud" / "backups" / "backup-ledger.jsonl"
NAME_INDEX = DATA / "plaud" / "pl-name-index.json"
CALENDARI = DATA / "calendars"
L3 = DATA / "l3" / "nlp"

GENERICO = re.compile(r"^speaker\s*\d+$", re.I)
NON_NOMI = {
    "r",
    "rumore",
    "voce di fondo inutile",
    "varie",
    "demo",
    "speaker",
    "unknown",
    "sconosciuto",
}
# Your own speaker labels, from sbk.config.json (owner, own_names).
OWNER = set(OWNER_TOKENS) | ({OWNER_CANONICO} if OWNER_CANONICO else set())
# The label Plaud gives your own voice: your name as first.last ("alex.demo").
OWNER_PLAUD_LABEL = OWNER_CANONICO.replace(" ", ".")
PAROLE_COMUNI = frozenset(
    [
        "management",
        "software",
        "design",
        "fashion",
        "business",
        "data",
        "product",
        "sales",
        "cloud",
        "digital",
        "tech",
        "app",
        "web",
        "marketing",
        "office",
        "meeting",
        "call",
        "manager",
        "partner",
        "food",
        "beauty",
        "project",
        "progetto",
        "scusa",
        "scusate",
        "senti",
        "guarda",
        "allora",
        "comunque",
        "perfetto",
        "esatto",
        "tesoro",
        "amore",
        "fratello",
        "ragazzo",
        "ragazza",
        "zio",
        "compa",
        "capo",
        "bro",
        "mister",
        "boh",
        "vabbè",
        "dai",
        "forza",
        "buongiorno",
        "buonasera",
        "al",
        "la",
        "il",
        "lo",
        "le",
        "gli",
        "di",
        "de",
        "da",
        "del",
        "della",
        "dei",
        "the",
        "and",
        "per",
        "con",
        "non",
        "che",
        "chi",
        "qua",
        "qui",
        "bravo",
        "tutti",
        "ragazzi",
        "stati",
        "clienti",
        "cliente",
        "uno",
        "una",
        "bella",
        "bello",
        "fine",
        "mamma",
        "papa",
        "numeri",
        "meta",
        "lavoro",
        "fornitori",
        "vale",
        "cose",
        "secondo",
        "hey",
        "super",
        "milano",
        "roma",
        "napoli",
        "top",
        "buono",
        "meglio",
        "google",
        "tiktok",
        "linkedin",
        "instagram",
        "facebook",
        "amazon",
        "apple",
        "marketing",
        "brand",
        "media",
        "social",
        "team",
        "studio",
        "gruppo",
        "italia",
        "ai",
        "prodotti",
        "prodotto",
        "piano",
        "costi",
        "soci",
        "persone",
        "altri",
        "piccoli",
        "now",
        "dale",
        "madonna",
        "mo",
        "so",
        "sa",
        "li",
        "fa",
        "via",
        "casa",
        "amico",
        "amici",
        "signore",
        "signora",
        "dottore",
        "dottor",
        "dott",
        "avvocato",
        "capo",
        "boss",
        "grazie",
        "ciao",
        "prego",
        "okay",
        "ok",
        "yes",
        "sir",
        "mister",
    ]
)
OWNER_EMAIL_LOCALI = re.compile(
    r"^(?:owner" + "".join("|" + re.escape(t.replace(" ", ".")) for t in sorted(OWNER, key=len, reverse=True)) + r")",
    re.I,
)


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def classe_etichetta(label: str | None) -> str:
    n = norm(label)
    if not n or GENERICO.match(n):
        return "generico"
    if n in NON_NOMI or n.startswith("misto") or len(n) <= 1:
        return "non-nome"
    if n in OWNER or (OWNER_CANONICO and n.startswith(OWNER_CANONICO)):
        return "owner"
    return "nome"


def tokens_nome(label: str) -> set[str]:
    return {t for t in norm(label).split() if len(t) >= 3}





def carica_indice() -> dict[str, dict]:
    return {x["id"]: x for x in json.loads((RAW / "_file_index.json").read_text())}


def mappa_id_json() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for t in RAW.glob("*.txt"):
        try:
            head = t.open(errors="ignore").read(400)
        except OSError:
            continue
        m = re.search(r"# ID:\s*(\S+)", head)
        j = t.with_suffix(".json")
        if m and j.exists():
            out[m.group(1)] = j
    return out


def scritture_nostre() -> dict[str, dict[str, str]]:
    ""

    out: dict[str, dict[str, str]] = defaultdict(dict)
    if not WRITE_HISTORY.exists():
        return out
    for line in WRITE_HISTORY.read_text().splitlines():
        try:
            w = json.loads(line)
        except json.JSONDecodeError:
            continue
        ops = w.get("ops") or {}
        if isinstance(ops, dict):
            for slot, op in ops.items():
                if isinstance(op, dict) and op.get("new"):
                    out[w.get("file_id", "")][slot] = op["new"]
    return out


def scritture_senza_storico(nostre: dict) -> list[str]:
    if not BACKUP_LEDGER.exists():
        return []
    ids = set()
    for line in BACKUP_LEDGER.read_text().splitlines():
        try:
            ids.add(json.loads(line).get("file_id"))
        except json.JSONDecodeError:
            continue
    return sorted(i for i in ids if i and i not in nostre)


def conferme_owner() -> dict[tuple[str, str], dict]:
    p = QUADRO / "conferme-owner.jsonl"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[(c["file_id"], c["slot"])] = c
    return out


def nomi_kb() -> tuple[frozenset[str], dict[str, int]]:
    ""

    if not NAME_INDEX.exists():
        return frozenset(), {}
    d = json.loads(NAME_INDEX.read_text())
    full = d.get("full") or {}

    primi: Counter = Counter()
    for k, v in full.items():
        t = norm(k).split()
        if len(t) >= 2 and t[0].isalpha() and len(t[0]) >= 3:
            primi[t[0]] += len(v)
    pool = frozenset(t for t, c in primi.items() if c >= 4 and t not in PAROLE_COMUNI)
    return pool, {norm(k): len(v) for k, v in full.items()}


def carica_eventi() -> list[dict]:
    ""
    import duckdb

    con = duckdb.connect()
    con.execute("set memory_limit='1GB'; set threads=2")
    righe = con.execute(
        "select distinct summary, start_datetime, end_datetime, location, conference_url, attendees "
        f"from read_parquet('{CALENDARI}/*/events.parquet', union_by_name=true) "
        "where length(start_datetime) > 10 and coalesce(status,'') <> 'cancelled'"
    ).fetchall()
    ev = []
    for summary, s, e, loc, conf, att in righe:
        try:
            a = dt.datetime.fromisoformat(s).timestamp()
            b = dt.datetime.fromisoformat(e).timestamp() if e else a + 1800
        except ValueError:
            continue
        if b - a > 12 * 3600 or b <= a:
            continue
        invitati = []
        try:
            for x in json.loads(att or "[]"):
                em = (x.get("email") or "").lower()
                if (
                    not em
                    or OWNER_EMAIL_LOCALI.match(em.split("@")[0])
                    or x.get("status") == "declined"
                ):
                    continue
                if "resource.calendar" in em or em.startswith("group") or "noreply" in em:
                    continue
                invitati.append(em)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        ev.append(
            {
                "a": a,
                "b": b,
                "titolo": summary or "",
                "luogo": (loc or "").strip(),
                "call": bool(conf),
                "invitati": invitati,
            }
        )
    ev.sort(key=lambda x: x["a"])
    return ev


def eventi_sovrapposti(eventi: list[dict], a: float, b: float, toll: float = 1200) -> list[dict]:
    out = []
    for e in eventi:
        if e["a"] > b + toll:
            break
        if e["b"] >= a - toll and e["a"] <= b + toll:
            out.append(e)
    return out


def chiave_titolo(nome_file: str) -> str:
    ""
    base = Path(nome_file).stem
    data, _, titolo = base.partition("_")
    titolo = re.sub(r"^\d\d-\d\d\s*", "", titolo)
    return data + "|" + re.sub(r"[^a-z0-9]", "", norm(titolo))[:60]


def alias_nomi(id2json: dict[str, Path]) -> dict[str, str]:
    ""

    out: dict[str, str] = {}
    for fid, p in id2json.items():
        out[chiave_titolo(p.name)] = fid
    dop = RAW / "_doppioni"
    sp = dop / "_spostati.jsonl"
    if sp.exists():
        for line in sp.read_text().splitlines():
            try:
                x = json.loads(line)
            except json.JSONDecodeError:
                continue
            for k in ("spostato", "tenuto"):
                if x.get(k) and x.get("id"):
                    out.setdefault(chiave_titolo(x[k] + ".json"), x["id"])
    for t in dop.glob("*.txt") if dop.exists() else []:
        m = re.search(r"# ID:\s*(\S+)", t.open(errors="ignore").read(400))
        if m:
            out.setdefault(chiave_titolo(t.with_suffix(".json").name), m.group(1))
    return out


def abbina_kb(fatti: dict[str, int], alias: dict[str, str]) -> dict[str, int]:
    ""
    import difflib

    per_data: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for k, fid in alias.items():
        per_data[k[:10]].append((k[11:], fid))
    out: Counter = Counter()
    for k, n in fatti.items():
        fid = alias.get(k)
        if not fid:
            cand = per_data.get(k[:10], [])
            best = max(
                cand,
                key=lambda c: difflib.SequenceMatcher(None, c[0], k[11:]).ratio(),
                default=None,
            )
            if best and difflib.SequenceMatcher(None, best[0], k[11:]).ratio() >= 0.55:
                fid = best[1]
            elif len({f for _, f in cand}) == 1:
                fid = cand[0][1]
        if fid:
            out[fid] += n
    return dict(out)


def fatti_kb_per_registrazione() -> tuple[dict[str, int], str | None]:
    import duckdb

    con = duckdb.connect()
    con.execute("set memory_limit='1GB'; set threads=2")
    conta: Counter = Counter()
    ultima = None
    for p in ("deep-facts", "relationship-facts"):
        f = L3 / f"{p}.parquet"
        if not f.exists():
            continue
        for sid, n in con.execute(
            f"select source_id, count(*) from read_parquet('{f}') where source_type='plaud' group by 1"
        ).fetchall():
            conta[chiave_titolo(sid or "")] += n
            d = (sid or "")[:10]
            if re.match(r"\d{4}-\d\d-\d\d", d) and (ultima is None or d > ultima) and d < "2100":
                ultima = d
    return dict(conta), ultima


def dettaglio(fid: str) -> dict:
    p = DETTAGLI / f"{fid}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}





def analizza(fid: str, meta: dict, segs: list[dict], ctx: dict) -> dict:
    voci: dict[str, dict] = {}
    for s in segs:
        if not isinstance(s, dict):
            continue
        slot = s.get("original_speaker") or s.get("speaker") or "?"
        try:
            ms = max(0, int(s.get("end_time") or 0) - int(s.get("start_time") or 0))
        except (TypeError, ValueError):
            ms = 0
        v = voci.setdefault(slot, {"ms": 0, "etichette": Counter(), "seg": 0})
        v["ms"] += ms
        v["seg"] += 1
        v["etichette"][s.get("speaker") or ""] += ms or 1

    st = (meta.get("st") or 0) / 1000
    durata = float(meta.get("duration_sec") or 0)
    eventi = eventi_sovrapposti(ctx["eventi"], st, st + durata) if st else []
    eventi.sort(
        key=lambda e: (abs(e["a"] - st), e["titolo"])
    )
    piccoli = [e for e in eventi if 0 < len(e["invitati"]) <= 6]
    invitati = sorted({i for e in piccoli for i in e["invitati"]})
    luoghi = sorted(
        {e["luogo"] for e in eventi if e["luogo"] and not e["luogo"].startswith("http")}
    )


    testo_per_voce: dict[str, Counter] = defaultdict(Counter)
    try:
        for ev in emit_all(segs, ctx["pool"]):
            sig = ev.meta.get("signal", "")
            if sig.startswith("S1_"):
                sid, nome = ev.meta.get("target_speaker_id"), ev.meta.get("addressed_name")
            elif sig in ("S2_self_intro",):
                sid, nome = ev.meta.get("speaker_id"), ev.meta.get("self_name")
            elif sig.startswith("S2_owner"):
                sid, nome = ev.meta.get("speaker_id"), OWNER_PRIMO
            else:
                continue
            nome = norm(nome)
            if sid and nome and (nome == OWNER_PRIMO or nome.split()[0] in ctx["pool"]):
                testo_per_voce[sid][nome] += 1
    except Exception:  # noqa: BLE001 - a strange file does not stop the quadro
        pass

    nostre = ctx["nostre"].get(fid, {})
    etichette_per_nome: Counter = Counter()
    righe = []
    for slot, v in voci.items():
        label = v["etichette"].most_common(1)[0][0]
        righe.append((slot, v, label))
        if classe_etichetta(label) in ("nome", "owner"):
            etichette_per_nome[norm(label)] += 1

    out_voci = []
    for slot, v, label in righe:
        cl = classe_etichetta(label)
        prove, contro, avvisi = [], [], []
        conf = ctx["conferme"].get((fid, slot))
        if cl in ("nome", "owner"):
            tk = tokens_nome(label)
            if cl == "nome" and any(any(t in inv.split("@")[0] for t in tk) for inv in invitati):
                prove.append("calendario")
            dal_testo = testo_per_voce.get(slot, Counter())
            if any(any(t == n or t in n.split() for t in (tk or {norm(label)})) for n in dal_testo):
                prove.append("testo")
            altri = {n for n in dal_testo if n and not any(t in n.split() for t in tk)}
            if cl == "nome" and sum(dal_testo[n] for n in altri) >= 2 and not prove:
                contro.append("il testo la chiama con un altro nome")
            if nostre.get(slot) and norm(nostre[slot]) == norm(label):
                prove.append("agenti con citazione")
            if (
                cl == "owner"
                and OWNER_PLAUD_LABEL
                and label == OWNER_PLAUD_LABEL
            ):
                prove.append("voce (Plaud, proprietario)")
            if cl == "nome" and etichette_per_nome[norm(label)] >= 2:
                contro.append("stesso nome su più speaker")
            if cl == "owner" and etichette_per_nome[norm(label)] >= 2:
                avvisi.append("il proprietario su più speaker")
            if cl == "nome" and ctx["kb_full"].get(norm(label), 0) > 1:
                avvisi.append("nome di più persone nel KB")
            if cl == "nome" and len(tk) <= 1:
                avvisi.append("solo il nome di battesimo")
        nome_noto = ""
        if conf and conf.get("non_e") and norm(conf["non_e"]) == norm(label):
            livello = "smentito"
        elif conf and conf.get("nome") and cl in ("nome", "owner"):
            livello = "confermato" if norm(conf["nome"]) == norm(label) else "smentito"
        elif conf and conf.get("nome"):
            livello, nome_noto = "senza nome", conf["nome"]
        elif cl == "generico" or cl == "non-nome":
            livello = "senza nome"
        elif contro:
            livello = "sospetto"
        elif len(set(prove)) >= 2:
            livello = "solido"
        elif prove:
            livello = "una prova"
        else:
            livello = "solo nome"
        provenienza = (
            "il proprietario"
            if conf
            else "noi"
            if nostre.get(slot) and norm(nostre[slot]) == norm(label)
            else "Plaud o il proprietario"
            if cl in ("nome", "owner")
            else "-"
        )
        candidati = (
            [n for n, c in testo_per_voce.get(slot, Counter()).most_common(3)]
            if cl == "generico"
            else []
        )
        out_voci.append(
            {
                "voce": slot,
                "etichetta": label if cl != "generico" else "",
                "classe": cl,
                "minuti": round(v["ms"] / 60000, 1),
                "livello": livello,
                "prove": sorted(set(prove)),
                "contro": contro,
                "avvisi": avvisi,
                "provenienza": provenienza,
                "indizi_testo": candidati,
                "nome_noto": nome_noto,
            }
        )
    det = ctx["dettaglio"](fid)
    return {
        "id": fid,
        "titolo": meta.get("filename") or "",
        "data": meta.get("date") or "",
        "inizio": dt.datetime.fromtimestamp(st).isoformat(timespec="minutes") if st else "",
        "durata_min": round(durata / 60, 1),
        "tipo": {
            1: "registratore",
            102: "app",
            101: "audio importato",
            1000: "esempio di Plaud",
        }.get(meta.get("scene"), "altro"),
        "trascritta_da": det.get("piattaforma"),
        "registratore": det.get("dispositivo"),
        "voci": out_voci,
        "una_voce_sola": len(out_voci) == 1 and durata >= 1200,
        "contesto": {
            "eventi": [e["titolo"][:80] for e in eventi[:3]],
            "invitati": len(invitati),
            "luogo": luoghi[:2],
            "call": any(e["call"] for e in eventi),
            "di_persona": any(
                e["luogo"] and not e["luogo"].startswith("http") and not e["call"] for e in eventi
            ),
        },
        "fatti_kb": ctx["fatti"].get(fid, 0),
    }





LIVELLI = ["confermato", "solido", "una prova", "solo nome", "sospetto", "smentito", "senza nome"]


def aggrega(regs: list[dict], extra: dict) -> dict:
    voci = [(r, v) for r in regs for v in r["voci"]]
    min_tot = sum(v["minuti"] for _, v in voci) or 1
    per_liv = {lv: {"voci": 0, "minuti": 0.0} for lv in LIVELLI}
    for _, v in voci:
        per_liv[v["livello"]]["voci"] += 1
        per_liv[v["livello"]]["minuti"] += v["minuti"]
    for lv in per_liv.values():
        lv["minuti"] = round(lv["minuti"])
    nominate = [v for _, v in voci if v["livello"] != "senza nome"]
    min_nom = sum(v["minuti"] for v in nominate) or 1
    solidi = sum(v["minuti"] for v in nominate if v["livello"] in ("confermato", "solido"))
    sospetti = sum(v["minuti"] for v in nominate if v["livello"] in ("sospetto", "smentito"))
    verificate = [v for v in nominate if v["livello"] in ("confermato", "smentito")]
    giuste = sum(1 for v in verificate if v["livello"] == "confermato")

    per_mese: dict[str, dict] = {}
    for r in regs:
        m = (r["data"] or "?")[:7]
        pm = per_mese.setdefault(
            m,
            {
                "mese": m,
                "registrazioni": 0,
                "ore": 0.0,
                "minuti_senza_nome": 0.0,
                "minuti": 0.0,
                "senza_nessun_nome": 0,
                "minuti_solidi": 0.0,
                "nel_kb": 0,
            },
        )
        pm["registrazioni"] += 1
        pm["ore"] += r["durata_min"] / 60
        pm["nel_kb"] += 1 if r["fatti_kb"] else 0
        if all(v["livello"] == "senza nome" for v in r["voci"]):
            pm["senza_nessun_nome"] += 1
        for v in r["voci"]:
            pm["minuti"] += v["minuti"]
            if v["livello"] == "senza nome":
                pm["minuti_senza_nome"] += v["minuti"]
            if v["livello"] in ("confermato", "solido"):
                pm["minuti_solidi"] += v["minuti"]
    for pm in per_mese.values():
        tot = pm["minuti"] or 1
        pm["ore"] = round(pm["ore"], 1)
        pm["pct_senza_nome"] = round(100 * pm["minuti_senza_nome"] / tot)
        pm["pct_solidi"] = round(100 * pm["minuti_solidi"] / tot)
        for k in ("minuti_senza_nome", "minuti", "minuti_solidi"):
            pm[k] = round(pm[k])

    def mancano(r: dict) -> float:
        return sum(v["minuti"] for v in r["voci"] if v["livello"] == "senza nome")

    lista_mancano = sorted(
        (
            {
                "id": r["id"],
                "titolo": r["titolo"],
                "data": r["data"],
                "inizio": r["inizio"],
                "durata_min": r["durata_min"],
                "minuti_senza_nome": round(mancano(r)),
                "voci_senza_nome": sum(1 for v in r["voci"] if v["livello"] == "senza nome"),
                "voci": len(r["voci"]),
                "fatti_kb": r["fatti_kb"],
                "contesto": r["contesto"],
                "tipo": r["tipo"],
                "trascritta_da": r["trascritta_da"],
                "una_voce_sola": r.get("una_voce_sola", False),
                "indizi": sorted({n for v in r["voci"] for n in v["indizi_testo"]})[:6],
            }
            for r in regs
            if mancano(r) > 0
        ),
        key=lambda x: -x["minuti_senza_nome"],
    )
    con_indizi = [x for x in lista_mancano if x["contesto"]["invitati"] or x["indizi"]]
    fuori_kb = sorted((r for r in regs if not r["fatti_kb"]), key=lambda r: -r["durata_min"])

    gruppi = [
        ("calendario e testo", "invitati a quell'ora e un nome detto nel testo"),
        ("incontro piccolo a calendario", "una o due persone invitate, pochi speaker"),
        ("nome detto nel testo", "qualcuno la chiama per nome o si presenta"),
        ("prima separare le voci", "Plaud ha messo tutto su uno speaker solo"),
        ("invitati, incontro grande", "a calendario ma con più invitati che speaker"),
        ("nessun indizio", "niente calendario né nomi nel testo: voce, tue conferme, contesto"),
    ]
    conta_g = {g: {"voci": 0, "minuti": 0.0} for g, _ in gruppi}
    gruppo_reg: dict[str, int] = {}
    for r in regs:
        c = r["contesto"]
        for v in r["voci"]:
            if v["livello"] != "senza nome":
                continue
            if r.get("una_voce_sola"):
                g = "prima separare le voci"
            elif c["invitati"] and v["indizi_testo"]:
                g = "calendario e testo"
            elif 1 <= c["invitati"] <= 2 and len(r["voci"]) <= 3:
                g = "incontro piccolo a calendario"
            elif v["indizi_testo"]:
                g = "nome detto nel testo"
            elif c["invitati"]:
                g = "invitati, incontro grande"
            else:
                g = "nessun indizio"
            ordine = [x for x, _ in gruppi].index(g)
            gruppo_reg[r["id"]] = min(gruppo_reg.get(r["id"], 99), ordine)
            conta_g[g]["voci"] += 1
            conta_g[g]["minuti"] += v["minuti"]
    for x in lista_mancano:
        x["gruppo"] = gruppi[gruppo_reg[x["id"]]][0] if x["id"] in gruppo_reg else ""
    piano_nomi = [
        {
            "gruppo": g,
            "come": come,
            "voci": conta_g[g]["voci"],
            "ore": round(conta_g[g]["minuti"] / 60),
        }
        for g, come in gruppi
    ]

    return {
        "totali": {
            "registrazioni": len(regs),
            "ore": round(sum(r["durata_min"] for r in regs) / 60),
            "voci": len(voci),
            "minuti_parlato": round(min_tot),
        },
        "nomi": {
            "voci_senza_nome": per_liv["senza nome"]["voci"],
            "minuti_senza_nome": per_liv["senza nome"]["minuti"],
            "pct_minuti_senza_nome": round(100 * per_liv["senza nome"]["minuti"] / min_tot),
            "registrazioni_senza_nessun_nome": sum(
                1 for r in regs if all(v["livello"] == "senza nome" for v in r["voci"])
            ),
            "registrazioni_una_voce_sola": sum(1 for r in regs if r.get("una_voce_sola")),
            "ore_una_voce_sola": round(
                sum(r["durata_min"] for r in regs if r.get("una_voce_sola")) / 60
            ),
            "registrazioni_tutte_nominate": sum(
                1 for r in regs if all(v["livello"] != "senza nome" for v in r["voci"])
            ),
            "voci_owner": sum(1 for _, v in voci if v["classe"] == "owner"),
            "voci_altri": sum(1 for _, v in voci if v["classe"] == "nome"),
            "nomi_scritti_da_noi": sum(1 for _, v in voci if v["provenienza"] == "noi"),
        },
        "solidita": {
            "livelli": per_liv,
            "pct_solidi_sui_nominati": round(100 * solidi / min_nom),
            "pct_sospetti_sui_nominati": round(100 * sospetti / min_nom),
            "come_si_misura": "minutes of speech with a name confirmed by the owner or backed by two independent pieces of evidence, over the minutes that have a name",
        },
        "veridicita": {
            "voci_verificate_da_owner": len(verificate),
            "giuste": giuste,
            "sbagliate": len(verificate) - giuste,
            "pct_misurata": round(100 * giuste / len(verificate)) if verificate else None,
            "copertura_pct": round(100 * len(verificate) / max(1, len(nominate)), 2),
            "come_si_misura": "only where the owner has confirmed who it is: correct over the verified ones. Below a minimum threshold of verifications it is a signal, not a measure.",
        },
        "piano_nomi": piano_nomi,
        "per_mese": [per_mese[k] for k in sorted(per_mese)],
        "mancano": lista_mancano,
        "mancano_con_indizi": len(con_indizi),
        "kb": {
            "registrazioni_con_fatti": sum(1 for r in regs if r["fatti_kb"]),
            "registrazioni_fuori": len(fuori_kb),
            "ore_fuori": round(sum(r["durata_min"] for r in fuori_kb) / 60),
            "ultima_registrazione_nel_kb": extra.get("ultima_kb"),
            "piu_lunghe_fuori": [
                {
                    "id": r["id"],
                    "titolo": r["titolo"],
                    "data": r["data"],
                    "durata_min": r["durata_min"],
                    "minuti_senza_nome": round(mancano(r)),
                    "contesto": r["contesto"],
                }
                for r in fuori_kb[:40]
            ],
        },
        "contesto": {
            "con_evento": sum(1 for r in regs if r["contesto"]["eventi"]),
            "con_invitati": sum(1 for r in regs if r["contesto"]["invitati"]),
            "con_luogo": sum(1 for r in regs if r["contesto"]["luogo"]),
            "in_call": sum(1 for r in regs if r["contesto"]["call"]),
            "di_persona": sum(1 for r in regs if r["contesto"].get("di_persona")),
            "per_tipo": dict(Counter(r["tipo"] for r in regs)),
            "trascritta_da": dict(Counter(r["trascritta_da"] or "non letto" for r in regs)),
        },
        "registro_scritture": {
            "note_con_backup_senza_storico": extra.get("senza_storico", []),
        },
    }


INDIZI = [

    (
        "plaud_etichetta",
        "Label set by Plaud",
        0.55,
        "starting weight, to be tuned on the confirmations",
    ),
    (
        "plaud_voce_tua",
        "Your voice recognized by Plaud",
        0.80,
        "the only voice Plaud still recognizes, if you have the profile",
    ),
    (
        "calendario",
        "Invited to the event at that time",
        0.60,
        "many recordings are not on the calendar or have several invitees",
    ),
    (
        "testo",
        "Name said in the text near that speaker",
        0.70,
        "vocatives and introductions, sometimes on the wrong turn",
    ),
    (
        "agenti",
        "Name found by the agents with the quote",
        0.85,
        "starting threshold",
    ),
    ("voce_nostra", "Voice recognized by us", 0.70, "our own voice registry, still small"),
]


def impara_indizi(regs: list[dict], conferme: dict, nostre_storia: dict) -> list[dict]:
    ""


    per_id = {r["id"]: r for r in regs}
    conta = {k: {"giusti": 0, "sbagliati": 0, "casi": []} for k, *_ in INDIZI}

    def segna(k: str, nome: str, conf: dict, fid: str, slot: str) -> None:
        if not nome:
            return
        if conf.get("non_e"):
            ok = norm(nome) != norm(conf["non_e"])
        else:
            ok = norm(nome) == norm(conf.get("nome"))
        conta[k]["giusti" if ok else "sbagliati"] += 1
        conta[k]["casi"].append({"id": fid, "voce": slot, "diceva": nome, "giusto": ok})

    for (fid, slot), conf in conferme.items():
        r = per_id.get(fid)
        v = next((x for x in (r or {}).get("voci", []) if x["voce"] == slot), None)
        storia = nostre_storia.get((fid, slot), [])
        if storia:
            vecchio = storia[0]["old"]
            if classe_etichetta(vecchio) in ("nome", "owner"):
                segna(
                    "plaud_voce_tua" if OWNER_PLAUD_LABEL and vecchio == OWNER_PLAUD_LABEL else "plaud_etichetta",
                    vecchio,
                    conf,
                    fid,
                    slot,
                )
            for w in storia:
                segna("agenti", w["new"], conf, fid, slot)
        elif v and v["classe"] in ("nome", "owner"):
            chi = (
                "plaud_voce_tua" if OWNER_PLAUD_LABEL and v["etichetta"] == OWNER_PLAUD_LABEL else "plaud_etichetta"
            )
            segna(chi, v["etichetta"], conf, fid, slot)
        if v and v["classe"] in ("nome", "owner"):
            for prova in v.get("prove", []):
                if prova in ("calendario", "testo"):
                    segna(prova, v["etichetta"], conf, fid, slot)
    out = []
    for k, nome, partenza, perche in INDIZI:
        g, b = conta[k]["giusti"], conta[k]["sbagliati"]
        out.append(
            {
                "chiave": k,
                "indizio": nome,
                "partenza": partenza,
                "perche_partenza": perche,
                "giusti": g,
                "sbagliati": b,
                "punteggio": round((g + 2 * partenza) / (g + b + 2), 2),
                "casi": conta[k]["casi"],
            }
        )
    return out


def storia_nostre_scritture() -> dict:
    ""
    out: dict = defaultdict(list)
    if WRITE_HISTORY.exists():
        for line in WRITE_HISTORY.read_text().splitlines():
            try:
                w = json.loads(line)
            except json.JSONDecodeError:
                continue
            for slot, op in (w.get("ops") or {}).items():
                if isinstance(op, dict):
                    out[(w.get("file_id"), slot)].append(
                        {"old": op.get("old"), "new": op.get("new")}
                    )
    return out


def calcola() -> tuple[dict, list[dict]]:
    indice = carica_indice()
    id2json = mappa_id_json()
    pool, kb_full = nomi_kb()
    fatti_chiave, ultima_kb = fatti_kb_per_registrazione()
    fatti = abbina_kb(fatti_chiave, alias_nomi(id2json))
    nostre = scritture_nostre()
    ctx = {
        "eventi": carica_eventi(),
        "pool": pool,
        "kb_full": kb_full,
        "fatti": fatti,
        "nostre": nostre,
        "conferme": conferme_owner(),
        "dettaglio": dettaglio,
    }
    regs = []
    for fid, meta in indice.items():
        if meta.get("is_trash") or fid not in id2json:
            continue
        if (meta.get("date") or "") < "2024" or meta.get("scene") == 1000:
            continue
        try:
            segs = json.loads(id2json[fid].read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(segs, list):
            continue
        ctx["json_path"] = str(id2json[fid])
        regs.append(analizza(fid, meta, segs, ctx))
    regs.sort(key=lambda r: r["inizio"] or r["data"])
    agg = aggrega(regs, {"ultima_kb": ultima_kb, "senza_storico": scritture_senza_storico(nostre)})
    dispositivi_p = DETTAGLI / "_dispositivi.json"
    agg["indizi"] = impara_indizi(regs, ctx["conferme"], storia_nostre_scritture())
    punteggi = {i["chiave"]: i["punteggio"] for i in agg["indizi"]}
    dist: Counter = Counter()
    for r in regs:
        for v in r["voci"]:
            if v["classe"] not in ("nome", "owner"):
                continue
            segnali = []
            if v["provenienza"] in ("Plaud o il proprietario", "il proprietario") and v["etichetta"]:
                segnali.append(
                    "plaud_voce_tua"
                    if OWNER_PLAUD_LABEL and v["etichetta"] == OWNER_PLAUD_LABEL
                    else "plaud_etichetta"
                )
            if v["provenienza"] == "noi":
                segnali.append("agenti")
            segnali += [p for p in v.get("prove", []) if p in ("calendario", "testo")]
            resto = 1.0
            for k in set(segnali):
                resto *= 1 - punteggi.get(k, 0.5)
            v["punteggio"] = round(1 - resto, 2) if segnali else 0.0
            v["indizi"] = sorted(set(segnali))
            fascia = (
                "90% e oltre"
                if v["punteggio"] >= 0.9
                else "70-90%"
                if v["punteggio"] >= 0.7
                else "50-70%"
                if v["punteggio"] >= 0.5
                else "sotto il 50%"
            )
            dist[fascia] += 1
    agg["fiducia_nomi"] = {
        f: dist.get(f, 0) for f in ("90% e oltre", "70-90%", "50-70%", "sotto il 50%")
    }
    agg["dispositivi"] = json.loads(dispositivi_p.read_text()) if dispositivi_p.exists() else {}
    agg["contesto"]["per_registratore"] = dict(
        Counter(r["registratore"] or "non letto" for r in regs)
    )
    agg["senza_trascrizione"] = sum(
        1 for m in indice.values() if not m.get("has_transcript") and not m.get("is_trash")
    )
    return agg, regs


SIGLE = {
    "needsAction": "did not reply",
    "embeddingKey": "Plaud fingerprint",
    "PLAUD_NOTE": "Plaud Note",
    "a_te": "said to the other person",
    "di_se": "said about self",
    "domanda_coda": "question at the end",
    "domanda_testa": "question at the start",
    "mi_chiamo": "«my name is»",
    "noi_di": "«we at»",
    "presenta_altri": "introduced by another",
    "pronto_iniziale": "«hello» at the start",
    "pronto_sono": "«hello, this is»",
    "owner_si_presenta": "the owner introduces themselves",
    "studio_clienti": "firm and clients",
    "titolo_vocativo": "«ma'am», «doctor»",
    "KB": "knowledge base",
    "mpdm": "small group",
    "en": "English",
}
ACUTI = {"se": "sé", "perche": "perché", "ne": "né", "poiche": "poiché", "affinche": "affinché"}
ACCENTI = {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}


def pulisci_testo(t: str | None) -> str:
    ""

    t = t or ""
    t = re.sub(
        r"(?<!\w)'(\S[^'\n]{0,58}\S)'(?=[\s,.;)]|$)", r"«\1»", t
    )
    t = re.sub(
        r"\s*\([^)]*(?:\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z]\w*|\bS\d_)[^)]*\)", "", t
    )
    t = t.replace("fatti KB", "fatti della base di conoscenza")
    t = re.sub(r"\bdel KB\b", "della base di conoscenza", t)
    t = re.sub(
        r"\b(il|nel|al|dal) KB\b",
        lambda m: (
            {"il": "la", "nel": "nella", "al": "alla", "dal": "dalla"}[m.group(1)]
            + " base di conoscenza"
        ),
        t,
    )
    t = re.sub(r"\s*\((?:tentative|declined|accepted|N|P)\)", "", t)
    t = re.sub(r"\b1-1 invitati\b", "un invitato", t)
    t = re.sub(r"\b(\d+)-oltre\b", r"\1 o più", t)
    for k, v in SIGLE.items():
        t = re.sub(rf"\b{k}\b", v, t)
    t = re.sub(r"\bS\d_\w+\b|\bpl_\w+\b", "", t)
    t = re.sub(
        r"\b(se|perche|ne|poiche|affinche)'(?=[\s,.;:)»]|$)",
        lambda m: ACUTI[m.group(1).lower()],
        t,
        flags=re.I,
    )
    t = t.replace("di sè", "di sé")
    t = re.sub(r"\b(\w*?)([aeiou])'(?=[\s,.;:)»]|$)", lambda m: m.group(1) + ACCENTI[m.group(2)], t)
    t = t.replace(" -> ", " → ").replace("->", "→").replace(">=", "≥").replace("<=", "≤")
    t = re.sub(r"\s*\((?:gruppo piccolo)\)", "", t)
    t = re.sub(r"\s*:\s+", ", ", t)
    t = re.sub(r"_", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,")


def regole_in_calcolo() -> list[dict]:
    ""


    pesi = leggi_json(QUADRO / "pesi-regole.json", {}).get("pesi_leggibili", {})
    righe: dict[str, dict] = {}
    for fronte in ("r1", "r2", "r3"):
        f = QUADRO / "segnali" / f"{fronte}.jsonl"
        if not f.exists():
            continue
        with f.open() as fh:
            for line in fh:
                try:
                    x = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = x.get("regola") or ""
                r = righe.get(k)
                if r is None:
                    chiave = f"{fronte.upper()}:{x.get('gruppo')}:{x.get('direzione')}"
                    pw = pesi.get(chiave) or {}
                    r = righe[k] = {
                        "regola": k,
                        "fronte": fronte.upper(),
                        "famiglia": x.get("famiglia", ""),
                        "sottotipo": re.sub(r"\+riportato$", "", x.get("sottotipo", "")),
                        "direzione": x.get("direzione", ""),
                        "tipo": x.get("tipo", ""),
                        "gruppo": x.get("gruppo", ""),
                        "peso": pw.get("presenza"),
                        "voci_addestramento": pw.get("voci_di_addestramento"),
                        "filtro": x.get("direzione") == "esclude" and fronte == "r1",
                        "segnali": 0,
                        "_reg": set(),
                    }
                r["segnali"] += 1
                r["_reg"].add(x.get("file_id"))
    cat = {c["id"]: c for c in leggi_json(QUADRO / "regole-catalogo.json", {}).get("regole", [])}
    out = []
    for r in righe.values():
        r["registrazioni"] = len(r.pop("_reg"))
        c = cat.get(r["regola"])
        r["nome"] = pulisci_testo(c["regola"] if c else r["sottotipo"])
        r["sottotipo"] = pulisci_testo(c["sottotipo"] if c else r["sottotipo"])
        r["famiglia"] = pulisci_testo(r["famiglia"])
        out.append(r)
    return sorted(
        out, key=lambda r: (r["fronte"], r["famiglia"], -(abs(r["peso"] or 0)), r["regola"])
    )


def leggi_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud speaker overview"])[0]
    )
    ap.add_argument("--stampa", action="store_true", help="compute and print, without writing")
    args = ap.parse_args()
    agg, regs = calcola()
    adesso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    quadro = {
        "generato": adesso,
        "obiettivo": leggi_json(QUADRO / "obiettivo.json", {}),
        "perche": leggi_json(QUADRO / "perche.json", {}),
        "metodo": leggi_json(QUADRO / "metodo.json", {}),
        "attivita": leggi_json(QUADRO / "attivita.json", []),
        "regole": {
            "regole": [
                {
                    **r,
                    **{
                        k: pulisci_testo(r.get(k))
                        for k in ("famiglia", "regola", "sottotipo", "stato_perche")
                    },
                }
                for r in leggi_json(QUADRO / "regole-catalogo.json", {}).get("regole", [])
            ]
        },
        "proposte_giudizio": leggi_json(QUADRO / "proposte.json", {}).get("riepilogo", {}),
        "regole_in_calcolo": regole_in_calcolo(),
        **agg,
        "registrazioni": regs,
    }
    riga = {
        "quando": adesso,
        "registrazioni": agg["totali"]["registrazioni"],
        "minuti_parlato": agg["totali"]["minuti_parlato"],
        "pct_minuti_senza_nome": agg["nomi"]["pct_minuti_senza_nome"],
        "voci_senza_nome": agg["nomi"]["voci_senza_nome"],
        "pct_solidi_sui_nominati": agg["solidita"]["pct_solidi_sui_nominati"],
        "pct_sospetti_sui_nominati": agg["solidita"]["pct_sospetti_sui_nominati"],
        "verificate_da_owner": agg["veridicita"]["voci_verificate_da_owner"],
        "registrazioni_fuori_kb": agg["kb"]["registrazioni_fuori"],
        "livelli": {k: v["voci"] for k, v in agg["solidita"]["livelli"].items()},
    }
    if args.stampa:
        print(
            json.dumps(
                {k: agg[k] for k in ("totali", "nomi", "solidita", "veridicita", "contesto")},
                ensure_ascii=False,
                indent=1,
            )
        )
        print("kb", {k: v for k, v in agg["kb"].items() if k != "piu_lunghe_fuori"})
        print("mancano", len(agg["mancano"]), "di cui con indizi", agg["mancano_con_indizi"])
        return 0
    QUADRO.mkdir(parents=True, exist_ok=True)
    storia_p = QUADRO / "storia.jsonl"
    storia = (
        [json.loads(x) for x in storia_p.read_text().splitlines() if x.strip()]
        if storia_p.exists()
        else []
    )
    quadro["storia"] = storia + [riga]
    tmp = QUADRO / "quadro.json.tmp"
    tmp.write_text(json.dumps(quadro, ensure_ascii=False))
    tmp.replace(QUADRO / "quadro.json")
    with storia_p.open("a") as f:
        f.write(json.dumps(riga, ensure_ascii=False) + "\n")
    print(
        f"quadro written: {len(regs)} recordings, {agg['nomi']['pct_minuti_senza_nome']}% of minutes without a name, "
        f"solid {agg['solidita']['pct_solidi_sui_nominati']}% of named minutes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
