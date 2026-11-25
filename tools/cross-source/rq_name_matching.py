""

















from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import GENERIC_NICKNAMES, NICKNAME_ALIASES, OWNER_SPEAKER_LABELS  # noqa: E402

log = logging.getLogger("rq.name_matching")




# Nickname -> full name of the people YOU call that way: sbk.config.json "nickname_aliases"
# (and the dashboard's Shadows page). Nothing is built in. Generic rules such as
# "bob" -> "robert" live in sbk_config.GENERIC_NICKNAMES and are applied to known full names.
KNOWN_NICKNAMES: dict[str, str] = dict(NICKNAME_ALIASES)

# Given name -> its generic nicknames ("robert" -> ["bob", "bobby", "rob"]).
_NICKS_OF_GIVEN: dict[str, list[str]] = {}
for _nick, _given in GENERIC_NICKNAMES.items():
    _NICKS_OF_GIVEN.setdefault(_given, []).append(_nick)


# Your names and speaker labels, from sbk.config.json (owner, own_names).
_OWNER_NAMES = {" ".join(n.split()) for n in OWNER_SPEAKER_LABELS}


def _nickname_index(exact_index: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """Nickname -> (person_id, name) for the people in exact_index.

    1. Your aliases (KNOWN_NICKNAMES): "sammy" -> the known "sam demo".
    2. Generic rules on full names: a known "robert smith" is also found as "bob smith" and
       "rob smith". A form that would point at two different people is left out.
    """
    out: dict[str, tuple[str, str]] = {}
    for nick, full_name in KNOWN_NICKNAMES.items():
        norm_full = _normalize(full_name)
        if norm_full in exact_index:
            out[_normalize(nick)] = exact_index[norm_full]
    generici: dict[str, tuple[str, str]] = {}
    doppi: set[str] = set()
    for norm, (pid, orig) in exact_index.items():
        parti = norm.split()
        if len(parti) < 2:
            continue
        for nick in _NICKS_OF_GIVEN.get(parti[0], ()):
            forma = " ".join([nick, *parti[1:]])
            if forma in exact_index or forma in out:
                continue
            if forma in generici and generici[forma][0] != pid:
                doppi.add(forma)
            generici.setdefault(forma, (pid, orig))
    out.update({k: v for k, v in generici.items() if k not in doppi})
    return out


@dataclass(frozen=True)
class MatchResult:
    ""

    person_id: str | None
    method: str
    confidence: float
    matched_name: str = ""

    @property
    def resolved(self) -> bool:
        return self.person_id is not None and self.method not in (
            "unresolved",
            "ambiguous",
            "owner",
        )





_EMOJI_RE = re.compile(
    "[\U0001f600-\U0001f9ff\U00002600-\U000027bf\U0000fe00-\U0000fe0f\U0001f000-\U0001f02f]"
)


def _normalize(name: str) -> str:
    ""
    name = name.strip().lower()
    name = _EMOJI_RE.sub("", name).strip()

    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


try:
    from rapidfuzz.distance import Levenshtein as _RF_Levenshtein

    _HAVE_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - fallback path
    _HAVE_RAPIDFUZZ = False


def _levenshtein_ratio(s1: str, s2: str) -> float:
    ""





    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    if _HAVE_RAPIDFUZZ:
        return _RF_Levenshtein.normalized_similarity(s1, s2)


    matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        matrix[i][0] = i
    for j in range(len2 + 1):
        matrix[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )
    distance = matrix[len1][len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len) if max_len > 0 else 0.0





class NameMatcher:
    ""

    FUZZY_THRESHOLD = 0.85

    def __init__(self, contacts_merged_path: Path | None = None, df: pd.DataFrame | None = None):
        ""





        self._exact_index: dict[
            str, tuple[str, str]
        ] = {}
        self._names: list[tuple[str, str, str]] = []
        self._nickname_index: dict[
            str, tuple[str, str]
        ] = {}

        if df is not None:
            self._build_from_df(df)
        elif contacts_merged_path is not None and contacts_merged_path.exists():
            cm = pd.read_parquet(contacts_merged_path, columns=["person_id", "name"])
            self._build_from_df(cm)

    def _build_from_df(self, df: pd.DataFrame) -> None:
        ""
        for _, row in df.iterrows():
            pid = str(row.get("person_id", ""))
            name = str(row.get("name", "")) if pd.notna(row.get("name")) else ""
            if not pid or not name:
                continue
            norm = _normalize(name)
            if not norm:
                continue
            existing = self._exact_index.get(norm)
            if existing and existing[0] != pid:
                log.debug(
                    "Ambiguous name '%s': %s vs %s — skipping exact match", name, existing[0], pid
                )
            else:
                self._exact_index[norm] = (pid, name)
            self._names.append((norm, pid, name))


        self._nickname_index = _nickname_index(self._exact_index)

        log.info(
            "NameMatcher: %d names indexed, %d nicknames",
            len(self._exact_index),
            len(self._nickname_index),
        )

    def match(self, name: str) -> MatchResult:
        ""




        if not name or not name.strip():
            return MatchResult(person_id=None, method="unresolved", confidence=0.0)

        norm = _normalize(name)
        if not norm:
            return MatchResult(person_id=None, method="unresolved", confidence=0.0)


        if norm in _OWNER_NAMES:
            return MatchResult(person_id=None, method="owner", confidence=1.0, matched_name=name)


        if norm in self._exact_index:
            pid, orig = self._exact_index[norm]
            return MatchResult(person_id=pid, method="exact", confidence=1.0, matched_name=orig)


        if norm in self._nickname_index:
            pid, orig = self._nickname_index[norm]
            return MatchResult(person_id=pid, method="nickname", confidence=0.95, matched_name=orig)


        best_score = 0.0
        best_matches: list[tuple[str, str, float]] = []

        for cand_norm, cand_pid, cand_name in self._names:
            score = _levenshtein_ratio(norm, cand_norm)
            if score >= self.FUZZY_THRESHOLD:
                if score > best_score + 0.05:

                    best_matches = [(cand_pid, cand_name, score)]
                    best_score = score
                elif abs(score - best_score) <= 0.05:

                    best_matches.append((cand_pid, cand_name, score))
                    best_score = max(best_score, score)

        if len(best_matches) == 1:
            pid, matched_name, score = best_matches[0]
            return MatchResult(
                person_id=pid,
                method="fuzzy",
                confidence=round(score, 3),
                matched_name=matched_name,
            )
        elif len(best_matches) > 1:

            log.warning(
                "Ambiguous match for '%s': %s",
                name,
                [(m[1], round(m[2], 3)) for m in best_matches],
            )
            return MatchResult(person_id=None, method="ambiguous", confidence=0.0)

        return MatchResult(person_id=None, method="unresolved", confidence=0.0)

    def match_batch(self, names: list[str]) -> dict[str, MatchResult]:
        ""
        return {name: self.match(name) for name in names}

    def save_index(self, path: Path) -> None:
        ""

        data = {
            "version": 1,
            "matches": {},
            "unresolved": [],
            "ambiguous": [],
        }

        all_names = set()
        for norm, pid, orig in self._names:
            all_names.add(orig)
        for nick in KNOWN_NICKNAMES:
            all_names.add(nick)

        for name in sorted(all_names):
            result = self.match(name)
            if result.resolved:
                data["matches"][name] = {
                    "person_id": result.person_id,
                    "method": result.method,
                    "confidence": result.confidence,
                    "matched_name": result.matched_name,
                }
            elif result.method == "ambiguous":
                data["ambiguous"].append(name)
            elif result.method == "unresolved":
                data["unresolved"].append(name)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Saved name matching index: %s (%d matches)", path, len(data["matches"]))

    @classmethod
    def load_index(cls, path: Path) -> NameMatcher:
        ""
        matcher = cls.__new__(cls)
        matcher._exact_index = {}
        matcher._names = []
        matcher._nickname_index = {}

        if not path.exists():
            return matcher

        data = json.loads(path.read_text(encoding="utf-8"))
        for name, info in data.get("matches", {}).items():
            norm = _normalize(name)
            pid = info["person_id"]
            matched = info.get("matched_name", name)
            matcher._exact_index[norm] = (pid, matched)
            matcher._names.append((norm, pid, matched))


        matcher._nickname_index = _nickname_index(matcher._exact_index)

        return matcher

    def get_stats(self) -> dict:
        ""
        return {
            "total_names": len(self._exact_index),
            "total_nicknames": len(self._nickname_index),
        }
