#!/usr/bin/env python3
""


















from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import cached_property
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import (
    ATTIO_PROCESSED_DIR,
    ATTIO_TRANSCRIPTS_DIR,
    BRIEFS_DIR,
    CALENDARS_DIR,
    ENRICHED_DIR,
    EXPORTS_DIR,
    L3_DIR,
    LINKEDIN_DIR,
    PERSON_ANNOTATIONS_FILE,
    RELATIONSHIP_FACTS_FILE,
    SHADOW_CONTACTS_FILE,
    SLACK_DIR,
    TACTIQ_DIR,
    TACTIQ_RAW_DIR,
    attio_transcript_files,
)

log = logging.getLogger("sbk-l3")



PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent



API_USAGE_FILE = L3_DIR / ".l3-api-usage.json"


PRICING = {
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "gemini-2.5-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "deepseek-chat": {"input": 0.28, "output": 0.42},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.0},
}



PROVIDER_CONFIG = {
    "anthropic": {
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-haiku-4-5-20251001",
        "models": {
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-5-20250929",
        },
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GOOGLE_API_KEY",
        "default_model": "gemini-2.5-flash",
        "models": {
            "flash": "gemini-2.5-flash",
            "pro": "gemini-2.5-pro",
        },
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "models": {
            "chat": "deepseek-chat",
            "reasoner": "deepseek-reasoner",
        },
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "models": {
            "mini": "gpt-4o-mini",
            "4o": "gpt-4o",
        },
    },
}


PROVIDER_PRICING = {
    "anthropic": {"input": 0.80, "output": 4.0},
    "gemini": {"input": 0.10, "output": 0.40},
    "deepseek": {"input": 0.28, "output": 0.42},
    "openai": {"input": 0.15, "output": 0.60},
}


_api_usage_lock = threading.Lock()


def _track_api_usage(
    model: str, input_tokens: int, output_tokens: int, provider: str = "anthropic"
):
    ""
    API_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


    pricing = PRICING.get(model)
    if not pricing:
        pricing = PROVIDER_PRICING.get(provider, {"input": 3.0, "output": 15.0})
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    entry["cost_usd"] = round(cost, 6)


    with _api_usage_lock:
        usage = []
        if API_USAGE_FILE.exists():
            try:
                usage = json.loads(API_USAGE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                usage = []

        usage.append(entry)
        API_USAGE_FILE.write_text(json.dumps(usage, indent=2))
    return cost




DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 15]


def _call_openai_compat(
    prompt: str,
    system: str,
    model: str,
    max_tokens: int,
    temperature: float,
    provider: str,
) -> str:
    ""
    from openai import APIStatusError, OpenAI, RateLimitError

    config = PROVIDER_CONFIG[provider]
    api_key = os.environ.get(config["api_key_env"])
    if not api_key:
        raise RuntimeError(f"{config['api_key_env']} not set in environment")

    client_kwargs = {"api_key": api_key}
    if "base_url" in config:
        client_kwargs["base_url"] = config["base_url"]
    client = OpenAI(**client_kwargs)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(**kwargs)


            usage = response.usage
            if usage:
                _track_api_usage(
                    model,
                    usage.prompt_tokens or 0,
                    usage.completion_tokens or 0,
                    provider=provider,
                )

                try:
                    from monitoring.api_ledger import log_api_call

                    log_api_call(
                        service=provider,
                        method=f"{model}.chat.completions.create",
                        direction="READ",
                        caller="xs_l3_common.call_claude",
                        tokens_in=usage.prompt_tokens or 0,
                        tokens_out=usage.completion_tokens or 0,
                    )
                except Exception:
                    pass


            choice = response.choices[0]
            return choice.message.content or ""

        except RateLimitError:
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            log.warning(
                f"[{provider}] Rate limited, retrying in {delay}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})"
            )
            time.sleep(delay)

        except APIStatusError as e:
            if e.status_code >= 500:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                log.warning(f"[{provider}] API error {e.status_code}, retrying in {delay}s")
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"{provider} API failed after {MAX_RETRIES} retries")


