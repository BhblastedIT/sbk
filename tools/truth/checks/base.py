""







from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pandas as pd

import sbk_config



DEFAULT_DATE_COLUMNS: tuple[str, ...] = (
    "source_date",
    "observed_at",
    "valid_from",
    "event_date",
    "message_date",
    "date",
    "occurred_at",
)



DEFAULT_FLOOR = date(2000, 1, 1)


class CheckStatus(enum.StrEnum):
    ""

    OK = "ok"
    DEGRADED = "degraded"
    BROKEN = "broken"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    ""

    check: str
    target: str
    status: CheckStatus
    detail: str = ""
    metrics: dict = field(default_factory=dict)
    as_of: str = field(default_factory=lambda: sbk_config.utc_now().isoformat())

    def __post_init__(self) -> None:
        if not isinstance(self.status, CheckStatus):
            self.status = CheckStatus(self.status)

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "target": self.target,
            "status": self.status.value,
            "detail": self.detail,
            "metrics": self.metrics,
            "as_of": self.as_of,
        }


def coerce_as_of(value: object | None) -> datetime:
    ""
    if value is None:
        return sbk_config.utc_now()
    if isinstance(value, datetime):
        return sbk_config.to_utc_aware(value)
    if isinstance(value, str):
        return sbk_config.to_utc_aware(datetime.fromisoformat(value))
    raise ValueError(f"as_of tipo non valido: {type(value).__name__}")


@dataclass
class ContentDates:
    ""

    columns_present: list[str]
    max_date: datetime | None
    n_values: int
    n_valid: int
    n_future_clamped: int
    n_floor_clamped: int
    n_unparsable: int


def pool_content_dates(
    df: pd.DataFrame,
    *,
    date_columns: tuple[str, ...] | list[str] = DEFAULT_DATE_COLUMNS,
    as_of: object | None = None,
    floor: date = DEFAULT_FLOOR,
) -> ContentDates:
    ""







    as_of_dt = coerce_as_of(as_of)
    floor_dt = datetime(floor.year, floor.month, floor.day, tzinfo=UTC)

    present = [c for c in date_columns if c in df.columns]
    if not present:
        return ContentDates(
            columns_present=[],
            max_date=None,
            n_values=0,
            n_valid=0,
            n_future_clamped=0,
            n_floor_clamped=0,
            n_unparsable=0,
        )

    all_parsed: list[pd.Timestamp] = []
    n_values = 0
    n_unparsable = 0
    for col in present:
        raw = df[col]
        n_values += int(raw.notna().sum())
        parsed = pd.to_datetime(raw, errors="coerce", utc=True)
        n_unparsable += int(raw.notna().sum() - parsed.notna().sum())
        all_parsed.extend(parsed.dropna().tolist())

    n_future = 0
    n_floor = 0
    valid: list[pd.Timestamp] = []
    for ts in all_parsed:
        py = ts.to_pydatetime()
        if py > as_of_dt:
            n_future += 1
        elif py < floor_dt:
            n_floor += 1
        else:
            valid.append(ts)

    max_date = max(valid).to_pydatetime() if valid else None
    return ContentDates(
        columns_present=present,
        max_date=max_date,
        n_values=n_values,
        n_valid=len(valid),
        n_future_clamped=n_future,
        n_floor_clamped=n_floor,
        n_unparsable=n_unparsable,
    )
