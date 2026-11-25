#!/usr/bin/env python3
""




















































from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))

from knowledge_view import (  # noqa: E402
    classe_attributo,
    closure_rate,
    conoscenza,
    is_group_name,
    verdetto_stato,
)

import sbk_config as cfg  # noqa: E402

KB = cfg.DATA_ROOT / "knowledge"
PERSON = KB / "entities" / "person"






INDICE = cfg.DATA_ROOT / "cache" / "sb-who-name-index-v2.json"


def _norm(s: str) -> str:
    ""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def costruisci_indice(verbose: bool = False) -> dict:
    ""








    idx: dict[str, list[str]] = {}
    n = 0
    for f in os.scandir(PERSON):
        if not f.name.endswith(".json"):
            continue
        try:
            d = json.loads(Path(f.path).read_text())
        except Exception:  # noqa: BLE001
            continue
        n += 1
        e_gruppo = is_group_name(d.get("canonical_name") or "")
        nomi = [d.get("canonical_name") or ""]
        for fa in d.get("facts") or []:
            if isinstance(fa, dict) and fa.get("attribute") == "identity.name":
                nomi.append(str(fa.get("value") or ""))
        for nome in nomi:
            k = _norm(nome)
            if not k:
                continue
            idx.setdefault(k, [])
            if f.name not in idx[k]:
                idx[k].append(f.name)





            if e_gruppo:
                continue
            for pezzo in k.split():
                if len(pezzo) >= 4:
                    idx.setdefault(pezzo, [])



                    if f.name not in idx[pezzo] and len(idx[pezzo]) < 40:
                        idx[pezzo].append(f.name)
    if verbose:
        print(f"  index: {n} entities → {len(idx)} keys", file=sys.stderr)
    return idx


def _impronta_store() -> dict:
    ""
    try:
        n, mx = 0, 0.0
        for f in os.scandir(PERSON):
            n += 1
            m = f.stat().st_mtime
            if m > mx:
                mx = m
        return {"n_file": n, "max_mtime": round(mx, 3)}
    except OSError:
        return {}


def carica_indice(rifai: bool = False) -> dict:
    ""







    impronta = _impronta_store()
    if not rifai and INDICE.exists():
        try:
            d = json.loads(INDICE.read_text())
            if isinstance(d, dict) and d.get("_impronta") == impronta:
                return d.get("_idx") or {}
        except Exception:  # noqa: BLE001
            pass
    idx = costruisci_indice()
    INDICE.parent.mkdir(parents=True, exist_ok=True)
    INDICE.write_text(json.dumps({"_impronta": impronta, "_idx": idx}))
    return idx


def risolvi(nome: str, idx: dict) -> list[str]:
    ""










    k = _norm(nome)
    if k in idx:
        return idx[k]
    parole = {w for w in k.split() if len(w) >= 4}
    if not parole:
        return []
    fuori: list[str] = []
    for chiave, files in idx.items():
        pc = set(chiave.split())

        if parole & pc:
            fuori.extend(files)
        if len(fuori) > 60:
            break
    return list(dict.fromkeys(fuori))








TUTTO = [False]

_CACHE: dict[str, dict | None] = {}







_CACHE_BYTE_MAX = 64 * 1024 * 1024
_cache_byte = 0










_ENTITA_GRANDE = 4 * 1024 * 1024


