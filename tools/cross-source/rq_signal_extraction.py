""











from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import numpy as np
import pandas as pd

from sbk_config import (
    ENRICHED_DIR,
    GRAPH_DIR,
    NLP_DIR,
    PERSON_CONTEXT_DIR,
    PERSONIO_DIR,
    RQ_DIR,
    SLACK_DIR,
)

log = logging.getLogger("rq.signals")





def _consolidate_weighted_ratio(raw: dict[str, tuple[float, int]], resolver) -> dict[str, float]:
    ""



    groups: dict[str, list[tuple[float, int]]] = {}
    for key, (ratio, count) in raw.items():
        pid = resolver.resolve(key) or key
        groups.setdefault(pid, []).append((ratio, count))

    result: dict[str, float] = {}
    for pid, entries in groups.items():
        if len(entries) == 1:
            result[pid] = entries[0][0]
        else:
            total_count = sum(c for _, c in entries)
            if total_count > 0:
                result[pid] = round(sum(r * c for r, c in entries) / total_count, 4)
    return result


def _consolidate_weighted_harmonic(raw: dict[str, tuple[float, int]], resolver) -> dict[str, float]:
    ""



    groups: dict[str, list[tuple[float, int]]] = {}
    for key, (val, n) in raw.items():
        pid = resolver.resolve(key) or key
        groups.setdefault(pid, []).append((val, n))

    result: dict[str, float] = {}
    for pid, entries in groups.items():
        if len(entries) == 1:
            result[pid] = entries[0][0]
        else:
            total_n = sum(n for _, n in entries)
            if total_n > 0 and all(v > 0 for v, _ in entries):
                result[pid] = round(total_n / sum(n / v for v, n in entries), 2)
            else:
                result[pid] = min(v for v, _ in entries)
    return result


def _consolidate_weighted_avg(raw: dict[str, tuple[float, int]], resolver) -> dict[str, float]:
    ""
    groups: dict[str, list[tuple[float, int]]] = {}
    for key, (val, n) in raw.items():
        pid = resolver.resolve(key) or key
        groups.setdefault(pid, []).append((val, n))

    result: dict[str, float] = {}
    for pid, entries in groups.items():
        if len(entries) == 1:
            result[pid] = entries[0][0]
        else:
            total_n = sum(n for _, n in entries)
            if total_n > 0:
                result[pid] = round(sum(v * n for v, n in entries) / total_n, 4)
    return result


def _consolidate_negatives(raw: dict[str, dict], resolver) -> dict[str, dict]:
    ""



    groups: dict[str, list[dict]] = {}
    for key, val in raw.items():
        pid = resolver.resolve(key) or key
        groups.setdefault(pid, []).append(val)

    result: dict[str, dict] = {}
    for pid, entries in groups.items():
        if len(entries) == 1:
            result[pid] = entries[0]
        else:
            merged: dict = {}
            merged["rejection_count"] = sum(e.get("rejection_count", 0) for e in entries)
            max_ghost = max((e.get("ghosting_score", 0.0) for e in entries), default=0.0)
            if max_ghost > 0:
                merged["ghosting_score"] = max_ghost
            max_osr = max((e.get("one_sided_ratio", 0.0) for e in entries), default=0.0)
            if max_osr > 0:
                merged["one_sided_ratio"] = max_osr
            if any(e.get("is_ex_employee", False) for e in entries):
                merged["is_ex_employee"] = True
            if merged.get("rejection_count", 0) == 0:
                merged.pop("rejection_count", None)
            result[pid] = merged
    return result


def _consolidate_simple(raw: dict[str, float], resolver, merge_fn=max) -> dict[str, float]:
    ""
    groups: dict[str, list[float]] = {}
    for key, val in raw.items():
        pid = resolver.resolve(key) or key
        groups.setdefault(pid, []).append(val)

    return {pid: merge_fn(vals) for pid, vals in groups.items()}


def _extract_email(addr: str) -> str:
    ""
    addr = addr.strip().lower()
    if "<" in addr and ">" in addr:
        return addr.split("<")[1].split(">")[0].strip()
    return addr





