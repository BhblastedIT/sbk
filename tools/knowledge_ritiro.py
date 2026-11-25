""




































































































from __future__ import annotations

from datetime import datetime, timezone  # noqa: UP017

UTC = timezone.utc  # noqa: UP017








REWIND = "rewind"




DROP = "drop"

EFFETTI = (REWIND, DROP)






SMENTITO = "smentito"
SOSTITUITO = "sostituito"
RIATTRIBUITO = "riattribuito"
SCARTATO = "scartato"

TIPI = (SMENTITO, SOSTITUITO, RIATTRIBUITO, SCARTATO)
























VERSO_VIETATO = "vietato"
VERSO_FATTO = "fact_id"
VERSO_ENTITA = "entity_id"

MOTIVI = {
    "sostituito_da_fatto_piu_recente": {
        "tipo": SOSTITUITO,
        "effetto": REWIND,
        "verso": VERSO_FATTO,
        "cosa_dice": "another assertion takes the place of this one from that day",
        "caso": (
            "`xs_knowledge_conflict.apply_resolution` with `recommended_action=expire_old`: "
            "today it writes a bare `expired_at`, with no reason, no pointer and no journal"
        ),
    },
    "smentito_da_fonte": {
        "tipo": SMENTITO,
        "effetto": REWIND,
        "verso": VERSO_VIETATO,
        "cosa_dice": "no longer true, and the real-world end date remains unknown",
        "caso": (
            "the departure lexicon of `knowledge_view.dice_uscita()`: «Terminated (ex-employee)» "
            "declares a departure and carries no departure date — timeless by construction"
        ),
    },
    "riattribuito_ad_altro_soggetto": {
        "tipo": RIATTRIBUITO,
        "effetto": REWIND,
        "verso": VERSO_ENTITA,
        "cosa_dice": "the fact **stays true**: it does not belong to this record",
        "caso": (
            "a record that by mistake merged several people: its facts **stay "
            "true**, they just belong to another person — and the only available channel "
            "to say so was the one that means «no longer true»"
        ),
    },
    "errore_di_estrazione": {
        "tipo": SCARTATO,
        "effetto": DROP,
        "verso": VERSO_VIETATO,
        "cosa_dice": "was never true: the model or the parser produced a false assertion",
        "caso": (
            "the only legitimate DROP. It has never yet been written to the store: today a "
            "wrong fact is either deleted (and the evidence disappears) or left (and stays true)"
        ),
    },
    "duplicato_della_stessa_asserzione": {
        "tipo": SCARTATO,
        "effetto": DROP,
        "verso": VERSO_FATTO,
        "cosa_dice": "it was not a second fact: it was the same one, counted twice",
        "caso": (
            "the collapse by `assertion_hash` (point ⑫): the duplicate was never "
            "an assertion of its own, so it has no past in which it held alone. `verso` "
            "names the surviving twin, so the duplicate's source stays reachable"
        ),
    },
}


def motivi() -> tuple:
    ""
    return tuple(sorted(MOTIVI))


def descrivi(motivo: str) -> dict:
    ""
    return dict(MOTIVI.get(str(motivo or ""), {}))


def esigi_motivo_noto(motivo) -> dict:
    ""





    if not motivo or not str(motivo).strip():
        raise ValueError(
            "the demotion reason is mandatory: a fact that stops being valid "
            "without a reason attached is a deletion by another name. "
            "Allowed reasons: " + ", ".join(motivi())
        )
    voce = MOTIVI.get(str(motivo))
    if voce is None:
        raise ValueError(
            "reason outside the closed taxonomy: {!r}. Allowed: {}. "
            "If a new reason is needed it is added HERE, with its type, its effect and the "
            "real case it comes from — you do not pass a free string.".format(
                motivo, ", ".join(motivi())
            )
        )
    return dict(voce)







def oggi_iso() -> str:
    ""
    return datetime.now(UTC).date().isoformat()


def e_giorno(valore) -> bool:
    ""








    s = str(valore or "")
    if len(s) != 10:
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")  # noqa: DTZ007 — it is a date, not an instant
    except ValueError:
        return False
    return True












PREFISSI_ENTITA = (
    "person_",
    "organization_",
    "org_",
    "deal_",
    "commitment_",
)


