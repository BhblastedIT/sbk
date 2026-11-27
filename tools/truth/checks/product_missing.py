""







from __future__ import annotations

from pathlib import Path

from .base import CheckResult, CheckStatus, coerce_as_of

__all__ = ["check_product_missing"]


def _parquet_num_rows(path: Path) -> int:
    import pyarrow.parquet as pq

    return pq.ParquetFile(path).metadata.num_rows


def check_product_missing(
    path: str | Path | None = None,
    *,
    target: str = "",
    count: int | None = None,
    min_rows: int = 1,
    previous_count: int | None = None,
    max_drop_pct: float = 90.0,
    as_of=None,
) -> CheckResult:
    ""








    as_of_dt = coerce_as_of(as_of)
    tgt = target or (str(path) if path is not None else "")

    n_rows: int | None = count
    if n_rows is None:
        if path is None:
            return CheckResult(
                check="product_missing",
                target=tgt,
                status=CheckStatus.UNKNOWN,
                detail="ne path ne count forniti",
                metrics={},
                as_of=as_of_dt.isoformat(),
            )
        p = Path(path)
        if not p.exists():
            return CheckResult(
                check="product_missing",
                target=tgt,
                status=CheckStatus.BROKEN,
                detail=f"product missing: {p}",
                metrics={"exists": False},
                as_of=as_of_dt.isoformat(),
            )
        try:
            n_rows = _parquet_num_rows(p)
        except Exception as exc:  # noqa: BLE001 - file illeggibile = prodotto rotto
            return CheckResult(
                check="product_missing",
                target=tgt,
                status=CheckStatus.BROKEN,
                detail=f"product unreadable: {type(exc).__name__}: {exc}",
                metrics={"exists": True, "readable": False},
                as_of=as_of_dt.isoformat(),
            )

    metrics: dict = {"rows": n_rows, "min_rows": min_rows}

    if n_rows < min_rows:
        return CheckResult(
            check="product_missing",
            target=tgt,
            status=CheckStatus.BROKEN,
            detail=f"product empty: {n_rows} rows (< {min_rows})",
            metrics=metrics,
            as_of=as_of_dt.isoformat(),
        )

    if previous_count is not None and previous_count > 0:
        drop_pct = (previous_count - n_rows) / previous_count * 100
        metrics["previous_count"] = previous_count
        metrics["drop_pct"] = round(drop_pct, 4)
        metrics["max_drop_pct"] = max_drop_pct
        if drop_pct > max_drop_pct:
            return CheckResult(
                check="product_missing",
                target=tgt,
                status=CheckStatus.BROKEN,
                detail=(
                    f"drop {drop_pct:.1f}% ({previous_count} -> {n_rows}): "
                    "the product collapsed although the receipt says ok"
                ),
                metrics=metrics,
                as_of=as_of_dt.isoformat(),
            )

    return CheckResult(
        check="product_missing",
        target=tgt,
        status=CheckStatus.OK,
        detail=f"product present: {n_rows} rows",
        metrics=metrics,
        as_of=as_of_dt.isoformat(),
    )