def extract_intimacy_family(rf_df: pd.DataFrame) -> dict[str, bool]:
    ""

















    from sbk_config import ENRICHED_DIR, OWN_NAMES_NORMALIZED, OWN_PERSON_ID

    result: dict[str, bool] = {}



    own_surname = ""
    for name in OWN_NAMES_NORMALIZED:
        parts = name.strip().split()
        if len(parts) >= 2:
            own_surname = parts[-1].lower()
            break

    if own_surname:
        cm_path = ENRICHED_DIR / "contacts-merged.parquet"
        if cm_path.exists():
            try:
                cm = pd.read_parquet(cm_path, columns=["person_id", "name"])
                for _, row in cm.iterrows():
                    pid = str(row.get("person_id", ""))
                    name = str(row.get("name", ""))
                    if not pid or pid == OWN_PERSON_ID or not name:
                        continue

                    name_parts = name.strip().split()
                    if len(name_parts) >= 2:
                        candidate_surname = name_parts[-1].lower()
                        if candidate_surname == own_surname:
                            result[pid] = True
            except Exception as e:
                log.warning("Failed to check family surname for person: %s", e)
        log.info("Family (surname '%s'): %d persons", own_surname, len(result))


    if not rf_df.empty:
        family_predicates = {
            "FAMILY_OF",
            "MARRIED_TO",
            "SPOUSE_OF",
            "PARENT_OF",
            "CHILD_OF",
            "SIBLING_OF",
            "BROTHER_OF",
            "SISTER_OF",
            "WIFE_OF",
            "HUSBAND_OF",
        }
        fam_mask = rf_df["predicate"].str.upper().isin(family_predicates)
        fam_df = rf_df[fam_mask]

        sub_col = "subject_person_id"
        obj_col = "object_person_id"
        if not fam_df.empty and sub_col in fam_df.columns and obj_col in fam_df.columns:
            facts_count = 0
            for _, row in fam_df.iterrows():
                subj = str(row.get(sub_col, "")).strip()
                obj = str(row.get(obj_col, "")).strip()
                if subj == OWN_PERSON_ID and obj.startswith("p_") and obj != OWN_PERSON_ID:
                    if obj not in result:
                        result[obj] = True
                        facts_count += 1
                elif obj == OWN_PERSON_ID and subj.startswith("p_") and subj != OWN_PERSON_ID:
                    if subj not in result:
                        result[subj] = True
                        facts_count += 1
            if facts_count > 0:
                log.info("Family (relationship facts): +%d persons", facts_count)

    log.info("Family flag total: %d persons", len(result))
    return result





_PERSONAL_PREDICATES = {"HOBBY", "HEALTH", "BIRTHDAY", "PERSONAL_INTEREST", "PET", "FAMILY_EVENT"}


def extract_intimacy_personal_topics(rf_df: pd.DataFrame) -> dict[str, int]:
    ""







    if rf_df.empty:
        return {}
    mask = rf_df["predicate"].str.upper().isin(_PERSONAL_PREDICATES)
    personal = rf_df[mask]
    result: dict[str, int] = {}
    for pid_col in ("subject_person_id",):
        if pid_col in personal.columns:
            counts = personal[pid_col].value_counts()
            for pid, count in counts.items():
                pid_str = str(pid).strip()
                if pid_str:
                    result[pid_str] = result.get(pid_str, 0) + int(count)
    return result





