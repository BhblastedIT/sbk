""

































































































































































from __future__ import annotations








NORMALE = "normal"



PREFERITO = "preferred"



RETROCESSO = "deprecated"


RANGHI = (RETROCESSO, NORMALE, PREFERITO)
ORDINE = {RETROCESSO: -1, NORMALE: 0, PREFERITO: 1}


CAMPO = "rank"





EFFETTO_RETROCEDE = "drop"


def esigi_rango_noto(valore) -> str:
    ""









    v = str(valore or "").strip().lower()
    if v in ORDINE:
        return v
    raise ValueError(
        "rank {!r} outside the three allowed ({}). Do not add a fourth rank: "
        "Wikibase had `RANK_TRUTH` (July 2013) and dismantled it in twenty months, and "
        "facts at confidence 1.0 are already that rank reborn under another name "
        "— read them as «one source says it and nobody contradicts it», not as «true».".format(
            valore, ", ".join(RANGHI)
        )
    )


def rango(fatto) -> str:
    ""










    f = fatto if isinstance(fatto, dict) else {}
    r = f.get("ritiro")
    if isinstance(r, dict) and str(r.get("effetto") or "").strip().lower() == EFFETTO_RETROCEDE:
        return RETROCESSO
    grezzo = f.get(CAMPO)
    if grezzo is None or str(grezzo).strip() == "":
        return NORMALE
    return esigi_rango_noto(grezzo)


def valore_rango(fatto) -> int:
    ""
    return ORDINE[rango(fatto)]


def e_promosso(fatto) -> bool:
    return rango(fatto) == PREFERITO


def e_default(fatto) -> bool:
    ""
    return rango(fatto) == NORMALE







def migliori(fatti) -> list:
    ""











    fatti = [f for f in (fatti or []) if isinstance(f, dict)]
    if not fatti:
        return []
    attributi = {str(f.get("attribute") or "") for f in fatti}
    if len(attributi) > 1:
        raise ValueError(
            "migliori() wants the facts of ONE property only, it got {}: {}. "
            "Best rank is computed per property, not per entity — a `preferred` on one "
            "attribute must not silence the others. For a mixed list: vista_potata().".format(
                len(attributi), ", ".join(sorted(attributi)[:5])
            )
        )
    vivi = [f for f in fatti if rango(f) != RETROCESSO]
    if not vivi:
        return []
    alto = max(valore_rango(f) for f in vivi)
    return [f for f in vivi if valore_rango(f) == alto]


def vista_potata(fatti) -> list:
    ""





    per_attributo = {}
    for f in fatti or []:
        if not isinstance(f, dict):
            continue
        per_attributo.setdefault(str(f.get("attribute") or ""), []).append(f)
    tenuti = []
    for gruppo in per_attributo.values():
        tenuti.extend(migliori(gruppo))

    tenuti_id = {id(f) for f in tenuti}
    return [f for f in fatti or [] if isinstance(f, dict) and id(f) in tenuti_id]


def vista_completa(fatti) -> list:
    ""

    return [f for f in fatti or [] if isinstance(f, dict)]







def _valore_normalizzato(v) -> str:
    ""


    return str(v).strip().lower() if v is not None else ""


def chiave_asserzione(fatto) -> tuple:
    ""









    f = fatto if isinstance(fatto, dict) else {}
    return (
        str(f.get("entity_id") or ""),
        str(f.get("attribute") or ""),
        _valore_normalizzato(f.get("value")),
    )


def impronta_versione(fatto) -> tuple:
    ""





    return chiave_asserzione(fatto) + (rango(fatto),)


def sono_la_stessa_versione(a, b) -> bool:
    ""

    return impronta_versione(a) == impronta_versione(b)


def rango_sopravvissuto(fatti) -> str:
    ""















    fatti = [f for f in (fatti or []) if isinstance(f, dict)]
    if not fatti:
        return NORMALE
    vivi = [f for f in fatti if rango(f) != RETROCESSO]
    if not vivi:
        return RETROCESSO
    return RANGHI[max(valore_rango(f) for f in vivi) + 1]





















