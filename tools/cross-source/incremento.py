""
























































































from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime  # noqa: UP017
from pathlib import Path

try:  # noqa: UP017  — `UTC` esiste solo da 3.11, il gate gira sulla 3.9
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.9
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))



import sbk_config as cfg  # noqa: E402

VERSIONE_FORMATO = 1



OPERAZIONI = {
    "sposta_fatto": "remove it from `a`, put it back on `da`",
    "scarta_fatto": "re-append it to `da`",
    "aggiungi_fatto": "remove it",
    "modifica_campo": "rewrite `prima`",
    "archivia_entita": "restore the verbatim text, the archive is set aside",
    "crea_entita": "set aside the created entity",
    "chiudi_stato": "reopen (`valid_to` returns to `valid_to_prima`)",
    "ritira_fatto": "remove the tombstone: `expired_at` returns to what it was and the `ritiro` block disappears",
    "promuovi_fatto": "remove the rank: the `rank` key disappears if it was not there before",
}



FONTE_DI_VERITA = ("entities", "facts", "archive")





def ora() -> str:
    return datetime.now(UTC).isoformat()


def dump_canonico(dati) -> str:
    ""







    return json.dumps(dati, ensure_ascii=False, indent=2, default=str)


def sha256_testo(testo: str) -> str:
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


def scrivi_entita(percorso, dati) -> Path:
    ""




    p = Path(percorso)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fatto = False
    try:
        tmp.write_text(dump_canonico(dati), encoding="utf-8")
        tmp.replace(p)
        fatto = True
    finally:
        if not fatto and tmp.exists():
            tmp.unlink()
    return p


def impronta(fatto: dict) -> str:
    ""


    sorgente = (fatto.get("source") or {}).get("source_file") or ""
    grezzo = "|".join(
        [
            str(fatto.get("attribute") or ""),
            str(fatto.get("value") or "").strip().lower(),
            str(sorgente),
            str((fatto.get("source") or {}).get("record_id") or ""),
        ]
    )
    return hashlib.sha1(grezzo.encode()).hexdigest()[:16]  # noqa: S324


def _identifica(f: dict) -> tuple:
    fid = f.get("fact_id") or ""
    if fid:
        return str(fid), "fact_id"
    return impronta(f), "impronta"


def radice_default() -> Path:
    return cfg.DATA_ROOT / "knowledge"


def cartella_incrementi(radice=None) -> Path:
    return Path(radice or radice_default()) / "increments"


def impronta_store(radice) -> str:
    ""




    radice = Path(radice)
    voci = []
    for sotto in FONTE_DI_VERITA:
        base = radice / sotto
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                voci.append(
                    f"{p.relative_to(radice)}:{sha256_testo(p.read_text(encoding='utf-8'))}"
                )
    return hashlib.sha256("\n".join(voci).encode("utf-8")).hexdigest()


def _versione(script: str) -> dict:
    ""




    testa = ""
    try:
        testa = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        testa = ""
    sha_file = ""
    for cartella in ("cross-source", "util", ""):
        p = (
            REPO / "tools" / cartella / f"{script}.py"
            if cartella
            else REPO / "tools" / f"{script}.py"
        )
        if p.exists():
            sha_file = sha256_testo(p.read_text(encoding="utf-8"))[:16]
            break
    return {"git": testa, "sha_file": sha_file}