def _carica_grande(nome_file: str, tutto: bool = False) -> dict | None:
    ""




































    percorso = PERSON / nome_file
    stato: list[dict] = []
    eventi: list[dict] = []
    testa: dict = {}
    n_eventi = 0


    finestra = 10_000 if not tutto else 10**9

    def _aggiungi(f: dict) -> None:
        nonlocal n_eventi
        if classe_attributo(f.get("attribute", "")) == "stato":
            stato.append(f)
            return
        n_eventi += 1
        eventi.append(f)
        if len(eventi) > finestra * 2:

            eventi.sort(key=_ordine, reverse=True)
            del eventi[finestra:]

    try:
        with open(percorso, encoding="utf-8") as fh:
            inizio = fh.read(4096)
            for chiave in ("entity_id", "entity_type", "canonical_name"):
                m = re.search(rf'"{chiave}"\s*:\s*"([^"]*)"', inizio)
                if m:
                    testa[chiave] = m.group(1)

            fh.seek(0)
            dentro = False
            prof = 0
            buf: list[str] = []
            coda: list[str] = []
            in_str = False
            esc = False
            while True:
                blocco = fh.read(1024 * 1024)
                if not blocco:
                    break
                for ch in blocco:
                    if not dentro:
                        coda.append(ch)
                        if len(coda) > 16:
                            del coda[:8]
                        if '"facts"' in "".join(coda):
                            dentro = True
                            coda = []
                        continue
                    if in_str:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_str = False
                        buf.append(ch)
                        continue
                    if ch == '"':
                        in_str = True
                        buf.append(ch)
                        continue
                    if ch == "{":
                        prof += 1
                        buf.append(ch)
                        continue
                    if ch == "}":
                        prof -= 1
                        buf.append(ch)
                        if prof == 0:
                            try:
                                f = json.loads("".join(buf))
                            except Exception:  # noqa: BLE001
                                f = None
                            buf = []
                            if isinstance(f, dict):
                                _aggiungi(f)
                        continue
                    if prof > 0:
                        buf.append(ch)
                    elif ch == "]":
                        dentro = False
    except OSError:
        return None

    if not stato and not eventi:
        return None






    eventi.sort(key=_ordine, reverse=True)
    if len(eventi) > finestra:
        per_anno: dict[str, list[dict]] = {}
        for f in eventi:
            per_anno.setdefault(_quando(f)[:4] or "?", []).append(f)
        quota = max(200, finestra // max(len(per_anno), 1))
        tenuti: list[dict] = []
        for anno in sorted(per_anno, reverse=True):
            tenuti.extend(per_anno[anno][:quota])

        visti = {id(x) for x in tenuti}
        for f in eventi:
            if len(tenuti) >= finestra:
                break
            if id(f) not in visti:
                tenuti.append(f)
        eventi = tenuti[:finestra]
    scartati = max(0, n_eventi - len(eventi[:finestra]))
    testa["facts"] = stato + eventi[:finestra]
    testa["_parziale"] = {
        "stato": len(stato),
        "eventi_totali": n_eventi,
        "eventi_tenuti": min(n_eventi, finestra),
        "eventi_scartati": scartati,
        "nota": (
            "no trimming"
            if not scartati
            else f"{scartati} older events not loaded "
            f"(--all to get them, or read the file: {percorso})"
        ),
    }
    return testa


def _giorno(s) -> date | None:
    ""

    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _quando(f: dict) -> str:
    ""
    return str(f.get("valid_from") or f.get("created_at") or "")[:10]


def _ordine(f: dict) -> tuple:
    ""











    vf = str(f.get("valid_from") or "")[:10]
    ca = str(f.get("created_at") or "")[:10]
    return (1 if vf else 0, vf or ca)


def _carica(nome_file: str) -> dict | None:
    if nome_file in _CACHE:
        return _CACHE[nome_file]
    try:
        grande = (PERSON / nome_file).stat().st_size > _ENTITA_GRANDE
    except OSError:
        grande = False
    if grande:

        return _carica_grande(nome_file, tutto=TUTTO[0])
    try:
        d = json.loads((PERSON / nome_file).read_text())
    except Exception:  # noqa: BLE001
        d = None
    global _cache_byte
    try:
        peso = (PERSON / nome_file).stat().st_size
    except OSError:
        peso = 0


    if peso > _CACHE_BYTE_MAX // 4:
        return d
    if _cache_byte + peso > _CACHE_BYTE_MAX:
        _CACHE.clear()
        _cache_byte = 0
    _CACHE[nome_file] = d
    _cache_byte += peso
    return d


def chiedi(
    nome: str,
    idx: dict,
    as_of: date | None = None,
    verbose: bool = False,
    org: str | None = None,
) -> dict:






    if is_group_name(nome):
        return {
            "cercato": nome,
            "verdetto": "AMBIGUO",
            "non_so": [
                "the question names SEVERAL PEOPLE together: one verdict would apply to all, "
                "which is always wrong for at least one",
                "ask one person at a time, by their name",
            ],
            "ripara": ["type the group-records and split them with a tombstone (see roadmap)"],
        }

    cand = risolvi(nome, idx)
    if not cand:
        return {
            "cercato": nome,
            "verdetto": "IGNOTO",
            "non_so": [
                f"no entity with a name similar to «{nome}»",
                "the KB does not know this person: it doesn't mean they don't exist",
            ],
            "ripara": [
                "xs-manual-knowledge-ingest.py to add them"
            ],
        }

    singole, gruppi = [], []
    for c in cand[:40]:
        d = _carica(c)
        if not d:
            continue
        (gruppi if is_group_name(d.get("canonical_name") or "") else singole).append((c, d))

    if not singole and gruppi:
        return {
            "cercato": nome,
            "verdetto": "AMBIGUO",
            "non_so": [
                f"«{nome}» appears only inside {len(gruppi)} group-records "
                "(names that contain several people): there is no single entity",
                "the facts attached there are attributed to a set, not to them",
            ],
            "gruppi": [d.get("canonical_name") for _c, d in gruppi[:12]],
            "ripara": ["type the groups and split them with a tombstone (see roadmap)"],
        }

    if len(singole) > 1:

        esatti = [(c, d) for c, d in singole if _norm(d.get("canonical_name") or "") == _norm(nome)]
        if len(esatti) != 1:
            return {
                "cercato": nome,
                "verdetto": "AMBIGUO",
                "candidati": [d.get("canonical_name") for _c, d in singole[:12]],
                "non_so": [
                    f"{len(singole)} entities match «{nome}»",
                    "choosing silently would be the quickest way to answer about the wrong person",
                ],
                "ripara": ["re-run with the full name"],
            }
        singole = esatti

    _c, d = singole[0]








    if is_group_name(d.get("canonical_name") or ""):
        return {
            "cercato": nome,
            "trovato": d.get("canonical_name"),
            "entity_id": d.get("entity_id"),
            "verdetto": "AMBIGUO",
            "non_so": [
                "this entity contains SEVERAL PEOPLE in one name: a verdict here "
                "would apply to all of them together, which is always wrong for at least one",
                f"the {len(d.get('facts') or [])} facts attached here are attributed to a set",
            ],
            "gruppi": [d.get("canonical_name")],
            "ripara": ["type the groups and split them with a tombstone (see roadmap)"],
        }

    fatti = d.get("facts") or []
    v = verdetto_stato(fatti, as_of, org)

    out = {
        "cercato": nome,
        "trovato": d.get("canonical_name"),
        "entity_id": d.get("entity_id"),
        **v.to_dict(),
        "verdetto": v.esito,
    }
    out.pop("esito", None)






    if v.esito == "IGNOTO":
        eventi = [
            f
            for f in fatti
            if isinstance(f, dict) and classe_attributo(f.get("attribute", "")) == "evento"
        ]
        if eventi:
            piu_recente = max(
                eventi, key=lambda x: str(x.get("valid_from") or x.get("created_at") or "")
            )
            quando = str(piu_recente.get("valid_from") or piu_recente.get("created_at") or "")[:10]
            out["so_pero"] = {
                "ultimo_evento": {
                    "quando": quando,
                    "attributo": piu_recente.get("attribute"),
                    "valore": str(piu_recente.get("value"))[:100],
                    "fonte": (piu_recente.get("source") or {}).get("source_type"),
                },
                "eventi_totali": len(eventi),
                "avvertenza": "the events say it was talked about, not that they're still in",
            }


    if gruppi:
        n_fatti = sum(len(g.get("facts") or []) for _c, g in gruppi)
        out.setdefault("non_so", []).append(
            f"{len(gruppi)} group-records carry this name ({n_fatti} facts): "
            "they are not counted in the claim"
        )
        out["gruppi"] = [g.get("canonical_name") for _c, g in gruppi[:12]]





    if d.get("_parziale", {}).get("eventi_scartati"):
        p_ = d["_parziale"]
        out.setdefault("non_so", []).append(
            f"read {p_['eventi_tenuti']} events out of {p_['eventi_totali']} "
            f"(the most recent, with a quota per year): "
            f"{p_['eventi_scartati']} older ones were not loaded — `--all` to get them"
        )
        out["parziale"] = p_





    try:
        con_ = conoscenza(out.get("entity_id"), fatti)
        if con_.ruoli:
            out["ruoli"] = con_.ruoli
            out["prove_ruoli"] = con_.prove
            for s in con_.non_so:
                if s not in (out.get("non_so") or []):
                    out.setdefault("non_so", []).append(s)
            for s in con_.ripara:
                if s not in (out.get("ripara") or []):
                    out.setdefault("ripara", []).append(s)
    except Exception as e:  # pragma: no cover — one extra view must not bring down the answer
        if os.environ.get("SB_WHO_DEBUG"):
            raise
        out.setdefault("non_so", []).append(f"roles not computed: {type(e).__name__}")

    if verbose:
        eventi = [f for f in fatti if classe_attributo(f.get("attribute", "")) == "evento"]
        out["eventi_recenti"] = [
            {
                "attributo": f.get("attribute"),
                "valore": str(f.get("value"))[:90],
                "quando": str(f.get("valid_from") or "")[:10],
            }
            for f in sorted(eventi, key=lambda x: str(x.get("valid_from") or ""), reverse=True)[:8]
        ]
        out["fatti_totali"] = len(fatti)
    return out


def stampa(r: dict) -> None:
    nome = r.get("trovato") or r.get("cercato")
    print(f"\n{nome} → {r['verdetto']}")
    if r.get("claim"):
        conf = f" (conf {r['confidenza']:.2f})" if r.get("confidenza") is not None else ""
        print(f"  claim   : {r['claim']} = {r.get('valore')}{conf}")
    if r.get("quando"):
        gg = f" · {r['giorni']} days ago" if r.get("giorni") is not None else ""
        fonte = f" · source {r['fonte']}" if r.get("fonte") else ""
        print(f"  when    : {r['quando']}{gg}{fonte}")




    if r.get("visto"):
        eta = ""
        d_ = _giorno(r["visto"])
        if d_:
            eta = f" · {(date.today() - d_).days} days ago"
        print(
            f"  seen    : {r['visto']}{eta} (our clock: when this "
            f"provenance arrived — it does not refresh on every re-read)"
        )
    if r.get("ruoli"):
        print(f"  role    : {' + '.join(r['ruoli'])}")
        for k, v in (r.get("prove_ruoli") or {}).items():
            print(f"            {k}: {v}")
    non_so = r.get("non_so") or ["no reservation stated"]
    print(f"  unknown : {non_so[0]}")
    for x in non_so[1:]:
        print(f"            {x}")
    for x in r.get("candidati") or []:
        print(f"            · {x}")
    for x in r.get("gruppi") or []:
        print(f"            [GROUP] {x}")
    sp = r.get("so_pero")
    if sp:
        e = sp["ultimo_evento"]
        print(
            f"  but know: it was last mentioned on {e['quando'] or '?'} · {e['attributo']}"
        )
        print(
            f"           {e['valore'][:80]}  (source {e['fonte']}, {sp['eventi_totali']} events in total)"
        )
        print(f"           ⚠️  {sp['avvertenza']}")
    for i, x in enumerate(r.get("ripara") or []):
        print(f"  {'fix     ' if i == 0 else '        '}: {x}")
    if r.get("eventi_recenti"):
        print("  events  : (they don't answer «now», they're history)")
        for e in r["eventi_recenti"]:
            print(f"            {e['quando'] or '        '}  {e['attributo']}: {e['valore'][:70]}")




GOLDEN = [

    ("Quinn Hart", {"CHIUSO"}),


    ("Noah Webb", {"CHIUSO"}),


    # you (sbk.config.json "owner"), when set
    *([(cfg.OWNER_NAME, {"DENTRO", "STALE", "APERTO-NON-VERIFICABILE", "IGNOTO"})] if cfg.OWNER_NAME else []),

    ("Sam Monroe", {"IGNOTO", "AMBIGUO", "DENTRO", "STALE", "APERTO-NON-VERIFICABILE"}),

    ("Zxqwerty Nonesiste", {"IGNOTO"}),
]


























PERSONIO = cfg.DATA_ROOT / "personio" / "employees-flat.json"
CLICKUP = cfg.DATA_ROOT / "clickup-members-cache.json"
TOP150 = cfg.DATA_ROOT / "rq" / "top-150-people.json"



PER_GRUPPO = 60
SEME_COLLAUDO = 11


def _righe(p: Path, chiavi=("employees", "members", "users", "people", "rows")) -> list:
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return []
    if isinstance(d, list):
        return d
    for k in chiavi:
        if isinstance(d.get(k), list):
            return d[k]
    return []


def _nome_di(r) -> str:
    if not isinstance(r, dict):
        return str(r or "")
    n = " ".join(str(x) for x in (r.get("first_name"), r.get("last_name")) if x)
    return n or str(r.get("name") or r.get("username") or r.get("full_name") or "")


def _campiona(righe: list, n: int) -> list:
    import random

    if len(righe) <= n:
        return righe
    return random.Random(SEME_COLLAUDO).sample(righe, n)


def _g1_personio(idx: dict) -> tuple[dict, list, int]:
    ""
    conta: dict[str, dict[str, int]] = {}
    male: list[tuple[str, str, str]] = []
    righe = _campiona(_righe(PERSONIO), PER_GRUPPO)
    for r in righe:
        nome = _nome_di(r)
        if not nome:
            continue
        atteso = (
            "uscito" if str(r.get("status", "")).lower() not in ("active", "attivo") else "attivo"
        )
        v = chiedi(nome, idx)["verdetto"]
        conta.setdefault(atteso, {}).setdefault(v, 0)
        conta[atteso][v] += 1
        if (atteso == "attivo" and v == "CHIUSO") or (atteso == "uscito" and v == "DENTRO"):
            male.append((nome, atteso, v))
    return conta, male, len(righe)


def _g2_clickup(idx: dict) -> tuple[int, list]:
    ""
    male = []
    righe = _campiona(_righe(CLICKUP), PER_GRUPPO)
    for r in righe:
        nome = _nome_di(r)
        if not nome:
            continue
        v = chiedi(nome, idx)["verdetto"]
        if v == "CHIUSO":
            male.append((nome, v))
    return len(righe), male


def _g3_rilevanti(idx: dict) -> dict:
    ""
    c: dict[str, int] = {}
    con_evento = 0
    righe = _campiona(_righe(TOP150), PER_GRUPPO)
    for r in righe:
        nome = _nome_di(r)
        if not nome:
            continue
        res = chiedi(nome, idx)
        v = res["verdetto"]
        c[v] = c.get(v, 0) + 1
        if v == "IGNOTO" and res.get("so_pero"):
            con_evento += 1
    return {"n": len(righe), "verdetti": c, "ignoti_con_evento": con_evento}



_AZIENDA = re.compile(
    r"(?i)\b(s\.?r\.?l|s\.?p\.?a|gmbh|ltd|inc|llc|holding|group|agency|studio|co\.)\b"
)


def _g4_misto(idx: dict) -> tuple[dict, list]:
    ""







    import random

    rnd = random.Random(SEME_COLLAUDO)
    nomi = os.listdir(PERSON)
    gruppi, aziende, scarni, veri = [], [], [], []
    for n in rnd.sample(nomi, min(4000, len(nomi))):
        if len(gruppi) >= 15 and len(aziende) >= 15 and len(scarni) >= 15 and len(veri) >= 15:
            break
        d = _carica(n)
        if not d:
            continue
        nome = d.get("canonical_name") or ""
        if not nome:
            continue
        nf = len(d.get("facts") or [])
        if is_group_name(nome):
            if len(gruppi) < 15:
                gruppi.append(nome)
        elif _AZIENDA.search(nome):
            if len(aziende) < 15:
                aziende.append(nome)
        elif nf <= 2:
            if len(scarni) < 15:
                scarni.append(nome)
        elif nf >= 20 and len(veri) < 15:
            veri.append(nome)

    esiti: dict[str, dict[str, int]] = {}
    violazioni: list[str] = []
    for etichetta, lista in (
        ("record-gruppo", gruppi),
        ("aziende-come-persone", aziende),
        ("record scarni", scarni),
        ("persone vere", veri),
    ):
        for nome in lista:
            v = chiedi(nome, idx)["verdetto"]
            esiti.setdefault(etichetta, {}).setdefault(v, 0)
            esiti[etichetta][v] += 1
            if etichetta == "record-gruppo" and v in ("DENTRO", "CHIUSO"):
                violazioni.append(f"group «{nome[:48]}» → {v}: blunt claim on several people")
            if etichetta == "aziende-come-persone" and v == "DENTRO":
                violazioni.append(f"company «{nome[:48]}» → DENTRO: not a person")
            if etichetta == "record scarni" and v in ("DENTRO", "CHIUSO"):
                violazioni.append(f"record with ≤2 facts «{nome[:40]}» → {v}: asserts on nothing")
    return esiti, violazioni


def selftest() -> int:
    idx = carica_indice()
    ko = 0
    print("── selftest: 5 golden cases + four groups of 60 ──")

    print("\n  [0] THE FIVE GOLDEN CASES")
    for nome, attesi in GOLDEN:
        v = chiedi(nome, idx)["verdetto"]
        ok = v in attesi
        print(
            f"      {'✅' if ok else '❌'} {nome:24} → {v:24} (expected: {'|'.join(sorted(attesi))})"
        )
        if not ok:
            ko += 1

    m, male, n1 = _g1_personio(idx)
    if m:
        print(f"\n  [1] PERSONIO ({n1}) — does it tell the truth? hard truth from HR")
        for atteso in sorted(m):
            n = sum(m[atteso].values())
            print(f"      declared «{atteso}» ({n}):")
            for v, c in sorted(m[atteso].items(), key=lambda x: -x[1]):
                grave = (atteso == "attivo" and v == "CHIUSO") or (
                    atteso == "uscito" and v == "DENTRO"
                )
                print(f"        {'🔴' if grave else '  '} {v:26} {c:4}  {100 * c / n:5.1f}%")
        if m.get("attivo", {}).get("CHIUSO", 0):
            print("      🔴 ACTIVE ones declared CLOSED — the costliest error")
            ko += 1
        if m.get("uscito", {}).get("DENTRO", 0):
            print(
                "      🟠 HR LEAVERS that show as DENTRO: the closure came from Personio"
            )
            print("         and was thrown away by the merge (xs-l2-knowledge-extract.py:1204-1207).")
            print("         It's not a defect of sb-who: it's the damage phase 2 must repair,")
            print("         and this number must GO DOWN.")
        for nome, atteso, v in male[:6]:
            print(f"         · {nome} — HR «{atteso}», sb-who «{v}»")

    n2, male2 = _g2_clickup(idx)
    if n2:
        print(f"\n  [2] CLICKUP MEMBERS ({n2}) — does it switch off who's on?")
        if male2:
            print(f"      🔴 {len(male2)} show as CLOSED while working with you now:")
            for nome, v in male2[:6]:
                print(f"         · {nome} → {v}")
            ko += 1
        else:
            print("      ✅ none show as CLOSED")

    u = _g3_rilevanti(idx)
    if u["n"]:
        print(f"\n  [3] TOP RELEVANCE ({u['n']}) — is it any use?")
        for v, c in sorted(u["verdetti"].items(), key=lambda x: -x[1]):
            print(f"        {v:26} {c:4}  {100 * c / u['n']:5.1f}%")
        ign = u["verdetti"].get("IGNOTO", 0)
        if ign:
            print(
                f"        of which {u['ignoti_con_evento']}/{ign} IGNOTO have a «but know» to show"
            )

    e4, viol = _g4_misto(idx)
    if e4:
        n4 = sum(sum(v.values()) for v in e4.values())
        print(f"\n  [4] MIXED ({n4}) — does it hold up to the real store's mess?")
        for etichetta in sorted(e4):
            n = sum(e4[etichetta].values())
            dettaglio = " · ".join(
                f"{v} {c}" for v, c in sorted(e4[etichetta].items(), key=lambda x: -x[1])
            )
            print(f"        {etichetta:24} ({n:2}): {dettaglio}")
        if viol:
            print(f"      🔴 {len(viol)} behavior violations:")
            for x in viol[:8]:
                print(f"         · {x}")
            ko += 1
        else:
            print("      ✅ no blunt claim on groups, companies or empty records")

    cr = closure_rate()
    vivi = {k: v for k, v in cr.items() if v > 0}
    print(f"\n  channels that can close: {len(vivi)}/{len(cr)}")
    if len(vivi) <= 1:
        print("  ⚠️  as long as it's 1, «DENTRO» can't be uttered and that's fine:")
        print("      the verdict promotes itself when phase 2 repairs the merge.")
    return 1 if ko else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="who is X, what they do now, are they still in")
    ap.add_argument("nome", nargs="?", help="the person's name")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="groups and events too")
    ap.add_argument("--as-of", help="what was true on this date (YYYY-MM-DD)")
    ap.add_argument(
        "--org", help="in WHERE: filters the facts that name this organization"
    )
    ap.add_argument("--reindex", action="store_true", help="rebuilds the name index")
    # Older Italian name, kept as a hidden alias.
    ap.add_argument("--tutto", dest="tutto", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--all",
        dest="tutto",
        action="store_true",
        help="load EVERY fact even on huge entities (for deep searches: "
        "it costs memory, and without this the answer declares how many it discarded)",
    )
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if not PERSON.is_dir():
        print(f"knowledge store missing: {PERSON}", file=sys.stderr)
        return 2
    if a.selftest:
        return selftest()
    if not a.nome and not a.reindex:
        ap.print_help()
        return 2

    TUTTO[0] = a.tutto
    idx = carica_indice(rifai=a.reindex)
    if a.reindex and not a.nome:
        print(f"index rebuilt: {len(idx)} keys → {INDICE}")
        return 0

    as_of = date.fromisoformat(a.as_of) if a.as_of else None
    r = chiedi(a.nome, idx, as_of, a.verbose, a.org)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        stampa(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
