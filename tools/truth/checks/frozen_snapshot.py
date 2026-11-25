""






from __future__ import annotations

import pandas as pd

from .base import (
    DEFAULT_DATE_COLUMNS,
    DEFAULT_FLOOR,
    CheckResult,
    CheckStatus,
    coerce_as_of,
    pool_content_dates,
)

__all__ = ["check_frozen_snapshot"]


def check_frozen_snapshot(
    df: pd.DataFrame,
    *,
    previous_max_date=None,
    target: str = "",
    date_columns: tuple[str, ...] | list[str] = DEFAULT_DATE_COLUMNS,
    as_of=None,
    floor=DEFAULT_FLOOR,
) -> CheckResult:
    ""






    as_of_dt = coerce_as_of(as_of)
    cd = pool_content_dates(df, date_columns=date_columns, as_of=as_of_dt, floor=floor)

    if not cd.columns_present:
        return CheckResult(
            check="frozen_snapshot",
            target=target,
            status=CheckStatus.BROKEN,
            detail="nessuna colonna-data: impossibile confrontare senza mtime",
            metrics={"candidate_columns": list(date_columns)},
            as_of=as_of_dt.isoformat(),
        )

    if cd.max_date is None:
        return CheckResult(
            check="frozen_snapshot",
            target=target,
            status=CheckStatus.BROKEN,
            detail="nessuna data-contenuto valida dopo clamp",
            metrics={
                "n_future_clamped": cd.n_future_clamped,
                "n_floor_clamped": cd.n_floor_clamped,
            },
            as_of=as_of_dt.isoformat(),
        )

    current = cd.max_date
    metrics: dict = {"current_max_content_date": current.isoformat()}

    if previous_max_date is None:
        return CheckResult(
            check="frozen_snapshot",
            target=target,
            status=CheckStatus.UNKNOWN,
            detail="nessun riferimento precedente: prima osservazione",
            metrics=metrics,
            as_of=as_of_dt.isoformat(),
        )

    prev = coerce_as_of(previous_max_date)
    metrics["previous_max_content_date"] = prev.isoformat()

    if current <= prev:
        return CheckResult(
            check="frozen_snapshot",
            target=target,
            status=CheckStatus.DEGRADED,
            detail=(
                f"snapshot congelato: data-contenuto ferma a {current.date()} "
                f"(precedente {prev.date()}); riscrittura senza nuovi dati"
            ),
            metrics=metrics,
            as_of=as_of_dt.isoformat(),
        )

    return CheckResult(
        check="frozen_snapshot",
        target=target,
        status=CheckStatus.OK,
        detail=f"contenuto avanzato a {current.date()} (da {prev.date()})",
        metrics=metrics,
        as_of=as_of_dt.isoformat(),
    )
