""




















from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from ingestion.loud_fail import AuthExpired  # noqa: E402


class Reaction(StrEnum):
    ""

    RETRY_LATER = "retry_later"
    FALLBACK_ADAPTER = "fallback_adapter"
    STOP_AND_ALERT = "stop_and_alert"
    ACCEPT_EMPTY = "accept_empty"




OUTCOME_EMPTY_CONFIRMED = "empty_confirmed"
OUTCOME_DEGRADED = "degraded"
OUTCOME_BROKEN = "broken"


class EdgeError(Exception):
    ""






    outcome: str = OUTCOME_BROKEN

    reaction: Reaction = Reaction.STOP_AND_ALERT

    advances_watermark: bool = False


class AuthPermanent(AuthExpired, EdgeError):
    ""






    outcome = OUTCOME_BROKEN
    reaction = Reaction.FALLBACK_ADAPTER
    advances_watermark = False


class RateLimited(EdgeError):
    ""




    outcome = OUTCOME_DEGRADED
    reaction = Reaction.RETRY_LATER
    advances_watermark = False

    def __init__(self, message: str = "", *, reset_at: datetime | None = None) -> None:
        super().__init__(message or "rate limited")
        self.reset_at = reset_at


class Transient(EdgeError):
    ""

    outcome = OUTCOME_DEGRADED
    reaction = Reaction.RETRY_LATER
    advances_watermark = False


class RemoteEmpty(EdgeError):
    ""





    outcome = OUTCOME_EMPTY_CONFIRMED
    reaction = Reaction.ACCEPT_EMPTY
    advances_watermark = True

    def __init__(self, message: str = "", *, proof: str = "") -> None:
        super().__init__(message or "remote confirmed empty")
        self.proof = proof


class Broken(EdgeError):
    ""

    outcome = OUTCOME_BROKEN
    reaction = Reaction.STOP_AND_ALERT
    advances_watermark = False


@dataclass(frozen=True)
class ErrorPolicy:
    ""

    error: type[EdgeError]
    outcome: str
    reaction: Reaction
    advances_watermark: bool



ERROR_TABLE: tuple[ErrorPolicy, ...] = (
    ErrorPolicy(AuthPermanent, AuthPermanent.outcome, AuthPermanent.reaction, False),
    ErrorPolicy(RateLimited, RateLimited.outcome, RateLimited.reaction, False),
    ErrorPolicy(Transient, Transient.outcome, Transient.reaction, False),
    ErrorPolicy(RemoteEmpty, RemoteEmpty.outcome, RemoteEmpty.reaction, True),
    ErrorPolicy(Broken, Broken.outcome, Broken.reaction, False),
)


def policy_for(err: EdgeError | type[EdgeError]) -> ErrorPolicy:
    ""



    cls = err if isinstance(err, type) else type(err)
    if not issubclass(cls, EdgeError):
        raise TypeError(f"{cls!r} non è un EdgeError")

    by_class = {row.error: row for row in ERROR_TABLE}
    if cls in by_class:
        return by_class[cls]
    for base in cls.__mro__:
        if base in by_class:
            return by_class[base]

    return ErrorPolicy(Broken, OUTCOME_BROKEN, Reaction.STOP_AND_ALERT, False)
