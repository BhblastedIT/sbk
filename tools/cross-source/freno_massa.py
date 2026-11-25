""





























from __future__ import annotations

import logging

log = logging.getLogger("freno")






QUOTA_MASSIMA = 0.20



MINIMO_PER_CONTARE = 500


class TroppoDiMassa(RuntimeError):
    ""


def verifica_quota(
    tocca: int,
    totale: int,
    operazione: str,
    *,
    quota: float = QUOTA_MASSIMA,
    forza: bool = False,
    perche: str = "",
) -> float:
    ""






    if totale <= 0:
        return 0.0
    frazione = tocca / totale
    if totale < MINIMO_PER_CONTARE or frazione <= quota:
        return frazione
    if forza:
        if not perche.strip():
            raise TroppoDiMassa(
                f"{operazione}: forza=True without `perche`. An override without a written "
                "reason is not a decision."
            )
        log.warning(
            "BRAKE OVERRIDDEN — %s touches %s of %s (%.1f%%). Reason: %s",
            operazione,
            f"{tocca:,}",
            f"{totale:,}",
            frazione * 100,
            perche,
        )
        return frazione
    raise TroppoDiMassa(
        f"{operazione} touches {tocca:,} of {totale:,} — that is {frazione * 100:.1f}%, "
        f"over the {quota * 100:.0f}% cap.\n"
        "  Above this quota it is more likely that the pipeline is broken than that the "
        "world changed: an empty source, a join that does not match, an inverted filter.\n"
        "  Look FIRST at what changed upstream. If the decision is intended, pass "
        "forza=True with the written reason."
    )
