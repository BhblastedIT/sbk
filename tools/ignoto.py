""























































































from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

__all__ = [
    "PREFISSO",
    "NAMESPACE",
    "NessunValore",
    "Riconoscimento",
    "Snak",
    "Valore",
    "ValoreIgnoto",
    "affermazione_di",
    "e_ignoto",
    "id_ignoto",
    "riconosci",
    "snak_per",
]



NAMESPACE = "ignoto"



PREFISSO = "ignoto_"




_LUNGHEZZA_ID = 16





@dataclass(frozen=True)
class Valore:
    ""





    valore: str

    def __post_init__(self) -> None:
        if self.valore is None or not str(self.valore).strip():
            raise ValueError(
                "Valore with no value: if there is no value the class is "
                "ValoreIgnoto (it exists, I don't know which one) or NessunValore (there is none)"
            )

    tipo = "valore"

    def come_dict(self) -> dict:
        return {"snak": self.tipo, "valore": self.valore}


@dataclass(frozen=True)
class ValoreIgnoto:
    ""











    id: str
    affermazione: str
    famiglia: str
    motivo: str
    testo: str = ""
    ancora: str = ""

    tipo = "ignoto"

    def __post_init__(self) -> None:
        if not self.id.startswith(PREFISSO):
            raise ValueError(f"id of an ignoto without the prefix {PREFISSO!r}: {self.id!r}")
        if not self.affermazione:
            raise ValueError(
                "ValoreIgnoto without a statement: the id would be per-name instead of "
                "per-statement, and the separate facts would collapse into a single shell"
            )
        if not self.motivo:
            raise ValueError("ValoreIgnoto without a reason: a mute ignoto cannot be reviewed")

    def come_dict(self) -> dict:
        d = {
            "snak": self.tipo,
            "id": self.id,
            "affermazione": self.affermazione,
            "famiglia": self.famiglia,
            "motivo": self.motivo,
        }
        if self.testo:
            d["testo"] = self.testo
        if self.ancora:
            d["ancora"] = self.ancora
        return d


@dataclass(frozen=True)
class NessunValore:
    ""










    motivo: str = ""

    tipo = "nessun_valore"

    def come_dict(self) -> dict:
        d = {"snak": self.tipo}
        if self.motivo:
            d["motivo"] = self.motivo
        return d


Snak = Valore | ValoreIgnoto | NessunValore


def e_ignoto(x: object) -> bool:
    ""





    if isinstance(x, ValoreIgnoto):
        return True
    return isinstance(x, str) and x.startswith(PREFISSO)





def affermazione_di(
    source_file: str, record_id: str, attributo: str, ruolo: str = "subject"
) -> str:
    ""







    return "|".join((source_file or "", record_id or "", attributo or "", ruolo or ""))


def id_ignoto(affermazione: str, namespace: str = NAMESPACE) -> str:
    ""







    if not affermazione:
        raise ValueError("id_ignoto() without a statement: it would be a per-name id")
    h = hashlib.md5(f"{namespace}|{affermazione}".encode()).hexdigest()[:_LUNGHEZZA_ID]
    return f"{PREFISSO}{h}"





def _lessico(testo: str) -> frozenset[str]:
    ""
    return frozenset(testo.split())










RUOLI = _lessico(
    """
    accountant accountants admin administration advisor advisors agency agencies agent agents
    analyst analysts architect assistant assistants attorney attorneys auditor auditors
    board broker brokers buyer buyers candidate candidates ceo cfo client clients cliente clienti
    coach colleague colleagues collaborator collaborators consultant consultants contact contacts
    contractor contractors coordinator counsel counterpart counterparty courier customer customers
    department departments designer designers developer developers director directors distributor
    distributors employee employees employer employers engineer engineers executive executives
    finance founder founders freelance freelancer freelancers head heads hire hires hr
    installer intern interns investor investors it landlord lawyer lawyers lead leadership
    legal maintainer manager managers management marketing mgmt notary operator operators
    owner owners partner partners people personnel photographer plumber pm president
    provider providers recruiter recruiters reseller resellers sales salesperson secretary
    shareholder shareholders solicitor staff stakeholder stakeholders subcontractor
    supplier suppliers support team teams technician technicians tenant tenants trainer
    translator vendor vendors worker workers
    accountants amministratore amministrazione avvocato avvocati candidato candidati
    collaboratore collaboratori commercialista commercialisti consulente consulenti
    contabilita controparte dipendente dipendenti direttore fornitore fornitori
    geometra idraulico impiegato impiegati ingegnere notaio operaio operai
    progettista proprietario responsabile segreteria socio soci tecnico tecnici
    condominium condominio
    """
)




MODIFICATORI = _lessico(
    """
    a all an and another any as at by e ed di del della dei delle da for from her his in
    into il lo la le gli un uno una new next of on or other our per potential previous prior
    same senior junior some the their to two three with within your
    external internal future former current main other second third local remote generic
    unnamed unspecified various several multiple key primary secondary
    business commercial corporate creative digital financial general global graphic legal
    logistic logistics marketing media operational operations product project quality real
    estate regional sales security social software strategic technical
    """
)