class Incremento:
    ""

    def __init__(
        self,
        script,
        *,
        motivo_run,
        argv=None,
        operatore=None,
        radice=None,
        attivo=True,
        cartella=None,
    ):
        self.script = script
        self.motivo_run = motivo_run
        self.argv = list(argv if argv is not None else sys.argv[1:])
        self.operatore = operatore or os.environ.get("SBK_OPERATORE") or "pipeline"
        self.radice = Path(radice) if radice else radice_default()
        self.attivo = attivo
        self.cartella = Path(cartella) if cartella else cartella_incrementi(self.radice)
        self.percorso = None
        self.incremento_id = None
        self._fh = None
        self.righe = 0
        self.op_scritte = 0
        self._entita = set()
        self._fatti = 0
        self.sigillato = False



    def __enter__(self):
        if not self.attivo:
            return self
        self.cartella.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.incremento_id = f"{ts}-{self.script}-{os.getpid()}"
        self.percorso = self.cartella / f"{self.incremento_id}.jsonl"
        n = 1
        while self.percorso.exists():
            n += 1
            self.incremento_id = f"{ts}-{self.script}-{os.getpid()}-{n}"
            self.percorso = self.cartella / f"{self.incremento_id}.jsonl"
        self._fh = self.percorso.open("a", encoding="utf-8")
        self._scrivi(
            {
                "tipo": "inizio",
                "formato": VERSIONE_FORMATO,
                "incremento_id": self.incremento_id,
                "script": self.script,
                "argv": self.argv,
                "versione": _versione(self.script),
                "operatore": self.operatore,
                "motivo_run": self.motivo_run,
            }
        )
        self.punto_fermo()
        return self

    def __exit__(self, tipo_exc, valore, traccia):
        if not self._fh:
            return False
        if tipo_exc is not None:



            self._scrivi({"tipo": "errore", "eccezione": f"{tipo_exc.__name__}: {valore}"})
            self.punto_fermo()
        else:
            self._scrivi(
                {
                    "tipo": "fine",
                    "righe": self.righe,
                    "op": self.op_scritte,
                    "entita_toccate": len(self._entita),
                    "fatti_toccati": self._fatti,
                }
            )
            self.punto_fermo()
            self.sigillato = True
        self._fh.close()
        self._fh = None
        return False



    def _scrivi(self, record: dict) -> dict:
        if not self._fh:
            return record
        record["quando"] = ora()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")



        self._fh.flush()
        self.righe += 1
        return record

    def punto_fermo(self) -> None:
        ""




        if self._fh:
            self._fh.flush()
            os.fsync(self._fh.fileno())

    def _op(self, op: str, campi: dict, *, invertibile=True, perche_non_invertibile="") -> dict:
        if op not in OPERAZIONI:
            raise ValueError(f"op outside enum: {op!r}. Allowed: {sorted(OPERAZIONI)}")
        if not invertibile and not perche_non_invertibile.strip():
            raise ValueError(f"{op}: `invertibile=False` without a written reason")
        record = {"tipo": "op", "op": op, "invertibile": bool(invertibile)}
        if not invertibile:
            record["perche_non_invertibile"] = perche_non_invertibile
        record.update(campi)
        self.op_scritte += 1
        for chiave in ("da", "a", "entity_id"):
            if record.get(chiave):
                self._entita.add(record[chiave])
        if record.get("fact_id") or record.get("impronta"):
            self._fatti += 1
        return self._scrivi(record)



    def sposta_fatto(self, f: dict, *, da: str, a: str, indice=None, motivo=""):
        fid, tipo = _identifica(f)
        return self._op(
            "sposta_fatto",
            {
                "fact_id": fid if tipo == "fact_id" else "",
                "impronta": impronta(f),
                "id_tipo": tipo,
                "attributo": f.get("attribute"),
                "da": da,
                "a": a,
                "indice": indice,
                "fatto": f,
                "sha256": sha256_testo(dump_canonico(f)),
                "motivo": motivo,
            },
        )

    def scarta_fatto(self, f: dict, *, da: str, perche: str, indice=None):
        fid, tipo = _identifica(f)
        return self._op(
            "scarta_fatto",
            {
                "fact_id": fid if tipo == "fact_id" else "",
                "impronta": impronta(f),
                "id_tipo": tipo,
                "attributo": f.get("attribute"),
                "sorgente": (f.get("source") or {}).get("source_type"),
                "da": da,
                "indice": indice,
                "perche": perche,
                "fatto": f,
                "sha256": sha256_testo(dump_canonico(f)),
            },
        )

    def aggiungi_fatto(self, f: dict, *, entity_id: str, motivo=""):
        fid, tipo = _identifica(f)
        return self._op(
            "aggiungi_fatto",
            {
                "fact_id": fid if tipo == "fact_id" else "",
                "impronta": impronta(f),
                "id_tipo": tipo,
                "entity_id": entity_id,
                "fatto": f,
                "sha256": sha256_testo(dump_canonico(f)),
                "motivo": motivo,
            },
        )

    def modifica_campo(self, *, campo, prima, dopo, entity_id=None, fact_id=None, motivo=""):
        if not entity_id and not fact_id:
            raise ValueError("modifica_campo: `entity_id` or `fact_id` required")
        return self._op(
            "modifica_campo",
            {
                "entity_id": entity_id or "",
                "fact_id": fact_id or "",
                "campo": campo,
                "prima": prima,
                "dopo": dopo,
                "motivo": motivo,
            },
        )

    def archivia_entita(self, entity_id, *, percorso, percorso_archivio, motivo=""):
        ""







        p = Path(percorso)
        testo = p.read_text(encoding="utf-8")
        return self._op(
            "archivia_entita",
            {
                "entity_id": entity_id,
                "percorso": str(p),
                "percorso_archivio": str(percorso_archivio),
                "prima_testo": testo,
                "sha256": sha256_testo(testo),
                "motivo": motivo,
            },
        )

    def crea_entita(self, entity_id, *, motivo, percorso=None, tipo="person"):
        return self._op(
            "crea_entita",
            {
                "entity_id": entity_id,
                "entity_type": tipo,
                "percorso": str(percorso) if percorso else "",
                "motivo": motivo,
            },
        )

    def chiudi_stato(self, fact_id, *, valid_to_dopo, chiuso_da, valid_to_prima=None, entity_id=""):
        ""



        return self._op(
            "chiudi_stato",
            {
                "fact_id": fact_id,
                "entity_id": entity_id,
                "valid_to_prima": valid_to_prima,
                "valid_to_dopo": valid_to_dopo,
                "chiuso_da": chiuso_da,
            },
        )

    def ritira_fatto(self, f: dict, *, entity_id: str, ritiro: dict, prima: dict = None):
        ""





















        from knowledge_ritiro import pre_image_lapide, valida_ritiro  # noqa: PLC0415

        violazioni = valida_ritiro(ritiro)
        if violazioni:
            raise ValueError("ritira_fatto: invalid `ritiro` block — " + " · ".join(violazioni))

        if prima is None:
            prima = pre_image_lapide(f)
        fid, tipo = _identifica(f)
        return self._op(
            "ritira_fatto",
            {
                "fact_id": fid if tipo == "fact_id" else "",
                "impronta": impronta(f),
                "id_tipo": tipo,
                "attributo": f.get("attribute"),
                "entity_id": entity_id,
                "ritiro": dict(ritiro),
                "expired_at_dopo": ritiro.get("quando"),
                "prima": prima,
                "motivo": ritiro.get("motivo"),
                "effetto": ritiro.get("effetto"),
            },
        )

    def promuovi_fatto(self, f: dict, *, entity_id: str, criterio: str, prima=None, perche=""):
        ""














        from knowledge_rango import CRITERI, PREFERITO, pre_image_rango  # noqa: PLC0415

        if criterio not in CRITERI:
            raise ValueError(
                "promuovi_fatto: criterion {!r} outside the three declared ({})".format(
                    criterio, ", ".join(CRITERI)
                )
            )
        if prima is None:
            prima = pre_image_rango(f)
        fid, tipo = _identifica(f)
        return self._op(
            "promuovi_fatto",
            {
                "fact_id": fid if tipo == "fact_id" else "",
                "impronta": impronta(f),
                "id_tipo": tipo,
                "attributo": f.get("attribute"),
                "entity_id": entity_id,
                "rank_dopo": PREFERITO,
                "criterio": criterio,
                "prima": prima,
                "perche": str(perche or ""),
            },
        )

    def non_invertibile(self, op, *, perche, **campi):
        ""


        return self._op(op, campi, invertibile=False, perche_non_invertibile=perche)

    def nota(self, **campi):
        return self._scrivi({"tipo": "nota", **campi})





