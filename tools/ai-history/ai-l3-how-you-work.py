#!/usr/bin/env python3
"""AI history, step L3: how you work.

Reads the messages YOU typed to AI assistants (Claude Code, ChatGPT, Claude.ai, Manus),
as collected by the ai-history readers into $SBK_DATA_ROOT/ai-history/messages.jsonl
(one JSON object per line: {source, session_id, project, ts, text}), and builds the
identity files that SBK's drafts and chat read from sbk/identity/.

Step 1, local and deterministic, no model:
  recurring instructions (sentences you repeat across sessions: "always ...", "never ...",
  rules, corrections), recurring phrases, length and vocabulary statistics, languages,
  active hours, top topics per project. Saved to
  $SBK_DATA_ROOT/ai-history/how-you-work-stats.json and printed in the terminal.

Step 2, model synthesis (only with --yes):
  sends a bounded sample of your messages plus the step 1 summary through the repo's
  model call path (call_claude in tools/cross-source/xs_l3_common.py) and writes
  sbk/identity/profile.md, style-guide.md, communication-playbook.md,
  decision-framework.md and working-rules.md.

Before anything is sent the script prints what would go out (provider, host, model,
number of messages, characters per call and in total). Nothing is sent without --yes.
--dry-run computes everything and sends nothing. An existing identity file is never
overwritten without --force: the new version is written next to it as <name>.new.md.

Examples:
  uv run python tools/ai-history/ai-l3-how-you-work.py --stats-only
  uv run python tools/ai-history/ai-l3-how-you-work.py --dry-run --show-payload
  uv run python tools/ai-history/ai-l3-how-you-work.py --yes --max-chars 60000
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import random
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOLS_DIR = _HERE.parent
_CROSS_SOURCE_DIR = _TOOLS_DIR / "cross-source"
PROJECT_ROOT = _TOOLS_DIR.parent
for _p in (_HERE, _TOOLS_DIR, _CROSS_SOURCE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SCRIPT_NAME = "tools/ai-history/ai-l3-how-you-work.py"
IDENTITY_DIR = PROJECT_ROOT / "sbk" / "identity"

# The names load_identity_files() (tools/cross-source/xs_l3_common.py) and the dashboard
# chat (_IDENTITY_FILES in dashboard/app/core/chat_tools.py) read.
IDENTITY_FILES = (
    "profile.md",
    "style-guide.md",
    "communication-playbook.md",
    "decision-framework.md",
    "working-rules.md",
)

DEFAULT_MAX_CHARS = 60_000
PER_MESSAGE_CAP = 1_500
DEFAULT_MIN_SESSIONS = 2
NGRAM_SIZES = (4, 5, 6)
NGRAM_PRUNE_AT = 1_500_000
INDEX_CAP = 150

PROVIDER_HOSTS = {
    "anthropic": ("api.anthropic.com", "ANTHROPIC_API_KEY"),
    "gemini": ("generativelanguage.googleapis.com", "GOOGLE_API_KEY"),
    "deepseek": ("api.deepseek.com", "DEEPSEEK_API_KEY"),
    "openai": ("api.openai.com", "OPENAI_API_KEY"),
}


def data_root() -> Path:
    """SBK data root, same rule as sbk_config.DATA_ROOT (an empty value counts as unset)."""
    return Path(os.environ.get("SBK_DATA_ROOT") or str(Path.home() / ".sbk-data")).expanduser()


# ---------------------------------------------------------------------------
# Language and word lists (small on purpose: enough to tell languages apart and
# to drop function words from keyword counts)
# ---------------------------------------------------------------------------


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


STOPWORDS: dict[str, frozenset[str]] = {
    "en": _words(
        "the and to of a in is it that for you this on with be are not have as i do"
        " can at was if or but what so we my me your an all from they will just there"
        " how about would should it's i'm don't then them only also more like into which"
        " tell want need get one two let see please ok okay yes here now"
    ),
    "it": _words(
        "il lo la i gli le di che e è un una per non con del della in mi ti si ma come"
        " anche questo questa sono se da al alla dei delle nel nella più cosa fai fare"
        " tutto ci ho hai ha poi così quello quella perché già"
    ),
    "es": _words(
        "el la los las de que y en un una por con no es para se lo como más pero sus le"
        " ya o este esta sí porque muy sin sobre también me hay donde cuando todo"
    ),
    "fr": _words(
        "le la les de des du et en un une est que qui pour pas ne dans sur avec il elle"
        " ce cette au aux je tu nous vous mais ou plus par se sont comme tout"
    ),
    "de": _words(
        "der die das und ist nicht ein eine zu den mit von auf für sich dem des im es"
        " ich du wir sie aber auch wie oder noch nur wenn dass bitte kein"
    ),
    "pt": _words(
        "o a os as de que e em um uma para com não é se do da dos das no na por mais"
        " mas como ao seu sua ou quando muito já também isso você"
    ),
}
ALL_STOPWORDS = frozenset().union(*STOPWORDS.values())

# Words that mark a sentence as a rule or a standing instruction.
RULE_MARKERS = re.compile(
    r"\b("
    # English
    r"always|never|don'?t|do not|must|make sure|remember|avoid|stop|from now on|every time|"
    r"each time|no more|instead of|should never|should always|keep in mind|"
    # Italian
    r"sempre|mai|non devi|devi|ricordati|ricorda|evita|niente|basta|d'ora in poi|"
    r"ogni volta|invece di|assicurati|"
    # Spanish
    r"siempre|nunca|no debes|debes|recuerda|evita|asegúrate|cada vez|"
    # French
    r"toujours|jamais|ne dois|dois|n'oublie|évite|assure-toi|chaque fois|"
    # German
    r"immer|niemals|nie|musst|vergiss|vermeide|jedes mal|"
    # Portuguese
    r"nunca|não deve|lembre|evite|toda vez"
    r")\b",
    re.IGNORECASE,
)

# Openings that mark a message as a correction of what the assistant just did.
CORRECTION_OPENINGS = re.compile(
    r"^\s*("
    r"no\b|nope\b|wrong\b|that'?s (not|wrong)|not what i|i (said|told you|asked)|again\b|"
    r"why did you|you didn'?t|you forgot|you missed|undo\b|revert\b|that'?s not it|"
    r"sbagliato|non è (così|questo|quello)|non così|ti (ho|avevo) detto|ancora\b|di nuovo|"
    r"perch[eé] hai|hai dimenticato|non hai|rifai|fermati|"
    r"mal\b|te dije|otra vez|"
    r"non\s*[,.!]|faux\b|je t'ai dit|encore\b|"
    r"nein\b|falsch\b|ich habe (gesagt|dir gesagt)|nochmal\b|"
    r"errado|eu disse|de novo"
    r")",
    re.IGNORECASE,
)

FILLER_OPENINGS = re.compile(
    r"^(ok(ay)?|please|and|also|so|then|now|e|poi|allora|ok quindi|quindi|y|et|und|und dann)\s+",
    re.IGNORECASE,
)

WORD_RE = re.compile(r"[^\W\d_][^\W\d_'’-]*", re.UNICODE)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+|;\s+")
EMOJI_RE = re.compile("[\U0001f300-\U0001faff☀-➿]")
BULLET_RE = re.compile(r"^\s*([-*•]|\d+[.)])\s+", re.MULTILINE)

# ---------------------------------------------------------------------------
# Secret and contact redaction (a second line of defence: the readers redact
# secrets already; this runs again on everything that could be sent)
# ---------------------------------------------------------------------------

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
        "[REDACTED private key]",
    ),
    (re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{16,}"), "[REDACTED key]"),
    (
        re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
        "[REDACTED token]",
    ),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "[REDACTED key]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
        "[REDACTED token]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|passcode|token|secret|api[_-]?key|access[_-]?key)"
            r"(\s*[:=]\s*)(?!\[REDACTED)(\"[^\"]+\"|'[^']+'|\S+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[REDACTED hex]"),
    # long opaque strings with letters and digits (base64, random ids); paths are left alone
    (
        re.compile(
            r"(?<![\w/])(?=[A-Za-z0-9+_-]*\d)(?=[A-Za-z0-9+_-]*[A-Za-z])[A-Za-z0-9+_-]{40,}={0,2}"
        ),
        "[REDACTED blob]",
    ),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email]"),
)

_PHONE_CANDIDATE = re.compile(r"(?<![\w/:.-])\+?\d[\d ().-]{7,}\d(?![\w/:])")
_DATE_LIKE = re.compile(r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}$|^\d{1,2}[-./]\d{1,2}[-./]\d{2,4}$")


def _phone_repl(m: re.Match[str]) -> str:
    s = m.group(0)
    digits = sum(ch.isdigit() for ch in s)
    if digits < 9 or _DATE_LIKE.match(s.strip()):
        return s
    return "[phone]"


def _plugin_redact(text: str) -> tuple[str, int]:
    """The ai-history readers' own rules (ai_redact.py, named after gitleaks rules), with
    e-mail addresses on. Skipped if that module is not there."""
    try:
        from ai_redact import redact as ai_redact
    except ImportError:
        return text, 0
    text, hits = ai_redact(text, emails=True)
    return text, sum(hits.values())


def redact(text: str) -> tuple[str, int]:
    """Replace secrets, e-mail addresses and phone numbers. Returns (text, replacements).
    First the readers' rules, then a broader pass of this script."""
    text, total = _plugin_redact(text)
    for pattern, repl in _REDACTIONS:
        text, n = pattern.subn(repl, text)
        total += n
    new = _PHONE_CANDIDATE.sub(_phone_repl, text)
    if new != text:
        total += new.count("[phone]") - text.count("[phone]")
        text = new
    return text, total


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass
class Message:
    source: str
    session_id: str
    project: str
    ts: datetime | None
    text: str
    paste: bool = False
    correction: bool = False
    lang: str = "?"
    idx: int = 0


