#!/usr/bin/env python3
""













































from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from conteggio import Conteggio, FileIlleggibile  # noqa: E402



RATCHET = REPO / "docs" / "sbk" / "audits" / "RATCHET.json"











CANDIDATO_NOME = "RATCHET-CANDIDATO.json"
CANDIDATO = REPO / "docs" / "sbk" / "audits" / CANDIDATO_NOME


def _candidato() -> Path:
    ""










    return RATCHET.with_name(CANDIDATO_NOME)










VERSO = {






    "entita": None,
    "fatti": None,
    "persone_provate_pct": "su",
    "non_persone_pct": "giu",
    "non_persone": "giu",



    "compositi": None,
    "ha_puntatore_pct": "su",
    "ha_puntatore": "su",
    "collegate_pct": "su",
    "fatti_di_stato": None,
    "senza_nome": "giu",
}





























TOLLERANZA_PUNTI = {
    "non_persone": 0.05,
    "ha_puntatore": 0.05,
    "senza_nome": 0.0,
}














CHE_NON_SCENDONO = ("entita",)


def entita_sparite(nuovo: dict, vecchio: dict) -> list[str]:
    ""
    per_prima = (vecchio or {}).get("numeri", {})
    fuori = []
    for k in CHE_NON_SCENDONO:
        v_nuovo, v_vecchio = nuovo.get(k), per_prima.get(k)
        if v_nuovo is None or v_vecchio is None:
            continue
        a = Conteggio.da_dict(v_vecchio).valore if isinstance(v_vecchio, dict) else v_vecchio
        b = Conteggio.da_dict(v_nuovo).valore if isinstance(v_nuovo, dict) else v_nuovo
        if isinstance(a, int) and isinstance(b, int) and b < a:
            fuori.append(f"{k}: {a:,} → {b:,}  (−{a - b:,})")
    return fuori


def misura(tollera_illeggibili: bool = False) -> dict:
    ""














    import sbk_config as cfg

    K = cfg.DATA_ROOT / "knowledge" / "entities"
    if not K.exists():
        return {}
    import knowledge_view as kv








    if not kv._riconoscitore_gruppi():
        raise RuntimeError(
            "the group-name recognizer (tools/cross-source/xs-l3-knows-query.py) "
            "does not load with this interpreter: compositi and non_persone would come out at zero. "
            "Run sb-ratchet with the repo interpreter (uv run) or with a python3 that has pyarrow."
        )

    n_ent = n_fatti = senza_nome = compositi = ancorati = 0
    compositi_persone = 0
    n_file = illeggibili = 0
    classi: collections.Counter = collections.Counter()
    per_cartella: collections.Counter = collections.Counter()
    for cartella in sorted(K.iterdir()):
        if not cartella.is_dir():
            continue
        for f in cartella.glob("*.json"):
            n_file += 1
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:



                if not tollera_illeggibili:
                    raise FileIlleggibile(
                        f"{f} cannot be read ({exc}). To measure anyway: "
                        f"misura(tollera_illeggibili=True), and the file ends up in the skipped ones."
                    ) from exc
                illeggibili += 1
                continue
            n_ent += 1
            per_cartella[cartella.name] += 1
            nome = (d.get("canonical_name") or "").strip()
            if not nome:
                senza_nome += 1
            elif kv.is_group_name(nome):
                compositi += 1














                if cartella.name == "person":
                    compositi_persone += 1

















            for x in d.get("facts") or []:
                n_fatti += 1
                classi[kv.classe_attributo(x.get("attribute") or "")] += 1
                if str((x.get("source") or {}).get("record_id") or "").strip():
                    ancorati += 1
            del d
    persone = per_cartella.get("person", 0)



    saltati = {"unreadable json": illeggibili}

    def _c(valore: int, su: int) -> dict:
        return Conteggio(valore=valore, su=su, saltati=saltati).come_dict()

    return {












        "entita": _c(n_ent, n_file),
        "fatti": _c(n_fatti, n_ent),
        "compositi": _c(compositi, n_ent),
        "senza_nome": _c(senza_nome, n_ent),
















        "ha_puntatore": _c(ancorati, n_fatti),
        "fatti_di_stato": _c(classi.get("stato", 0), n_fatti),


        "non_persone": _c(compositi_persone, persone),
    }







def _adesso_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _quando_ultima_estrazione() -> str:
    import sbk_config as cfg

    p = cfg.DATA_ROOT / "knowledge" / "meta" / "last-extraction.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("last_extraction", "")
    except (OSError, ValueError):
        return ""


