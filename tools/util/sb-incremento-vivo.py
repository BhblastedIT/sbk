#!/usr/bin/env python3
""
































































from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INCREMENTO_PY = REPO / "tools" / "cross-source" / "incremento.py"
REGISTRO = REPO / "docs" / "sbk" / "audits" / "INCREMENTO.json"
STORE = Path.home() / ".sbk-data" / "knowledge"



RUN_LOG = STORE / "quality-metrics"





def carica_incremento():
    ""
    if not INCREMENTO_PY.exists():
        raise FileNotFoundError(f"{INCREMENTO_PY} does not exist")
    spec = importlib.util.spec_from_file_location("incremento", INCREMENTO_PY)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"{INCREMENTO_PY} not importable")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["incremento"] = mod
    spec.loader.exec_module(mod)
    return mod





def _fatto(fid, attributo, valore, sorgente="email"):
    return {
        "fact_id": fid,
        "attribute": attributo,
        "value": valore,
        "confidence": 0.8,
        "source": {"source_type": sorgente, "source_file": f"{sorgente}/{fid}.json"},
    }


def semina(radice: Path, mod) -> None:
    ""
    (radice / "entities" / "person").mkdir(parents=True, exist_ok=True)
    (radice / "archive" / "merged").mkdir(parents=True, exist_ok=True)
    a = {
        "entity_id": "person_00000000",
        "entity_type": "person",
        "identity": {"name": "Alex Rossi (Globex)"},
        "facts": [
            _fatto("00000000-0000-0000-0000-000000000000", "identity.name", "Alex Rossi"),
            _fatto("00000000-0000-0000-0000-000000000000", "work.role", "CFO"),
        ],
    }
    b = {
        "entity_id": "person_00000000",
        "entity_type": "person",
        "identity": {"name": "A. Rossi"},
        "facts": [
            _fatto("00000000-0000-0000-0000-000000000000", "work.company", "Globex", "attio"),
            _fatto(
                "00000000-0000-0000-0000-000000000000", "identity.name", "Alex Rossi", "attio"
            ),
        ],
    }
    mod.scrivi_entita(radice / "entities" / "person" / "person_00000000.json", a)
    mod.scrivi_entita(radice / "entities" / "person" / "person_00000000.json", b)


def fai_la_fusione(radice: Path, mod, *, motivo="pre-commit decoy"):
    ""





    pa = radice / "entities" / "person" / "person_00000000.json"
    pb = radice / "entities" / "person" / "person_00000000.json"
    arch = radice / "archive" / "merged" / "person_00000000.json"
    a = json.loads(pa.read_text(encoding="utf-8"))
    b = json.loads(pb.read_text(encoding="utf-8"))

    with mod.Incremento(
        "esca-incremento-vivo",
        motivo_run=motivo,
        radice=radice,
        operatore="pre-commit",
    ) as inc:
        spostato = b["facts"][0]
        scartato = b["facts"][1]
        inc.sposta_fatto(spostato, da="person_00000000", a="person_00000000", indice=0)
        inc.scarta_fatto(
            scartato, da="person_00000000", perche="duplicate (attribute, value)", indice=1
        )
        inc.modifica_campo(
            entity_id="person_00000000",
            campo="identity.name",
            prima=a["identity"]["name"],
            dopo="Alex Rossi",
            motivo="canonical name after merge",
        )
        inc.archivia_entita("person_00000000", percorso=pb, percorso_archivio=arch)
        inc.punto_fermo()

        a["facts"].append(dict(spostato, source_entity_id="person_00000000"))
        a["identity"]["name"] = "Alex Rossi"
        mod.scrivi_entita(pa, a)
        arch.write_text(pb.read_text(encoding="utf-8"), encoding="utf-8")
        pb.unlink()
    return inc


def _righe(percorso: Path):
    return [json.loads(r) for r in percorso.read_text(encoding="utf-8").splitlines() if r.strip()]


def _riscrivi(percorso: Path, righe):
    percorso.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in righe), encoding="utf-8"
    )