MARCATORI = _lessico(
    """
    unknown unknowns sconosciuto sconosciuta ignoto ignota anonimo anonima anonymous
    tbd tba na n/a none nessuno nobody someone somebody qualcuno unspecified unnamed
    undisclosed unidentified undefined null nil ? ??? xxx tbc
    """
)




_POSSESSIVO = re.compile(r"^(.{2,60}?)['’]s\s+(.{2,40})$", re.I)

















_PAREN = re.compile(r"[(\[].*?[)\]]")
_SEPARATORI = re.compile(r"[\s,;/\\|+&\-–—_.:]+")


@dataclass(frozen=True)
class Riconoscimento:
    ""


    famiglia: str
    motivo: str
    ancora: str = ""


def _parole(s: str) -> list[str]:
    ""

    return [p for p in _SEPARATORI.split(s.strip()) if p]


def _tutte_di_ruolo(parole: list[str]) -> bool:
    ""










    if not parole:
        return False
    basse = [p.lower() for p in parole]
    if not any(p in RUOLI for p in basse):
        return False
    for grezza, p in zip(parole, basse):
        if p in RUOLI or p in MODIFICATORI:
            continue
        if 2 <= len(grezza) <= 5 and grezza.isalpha() and grezza.isupper():
            continue
        return False
    return True


def _norma(s: str) -> str:
    return " ".join(_SEPARATORI.split((s or "").strip().lower())).strip()


def riconosci(nome: str, noti: frozenset[str] | set[str] | None = None) -> Riconoscimento | None:
    ""













    testo = (nome or "").strip()
    if not testo:
        return None
    if noti:
        n = _norma(_PAREN.sub(" ", testo))
        if n in noti or n.replace(" ", "") in noti:
            return None

    parole_intere = [p.lower() for p in _parole(testo)]
    if parole_intere and all(p in MARCATORI for p in parole_intere):
        return Riconoscimento("marcatore", f"literal marker of ignorance: «{testo[:40]}»")


    nudo = _PAREN.sub(" ", testo).strip(" ,;-–—")
    if not nudo:
        nudo = testo

    en = _POSSESSIVO.match(nudo)
    if en and _tutte_di_ruolo(_parole(en.group(2))):

        return Riconoscimento(
            "possessivo",
            f"a role referring to a third party: «{nudo[:50]}»",
            ancora=en.group(1).strip(),
        )
    if _tutte_di_ruolo(_parole(nudo)):
        return Riconoscimento("ruolo_nudo", f"describes a position, not who holds it: «{nudo[:50]}»")

    return None


def snak_per(
    nome: str,
    *,
    source_file: str,
    record_id: str,
    attributo: str,
    ruolo: str = "subject",
    noti: frozenset[str] | set[str] | None = None,
) -> Snak:
    ""





    r = riconosci(nome, noti)
    if r is None:
        return Valore(nome)
    aff = affermazione_di(source_file, record_id, attributo, ruolo)
    return ValoreIgnoto(
        id=id_ignoto(aff),
        affermazione=aff,
        famiglia=r.famiglia,
        motivo=r.motivo,
        testo=(nome or "").strip(),
        ancora=r.ancora,
    )







PERCORSO_SPEGNIMENTO = "meta/ignoto-OFF"




PERCORSO_DIARIO = "resolutions/ignoti.jsonl"


ENV_MODALITA = "SBK_IGNOTO"


@dataclass(frozen=True)
class DecisioneIgnoto:
    ""

    nome: str
    azione: str
    avrebbe: str
    entity_id: str = ""
    snak: object = None
    motivo: str = ""

    def come_riga(self, run_id: str = "") -> dict:
        import datetime as _dt

        s = self.snak
        return {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),  # noqa: UP017
            "run_id": run_id,
            "nome": self.nome,
            "azione": self.azione,
            "avrebbe": self.avrebbe,
            "entity_id_evitato": self.entity_id,
            "id_ignoto": getattr(s, "id", ""),
            "affermazione": getattr(s, "affermazione", ""),
            "famiglia": getattr(s, "famiglia", ""),
            "ancora": getattr(s, "ancora", ""),
            "motivo": self.motivo,
        }