@dataclass
class LoadResult:
    messages: list[Message] = field(default_factory=list)
    bad_lines: int = 0
    empty: int = 0


def parse_ts(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            if v > 1e12:  # milliseconds
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=UTC)
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def looks_pasted(text: str) -> bool:
    """True for what is most likely pasted material (code, logs, documents), not typed prose."""
    if "```" in text:
        return True
    if len(text) > 4000:
        return True
    lines = text.splitlines()
    if len(lines) >= 8:
        codey = sum(
            1
            for ln in lines
            if ln.startswith(("    ", "\t", "$ ", "> ", "at ", 'File "', "{", "}", "<", "#!"))
            or ln.rstrip().endswith(("{", "}", ";", ");"))
        )
        if codey / len(lines) > 0.4:
            return True
    stripped = text.lstrip()
    if stripped.startswith(("Traceback (most recent call last)", '{"', "<?xml", "<!DOCTYPE")):
        return True
    letters = sum(ch.isalpha() for ch in text)
    return len(text) > 200 and letters / max(len(text), 1) < 0.55


def detect_language(text: str) -> str:
    words = [w.lower() for w in WORD_RE.findall(text)]
    if len(words) < 3:
        return "?"
    scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "?"
    return best


def load_messages(path: Path, max_messages: int | None = None) -> LoadResult:
    res = LoadResult()
    if not path.exists():
        return res
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                res.bad_lines += 1
                continue
            if not isinstance(obj, dict):
                res.bad_lines += 1
                continue
            text = obj.get("text")
            if not isinstance(text, str) or not text.strip():
                res.empty += 1
                continue
            text = text.strip()
            msg = Message(
                source=str(obj.get("source") or "unknown"),
                session_id=str(obj.get("session_id") or "unknown"),
                project=str(obj.get("project") or "(none)"),
                ts=parse_ts(obj.get("ts")),
                text=text,
                idx=len(res.messages),
            )
            msg.paste = looks_pasted(text)
            msg.correction = (not msg.paste) and bool(CORRECTION_OPENINGS.match(text))
            msg.lang = detect_language(text[:2000])
            res.messages.append(msg)
            if max_messages and len(res.messages) >= max_messages:
                break
    return res


# ---------------------------------------------------------------------------
# Step 1: statistics
# ---------------------------------------------------------------------------


