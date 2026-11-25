""











from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import DATA_ROOT, OWN_EMAILS, attio_transcript_files, is_owner_speaker

log = logging.getLogger("rq.content_quality")

DICTIONARIES_PATH = Path(__file__).resolve().parent / "content-quality-dictionaries.json"


_QUOTE_LINE_RE = re.compile(r"^>.*$", re.MULTILINE)
_ON_WROTE_RE = re.compile(r"^On .{10,80} wrote:\s*$", re.MULTILINE | re.IGNORECASE)
_FWD_HEADER_RE = re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}", re.MULTILINE | re.IGNORECASE)


_RE_FWD_PREFIX = re.compile(r"^(Re|Fwd|Fw|R|I)\s*:\s*", re.IGNORECASE)





def _load_dictionaries() -> dict:
    ""
    with open(DICTIONARIES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _extract_email(addr: str) -> str:
    ""
    if "<" in addr and ">" in addr:
        return addr.split("<")[1].split(">")[0].strip().lower()
    return addr.strip().lower()


def _is_own_email(addr: str) -> bool:
    return _extract_email(addr) in {e.lower() for e in OWN_EMAILS}


def _strip_quoted_reply(body: str) -> str:
    ""

    m = _ON_WROTE_RE.search(body)
    if m:
        body = body[: m.start()]

    m = _FWD_HEADER_RE.search(body)
    if m:
        body = body[: m.start()]

    body = _QUOTE_LINE_RE.sub("", body)
    return body.strip()


def _load_email_bodies(emails_dir: Path | None = None) -> pd.DataFrame:
    ""



    if emails_dir is None:
        emails_dir = DATA_ROOT / "emails"
    filtered = emails_dir / "filtered-messages.parquet"
    if filtered.exists():
        return pd.read_parquet(
            filtered,
            columns=["from_addr", "to_addr", "date", "body_text", "subject"],
        )

    frames = []
    for pq in sorted(emails_dir.glob("*/messages.parquet")):
        try:
            df = pd.read_parquet(
                pq, columns=["from_addr", "to_addr", "date", "body_text", "subject"]
            )
            frames.append(df)
        except Exception:
            continue
    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(columns=["from_addr", "to_addr", "date", "body_text", "subject"])


def _group_emails_by_person(
    email_df: pd.DataFrame,
) -> dict[str, list[dict]]:
    ""




    own_lower = {e.lower() for e in OWN_EMAILS}
    groups: dict[str, list[dict]] = defaultdict(list)

    for _, row in email_df.iterrows():
        from_addr = str(row.get("from_addr", ""))
        to_addr = str(row.get("to_addr", ""))
        body = str(row.get("body_text", ""))
        subject = str(row.get("subject", ""))
        date = str(row.get("date", ""))

        if not body or len(body) < 20:
            continue

        from_email = _extract_email(from_addr)

        if from_email in own_lower:

            for addr in re.split(r"[,;]", to_addr):
                other = _extract_email(addr.strip())
                if other and other not in own_lower:
                    groups[other].append(
                        {"body": body, "subject": subject, "date": date, "direction": "sent"}
                    )
        else:

            groups[from_email].append(
                {"body": body, "subject": subject, "date": date, "direction": "received"}
            )

    return dict(groups)


def _load_slack_dm_texts() -> dict[str, str]:
    ""



    path = DATA_ROOT / "slack" / "processed" / "channel-texts.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    if "channel_type" not in df.columns or "dm_with" not in df.columns:
        return {}
    dm = df[df["channel_type"] == "dm"]
    result: dict[str, str] = {}
    for _, row in dm.iterrows():
        user = str(row.get("dm_with", "")).strip()
        text = str(row.get("channel_text", ""))
        if user and text:
            result[user] = text
    return result


def _tokenize(text: str) -> list[str]:
    ""
    return re.findall(r"\b\w+\b", text.lower())





def extract_formality_score(
    person_emails: dict[str, list[dict]],
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""




    if dicts is None:
        dicts = _load_dictionaries()
    formal_greet = [g.lower() for g in dicts["greeting_formal"]]
    semi_greet = [g.lower() for g in dicts["greeting_semi"]]
    informal_greet = [g.lower() for g in dicts["greeting_informal"]]
    formal_sign = [s.lower() for s in dicts["signoff_formal"]]
    semi_sign = [s.lower() for s in dicts["signoff_semi"]]
    informal_sign = [s.lower() for s in dicts["signoff_informal"]]

    result: dict[str, tuple[float, int]] = {}

    for email, msgs in person_emails.items():
        scores = []
        for msg in msgs:
            body = _strip_quoted_reply(msg["body"])
            if len(body) < 20:
                continue
            first_500 = body[:500].lower()
            last_300 = body[-300:].lower()


            g_score = 0.8
            for g in formal_greet:
                if g in first_500:
                    g_score = 0.0
                    break
            else:
                for g in semi_greet:
                    if g in first_500:
                        g_score = 0.4
                        break
                else:
                    for g in informal_greet:
                        if g in first_500:
                            g_score = 0.8
                            break


            s_score = 0.8
            for s in formal_sign:
                if s in last_300:
                    s_score = 0.0
                    break
            else:
                for s in semi_sign:
                    if s in last_300:
                        s_score = 0.4
                        break
                else:
                    for s in informal_sign:
                        if s in last_300:
                            s_score = 0.9
                            break


            sentences = [s.strip() for s in re.split(r"[.!?]+", body) if len(s.strip()) > 5]
            if sentences:
                avg_words = sum(len(s.split()) for s in sentences) / len(sentences)
                if avg_words > 20:
                    l_score = 0.0
                elif avg_words > 15:
                    l_score = 0.3
                elif avg_words > 10:
                    l_score = 0.5
                elif avg_words > 7:
                    l_score = 0.7
                else:
                    l_score = 1.0
            else:
                l_score = 0.5

            formality = g_score * 0.4 + s_score * 0.3 + l_score * 0.3
            scores.append(formality)

        if scores:
            result[email] = (round(sum(scores) / len(scores), 4), len(scores))

    return result


def extract_formality_trend(
    person_emails: dict[str, list[dict]],
    dicts: dict | None = None,
) -> dict[str, float]:
    ""




    formality_fn = extract_formality_score
    now = pd.Timestamp.now(tz="UTC")
    cutoff_recent = now - pd.Timedelta(days=90)
    cutoff_earlier = now - pd.Timedelta(days=180)

    result: dict[str, float] = {}

    for email, msgs in person_emails.items():
        recent = []
        earlier = []
        for msg in msgs:
            try:
                dt = pd.Timestamp(msg["date"])
                if dt.tzinfo is None:
                    dt = dt.tz_localize("UTC")
            except Exception:
                continue
            if dt >= cutoff_recent:
                recent.append(msg)
            elif dt >= cutoff_earlier:
                earlier.append(msg)

        if len(recent) < 3 or len(earlier) < 3:
            continue

        recent_score = formality_fn({email: recent}, dicts)
        earlier_score = formality_fn({email: earlier}, dicts)

        if email in recent_score and email in earlier_score:
            delta = recent_score[email][0] - earlier_score[email][0]
            result[email] = round(delta, 4)

    return result


def extract_self_disclosure_count(
    person_emails: dict[str, list[dict]],
    slack_dm_texts: dict[str, str] | None = None,
    dicts: dict | None = None,
) -> dict[str, tuple[int, int]]:
    ""



    if dicts is None:
        dicts = _load_dictionaries()
    patterns = [re.compile(p, re.IGNORECASE) for p in dicts["self_disclosure_patterns"]]

    result: dict[str, tuple[int, int]] = {}


    for email, msgs in person_emails.items():
        count = 0
        for msg in msgs:
            body = _strip_quoted_reply(msg["body"])
            for pat in patterns:
                count += len(pat.findall(body))
        if count > 0 or msgs:
            result[email] = (count, len(msgs))


    if slack_dm_texts:
        for user, text in slack_dm_texts.items():
            count = 0
            for pat in patterns:
                count += len(pat.findall(text))

            msg_count = max(1, text.count("\n"))
            if count > 0:
                result.setdefault(user, (0, 0))
                prev_count, prev_msgs = result.get(user, (0, 0))
                result[user] = (prev_count + count, prev_msgs + msg_count)

    return result


def extract_emotional_word_density(
    person_emails: dict[str, list[dict]],
    slack_dm_texts: dict[str, str] | None = None,
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""




    if dicts is None:
        dicts = _load_dictionaries()
    emo_words = set()
    for w in dicts.get("emotional_positive", []):
        emo_words.add(w.lower())
    for w in dicts.get("emotional_negative", []):
        emo_words.add(w.lower())

    result: dict[str, tuple[float, int]] = {}

    for email, msgs in person_emails.items():
        total_emo = 0
        total_words = 0
        for msg in msgs:
            body = _strip_quoted_reply(msg["body"])
            words = _tokenize(body)
            total_words += len(words)
            total_emo += sum(1 for w in words if w in emo_words)
        if total_words > 0:
            result[email] = (round(total_emo / total_words, 6), total_words)

    if slack_dm_texts:
        for user, text in slack_dm_texts.items():
            words = _tokenize(text)
            if not words:
                continue
            emo_count = sum(1 for w in words if w in emo_words)
            density = round(emo_count / len(words), 6)
            if user in result:
                prev_d, prev_w = result[user]
                total_w = prev_w + len(words)
                merged = round((prev_d * prev_w + density * len(words)) / total_w, 6)
                result[user] = (merged, total_w)
            elif emo_count > 0:
                result[user] = (density, len(words))

    return result


def extract_inclusive_pronoun_ratio(
    person_emails: dict[str, list[dict]],
    slack_dm_texts: dict[str, str] | None = None,
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""




    if dicts is None:
        dicts = _load_dictionaries()
    inclusive = set(w.lower() for w in dicts["inclusive_pronouns"])
    individual = set(w.lower() for w in dicts["individual_pronouns"])

    result: dict[str, tuple[float, int]] = {}

    for email, msgs in person_emails.items():
        inc_count = 0
        ind_count = 0
        for msg in msgs:
            body = _strip_quoted_reply(msg["body"])
            words = _tokenize(body)
            inc_count += sum(1 for w in words if w in inclusive)
            ind_count += sum(1 for w in words if w in individual)
        total = inc_count + ind_count
        if total > 0:
            ratio = round(inc_count / (total + 0.0001), 4)
            result[email] = (ratio, total)

    if slack_dm_texts:
        for user, text in slack_dm_texts.items():
            words = _tokenize(text)
            inc = sum(1 for w in words if w in inclusive)
            ind = sum(1 for w in words if w in individual)
            total = inc + ind
            if total > 0:
                ratio = round(inc / (total + 0.0001), 4)
                if user in result:
                    prev_r, prev_t = result[user]
                    merged_t = prev_t + total
                    merged_r = round((prev_r * prev_t + ratio * total) / merged_t, 4)
                    result[user] = (merged_r, merged_t)
                else:
                    result[user] = (ratio, total)

    return result


def extract_humor_markers(
    person_emails: dict[str, list[dict]],
    slack_dm_texts: dict[str, str] | None = None,
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""



    if dicts is None:
        dicts = _load_dictionaries()
    patterns = [re.compile(p, re.IGNORECASE) for p in dicts["humor_patterns"]]
    emoji_set = set(dicts.get("humor_emoji", []))

    result: dict[str, tuple[float, int]] = {}

    for email, msgs in person_emails.items():
        humor_count = 0
        for msg in msgs:
            body = msg["body"]
            for pat in patterns:
                humor_count += len(pat.findall(body))
            humor_count += sum(1 for ch in body if ch in emoji_set)
        if humor_count > 0 and msgs:
            result[email] = (round(humor_count / len(msgs), 4), len(msgs))

    if slack_dm_texts:
        for user, text in slack_dm_texts.items():
            humor_count = 0
            for pat in patterns:
                humor_count += len(pat.findall(text))
            humor_count += sum(1 for ch in text if ch in emoji_set)
            msg_count = max(1, text.count("\n"))
            if humor_count > 0:
                density = round(humor_count / msg_count, 4)
                if user in result:
                    prev_d, prev_m = result[user]
                    total_m = prev_m + msg_count
                    merged = round((prev_d * prev_m + density * msg_count) / total_m, 4)
                    result[user] = (merged, total_m)
                else:
                    result[user] = (density, msg_count)

    return result





def extract_linguistic_style_matching(
    person_emails: dict[str, list[dict]],
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""







    if dicts is None:
        dicts = _load_dictionaries()
    func_words = dicts.get("function_words", {})

    categories: dict[str, set[str]] = {}
    for cat_name, word_list in func_words.items():
        if isinstance(word_list, dict):

            flat = []
            for lang_words in word_list.values():
                flat.extend(lang_words)
            categories[cat_name] = set(w.lower() for w in flat)
        else:
            categories[cat_name] = set(w.lower() for w in word_list)

    result: dict[str, tuple[float, int]] = {}

    for email, msgs in person_emails.items():
        owner_texts = [_strip_quoted_reply(m["body"]) for m in msgs if m["direction"] == "sent"]
        other_texts = [_strip_quoted_reply(m["body"]) for m in msgs if m["direction"] == "received"]

        if len(owner_texts) < 5 or len(other_texts) < 5:
            continue

        owner_words = _tokenize(" ".join(owner_texts))
        other_words = _tokenize(" ".join(other_texts))

        if not owner_words or not other_words:
            continue

        lsm_scores = []
        for cat_name, cat_words in categories.items():
            owner_count = sum(1 for w in owner_words if w in cat_words) / len(owner_words)
            other_count = sum(1 for w in other_words if w in cat_words) / len(other_words)
            lsm_cat = 1.0 - abs(owner_count - other_count) / (owner_count + other_count + 0.0001)
            lsm_scores.append(lsm_cat)

        if lsm_scores:
            lsm = round(sum(lsm_scores) / len(lsm_scores), 4)
            pair_count = min(len(owner_texts), len(other_texts))
            result[email] = (lsm, pair_count)

    return result


def extract_topic_coherence(
    person_emails: dict[str, list[dict]],
) -> dict[str, float]:
    ""





    result: dict[str, float] = {}

    for email, msgs in person_emails.items():
        subjects = []
        for msg in msgs:
            subj = str(msg.get("subject", ""))

            subj = _RE_FWD_PREFIX.sub("", subj).strip()
            if len(subj) > 3:
                subjects.append(subj.lower())

        if len(subjects) < 3:
            continue


        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "to",
            "in",
            "for",
            "of",
            "and",
            "or",
            "il",
            "la",
            "le",
            "di",
            "da",
            "per",
            "con",
            "che",
            "un",
            "una",
            "e",
            "re",
            "fwd",
            "fw",
        }
        kw_sets = []
        for subj in subjects:
            words = set(_tokenize(subj)) - stopwords
            if words:
                kw_sets.append(words)

        if not kw_sets:
            continue


        clusters: list[set[str]] = [kw_sets[0]]
        for kw in kw_sets[1:]:
            merged = False
            for cluster in clusters:
                intersection = len(kw & cluster)
                union = len(kw | cluster)
                if union > 0 and intersection / union >= 0.3:
                    cluster.update(kw)
                    merged = True
                    break
            if not merged:
                clusters.append(kw.copy())

        coherence = round(1.0 / (1.0 + len(clusters) / 10.0), 4)
        result[email] = coherence

    return result





MESSAGE_TYPE_PROMPT = """Classify this message into ONE category:
- TRANSACTIONAL: requests, confirmations, scheduling, invoices
- COORDINATIVE: project updates, status reports, task assignments
- INFORMATIONAL: sharing news, articles, knowledge
- RELATIONAL: personal check-ins, emotional support, humor, non-work topics
- STRATEGIC: advice, decisions, confidential discussions, strategy

Message: {message_text}
Category:"""


def extract_message_types_llm(
    person_emails: dict[str, list[dict]],
    max_per_person: int = 50,
) -> dict[str, dict[str, int]]:
    ""





    raise NotImplementedError(
        "Layer C requires --content-llm flag. Use rq-02b-extract-signals.py --content-llm to run."
    )


def derive_relational_message_ratio(
    message_types: dict[str, dict[str, int]],
) -> dict[str, float]:
    ""
    result: dict[str, float] = {}
    for email, counts in message_types.items():
        total = sum(counts.values())
        if total > 0:
            result[email] = round(counts.get("relational", 0) / total, 4)
    return result


def derive_strategic_discussion_count(
    message_types: dict[str, dict[str, int]],
) -> dict[str, int]:
    ""
    return {email: counts.get("strategic", 0) for email, counts in message_types.items()}





def _load_transcripts(
    tactiq_dir: Path | None = None,
    attio_dir: Path | None = None,
) -> list[dict]:
    ""





    if tactiq_dir is None:
        tactiq_dir = DATA_ROOT / "tactiq" / "raw"
    if attio_dir is None:
        attio_dir = DATA_ROOT / "attio" / "transcripts"

    transcripts: list[dict] = []


    if tactiq_dir.exists():
        for jf in sorted(tactiq_dir.glob("*.json")):
            if jf.name.startswith("_"):
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            blocks = data.get("transcript", {}).get("blocks", [])
            if not blocks:
                continue
            duration = data.get("duration", 0)

            base_ts = None
            segments = []
            for b in blocks:
                if b.get("isDeleted"):
                    continue
                speaker = str(b.get("speakerName", "")).strip()
                text = str(b.get("transcript", "")).strip()
                ts = b.get("timestamp", 0)
                if not speaker or not text:
                    continue
                if isinstance(ts, int | float) and ts > 1_000_000_000:

                    if base_ts is None:
                        base_ts = ts
                    start_sec = (ts - base_ts) / 1000.0
                else:
                    start_sec = float(ts) if ts else 0.0
                segments.append({"speaker": speaker, "text": text, "start_sec": max(0, start_sec)})
            if segments:
                transcripts.append(
                    {
                        "source": "tactiq",
                        "meeting_id": data.get("id", jf.stem),
                        "title": data.get("title", ""),
                        "segments": segments,
                        "duration_sec": float(duration) if duration else 0.0,
                    }
                )



    if attio_dir.exists() or attio_dir == DATA_ROOT / "attio" / "transcripts":
        for jf in attio_transcript_files(attio_dir):
            if jf.name.startswith("_"):
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            raw_segs = data.get("segments", [])
            if not raw_segs:
                continue

            grouped: list[dict] = []
            current_speaker = None
            current_words: list[str] = []
            current_start = 0.0
            for seg in raw_segs:
                speaker = str(seg.get("speaker", "")).strip()
                text = str(seg.get("text", "")).strip()
                start = float(seg.get("start", 0))
                if not speaker or not text:
                    continue
                if speaker == current_speaker:
                    current_words.append(text)
                else:
                    if current_speaker and current_words:
                        grouped.append(
                            {
                                "speaker": current_speaker,
                                "text": " ".join(current_words),
                                "start_sec": current_start,
                            }
                        )
                    current_speaker = speaker
                    current_words = [text]
                    current_start = start
            if current_speaker and current_words:
                grouped.append(
                    {
                        "speaker": current_speaker,
                        "text": " ".join(current_words),
                        "start_sec": current_start,
                    }
                )
            if grouped:

                last_end = float(raw_segs[-1].get("end", 0)) if raw_segs else 0
                transcripts.append(
                    {
                        "source": "attio",
                        "meeting_id": data.get("meeting_id", jf.stem),
                        "title": data.get("meeting_title", ""),
                        "segments": grouped,
                        "duration_sec": last_end,
                    }
                )

    return transcripts


def _is_owner_speaker(name: str) -> bool:
    ""
    return is_owner_speaker(name)


def _resolve_speaker(name: str, name_matcher) -> str | None:
    ""



    if name_matcher is None:
        return name
    from rq_name_matching import _normalize

    norm = _normalize(name)
    if not norm:
        return None
    if norm in name_matcher._exact_index:
        pid, _ = name_matcher._exact_index[norm]
        return pid
    if norm in name_matcher._nickname_index:
        pid, _ = name_matcher._nickname_index[norm]
        return pid
    return name


def extract_turn_taking_balance(
    transcripts: list[dict] | None = None,
    name_matcher=None,
) -> dict[str, tuple[float, int]]:
    ""





    if transcripts is None:
        transcripts = _load_transcripts()

    person_scores: dict[str, list[float]] = defaultdict(list)

    for t in transcripts:
        owner_words = 0
        others: dict[str, int] = defaultdict(int)
        for seg in t["segments"]:
            word_count = len(seg["text"].split())
            if _is_owner_speaker(seg["speaker"]):
                owner_words += word_count
            else:
                pid = _resolve_speaker(seg["speaker"], name_matcher) or seg["speaker"]
                others[pid] += word_count

        for pid, other_words in others.items():
            total = owner_words + other_words
            if total < 50:
                continue
            owner_ratio = owner_words / total
            balance = 1.0 - abs(owner_ratio - 0.5) * 2
            person_scores[pid].append(balance)

    result: dict[str, tuple[float, int]] = {}
    for pid, scores in person_scores.items():
        if scores:
            result[pid] = (round(sum(scores) / len(scores), 4), len(scores))
    return result


def extract_meeting_warmth(
    transcripts: list[dict] | None = None,
    name_matcher=None,
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""




    if transcripts is None:
        transcripts = _load_transcripts()
    if dicts is None:
        dicts = _load_dictionaries()
    warmth_phrases = [w.lower() for w in dicts["warmth_greetings"]]

    person_scores: dict[str, list[float]] = defaultdict(list)

    for t in transcripts:

        first_120_text = ""
        participants: set[str] = set()
        for seg in t["segments"]:
            if seg["start_sec"] <= 120:
                first_120_text += " " + seg["text"]
                if not _is_owner_speaker(seg["speaker"]):
                    pid = _resolve_speaker(seg["speaker"], name_matcher) or seg["speaker"]
                    participants.add(pid)

        if not participants:
            continue

        first_lower = first_120_text.lower()
        warmth_count = sum(1 for phrase in warmth_phrases if phrase in first_lower)
        warmth_score = min(1.0, warmth_count / 3.0)

        for pid in participants:
            person_scores[pid].append(warmth_score)

    result: dict[str, tuple[float, int]] = {}
    for pid, scores in person_scores.items():
        if scores:
            result[pid] = (round(sum(scores) / len(scores), 4), len(scores))
    return result


def extract_laughter_count(
    transcripts: list[dict] | None = None,
    name_matcher=None,
) -> dict[str, tuple[float, int]]:
    ""



    if transcripts is None:
        transcripts = _load_transcripts()

    _laughter_re = re.compile(
        r"\[laugh(?:ter|ing)?\]|\[risata?\]|\[ride\]|\bahaha?\b|\bhahaha?\b",
        re.IGNORECASE,
    )

    person_scores: dict[str, list[float]] = defaultdict(list)

    for t in transcripts:
        duration_min = t.get("duration_sec", 0) / 60.0
        if duration_min < 1:

            if t["segments"]:
                duration_min = max(1, t["segments"][-1]["start_sec"] / 60.0)
            else:
                continue

        full_text = " ".join(seg["text"] for seg in t["segments"])
        laughter_hits = len(_laughter_re.findall(full_text))
        if laughter_hits == 0:
            continue

        laughter_per_min = laughter_hits / duration_min

        participants: set[str] = set()
        for seg in t["segments"]:
            if not _is_owner_speaker(seg["speaker"]):
                pid = _resolve_speaker(seg["speaker"], name_matcher) or seg["speaker"]
                participants.add(pid)

        for pid in participants:
            person_scores[pid].append(laughter_per_min)

    result: dict[str, tuple[float, int]] = {}
    for pid, scores in person_scores.items():
        if scores:
            result[pid] = (round(sum(scores) / len(scores), 4), len(scores))
    return result


def extract_personal_topic_in_meeting(
    transcripts: list[dict] | None = None,
    name_matcher=None,
    dicts: dict | None = None,
) -> dict[str, tuple[float, int]]:
    ""




    if transcripts is None:
        transcripts = _load_transcripts()
    if dicts is None:
        dicts = _load_dictionaries()
    personal_kw = set(w.lower() for w in dicts["personal_topic_keywords"])

    person_scores: dict[str, list[float]] = defaultdict(list)

    for t in transcripts:
        segs = t["segments"]
        if len(segs) < 5:
            continue


        personal_windows = 0
        total_windows = len(segs) - 4
        for i in range(total_windows):
            window_text = " ".join(segs[j]["text"] for j in range(i, i + 5)).lower()
            words = set(_tokenize(window_text))
            if words & personal_kw:
                personal_windows += 1

        if total_windows <= 0:
            continue

        ratio = personal_windows / total_windows

        participants: set[str] = set()
        for seg in segs:
            if not _is_owner_speaker(seg["speaker"]):
                pid = _resolve_speaker(seg["speaker"], name_matcher) or seg["speaker"]
                participants.add(pid)

        for pid in participants:
            person_scores[pid].append(ratio)

    result: dict[str, tuple[float, int]] = {}
    for pid, scores in person_scores.items():
        if scores:
            result[pid] = (round(sum(scores) / len(scores), 4), len(scores))
    return result





def extract_content_quality_signals(
    emails_dir: Path | None = None,
    name_matcher=None,
    resolver=None,
) -> dict[str, dict[str, float]]:
    ""





    log.info("Loading email bodies...")
    email_df = _load_email_bodies(emails_dir)
    log.info("Loaded %d emails", len(email_df))

    person_emails = _group_emails_by_person(email_df)
    log.info("Grouped emails for %d persons", len(person_emails))

    log.info("Loading Slack DM texts...")
    slack_dm = _load_slack_dm_texts()
    log.info("Loaded %d Slack DMs", len(slack_dm))

    log.info("Loading transcripts...")
    transcripts = _load_transcripts()
    log.info("Loaded %d transcripts", len(transcripts))

    dicts = _load_dictionaries()


    log.info("Layer A: formality...")
    formality = extract_formality_score(person_emails, dicts)
    log.info("Layer A: formality trend...")
    formality_trend = extract_formality_trend(person_emails, dicts)
    log.info("Layer A: self disclosure...")
    disclosure = extract_self_disclosure_count(person_emails, slack_dm, dicts)
    log.info("Layer A: emotional density...")
    emotional = extract_emotional_word_density(person_emails, slack_dm, dicts)
    log.info("Layer A: inclusive pronouns...")
    pronouns = extract_inclusive_pronoun_ratio(person_emails, slack_dm, dicts)
    log.info("Layer A: humor markers...")
    humor = extract_humor_markers(person_emails, slack_dm, dicts)


    log.info("Layer B: LSM...")
    lsm = extract_linguistic_style_matching(person_emails, dicts)
    log.info("Layer B: topic coherence...")
    coherence = extract_topic_coherence(person_emails)


    log.info("Layer D: turn-taking balance...")
    balance = extract_turn_taking_balance(transcripts, name_matcher)
    log.info("Layer D: meeting warmth...")
    warmth = extract_meeting_warmth(transcripts, name_matcher, dicts)
    log.info("Layer D: laughter...")
    laughter = extract_laughter_count(transcripts, name_matcher)
    log.info("Layer D: personal topics in meeting...")
    personal_meeting = extract_personal_topic_in_meeting(transcripts, name_matcher, dicts)


    def _resolve_key(key: str) -> str:
        if resolver is not None:
            resolved = resolver.resolve(key)
            if resolved:
                return resolved
        return key


    merged: dict[str, dict[str, float]] = defaultdict(dict)


    for email, (val, _) in formality.items():
        pid = _resolve_key(email)
        merged[pid]["formality_score"] = val

    for email, val in formality_trend.items():
        pid = _resolve_key(email)
        merged[pid]["formality_trend"] = val

    for key, (val, _) in disclosure.items():
        pid = _resolve_key(key)
        prev = merged[pid].get("self_disclosure_count", 0)
        merged[pid]["self_disclosure_count"] = prev + val

    for key, (val, _) in emotional.items():
        pid = _resolve_key(key)

        prev = merged[pid].get("emotional_word_density", 0.0)
        merged[pid]["emotional_word_density"] = max(prev, val)

    for key, (val, _) in pronouns.items():
        pid = _resolve_key(key)
        prev = merged[pid].get("inclusive_pronoun_ratio", 0.0)
        merged[pid]["inclusive_pronoun_ratio"] = max(prev, val)

    for key, (val, _) in humor.items():
        pid = _resolve_key(key)
        prev = merged[pid].get("humor_markers_density", 0.0)
        merged[pid]["humor_markers_density"] = max(prev, val)


    for email, (val, _) in lsm.items():
        pid = _resolve_key(email)
        merged[pid]["linguistic_style_matching"] = val

    for email, val in coherence.items():
        pid = _resolve_key(email)
        merged[pid]["topic_coherence"] = val


    for key, (val, _) in balance.items():
        pid = _resolve_key(key)
        merged[pid]["turn_taking_balance"] = val

    for key, (val, _) in warmth.items():
        pid = _resolve_key(key)
        merged[pid]["meeting_warmth_score"] = val

    for key, (val, _) in laughter.items():
        pid = _resolve_key(key)
        merged[pid]["laughter_per_minute"] = val

    for key, (val, _) in personal_meeting.items():
        pid = _resolve_key(key)
        merged[pid]["personal_topic_in_meeting"] = val

    log.info("Content quality signals: %d persons with data", len(merged))
    return dict(merged)
