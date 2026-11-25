""


































































from __future__ import annotations

import functools
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import NamedTuple




SOGLIA_COPERTURA = 0.75

SOGLIA_DENSITA = 1 / 3



FINESTRA_TURNI = 3

ESATTO = "ESATTO"
FUZZY = "FUZZY"








_LETTERE = r"[^\W\d_]+"
_CIFRE = r"\d+"

_SIMBOLI = r"([^\w\s]|_)\1*"
_TOKEN = re.compile(rf"{_LETTERE}|{_CIFRE}|{_SIMBOLI}")


@functools.lru_cache(maxsize=10000)
def normalizza(token: str) -> str:
    ""
    token = token.lower()
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


def tokenizza(testo: str) -> tuple[list[str], list[int], list[int]]:
    ""
    bassi: list[str] = []
    inizi: list[int] = []
    fini: list[int] = []
    for m in _TOKEN.finditer(testo):
        bassi.append(m.group(0).lower())
        inizi.append(m.start())
        fini.append(m.end())
    return bassi, inizi, fini





class _Span(NamedTuple):
    ""

    combaciano: int
    inizio: int
    fine: int

    @property
    def lunghezza(self) -> int:
        return 0 if self.inizio < 0 else self.fine - self.inizio + 1


def _occorrenze(sorgente: list[str], estratto: list[str]) -> list[int]:
    ""
    n, m = len(sorgente), len(estratto)
    if m == 0 or n < m:
        return []
    primo = estratto[0]
    return [
        i
        for i in range(n - m + 1)

        if sorgente[i] == primo and sorgente[i : i + m] == estratto
    ]


def _span_lcs(sorgente: list[str], estratto: list[str]) -> dict[int, _Span]:
    ""









    n, m = len(sorgente), len(estratto)
    if n == 0 or m == 0:
        return {}


    riga_prec = [[-1] * (m + 1) for _ in range(m + 1)]
    riga_corr = [[-1] * (m + 1) for _ in range(m + 1)]
    for j in range(m + 1):
        riga_prec[j][0] = 0

    migliori: dict[int, _Span] = {}

    for i in range(1, n + 1):
        tok = sorgente[i - 1]
        riga_corr[0][0] = i
        for k in range(1, m + 1):
            riga_corr[0][k] = -1

        for j in range(1, m + 1):
            riga_corr[j][0] = i
            combacia = tok == estratto[j - 1]
            for k in range(1, m + 1):
                salta_sorgente = riga_prec[j][k]
                salta_estratto = riga_corr[j - 1][k]
                meglio = salta_sorgente if salta_sorgente > salta_estratto else salta_estratto
                if combacia:
                    cand = i - 1 if k == 1 else riga_prec[j - 1][k - 1]
                    if cand > meglio:
                        meglio = cand
                riga_corr[j][k] = meglio

        fine = i - 1
        for k in range(1, m + 1):
            s = riga_corr[m][k]
            if s < 0:
                continue
            gia = migliori.get(k)
            if gia is None:
                migliori[k] = _Span(combaciano=k, inizio=s, fine=fine)
                continue
            nuova = fine - s + 1
            if nuova < gia.lunghezza or (nuova == gia.lunghezza and s < gia.inizio):
                migliori[k] = _Span(combaciano=k, inizio=s, fine=fine)

        riga_prec, riga_corr = riga_corr, riga_prec

    return migliori


def _accetta(
    span: _Span,
    lunghezza_estratto: int,
    copertura: float = SOGLIA_COPERTURA,
    densita: float = SOGLIA_DENSITA,
) -> bool:
    ""






    if span.combaciano == 0 or lunghezza_estratto == 0 or span.lunghezza <= 0:
        return False
    servono = math.ceil(lunghezza_estratto * copertura)
    return span.combaciano >= servono and span.combaciano / span.lunghezza >= densita





@dataclass(frozen=True)
class Ancora:
    ""

    char_start: int
    char_end: int
    stato: str
    copertura: float
    densita: float

    turno: int | None = None

    speaker: str = ""

    occorrenze: int = 1

    @property
    def e_citazione(self) -> bool:
        ""

        return self.stato == ESATTO





class Documento:
    ""





    __slots__ = ("testo", "bassi", "inizi", "fini", "norm")

    def __init__(self, testo: str) -> None:
        self.testo = testo
        self.bassi, self.inizi, self.fini = tokenizza(testo)
        self.norm = [normalizza(t) for t in self.bassi]

    def __len__(self) -> int:
        return len(self.bassi)


