#!/usr/bin/env python3
""




























from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path




_ENTITY_ID_LIKE = re.compile(r"^(person|company|entity)[ _][0-9a-f]{4,}$", re.IGNORECASE)

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud.pl_types import SpeakerResolution
except ImportError:  # pragma: no cover
    from pl_types import SpeakerResolution  # type: ignore[no-redef]


class WriteAction(str, Enum):
    ""

    WRITE_CERTAIN = "WRITE_CERTAIN"
    WRITE_SUGGESTED = "WRITE_SUGGESTED"
    CONFIRM_ONLY = "CONFIRM_ONLY"
    KEEP_PLAUD = "KEEP_PLAUD"
    REVIEW_CONFLICT = (
        "REVIEW_CONFLICT"
    )
    SKIP_NO_EVIDENCE = "SKIP_NO_EVIDENCE"



_WRITING_ACTIONS = frozenset({WriteAction.WRITE_CERTAIN, WriteAction.WRITE_SUGGESTED})


@dataclass(frozen=True)
class WriteDecision:
    ""

    speaker_id: str
    action: WriteAction
    write_name: str | None
    enroll: bool
    certain: bool
    reason: str

    @property
    def writes_transcript(self) -> bool:
        return self.action in _WRITING_ACTIONS and bool(self.write_name)

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "action": self.action.value,
            "write_name": self.write_name,
            "enroll": self.enroll,
            "certain": self.certain,
            "reason": self.reason,
        }


def is_generic_label(label: str | None) -> bool:
    ""
    if label is None:
        return True
    s = label.strip()
    if not s:
        return True
    low = s.lower()

    return low.startswith("speaker") or low.startswith("spk")


def is_writable_name(name: str | None) -> bool:
    ""

    if not name or not name.strip():
        return False
    if is_generic_label(name):
        return False
    return not _ENTITY_ID_LIKE.match(name.strip())


def _norm(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def decide_write(res: SpeakerResolution) -> WriteDecision:
    ""




    sid = res.speaker_id
    label = res.plaud_label
    best = res.best
    generic = is_generic_label(label)




    if not generic:

        if best is not None and _norm(best.name) == _norm(label) and not res.plaud_disagree:
            return WriteDecision(
                sid,
                WriteAction.CONFIRM_ONLY,
                None,
                enroll=False,
                certain=True,
                reason=f"Plaud dice '{label}' e il motore concorda: identità confermata, nessun write",
            )

        proposes_other = res.proposed_name is not None and _norm(res.proposed_name) != _norm(label)
        if res.plaud_disagree or proposes_other:
            alt = res.proposed_name or (best.name if best else "?")
            return WriteDecision(
                sid,
                WriteAction.REVIEW_CONFLICT,
                None,
                enroll=False,
                certain=False,
                reason=(
                    f"Plaud dice '{label}' ma il motore propone '{alt}': conflitto su un nome "
                    "esistente -> all'utente, mai auto-overwrite (rischio di peggiorare)"
                ),
            )

        return WriteDecision(
            sid,
            WriteAction.KEEP_PLAUD,
            None,
            enroll=False,
            certain=False,
            reason=f"Plaud dice '{label}', nessuna evidenza migliore: si mantiene",
        )






    if res.proposed_name and res.corroborated and is_writable_name(res.proposed_name):
        return WriteDecision(
            sid,
            WriteAction.WRITE_CERTAIN,
            res.proposed_name,
            enroll=True,
            certain=True,
            reason="slot generico + nome corroborato da >=2 fonti indipendenti: scrivo e insegno la voce",
        )



    if best is not None and best.entity_id and is_writable_name(best.name):
        return WriteDecision(
            sid,
            WriteAction.WRITE_SUGGESTED,
            best.name,
            enroll=False,
            certain=False,
            reason="slot generico, evidenza debole ma candidato risolto al KB: proposto (flaggato), no enrollment",
        )

    return WriteDecision(
        sid,
        WriteAction.SKIP_NO_EVIDENCE,
        None,
        enroll=False,
        certain=False,
        reason="slot generico senza candidati: resta 'Speaker N'",
    )


def decide_all(resolutions: dict[str, SpeakerResolution]) -> dict[str, WriteDecision]:
    ""
    return {sid: decide_write(res) for sid, res in resolutions.items()}


def summarize(decisions: dict[str, WriteDecision]) -> dict[str, int]:
    ""
    out: dict[str, int] = {}
    for d in decisions.values():
        out[d.action.value] = out.get(d.action.value, 0) + 1
    return out


if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print(
            "uso: pl_write_policy.py <resolutions.json>  (dict speaker_id -> SpeakerResolution.to_dict)"
        )
        raise SystemExit(2)
    raw = json.loads(Path(sys.argv[1]).read_text())
    res = {sid: SpeakerResolution.from_dict(d) for sid, d in raw.items()}
    decs = decide_all(res)
    for sid, d in decs.items():
        print(
            f"{sid:12} {d.action.value:16} write={d.write_name!r:24} enroll={d.enroll} :: {d.reason}"
        )
    print("\nRiepilogo:", summarize(decs))
