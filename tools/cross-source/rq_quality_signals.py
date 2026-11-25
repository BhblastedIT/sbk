""











from __future__ import annotations

import json
import logging
import math
from pathlib import Path

log = logging.getLogger("rq.quality")




class QualityProfile:
    ""





    __slots__ = (
        "person_id",
        "relationship_depth",
        "personal_knowledge",
        "content_richness",
        "communication_style",
        "engagement_quality",
        "structural_importance",
        "overall_multiplier",
    )

    def __init__(self, person_id: str):
        self.person_id = person_id
        self.relationship_depth = 0.0
        self.personal_knowledge = 0.0
        self.content_richness = 0.0
        self.communication_style = 0.0
        self.engagement_quality = 0.5
        self.structural_importance = 0.0
        self.overall_multiplier = 1.0

    def compute_multiplier(self) -> float:
        ""













        identity = (
            0.45 * self.relationship_depth
            + 0.15 * self.personal_knowledge
            + 0.05 * self.engagement_quality
        )


        substance = (
            0.15 * self.content_richness
            + 0.08 * self.communication_style
            + 0.02
            * self.structural_importance
        )



        raw = identity + substance




        self.overall_multiplier = 0.1 + raw * 5.4
        return self.overall_multiplier

    def to_dict(self) -> dict:
        return {
            "person_id": self.person_id,
            "relationship_depth": round(self.relationship_depth, 3),
            "personal_knowledge": round(self.personal_knowledge, 3),
            "content_richness": round(self.content_richness, 3),
            "communication_style": round(self.communication_style, 3),
            "engagement_quality": round(self.engagement_quality, 3),
            "structural_importance": round(self.structural_importance, 3),
            "overall_multiplier": round(self.overall_multiplier, 3),
        }




_QUALITY_CACHE: dict[str, QualityProfile] | None = None


def load_quality_profiles(force_reload: bool = False) -> dict[str, QualityProfile]:
    ""








    global _QUALITY_CACHE
    if _QUALITY_CACHE is not None and not force_reload:
        return _QUALITY_CACHE

    profiles: dict[str, QualityProfile] = {}


    _load_from_signals(profiles)


    _load_from_knowledge(profiles)


    _load_from_events(profiles)


    _load_personal_channels(profiles)


    _apply_ex_employee_penalty(profiles)


    _apply_recency_weighting(profiles)


    _load_from_transcript_classifications(profiles)


    for p in profiles.values():
        p.compute_multiplier()

    _QUALITY_CACHE = profiles
    log.info(
        "Loaded quality profiles for %d persons (mean multiplier: %.2f)",
        len(profiles),
        sum(p.overall_multiplier for p in profiles.values()) / max(1, len(profiles)),
    )
    return profiles


def get_quality_multiplier(person_id: str) -> float:
    ""
    profiles = load_quality_profiles()
    profile = profiles.get(person_id)
    if profile:
        return profile.overall_multiplier
    return 0.5





def _load_from_signals(profiles: dict[str, QualityProfile]) -> None:
    ""
    try:
        import pandas as pd

        from sbk_config import RQ_DIR

        signals_path = RQ_DIR / "signals.parquet"
        if not signals_path.exists():
            log.warning("signals.parquet not found")
            return

        df = pd.read_parquet(signals_path)
        pid_col = "person" if "person" in df.columns else "person_id"

        for _, row in df.iterrows():
            pid = str(row.get(pid_col, ""))
            if not pid:
                continue

            if pid not in profiles:
                profiles[pid] = QualityProfile(pid)
            p = profiles[pid]


            personal_topics = int(row.get("personal_topic_count", 0))
            topic_breadth = int(row.get("topic_breadth", 0))
            self_disc = int(row.get("self_disclosure_count", 0))
            meeting_personal = float(row.get("personal_topic_in_meeting", 0))

            p.content_richness = min(
                1.0,
                (
                    0.35 * min(1.0, personal_topics / 10)
                    + 0.25 * min(1.0, topic_breadth / 20)
                    + 0.20 * min(1.0, self_disc / 5)
                    + 0.20 * min(1.0, meeting_personal / 0.2)
                ),
            )


            formality_trend = float(row.get("formality_trend", 0))
            lsm = float(row.get("linguistic_style_matching", 0))
            inclusive_pron = float(row.get("inclusive_pronoun_ratio", 0))


            formality_signal = min(1.0, max(0, -formality_trend * 3))
            p.communication_style = min(
                1.0,
                (
                    0.30 * formality_signal
                    + 0.35 * min(1.0, lsm / 0.7)
                    + 0.35 * min(1.0, inclusive_pron / 0.4)
                ),
            )





            pagerank = float(row.get("pagerank", 0))
            intros = int(row.get("introductions_count", 0))
            actions = int(row.get("action_items_count", 0))




            p.structural_importance = min(
                0.50, (0.50 * min(1.0, pagerank / 0.005) + 0.50 * min(1.0, intros / 20))
            )








        log.info("Loaded signals for %d persons from signals.parquet", len(df))

    except Exception as exc:
        log.warning("Failed to load signals.parquet: %s", exc)