def prova_giro(mod, base: Path) -> list:
    ""
    errori = []
    radice = base / "giro" / "knowledge"
    semina(radice, mod)
    prima = mod.impronta_store(radice)
    inc = fai_la_fusione(radice, mod)

    if mod.impronta_store(radice) == prima:
        errori.append("the run: the mutation did not change the store (useless test)")
    righe = _righe(inc.percorso)
    if not righe or righe[0].get("tipo") != "inizio":
        errori.append("the run: the header line is missing")
    if not righe or righe[-1].get("tipo") != "fine":
        errori.append("the run: the closing seal is missing")
    for campo in ("script", "versione", "argv", "operatore", "motivo_run", "quando"):
        if campo not in (righe[0] if righe else {}):
            errori.append(f"the run: the header does not carry `{campo}`")
    op = [r for r in righe if r.get("tipo") == "op"]
    if len(op) != 4:
        errori.append(f"the run: 4 recorded ops expected, found {len(op)}")

    rapporto = mod.disfa(inc.incremento_id, radice=radice, apply=True)
    if rapporto["esito"] != "disfatto":
        errori.append(f"the run: the inversion did not undo ({rapporto['esito']})")
    dopo = mod.impronta_store(radice)
    if dopo != prima:
        errori.append(f"the run: the store did NOT return byte for byte ({prima} → {dopo})")

    if not rapporto.get("incremento_prodotto"):
        errori.append("the run: the inversion did not produce its own increment")
    return errori


def prova_esche(mod, base: Path) -> list:
    ""
    errori = []

    def apparecchia(nome):
        radice = base / nome / "knowledge"
        semina(radice, mod)
        prima = mod.impronta_store(radice)
        inc = fai_la_fusione(radice, mod)
        return radice, prima, inc


    radice, prima, inc = apparecchia("esca1")
    righe = _righe(inc.percorso)
    for r in righe:
        if r.get("op") == "archivia_entita":
            testo = json.loads(r["prima_testo"])
            testo["identity"]["name"] = "TAMPERED NAME"
            r["prima_testo"] = json.dumps(testo, ensure_ascii=False, indent=2)
    _riscrivi(inc.percorso, righe)
    rap = mod.disfa(inc.incremento_id, radice=radice, apply=True)
    if rap["esito"] != "rifiutato":
        errori.append("DECOY 1 did not trip: a tampered `prima` was restored anyway")
    elif "sha256" not in json.dumps(rap.get("motivi") or []):
        errori.append("DECOY 1: rejected, but not for the hash mismatch of the prima")


    radice, prima, inc = apparecchia("esca2")
    pa = radice / "entities" / "person" / "person_00000000.json"
    a = json.loads(pa.read_text(encoding="utf-8"))
    a["identity"]["name"] = "someone else wrote afterwards"
    mod.scrivi_entita(pa, a)
    rap = mod.disfa(inc.incremento_id, radice=radice, apply=True)
    if rap["esito"] != "rifiutato":
        errori.append("DECOY 2 did not trip: inverted a history that is not the recorded one")


    radice, prima, inc = apparecchia("esca3")
    righe = [r for r in _righe(inc.percorso) if r.get("tipo") != "fine"]
    _riscrivi(inc.percorso, righe)
    rap = mod.disfa(inc.incremento_id, radice=radice, apply=True)
    if rap["esito"] != "rifiutato":
        errori.append("DECOY 3 did not trip: silently inverted the prefix of an interrupted run")


    rap = mod.disfa(inc.incremento_id, radice=radice, apply=True, anche_interrotto=True)
    if rap["esito"] != "disfatto":
        errori.append("DECOY 3: with --anche-interrotto the inversion should have proceeded")
    elif mod.impronta_store(radice) != prima:
        errori.append("DECOY 3: interrupted run undone, but the store did not return")


    for nome in ("pos1", "pos2", "pos3"):
        radice, prima, inc = apparecchia(nome)
        rap = mod.disfa(inc.incremento_id, radice=radice, apply=True)
        if rap["esito"] != "disfatto" or mod.impronta_store(radice) != prima:
            errori.append(f"POSITIVE CHECK {nome}: an intact run was rejected")
    return errori