def call_claude(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    provider: str = "anthropic",
    cache_system: bool = False,
) -> str:
    ""












    if provider not in PROVIDER_CONFIG:
        raise ValueError(f"Unknown provider: {provider}. Valid: {list(PROVIDER_CONFIG.keys())}")


    if provider != "anthropic":

        if model.startswith("claude-") or model == DEFAULT_MODEL:
            model = PROVIDER_CONFIG[provider]["default_model"]
        return _call_openai_compat(
            prompt=prompt,
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            provider=provider,
        )


    import anthropic
    from xs_anthropic_client import (
        chiave_in_uso,
        classify_error,
        get_client,
        passa_alla_riserva,
    )

    client = get_client()

    messages = [{"role": "user", "content": prompt}]
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        if cache_system:

            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            kwargs["system"] = system





    riserva_provata = False
    for attempt in range(MAX_RETRIES + 1):
        if attempt == MAX_RETRIES and not riserva_provata:
            break
        try:
            response = client.messages.create(**kwargs)


            usage = response.usage
            _track_api_usage(model, usage.input_tokens, usage.output_tokens, provider="anthropic")

            try:
                from monitoring.api_ledger import log_api_call

                log_api_call(
                    service="anthropic",
                    method=f"{model}.messages.create",
                    direction="READ",
                    caller="xs_l3_common.call_claude",
                    tokens_in=usage.input_tokens,
                    tokens_out=usage.output_tokens,
                )
            except Exception:
                pass


            text_parts = [block.text for block in response.content if block.type == "text"]
            return "\n".join(text_parts)

        except Exception as e:

            if perm := classify_error(e):
                prima = chiave_in_uso()
                if (
                    not riserva_provata
                    and not isinstance(e, anthropic.NotFoundError)
                    and passa_alla_riserva()
                ):
                    riserva_provata = True
                    log.warning(
                        "la chiave «%s» non va (%s): riprovo con la riserva «%s»",
                        prima,
                        type(e).__name__,
                        chiave_in_uso(),
                    )
                    client = get_client()
                    continue
                raise perm from e

            if isinstance(e, anthropic.RateLimitError):
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                log.warning(
                    f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(delay)
                continue

            if isinstance(e, anthropic.APIStatusError):
                if e.status_code >= 500:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    log.warning(f"API error {e.status_code}, retrying in {delay}s")
                    time.sleep(delay)
                    continue
                raise

            raise

    raise RuntimeError(f"Claude API failed after {MAX_RETRIES} retries")





class _MtimeParquetProperty:
    ""

    def __init__(self, path_func, empty_factory=pd.DataFrame):
        self._path_func = path_func
        self._empty_factory = empty_factory

    def __set_name__(self, owner, name):
        self._attr_val = f"_mtime_prop_{name}_val"
        self._attr_mtime = f"_mtime_prop_{name}_mt"

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        path = self._path_func()
        try:
            mt = path.stat().st_mtime
        except OSError:
            return self._empty_factory()
        current_mt = getattr(obj, self._attr_mtime, 0)
        if mt != current_mt:
            with obj._mtime_lock:
                current_mt = getattr(obj, self._attr_mtime, 0)
                if mt != current_mt:
                    log.debug(f"Loading {path.name} (mtime changed)")
                    val = pd.read_parquet(path)
                    object.__setattr__(obj, self._attr_val, val)
                    object.__setattr__(obj, self._attr_mtime, mt)
        return getattr(obj, self._attr_val, self._empty_factory())





class SBKData:
    ""








    def __init__(self):
        self._mtime_lock = threading.Lock()


    contacts = _MtimeParquetProperty(lambda: ENRICHED_DIR / "contacts-merged.parquet")
    interactions = _MtimeParquetProperty(lambda: ENRICHED_DIR / "interactions.parquet")
    threads = _MtimeParquetProperty(lambda: ENRICHED_DIR / "threads.parquet")

    @cached_property
    def entity_map(self) -> dict:
        ""
        path = ENRICHED_DIR / "entity-map.json"
        log.debug(f"Loading entity map from {path}")
        return json.loads(path.read_text())

    @cached_property
    def calendar_contacts(self) -> pd.DataFrame:
        ""
        path = ENRICHED_DIR / "contacts-calendar.parquet"
        log.debug(f"Loading calendar contacts from {path}")
        return pd.read_parquet(path)

    @cached_property
    def calendar_interactions(self) -> pd.DataFrame:
        ""
        path = ENRICHED_DIR / "interactions-calendar.parquet"
        log.debug(f"Loading calendar interactions from {path}")
        return pd.read_parquet(path)

    @cached_property
    def calendar_events(self) -> list[dict]:
        ""




        events = []


        if CALENDARS_DIR.exists():
            for account_dir in sorted(CALENDARS_DIR.iterdir()):
                pq = account_dir / "events.parquet"
                if not pq.exists():
                    continue
                try:
                    df = pd.read_parquet(pq)
                    cal_name = account_dir.name
                    for _, row in df.iterrows():
                        ev = row.to_dict()

                        start_dt = str(ev.get("start_datetime", ""))
                        end_dt = str(ev.get("end_datetime", ""))
                        ev["start"] = (
                            {"dateTime": start_dt} if "T" in start_dt else {"date": start_dt}
                        )
                        ev["end"] = {"dateTime": end_dt} if "T" in end_dt else {"date": end_dt}
                        ev["calendarName"] = cal_name
                        ev["_source_file"] = pq.name
                        events.append(ev)
                except Exception as e:
                    log.warning(f"Failed to load calendar parquet {pq}: {e}")


        raw_dir = PROJECT_ROOT / "sbk" / "raw"
        seen_ids = {ev.get("id") for ev in events if ev.get("id")}
        for f in sorted(raw_dir.glob("cal-*.json")):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    for ev in data:
                        if ev.get("id") in seen_ids:
                            continue
                        ev["_source_file"] = f.name
                        events.append(ev)
                        if ev.get("id"):
                            seen_ids.add(ev["id"])
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Failed to load {f}: {e}")

        log.debug(f"Loaded {len(events)} calendar events")
        return events

    @cached_property
    def tactiq_meetings(self) -> pd.DataFrame:
        ""
        path = TACTIQ_DIR / "meetings.parquet"
        log.debug(f"Loading Tactiq meetings from {path}")
        return pd.read_parquet(path)

    @cached_property
    def slack_interactions(self) -> pd.DataFrame:
        ""
        path = SLACK_DIR / "interactions-slack.parquet"
        log.debug(f"Loading Slack interactions from {path}")
        return pd.read_parquet(path)

    @cached_property
    def slack_contacts(self) -> pd.DataFrame:
        ""
        path = SLACK_DIR / "contacts-slack.parquet"
        log.debug(f"Loading Slack contacts from {path}")
        return pd.read_parquet(path)

    @cached_property
    def attio_contacts(self) -> pd.DataFrame:
        ""
        path = ATTIO_PROCESSED_DIR / "contacts-attio.parquet"
        log.debug(f"Loading Attio contacts from {path}")
        return pd.read_parquet(path)

    @cached_property
    def attio_transcripts(self) -> pd.DataFrame:
        ""
        path = ATTIO_PROCESSED_DIR / "transcripts-index.parquet"
        log.debug(f"Loading Attio transcripts from {path}")
        return pd.read_parquet(path)

    @cached_property
    def linkedin_contacts(self) -> pd.DataFrame:
        ""
        path = LINKEDIN_DIR / "contacts-linkedin.parquet"
        log.debug(f"Loading LinkedIn contacts from {path}")
        return pd.read_parquet(path)

    @cached_property
    def relationship_scores(self) -> pd.DataFrame:
        ""
        path = EXPORTS_DIR / "relationship-scores.parquet"
        log.debug(f"Loading relationship scores from {path}")
        return pd.read_parquet(path)

    @cached_property
    def network_graph_data(self) -> dict:
        ""
        path = EXPORTS_DIR / "network-graph.json"
        log.debug(f"Loading network graph from {path}")
        return json.loads(path.read_text())

    @cached_property
    def network_profiles(self) -> dict[str, str]:
        ""



        profiles_dir = PROJECT_ROOT / "sbk" / "network" / "people"
        profiles = {}
        if profiles_dir.exists():
            for f in sorted(profiles_dir.glob("*.md")):
                profiles[f.stem] = f.read_text()

        net_dir = PROJECT_ROOT / "sbk" / "network"
        for f in sorted(net_dir.glob("*.md")):
            if f.name != "_index.md":
                profiles[f.stem] = f.read_text()
        log.debug(f"Loaded {len(profiles)} network profiles")
        return profiles



    @cached_property
    def attio_companies(self) -> pd.DataFrame:
        ""
        path = ATTIO_PROCESSED_DIR / "companies-attio.parquet"
        if not path.exists():
            log.debug("No companies-attio.parquet found, returning empty DataFrame")
            return pd.DataFrame()
        log.debug(f"Loading Attio companies from {path}")
        return pd.read_parquet(path)

    @cached_property
    def attio_deals(self) -> pd.DataFrame:
        ""
        path = ATTIO_PROCESSED_DIR.parent / "deals.parquet"
        if not path.exists():
            log.debug("No deals.parquet found, returning empty DataFrame")
            return pd.DataFrame()
        log.debug(f"Loading Attio deals from {path}")
        return pd.read_parquet(path)

    @cached_property
    def attio_lists(self) -> dict[str, pd.DataFrame]:
        ""
        lists: dict[str, pd.DataFrame] = {}
        attio_dir = ATTIO_PROCESSED_DIR.parent
        for f in sorted(attio_dir.glob("list-*.parquet")):
            list_name = f.stem.replace("list-", "")
            try:
                lists[list_name] = pd.read_parquet(f)
            except Exception as e:
                log.warning(f"Failed to load Attio list {f}: {e}")
        log.debug(f"Loaded {len(lists)} Attio lists")
        return lists




    relationship_facts = _MtimeParquetProperty(lambda: RELATIONSHIP_FACTS_FILE)

    @cached_property
    def shadow_contacts(self) -> pd.DataFrame:
        ""
        if not SHADOW_CONTACTS_FILE.exists():
            log.debug("No shadow-contacts.parquet found, returning empty DataFrame")
            return pd.DataFrame()
        log.debug(f"Loading shadow contacts from {SHADOW_CONTACTS_FILE}")
        return pd.read_parquet(SHADOW_CONTACTS_FILE)

    @cached_property
    def person_annotations(self) -> dict:
        ""
        if not PERSON_ANNOTATIONS_FILE.exists():
            log.debug("No person-annotations.json found, returning empty dict")
            return {}
        log.debug(f"Loading person annotations from {PERSON_ANNOTATIONS_FILE}")
        data = json.loads(PERSON_ANNOTATIONS_FILE.read_text())
        if isinstance(data, dict):
            return data

        log.warning("person-annotations.json is a list, expected dict — returning empty dict")
        return {}



    def resolve_person_by_name(self, name: str) -> str | None:
        ""








        if not name or not name.strip():
            return None
        name_lower = name.strip().lower()


        name_col = self.contacts["name"].fillna("").str.lower()
        matches = self.contacts[name_col == name_lower]
        if not matches.empty:
            return matches.iloc[0].get("person_id")


        for key, entry in self.entity_map.items():
            if key.startswith("nameonly:"):
                entry_name = entry.get("canonical_name", "").lower()
                if entry_name == name_lower:
                    return entry.get("person_id")


        try:
            from rapidfuzz import fuzz

            best_score = 0
            best_pid = None
            for _, row in self.contacts.iterrows():
                contact_name = str(row.get("name", "")).lower()
                if not contact_name:
                    continue
                score = fuzz.token_sort_ratio(name_lower, contact_name)
                if score > best_score and score >= 85:
                    best_score = score
                    best_pid = row.get("person_id")
            if best_pid:
                return best_pid
        except ImportError:
            log.debug("rapidfuzz not available, fuzzy name matching disabled")


        if " " not in name_lower and len(name_lower) >= 3:
            first_name_matches = []
            for _, row in self.contacts.iterrows():
                contact_name = str(row.get("name", "")).lower()
                if not contact_name:
                    continue
                parts = contact_name.split()
                if parts and parts[0] == name_lower:
                    first_name_matches.append(row.get("person_id"))
            if len(first_name_matches) == 1:
                return first_name_matches[0]

        return None

    def resolve_person(self, identifier: str) -> dict | None:
        ""









        identifier = identifier.strip().lower()


        if "@" in identifier:
            row = self.contacts[self.contacts["email"] == identifier]
            if not row.empty:
                result = row.iloc[0].to_dict()
                result["_matched_by"] = "direct_email"

                if identifier in self.entity_map:
                    result["entity_entry"] = self.entity_map[identifier]
                return result


        if identifier in self.entity_map:
            entry = self.entity_map[identifier]
            all_emails = entry.get("all_emails", [])
            for em in all_emails:
                row = self.contacts[self.contacts["email"] == em.lower()]
                if not row.empty:
                    result = row.iloc[0].to_dict()
                    result["_matched_by"] = "all_emails_loop"
                    result["entity_entry"] = entry
                    return result

            person_id = entry.get("person_id")
            if person_id:
                row = self.contacts[self.contacts["person_id"] == person_id]
                if not row.empty:
                    result = row.iloc[0].to_dict()
                    result["_matched_by"] = "person_id_fallback"
                    result["entity_entry"] = entry
                    log.debug(
                        f"resolve_person: used person_id fallback for '{identifier}' "
                        f"(person_id={person_id})"
                    )
                    return result


        name_col = self.contacts["name"].fillna("").str.lower()
        matches = self.contacts[name_col == identifier]
        if not matches.empty:
            result = matches.iloc[0].to_dict()
            result["_matched_by"] = "name_match"
            return result

        return None

    def get_person_context(self, email: str) -> dict:
        ""




        ctx = {"email": email, "found": False}

        person = self.resolve_person(email)
        if not person:
            return ctx

        ctx["found"] = True
        ctx["name"] = person.get("name", "")
        ctx["person_id"] = person.get("person_id", "")
        ctx["organization"] = person.get("organization") or person.get("attio_company") or ""
        ctx["job_title"] = person.get("attio_job_title") or person.get("linkedin_headline") or ""
        ctx["score"] = person.get("score", 0)
        ctx["source_count"] = person.get("source_count", 0)
        ctx["is_internal"] = person.get("is_internal", False)


        ctx["email_total_msgs"] = person.get("email_total_msgs", 0)
        ctx["email_last_seen"] = str(person.get("email_last_seen", ""))
        ctx["last_contact"] = str(person.get("last_contact", ""))
        ctx["last_contact_source"] = str(person.get("last_contact_source", ""))
        ctx["cal_last_seen"] = str(person.get("cal_last_seen", ""))
        ctx["slack_last_seen"] = str(person.get("slack_last_seen", ""))


        if person.get("email") and "@" in str(person.get("email", "")):
            threads_with = self.threads[
                self.threads["participants"].fillna("").str.contains(email, case=False, na=False)
            ]
            if not threads_with.empty:
                last_thread = threads_with.sort_values("date_end", ascending=False).iloc[0]
                ctx["last_thread_subject"] = last_thread.get("subject", "")
                ctx["last_thread_date"] = str(last_thread.get("date_end", ""))


        ctx["cal_events"] = person.get("cal_events", 0)
        ctx["plaud_meetings"] = person.get("plaud_meetings", 0)
        ctx["tactiq_meetings"] = person.get("tactiq_meetings", 0)


        ctx["attio_connection_strength"] = person.get("attio_connection_strength", "")
        ctx["attio_sourcing_stage"] = person.get("attio_sourcing_stage", "")
        ctx["attio_notes_count"] = person.get("attio_notes_count", 0)


        ctx["linkedin_url"] = person.get("linkedin_url", "")


        name = person.get("name", "")
        if name:
            slug = name.lower().replace(" ", "-")
            profile = self.network_profiles.get(slug, "")
            if profile:
                ctx["network_profile"] = profile


        person_id = ctx.get("person_id", "")
        if not self.relationship_facts.empty and person_id:
            rf = self.relationship_facts

            is_subject = rf["subject_person_id"] == person_id
            is_object = rf["object_person_id"] == person_id
            person_facts = rf[is_subject | is_object]
            if not person_facts.empty:
                facts_list = []
                for _, fact in person_facts.head(20).iterrows():
                    facts_list.append(
                        {
                            "type": fact.get("fact_type", ""),
                            "predicate": fact.get("predicate", ""),
                            "subject": fact.get("subject", ""),
                            "object": fact.get("object", ""),
                            "context": fact.get("context", ""),
                            "confidence": fact.get("confidence", ""),
                        }
                    )
                ctx["relationship_facts"] = facts_list


        if name:
            name_key = name.lower()
            annotations = self.person_annotations.get(name_key, {})
            if not annotations:
                annotations = self.person_annotations.get(email, {})
            if annotations:
                ctx["annotations"] = annotations

                if annotations.get("organization_override"):
                    ctx["organization"] = annotations["organization_override"]
                if annotations.get("role_override"):
                    ctx["job_title"] = annotations["role_override"]

        return ctx

    def get_upcoming_events(self, hours: float = 2.0) -> list[dict]:
        ""
        from datetime import timedelta

        now = datetime.now(UTC)
        cutoff = now + timedelta(hours=hours)
        upcoming = []

        for ev in self.calendar_events:
            start = ev.get("start", {})
            start_str = start.get("dateTime") or start.get("date", "")
            if not start_str:
                continue
            try:

                if "T" in start_str:
                    dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                else:
                    continue
                if now <= dt <= cutoff:
                    ev["_start_dt"] = dt
                    upcoming.append(ev)
            except (ValueError, TypeError):
                continue

        return sorted(upcoming, key=lambda e: e.get("_start_dt", now))





def notify_macos(
    title: str,
    message: str,
    subtitle: str = "SBK",
    url: str = "",
    group: str = "sbk",
):
    ""









    try:
        cmd = [
            "terminal-notifier",
            "-title",
            title,
            "-subtitle",
            subtitle,
            "-message",
            message,
            "-group",
            group,
            "-sound",
            "default",
        ]
        if url:
            cmd.extend(["-open", url])
        subprocess.run(cmd, capture_output=True, timeout=5)
        return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass




    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                "display notification (item 1 of argv) with title (item 2 of argv) subtitle (item 3 of argv)",
                "-e",
                "end run",
                "--",
                message,
                title,
                subtitle,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            log.warning(
                f"Notification failed: osascript exit {r.returncode} ({(r.stderr or '').strip()[:160]})"
            )
    except Exception as e:
        log.warning(f"Notification failed: {e}")





def load_identity_files() -> dict[str, str]:
    ""





    identity_dir = PROJECT_ROOT / "sbk" / "identity"
    files = {
        "profile": "profile.md",
        "style_guide": "style-guide.md",
        "communication_playbook": "communication-playbook.md",
        "decision_framework": "decision-framework.md",
        "working_rules": "working-rules.md",
    }
    result = {}
    for key, filename in files.items():
        path = identity_dir / filename
        if path.exists():
            result[key] = path.read_text()
        else:
            log.warning(f"Identity file not found: {path}")
            result[key] = ""
    return result





def write_brief(content: str, brief_type: str, slug: str = "") -> Path:
    ""









    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M")
    name = f"{brief_type}-{ts}"
    if slug:

        safe_slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug.lower())
        safe_slug = safe_slug[:50].strip("-")
        name += f"-{safe_slug}"
    name += ".md"
    path = BRIEFS_DIR / name
    path.write_text(content, encoding="utf-8")
    log.info(f"Brief written: {path}")
    return path