def _load_from_knowledge(profiles: dict[str, QualityProfile]) -> None:
    ""











    try:
        from rq_kl_quality import compute_kl_depth

        from sbk_config import KNOWLEDGE_DIR


        try:
            from rq_entity_bridge import load_bridge

            bridge = load_bridge()
            reverse_bridge: dict[str, str] = {}
            for k, v in bridge.items():
                if isinstance(v, str) and k.startswith("person_") and v.startswith("p_"):
                    reverse_bridge[k] = v
        except Exception:
            bridge = {}
            reverse_bridge = {}


        golden_types: dict[str, dict] = {}
        try:
            golden_path = Path("~/.sbk-data/rq/golden-ranking.json").expanduser()
            if golden_path.exists():
                with open(golden_path, encoding="utf-8") as f:
                    gdata = json.load(f)
                for o in gdata.get("type_overrides", {}).get("overrides", []):
                    name = o.get("name", "").strip().lower()
                    if name:
                        golden_types[name] = o
        except Exception:
            pass






        name_to_pid: dict[str, str] = {}
        try:
            import pandas as pd

            from sbk_config import ENRICHED_DIR

            cm_path = ENRICHED_DIR / "contacts-merged.parquet"
            if cm_path.exists():
                cm = pd.read_parquet(cm_path, columns=["person_id", "name"])
                for _, row in cm.iterrows():
                    n = str(row.get("name", "")).strip().lower()
                    pid = str(row.get("person_id", ""))
                    if n and pid:
                        name_to_pid[n] = pid
        except Exception:
            pass

        person_dir = KNOWLEDGE_DIR / "entities" / "person"
        if not person_dir.exists():
            return

        import glob

        files = glob.glob(str(person_dir / "*.json"))
        enriched = 0

        for fpath in files:
            try:
                with open(fpath, encoding="utf-8") as f:
                    ent = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            entity_id = ent.get("entity_id", "")
            facts = ent.get("facts", [])
            if not facts:
                continue

            pid = reverse_bridge.get(entity_id, entity_id)
            if pid not in profiles:
                profiles[pid] = QualityProfile(pid)
            p = profiles[pid]





            personal_fact_count = 0
            has_birthday = False
            categories: set[str] = set()

            for fact in facts:
                attr = fact.get("attribute", "")


                cat = attr.split(".")[0] if "." in attr else attr
                categories.add(cat)

                if attr.startswith("personal."):
                    personal_fact_count += 1
                elif attr == "relationship.birthday":
                    has_birthday = True


            cat_breadth = len(categories)
            fact_count = len(facts)

            breadth_signal = min(1.0, max(0.0, (cat_breadth - 2) / 10))

            count_signal = min(1.0, math.log1p(fact_count) / math.log1p(500))
            knowledge_depth = 0.6 * breadth_signal + 0.4 * count_signal








            kl_result = compute_kl_depth(facts, pid)
            depth = kl_result["depth"]

            if depth > p.relationship_depth:
                p.relationship_depth = depth


            pk = 0.0
            if has_birthday:
                pk += 0.3
            pk += min(0.7, personal_fact_count * 0.05)
            if pk > p.personal_knowledge:
                p.personal_knowledge = min(1.0, pk)


            if knowledge_depth > p.content_richness:
                p.content_richness = max(p.content_richness, knowledge_depth * 0.5)

            if depth > 0 or pk > 0 or knowledge_depth > 0.2:
                enriched += 1






        golden_injected = 0


        GOLDEN_BASE_DEPTH = {
            "family": 0.95,
            "close_partner": 0.65,
            "personal_friend": 0.55,
            "advisor": 0.35,
            "investor": 0.30,
            "business_partner": 0.30,
            "colleague": 0.15,
            "vendor": 0.10,
            "acquaintance": 0.05,
        }


        GOLDEN_TIER_MULTIPLIER = {
            "inner_circle": 1.10,
            "sympathy_group": 0.85,
            "active_network": 0.55,
        }


        NON_GOLDEN_TYPE_FLOOR = {
            "family": 0.50,
            "close_partner": 0.25,
            "personal_friend": 0.20,
            "investor": 0.08,
            "advisor": 0.08,
            "business_partner": 0.06,
            "colleague": 0.03,
            "vendor": 0.02,
            "acquaintance": 0.01,
        }





        name_to_tier: dict[str, str] = {}
        golden_tiers: dict[str, str] = {}
        for tier_name, tier_data in gdata.get("tiers", {}).items():
            for member in tier_data.get("members", []):
                tname = member.get("name", "").strip().lower()
                name_to_tier[tname] = tier_name
                tpid = name_to_pid.get(tname) or (
                    bridge.get(tname) if isinstance(bridge.get(tname), str) else None
                )
                if tpid:
                    golden_tiers[tpid] = tier_name






        pid_candidates: dict[
            str, list[tuple[str, str, float, bool]]
        ] = {}

        for name_lower, override in golden_types.items():
            gtype = override.get("type", "")
            base = GOLDEN_BASE_DEPTH.get(gtype, 0.05)


            direct_pid = name_to_pid.get(name_lower)
            pid = direct_pid
            if not pid:

                pid = bridge.get(name_lower) if isinstance(bridge.get(name_lower), str) else None
            if not pid:
                continue





            tier = name_to_tier.get(name_lower)
            if tier:
                mult = GOLDEN_TIER_MULTIPLIER.get(tier, 0.40)
            else:
                mult = 0.30

            depth_boost = min(1.0, base * mult)


            if not tier:
                floor = NON_GOLDEN_TYPE_FLOOR.get(gtype, 0.01)
                depth_boost = max(depth_boost, floor)

            is_direct = direct_pid == pid
            if pid not in pid_candidates:
                pid_candidates[pid] = []
            pid_candidates[pid].append((name_lower, gtype, depth_boost, is_direct))






        for pid, candidates in pid_candidates.items():

            direct = [c for c in candidates if c[3]]
            force_override = False
            if direct:

                _name, gtype, depth_boost, _ = direct[0]

                force_override = True
            else:

                candidates.sort(key=lambda c: c[2], reverse=True)
                _name, gtype, depth_boost, _ = candidates[0]

            if pid not in profiles:
                profiles[pid] = QualityProfile(pid)
            prof = profiles[pid]

            if force_override:


                if prof.relationship_depth != depth_boost:
                    prof.relationship_depth = depth_boost
                    golden_injected += 1
            else:

                if depth_boost > prof.relationship_depth:
                    prof.relationship_depth = depth_boost
                    golden_injected += 1


            if gtype == "family" and prof.personal_knowledge < 0.5:
                prof.personal_knowledge = 0.5

        log.info(
            "Enriched %d persons from Knowledge Layer (%d files), "
            "%d golden type injections (KL deep facts analyzer active)",
            enriched,
            len(files),
            golden_injected,
        )

    except Exception as exc:
        log.warning("Failed to load Knowledge Layer: %s", exc)