def _pare_un_fact_id(valore) -> bool:
    ""




    v = str(valore or "")
    if not v or v.startswith(PREFISSI_ENTITA):
        return False
    if v.startswith("f:") and len(v) > 2:
        return True
    pezzi = v.split("-")
    return len(pezzi) == 5 and all(
        len(p) == n and all(c in "0123456789abcdefABCDEF" for c in p)
        for p, n in zip(pezzi, (8, 4, 4, 4, 12))
    )


def costruisci_ritiro(*, motivo, da, quando=None, verso="", perche="") -> dict:
    ""





    voce = esigi_motivo_noto(motivo)
    blocco = {
        "motivo": str(motivo),
        "tipo": voce["tipo"],
        "effetto": voce["effetto"],
        "quando": str(quando) if quando else oggi_iso(),
        "verso": str(verso or ""),
        "da": str(da or ""),
        "perche": str(perche or ""),
    }
    violazioni = valida_ritiro(blocco)
    if violazioni:
        raise ValueError("invalid `ritiro` block — " + " · ".join(violazioni))
    return blocco


def valida_ritiro(blocco) -> list:
    ""






    fuori = []
    if not isinstance(blocco, dict):
        return ["the ritiro is not an object"]

    motivo = blocco.get("motivo")
    voce = MOTIVI.get(str(motivo or ""))
    if voce is None:
        fuori.append(
            "motivo={!r} outside the closed taxonomy (allowed: {})".format(
                motivo, ", ".join(motivi())
            )
        )

    tipo = blocco.get("tipo")
    if tipo not in TIPI:
        fuori.append("tipo={!r} is not one of {}".format(tipo, ", ".join(TIPI)))
    elif voce is not None and tipo != voce["tipo"]:
        fuori.append(
            "tipo={!r} is not the one for reason {!r} ({})".format(tipo, motivo, voce["tipo"])
        )

    effetto = blocco.get("effetto")
    if effetto not in EFFETTI:
        fuori.append("effetto={!r} is not one of {}".format(effetto, ", ".join(EFFETTI)))
    elif voce is not None and effetto != voce["effetto"]:
        fuori.append(
            "effetto={!r} is not the one for reason {!r} ({})".format(
                effetto, motivo, voce["effetto"]
            )
        )

    quando = blocco.get("quando")
    if not quando:
        fuori.append(
            "quando missing: a ritiro without a date is not reconstructible, and the view will tell "
            "the reader instead of silently treating it as a DROP"
        )
    elif not e_giorno(quando):
        fuori.append(
            f"quando={quando!r} is not a `YYYY-MM-DD` day. The REWIND we have is at day granularity: "
            "a timestamp would assert an ordering over events that does not exist "
            "(`extracted_at` is often just the script's time)"
        )

    if not str(blocco.get("da") or "").strip():
        fuori.append("da missing: whoever retracts is recorded")

    verso = str(blocco.get("verso") or "")
    atteso = voce["verso"] if voce is not None else None
    if atteso == VERSO_VIETATO and verso:
        fuori.append(f"verso={verso!r} on a reason that points to nothing ({motivo})")
    elif atteso == VERSO_FATTO:
        if not verso:
            fuori.append(f"verso missing: {motivo!r} must name the fact_id")
        elif not _pare_un_fact_id(verso):
            fuori.append(
                f"verso={verso!r} must be a fact_id (UUID or 'f:…'), not an entity_id: "
                "it is a typical mistake in `superseded_by`"
            )
    elif atteso == VERSO_ENTITA:
        if not verso:
            fuori.append(f"verso missing: {motivo!r} must name the entity_id")
        elif not verso.startswith(PREFISSI_ENTITA):
            fuori.append(f"verso={verso!r} must be an entity_id (person_…, organization_…)")
    return fuori











CAMPI_LAPIDE = ("expired_at", "ritiro", "superseded_by", "superseded_at")


def pre_image_lapide(fatto) -> dict:
    ""







    f = fatto if isinstance(fatto, dict) else {}
    return {campo: {"c_era": campo in f, "valore": f.get(campo)} for campo in CAMPI_LAPIDE}


def gia_ritirato(fatto) -> tuple:
    ""





    if not isinstance(fatto, dict):
        return False, ""
    if fatto.get("ritiro"):
        r = fatto["ritiro"]
        quando = r.get("quando") if isinstance(r, dict) else ""
        motivo = r.get("motivo") if isinstance(r, dict) else ""
        return True, "already retracted on {} ({})".format(quando or "?", motivo or "?")
    if fatto.get("expired_at"):
        return True, "already expired on {} (tombstone without a `ritiro` block)".format(
            str(fatto["expired_at"])[:10]
        )
    return False, ""








