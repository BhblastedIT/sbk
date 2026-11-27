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

__all__ = ["DEFAULT_DATE_COLUMNS", "check_freshness"]


def check_freshness(
    df: pd.DataFrame,
    *,
    target: str = "",
    date_columns: tuple[str, ...] | list[str] = DEFAULT_DATE_COLUMNS,
    as_of=None,
    warn_days: int = 7,
    broken_days: int = 30,
    floor=DEFAULT_FLOOR,
) -> CheckResult:
    ""






    as_of_dt = coerce_as_of(as_of)
    cd = pool_content_dates(df, date_columns=date_columns, as_of=as_of_dt, floor=floor)

    base_metrics = {
        "candidate_columns": list(date_columns),
        "columns_present": cd.columns_present,
        "n_values": cd.n_values,
        "n_valid": cd.n_valid,
        "n_future_clamped": cd.n_future_clamped,
        "n_floor_clamped": cd.n_floor_clamped,
        "n_unparsable": cd.n_unparsable,
    }

    if not cd.columns_present:
        return CheckResult(
            check="freshness",
            target=target,
            status=CheckStatus.BROKEN,
            detail=(
                "no date column among "
                f"{list(date_columns)}: refusing the mtime fallback"
            ),
            metrics=base_metrics,
            as_of=as_of_dt.isoformat(),
        )

    if cd.max_date is None:
        return CheckResult(
            check="freshness",
            target=target,
            status=CheckStatus.BROKEN,
            detail=(
                "no valid date after the clamp "
                f"(future={cd.n_future_clamped}, pre-floor={cd.n_floor_clamped}): "
                "freshness cannot be established without guessing"
            ),
            metrics=base_metrics,
            as_of=as_of_dt.isoformat(),
        )

    age_days = (as_of_dt - cd.max_date).days
    metrics = {
        **base_metrics,
        "max_content_date": cd.max_date.isoformat(),
        "age_days": age_days,
        "warn_days": warn_days,
        "broken_days": broken_days,
    }

    if age_days <= warn_days:
        status = CheckStatus.OK
    elif age_days <= broken_days:
        status = CheckStatus.DEGRADED
    else:
        status = CheckStatus.BROKEN

    return CheckResult(
        check="freshness",
        target=target,
        status=status,
        detail=f"dato-contenuto piu recente {cd.max_date.date()} ({age_days}g fa)",
        metrics=metrics,
        as_of=as_of_dt.isoformat(),
    )