def percorso_incremento(incremento_id, radice=None) -> Path:
    return cartella_incrementi(radice) / f"{incremento_id}.jsonl"


def leggi(incremento_id, radice=None) -> dict:
    ""

    p = percorso_incremento(incremento_id, radice)
    intestazione, op, sigillo, errore = {}, [], None, None
    with p.open(encoding="utf-8") as fh:
        for riga in fh:
            riga = riga.strip()
            if not riga:
                continue
            r = json.loads(riga)
            tipo = r.get("tipo")
            if tipo == "inizio":
                intestazione = r
            elif tipo == "op":
                op.append(r)
            elif tipo == "fine":
                sigillo = r
            elif tipo == "errore":
                errore = r
    return {
        "incremento_id": incremento_id,
        "percorso": p,
        "intestazione": intestazione,
        "op": op,
        "sigillo": sigillo,
        "errore": errore,
        "interrotto": sigillo is None,
    }


def elenca(radice=None):
    cartella = cartella_incrementi(radice)
    if not cartella.is_dir():
        return []
    return sorted(p.stem for p in cartella.glob("*.jsonl"))


def ids_toccati(incremento_id, radice=None) -> set:
    ""
    p = percorso_incremento(incremento_id, radice)
    fuori = set()
    with p.open(encoding="utf-8") as fh:
        for riga in fh:
            if '"tipo": "op"' not in riga and '"tipo":"op"' not in riga:
                continue
            try:
                r = json.loads(riga)
            except ValueError:  # pragma: no cover
                continue
            for chiave in ("da", "a", "entity_id"):
                if r.get(chiave):
                    fuori.add(r[chiave])
    return fuori




