TEMPO = "tempo"







CONFIDENZA = "confidenza"

















OSSERVAZIONI = "osservazioni"

CRITERI = (TEMPO, CONFIDENZA, OSSERVAZIONI)



















PESO_FONTE_NON_E_UN_CRITERIO = True



SOLO_UN_VALORE = "fewer than two distinct live values"
VALORI_ANNIDATI = "nested values: it's a collapse, not a competition"
NON_FUNZIONALE = "the attribute is not declared functional: rank does not apply"
PARITA = "no criterion breaks the tie"
VALORE_IGNOTO = "the leading candidate is an ignorance marker"

MOTIVI_ASTENSIONE = (SOLO_UN_VALORE, VALORI_ANNIDATI, NON_FUNZIONALE, PARITA, VALORE_IGNOTO)


def in_gara(fatto) -> bool:
    ""






    f = fatto if isinstance(fatto, dict) else {}
    return not (
        f.get("expired_at") or f.get("ritiro") or f.get("valid_to") or f.get("superseded_by")
    )


def fonti_indipendenti(fatto) -> int:
    ""







    f = fatto if isinstance(fatto, dict) else {}
    distinte = {
        (str((o or {}).get("source_file") or ""), str((o or {}).get("record_id") or ""))
        for o in (f.get("observations") or [])
        if isinstance(o, dict) and (o or {}).get("record_id")
    }
    return max(1, len(distinte))


def _valori_annidati(valori) -> bool:
    ""

























    puliti = sorted({_solo_lettere(v) for v in valori if _solo_lettere(v)}, key=len)
    for i in range(len(puliti)):
        for j in range(i + 1, len(puliti)):
            if puliti[i] in puliti[j]:
                return True
    compatti = sorted({p.replace(" ", "") for p in puliti if p.replace(" ", "")}, key=len)


    for i in range(len(compatti)):
        for j in range(i + 1, len(compatti)):
            if len(compatti[i]) >= 3 and compatti[i] in compatti[j]:
                return True
    if len(compatti) < len(puliti):
        return True
    return False


def _solo_lettere(v) -> str:
    fuori = []
    for ch in str(v or "").lower():
        fuori.append(ch if (ch.isalnum()) else " ")
    return " ".join("".join(fuori).split())


class Verdetto:
    ""

    __slots__ = ("esito", "criterio", "motivo", "vincitore", "perdenti")

    PROMUOVI = "promuovi"
    ASTIENITI = "astensione"

    def __init__(self, esito, criterio="", motivo="", vincitore=None, perdenti=None):
        self.esito = esito
        self.criterio = criterio
        self.motivo = motivo
        self.vincitore = vincitore
        self.perdenti = perdenti or []

    def __bool__(self):
        return self.esito == self.PROMUOVI

    def __repr__(self):  # pragma: no cover - diagnostics
        return f"Verdetto({self.esito!r}, {self.criterio or self.motivo!r})"


