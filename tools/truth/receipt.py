""


















from __future__ import annotations

import enum
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import sbk_config


class Outcome(enum.StrEnum):
    ""

    OK = "ok"
    EMPTY_CONFIRMED = "empty_confirmed"
    DEGRADED = "degraded"
    BROKEN = "broken"
    SKIPPED_LOCK = "skipped_lock"
    SKIPPED_WINDOW = "skipped_window"
    SKIPPED_STATE = "skipped_state"
    REFUSED_PAID = "refused_paid"
    REFUSED_STATE = "refused_state"
    REFUSED_PERIMETER = "refused_perimeter"
    REFUSED_BUDGET = "refused_budget"


class Mode(enum.StrEnum):
    ""

    NORMAL = "normal"
    DRY_RUN = "dry_run"
    SHADOW = "shadow"
    CANARY = "canary"
    CAMPAIGN = "campaign"



ADVANCING_OUTCOMES = frozenset({Outcome.OK, Outcome.EMPTY_CONFIRMED})



HEALTH_STATUS = ("healthy", "degraded", "broken", "unknown")


def _coerce_outcome(value: object) -> Outcome:
    if isinstance(value, Outcome):
        return value
    if isinstance(value, str):
        try:
            return Outcome(value)
        except ValueError as exc:
            valid = ", ".join(o.value for o in Outcome)
            raise ValueError(f"invalid outcome: {value!r}. Allowed: {valid}") from exc
    raise ValueError(f"invalid outcome (type {type(value).__name__}): {value!r}")


def _coerce_mode(value: object) -> Mode:
    if isinstance(value, Mode):
        return value
    if isinstance(value, str):
        try:
            return Mode(value)
        except ValueError as exc:
            valid = ", ".join(m.value for m in Mode)
            raise ValueError(f"invalid mode: {value!r}. Allowed: {valid}") from exc
    raise ValueError(f"invalid mode (type {type(value).__name__}): {value!r}")


def _coerce_as_of(value: object) -> str:
    ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive as_of not allowed: use a timezone-aware datetime")
        return value.isoformat()
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError(f"naive as_of not allowed: {value!r}")
        return parsed.isoformat()
    raise ValueError(f"invalid as_of type: {type(value).__name__}")


@dataclass
class Receipt:
    ""






    job_id: str
    caller: str
    status: Outcome
    mode: Mode = Mode.NORMAL
    records_seen: int = 0
    records_written: int = 0
    records_lost: int = 0
    paid: bool = False
    cost_usd: float = 0.0
    cost_equiv_usd: float = 0.0
    campaign_id: str | None = None
    duration_s: float = 0.0
    as_of: str = field(default_factory=lambda: sbk_config.utc_now().isoformat())
    detail: str = ""

    def __post_init__(self) -> None:
        self.status = _coerce_outcome(self.status)
        self.mode = _coerce_mode(self.mode)
        self.as_of = _coerce_as_of(self.as_of)
        self.records_seen = int(self.records_seen)
        self.records_written = int(self.records_written)
        self.records_lost = int(self.records_lost)
        self.paid = bool(self.paid)
        self.cost_usd = float(self.cost_usd)
        self.cost_equiv_usd = float(self.cost_equiv_usd)
        self.duration_s = float(self.duration_s)

    @property
    def advances_watermark(self) -> bool:
        return self.status in ADVANCING_OUTCOMES

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "caller": self.caller,
            "status": self.status.value,
            "mode": self.mode.value,
            "records_seen": self.records_seen,
            "records_written": self.records_written,
            "records_lost": self.records_lost,
            "paid": self.paid,
            "cost_usd": self.cost_usd,
            "cost_equiv_usd": self.cost_equiv_usd,
            "campaign_id": self.campaign_id,
            "duration_s": self.duration_s,
            "as_of": self.as_of,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Receipt:
        return cls(
            job_id=data["job_id"],
            caller=data["caller"],
            status=data["status"],
            mode=data.get("mode", Mode.NORMAL.value),
            records_seen=data.get("records_seen", 0),
            records_written=data.get("records_written", 0),
            records_lost=data.get("records_lost", 0),
            paid=data.get("paid", False),
            cost_usd=data.get("cost_usd", 0.0),
            cost_equiv_usd=data.get("cost_equiv_usd", 0.0),
            campaign_id=data.get("campaign_id"),
            duration_s=data.get("duration_s", 0.0),
            as_of=data["as_of"],
            detail=data.get("detail", ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> Receipt:
        return cls.from_dict(json.loads(line))


def _receipts_root(root: Path | None) -> Path:

    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    return base / "system" / "receipts"


def receipts_path_for(as_of: str, root: Path | None = None) -> Path:
    ""
    dt = datetime.fromisoformat(as_of)
    return _receipts_root(root) / f"receipts-{dt.strftime('%Y%m')}.jsonl"


def write_receipt(receipt: Receipt, root: Path | None = None) -> Path:
    ""



    path = receipts_path_for(receipt.as_of, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = receipt.to_json()

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def read_receipts(path: Path) -> list[Receipt]:
    ""
    out: list[Receipt] = []
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(Receipt.from_json(line))
    return out


def build_health_state_entry(
    unit: str,
    status: str,
    as_of: str,
    receipts_ref: str,
) -> dict:
    ""



    if status not in HEALTH_STATUS:
        raise ValueError(
            f"invalid health status: {status!r}. Allowed: {', '.join(HEALTH_STATUS)}"
        )
    as_of_norm = _coerce_as_of(as_of)
    return {
        "unit": unit,
        "status": status,
        "as_of": as_of_norm,
        "receipts_ref": receipts_ref,
    }