def _percorso_entita(radice, eid, tipi=("person", "organization", "org", "company")):
    for t in tipi:
        p = Path(radice) / "entities" / t / f"{eid}.json"
        if p.exists():
            return p
    return None


class _CacheEntita:
    ""












    def __init__(self, tetto: int = 64):
        self.tetto = tetto
        self._dati = {}
        self._sporchi = set()
        self._ordine = []

    def _tocca(self, chiave):
        if chiave in self._ordine:
            self._ordine.remove(chiave)
        self._ordine.append(chiave)
        while len(self._ordine) > self.tetto:
            vecchia = self._ordine.pop(0)
            self._scarica(vecchia)

    def _scarica(self, chiave):
        if chiave in self._sporchi:
            scrivi_entita(chiave, self._dati[chiave])
            self._sporchi.discard(chiave)
        self._dati.pop(chiave, None)

    def carica(self, percorso):
        chiave = str(percorso)
        if chiave not in self._dati:
            self._dati[chiave] = json.loads(Path(percorso).read_text(encoding="utf-8"))
        self._tocca(chiave)
        return self._dati[chiave]

    def salva(self, percorso, dati):
        chiave = str(percorso)
        self._dati[chiave] = dati
        self._sporchi.add(chiave)
        self._tocca(chiave)

    def dimentica(self, percorso):
        ""
        chiave = str(percorso)
        self._dati.pop(chiave, None)
        self._sporchi.discard(chiave)
        if chiave in self._ordine:
            self._ordine.remove(chiave)

    def chiudi(self):
        for chiave in list(self._ordine):
            self._scarica(chiave)
        self._ordine = []




_CACHE = None


def _carica(p):
    if _CACHE is not None:
        return _CACHE.carica(p)
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _salva(p, dati):
    if _CACHE is not None:
        _CACHE.salva(p, dati)
        return Path(p)
    return scrivi_entita(p, dati)


def _dimentica(p):
    if _CACHE is not None:
        _CACHE.dimentica(p)


def _indice_fatto(fatti, fact_id, imp):
    for i, f in enumerate(fatti):
        if fact_id and f.get("fact_id") == fact_id:
            return i
        if not fact_id and impronta(f) == imp:
            return i
    return -1


def _leggi_campo(dati, campo):
    corrente = dati
    for pezzo in str(campo).split("."):
        if not isinstance(corrente, dict) or pezzo not in corrente:
            return None, False
        corrente = corrente[pezzo]
    return corrente, True


def _scrivi_campo(dati, campo, valore):
    pezzi = str(campo).split(".")
    corrente = dati
    for pezzo in pezzi[:-1]:
        corrente = corrente.setdefault(pezzo, {})
    corrente[pezzi[-1]] = valore


