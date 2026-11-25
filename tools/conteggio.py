""








































































from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

__all__ = [
    "Conteggio",
    "FileIlleggibile",
    "LimiteNonRichiesto",
    "verifica_partizione",
]


class LimiteNonRichiesto(RuntimeError):
    ""







class FileIlleggibile(LimiteNonRichiesto):
    ""







def _saltati_puliti(saltati) -> MappingProxyType:
    ""
    if saltati is None:
        saltati = {}
    if not hasattr(saltati, "items"):
        raise TypeError(
            f"saltati must be a dict reason → count, not {type(saltati).__name__}"
        )
    pulito = {}
    for motivo, quanti in saltati.items():
        if not isinstance(motivo, str):
            raise TypeError(f"a skip reason is a readable string, not {motivo!r}")
        if isinstance(quanti, bool) or not isinstance(quanti, int):
            raise TypeError(f"saltati[{motivo!r}] must be an integer, not {quanti!r}")
        if quanti < 0:
            raise ValueError(f"saltati[{motivo!r}] = {quanti}: a negative skip does not exist")
        pulito[motivo] = quanti
    return MappingProxyType(pulito)


@dataclass(frozen=True)
class Conteggio:
    ""













    valore: int
    su: int


    saltati: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for nome in ("valore", "su"):
            n = getattr(self, nome)
            if isinstance(n, bool) or not isinstance(n, int):
                raise TypeError(f"{nome} must be an integer, not {n!r}")
            if n < 0:
                raise ValueError(f"{nome} = {n}: a negative count does not exist")




        object.__setattr__(self, "saltati", _saltati_puliti(self.saltati))

    @property
    def parziale(self) -> bool:
        ""
        return self.su == 0 or any(self.saltati.values())

    @property
    def quota(self) -> float | None:
        ""

        return None if self.su == 0 else self.valore / self.su

    def percentuale(self, cifre: int = 2) -> float | None:
        ""
        q = self.quota
        return None if q is None else round(q * 100, cifre)

    def __str__(self) -> str:
        p = f" ⚠️ PARZIALE — {dict(self.saltati)}" if self.parziale else ""
        return f"{self.valore:,} su {self.su:,}{p}"

    def come_dict(self) -> dict:
        ""




        return {
            "valore": self.valore,
            "su": self.su,
            "saltati": dict(self.saltati),
            "parziale": self.parziale,
        }

    @classmethod
    def da_dict(cls, d: dict) -> Conteggio:
        ""

        return cls(
            valore=int(d["valore"]),
            su=int(d["su"]),
            saltati=dict(d.get("saltati") or {}),
        )


def verifica_partizione(parti, su: int, nome: str = "partition") -> None:
    ""












    valori = [p.valore if isinstance(p, Conteggio) else int(p) for p in parti]
    totale = sum(valori)
    if totale != su:
        raise ValueError(
            f"{nome}: the classes sum to {totale:,} but the population is {su:,} "
            f"(gap {totale - su:+,}). The classes: {valori}"
        )