def _load_from_events(profiles: dict[str, QualityProfile]) -> None:
    ""









    try:
        import sqlite3

        from rq_event_store import EventStore

        store = EventStore()
        conn = sqlite3.connect(str(store.db_path))


        cur = conn.execute("""
            SELECT person_id, event_type, COUNT(*) as cnt
            FROM events
            GROUP BY person_id, event_type
        """)

        person_events: dict[str, dict[str, int]] = {}
        for pid, etype, cnt in cur.fetchall():
            if pid not in person_events:
                person_events[pid] = {}
            person_events[pid][etype] = cnt


        ACTIVE_TYPES = {
            "email_reply_sent",
            "email_1to1_sent",
            "call_1on1",
            "meeting_1on1",
            "slack_dm",
            "whatsapp_dm",
        }



        INBOUND_TYPES = {
            "email_reply_received",
            "email_1to1_received",
        }


        PASSIVE_TYPES = {
            "whatsapp_small_group",
            "email_cc",
            "email_small_group",
            "meeting_group_large",
            "slack_channel_msg",
            "meeting_group_small",
            "call_group",
            "slack_mention",
            "slack_thread_reply",
        }


        NLP_TYPES = {
            "commitment_made",
            "commitment_fulfilled",
            "introduction_made",
            "introduction_received",
        }

        for pid, events in person_events.items():
            if pid not in profiles:
                profiles[pid] = QualityProfile(pid)
            p = profiles[pid]

            total = sum(events.values())
            if total == 0:
                continue

            active = sum(events.get(t, 0) for t in ACTIVE_TYPES)
            inbound = sum(events.get(t, 0) for t in INBOUND_TYPES)
            passive = sum(events.get(t, 0) for t in PASSIVE_TYPES)



            meaningful_total = active + inbound + passive
            if meaningful_total > 0:
                engagement = (active + 0.15 * inbound) / meaningful_total
            else:
                engagement = 0.0



            one_on_one = sum(
                events.get(t, 0)
                for t in [
                    "meeting_1on1",
                    "call_1on1",
                    "whatsapp_dm",
                    "email_1to1_sent",
                ]
            )
            one_on_one_ratio = one_on_one / max(1, total)


            eq = 0.6 * engagement + 0.4 * min(1.0, one_on_one_ratio * 3)


            p.engagement_quality = eq

        conn.close()
        log.info("Analyzed participation for %d persons", len(person_events))

    except Exception as exc:
        log.warning("Failed to analyze event participation: %s", exc)