def _stato_op(radice, r):
    ""



    op = r.get("op")
    if op in ("sposta_fatto", "aggiungi_fatto"):
        eid = r.get("a") or r.get("entity_id")
        p = _percorso_entita(radice, eid)
        if p is None:
            return "assente", f"{eid} no longer exists"
        fatti = _carica(p).get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "assente", f"the fact is not on {eid}"






        atteso = r.get("fatto") or {}
        manca = object()



        contabilita = {x for x in (r.get("a"), r.get("da"), r.get("entity_id")) if x}
        diversi = sorted(
            k
            for k, v in atteso.items()
            if fatti[i].get(k, manca) != v and fatti[i].get(k) not in contabilita
        )
        if diversi:
            return "divergente", (
                f"the fact {r.get('fact_id') or r.get('impronta')} on {eid} changed after "
                f"the run on {diversi}: putting back `prima` would erase that change"
            )
        return "ok", ""
    if op == "scarta_fatto":


        return "non-verificabile", "the discard leaves no observable state"
    if op == "modifica_campo":
        if r.get("fact_id"):
            p = _percorso_entita(radice, r.get("entity_id")) if r.get("entity_id") else None
            if p is None:
                return "assente", "the fact's entity not found"
            fatti = _carica(p).get("facts") or []
            i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
            if i < 0:
                return "assente", "the fact is no longer there"
            valore, trovato = _leggi_campo(fatti[i], r.get("campo"))
        else:
            p = _percorso_entita(radice, r.get("entity_id"))
            if p is None:
                return "assente", f"{r.get('entity_id')} no longer exists"
            valore, trovato = _leggi_campo(_carica(p), r.get("campo"))
        if not trovato:
            return "assente", f"the field {r.get('campo')} is not present"
        if valore != r.get("dopo"):
            return (
                "divergente",
                f"{r.get('campo')} is {valore!r}, the increment says {r.get('dopo')!r}",
            )
        return "ok", ""
    if op == "archivia_entita":
        p = Path(r.get("percorso"))
        if p.exists():
            return "divergente", f"{r.get('entity_id')} is alive again in {p.parent}"
        return "ok", ""
    if op == "crea_entita":
        p = (
            Path(r["percorso"])
            if r.get("percorso")
            else _percorso_entita(radice, r.get("entity_id"))
        )
        if p is None or not Path(p).exists():
            return "assente", f"{r.get('entity_id')} not present"
        return "ok", ""
    if op == "chiudi_stato":
        p = _percorso_entita(radice, r.get("entity_id")) if r.get("entity_id") else None
        if p is None:
            return "non-verificabile", "without entity_id the fact cannot be found"
        fatti = _carica(p).get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "assente", "the fact is no longer there"
        if fatti[i].get("valid_to") != r.get("valid_to_dopo"):
            return "divergente", "valid_to is not the one recorded"
        return "ok", ""
    if op == "ritira_fatto":
        p = _percorso_entita(radice, r.get("entity_id")) if r.get("entity_id") else None
        if p is None:
            return "non-verificabile", "without entity_id the fact cannot be found"
        fatti = _carica(p).get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "assente", "the retired fact is no longer there"
        if fatti[i].get("ritiro") != r.get("ritiro"):




            return "divergente", "the `ritiro` block is not the one recorded"
        if str(fatti[i].get("expired_at") or "") != str(r.get("expired_at_dopo") or ""):
            return "divergente", "expired_at is not the one recorded"
        return "ok", ""
    if op == "promuovi_fatto":
        p = _percorso_entita(radice, r.get("entity_id")) if r.get("entity_id") else None
        if p is None:
            return "non-verificabile", "without entity_id the fact cannot be found"
        fatti = _carica(p).get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "assente", "the promoted fact is no longer there"
        if str(fatti[i].get("rank") or "") != str(r.get("rank_dopo") or ""):


            return "divergente", "the rank is not the one recorded"
        return "ok", ""
    return "non-verificabile", f"unknown op: {op}"  # pragma: no cover