def _quando_misurato_dall_estrazione() -> str:
    ""











    import sbk_config as cfg

    p = cfg.DATA_ROOT / "knowledge" / "meta" / "last-extraction.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return str((((d.get("stats") or {}).get("ratchet")) or {}).get("quando") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def carica() -> dict:
    try:
        return json.loads(RATCHET.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def carica_candidato() -> dict:
    try:
        return json.loads(_candidato().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def candidato_pendente() -> dict:
    ""







    cand = carica_candidato()
    if not cand:
        return {}
    base = carica().get("quando", "")
    return {} if base and base >= cand.get("quando", "") else cand


def scrivi_misura(
    numeri: dict, peggiorati: list, firma: str = "", base: dict | None = None
) -> Path:
    ""

















    quando = _adesso_iso()
    if peggiorati and not firma:
        dove, corpo = (
            _candidato(),
            {
                "quando": quando,
                "peggiorati": list(peggiorati),
                "perche_qui": (
                    "measure that WORSENS: the base stays put until the regression "
                    'is signed with `sb-ratchet.py --scrivi --firma "reason"`'
                ),
                "numeri": numeri,
            },
        )
    elif firma:
        dove, corpo = (
            RATCHET,
            {
                "quando": quando,
                "firma": firma,
                "regressione_firmata": list(peggiorati),
                "numeri": numeri,
            },
        )
    else:
        migliori, tenuti = _base_migliore(numeri, carica() if base is None else base)
        dove, corpo = RATCHET, {"quando": quando, "numeri": migliori}
        if tenuti:
            corpo["dentro_la_banda"] = {k: numeri[k] for k in tenuti}
    dove.parent.mkdir(parents=True, exist_ok=True)
    dove.write_text(
        json.dumps(corpo, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return dove


def _mostra(v) -> str:
    ""
    if isinstance(v, dict) and "valore" in v:
        return str(Conteggio.da_dict(v))
    return f"{v:,}" if isinstance(v, int) else str(v)


def _confrontabili(nuovo, vecchio):
    ""
















    n_dict = isinstance(nuovo, dict) and "valore" in nuovo
    v_dict = isinstance(vecchio, dict) and "valore" in vecchio
    if n_dict and Conteggio.da_dict(nuovo).parziale:
        return None
    if n_dict and v_dict:
        a, b = Conteggio.da_dict(vecchio), Conteggio.da_dict(nuovo)
        if a.quota is None or b.quota is None:
            return None
        return (a.quota, b.quota, *_percentuali_che_si_distinguono(a.quota, b.quota), True)
    if n_dict != v_dict:
        a = Conteggio.da_dict(vecchio).valore if v_dict else vecchio
        b = Conteggio.da_dict(nuovo).valore if n_dict else nuovo
        return a, b, f"{a}", f"{b}", False
    return vecchio, nuovo, f"{vecchio}", f"{nuovo}", False


def _percentuali_che_si_distinguono(a: float, b: float) -> tuple[str, str]:
    ""





    for cifre in (2, 4, 6):
        if round(a * 100, cifre) != round(b * 100, cifre):
            break
    return f"{round(a * 100, cifre)}%", f"{round(b * 100, cifre)}%"


def giudica(nuovo: dict, vecchio: dict) -> dict:
    ""






    peggio, meglio, banda = [], [], []
    per_prima = (vecchio or {}).get("numeri", {})
    for k, v in nuovo.items():
        verso = VERSO.get(k)
        if verso is None or k not in per_prima:
            continue
        coppia = _confrontabili(v, per_prima[k])
        if coppia is None:
            continue
        prima, dopo, s_prima, s_dopo, quota = coppia
        if dopo == prima:
            continue
        salito = dopo > prima
        riga = f"{k}: {s_prima} → {s_dopo}"
        if salito == (verso == "su"):
            meglio.append(riga)
            continue
        if not quota:
            peggio.append(riga)
            continue
        scarto = abs(dopo - prima) * 100
        tolleranza = TOLLERANZA_PUNTI.get(k, 0.0)
        riga += f" ({'+' if salito else '−'}{scarto:.4f} points, tolerance {tolleranza})"
        (banda if scarto <= tolleranza else peggio).append(riga)
    return {"peggiorati": peggio, "migliorati": meglio, "entro_tolleranza": banda}


def confronta(nuovo: dict, vecchio: dict) -> tuple[list[str], list[str]]:
    ""
    g = giudica(nuovo, vecchio)
    return g["peggiorati"], g["migliorati"]


def _base_migliore(nuovo: dict, vecchio: dict) -> tuple[dict, list[str]]:
    ""









    per_prima = (vecchio or {}).get("numeri", {})
    fuori, tenuti = dict(nuovo), []
    for k, v in nuovo.items():
        verso = VERSO.get(k)
        if verso is None or k not in per_prima:
            continue
        coppia = _confrontabili(v, per_prima[k])
        if coppia is None:
            continue
        prima, dopo = coppia[0], coppia[1]
        if dopo != prima and (dopo > prima) != (verso == "su"):
            fuori[k] = per_prima[k]
            tenuti.append(k)
    return fuori, tenuti


def parziali(numeri: dict) -> list[str]:
    ""

    fuori = []
    for k, v in numeri.items():
        if isinstance(v, dict) and "valore" in v and Conteggio.da_dict(v).parziale:
            fuori.append(f"{k}: {_mostra(v)}")
    return fuori


def main() -> int:
    ap = argparse.ArgumentParser(description="The seven KB numbers, like a diff")
    ap.add_argument("--scrivi", action="store_true", help="update RATCHET.json")
    ap.add_argument(
        "--firma",
        default="",
        metavar="MOTIVO",
        help=(
            "accept a MEASURED regression and write it as the new base, with the reason "
            "inside the versioned file. Without it, a measure that worsens ends up in "
            "RATCHET-CANDIDATO.json and the base stays put."
        ),
    )
    ap.add_argument(
        "--controlla",
        action="store_true",
        help=(
            "gate: red if a number worsens beyond its tolerance, or if the last "
            "extraction did not take its measure"
        ),
    )
    a = ap.parse_args()

    vecchio = carica()





    if a.controlla:






        pendente = candidato_pendente()
        if pendente:
            print(
                "❌ a KB measure WORSENS and is not signed:\n"
                f"     {' · '.join(pendente.get('peggiorati') or ['(no detail)'])}\n"
                f"     measured on {str(pendente.get('quando', ''))[:19]}, "
                f"in {CANDIDATO_NOME}\n"
                "   The base was NOT touched. Two paths, both explicit:\n"
                "     1. fix the regression, then:  sb-ratchet.py --scrivi\n"
                '     2. accept it:  sb-ratchet.py --scrivi --firma "reason it is fine"'
            )
            return 1
        estratto = _quando_ultima_estrazione()
        misurato = vecchio.get("quando", "")




        sua = _quando_misurato_dall_estrazione()
        if estratto and misurato and estratto > misurato and not (sua and sua <= misurato):
            print(
                "❌ the KB measure is older than the last extraction:\n"
                f"     extraction  {estratto[:19]}\n"
                f"     measure     {misurato[:19]}\n"
                "   The extraction ran and the guard did not speak. Re-measure:\n"
                "     uv run python tools/util/sb-ratchet.py --scrivi"
            )
            return 1
        if not vecchio:
            print("❌ no measure: uv run python tools/util/sb-ratchet.py --scrivi")
            return 1





        print(f"✓ KB measure from {misurato[:19]}, no longer older than the extraction")





    nuovo = misura(tollera_illeggibili=True)
    if not nuovo:
        print("store not found")
        return 0
    giudizio = giudica(nuovo, vecchio)
    peggio, meglio = giudizio["peggiorati"], giudizio["migliorati"]
    incompleti = parziali(nuovo)
    sparite = entita_sparite(nuovo, vecchio)

    for k, v in ({} if (a.controlla and not a.scrivi) else nuovo).items():
        prima = vecchio.get("numeri", {}).get(k)
        delta = "" if prima is None or prima == v else f"   (was {_mostra(prima)})"
        print(f"  {k:22} {_mostra(v):>26}{delta}")





    saltato_davvero = any(
        isinstance(v, dict) and any((v.get("saltati") or {}).values()) for v in nuovo.values()
    )
    if incompleti:


        print("\n⚠️  PARTIAL measure, not compared: " + " · ".join(incompleti))
    if saltato_davvero and a.controlla and not a.scrivi:
        print("\nrepair the files that cannot be read, then re-measure: sb-ratchet.py --scrivi")
        return 1



    if sparite:
        print("\n❌ ENTITIES GONE from the store: " + " · ".join(sparite))
        print(
            "   A renamed profile (.corrotto) drops out of the glob and this counter\n"
            "   is the only one that notices — the quota does not, they drop together.\n"
            "   Restore:  uv run python tools/util/sb-kb-ripara.py --entita <id>\n"
            "   If the drop is INTENDED, SIGN it:\n"
            '     sb-ratchet.py --scrivi --firma "reason"'
        )
        if a.controlla and not a.scrivi:
            return 1
    if meglio:
        print("\n✓ improved: " + " · ".join(meglio))
    if giudizio["entro_tolleranza"]:


        print(
            "\n· in the wrong direction but inside the band: "
            + " · ".join(giudizio["entro_tolleranza"])
        )
    if peggio:
        print("\n⚠️  WORSENED: " + " · ".join(peggio))





        if a.controlla and not a.scrivi:



            print(
                "\nif the regression is intended, SIGN it, and the reason stays in the file:\n"
                '   uv run python tools/util/sb-ratchet.py --scrivi --firma "reason it is fine"\n'
                "   (`--scrivi` alone is no longer enough: it writes "
                f"{CANDIDATO_NOME} and leaves the base in place)"
            )
            return 1

    if a.scrivi:













        scritto = scrivi_misura(nuovo, peggio + sparite, firma=a.firma, base=vecchio)
        try:
            dove = scritto.relative_to(REPO)
        except ValueError:
            dove = scritto
        if scritto == _candidato():
            print(
                f"\n⛔ base NOT updated: the measure worsens and is not signed.\n"
                f"   wrote {dove} — the diff says what worsened.\n"
                '   To accept it:  sb-ratchet.py --scrivi --firma "reason"'
            )
            return 1
        if a.firma:
            print(f"\nwrote {dove} — regression SIGNED: {a.firma}")
        else:
            print(f"\nwrote {dove} — the diff is the measure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