def _load_personal_channels(profiles: dict[str, QualityProfile]) -> None:
    ""





    try:
        import pandas as pd

        from sbk_config import ENRICHED_DIR

        cm_path = ENRICHED_DIR / "contacts-merged.parquet"
        if not cm_path.exists():
            return

        cols = [
            "person_id",
            "has_whatsapp",
            "has_plaud",
            "has_iphone",
            "has_slack",
            "has_docusign",
            "has_gdrive",
        ]
        available_cols = pd.read_parquet(cm_path, columns=["person_id"]).columns
        read_cols = [c for c in cols if c in pd.read_parquet(cm_path).columns]
        cm = pd.read_parquet(cm_path, columns=read_cols)

        for _, row in cm.iterrows():
            pid = str(row.get("person_id", ""))
            if pid not in profiles:
                continue

            p = profiles[pid]


            personal = 0.0
            if row.get("has_whatsapp", False):
                personal += 0.40
            if row.get("has_plaud", False):
                personal += 0.35
            if row.get("has_iphone", False):
                personal += 0.25


            p.engagement_quality = p.engagement_quality * 0.7 + personal * 0.3

        log.info("Loaded personal channel scores from contacts-merged")

    except Exception as exc:
        log.warning("Failed to load personal channels: %s", exc)





def _apply_ex_employee_penalty(profiles: dict[str, QualityProfile]) -> None:
    ""










    try:
        import pandas as pd

        from sbk_config import ENRICHED_DIR

        cm_path = ENRICHED_DIR / "contacts-merged.parquet"
        if not cm_path.exists():
            return

        cols = ["person_id", "personio_status", "last_contact"]
        available = pd.read_parquet(cm_path, columns=cols)

        now = pd.Timestamp.now(tz="UTC")

        import math


        event_store = None
        try:
            from rq_event_store import EventStore

            event_store = EventStore()
        except Exception:
            log.debug("Could not load EventStore for ex-employee activity check")

        active_override_count = 0

        for _, row in available.iterrows():
            pid = str(row.get("person_id", ""))
            if pid not in profiles:
                continue

            p = profiles[pid]
            status = str(row.get("personio_status", "")).lower()
            last_contact = pd.to_datetime(row.get("last_contact"), errors="coerce", utc=True)
            if pd.notna(last_contact):
                days_since = (now - last_contact).days
            else:
                days_since = 999





            recency_half_life = 120.0
            recency_factor = math.exp(-math.log(2) / recency_half_life * max(0, days_since))

            p.engagement_quality = p.engagement_quality * 0.7 + recency_factor * 0.3


            if status == "terminated":




                recent_events = 0
                if event_store is not None:
                    try:
                        recent_events = event_store.count_events(pid, days=180)
                    except Exception:
                        pass

                if recent_events > 0:



                    ex_half_life = 90.0
                    ex_factor = math.exp(-math.log(2) / ex_half_life * max(0, days_since))
                    p.relationship_depth *= 0.50 + 0.50 * ex_factor
                    p.content_richness *= 0.50 + 0.50 * ex_factor
                    p.personal_knowledge *= 0.60 + 0.40 * ex_factor
                    p.engagement_quality *= 0.40 + 0.60 * ex_factor
                    active_override_count += 1
                    log.debug(
                        "Ex-employee %s has %d recent events — gentle penalty "
                        "(depth=%.2f, richness=%.2f)",
                        pid,
                        recent_events,
                        p.relationship_depth,
                        p.content_richness,
                    )
                else:


                    ex_half_life = 45.0
                    ex_factor = math.exp(-math.log(2) / ex_half_life * max(0, days_since))
                    p.relationship_depth *= 0.15 + 0.85 * ex_factor
                    p.content_richness *= 0.15 + 0.85 * ex_factor
                    p.personal_knowledge *= 0.20 + 0.80 * ex_factor
                    p.engagement_quality *= 0.10 + 0.90 * ex_factor

        log.info(
            "Applied gradual recency/ex-employee decay from contacts-merged (%d active overrides)",
            active_override_count,
        )

    except Exception as exc:
        log.warning("Failed to apply ex-employee penalty: %s", exc)