def _integrita(r):
    ""





    atteso = r.get("sha256")
    if not atteso:
        return True, ""
    if r.get("op") == "archivia_entita":
        vero = sha256_testo(r.get("prima_testo") or "")
    elif "fatto" in r:
        vero = sha256_testo(dump_canonico(r["fatto"]))
    else:
        return True, ""
    if vero != atteso:
        return (
            False,
            f"sha256 does not match on {r.get('op')} ({r.get('entity_id') or r.get('fact_id')})",
        )
    return True, ""


def _da_parte(radice, incremento_id, percorso):
    ""





    dove = cartella_incrementi(radice) / "disfatti" / incremento_id
    dove.mkdir(parents=True, exist_ok=True)
    destinazione = dove / Path(percorso).name
    n = 1
    while destinazione.exists():
        n += 1
        destinazione = dove / f"{Path(percorso).stem}.{n}{Path(percorso).suffix}"
    Path(percorso).replace(destinazione)
    return destinazione


def _inverti(radice, r, inc, incremento_id):
    ""
    op = r.get("op")
    if op == "sposta_fatto":
        pa = _percorso_entita(radice, r["a"])
        fatto = r.get("fatto") or {}
        if pa is not None:
            dati = _carica(pa)
            fatti = dati.get("facts") or []
            i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
            if i >= 0:
                fatti.pop(i)
                dati["facts"] = fatti
                inc.scarta_fatto(fatto, da=r["a"], perche=f"inversion of {incremento_id}")
                _salva(pa, dati)
        pda = _percorso_entita(radice, r["da"])
        if pda is None:
            return f"sposta_fatto: {r['da']} does not exist, the fact was not put back"
        dati = _carica(pda)
        fatti = dati.get("facts") or []
        if _indice_fatto(fatti, r.get("fact_id"), r.get("impronta")) < 0:
            i = r.get("indice")
            fatti.insert(i if isinstance(i, int) and 0 <= i <= len(fatti) else len(fatti), fatto)
            dati["facts"] = fatti
            inc.sposta_fatto(fatto, da=r["a"], a=r["da"], indice=r.get("indice"))
            _salva(pda, dati)
            return ""
        return f"sposta_fatto: the fact was already on {r['da']} (idempotent inverse)"
    if op == "scarta_fatto":
        pda = _percorso_entita(radice, r["da"])
        if pda is None:
            return f"scarta_fatto: {r['da']} does not exist, the discarded fact was not put back"
        dati = _carica(pda)
        fatti = dati.get("facts") or []
        if _indice_fatto(fatti, r.get("fact_id"), r.get("impronta")) >= 0:
            return f"scarta_fatto: the fact was already on {r['da']} (idempotent inverse)"
        i = r.get("indice")
        fatti.insert(i if isinstance(i, int) and 0 <= i <= len(fatti) else len(fatti), r["fatto"])
        dati["facts"] = fatti
        inc.aggiungi_fatto(r["fatto"], entity_id=r["da"], motivo=f"inversion of {incremento_id}")
        _salva(pda, dati)
        return ""
    if op == "aggiungi_fatto":
        p = _percorso_entita(radice, r["entity_id"])
        if p is None:
            return f"aggiungi_fatto: {r['entity_id']} no longer exists"
        dati = _carica(p)
        fatti = dati.get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "aggiungi_fatto: the fact was not there (idempotent inverse)"
        fatti.pop(i)
        dati["facts"] = fatti
        inc.scarta_fatto(r["fatto"], da=r["entity_id"], perche=f"inversion of {incremento_id}")
        _salva(p, dati)
        return ""
    if op == "modifica_campo":
        p = _percorso_entita(radice, r.get("entity_id"))
        if p is None:
            return f"modifica_campo: {r.get('entity_id')} no longer exists"
        dati = _carica(p)
        if r.get("fact_id"):
            fatti = dati.get("facts") or []
            i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
            if i < 0:
                return "modifica_campo: the fact is no longer there"
            _scrivi_campo(fatti[i], r["campo"], r.get("prima"))
        else:
            _scrivi_campo(dati, r["campo"], r.get("prima"))
        inc.modifica_campo(
            campo=r["campo"],
            prima=r.get("dopo"),
            dopo=r.get("prima"),
            entity_id=r.get("entity_id") or None,
            fact_id=r.get("fact_id") or None,
            motivo=f"inversion of {incremento_id}",
        )
        _salva(p, dati)
        return ""
    if op == "archivia_entita":
        p = Path(r["percorso"])
        p.parent.mkdir(parents=True, exist_ok=True)
        inc.crea_entita(
            r["entity_id"],
            motivo=f"inversion of {incremento_id}",
            percorso=p,
        )
        inc.punto_fermo()




        _dimentica(p)
        p.write_text(r["prima_testo"], encoding="utf-8")
        arch = Path(r.get("percorso_archivio") or "")
        if arch and arch.exists():
            _dimentica(arch)
            dove = _da_parte(radice, incremento_id, arch)
            inc.nota(cosa="archive set aside", da=str(arch), a=str(dove))
        return ""
    if op == "crea_entita":
        p = Path(r["percorso"]) if r.get("percorso") else _percorso_entita(radice, r["entity_id"])
        if p is None or not Path(p).exists():
            return f"crea_entita: {r['entity_id']} not present (idempotent inverse)"
        inc.archivia_entita(
            r["entity_id"],
            percorso=p,
            percorso_archivio=str(cartella_incrementi(radice) / "disfatti" / incremento_id),
            motivo=f"inversion of {incremento_id}",
        )
        inc.punto_fermo()
        _dimentica(p)
        _da_parte(radice, incremento_id, p)
        return ""
    if op == "chiudi_stato":
        p = _percorso_entita(radice, r.get("entity_id"))
        if p is None:
            return "chiudi_stato: entity not found"
        dati = _carica(p)
        fatti = dati.get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "chiudi_stato: the fact is no longer there"
        fatti[i]["valid_to"] = r.get("valid_to_prima")
        inc.chiudi_stato(
            r["fact_id"],
            valid_to_dopo=r.get("valid_to_prima"),
            chiuso_da="",
            valid_to_prima=r.get("valid_to_dopo"),
            entity_id=r.get("entity_id") or "",
        )
        _salva(p, dati)
        return ""
    if op == "ritira_fatto":
        p = _percorso_entita(radice, r.get("entity_id"))
        if p is None:
            return "ritira_fatto: entity not found"
        dati = _carica(p)
        fatti = dati.get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "ritira_fatto: the fact is no longer there"
        if not fatti[i].get("ritiro") and not fatti[i].get("expired_at"):
            return "ritira_fatto: the tombstone was not there (idempotent inverse)"









        prima = r.get("prima") or {}
        for campo, stato in sorted(prima.items()):
            if not isinstance(stato, dict):
                continue
            if stato.get("c_era"):
                fatti[i][campo] = stato.get("valore")
            else:
                fatti[i].pop(campo, None)
        blocco = r.get("ritiro") or {}
        inc.modifica_campo(
            campo="ritiro",
            prima=blocco,
            dopo=None,
            entity_id=r.get("entity_id") or None,
            fact_id=r.get("fact_id") or None,
            motivo=f"inversion of {incremento_id}",
        )
        _salva(p, dati)
        return ""
    if op == "promuovi_fatto":
        p = _percorso_entita(radice, r.get("entity_id"))
        if p is None:
            return "promuovi_fatto: entity not found"
        dati = _carica(p)
        fatti = dati.get("facts") or []
        i = _indice_fatto(fatti, r.get("fact_id"), r.get("impronta"))
        if i < 0:
            return "promuovi_fatto: the fact is no longer there"
        if not fatti[i].get("rank"):
            return "promuovi_fatto: the rank was not there (idempotent inverse)"



        prima = r.get("prima") or {}
        for campo, stato in sorted(prima.items()):
            if not isinstance(stato, dict):
                continue
            if stato.get("c_era"):
                fatti[i][campo] = stato.get("valore")
            else:
                fatti[i].pop(campo, None)
        inc.modifica_campo(
            campo="rank",
            prima=r.get("rank_dopo"),
            dopo=None,
            entity_id=r.get("entity_id") or None,
            fact_id=r.get("fact_id") or None,
            motivo=f"inversion of {incremento_id}",
        )
        _salva(p, dati)
        return ""
    return f"unknown op, skipped: {op}"  # pragma: no cover