def setup_logging(verbose: bool = False, name: str = "sbk-l3"):
    ""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
    logging.basicConfig(level=level, format=fmt)


    from logging.handlers import RotatingFileHandler

    log_dir = L3_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / f"{name}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(fh)





def slugify(text: str, max_len: int = 50) -> str:
    ""
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:max_len]


def compute_source_hash(text: str) -> str:
    ""




    import hashlib

    _SAMPLE_THRESHOLD = 20_000
    _SAMPLE_SIZE = 10_000
    if len(text) > _SAMPLE_THRESHOLD:
        sample = text[:_SAMPLE_SIZE] + text[-_SAMPLE_SIZE:]
    else:
        sample = text
    return hashlib.sha256(sample.encode("utf-8")).hexdigest()[:16]


def ensure_dirs():
    ""
    for d in [
        L3_DIR,
        L3_DIR / "vectordb",
        L3_DIR / "graph",
        L3_DIR / "decay",
        L3_DIR / "nlp",
        L3_DIR / "logs",
        BRIEFS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)



ensure_dirs()






















_ts_log = logging.getLogger("sbk-transcript-select")

MIN_WORDS_THRESHOLD = 20
ATTIO_WORD_RATIO_THRESHOLD = 0.80
TITLE_SIMILARITY_THRESHOLD = 0.60
DURATION_COVERAGE_THRESHOLD = 0.70
MIN_SEGMENTS_PER_MINUTE = 1.0