class Sentinella:
    ""













    def __init__(
        self,
        *,
        modalita: str = "ombra",
        store=None,
        diario=None,
        run_id: str = "",
        noti: frozenset[str] | set[str] | None = None,
    ):
        if modalita not in ("ombra", "blocco"):
            raise ValueError(f"unknown mode: {modalita!r}")
        import datetime as _dt
        from pathlib import Path as _P

        self.modalita = modalita
        self.store = _P(store) if store else None
        self.diario = _P(diario) if diario else None
        self.run_id = run_id or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
        self.noti = noti or frozenset()
        self.conteggi: dict[str, int] = {
            "consultazioni": 0,
            "ruolo_nudo": 0,
            "possessivo": 0,
            "marcatore": 0,
            "non_coniati": 0,
            "spento": 0,
        }
        self._interruttore = (self.store / PERCORSO_SPEGNIMENTO) if self.store else None

    @property
    def spento(self) -> bool:
        return bool(self._interruttore and self._interruttore.exists())

    def al_conio(
        self,
        nome: str,
        *,
        source_file: str = "",
        record_id: str = "",
        attributo: str = "",
        ruolo: str = "subject",
        entity_id: str = "",
    ) -> DecisioneIgnoto:
        ""
        self.conteggi["consultazioni"] += 1
        r = riconosci(nome, self.noti)
        if r is None:
            return DecisioneIgnoto(nome, "conia", "conia", entity_id, None, "names someone")

        self.conteggi[r.famiglia] = self.conteggi.get(r.famiglia, 0) + 1
        aff = affermazione_di(source_file, record_id, attributo, ruolo)
        snak = ValoreIgnoto(
            id=id_ignoto(aff),
            affermazione=aff,
            famiglia=r.famiglia,
            motivo=r.motivo,
            testo=(nome or "").strip(),
            ancora=r.ancora,
        )

        if self.spento:
            self.conteggi["spento"] += 1
            d = DecisioneIgnoto(
                nome, "conia", "non_coniare", entity_id, snak, r.motivo + " · SWITCH"
            )
            self._diario(d)
            return d
        if self.modalita == "ombra":
            d = DecisioneIgnoto(nome, "conia", "non_coniare", entity_id, snak, r.motivo)
            self._diario(d)
            return d
        self.conteggi["non_coniati"] += 1
        d = DecisioneIgnoto(nome, "non_coniare", "non_coniare", entity_id, snak, r.motivo)
        self._diario(d)
        return d

    def _diario(self, d: DecisioneIgnoto) -> None:
        if not self.diario:
            return
        import json as _json

        self.diario.parent.mkdir(parents=True, exist_ok=True)
        with self.diario.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(d.come_riga(self.run_id), ensure_ascii=False) + "\n")

    def stats(self) -> dict:
        return {"modalita": self.modalita, "run_id": self.run_id, **self.conteggi}










def rileggi_diario(percorso) -> dict:
    ""
    import collections
    import json as _json
    from pathlib import Path as _P





    p = _P(percorso or PERCORSO_DIARIO)
    fuori = {
        "righe": 0,
        "illeggibili": 0,
        "famiglie": collections.Counter(),
        "nomi": collections.Counter(),
        "ignoti_distinti": set(),
        "entita_evitate": set(),
        "bloccati": 0,
    }




    if not _P(percorso or PERCORSO_DIARIO).exists():
        return fuori
    with p.open(encoding="utf-8") as fh:
        for riga in fh:
            riga = riga.strip()
            if not riga:
                continue
            fuori["righe"] += 1
            try:
                d = _json.loads(riga)
            except ValueError:
                fuori["illeggibili"] += 1
                continue
            fuori["famiglie"][d.get("famiglia", "?")] += 1
            fuori["nomi"][d.get("nome", "")] += 1
            if d.get("id_ignoto"):
                fuori["ignoti_distinti"].add(d["id_ignoto"])
            if d.get("entity_id_evitato"):
                fuori["entita_evitate"].add(d["entity_id_evitato"])
            if d.get("azione") == "non_coniare":
                fuori["bloccati"] += 1
    return fuori


def main() -> int:
    import argparse
    from pathlib import Path as _P

    ap = argparse.ArgumentParser(
        description="the ignoto: recognition and re-reading of the shadow run"
    )
    ap.add_argument("--prova", nargs="+", help="classify one or more names")
    ap.add_argument("--diario", help="summarizes a `resolutions/ignoti.jsonl`")
    a = ap.parse_args()

    if a.prova:
        for n in a.prova:
            r = riconosci(n)
            print(f"  {('IGNOTO ' + r.famiglia) if r else 'names someone':22s} «{n}»")
            if r:
                print(f"      {r.motivo}" + (f" · anchor: «{r.ancora}»" if r.ancora else ""))
        return 0

    if a.diario:
        d = rileggi_diario(_P(a.diario))
        print(f"\n  {a.diario}")
        print(f"  lines: {d['righe']:,} · unreadable: {d['illeggibili']}")
        print(f"  entities that would not have been born: {len(d['entita_evitate']):,}")
        print(f"  distinct ignoti (one per statement): {len(d['ignoti_distinti']):,}")
        print(f"  already blocked (block mode): {d['bloccati']:,}")
        print(f"  by family: {dict(d['famiglie'])}")
        print("\n  the twenty most frequent names:")
        for n, k in d["nomi"].most_common(20):
            print(f"    {k:>6}  «{n[:60]}»")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