def _incrementi_successivi(incremento_id, radice):
    return [i for i in elenca(radice) if i > incremento_id and not i.startswith("disfatti")]


def disfa(incremento_id, *, radice=None, apply=False, anche_interrotto=False, operatore=None):
    ""





    global _CACHE
    _CACHE = _CacheEntita()
    try:
        return _disfa(
            incremento_id,
            radice=radice,
            apply=apply,
            anche_interrotto=anche_interrotto,
            operatore=operatore,
        )
    finally:


        _CACHE.chiudi()
        _CACHE = None


def _disfa(incremento_id, *, radice=None, apply=False, anche_interrotto=False, operatore=None):
    ""






    radice = Path(radice) if radice else radice_default()
    p = percorso_incremento(incremento_id, radice)
    rapporto = {
        "incremento_id": incremento_id,
        "percorso": str(p),
        "esito": "rifiutato",
        "motivi": [],
        "note": [],
        "op_totali": 0,
        "invertite": 0,
        "non_invertibili": [],
        "non_verificabili": [],
        "incremento_prodotto": "",
        "applicato": bool(apply),
    }
    if not p.exists():
        rapporto["motivi"].append(f"increment {incremento_id} does not exist in {p.parent}")
        return rapporto

    letto = leggi(incremento_id, radice)
    op = letto["op"]
    rapporto["op_totali"] = len(op)
    rapporto["interrotto"] = letto["interrotto"]

    if letto["interrotto"] and not anche_interrotto:
        rapporto["motivi"].append(
            "INTERRUPTED run (no `fine` seal): the store was modified halfway. "
            "An explicit confirmation is required (`anche_interrotto=True` / `--anche-interrotto`): "
            "inverting the prefix silently is the way to make things worse."
        )
        return rapporto




    miei = ids_toccati(incremento_id, radice)
    for altro in _incrementi_successivi(incremento_id, radice):
        try:
            comuni = miei & ids_toccati(altro, radice)
        except (OSError, ValueError):  # pragma: no cover
            continue
        if comuni:
            rapporto["motivi"].append(
                f"the later increment {altro} touched {len(comuni)} of the same ids "
                f"(e.g. {sorted(comuni)[:3]}): only the last one can be undone"
            )
            return rapporto


    piano = []
    visto_effetto = False
    for r in reversed(op):
        if not r.get("invertibile", True):
            rapporto["non_invertibili"].append(
                {"op": r.get("op"), "perche": r.get("perche_non_invertibile")}
            )
            continue
        integro, perche = _integrita(r)
        if not integro:
            rapporto["motivi"].append(perche)
            return rapporto
        stato, dettaglio = _stato_op(radice, r)
        if stato == "divergente":
            rapporto["motivi"].append(f"{r.get('op')}: {dettaglio}")
            return rapporto
        if stato == "assente":
            if visto_effetto or not letto["interrotto"]:
                rapporto["motivi"].append(
                    f"{r.get('op')}: {dettaglio} — the recorded «dopo» is not there, "
                    "and the run appears completed: the history is not the one written"
                )
                return rapporto

            rapporto["note"].append(f"{r.get('op')}: {dettaglio} (tail of the interrupted run)")
            continue
        if stato == "non-verificabile":
            rapporto["non_verificabili"].append({"op": r.get("op"), "perche": dettaglio})
        else:
            visto_effetto = True
        piano.append(r)

    if not apply:
        rapporto["esito"] = "da_disfare"
        rapporto["invertite"] = len(piano)
        return rapporto


    with Incremento(
        "disfa",
        motivo_run=f"inversion of {incremento_id}",
        argv=[incremento_id],
        operatore=operatore or "disfa",
        radice=radice,
    ) as inc:
        rapporto["incremento_prodotto"] = inc.incremento_id
        inc.nota(cosa="inversion", incremento_disfatto=incremento_id, op=len(piano))
        inc.punto_fermo()
        for r in piano:
            nota = _inverti(radice, r, inc, incremento_id)
            if nota:
                rapporto["note"].append(nota)
            else:
                rapporto["invertite"] += 1








        _CACHE.chiudi()
        inc.punto_fermo()
    rapporto["esito"] = "disfatto"
    return rapporto