def prova_ritiro(mod, base: Path) -> list:
    ""














    errori = []
    radice = base / "ritiro" / "knowledge"
    semina(radice, mod)
    percorso = radice / "entities" / "person" / "person_00000000.json"
    prima = mod.impronta_store(radice)

    blocco = {
        "motivo": "errore_di_estrazione",
        "tipo": "scartato",
        "effetto": "drop",
        "quando": "2024-01-01",
        "verso": "",
        "da": "esca-incremento-vivo",
        "perche": "pre-commit decoy",
    }
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    bersaglio = dati["facts"][1]

    with mod.Incremento(
        "esca-incremento-vivo",
        motivo_run="decoy tombstone",
        radice=radice,
        operatore="pre-commit",
    ) as inc:

        try:
            inc.ritira_fatto(
                bersaglio,
                entity_id="person_00000000",
                ritiro=dict(blocco, motivo="because yes"),
            )
            errori.append("WITHDRAWAL DECOY did not trip: an out-of-taxonomy motivo was written")
        except ValueError:
            pass

        inc.ritira_fatto(bersaglio, entity_id="person_00000000", ritiro=blocco)
        inc.punto_fermo()
        bersaglio["expired_at"] = blocco["quando"]
        bersaglio["ritiro"] = blocco
        mod.scrivi_entita(percorso, dati)

    if mod.impronta_store(radice) == prima:
        errori.append("the withdrawal: the tombstone did not change the store (useless test)")
    rap = mod.disfa(inc.incremento_id, radice=radice, apply=True)
    if rap["esito"] != "disfatto":
        errori.append(f"the withdrawal: the inversion did not undo ({rap['esito']})")
    dopo = mod.impronta_store(radice)
    if dopo != prima:
        errori.append(
            "the withdrawal: the store did NOT return byte for byte — the `ritiro` key "
            f"was not removed ({prima} → {dopo})"
        )
    return errori





def _handler_muto(nodo: ast.ExceptHandler) -> bool:
    ""
    for stmt in nodo.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Return) and stmt.value is None:
            continue
        return False
    return True


def controlla_backup(sorgente: str) -> list:
    ""




    errori = []
    try:
        albero = ast.parse(sorgente)
    except SyntaxError as exc:  # pragma: no cover
        return [f"sbk_config.py does not parse: {exc}"]
    trovata = False
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "_backup_file":
            trovata = True
            for sotto in ast.walk(nodo):
                if isinstance(sotto, ast.ExceptHandler) and _handler_muto(sotto):
                    errori.append(
                        f"_backup_file: mute `except` at line {sotto.lineno} — "
                        "the pre-image failure becomes invisible again"
                    )
    if not trovata:
        errori.append("_backup_file no longer exists in sbk_config.py: blind guardian")
    return errori


def prova_guardiano_backup() -> list:
    ""
    errori = []
    vero = (REPO / "tools" / "sbk_config.py").read_text(encoding="utf-8")
    if controlla_backup(vero):
        errori.extend(controlla_backup(vero))
    manomesso = (
        "def _backup_file(p, keep=3):\n"
        "    try:\n"
        "        copia(p)\n"
        "    except OSError:\n"
        "        return\n"
    )
    if not controlla_backup(manomesso):
        errori.append("backup GUARDIAN: the bare `return` was not seen — blind decoy")
    return errori





def _ultima_mutazione() -> tuple:
    ""
    ultima, chi = "", ""
    if not RUN_LOG.is_dir():
        return ultima, chi
    for p in sorted(RUN_LOG.glob("*run-log*.jsonl")):
        try:
            with p.open("rb") as fh:
                fh.seek(0, 2)
                coda = min(fh.tell(), 8192)
                fh.seek(-coda, 2)
                righe = [r for r in fh.read().decode("utf-8", "ignore").splitlines() if r.strip()]
            for riga in reversed(righe):
                try:
                    ts = json.loads(riga).get("timestamp") or ""
                except ValueError:
                    continue
                if ts > ultima:
                    ultima, chi = ts, p.stem.replace("-run-log", "")
                break
        except OSError:
            continue
    return ultima, chi


def _ts_incremento(p) -> str:
    ""



    s = p.stem.split("-")[0]
    if len(s) < 16 or s[8] != "T":
        return ""
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}"