def ancora(doc: Documento, citazione: str) -> Ancora | None:
    ""





    if not citazione or not doc.bassi:
        return None
    bassi, _, _ = tokenizza(citazione)
    m = len(bassi)
    if m == 0:
        return None

    occ = _occorrenze(doc.bassi, bassi)
    if occ:
        i = occ[0]
        return Ancora(
            char_start=doc.inizi[i],
            char_end=doc.fini[i + m - 1],
            stato=ESATTO,
            copertura=1.0,
            densita=1.0,
            occorrenze=len(occ),
        )

    norm = [normalizza(t) for t in bassi]
    span_per_k = _span_lcs(doc.norm, norm)
    for k in sorted(span_per_k, reverse=True):
        c = span_per_k[k]
        if _accetta(c, m):
            return Ancora(
                char_start=doc.inizi[c.inizio],
                char_end=doc.fini[c.fine],
                stato=FUZZY,
                copertura=c.combaciano / m,
                densita=c.combaciano / max(1, c.lunghezza),
            )
    return None





_RIGA_TURNO = re.compile(r"^\s*([^:\n]{1,60}?)\s*:\s*(.*)$")


@dataclass(frozen=True)
class Turno:
    speaker: str
    testo: str

    inizio: int


class DocTurni:
    ""







    __slots__ = ("testo", "turni", "_tok", "_indice")

    def __init__(self, testo: str) -> None:
        self.testo = testo
        self.turni: list[Turno] = []
        self._tok: list[tuple[list[str], list[int], list[int], list[str]]] = []
        self._indice: dict[str, set[int]] = {}

        pos = 0
        for riga in testo.split("\n"):
            m = _RIGA_TURNO.match(riga)
            if m and m.group(2).strip():


                self.turni.append(Turno(m.group(1).strip(), m.group(2).rstrip(), pos + m.start(2)))
            elif riga.strip():
                scarto = len(riga) - len(riga.lstrip())
                self.turni.append(Turno("", riga.strip(), pos + scarto))
            pos += len(riga) + 1

        for i, t in enumerate(self.turni):
            bassi, inizi, fini = tokenizza(t.testo)
            norm = [normalizza(x) for x in bassi]
            inizi = [x + t.inizio for x in inizi]
            fini = [x + t.inizio for x in fini]
            self._tok.append((bassi, inizi, fini, norm))
            for x in norm:
                self._indice.setdefault(x, set()).add(i)

    def __len__(self) -> int:
        return len(self.turni)

    def ancora(self, citazione: str, finestra: int = FINESTRA_TURNI) -> Ancora | None:
        ""






        if not citazione or not self.turni:
            return None
        bassi, _, _ = tokenizza(citazione)
        m = len(bassi)
        if m == 0:
            return None
        norm = [normalizza(t) for t in bassi]
        servono = math.ceil(m * SOGLIA_COPERTURA)
        conta_cit = Counter(norm)

        candidati: set[int] = set()
        for t in set(norm):
            candidati |= self._indice.get(t, set())
        if not candidati:
            return None

        migliore: Ancora | None = None




        for larghezza in range(1, finestra + 1):
            for i in sorted(candidati):
                if i + larghezza > len(self.turni):
                    continue
                fetta = self._tok[i : i + larghezza]
                b = [x for f in fetta for x in f[0]]
                if len(b) < servono:
                    continue




                n_norm = [x for f in fetta for x in f[3]]
                conta_fin = Counter(n_norm)
                comuni = sum(min(v, conta_fin[k]) for k, v in conta_cit.items())
                if comuni < servono:
                    continue
                ini = [x for f in fetta for x in f[1]]
                fin = [x for f in fetta for x in f[2]]

                occ = _occorrenze(b, bassi)
                if occ:
                    j = occ[0]
                    return self._ancora(
                        ini[j], fin[j + m - 1], ESATTO, 1.0, 1.0, occorrenze=len(occ)
                    )
                if migliore is not None:
                    continue
                span_per_k = _span_lcs(n_norm, norm)
                for k in sorted(span_per_k, reverse=True):
                    c = span_per_k[k]
                    if _accetta(c, m):
                        migliore = self._ancora(
                            ini[c.inizio],
                            fin[c.fine],
                            FUZZY,
                            c.combaciano / m,
                            c.combaciano / max(1, c.lunghezza),
                        )
                        break
        return migliore

    def _ancora(
        self,
        cs: int,
        ce: int,
        stato: str,
        copertura: float,
        densita: float,
        occorrenze: int = 1,
    ) -> Ancora:
        ""


        turno = 0
        for k, t in enumerate(self.turni):
            if t.inizio > cs:
                break
            turno = k
        return Ancora(
            char_start=cs,
            char_end=ce,
            stato=stato,
            copertura=copertura,
            densita=densita,
            turno=turno,
            speaker=self.turni[turno].speaker,
            occorrenze=occorrenze,
        )