def arbitra(fatti, *, e_funzionale=None, marcatori=None) -> Verdetto:
    ""










    fatti = [f for f in (fatti or []) if isinstance(f, dict)]
    if not fatti:
        return Verdetto(Verdetto.ASTIENITI, motivo=SOLO_UN_VALORE)

    attributi = {str(f.get("attribute") or "") for f in fatti}
    if len(attributi) > 1:
        raise ValueError(
            f"arbitra() wants the facts of ONE property only, it got {len(attributi)}. "
            "Rank is arbitrated per property."
        )
    attributo = next(iter(attributi))

    if e_funzionale is None:
        from knowledge_taxonomy import e_funzionale as _ef  # noqa: PLC0415

        e_funzionale = _ef
    if not e_funzionale(attributo):



        return Verdetto(Verdetto.ASTIENITI, motivo=NON_FUNZIONALE)

    gara = [f for f in fatti if in_gara(f)]
    valori = {_valore_normalizzato(f.get("value")) for f in gara}
    if len(valori) < 2:
        return Verdetto(Verdetto.ASTIENITI, motivo=SOLO_UN_VALORE)
    if _valori_annidati(valori):
        return Verdetto(Verdetto.ASTIENITI, motivo=VALORI_ANNIDATI)

    chiavi = {
        TEMPO: (lambda f: str(f.get("valid_from") or ""))
        if all(f.get("valid_from") for f in gara)
        else None,
        CONFIDENZA: lambda f: float(f.get("confidence") or 0.0),
        OSSERVAZIONI: fonti_indipendenti,
    }
    for criterio in CRITERI:
        chiave = chiavi[criterio]
        if chiave is None:
            continue
        punteggi = [chiave(f) for f in gara]
        alto = max(punteggi)
        testa = [f for f, p in zip(gara, punteggi) if p == alto]
        if len({_valore_normalizzato(f.get("value")) for f in testa}) != 1:
            continue
        if _e_marcatore(testa[0].get("value"), marcatori):
            return Verdetto(Verdetto.ASTIENITI, motivo=VALORE_IGNOTO)




        vinto = _valore_normalizzato(testa[0].get("value"))
        gemelli = [f for f in gara if _valore_normalizzato(f.get("value")) == vinto]
        alto_gemelli = max(chiave(f) for f in gemelli)
        vincitore = sorted(
            (f for f in gemelli if chiave(f) == alto_gemelli),
            key=lambda f: str(f.get("fact_id") or ""),
        )[0]
        perdenti = [f for f in gara if _valore_normalizzato(f.get("value")) != vinto]
        return Verdetto(
            Verdetto.PROMUOVI, criterio=criterio, vincitore=vincitore, perdenti=perdenti
        )
    return Verdetto(Verdetto.ASTIENITI, motivo=PARITA)


def _e_marcatore(valore, marcatori=None) -> bool:
    ""






    if marcatori is None:
        try:
            from ignoto import MARCATORI as marcatori  # noqa: PLC0415
        except ImportError:  # pragma: no cover - outside the repo
            return False
    parole = [p for p in _solo_lettere(valore).split() if p]
    return bool(parole) and all(p in marcatori for p in parole)







PROMOSSO = "promosso"
GIA_PROMOSSO = "gia-promosso"


class Esito:
    ""

    __slots__ = ("stato", "perche", "prima", "criterio")

    def __init__(self, stato, perche="", prima=None, criterio=""):
        self.stato = stato
        self.perche = perche
        self.prima = prima or {}
        self.criterio = criterio

    def __bool__(self):
        return self.stato == PROMOSSO

    def __repr__(self):  # pragma: no cover - diagnostics
        return f"Esito({self.stato!r}, {self.perche!r})"


def pre_image_rango(fatto) -> dict:
    ""





    f = fatto if isinstance(fatto, dict) else {}
    return {CAMPO: {"c_era": CAMPO in f, "valore": f.get(CAMPO)}}