def extract_intimacy_whatsapp(
    whatsapp_dir: Path | None = None,
    name_matcher=None,
) -> dict[str, dict]:
    ""











    from sbk_config import WHATSAPP_CHATS_DIR, is_own_name

    chats_dir = WHATSAPP_CHATS_DIR
    if whatsapp_dir is not None:

        chats_dir = whatsapp_dir / "chats" if (whatsapp_dir / "chats").exists() else whatsapp_dir

    result: dict[str, dict] = {}
    if not chats_dir.exists():
        return result

    for json_file in sorted(chats_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue


        participants = data.get("participants", [])
        if isinstance(participants, str):
            participants = [p.strip() for p in participants.split("|||")]
        participant_count = data.get("participant_count", len(participants))
        if participant_count > 2:
            continue


        contact_name = data.get("chat_name", json_file.stem)

        for p in participants:
            p_stripped = p.strip()
            if p_stripped and p_stripped.lower() not in ("you",) and not is_own_name(p_stripped):
                contact_name = p_stripped
                break

        if not contact_name:
            continue


        person_id = None
        if name_matcher:
            match = name_matcher.match(contact_name)
            if match.resolved:
                person_id = match.person_id

        if not person_id:
            continue


        messages = data.get("messages", [])
        total = len(messages)
        if total == 0:
            continue

        late_night = sum(
            1 for m in messages if _is_late_night(m.get("timestamp") or m.get("time", ""))
        )
        late_night_pct = late_night / total if total > 0 else 0.0


        informal_markers = 0
        for m in messages:
            text = m.get("text", "")
            if text:
                informal_markers += text.count("!") + text.count("😂") + text.count("❤")
                informal_markers += sum(1 for c in text if ord(c) > 0x1F600)
        informal_score = min(1.0, informal_markers / max(total, 1) * 2.0)

        result[person_id] = {
            "late_night_pct": round(late_night_pct, 4),
            "informal_score": round(informal_score, 4),
        }

    return result


def _is_late_night(time_str: str) -> bool:
    ""
    try:
        if "T" in str(time_str):
            hour = int(str(time_str).split("T")[1][:2])
        elif ":" in str(time_str):
            hour = int(str(time_str).split(":")[0][-2:])
        else:
            return False
        return hour >= 22 or hour < 6
    except (ValueError, IndexError):
        return False





def extract_intimacy_weekend_email(
    emails_dir: Path | None = None,
) -> dict[str, tuple[float, int]]:
    ""







    from sbk_config import EMAILS_DIR, OWN_EMAILS

    if emails_dir is None:
        emails_dir = EMAILS_DIR

    own_lower = {e.lower() for e in OWN_EMAILS}
    all_dfs = []

    for msg_file in sorted(emails_dir.glob("*/messages.parquet")):
        try:
            all_dfs.append(pd.read_parquet(msg_file, columns=["from_addr", "to_addr", "date"]))
        except Exception as e:
            log.warning("Failed to read email parquet %s: %s", msg_file, e)
            continue

    if not all_dfs:
        return {}

    df = pd.concat(all_dfs, ignore_index=True)
    df["from_email"] = df["from_addr"].fillna("").astype(str).apply(_extract_email)
    df["to_email"] = df["to_addr"].fillna("").astype(str).apply(_extract_email)
    df["dt"] = pd.to_datetime(df["date"], errors="coerce")


    from_is_owner = df["from_email"].isin(own_lower)
    to_is_owner = df["to_email"].isin(own_lower)
    df["other"] = np.where(from_is_owner, df["to_email"], np.where(to_is_owner, df["from_email"], ""))


    df = df[(df["other"] != "") & df["other"].str.contains("@", na=False) & df["dt"].notna()]


    df["is_weekend_eve"] = (
        (df["dt"].dt.dayofweek >= 5) | (df["dt"].dt.hour >= 20) | (df["dt"].dt.hour < 7)
    )

    totals = df.groupby("other").size()
    weekends = df[df["is_weekend_eve"]].groupby("other").size()

    return {
        email: (round(int(weekends.get(email, 0)) / int(total), 4), int(total))
        for email, total in totals.items()
        if total >= 3
    }





def extract_intimacy_topic_breadth(rf_df: pd.DataFrame) -> dict[str, int]:
    ""







    if rf_df.empty:
        return {}
    if "subject_person_id" not in rf_df.columns or "predicate" not in rf_df.columns:
        return {}
    grouped = rf_df.groupby("subject_person_id")["predicate"].nunique()
    return {str(pid): int(count) for pid, count in grouped.items() if count > 0}





def extract_quality_email_latency(
    emails_dir: Path | None = None,
) -> dict[str, tuple[float, int]]:
    ""






    from sbk_config import EMAILS_DIR, OWN_EMAILS

    if emails_dir is None:
        emails_dir = EMAILS_DIR

    own_lower = {e.lower() for e in OWN_EMAILS}
    all_dfs = []

    for msg_file in sorted(emails_dir.glob("*/messages.parquet")):
        try:
            cols = ["message_id", "date", "from_addr", "to_addr", "in_reply_to"]
            df = pd.read_parquet(msg_file, columns=cols)
            all_dfs.append(df)
        except Exception as e:
            log.warning("Failed to read email parquet %s: %s", msg_file, e)
            continue

    if not all_dfs:
        return {}

    df = pd.concat(all_dfs, ignore_index=True)
    df["from_email"] = df["from_addr"].fillna("").astype(str).apply(_extract_email)
    df["dt"] = pd.to_datetime(df["date"], errors="coerce")


    valid = df[df["message_id"].notna() & df["dt"].notna()].copy()
    valid["msg_id_str"] = valid["message_id"].astype(str).str.strip()
    msg_lookup = dict(zip(valid["msg_id_str"], zip(valid["from_email"], valid["dt"])))


    latencies: dict[str, list[float]] = {}
    replies = df[df["in_reply_to"].notna() & df["dt"].notna()]

    for row in replies.itertuples():
        reply_to = str(row.in_reply_to).strip()
        if reply_to not in msg_lookup:
            continue

        orig_from, orig_date = msg_lookup[reply_to]
        from_addr = row.from_email
        date = row.dt

        delta_hours = (date - orig_date).total_seconds() / 3600.0
        if delta_hours < 0 or delta_hours > 720:
            continue

        from_is_owner = from_addr in own_lower
        orig_is_owner = orig_from in own_lower

        if from_is_owner and not orig_is_owner:
            latencies.setdefault(orig_from, []).append(delta_hours)
        elif not from_is_owner and orig_is_owner:
            latencies.setdefault(from_addr, []).append(delta_hours)

    return {
        email: (round(float(np.median(lats)), 2), len(lats))
        for email, lats in latencies.items()
        if len(lats) >= 2
    }





def extract_quality_slack_latency(
    slack_dir: Path | None = None,
) -> dict[str, tuple[float, int]]:
    ""







    from sbk_config import OWN_NAMES_NORMALIZED

    if slack_dir is None:
        slack_dir = SLACK_DIR

    slack_file = slack_dir / "interactions-slack.parquet"
    if not slack_file.exists():
        return {}

    try:
        df = pd.read_parquet(slack_file)
    except Exception as e:
        log.warning("Failed to read slack parquet %s: %s", slack_file, e)
        return {}

    dm_df = df[df["message_type"] == "dm"].copy()
    if dm_df.empty:
        return {}

    dm_df["dt"] = pd.to_datetime(dm_df["timestamp"], errors="coerce")
    dm_df = dm_df.dropna(subset=["dt"]).sort_values(["channel_id", "dt"])

    own_names = OWN_NAMES_NORMALIZED

    latencies: dict[str, list[float]] = {}
    prev_row = None
    prev_channel = None

    for row in dm_df.itertuples():
        if prev_row is not None and row.channel_id == prev_channel:
            prev_from = str(prev_row.from_user).lower()
            curr_from = str(row.from_user).lower()

            if prev_from != curr_from:
                delta_h = (row.dt - prev_row.dt).total_seconds() / 3600.0
                if 0 < delta_h < 720:

                    other = curr_from if prev_from in own_names else prev_from
                    if other not in own_names:
                        latencies.setdefault(other, []).append(delta_h)

        prev_row = row
        prev_channel = row.channel_id

    return {
        user: (round(float(np.median(lats)), 2), len(lats))
        for user, lats in latencies.items()
        if len(lats) >= 2
    }





def extract_quality_rhythm_stability(iw_df: pd.DataFrame) -> dict[str, tuple[float, int]]:
    ""









    if iw_df.empty or "to_addr" not in iw_df.columns or "date" not in iw_df.columns:
        return {}

    iw_df = iw_df.copy()
    iw_df["dt"] = pd.to_datetime(iw_df["date"], errors="coerce", utc=True)
    iw_df = iw_df.dropna(subset=["dt"])

    result: dict[str, tuple[float, int]] = {}
    for person, group in iw_df.groupby("to_addr"):
        dates = group["dt"].sort_values()
        if len(dates) < 3:
            continue
        gaps = dates.diff().dt.total_seconds().dropna() / 86400.0
        if len(gaps) < 2:
            continue
        mean_gap = float(gaps.mean())
        std_gap = float(gaps.std())
        if mean_gap > 0:
            cov = std_gap / mean_gap
            result[str(person)] = (round(min(cov, 3.0), 4), len(gaps))

    return result





def extract_structural_centrality(centrality_path: Path | None = None) -> dict[str, dict]:
    ""




    if centrality_path is None:
        centrality_path = GRAPH_DIR / "centrality.json"

    if not centrality_path.exists():
        return {}

    try:
        data = json.loads(centrality_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


    entries = data.get("all", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        entries = list(entries.values()) if isinstance(entries, dict) else []

    result: dict[str, dict] = {}
    for entry in entries:
        if isinstance(entry, dict):
            pid = str(entry.get("person_id", entry.get("id", "")))
            if pid:
                result[pid] = {
                    "pagerank": float(entry.get("pagerank", 0.0)),
                    "betweenness": float(entry.get("betweenness", 0.0)),
                }

    return result





def extract_structural_introductions(rf_df: pd.DataFrame) -> dict[str, int]:
    ""




    if rf_df.empty:
        return {}

    intro_predicates = {"INTRODUCED_TO", "INTRODUCED_BY", "INTRODUCED"}
    mask = rf_df["predicate"].str.upper().isin(intro_predicates)
    intro_df = rf_df[mask]

    result: dict[str, int] = {}
    for pid_col in ("subject_person_id", "object_person_id"):
        if pid_col in intro_df.columns:
            counts = intro_df[pid_col].value_counts()
            for pid, count in counts.items():
                pid_str = str(pid).strip()
                if pid_str:
                    result[pid_str] = result.get(pid_str, 0) + int(count)

    return result





def extract_trust_promises(person_context_dir: Path | None = None) -> dict[str, float]:
    ""






    if person_context_dir is None:
        person_context_dir = PERSON_CONTEXT_DIR

    if not person_context_dir.exists():
        return {}

    result: dict[str, float] = {}
    for json_file in sorted(person_context_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue

        pid = data.get("person_id", json_file.stem)
        promises = data.get("promises", [])
        if not isinstance(promises, list) or not promises:
            continue

        done = sum(
            1 for p in promises if isinstance(p, dict) and p.get("status") in ("done", "completed")
        )
        pending = sum(1 for p in promises if isinstance(p, dict) and p.get("status") == "pending")
        total = done + pending
        if total > 0:
            result[str(pid)] = round(done / total, 4)

    return result





def extract_negative_signals(
    rf_df: pd.DataFrame,
    iw_df: pd.DataFrame | None = None,
    personio_path: Path | None = None,
    personio_enrichment: dict | None = None,
) -> dict[str, dict]:
    ""














    result: dict[str, dict] = {}









    if personio_path is None:
        personio_path = PERSONIO_DIR / "processed" / "employees.parquet"
    if personio_path.exists():
        try:
            pe_df = pd.read_parquet(personio_path, columns=["email", "status"])
            for _, row in pe_df.iterrows():
                if pd.notna(row.get("status")) and str(row["status"]).lower() == "terminated":
                    email = str(row.get("email", "")).lower().strip()
                    if email:
                        result.setdefault(email, {})["is_ex_employee"] = True
        except Exception as e:
            log.warning("Failed to read personio data: %s", e)




    if iw_df is not None and not iw_df.empty:
        from sbk_config import OWN_EMAILS

        own_lower = {e.lower() for e in OWN_EMAILS}

        _substantive_types = {"direct_1to1", "reply_substantive", "small_group_2to5"}
        if "interaction_type" in iw_df.columns:
            email_df = iw_df[iw_df["interaction_type"].isin(_substantive_types)]
        else:
            email_df = iw_df

        for person, group in email_df.groupby("to_addr"):
            pid_str = str(person)
            bare_from = group["from_addr"].apply(_extract_email)
            owner_mask = bare_from.isin(own_lower)
            sent = int(owner_mask.sum())
            received = int((~owner_mask).sum())
            total = sent + received
            if total >= 5:
                majority = max(sent, received)
                minority = min(sent, received)
                if minority == 0:
                    ratio = 1.0
                else:
                    ratio = 1.0 - (minority / majority)
                if ratio > 0.5:
                    result.setdefault(pid_str, {})["one_sided_ratio"] = round(ratio, 4)

                result.setdefault(pid_str, {})["has_ever_replied"] = received > 0


    from sbk_config import DATA_ROOT as _DATA_ROOT

    _decisions_path = _DATA_ROOT / "l3" / "nlp" / "decisions.parquet"
    if _decisions_path.exists():
        try:
            _dec_df = pd.read_parquet(_decisions_path, columns=["speaker", "date"])

            for speaker, count in _dec_df["speaker"].value_counts().items():
                speaker_str = str(speaker).strip()
                if speaker_str and speaker_str.lower() not in ("unknown", ""):

                    for pid_key, pid_data in result.items():
                        if speaker_str.lower() in pid_key.lower():
                            pid_data["decision_count"] = pid_data.get("decision_count", 0) + int(
                                count
                            )
                            break
        except Exception as e:
            log.warning("Failed to read decision facts: %s", e)

    _facts_path = _DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"
    if _facts_path.exists():
        try:
            _facts_df = pd.read_parquet(_facts_path, columns=["subject_person_id", "predicate"])

            _family_preds = {"FAMILY_OF", "PARENT_OF", "SIBLING_OF", "SPOUSE_OF", "CHILD_OF"}
            _hobby_preds = {"INTERESTED_IN", "PREFERENCE", "HOBBY"}
            _health_preds = {"CONDITION", "STRUGGLING_WITH"}

            for pid, group in _facts_df.groupby("subject_person_id"):
                pid_str = str(pid)
                if pid_str not in result:
                    continue
                preds = group["predicate"].value_counts()
                family_count = sum(preds.get(p, 0) for p in _family_preds)
                hobby_count = sum(preds.get(p, 0) for p in _hobby_preds)
                health_count = sum(preds.get(p, 0) for p in _health_preds)
                if family_count > 0:
                    result[pid_str]["family_fact_count"] = int(family_count)
                if hobby_count > 0:
                    result[pid_str]["hobby_fact_count"] = int(hobby_count)
                if health_count > 0:
                    result[pid_str]["health_fact_count"] = int(health_count)
        except Exception as e:
            log.warning("Failed to read relationship/deep facts: %s", e)


    from rq_negative_severity import aggregate_severity, classify_all_events, events_to_dicts

    for pid, neg_data in result.items():

        p_enrich = None
        if personio_enrichment:
            p_enrich = personio_enrichment.get(pid)

        events = classify_all_events(
            person_id=pid,
            rejection_count=neg_data.get("rejection_count", 0),
            is_ex_employee=neg_data.get("is_ex_employee", False),
            personio_enrichment=p_enrich,
            one_sided_ratio=neg_data.get("one_sided_ratio", 0.0),
            ghosting_score=neg_data.get("ghosting_score", 0.0),
            has_ever_replied=neg_data.get("has_ever_replied", True),
        )
        severity, penalty = aggregate_severity(events)
        neg_data["severity_level"] = severity
        neg_data["severity_penalty"] = penalty
        neg_data["severity_events"] = events_to_dicts(events)

    return result





def extract_all_signals(
    name_matcher=None,
    resolver=None,
    rf_path: Path | None = None,
    iw_path: Path | None = None,
) -> pd.DataFrame:
    ""












    if rf_path is None:
        rf_path = NLP_DIR / "relationship-facts.parquet"
    if iw_path is None:
        iw_path = RQ_DIR / "interaction-weights.parquet"

    rf_df = pd.read_parquet(rf_path) if rf_path.exists() else pd.DataFrame()




    _iw_cols = ["date", "to_addr", "from_addr", "weight", "interaction_type"]
    iw_df = pd.read_parquet(iw_path, columns=_iw_cols) if iw_path.exists() else pd.DataFrame()

    log.info(
        "Extracting signals from %d relationship facts, %d interactions", len(rf_df), len(iw_df)
    )


    log.info("[1/13] Extracting family flags...")
    family = extract_intimacy_family(rf_df)
    log.info("[1/13] Family: %d persons", len(family))

    log.info("[2/13] Extracting personal topics...")
    personal = extract_intimacy_personal_topics(rf_df)
    log.info("[2/13] Personal topics: %d persons", len(personal))

    log.info("[3/13] Extracting WhatsApp signals...")
    whatsapp = extract_intimacy_whatsapp(name_matcher=name_matcher)
    log.info("[3/13] WhatsApp: %d persons", len(whatsapp))

    log.info("[4/13] Extracting weekend email ratio...")
    weekend = extract_intimacy_weekend_email()
    log.info("[4/13] Weekend email: %d persons", len(weekend))

    log.info("[5/13] Extracting topic breadth...")
    breadth = extract_intimacy_topic_breadth(rf_df)
    log.info("[5/13] Topic breadth: %d persons", len(breadth))

    log.info("[6/13] Extracting email response latency...")
    email_lat = extract_quality_email_latency()
    log.info("[6/13] Email latency: %d persons", len(email_lat))

    log.info("[7/13] Extracting Slack response latency...")
    slack_lat = extract_quality_slack_latency()
    log.info("[7/13] Slack latency: %d persons", len(slack_lat))

    log.info("[8/13] Extracting rhythm stability...")
    rhythm = extract_quality_rhythm_stability(iw_df)
    log.info("[8/13] Rhythm: %d persons", len(rhythm))

    log.info("[9/13] Extracting centrality...")
    centrality = extract_structural_centrality()
    log.info("[9/13] Centrality: %d persons", len(centrality))

    log.info("[10/13] Extracting introductions...")
    intros = extract_structural_introductions(rf_df)
    log.info("[10/13] Introductions: %d persons", len(intros))

    log.info("[11/13] Extracting promise completion...")
    promises = extract_trust_promises()
    log.info("[11/13] Promises: %d persons", len(promises))

    log.info("[12/13] Extracting negative signals...")
    negatives = extract_negative_signals(rf_df, iw_df)
    log.info("[12/13] Negative signals: %d persons", len(negatives))


    log.info("[13/13] Extracting content quality signals...")
    from rq_content_quality import extract_content_quality_signals

    content_quality = extract_content_quality_signals(name_matcher=name_matcher, resolver=resolver)
    log.info("[13/13] Content quality: %d persons", len(content_quality))


    freq: dict[str, float] = {}
    if not iw_df.empty:
        now = pd.Timestamp.now(tz="UTC")
        iw_copy = iw_df.copy()
        iw_copy["dt"] = pd.to_datetime(iw_copy["date"], errors="coerce", utc=True)
        iw_copy["days_ago"] = (now - iw_copy["dt"]).dt.total_seconds() / 86400.0
        iw_copy["days_ago"] = iw_copy["days_ago"].clip(lower=0).fillna(365)
        iw_copy["recency_factor"] = np.power(0.5, iw_copy["days_ago"] / 180.0)
        iw_copy["recency_weight"] = iw_copy["weight"] * iw_copy["recency_factor"]
        person_rw = iw_copy.groupby("to_addr")["recency_weight"].sum()
        max_rw = person_rw.max() if len(person_rw) > 0 else 1.0
        for pid, rw in person_rw.items():
            freq[str(pid)] = round(float(rw / max_rw) if max_rw > 0 else 0.0, 4)


    last_interaction_days: dict[str, float] = {}
    if not iw_df.empty:
        _now = pd.Timestamp.now(tz="UTC")
        _iw_dt = iw_df.copy()
        _iw_dt["dt"] = pd.to_datetime(_iw_dt["date"], errors="coerce", utc=True)
        _iw_dt = _iw_dt.dropna(subset=["dt"])
        if not _iw_dt.empty:
            last_dates = _iw_dt.groupby("to_addr")["dt"].max()
            for pid, last_dt in last_dates.items():
                days = (_now - last_dt).total_seconds() / 86400.0
                last_interaction_days[str(pid)] = round(max(0.0, days), 1)


    attio_strength: dict[str, float] = {}
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if cm_path.exists():
        try:
            cm = pd.read_parquet(cm_path, columns=["person_id", "attio_connection_strength_num"])
            for _, row in cm.iterrows():
                pid = str(row.get("person_id", ""))
                strength = row.get("attio_connection_strength_num")
                if pid and pd.notna(strength):
                    attio_strength[pid] = round(float(strength), 4)
        except Exception as e:
            log.warning("Failed to read attio connection data: %s", e)



    ai_count: dict[str, int] = {}
    ai_path = NLP_DIR / "action-items.parquet"
    if ai_path.exists():
        try:
            ai_df = pd.read_parquet(ai_path, columns=["assignee"])
            if "assignee" in ai_df.columns and name_matcher is not None:
                name_counts: dict[str, int] = {}
                for assignee_name, count in ai_df["assignee"].dropna().value_counts().items():
                    name_str = str(assignee_name).strip()
                    if name_str and name_str.lower() != "none":
                        name_counts[name_str] = int(count)

                log.info(
                    "Matching %d unique assignee names (exact+nickname only)", len(name_counts)
                )
                for name_str, count in name_counts.items():
                    from rq_name_matching import _normalize

                    norm = _normalize(name_str)
                    if not norm:
                        continue

                    if norm in name_matcher._exact_index:
                        pid, _ = name_matcher._exact_index[norm]
                        ai_count[pid] = ai_count.get(pid, 0) + count

                    elif norm in name_matcher._nickname_index:
                        pid, _ = name_matcher._nickname_index[norm]
                        ai_count[pid] = ai_count.get(pid, 0) + count
                log.info("Resolved %d persons from action items", len(ai_count))
        except Exception:
            log.warning("Failed to load action items from %s", ai_path, exc_info=True)


    commit_count: dict[str, int] = {}
    if not rf_df.empty and "predicate" in rf_df.columns:
        commit_mask = rf_df["predicate"].str.upper() == "COMMITMENT"
        if commit_mask.any() and "subject_person_id" in rf_df.columns:
            counts = rf_df[commit_mask]["subject_person_id"].value_counts()
            commit_count = {str(pid): int(c) for pid, c in counts.items()}


    def _unwrap_tuples(d: dict) -> dict[str, float]:
        ""
        out: dict[str, float] = {}
        for k, v in d.items():
            out[k] = v[0] if isinstance(v, tuple) else v
        return out


    if resolver is not None:
        pre_count = sum(len(d) for d in [weekend, email_lat, slack_lat, rhythm])
        weekend = _consolidate_weighted_ratio(weekend, resolver)
        email_lat = _consolidate_weighted_harmonic(email_lat, resolver)
        slack_lat = _consolidate_weighted_harmonic(slack_lat, resolver)
        rhythm = _consolidate_weighted_avg(rhythm, resolver)
        negatives = _consolidate_negatives(negatives, resolver)
        freq = _consolidate_simple(freq, resolver, merge_fn=max)
        post_count = sum(len(d) for d in [weekend, email_lat, slack_lat, rhythm])
        log.info(
            "Consolidation: %d raw keys → %d resolved (%.0f%% reduction)",
            pre_count,
            post_count,
            (1 - post_count / pre_count) * 100 if pre_count > 0 else 0,
        )
    else:

        weekend = _unwrap_tuples(weekend)
        email_lat = _unwrap_tuples(email_lat)
        slack_lat = _unwrap_tuples(slack_lat)
        rhythm = _unwrap_tuples(rhythm)


    all_pids: set[str] = set()
    for d in [
        family,
        personal,
        whatsapp,
        breadth,
        centrality,
        intros,
        promises,
        negatives,
        freq,
        attio_strength,
        ai_count,
        commit_count,
        content_quality,
    ]:
        all_pids.update(d.keys())
    for d in [weekend, email_lat, slack_lat, rhythm]:
        all_pids.update(d.keys())

    log.info("Combining signals for %d unique persons", len(all_pids))


    now_iso = datetime.utcnow().isoformat()
    rows = []
    for pid in sorted(all_pids):
        cent = centrality.get(pid, {})
        wa = whatsapp.get(pid, {})
        neg = negatives.get(pid, {})
        cq = content_quality.get(pid, {})

        row = {
            "person_id": pid,

            "is_family": family.get(pid, False),
            "personal_topic_count": personal.get(pid, 0),
            "whatsapp_late_night_pct": wa.get("late_night_pct", 0.0),
            "whatsapp_informal_score": wa.get("informal_score", 0.0),
            "weekend_evening_email_ratio": weekend.get(pid, 0.0),
            "topic_breadth": breadth.get(pid, 0),

            "email_response_latency_hours": email_lat.get(pid, 48.0),
            "slack_response_latency_hours": slack_lat.get(pid, 24.0),
            "contact_rhythm_cov": rhythm.get(pid, 1.0),
            "recency_weighted_frequency": freq.get(pid, 0.0),

            "pagerank": cent.get("pagerank", 0.0),
            "betweenness": cent.get("betweenness", 0.0),
            "introductions_count": intros.get(pid, 0),
            "multiplexity_bidir": 0,

            "promise_completion_ratio": promises.get(pid, 0.0),
            "action_items_count": ai_count.get(pid, 0),
            "attio_connection_strength": attio_strength.get(pid, 0.0),
            "commitment_facts_count": commit_count.get(pid, 0),

            "rejection_count": neg.get("rejection_count", 0),
            "ghosting_score": neg.get("ghosting_score", 0.0),
            "one_sided_ratio": neg.get("one_sided_ratio", 0.0),
            "is_ex_employee": neg.get("is_ex_employee", False),

            "severity_level": neg.get("severity_level", 0),
            "severity_penalty": neg.get("severity_penalty", 0.0),

            "formality_score": cq.get("formality_score", 0.5),
            "formality_trend": cq.get("formality_trend", 0.0),
            "self_disclosure_count": cq.get("self_disclosure_count", 0),
            "emotional_word_density": cq.get("emotional_word_density", 0.0),
            "inclusive_pronoun_ratio": cq.get("inclusive_pronoun_ratio", 0.0),
            "humor_markers_density": cq.get("humor_markers_density", 0.0),
            "linguistic_style_matching": cq.get("linguistic_style_matching", 0.0),
            "topic_coherence": cq.get("topic_coherence", 0.0),
            "turn_taking_balance": cq.get("turn_taking_balance", 0.5),
            "meeting_warmth_score": cq.get("meeting_warmth_score", 0.0),
            "laughter_per_minute": cq.get("laughter_per_minute", 0.0),
            "personal_topic_in_meeting": cq.get("personal_topic_in_meeting", 0.0),

            "last_interaction_days_ago": last_interaction_days.get(pid, 365.0),

            "extraction_ts": now_iso,
        }


        signal_fields = [
            "is_family",
            "personal_topic_count",
            "whatsapp_late_night_pct",
            "whatsapp_informal_score",
            "weekend_evening_email_ratio",
            "topic_breadth",
            "email_response_latency_hours",
            "slack_response_latency_hours",
            "contact_rhythm_cov",
            "recency_weighted_frequency",
            "pagerank",
            "betweenness",
            "introductions_count",
            "multiplexity_bidir",
            "promise_completion_ratio",
            "action_items_count",
            "attio_connection_strength",
            "commitment_facts_count",
            "rejection_count",
            "ghosting_score",
            "one_sided_ratio",
            "is_ex_employee",

            "formality_score",
            "formality_trend",
            "self_disclosure_count",
            "emotional_word_density",
            "inclusive_pronoun_ratio",
            "humor_markers_density",
            "linguistic_style_matching",
            "topic_coherence",
            "turn_taking_balance",
            "meeting_warmth_score",
            "laughter_per_minute",
            "personal_topic_in_meeting",
        ]
        defaults = {
            "is_family": False,
            "personal_topic_count": 0,
            "whatsapp_late_night_pct": 0.0,
            "whatsapp_informal_score": 0.0,
            "weekend_evening_email_ratio": 0.0,
            "topic_breadth": 0,
            "email_response_latency_hours": 48.0,
            "slack_response_latency_hours": 24.0,
            "contact_rhythm_cov": 1.0,
            "recency_weighted_frequency": 0.0,
            "pagerank": 0.0,
            "betweenness": 0.0,
            "introductions_count": 0,
            "multiplexity_bidir": 0,
            "promise_completion_ratio": 0.0,
            "action_items_count": 0,
            "attio_connection_strength": 0.0,
            "commitment_facts_count": 0,
            "rejection_count": 0,
            "ghosting_score": 0.0,
            "one_sided_ratio": 0.0,
            "is_ex_employee": False,

            "formality_score": 0.5,
            "formality_trend": 0.0,
            "self_disclosure_count": 0,
            "emotional_word_density": 0.0,
            "inclusive_pronoun_ratio": 0.0,
            "humor_markers_density": 0.0,
            "linguistic_style_matching": 0.0,
            "topic_coherence": 0.0,
            "turn_taking_balance": 0.5,
            "meeting_warmth_score": 0.0,
            "laughter_per_minute": 0.0,
            "personal_topic_in_meeting": 0.0,
        }


        signal_values = []
        for f in signal_fields:
            val = row.get(f)
            default = defaults.get(f)
            if val != default and val is not None:


                if isinstance(val, int | float) and val > 0:
                    signal_values.append(min(1.0, abs(float(val))))

        signal_values.sort(reverse=True)
        top_n = signal_values[:5] if signal_values else []
        row["signal_depth"] = round(sum(top_n) / max(len(top_n), 1), 4) if top_n else 0.0

        non_default = sum(1 for f in signal_fields if row.get(f) != defaults.get(f))
        row["signal_coverage"] = round(non_default / len(signal_fields), 4)

        rows.append(row)

    return pd.DataFrame(rows)