def stato() -> dict:
    reg = {}
    if REGISTRO.exists():
        try:
            reg = json.loads(REGISTRO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reg = {}
    attivato = reg.get("attivato_il")
    cartella = STORE / "increments"
    incrementi = sorted(cartella.glob("*.jsonl")) if cartella.is_dir() else []
    mutato, chi = _ultima_mutazione()








    ultimo_inc = max((_ts_incremento(p) for p in incrementi), default="")[:19]
    if not attivato:
        esito = "mai-attivato"
    elif incrementi and (not mutato or ultimo_inc >= mutato[:19]):
        esito = "vivo"
    elif mutato and mutato > attivato:
        esito = "MUTO"
    else:
        esito = "silenzio-legittimo"
    return {
        "stato": esito,
        "attivato_il": attivato,
        "script_agganciati": reg.get("script_agganciati") or [],
        "incrementi": len(incrementi),
        "ultima_mutazione": mutato,
        "ultimo_mutante": chi,
        "registro": str(REGISTRO),
    }

















SCRITTURE = {
    "safe_write_json",
    "safe_write_text",
    "write_text",
    "write_bytes",
    "dump",
    "unlink",
    "rename",
    "replace",
    "move",
    "open",
}
_FONTE = "entities|facts|PERSON_DIR|ENTITY_DIR|ORG_DIR|knowledge_dir|KNOWLEDGE_ENTITIES|profile_path|entity_path|vivo_path"


_COSTRUISCE_LO_STORE = __import__("re").compile(
    r'KNOWLEDGE_ENTITIES_DIR|PERSON_DIR|ORG_DIR|ENTITY_DIR|ENTITIES_DIR|"entities"|\'entities\''
)

_DERIVATI = (
    r"\.parquet|/l3/|/l2/|/l1/|/l0/|quality-metrics|review-queue|snapshots|"
    r"conflicts|episodes|relationships|reclassification|epistemic|increments|\.csv|\.md|\.tmp"
)


def _segmento(righe, n):
    try:
        if n.lineno == n.end_lineno:
            return righe[n.lineno - 1][n.col_offset : n.end_col_offset]
        pezzi = (
            [righe[n.lineno - 1][n.col_offset :]]
            + righe[n.lineno : n.end_lineno - 1]
            + [righe[n.end_lineno - 1][: n.end_col_offset]]
        )
        return " ".join(x.strip() for x in pezzi)
    except (IndexError, AttributeError):  # pragma: no cover
        return ""


def _risolvi(testo, assegnazioni):
    import re

    nomi = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
    for _ in range(3):
        if len(testo) > 400:
            break
        nuovo = testo
        for nome in set(nomi.findall(testo)):
            valore = assegnazioni.get(nome)
            if valore and nome not in valore:
                nuovo = nuovo.replace(nome, "(" + valore + ")")
        if nuovo == testo:
            break
        testo = nuovo
    return testo


def mutanti(radice_codice=None):
    ""
    import re

    fonte = re.compile(_FONTE)
    derivati = re.compile(_DERIVATI)
    base = Path(radice_codice) if radice_codice else REPO / "tools"
    riconosciuti, da_leggere = {}, {}
    for p in sorted(base.rglob("*.py")):
        s = str(p.relative_to(REPO))
        if "_deprecated" in s or ".venv" in s or "site-packages" in s:
            continue
        testo = p.read_text(encoding="utf-8", errors="ignore")
        righe = testo.splitlines()
        try:
            albero = ast.parse(testo)
        except SyntaxError:  # pragma: no cover
            continue
        assegnazioni = {}
        for n in ast.walk(albero):
            if (
                isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
            ):
                v = _segmento(righe, n.value)
                if 0 < len(v) < 160:
                    assegnazioni[n.targets[0].id] = v




            elif isinstance(n, ast.For) and isinstance(n.target, ast.Name):
                v = _segmento(righe, n.iter)
                if 0 < len(v) < 160:
                    assegnazioni.setdefault(n.target.id, v)


        nomina_lo_store = bool(_COSTRUISCE_LO_STORE.search(testo))
        scrive = False
        for n in ast.walk(albero):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            breve = (
                f.attr
                if isinstance(f, ast.Attribute)
                else (f.id if isinstance(f, ast.Name) else "")
            )
            if breve not in SCRITTURE:
                continue
            if breve == "open":
                modi = [
                    a.value
                    for a in n.args[1:]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ]
                if not any(("w" in m or "a" in m) for m in modi):
                    continue
            scrive = True
            if breve in ("unlink", "rename", "replace", "write_text", "write_bytes") and isinstance(
                f, ast.Attribute
            ):
                bersaglio = _segmento(righe, f.value)
            elif breve == "dump" and len(n.args) > 1:
                bersaglio = _segmento(righe, n.args[1])
            else:
                bersaglio = _segmento(righe, n.args[0]) if n.args else ""
            risolto = _risolvi(bersaglio or "", assegnazioni)
            if fonte.search(risolto) and not derivati.search(risolto):
                riconosciuti.setdefault(s, []).append((n.lineno, breve, (bersaglio or "")[:60]))
        if scrive and nomina_lo_store and s not in riconosciuti:
            da_leggere[s] = True
    return riconosciuti, sorted(da_leggere)





def autotest() -> list:
    errori = []
    try:
        mod = carica_incremento()
    except Exception as exc:  # noqa: BLE001
        return [f"the mechanism does not exist or does not import: {exc}"]
    base = Path(tempfile.mkdtemp(prefix="sb-incremento-esca-"))
    try:
        errori.extend(prova_giro(mod, base))
        errori.extend(prova_esche(mod, base))
        errori.extend(prova_ritiro(mod, base))
    except Exception as exc:  # noqa: BLE001
        import traceback

        errori.append(f"the run blew up: {exc}\n{traceback.format_exc(limit=4)}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    errori.extend(prova_guardiano_backup())
    return errori


def controlla() -> int:
    errori = autotest()
    if errori:
        print("❌ the invertible increment is not alive:")
        for e in errori:
            print(f"     {e}")
        print("   the run is in tools/util/sb-incremento-vivo.py --autotest")
        return 1
    s = stato()
    if s["stato"] == "MUTO":
        print(
            "❌ the increment is active but MUTE: a mutant ran after activation\n"
            f"     activated  {s['attivato_il']}\n"
            f"     mutation   {s['ultima_mutazione'][:19]} ({s['ultimo_mutante']})\n"
            f"     increments {s['incrementi']}\n"
            "   it is exactly how the other five safeguards died."
        )
        return 1
    nota = {
        "mai-attivato": "no script mutates yet through the increment (declared)",
        "silenzio-legittimo": "no mutant has run since activation",
        "vivo": f"{s['incrementi']} increments on disk",
    }[s["stato"]]
    print(
        "✓ invertible increment: run complete, tombstone that undoes itself, 4 decoys seen red"
        f" — {nota}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="The decoy of the invertible increment")
    ap.add_argument("--controlla", action="store_true", help="the pre-commit gate")
    ap.add_argument("--autotest", action="store_true", help="only the run on a copy")
    ap.add_argument("--stato", action="store_true", help="only the registry status")
    ap.add_argument(
        "--mutanti",
        action="store_true",
        help="who writes under entities/ or facts/, with file:line (~14 s, not in the gate)",
    )
    a = ap.parse_args()
    if a.mutanti:
        riconosciuti, da_leggere = mutanti()
        righe = sum(len(v) for v in riconosciuti.values())
        print(f"RECOGNIZED MUTANTS: {len(riconosciuti)} files, {righe} writes\n")
        for f, r in sorted(riconosciuti.items()):
            print(f"  {f}")
            for riga, chiamata, bersaglio in r:
                print(f"     :{riga:<6} {chiamata:<18} {bersaglio}")
        print(
            f"\nTO READ BY HAND: {len(da_leggere)} files build a path under "
            "entities/ and write, but the target does not resolve statically\n"
            "  (typical: `path` arrives as a function parameter — l4-05:857, "
            "xs-l4-normalize-entity-id:87, xs-l4-reanchor-facts:549 are of this kind)"
        )
        for f in da_leggere:
            print(f"     {f}")
        return 0
    if a.stato:
        print(json.dumps(stato(), indent=2, ensure_ascii=False))
        return 0
    if a.autotest:
        errori = autotest()
        for e in errori:
            print(f"❌ {e}")
        if not errori:
            print("✓ run complete, 3 decoys red, 3 positives green, backup guardian ok")
        return 1 if errori else 0
    return controlla()


if __name__ == "__main__":
    raise SystemExit(main())