def applica_promozione(fatto, *, gruppo, criterio, da, perche="") -> Esito:
    ""





















    if not isinstance(fatto, dict):
        raise TypeError("applica_promozione wants a fact's dictionary")
    if criterio not in CRITERI:
        raise ValueError(
            "criterion {!r} outside the three declared ({}). Whoever promotes writes WHY: a "
            "promotion without a criterion is an opinion that looks like a rule.".format(
                criterio, ", ".join(CRITERI)
            )
        )
    if not str(da or "").strip():
        raise ValueError("da missing: whoever promotes is recorded")

    gruppo = [f for f in (gruppo or []) if isinstance(f, dict)]
    if fatto not in gruppo:
        gruppo = gruppo + [fatto]
    valori = {_valore_normalizzato(f.get("value")) for f in gruppo if in_gara(f)}
    if len(valori) < 2:
        raise ValueError(
            f"no promotion: the fact is not in competition ({len(valori)} distinct live value in the "
            "group). `preferred` is for choosing among several values; on a single value it "
            "says nothing and costs a write — `Help:Ranking` T:13."
        )

    gia = rango(fatto)
    if gia == PREFERITO:
        return Esito(GIA_PROMOSSO, "already at preferred rank")
    if gia == RETROCESSO:
        raise ValueError(
            "the fact carries a `ritiro` with DROP effect: it is deprecated, and promoting it "
            "would mean saying two opposite things with two different fields. If the tombstone is "
            "wrong you discuss the tombstone (R5: the first wins), you do not bypass it."
        )

    prima = pre_image_rango(fatto)
    fatto[CAMPO] = PREFERITO
    return Esito(PROMOSSO, prima=prima, criterio=criterio, perche=str(perche or ""))


def promuovi(fatto, *, incremento, entity_id, gruppo, criterio, da=None, perche=""):
    ""







    if incremento is None:
        raise ValueError(
            "promuovi(): an open `Incremento` is required. Rank is reversible by construction "
            "(you remove a key), but reversible-in-theory is precisely what the "
            "five mechanisms that died before this one were. See tools/cross-source/incremento.py"
        )
    if not hasattr(incremento, "promuovi_fatto"):
        raise TypeError(
            "the object passed as `incremento` cannot record a promotion "
            "(missing `promuovi_fatto`): it is not an Incremento"
        )
    autore = da or getattr(incremento, "script", "") or ""
    if rango(fatto) == PREFERITO:


        return Esito(GIA_PROMOSSO, "already at preferred rank")
    incremento.promuovi_fatto(
        fatto,
        entity_id=entity_id,
        criterio=criterio,
        prima=pre_image_rango(fatto),
        perche=perche,
    )
    return applica_promozione(fatto, gruppo=gruppo, criterio=criterio, da=autore, perche=perche)







def promozioni_illecite(fatti, *, e_funzionale=None) -> list:
    ""















    if e_funzionale is None:
        from knowledge_taxonomy import e_funzionale as _ef  # noqa: PLC0415

        e_funzionale = _ef
    gruppi = {}
    for f in fatti or []:
        if not isinstance(f, dict):
            continue
        chiave = (str(f.get("entity_id") or ""), str(f.get("attribute") or ""))
        gruppi.setdefault(chiave, []).append(f)

    fuori = []
    for (eid, attributo), gruppo in sorted(gruppi.items()):
        promossi = [f for f in gruppo if rango(f) == PREFERITO]
        if not promossi:
            continue
        if len(promossi) > 1:
            fuori.append((eid, attributo, f"{len(promossi)} `preferred` facts in the same group"))
        if not e_funzionale(attributo):
            fuori.append((eid, attributo, "`preferred` on a non-functional attribute"))
        valori = {_valore_normalizzato(f.get("value")) for f in gruppo if in_gara(f)}
        if len(valori) < 2:
            fuori.append((eid, attributo, "`preferred` without competition: a single value"))
    return fuori


__all__ = [
    "CAMPO",
    "CONFIDENZA",
    "CRITERI",
    "MOTIVI_ASTENSIONE",
    "NORMALE",
    "ORDINE",
    "OSSERVAZIONI",
    "PREFERITO",
    "RANGHI",
    "RETROCESSO",
    "TEMPO",
    "Esito",
    "Verdetto",
    "applica_promozione",
    "arbitra",
    "chiave_asserzione",
    "e_default",
    "e_promosso",
    "esigi_rango_noto",
    "fonti_indipendenti",
    "impronta_versione",
    "in_gara",
    "migliori",
    "pre_image_rango",
    "promozioni_illecite",
    "promuovi",
    "rango",
    "rango_sopravvissuto",
    "sono_la_stessa_versione",
    "valore_rango",
    "vista_completa",
    "vista_potata",
]