RITIRATO = "ritirato"
GIA_RITIRATO = "gia-ritirato"
RIFIUTATO = "rifiutato"


class Esito:
    ""

    __slots__ = ("stato", "perche", "ritiro", "prima")

    def __init__(self, stato, perche="", ritiro=None, prima=None):
        self.stato = stato
        self.perche = perche
        self.ritiro = ritiro
        self.prima = prima or {}

    def __bool__(self):
        return self.stato == RITIRATO

    def __repr__(self):  # pragma: no cover - diagnostics
        return f"Esito({self.stato!r}, {self.perche!r})"


def applica_ritiro(fatto, *, motivo, da, quando=None, verso="", perche="") -> Esito:
    ""




















    if not isinstance(fatto, dict):
        raise TypeError("applica_ritiro wants a fact dictionary")

    blocco = costruisci_ritiro(motivo=motivo, da=da, quando=quando, verso=verso, perche=perche)

    vecchia, spiega = gia_ritirato(fatto)
    if vecchia:


        return Esito(GIA_RITIRATO, spiega, prima={})

    prima = pre_image_lapide(fatto)

    if blocco["tipo"] == SOSTITUITO:
        fatto["superseded_by"] = blocco["verso"]
        fatto["superseded_at"] = blocco["quando"]
        violazioni = _violazioni_supersessione(fatto)
        if violazioni:  # pragma: no cover - building the block prevents them
            raise ValueError("malformed supersession after the retraction — " + " · ".join(violazioni))

    fatto["expired_at"] = blocco["quando"]
    fatto["ritiro"] = blocco
    return Esito(RITIRATO, "", ritiro=blocco, prima=prima)


def _violazioni_supersessione(fatto) -> list:
    ""






    try:
        import sys
        from pathlib import Path

        radice = Path(__file__).resolve().parent / "cross-source"
        if str(radice) not in sys.path:
            sys.path.insert(0, str(radice))
        import knowledge_schema
    except ImportError:  # pragma: no cover
        return []
    return knowledge_schema.valida_supersessione(fatto)







def ritira(fatto, *, incremento, entity_id, motivo, da=None, quando=None, verso="", perche=""):
    ""















    if incremento is None:
        raise ValueError(
            "ritira(): an open `Incremento` is required. Writing `expired_at` without a journal is "
            "PNR-3: the tombstone becomes irreversible the instant it touches the disk, and it is "
            "how the other five reversibility mechanisms died. "
            "See tools/cross-source/incremento.py"
        )
    if not hasattr(incremento, "ritira_fatto"):
        raise TypeError(
            "the object passed as `incremento` cannot record a retraction "
            "(missing `ritira_fatto`): it is not an Incremento"
        )

    autore = da or getattr(incremento, "script", "") or ""
    blocco = costruisci_ritiro(motivo=motivo, da=autore, quando=quando, verso=verso, perche=perche)

    vecchia, spiega = gia_ritirato(fatto)
    if vecchia:



        return Esito(GIA_RITIRATO, spiega)

    incremento.ritira_fatto(
        fatto,
        entity_id=entity_id,
        ritiro=blocco,
        prima=pre_image_lapide(fatto),
    )
    return applica_ritiro(
        fatto,
        motivo=motivo,
        da=autore,
        quando=blocco["quando"],
        verso=verso,
        perche=perche,
    )







def incoerenze(fatti) -> list:
    ""







    fuori = []
    for f in fatti or []:
        if not isinstance(f, dict):
            continue
        r = f.get("ritiro")
        if not r:
            continue
        if not isinstance(r, dict):
            fuori.append((f.get("fact_id"), "the ritiro is not an object"))
            continue
        violazioni = valida_ritiro(r)
        if violazioni:
            fuori.append((f.get("fact_id"), " · ".join(violazioni)))
            continue
        exp = str(f.get("expired_at") or "")[:10]
        if exp != r.get("quando"):
            fuori.append(
                (
                    f.get("fact_id"),
                    "expired_at={!r} != ritiro.quando={!r}".format(exp, r.get("quando")),
                )
            )
    return fuori
