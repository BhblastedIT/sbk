""







from __future__ import annotations

import pandas as pd

from .base import CheckResult, CheckStatus, coerce_as_of

__all__ = ["check_false_success"]

DEFAULT_ERROR_VALUES: tuple[str, ...] = ("llm_error", "error", "api_error", "exception")
DEFAULT_EXCEPTION_MARKERS: tuple[str, ...] = (
    "traceback",
    "exception",
    "quota",
    "rate limit",
    "error:",
    "429",
    "insufficient",
)


def check_false_success(
    df: pd.DataFrame,
    *,
    target: str = "",
    method_column: str = "method",
    error_values: tuple[str, ...] = DEFAULT_ERROR_VALUES,
    evidence_column: str = "evidence",
    exception_markers: tuple[str, ...] = DEFAULT_EXCEPTION_MARKERS,
    broken_frac: float = 0.05,
    as_of=None,
) -> CheckResult:
    ""





    as_of_dt = coerce_as_of(as_of)
    has_method = method_column in df.columns
    has_evidence = evidence_column in df.columns

    if not has_method and not has_evidence:
        return CheckResult(
            check="false_success",
            target=target,
            status=CheckStatus.UNKNOWN,
            detail=(
                f"nessuna colonna '{method_column}'/'{evidence_column}': check non applicabile"
            ),
            metrics={"has_method": False, "has_evidence": False},
            as_of=as_of_dt.isoformat(),
        )

    total = len(df)
    if total == 0:
        return CheckResult(
            check="false_success",
            target=target,
            status=CheckStatus.OK,
            detail="dataframe vuoto: nessun successo falso",
            metrics={"total": 0, "n_error": 0},
            as_of=as_of_dt.isoformat(),
        )

    err_lower = {v.lower() for v in error_values}
    error_mask = pd.Series(False, index=df.index)
    if has_method:
        method_norm = df[method_column].astype("string").str.strip().str.lower()
        error_mask = error_mask | method_norm.isin(err_lower).fillna(False)

    n_evidence_markers = 0
    if has_evidence:
        ev = df[evidence_column].astype("string").str.lower()
        marker_mask = pd.Series(False, index=df.index)
        for marker in exception_markers:
            marker_mask = marker_mask | ev.str.contains(marker, regex=False, na=False)
        n_evidence_markers = int(marker_mask.sum())

        error_mask = error_mask | marker_mask

    n_error = int(error_mask.sum())
    frac = n_error / total
    metrics = {
        "total": total,
        "n_error": n_error,
        "error_frac": round(frac, 6),
        "n_evidence_exception_markers": n_evidence_markers,
        "broken_frac": broken_frac,
        "method_column_present": has_method,
        "evidence_column_present": has_evidence,
    }

    if frac > broken_frac:
        status = CheckStatus.BROKEN
        detail = f"{n_error}/{total} ({frac:.1%}) righe sono errori scritti come dato"
    elif n_error > 0:
        status = CheckStatus.DEGRADED
        detail = f"{n_error}/{total} ({frac:.2%}) righe-errore sotto soglia"
    else:
        status = CheckStatus.OK
        detail = "nessun errore scritto come dato"

    return CheckResult(
        check="false_success",
        target=target,
        status=status,
        detail=detail,
        metrics=metrics,
        as_of=as_of_dt.isoformat(),
    )