def _apply_recency_weighting(profiles: dict[str, QualityProfile]) -> None:
    ""






    try:
        import math

        import pandas as pd

        from sbk_config import ENRICHED_DIR

        cm_path = ENRICHED_DIR / "contacts-merged.parquet"
        if not cm_path.exists():
            return

        cm = pd.read_parquet(cm_path, columns=["person_id", "last_contact"])
        now = pd.Timestamp.now(tz="UTC")

        for _, row in cm.iterrows():
            pid = str(row.get("person_id", ""))
            if pid not in profiles:
                continue

            p = profiles[pid]
            last_contact = pd.to_datetime(row.get("last_contact"), errors="coerce", utc=True)
            if pd.notna(last_contact):
                days_since = (now - last_contact).days
            else:
                days_since = 999



            half_life = 90.0
            recency = math.exp(-math.log(2) / half_life * max(0, days_since))



            p.content_richness *= 0.05 + 0.95 * recency
            p.communication_style *= 0.05 + 0.95 * recency


            p.structural_importance *= 0.02 + 0.98 * recency

        log.info("Applied recency weighting to lifetime signals")

    except Exception as exc:
        log.warning("Failed to apply recency weighting: %s", exc)





def _load_from_transcript_classifications(profiles: dict[str, QualityProfile]) -> None:
    ""





    try:
        from sbk_config import DATA_ROOT

        classifications_file = DATA_ROOT / "rq" / "transcript-classifications.json"
        if not classifications_file.exists():
            log.debug("No transcript classifications found — skipping")
            return

        data = json.loads(classifications_file.read_text(encoding="utf-8"))
        boosted = 0

        for pid, cls in data.items():
            if pid not in profiles:
                profiles[pid] = QualityProfile(pid)
            p = profiles[pid]

            score = cls.get("content_quality_score", 0.4)

            p.content_richness = max(p.content_richness, score * 0.5)
            boosted += 1

        log.info("Transcript classifications: boosted %d profiles", boosted)

    except Exception as exc:
        log.warning("Failed to load transcript classifications: %s", exc)





def print_profile(person_id: str) -> None:
    ""
    profiles = load_quality_profiles(force_reload=True)
    p = profiles.get(person_id)
    if not p:
        print(f"No quality profile for {person_id}")
        return
    print(f"Quality Profile: {person_id}")
    for k, v in p.to_dict().items():
        if k != "person_id":
            bar = "█" * int(v * 20) if isinstance(v, float) and v <= 3 else ""
            print(f"  {k:25s}  {v:6.3f}  {bar}")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    profiles = load_quality_profiles(force_reload=True)


    mults = [p.overall_multiplier for p in profiles.values()]
    print(f"\nQuality profiles: {len(profiles)}")
    print(f"Multiplier range: {min(mults):.2f} - {max(mults):.2f}")
    print(f"Mean: {sum(mults) / len(mults):.2f}")
    print(f"<0.5 (low quality): {sum(1 for m in mults if m < 0.5)}")
    print(f"0.5-1.0 (medium): {sum(1 for m in mults if 0.5 <= m < 1.0)}")
    print(f"1.0-2.0 (high): {sum(1 for m in mults if 1.0 <= m < 2.0)}")
    print(f">2.0 (exceptional): {sum(1 for m in mults if m >= 2.0)}")


    # People to inspect in this debug run: {person_id: label}.
    # Load from an unversioned local config; defaults to none.
    key_people: dict[str, str] = {}
    print(
        f"\n{'Name':25s} {'Depth':>6} {'Person':>6} {'Content':>7} {'Style':>6} {'Engage':>7} {'Struct':>6} {'MULTI':>6}"
    )
    print("-" * 80)
    for pid, name in key_people.items():
        p = profiles.get(pid)
        if p:
            print(
                f"{name:25s} {p.relationship_depth:6.3f} {p.personal_knowledge:6.3f} {p.content_richness:7.3f} {p.communication_style:6.3f} {p.engagement_quality:7.3f} {p.structural_importance:6.3f} {p.overall_multiplier:6.2f}"
            )
        else:
            print(f"{name:25s}  NOT FOUND")