# What redaction leaves in the text: the readers' "[REDACTED:<rule>]", this script's
# "[REDACTED ...]", "[email]" and "[phone]". Not words the person typed, so step 1
# never counts them (topics, vocabulary, phrases).
REDACTION_MARKER_RE = re.compile(r"\[(?:REDACTED(?:[: ][^\]\n]{0,80})?|email|phone)\]")


def count_markers(text: str) -> int:
    return len(REDACTION_MARKER_RE.findall(text))


def tokens(text: str) -> list[str]:
    text = REDACTION_MARKER_RE.sub(" ", text)
    return [w.lower().strip("'’-") for w in WORD_RE.findall(text) if len(w) <= 30]


def content_tokens(text: str) -> list[str]:
    return [w for w in tokens(text) if len(w) >= 3 and w not in ALL_STOPWORDS]


def split_sentences(text: str) -> list[str]:
    out = []
    for part in SENTENCE_SPLIT.split(text):
        part = BULLET_RE.sub("", part).strip(" \t-*•\"'“”«»")
        if part:
            out.append(part)
    return out


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_sentence(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"https?://\S+", " url ", s)
    s = re.sub(r"[`*_~]", "", s)
    s = re.sub(r"\d+", "#", s)
    s = re.sub(r"[^\w\s'#]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:
        prev = s
        s = FILLER_OPENINGS.sub("", s)
    return s


def _signature(norm: str) -> frozenset[str]:
    """Tokens that carry meaning for grouping; rule words are kept, function words dropped."""
    toks = norm.split()
    keep = {
        _strip_accents(t)
        for t in toks
        if (t not in ALL_STOPWORDS and len(t) >= 3) or RULE_MARKERS.fullmatch(t)
    }
    return frozenset(keep)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Cluster:
    signature: frozenset[str]
    sessions: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    count: int = 0
    variants: Counter = field(default_factory=Counter)
    first: datetime | None = None
    last: datetime | None = None
    example_idx: int = -1

    def add(self, sentence: str, msg: Message) -> None:
        self.sessions.add(msg.session_id)
        self.projects.add(msg.project)
        self.count += 1
        self.variants[sentence] += 1
        if msg.ts:
            self.first = msg.ts if self.first is None or msg.ts < self.first else self.first
            self.last = msg.ts if self.last is None or msg.ts > self.last else self.last
        if self.example_idx < 0:
            self.example_idx = msg.idx

    def merge(self, other: Cluster) -> None:
        self.sessions |= other.sessions
        self.projects |= other.projects
        self.count += other.count
        self.variants.update(other.variants)
        for ts in (other.first, other.last):
            if ts is None:
                continue
            if self.first is None or ts < self.first:
                self.first = ts
            if self.last is None or ts > self.last:
                self.last = ts
        if self.example_idx < 0:
            self.example_idx = other.example_idx

    def representative(self) -> str:
        # most frequent wording; on a tie the shorter one
        return sorted(self.variants.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]


def group_sentences(items: Iterable[tuple[str, Message]], threshold: float = 0.6) -> list[Cluster]:
    """Group sentences by exact normalized form, then merge near-duplicates (Jaccard on
    meaningful tokens). Candidate lookups go through each group's two rarest tokens, and each
    token lists at most INDEX_CAP clusters (the ones seen in most sessions come first), so
    the cost stays linear in the number of sentences."""
    exact: dict[str, Cluster] = {}
    for sentence, msg in items:
        norm = normalize_sentence(sentence)
        if len(norm.split()) < 3:
            continue
        sig = _signature(norm)
        if len(sig) < 2:
            continue
        cl = exact.get(norm)
        if cl is None:
            cl = exact[norm] = Cluster(signature=sig)
        cl.add(sentence.strip(), msg)

    groups = sorted(exact.values(), key=lambda c: (-len(c.sessions), -c.count))
    token_df: Counter = Counter()
    for g in groups:
        token_df.update(g.signature)

    merged: list[Cluster] = []
    index: dict[str, list[int]] = defaultdict(list)
    for g in groups:
        rare = sorted(g.signature, key=lambda t: (token_df[t], t))[:2]
        best, best_score = -1, 0.0
        seen: set[int] = set()
        size = len(g.signature)
        for t in rare:
            for ci in index.get(t, ()):
                if ci in seen:
                    continue
                seen.add(ci)
                other = len(merged[ci].signature)
                if min(size, other) < threshold * max(size, other):
                    continue  # sizes too far apart to reach the threshold
                score = _jaccard(g.signature, merged[ci].signature)
                if score > best_score:
                    best, best_score = ci, score
        if best >= 0 and best_score >= threshold:
            merged[best].merge(g)
        else:
            merged.append(g)
            for t in g.signature:
                lst = index[t]
                if len(lst) < INDEX_CAP:
                    lst.append(len(merged) - 1)
    return merged


def _stitch(out: list[list], gram: tuple[str, ...], count: int) -> bool:
    """Fold `gram` into a kept phrase it is part of or overlaps by 3+ words (same or higher
    session count). Returns True when folded."""
    for entry in out:
        toks, c2 = entry
        if c2 < count:
            continue
        n, m = len(toks), len(gram)
        for i in range(n - m + 1):
            if tuple(toks[i : i + m]) == gram:
                return True
        for k in range(min(n, m) - 1, 2, -1):
            if tuple(toks[-k:]) == gram[:k]:
                entry[0] = list(toks) + list(gram[k:])
                return True
            if tuple(toks[:k]) == gram[-k:]:
                entry[0] = list(gram[:-k]) + list(toks)
                return True
    return False


def recurring_phrases(
    messages: list[Message], min_sessions: int, top: int = 40, skip_in: Iterable[str] = ()
) -> list[dict]:
    """Word sequences (built from 4 to 6 word n-grams) that come back in several sessions.
    Overlapping n-grams are stitched into one phrase; phrases already inside a recurring
    instruction (`skip_in`, normalized) are left out."""
    by_session: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    counts: Counter = Counter()
    order = sorted(messages, key=lambda m: m.session_id)
    current = None
    for m in order:
        if m.paste:
            continue
        if m.session_id != current:
            if current is not None:
                counts.update(by_session.pop(current, set()))
                if len(counts) > NGRAM_PRUNE_AT:
                    counts = Counter({k: v for k, v in counts.items() if v > 1})
            current = m.session_id
        for sentence in split_sentences(m.text):
            toks = tokens(sentence)
            for n in NGRAM_SIZES:
                for i in range(len(toks) - n + 1):
                    gram = tuple(toks[i : i + n])
                    if all(t in ALL_STOPWORDS for t in gram):
                        continue
                    if sum(t not in ALL_STOPWORDS for t in gram) < 2:
                        continue
                    by_session[current].add(gram)
    if current is not None:
        counts.update(by_session.pop(current, set()))

    floor = max(min_sessions, 3)
    kept = [(g, c) for g, c in counts.items() if c >= floor]
    kept.sort(key=lambda gc: (-gc[1], -len(gc[0]), gc[0]))
    skip = [" " + s + " " for s in skip_in]
    out: list[list] = []
    for gram, c in kept:
        probe = " " + " ".join(gram) + " "
        if any(probe in s for s in skip):
            continue
        if _stitch(out, gram, c):
            continue
        if len(out) >= top:
            break
        out.append([list(gram), c])
    return [{"phrase": " ".join(toks), "sessions": c} for toks, c in out]


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return s[k]


def _mattr(words: list[str], window: int = 500) -> float:
    """Moving-average type/token ratio: comparable across corpora of different size."""
    if not words:
        return 0.0
    if len(words) <= window:
        return round(len(set(words)) / len(words), 3)
    step = max(1, (len(words) - window) // 200)
    ratios = [
        len(set(words[i : i + window])) / window for i in range(0, len(words) - window + 1, step)
    ]
    return round(sum(ratios) / len(ratios), 3)


def _date(dt: datetime | None) -> str | None:
    return dt.date().isoformat() if dt else None


def compute_stats(messages: list[Message], min_sessions: int = DEFAULT_MIN_SESSIONS) -> dict:
    typed = [m for m in messages if not m.paste]
    sessions = {m.session_id for m in messages}
    projects = Counter(m.project for m in messages)
    sources = Counter(m.source for m in messages)
    stamps = [m.ts for m in messages if m.ts]

    # length and form, on typed messages only
    words_per_msg = [len(tokens(m.text)) for m in typed]
    chars_per_msg = [len(m.text) for m in typed]
    n_typed = len(typed)
    questions = sum("?" in m.text for m in typed)
    exclaims = sum("!" in m.text for m in typed)
    emojis = sum(bool(EMOJI_RE.search(m.text)) for m in typed)
    bullets = sum(bool(BULLET_RE.search(m.text)) for m in typed)
    no_final_punct = sum(
        not m.text.rstrip().endswith((".", "!", "?", "…", ")", ":")) for m in typed
    )
    lowercase_start = sum(m.text[:1].islower() for m in typed)
    sentences_per_msg = [len(split_sentences(m.text)) for m in typed]

    # vocabulary
    all_words: list[str] = []
    content_counter: Counter = Counter()
    for m in typed:
        toks = tokens(m.text)
        all_words.extend(toks)
        content_counter.update(t for t in toks if len(t) >= 3 and t not in ALL_STOPWORDS)

    # languages (messages with a detectable language)
    langs = Counter(m.lang for m in typed if m.lang != "?")
    n_lang = sum(langs.values())

    # hours and weekdays in local time
    hours = Counter(m.ts.astimezone().hour for m in messages if m.ts)
    weekdays = Counter(m.ts.astimezone().strftime("%a") for m in messages if m.ts)

    # recurring instructions: rule-like sentences repeated across sessions
    rule_items = []
    for m in typed:
        for s in split_sentences(m.text):
            n_words = len(s.split())
            if 3 <= n_words <= 40 and RULE_MARKERS.search(s):
                rule_items.append((s, m))
    rule_clusters = [c for c in group_sentences(rule_items) if len(c.sessions) >= min_sessions]
    rule_clusters.sort(key=lambda c: (-len(c.sessions), -c.count))

    # corrections: the openings you use and the ones you repeat
    corrections = [m for m in typed if m.correction]
    corr_items = []
    for m in corrections:
        first = split_sentences(m.text)[:2]
        for s in first:
            if len(s.split()) >= 3:
                corr_items.append((s, m))
    corr_clusters = [c for c in group_sentences(corr_items) if len(c.sessions) >= min_sessions]
    corr_clusters.sort(key=lambda c: (-len(c.sessions), -c.count))
    openings = Counter(
        " ".join(tokens(m.text)[:2]) for m in corrections if tokens(m.text)
    ).most_common(10)

    # topics per project: words frequent in the project compared with everywhere else
    per_project_words: dict[str, Counter] = defaultdict(Counter)
    per_project_msgs: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        per_project_msgs[m.project].append(m)
        if not m.paste:
            per_project_words[m.project].update(content_tokens(m.text))
    total_global = sum(content_counter.values()) or 1
    topics = []
    for proj, cnt in projects.most_common():
        words = per_project_words[proj]
        total_proj = sum(words.values()) or 1
        scored = []
        for w, c in words.items():
            if c < 3:
                continue
            lift = (c / total_proj) / ((content_counter[w] + 1) / total_global)
            scored.append((lift * math.log(1 + c), w, c))
        scored.sort(reverse=True)
        ms = per_project_msgs[proj]
        ts_list = [m.ts for m in ms if m.ts]
        topics.append(
            {
                "project": proj,
                "messages": cnt,
                "sessions": len({m.session_id for m in ms}),
                "first": _date(min(ts_list)) if ts_list else None,
                "last": _date(max(ts_list)) if ts_list else None,
                "keywords": [w for _, w, _ in scored[:12]],
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": SCRIPT_NAME,
        "totals": {
            "messages": len(messages),
            "typed_messages": n_typed,
            "pasted_messages": len(messages) - n_typed,
            "sessions": len(sessions),
            "projects": len(projects),
            "first": _date(min(stamps)) if stamps else None,
            "last": _date(max(stamps)) if stamps else None,
        },
        "sources": dict(sources.most_common()),
        "languages_pct": {k: _pct(v, n_lang) for k, v in langs.most_common()},
        "length": {
            "words_median": int(statistics.median(words_per_msg)) if words_per_msg else 0,
            "words_p90": _percentile(words_per_msg, 0.9),
            "chars_median": int(statistics.median(chars_per_msg)) if chars_per_msg else 0,
            "chars_p90": _percentile(chars_per_msg, 0.9),
            "short_under_10_words_pct": _pct(sum(w < 10 for w in words_per_msg), n_typed),
            "sentences_per_message_median": (
                int(statistics.median(sentences_per_msg)) if sentences_per_msg else 0
            ),
        },
        "form_pct": {
            "questions": _pct(questions, n_typed),
            "exclamations": _pct(exclaims, n_typed),
            "emoji": _pct(emojis, n_typed),
            "bullet_lists": _pct(bullets, n_typed),
            "no_final_punctuation": _pct(no_final_punct, n_typed),
            "lowercase_start": _pct(lowercase_start, n_typed),
            "corrections": _pct(len(corrections), n_typed),
        },
        "vocabulary": {
            "words": len(all_words),
            "distinct_words": len(set(all_words)),
            "mattr_500": _mattr(all_words),
            "top_words": [w for w, _ in content_counter.most_common(40)],
        },
        "hours_local": {str(h): hours.get(h, 0) for h in range(24)},
        "weekdays_local": dict(weekdays),
        "recurring_instructions": [
            {
                "text": c.representative(),
                "sessions": len(c.sessions),
                "times": c.count,
                "projects": len(c.projects),
                "first": _date(c.first),
                "last": _date(c.last),
                "variants": [v for v, _ in c.variants.most_common(3)],
                "example_message": c.example_idx,
            }
            for c in rule_clusters[:60]
        ],
        "recurring_corrections": [
            {
                "text": c.representative(),
                "sessions": len(c.sessions),
                "times": c.count,
                "example_message": c.example_idx,
            }
            for c in corr_clusters[:30]
        ],
        "correction_openings": [{"opening": o, "times": n} for o, n in openings],
        "recurring_phrases": recurring_phrases(
            messages,
            min_sessions,
            skip_in=[
                " ".join(tokens(v)) for c in rule_clusters + corr_clusters for v in c.variants
            ],
        ),
        "topics_by_project": topics[:40],
    }


def print_stats(stats: dict, out=None) -> None:
    out = out or sys.stdout
    t = stats["totals"]

    def p(s: str = "") -> None:
        print(s, file=out)

    p("== How you work: step 1 (local, no model)")
    p(
        f"  {t['messages']} messages you typed, {t['sessions']} sessions, {t['projects']} projects,"
        f" {t['first'] or '?'} to {t['last'] or '?'}"
    )
    p(
        f"  {t['pasted_messages']} look pasted (code, logs, documents): counted, left out of style stats"
    )
    p("  sources: " + ", ".join(f"{k} {v}" for k, v in stats["sources"].items()))
    if stats["languages_pct"]:
        p("  languages: " + ", ".join(f"{k} {v}%" for k, v in stats["languages_pct"].items()))
    ln = stats["length"]
    p(
        f"  length: median {ln['words_median']} words (90% under {ln['words_p90']}),"
        f" {ln['short_under_10_words_pct']}% under 10 words"
    )
    f = stats["form_pct"]
    p(
        f"  form: questions {f['questions']}%, corrections {f['corrections']}%,"
        f" no final punctuation {f['no_final_punctuation']}%, lists {f['bullet_lists']}%,"
        f" emoji {f['emoji']}%"
    )
    v = stats["vocabulary"]
    p(f"  vocabulary: {v['distinct_words']} distinct words of {v['words']}, MATTR {v['mattr_500']}")
    ri = stats["recurring_instructions"]
    p(f"  recurring instructions: {len(ri)}")
    for r in ri[:15]:
        p(f"    [{r['sessions']} sessions] {r['text'][:140]}")
    rc = stats["recurring_corrections"]
    if rc:
        p(f"  recurring corrections: {len(rc)}")
        for r in rc[:8]:
            p(f"    [{r['sessions']} sessions] {r['text'][:140]}")
    if stats["topics_by_project"]:
        p("  topics by project:")
        for tp in stats["topics_by_project"][:10]:
            p(f"    {tp['project']} ({tp['messages']} messages): {', '.join(tp['keywords'][:8])}")


# ---------------------------------------------------------------------------
# Step 2: what is sent, and the model call
# ---------------------------------------------------------------------------


def _summary_block(stats: dict) -> tuple[str, int, int]:
    """The step 1 summary as sent, redacted. Returns (text, redactions made here,
    redaction markers the readers had already left in the quoted sentences)."""
    t = stats["totals"]
    lines = [
        "# Evidence: how this person works with AI assistants",
        f"{t['messages']} messages typed by the person ({t['typed_messages']} typed prose,"
        f" {t['pasted_messages']} pasted material) in {t['sessions']} sessions across"
        f" {t['projects']} projects, from {t['first'] or '?'} to {t['last'] or '?'}.",
        "Sources: " + ", ".join(f"{k} {v}" for k, v in stats["sources"].items()) + ".",
        "",
        "## Numbers (computed locally)",
    ]
    if stats["languages_pct"]:
        lines.append(
            "- languages: " + ", ".join(f"{k} {v}%" for k, v in stats["languages_pct"].items())
        )
    ln, f, v = stats["length"], stats["form_pct"], stats["vocabulary"]
    lines += [
        f"- message length: median {ln['words_median']} words, 90th percentile {ln['words_p90']};"
        f" {ln['short_under_10_words_pct']}% under 10 words",
        f"- form: questions {f['questions']}%, exclamations {f['exclamations']}%, emoji {f['emoji']}%,"
        f" bullet lists {f['bullet_lists']}%, no final punctuation {f['no_final_punctuation']}%,"
        f" lowercase start {f['lowercase_start']}%",
        f"- corrections of the assistant: {f['corrections']}% of messages",
        f"- vocabulary: {v['distinct_words']} distinct words, MATTR {v['mattr_500']};"
        f" most used: {', '.join(v['top_words'][:25])}",
    ]
    busiest = sorted(stats["hours_local"].items(), key=lambda kv: -kv[1])[:4]
    if any(c for _, c in busiest):
        lines.append("- busiest hours (local): " + ", ".join(f"{h}:00" for h, c in busiest if c))
    lines += ["", "## Recurring instructions (count = distinct sessions where it appears)"]
    for r in stats["recurring_instructions"]:
        alt = [x for x in r["variants"] if x != r["text"]][:2]
        extra = f"  (also: {' | '.join(alt)})" if alt else ""
        lines.append(f"- [{r['sessions']} sessions, {r['times']} times] {r['text']}{extra}")
    if stats["recurring_corrections"] or stats["correction_openings"]:
        lines += ["", "## Corrections given most often"]
        for r in stats["recurring_corrections"]:
            lines.append(f"- [{r['sessions']} sessions] {r['text']}")
        if stats["correction_openings"]:
            lines.append(
                "- usual openings: "
                + ", ".join(
                    f'"{o["opening"]}" ({o["times"]})' for o in stats["correction_openings"]
                )
            )
    if stats["recurring_phrases"]:
        lines += [
            "",
            "## Recurring phrases (word sequences repeated across sessions; count = sessions)",
        ]
        lines += [f"- [{r['sessions']}] {r['phrase']}" for r in stats["recurring_phrases"]]
    if stats["topics_by_project"]:
        lines += ["", "## Topics by project"]
        for tp in stats["topics_by_project"]:
            span = f"{tp['first'] or '?'} to {tp['last'] or '?'}"
            lines.append(
                f"- {tp['project']}: {tp['messages']} messages, {tp['sessions']} sessions, {span};"
                f" keywords: {', '.join(tp['keywords'])}"
            )
    raw = "\n".join(lines)
    text, n = redact(raw)
    return text, n, count_markers(raw)


def select_sample(
    messages: list[Message], stats: dict, budget: int, seed: int = 7
) -> list[tuple[Message, str, int]]:
    """Pick messages to show the model, within `budget` characters (after redaction).
    Order: one example per recurring instruction, then corrections, then typed messages
    taken round-robin over projects in a fixed pseudo-random order (so the whole period is
    covered, not only the latest weeks). Returns (message, redacted body, redactions made
    by this pass)."""
    chosen: list[tuple[Message, str, int]] = []
    used: set[int] = set()
    spent = 0

    def take(m: Message) -> bool:
        nonlocal spent
        if m.idx in used or m.paste:
            return False
        body, n = redact(m.text[:PER_MESSAGE_CAP])
        cost = len(body) + 80  # header line of each message
        if spent + cost > budget:
            return False
        chosen.append((m, body, n))
        used.add(m.idx)
        spent += cost
        return True

    by_idx = {m.idx: m for m in messages}
    for r in stats.get("recurring_instructions", [])[:40]:
        m = by_idx.get(r.get("example_message", -1))
        if m:
            take(m)
    rng = random.Random(seed)
    corrections = [m for m in messages if m.correction and not m.paste]
    rng.shuffle(corrections)
    for m in corrections[:30]:
        take(m)

    buckets: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        if not m.paste and m.idx not in used and len(m.text) >= 20:
            buckets[m.project].append(m)
    for proj in sorted(buckets):
        rng.shuffle(buckets[proj])
    order = sorted(buckets, key=lambda p: (-len(buckets[p]), p))
    misses = 0
    while order and misses < 200:
        progressed = False
        for proj in list(order):
            if not buckets[proj]:
                order.remove(proj)
                continue
            m = buckets[proj].pop()
            if take(m):
                progressed = True
                misses = 0
            else:
                misses += 1
        if not progressed and spent >= budget * 0.98:
            break
    chosen.sort(key=lambda mb: (mb[0].ts or datetime.min.replace(tzinfo=UTC), mb[0].idx))
    return chosen


def build_evidence(messages: list[Message], stats: dict, max_chars: int) -> tuple[str, dict]:
    """The text sent to the model (identical for every file) and its accounting."""
    summary, summary_redactions, summary_markers = _summary_block(stats)
    if len(summary) > max_chars // 2:
        summary = (
            summary[: max_chars // 2].rsplit("\n", 1)[0] + "\n[summary cut to fit --max-chars]"
        )
    header = (
        "\n\n## Sample of messages typed by the person"
        " (verbatim, redacted, chosen by: recurring instructions, corrections, then spread"
        " over projects and time)\n"
    )
    budget = max(0, max_chars - len(summary) - len(header))
    sample = select_sample(messages, stats, budget)
    parts = [summary, header]
    this_pass = summary_redactions
    by_readers = summary_markers
    for m, body, n in sample:
        this_pass += n
        by_readers += count_markers(m.text[:PER_MESSAGE_CAP])
        date = m.ts.date().isoformat() if m.ts else "?"
        cut = ' cut="yes"' if len(m.text) > PER_MESSAGE_CAP else ""
        parts.append(
            f'<msg source="{m.source}" project="{m.project}" date="{date}"{cut}>\n{body}\n</msg>\n'
        )
    evidence = "".join(parts)
    info = {
        "sample_messages": len(sample),
        "sample_sessions": len({m.session_id for m, _, _ in sample}),
        "summary_chars": len(summary),
        "evidence_chars": len(evidence),
        # redactions in what is sent: the readers' (already in messages.jsonl) plus
        # this script's own pass over the sample and the summary
        "redactions_by_readers": by_readers,
        "redactions_this_pass": this_pass,
        "redactions_in_sample": by_readers + this_pass,
    }
    return evidence, info


def _read_constant(src: Path, name: str):
    """Value of a module-level literal assignment, read without importing the module."""
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


# Used only if tools/cross-source/xs-l3-draft.py cannot be read; keep in step with its
# SEGMENT_SYSTEM_SECTIONS.
DEFAULT_PLAYBOOK_HEADERS = [
    "#### Investors",
    "#### Clients",
    "#### Partners",
    "#### Team",
    "#### Family / friends",
    "#### Other",
]


def _playbook_headers() -> list[str]:
    """Section headers the draft writer looks for (SEGMENT_SYSTEM_SECTIONS in
    tools/cross-source/xs-l3-draft.py), in its order."""
    value = _read_constant(_CROSS_SOURCE_DIR / "xs-l3-draft.py", "SEGMENT_SYSTEM_SECTIONS")
    if not isinstance(value, dict):
        return list(DEFAULT_PLAYBOOK_HEADERS)
    headers = [v for v in value.values() if isinstance(v, str) and v.startswith("#### ")]
    return headers or list(DEFAULT_PLAYBOOK_HEADERS)


def default_model(provider: str) -> str:
    """The model call_claude uses when none is passed (read from xs_l3_common.py)."""
    if provider == "anthropic":
        value = _read_constant(_CROSS_SOURCE_DIR / "xs_l3_common.py", "DEFAULT_MODEL")
        return value if isinstance(value, str) else "(repo default)"
    cfg = _read_constant(_CROSS_SOURCE_DIR / "xs_l3_common.py", "PROVIDER_CONFIG")
    if isinstance(cfg, dict) and isinstance(cfg.get(provider), dict):
        return str(cfg[provider].get("default_model") or "(provider default)")
    return "(provider default)"


COMMON_RULES = """You write one file of a private profile that AI tools will read to work the way this
person works. The evidence above comes only from messages the person typed to AI assistants.

Rules:
- Base every statement on the evidence. Where the evidence is thin, say so in one line; never invent.
- Write to the person in the second person ("you"). No praise, no judgement of their character.
- Short quotes of the person's own words are welcome when they show the point (keep their language).
- Leave out credentials, secrets, contact details of other people and anything marked [REDACTED].
- Output only the Markdown content of the file, starting with its H1 title. No preamble, no code fence.
- Write the file in {lang}."""

FILE_TASKS: dict[str, str] = {
    "profile.md": """File: profile.md, title "# Profile".
What you work on and how, as seen through your AI conversations: the domains and kinds of work, the
projects (by the names in the evidence) and what each is about, the tools and stacks you use, the
recurring goals, what you hand to an AI and what you keep for yourself. Sections: Work and domains,
Projects, Tools, What you ask AI for, Open questions (what the evidence cannot tell).""",
    "style-guide.md": """File: style-guide.md, title "# Style guide".
How you write, so a draft can sound like you: length, sentence shape, punctuation habits, register,
languages and when each is used, words and phrases you use often, words you avoid or correct, how you
open and close, use of lists, emoji and formatting. Use the numbers from the evidence. End with a short
"Do" and "Don't" list a writer can follow.""",
    "communication-playbook.md": """File: communication-playbook.md, title "# Communication playbook".
How you talk to different people, as far as the evidence shows (messages you asked an AI to draft or
fix, instructions about tone with investors, clients, partners, team, family and friends, everyone
else). Start with a
general section "## General". Then add exactly these level-4 headers, in this order, each followed by
what the evidence says or "No evidence yet." (tools look these headers up verbatim):
{headers}""",
    "decision-framework.md": """File: decision-framework.md, title "# Decision framework".
How you decide, as seen in your conversations: what you weigh, what you ask to see before deciding,
how you treat risk, cost and time, when you leave a choice to the AI and when you overrule it, the
trade-offs you choose again and again. Use concrete examples from the evidence (dated when the evidence
has dates). Sections: Principles, How you evaluate options, What you leave to the AI, Recurring
trade-offs, Examples.""",
    "working-rules.md": """File: working-rules.md, title "# Working rules".
The instructions you give your AI assistants habitually, rewritten as a clean list of rules an
assistant can follow from the first message: one rule per line, imperative, grouped under short
headings (for example Communication, Code, Process, Files, Safety). Put the most repeated first and
add the number of sessions in brackets, e.g. "- Never ... [12 sessions]". Include the corrections you
make most often, rewritten as rules. Leave out one-off instructions tied to a single task.""",
}


def file_prompt(name: str, lang: str) -> str:
    task = FILE_TASKS[name]
    if "{headers}" in task:
        headers = _playbook_headers()
        task = task.replace("{headers}", "\n".join(headers))
    return task + "\n\n" + COMMON_RULES.replace("{lang}", lang)


def _language_name(code: str) -> str:
    return {
        "en": "English",
        "it": "Italian",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
    }.get(code, "English")


def resolve_language(arg: str, stats: dict) -> str:
    if arg != "auto":
        return _language_name(arg) if len(arg) == 2 else arg
    langs = stats.get("languages_pct") or {}
    return _language_name(next(iter(langs), "en"))


def target_path(out_dir: Path, name: str, force: bool) -> Path:
    path = out_dir / name
    if path.exists() and not force:
        return out_dir / (name[:-3] + ".new.md")
    return path


def _strip_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", t, re.DOTALL)
    return m.group(1).strip() if m else t


def _default_caller() -> Callable[..., str]:
    """The repo's model call path. Imported only when something is really sent."""
    from xs_l3_common import call_claude

    return call_claude


def print_plan(
    args, stats: dict, info: dict, files: list[str], targets: dict, model: str, out=None
):
    out = out or sys.stdout
    host, key_env = PROVIDER_HOSTS[args.provider]
    calls = len(files)
    per_call = info["evidence_chars"] + max(len(file_prompt(f, "English")) for f in files)
    t = stats["totals"]

    def p(s: str = "") -> None:
        print(s, file=out)

    p("== How you work: step 2, what would be sent")
    p(f"  provider: {args.provider} ({host}), key from {key_env}, model: {model}")
    p(
        f"  sample: {info['sample_messages']} of {t['typed_messages']} typed messages"
        f" ({info['sample_sessions']} sessions), plus the step 1 summary ({info['summary_chars']} chars)"
    )
    p(
        f"  redacted in what would be sent: {info['redactions_in_sample']} in total"
        f" (secrets, e-mail addresses, phone numbers): {info['redactions_by_readers']} by the"
        f" readers when they saved your messages, {info['redactions_this_pass']} more in this pass"
    )
    p(
        f"  characters: {info['evidence_chars']} of evidence (cap --max-chars {args.max_chars}),"
        f" about {per_call} per call, {calls} calls (one per file),"
        f" about {per_call * calls} in total (~{per_call * calls // 4} tokens)"
    )
    if args.provider == "anthropic":
        p("  the evidence is sent as a cached system prompt, so calls after the first reuse it")
    p("  files:")
    for f in files:
        dest = targets[f]
        note = (
            "  (exists: writing .new.md, use --force to replace)"
            if dest.name.endswith(".new.md")
            else ""
        )
        p(f"    {dest}{note}")


def run(argv: list[str] | None = None, caller: Callable[..., str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the identity files (how you work) from the messages you typed to AI assistants.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--input",
        type=Path,
        help="messages.jsonl (default: $SBK_DATA_ROOT/ai-history/messages.jsonl)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=IDENTITY_DIR,
        help=f"identity folder (default: {IDENTITY_DIR})",
    )
    ap.add_argument(
        "--stats-out",
        type=Path,
        help="step 1 JSON (default: $SBK_DATA_ROOT/ai-history/how-you-work-stats.json)",
    )
    ap.add_argument("--stats-only", action="store_true", help="run step 1 only, no plan, no model")
    ap.add_argument(
        "--dry-run", action="store_true", help="show what would be sent and to whom; send nothing"
    )
    ap.add_argument(
        "--show-payload",
        action="store_true",
        help="with --dry-run, also save the exact evidence text locally",
    )
    ap.add_argument(
        "--yes",
        action="store_true",
        help="consent: send the sample to the model and write the files",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="replace existing identity files instead of writing *.new.md",
    )
    ap.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"cap on the evidence characters per call (default {DEFAULT_MAX_CHARS})",
    )
    ap.add_argument("--provider", choices=sorted(PROVIDER_HOSTS), default="anthropic")
    ap.add_argument(
        "--model", default="", help="model id (default: the repo default for the provider)"
    )
    ap.add_argument("--only", nargs="+", choices=IDENTITY_FILES, help="write only these files")
    ap.add_argument(
        "--lang",
        default="auto",
        help="language of the files: auto (your most used), en, it, es, fr, de, pt",
    )
    ap.add_argument(
        "--min-sessions",
        type=int,
        default=DEFAULT_MIN_SESSIONS,
        help="sessions needed to call an instruction recurring",
    )
    ap.add_argument(
        "--max-messages", type=int, default=0, help="read at most this many messages (0 = all)"
    )
    args = ap.parse_args(argv)

    if args.max_chars < 2000:
        print("--max-chars must be at least 2000", file=sys.stderr)
        return 2

    root = data_root()
    inp = args.input or root / "ai-history" / "messages.jsonl"
    if not inp.exists():
        print(
            f"No AI history found at {inp}. Run the ai-history readers first"
            " (they write messages.jsonl), or pass --input.",
            file=sys.stderr,
        )
        return 1

    loaded = load_messages(inp, args.max_messages or None)
    if not loaded.messages:
        print(
            f"{inp} has no messages with text ({loaded.bad_lines} unreadable lines). Nothing to do.",
            file=sys.stderr,
        )
        return 1
    if loaded.bad_lines:
        print(f"  note: {loaded.bad_lines} unreadable lines skipped")

    stats = compute_stats(loaded.messages, args.min_sessions)
    stats_out = args.stats_out or root / "ai-history" / "how-you-work-stats.json"
    stats_out.parent.mkdir(parents=True, exist_ok=True)
    stats_out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print_stats(stats)
    print(f"  saved: {stats_out}")
    if args.stats_only:
        return 0

    files = list(args.only or IDENTITY_FILES)
    targets = {f: target_path(args.out_dir, f, args.force) for f in files}
    evidence, info = build_evidence(loaded.messages, stats, args.max_chars)
    model = args.model or default_model(args.provider)
    print()
    print_plan(args, stats, info, files, targets, model)

    if args.dry_run:
        if args.show_payload:
            pay = root / "ai-history" / "how-you-work-payload.txt"
            pay.write_text(evidence, encoding="utf-8")
            print(f"  exact evidence text saved for review (not sent): {pay}")
        print("\nDry run: nothing was sent, nothing was written in the identity folder.")
        return 0
    if not args.yes:
        print(
            "\nNothing was sent. To send this sample and write the files, run again with --yes"
            " (add --dry-run --show-payload to read the exact text first)."
        )
        return 2

    try:
        call = caller or _default_caller()
    except Exception as e:
        print(f"Cannot load the model call path: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    lang = resolve_language(args.lang, stats)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t = stats["totals"]
    stamp = datetime.now().astimezone().date().isoformat()
    written, failed = [], []
    for name in files:
        print(f"  writing {name} ...", flush=True)
        kwargs = {
            "prompt": file_prompt(name, lang),
            "system": evidence,
            "max_tokens": 4096,
            "temperature": 0.2,
            "provider": args.provider,
            "cache_system": args.provider == "anthropic",
        }
        if args.model:
            kwargs["model"] = args.model
        try:
            text = _strip_fence(call(**kwargs) or "")
        except Exception as e:  # report and keep the files already written
            print(f"  model call failed for {name}: {type(e).__name__}: {e}", file=sys.stderr)
            failed.append(name)
            continue
        if not text:
            print(f"  empty answer for {name}, nothing written", file=sys.stderr)
            failed.append(name)
            continue
        text, _ = redact(text)
        header = (
            f"<!-- Generated by {SCRIPT_NAME} on {stamp} from {info['sample_messages']} of"
            f" {t['typed_messages']} messages you typed ({t['first'] or '?'} to {t['last'] or '?'})."
            " Edit freely: a new run writes a .new.md next to this file unless you pass --force. -->\n\n"
        )
        dest = targets[name]
        dest.write_text(header + text.rstrip() + "\n", encoding="utf-8")
        written.append(dest)
        print(f"  saved: {dest}")

    if any(p.name.endswith(".new.md") for p in written):
        print(
            "\nSome files already existed: the new versions are the *.new.md files."
            " Compare them and keep what you want (SBK reads only the names without .new)."
        )
    if failed:
        print(f"\nNot written: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