EXPECTED_LANGUAGES = {"it", "en"}


@dataclass
class TranscriptRecord:
    ""

    source: str
    meeting_id: str
    title: str
    date: str
    word_count: int
    segment_count: int
    duration_s: float = 0.0
    last_segment_time_s: float = 0.0
    raw_text_len: int = 0
    file_path: str = ""
    declared_lang: str = ""
    platform: str = ""
    lang_coherent: bool = True
    lang_detected: str = ""


@dataclass
class TranscriptSelection:
    ""

    date: str
    title: str
    winner: str
    reason: str
    attio: TranscriptRecord | None = None
    tactiq: TranscriptRecord | None = None
    attio_words: int = 0
    tactiq_words: int = 0


def _normalize_meeting_title(title: str) -> str:
    ""
    import re

    t = title.lower().strip()
    t = re.sub(r"^\d{4}-\d{2}-\d{2}[-_]?", "", t)
    t = re.sub(
        r"^(meeting\s*:\s*|call\s*:\s*|sync\s*:\s*|standup\s*:\s*)",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"[-_]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _check_tactiq_language(blocks: list[dict]) -> tuple[bool, str, str]:
    ""









    try:
        from langdetect import LangDetectException, detect
    except ImportError:
        return True, "langdetect_not_available", ""

    if len(blocks) < 10:
        return True, "too_few_blocks", ""

    n = len(blocks)

    sample_points = [min(5, n - 1), n // 2, max(0, n - 5)]
    detected_langs = []

    for idx in sample_points:
        window = blocks[max(0, idx - 3) : min(n, idx + 4)]
        text = " ".join(
            b.get("transcript", "")
            for b in window
            if b.get("transcript") and not b.get("isDeleted")
        )
        if len(text) < 30:
            continue
        try:
            lang = detect(text)
            detected_langs.append(lang)
        except LangDetectException:
            continue

    if len(detected_langs) < 2:
        return True, "insufficient_samples", ""


    from collections import Counter

    lang_counts = Counter(detected_langs)
    majority_lang = lang_counts.most_common(1)[0][0]
    majority_count = lang_counts.most_common(1)[0][1]


    if majority_count == len(detected_langs):
        return True, "ok", majority_lang


    if majority_count >= 2:
        divergent = [lang for lang in detected_langs if lang != majority_lang]

        if detected_langs[0] != majority_lang:
            return True, f"start_mismatch ({detected_langs[0]}->{majority_lang})", majority_lang
        return True, f"minor_inconsistency ({divergent})", majority_lang


    return False, f"language_incoherent ({detected_langs})", majority_lang


def _check_attio_completeness(rec: TranscriptRecord) -> tuple[bool, str]:
    ""






    if rec.word_count < MIN_WORDS_THRESHOLD:
        return False, f"too_few_words ({rec.word_count})"

    if rec.duration_s > 0:

        if rec.last_segment_time_s > 0:
            coverage = rec.last_segment_time_s / rec.duration_s
            if coverage < DURATION_COVERAGE_THRESHOLD:
                return (
                    False,
                    f"low_duration_coverage ({coverage:.0%}, need {DURATION_COVERAGE_THRESHOLD:.0%})",
                )



        duration_min = rec.duration_s / 60
        if duration_min > 2:
            words_per_min = rec.word_count / duration_min
            if words_per_min < 50:
                return False, f"low_word_density ({words_per_min:.0f} w/min, need 50)"

    return True, "ok"


def load_attio_transcript_index() -> dict[str, list[TranscriptRecord]]:
    ""



    index: dict[str, list[TranscriptRecord]] = {}


    for fpath in attio_transcript_files(ATTIO_TRANSCRIPTS_DIR):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        date_raw = data.get("meeting_date", "")
        date = date_raw[:10] if date_raw else ""
        if not date:
            continue

        segments = data.get("segments", [])
        word_count = sum(len(s.get("text", "").split()) for s in segments)
        raw_text = data.get("raw_transcript", "")

        last_seg_time = 0.0
        if segments:
            last_end = segments[-1].get("end", 0)
            if isinstance(last_end, int | float):
                last_seg_time = float(last_end)

        rec = TranscriptRecord(
            source="attio",
            meeting_id=data.get("meeting_id", fpath.stem),
            title=data.get("meeting_title", fpath.stem),
            date=date,
            word_count=word_count,
            segment_count=len(segments),
            duration_s=0.0,
            last_segment_time_s=last_seg_time,
            raw_text_len=len(raw_text),
            file_path=str(fpath),
        )
        index.setdefault(date, []).append(rec)

    return index


def load_tactiq_transcript_index() -> dict[str, list[TranscriptRecord]]:
    ""



    index: dict[str, list[TranscriptRecord]] = {}

    if not TACTIQ_RAW_DIR.exists():
        return index

    for fpath in sorted(TACTIQ_RAW_DIR.glob("*.json")):
        if fpath.name.startswith("_"):
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        created_ms = data.get("created", 0)
        if not created_ms:
            continue

        dt = datetime.fromtimestamp(created_ms / 1000, tz=UTC)
        date = dt.strftime("%Y-%m-%d")

        transcript = data.get("transcript", {})
        blocks = transcript.get("blocks", []) if isinstance(transcript, dict) else []
        word_count = sum(
            len(b.get("transcript", "").split()) for b in blocks if not b.get("isDeleted")
        )
        duration_s = float(data.get("duration", 0))


        lang_coherent, lang_issue, lang_detected = _check_tactiq_language(blocks)
        declared_lang = data.get("languageCode", "")[:2].lower()
        platform = data.get("platform", "")

        if not lang_coherent:
            _ts_log.debug(
                f"Tactiq lang issue: {fpath.name[:50]} declared={declared_lang} {lang_issue}"
            )

        rec = TranscriptRecord(
            source="tactiq",
            meeting_id=data.get("id", fpath.stem),
            title=data.get("title", fpath.stem),
            date=date,
            word_count=word_count,
            segment_count=len(blocks),
            duration_s=duration_s,
            file_path=str(fpath),
            declared_lang=declared_lang,
            platform=platform,
            lang_coherent=lang_coherent,
            lang_detected=lang_detected,
        )
        index.setdefault(date, []).append(rec)

    return index


def build_transcript_selection_index() -> list[TranscriptSelection]:
    ""






    attio_idx = load_attio_transcript_index()
    tactiq_idx = load_tactiq_transcript_index()

    selections: list[TranscriptSelection] = []
    matched_attio: set[str] = set()
    matched_tactiq: set[str] = set()


    all_dates = set(attio_idx.keys()) | set(tactiq_idx.keys())

    for date in sorted(all_dates):
        attio_recs = attio_idx.get(date, [])
        tactiq_recs = tactiq_idx.get(date, [])


        used_tactiq: set[int] = set()

        for a_rec in attio_recs:
            a_title_norm = _normalize_meeting_title(a_rec.title)
            best_match: TranscriptRecord | None = None
            best_ratio = 0.0
            best_idx = -1

            for t_i, t_rec in enumerate(tactiq_recs):
                if t_i in used_tactiq:
                    continue
                t_title_norm = _normalize_meeting_title(t_rec.title)
                ratio = SequenceMatcher(None, a_title_norm, t_title_norm).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = t_rec
                    best_idx = t_i

            if best_match and best_ratio >= TITLE_SIMILARITY_THRESHOLD:

                used_tactiq.add(best_idx)
                matched_attio.add(a_rec.file_path)
                matched_tactiq.add(best_match.file_path)

                sel = _select_winner(a_rec, best_match)
                selections.append(sel)
            else:

                matched_attio.add(a_rec.file_path)
                if a_rec.word_count >= MIN_WORDS_THRESHOLD:
                    selections.append(
                        TranscriptSelection(
                            date=date,
                            title=a_rec.title,
                            winner="attio",
                            reason="attio_only",
                            attio=a_rec,
                            attio_words=a_rec.word_count,
                        )
                    )
                else:
                    selections.append(
                        TranscriptSelection(
                            date=date,
                            title=a_rec.title,
                            winner="skip",
                            reason=f"attio_only_but_empty ({a_rec.word_count}w)",
                            attio=a_rec,
                            attio_words=a_rec.word_count,
                        )
                    )


        for t_i, t_rec in enumerate(tactiq_recs):
            if t_i in used_tactiq:
                continue
            matched_tactiq.add(t_rec.file_path)
            if t_rec.word_count >= MIN_WORDS_THRESHOLD:
                selections.append(
                    TranscriptSelection(
                        date=date,
                        title=t_rec.title,
                        winner="tactiq",
                        reason="tactiq_only",
                        tactiq=t_rec,
                        tactiq_words=t_rec.word_count,
                    )
                )
            else:
                selections.append(
                    TranscriptSelection(
                        date=date,
                        title=t_rec.title,
                        winner="skip",
                        reason=f"tactiq_only_but_empty ({t_rec.word_count}w)",
                        tactiq=t_rec,
                        tactiq_words=t_rec.word_count,
                    )
                )


    total_attio = sum(len(recs) for recs in attio_idx.values())
    total_tactiq = sum(len(recs) for recs in tactiq_idx.values())
    unmatched_attio = total_attio - len(matched_attio)
    unmatched_tactiq = total_tactiq - len(matched_tactiq)

    if unmatched_attio > 0 or unmatched_tactiq > 0:
        _ts_log.warning(
            f"Coverage gap: {unmatched_attio} Attio + {unmatched_tactiq} Tactiq meetings unaccounted"
        )


    winners = {"attio": 0, "tactiq": 0, "skip": 0}
    for s in selections:
        winners[s.winner] += 1

    _ts_log.info(
        f"Transcript selection: {len(selections)} meetings "
        f"(attio={winners['attio']}, tactiq={winners['tactiq']}, skip={winners['skip']}). "
        f"Sources: {total_attio} attio, {total_tactiq} tactiq"
    )


    try:
        index_path = ENRICHED_DIR / "transcript-selection-index.json"
        index_data = {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_meetings": len(selections),
            "attio_wins": winners["attio"],
            "tactiq_wins": winners["tactiq"],
            "skipped": winners["skip"],
            "selections": [asdict(s) for s in selections],
        }
        index_path.write_text(json.dumps(index_data, indent=2, default=str))
        _ts_log.info(f"Saved transcript selection index → {index_path}")
    except Exception as e:
        _ts_log.warning(f"Failed to persist selection index: {e}")

    return selections


def _select_winner(attio: TranscriptRecord, tactiq: TranscriptRecord) -> TranscriptSelection:
    ""

    if attio.word_count < MIN_WORDS_THRESHOLD and tactiq.word_count < MIN_WORDS_THRESHOLD:
        return TranscriptSelection(
            date=attio.date,
            title=attio.title,
            winner="skip",
            reason=f"both_empty (attio={attio.word_count}w, tactiq={tactiq.word_count}w)",
            attio=attio,
            tactiq=tactiq,
            attio_words=attio.word_count,
            tactiq_words=tactiq.word_count,
        )


    if attio.word_count < MIN_WORDS_THRESHOLD:

        if not tactiq.lang_coherent:
            return TranscriptSelection(
                date=attio.date,
                title=attio.title,
                winner="skip",
                reason="attio_empty + tactiq_lang_incoherent",
                attio=attio,
                tactiq=tactiq,
                attio_words=attio.word_count,
                tactiq_words=tactiq.word_count,
            )
        return TranscriptSelection(
            date=attio.date,
            title=attio.title,
            winner="tactiq",
            reason=f"attio_empty ({attio.word_count}w)",
            attio=attio,
            tactiq=tactiq,
            attio_words=attio.word_count,
            tactiq_words=tactiq.word_count,
        )


    if not tactiq.lang_coherent and attio.word_count >= MIN_WORDS_THRESHOLD:
        return TranscriptSelection(
            date=attio.date,
            title=attio.title,
            winner="attio",
            reason=f"tactiq_lang_incoherent (attio={attio.word_count}w)",
            attio=attio,
            tactiq=tactiq,
            attio_words=attio.word_count,
            tactiq_words=tactiq.word_count,
        )


    is_complete, check_reason = _check_attio_completeness(attio)

    if not is_complete:


        if tactiq.word_count >= MIN_WORDS_THRESHOLD and tactiq.lang_coherent:
            return TranscriptSelection(
                date=attio.date,
                title=attio.title,
                winner="tactiq",
                reason=f"attio_incomplete: {check_reason}",
                attio=attio,
                tactiq=tactiq,
                attio_words=attio.word_count,
                tactiq_words=tactiq.word_count,
            )

        return TranscriptSelection(
            date=attio.date,
            title=attio.title,
            winner="attio",
            reason=f"attio_incomplete_but_tactiq_worse ({check_reason})",
            attio=attio,
            tactiq=tactiq,
            attio_words=attio.word_count,
            tactiq_words=tactiq.word_count,
        )


    if tactiq.word_count >= MIN_WORDS_THRESHOLD:
        ratio = attio.word_count / max(tactiq.word_count, 1)
        if ratio >= ATTIO_WORD_RATIO_THRESHOLD:
            return TranscriptSelection(
                date=attio.date,
                title=attio.title,
                winner="attio",
                reason=f"attio_preferred (ratio={ratio:.2f})",
                attio=attio,
                tactiq=tactiq,
                attio_words=attio.word_count,
                tactiq_words=tactiq.word_count,
            )
        else:

            if not tactiq.lang_coherent:
                return TranscriptSelection(
                    date=attio.date,
                    title=attio.title,
                    winner="attio",
                    reason=f"attio_shorter_but_tactiq_lang_bad (ratio={ratio:.2f})",
                    attio=attio,
                    tactiq=tactiq,
                    attio_words=attio.word_count,
                    tactiq_words=tactiq.word_count,
                )
            return TranscriptSelection(
                date=attio.date,
                title=attio.title,
                winner="tactiq",
                reason=f"attio_too_short (ratio={ratio:.2f}, need {ATTIO_WORD_RATIO_THRESHOLD})",
                attio=attio,
                tactiq=tactiq,
                attio_words=attio.word_count,
                tactiq_words=tactiq.word_count,
            )


    return TranscriptSelection(
        date=attio.date,
        title=attio.title,
        winner="attio",
        reason="tactiq_empty",
        attio=attio,
        tactiq=tactiq,
        attio_words=attio.word_count,
        tactiq_words=tactiq.word_count,
    )


def get_excluded_tactiq_meeting_ids() -> set[str]:
    ""



    selections = build_transcript_selection_index()
    excluded = set()
    for sel in selections:
        if sel.winner != "tactiq" and sel.tactiq:
            excluded.add(sel.tactiq.meeting_id)
    return excluded


def get_excluded_attio_meeting_ids() -> set[str]:
    ""



    selections = build_transcript_selection_index()
    excluded = set()
    for sel in selections:
        if sel.winner != "attio" and sel.attio:
            excluded.add(sel.attio.meeting_id)
    return excluded


def log_transcript_selection_report(selections: list[TranscriptSelection] | None = None) -> None:
    ""
    if selections is None:
        selections = build_transcript_selection_index()

    matched = [s for s in selections if s.attio and s.tactiq]
    attio_only = [s for s in selections if s.attio and not s.tactiq]
    tactiq_only = [s for s in selections if s.tactiq and not s.attio]

    _ts_log.info("=== Transcript Selection Report ===")
    _ts_log.info(f"  Total meetings: {len(selections)}")
    _ts_log.info(f"  Matched (both sources): {len(matched)}")
    _ts_log.info(f"  Attio-only: {len(attio_only)}")
    _ts_log.info(f"  Tactiq-only: {len(tactiq_only)}")

    winners = {"attio": 0, "tactiq": 0, "skip": 0}
    for s in selections:
        winners[s.winner] += 1
    _ts_log.info(
        f"  Winners: attio={winners['attio']}, tactiq={winners['tactiq']}, skip={winners['skip']}"
    )


    for s in matched:
        _ts_log.debug(
            f"  [{s.date}] {s.title[:50]} -> {s.winner} ({s.reason}) "
            f"[attio={s.attio_words}w, tactiq={s.tactiq_words}w]"
        )
