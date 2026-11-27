""









from __future__ import annotations

import atexit
import json
import logging
import os
import re
import sys
import tempfile






try:  # noqa: UP017
    from datetime import UTC, datetime, timedelta
except ImportError:
    from datetime import datetime, timedelta, timezone

    UTC = timezone.utc
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("sbk.config")



DISPLAY_TZ = ZoneInfo(os.environ.get("SBK_DISPLAY_TZ", "UTC"))


def utc_now() -> datetime:
    ""
    return datetime.now(UTC)


def to_utc_aware(dt: datetime) -> datetime:
    ""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_display_tz(dt: datetime) -> datetime:
    ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(DISPLAY_TZ)






# An empty SBK_DATA_ROOT (e.g. an empty line in .env) counts as unset.
DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT") or str(Path.home() / ".sbk-data")).expanduser()







def _load_user_config() -> dict:
    import json

    candidates = [
        os.environ.get("SBK_CONFIG"),
        DATA_ROOT / "sbk.config.json",
        Path(__file__).resolve().parents[1] / "sbk.config.json",
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("sbk.config unreadable (%s): %s", p, exc)
    return {}


_USER_CFG = _load_user_config()


def user_cfg(path: str, default=None):
    """A value of sbk.config.json by dotted path ("slack.exclude_channel_ids").

    Missing keys, null and empty values ("", [], {}) give `default`, so an
    absent field always means "keep the built-in behaviour". Keys starting
    with "_" (like "_help") are notes for people and are never returned.
    """
    node = _USER_CFG
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    if node is None or node == "" or node == [] or node == {}:
        return default
    if isinstance(node, dict):
        node = {k: v for k, v in node.items() if not str(k).startswith("_")}
        if not node:
            return default
    return node


# --- Sources you connected (sbk.config.json "enabled_sources") -------------
# Empty or missing = every source (the behaviour before this field was read).
# Names are compared without "-" and "_", so "voice-memos" == "voicememos".
def _norm_source(name: str) -> str:
    return str(name).strip().lower().replace("-", "").replace("_", "")


ENABLED_SOURCES: frozenset[str] = frozenset(
    _norm_source(s) for s in (user_cfg("enabled_sources", []) or []) if str(s).strip()
)


def source_enabled(name: str) -> bool:
    """True if `name` is listed in enabled_sources, or if the list is empty."""
    return not ENABLED_SOURCES or _norm_source(name) in ENABLED_SOURCES


def source_listed(name: str) -> bool:
    """True only if `name` is written in enabled_sources (an empty list does not count).

    For the sources that read a login session of an app or a browser on this Mac (Plaud,
    Tactiq, LinkedIn) and for closed sources (chatgpt): they run only when you list them.
    """
    return _norm_source(name) in ENABLED_SOURCES


# --- Google ----------------------------------------------------------------
# Google plugins sign in with your own OAuth client (Desktop app), one browser
# login per account, refresh token in the Keychain: see tools/google_oauth.py.
# Nothing to set here; the client JSON path is GOOGLE_OAUTH_CLIENT_SECRET_PATH.

# --- Slack -----------------------------------------------------------------
# One user token reads one workspace: the one your Slack app is installed in,
# which Slack reports through auth.test. Nothing to set for it here.
# Channels you never want downloaded: regular expressions matched on the
# channel name, and/or conversation ids (channels, DMs, group DMs).
SLACK_EXCLUDE_CHANNEL_PATTERNS: list[str] = [
    str(p) for p in (user_cfg("slack.exclude_channel_patterns", []) or []) if str(p).strip()
]
SLACK_EXCLUDE_CHANNEL_IDS: frozenset[str] = frozenset(
    str(c).strip() for c in (user_cfg("slack.exclude_channel_ids", []) or []) if str(c).strip()
)
# {user_id: name} for ids Slack no longer resolves to a name (deactivated users,
# people from other organisations in shared channels).
SLACK_USER_NAMES: dict[str, str] = {
    str(k): str(v) for k, v in (user_cfg("slack.user_names", {}) or {}).items()
}

# --- Attio -----------------------------------------------------------------
# The primary workspace always reads ATTIO_API_KEY and needs no entry here.
# Extra workspaces: {label: display name}; key in Keychain sbk-attio/<label>,
# data in <data root>/attio-<label>/.
ATTIO_EXTRA_WORKSPACES: dict[str, str] = {
    str(k): str(v) for k, v in (user_cfg("attio.extra_workspaces", {}) or {}).items()
}

# --- ClickUp ---------------------------------------------------------------
# {workspace (team) id: name}. Empty = every workspace your API token can
# see, asked to ClickUp at run time. The first one is stored in clickup/backup/,
# the others in clickup/backup-<id>/.
CLICKUP_TEAMS: dict[str, str] = {
    str(k): str(v) for k, v in (user_cfg("clickup.teams", {}) or {}).items()
}

# --- Plaud -----------------------------------------------------------------
# API host of your Plaud account region. Env SBK_PLAUD_API_BASE wins.
PLAUD_API_BASE: str = (
    os.environ.get("SBK_PLAUD_API_BASE")
    or user_cfg("plaud.api_base", "")
    or "https://api-euc1.plaud.ai"
).rstrip("/")

# --- Voice Memos -----------------------------------------------------------
# whisper.cpp language code ("en", "it", ...) or "auto" to detect it.
VOICE_MEMOS_LANGUAGE: str = str(
    os.environ.get("SBK_VOICE_MEMOS_LANGUAGE") or user_cfg("voice_memos.language", "auto")
)


# --- Who you are (sbk.config.json only: owner, own_names, own_emails, own_person_id)
# There are no built-in defaults: a missing value stays empty and SBK logs one
# warning, so the stages that need it simply do not recognise you yet.
OWNER_NAME: str = str(user_cfg("owner", "") or "").strip()
# Used in prompts and messages; never a person's name unless you set "owner".
OWNER_LABEL: str = OWNER_NAME or "the owner"
OWNER_FIRST_NAME: str = OWNER_NAME.split()[0].lower() if OWNER_NAME else ""
# The label clinical records use for you (--subject): your "owner", lower case.
# Empty when "owner" is not set: the clinical scripts then ask for --subject.
OWNER_SUBJECT: str = OWNER_NAME.lower()



EMAILS_DIR = DATA_ROOT / "emails"


EMAIL_ACCOUNTS = tuple(_USER_CFG.get("email_accounts", ("work", "personal")))


def _labels_from(*groups) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for label in group:
            label = str(label).strip()
            if label and label not in seen:
                seen.append(label)
    return seen


def _subfolders_with(base: Path, filename: str) -> list[str]:
    try:
        return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / filename).exists())
    except OSError:
        return []


def mail_labels() -> list[str]:
    """Your mailbox labels, read from configuration and data, never built in.

    Keys of <data root>/emails/accounts.json, then "email_accounts" in sbk.config.json
    (only when you set it), then every emails/<label>/ folder that holds messages.parquet
    (mailboxes written by microsoft365 or imap-caldav). Order kept, no duplicates.
    """
    import json as _json

    from_file: list[str] = []
    accounts = DATA_ROOT / "emails" / "accounts.json"
    if accounts.is_file():
        try:
            data = _json.loads(accounts.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                from_file = list(data)
        except (ValueError, OSError):
            pass
    return _labels_from(
        from_file,
        user_cfg("email_accounts", []) or [],
        _subfolders_with(DATA_ROOT / "emails", "messages.parquet"),
    )


def calendar_labels() -> list[str]:
    """Your calendar account labels: every calendars/<label>/ folder that holds events.parquet,
    then the mailbox labels (mail_labels()) that have a calendars/<label>/ folder."""
    base = DATA_ROOT / "calendars"
    return _labels_from(
        _subfolders_with(base, "events.parquet"),
        [m for m in mail_labels() if (base / m).is_dir()],
    )


ENRICHED_DIR = DATA_ROOT / "enriched"
EXPORTS_DIR = DATA_ROOT / "exports"
PLAUD_DIR = DATA_ROOT / "plaud" / "raw"
PLAUD_PROCESSED_DIR = DATA_ROOT / "plaud" / "processed"
TACTIQ_DIR = DATA_ROOT / "tactiq" / "processed"
ATTIO_DIR = DATA_ROOT / "attio"
ATTIO_PROCESSED_DIR = DATA_ROOT / "attio" / "processed"












ENV_ATTIO_SECONDA_CLASSE = "SBK_ATTIO_CONTACTS_WITHOUT_EMAIL"
# Older Italian name of the same switch, still read.
ENV_ATTIO_SECONDA_CLASSE_VECCHIA = "SBK_ATTIO_SECONDA_CLASSE"





ATTIO_SECONDA_CLASSE_PARQUET = "contacts-attio-noemail.parquet"
ATTIO_SECONDA_CLASSE_PATH = ATTIO_PROCESSED_DIR / ATTIO_SECONDA_CLASSE_PARQUET


def attio_seconda_classe_attiva(cli_flag: bool = False) -> bool:
    ""
    if cli_flag:
        return True
    valore = os.environ.get(ENV_ATTIO_SECONDA_CLASSE) or os.environ.get(
        ENV_ATTIO_SECONDA_CLASSE_VECCHIA, "0"
    )
    return valore.strip().lower() in ("1", "true", "yes", "on", "si")


PERSONIO_DIR = DATA_ROOT / "personio"
LINKEDIN_DIR = DATA_ROOT / "linkedin" / "processed"
SLACK_DIR = DATA_ROOT / "slack" / "processed"
WHATSAPP_DIR = DATA_ROOT / "whatsapp" / "processed"
DOCUSIGN_DIR = DATA_ROOT / "docusign" / "processed"
IPHONE_DIR = DATA_ROOT / "contacts" / "processed"
NOTION_DIR = DATA_ROOT / "notion" / "processed"
CHATGPT_DIR = DATA_ROOT / "chatgpt" / "processed"
GDRIVE_DIR = DATA_ROOT / "gdrive" / "processed"
WHOOP_DIR = DATA_ROOT / "whoop"
WHOOP_RAW_DIR = WHOOP_DIR / "raw"
WHOOP_PROCESSED_DIR = WHOOP_DIR / "processed"
# Optional health feature (Apple Health / clinical records import).
# Paths only; enable the feature if you use it. No default data subject
# is assumed by the configuration.
APPLE_HEALTH_DIR = DATA_ROOT / "apple-health"
APPLE_HEALTH_IMPORTS_DIR = APPLE_HEALTH_DIR / "imports"
APPLE_HEALTH_RAW_DIR = APPLE_HEALTH_DIR / "raw"
APPLE_HEALTH_PROCESSED_DIR = APPLE_HEALTH_DIR / "processed"
CLINICAL_DIR = DATA_ROOT / "clinical"
CLINICAL_INCOMING_DIR = CLINICAL_DIR / "incoming"
CLINICAL_ORIGINALS_DIR = CLINICAL_DIR / "originals"
CLINICAL_PROCESSED_DIR = CLINICAL_DIR / "processed"



DOCUSIGN_RAW_DIR = DATA_ROOT / "docusign"
TACTIQ_RAW_DIR = DATA_ROOT / "tactiq" / "raw"
LINKEDIN_RAW_DIR = DATA_ROOT / "linkedin" / "raw"
PERSONIO_PROCESSED_DIR = PERSONIO_DIR / "processed"
SLACK_CONVERSATIONS_DIR = DATA_ROOT / "slack" / "conversations"
SLACK_CHANNELS_FILE = DATA_ROOT / "slack" / "slack-channels.json"
SLACK_CHANNEL_INDEX_FILE = DATA_ROOT / "slack" / "channel-index.json"
WHATSAPP_CHATS_DIR = DATA_ROOT / "whatsapp" / "chats"
WHATSAPP_DOCUMENTS_DIR = DATA_ROOT / "whatsapp" / "documents"
CONTACTS_DIR = DATA_ROOT / "contacts"
VOICE_MEMOS_DIR = DATA_ROOT / "voice-memos"
VOICE_MEMOS_TRANSCRIPTS_DIR = VOICE_MEMOS_DIR / "transcripts"
VOICE_MEMOS_PROCESSED_DIR = VOICE_MEMOS_DIR / "processed"
ATTIO_TRANSCRIPTS_DIR = ATTIO_DIR / "transcripts"




# Attio workspaces. The primary one (label "primary", key ATTIO_API_KEY, data in attio/)
# plus the extra ones of sbk.config.json "attio.extra_workspaces" (data in attio-<label>/).
ATTIO_PRIMARY_WORKSPACE = "primary"
ATTIO_WORKSPACE_DIRS: dict[str, Path] = {
    ATTIO_PRIMARY_WORKSPACE: ATTIO_DIR,
    **{
        label: DATA_ROOT / f"attio-{label}"
        for label in ATTIO_EXTRA_WORKSPACES
        if label != ATTIO_PRIMARY_WORKSPACE
    },
}
ATTIO_TRANSCRIPTS_DIRS: list[Path] = [d / "transcripts" for d in ATTIO_WORKSPACE_DIRS.values()]


def attio_transcript_files(primaria: Path | None = None) -> list[Path]:
    ""





    dirs = (
        ATTIO_TRANSCRIPTS_DIRS
        if primaria is None or primaria == ATTIO_TRANSCRIPTS_DIR
        else [primaria]
    )
    return sorted(
        f for d in dirs if d.exists() for f in d.glob("*.json") if not f.name.startswith("_")
    )


def attio_transcript_path(recording_id: str, primaria: Path | None = None) -> Path:
    ""

    base = primaria or ATTIO_TRANSCRIPTS_DIR
    dirs = ATTIO_TRANSCRIPTS_DIRS if base == ATTIO_TRANSCRIPTS_DIR else [base]
    for d in dirs:
        f = d / f"{recording_id}.json"
        if f.exists():
            return f
    return base / f"{recording_id}.json"


SESSIONS_TEXT_DIR = DATA_ROOT / "manual-ingestion" / "session-text"



CALENDARS_DIR = DATA_ROOT / "calendars"
# The JSON copy of a full calendar download (tools/calendar/ca-l0-download.py).
CALENDAR_RAW_DIR = CALENDARS_DIR / "raw"
# People profiles written by tools/cross-source/xs-l2-network-profiles.py (<tier>/<id>.md),
# plus your optional _index.md and investors.json; read by the search index and the drafts.
NETWORK_DIR = DATA_ROOT / "network"
# Your own markdown notes and analyses, indexed by tools/cross-source/xs-l3-index.py (source "raw").
NOTES_DIR = DATA_ROOT / "notes"



L3_DIR = DATA_ROOT / "l3"
PERFORMANCE_DIR = L3_DIR / "performance"
VECTOR_DB_DIR = L3_DIR / "vectordb"
GRAPH_DIR = L3_DIR / "graph"
DECAY_DIR = L3_DIR / "decay"
TASKS_DIR = L3_DIR / "tasks"
NLP_DIR = L3_DIR / "nlp"
RELATIONSHIP_FACTS_FILE = NLP_DIR / "relationship-facts.parquet"
DEEP_FACTS_FILE = NLP_DIR / "deep-facts.parquet"
SHADOW_CONTACTS_FILE = NLP_DIR / "shadow-contacts.parquet"
ENTITIES_FILE = NLP_DIR / "entities.parquet"
RELATIONSHIP_RESPONSES_DIR = NLP_DIR / "relationship-responses"
DEEP_RESPONSES_DIR = NLP_DIR / "deep-responses"
PERSON_ANNOTATIONS_FILE = ENRICHED_DIR / "person-annotations.json"
FACT_INDEX_FILE = L3_DIR / "fact-index.json"
BRIEFS_DIR = DATA_ROOT / "briefs"
ALERTS_DIR = DATA_ROOT / "alerts"
CONTENT_DIR = DATA_ROOT / "content"
CONTENT_QUEUE_FILE = CONTENT_DIR / "content-queue.json"
CONTENT_SEEDS_FILE = CONTENT_DIR / "content-seeds.json"
CONTENT_LOG_FILE = CONTENT_DIR / "content-log.json"
CONTENT_CALENDAR_FILE = CONTENT_DIR / "content-calendar.json"
CONTENT_DRAFTS_DIR = CONTENT_DIR / "drafts"
CONTENT_SEEDS_DIR = CONTENT_DIR / "seeds"
CONTENT_LOGS_DIR = CONTENT_DIR / "logs"
SENSITIVITY_CONFIG_FILE = CONTENT_DIR / "sensitivity-config.json"
IDEAS_FILE = CONTENT_DIR / "ideas.json"
COMMITMENTS_DIR = DATA_ROOT / "commitments"
COMMITMENTS_FILE = COMMITMENTS_DIR / "commitments.json"
SIGNALS_DIR = DATA_ROOT / "signals"
SIGNALS_LOG_FILE = SIGNALS_DIR / "signals-log.json"
SIGNAL_CONFIG_FILE = SIGNALS_DIR / "signal-config.json"
PERSON_CONTEXT_DIR = DATA_ROOT / "person-context"
DECISIONS_DIR = DATA_ROOT / "decisions"
DECISION_INDEX_FILE = DECISIONS_DIR / "decision-index.json"
DECISIONS_FILE = NLP_DIR / "decisions.parquet"
TOPICS_FILE = NLP_DIR / "topics.json"



HR_POLICY_DIR = DATA_ROOT / "hr-policy"
EMAIL_PDFS_DIR = DATA_ROOT / "email-pdfs"
SBK_ANALYSES_DIR = DATA_ROOT / "sbk-analyses"
MANUS_DIR = DATA_ROOT / "manus"



KNOWLEDGE_DIR = DATA_ROOT / "knowledge"
KNOWLEDGE_ENTITIES_DIR = KNOWLEDGE_DIR / "entities"
KNOWLEDGE_FACTS_DIR = KNOWLEDGE_DIR / "facts"
KNOWLEDGE_CONFLICTS_DIR = KNOWLEDGE_DIR / "conflicts"
KNOWLEDGE_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "snapshots"
KNOWLEDGE_META_DIR = KNOWLEDGE_DIR / "meta"
KNOWLEDGE_RELATIONSHIPS_DIR = KNOWLEDGE_DIR / "relationships"
QUALITY_METRICS_DIR = KNOWLEDGE_DIR / "quality-metrics"





KNOWLEDGE_LAST_EXTRACTION_FILE = KNOWLEDGE_META_DIR / "last-extraction.json"
















KB_SILENZIO_GIORNI = 7


def kb_ultima_estrazione() -> datetime | None:
    ""





    try:
        d = json.loads(KNOWLEDGE_LAST_EXTRACTION_FILE.read_text(encoding="utf-8"))
        t = datetime.fromisoformat(d["last_extraction"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def kb_giorni_di_silenzio() -> float | None:
    ""







    t = kb_ultima_estrazione()
    if t is None:
        return None
    return (datetime.now(UTC) - t).total_seconds() / 86400


def kb_ultimo_fatto_scritto() -> datetime | None:
    ""





    piu_recente = 0.0
    radice = DATA_ROOT / "knowledge" / "entities"
    if not radice.exists():
        return None
    for tipo in radice.iterdir():
        if not tipo.is_dir():
            continue
        try:
            with os.scandir(tipo) as voci:
                for v in voci:
                    if v.name.endswith(".json"):
                        m = v.stat().st_mtime
                        if m > piu_recente:
                            piu_recente = m
        except OSError:
            continue
    if not piu_recente:
        return None
    return datetime.fromtimestamp(piu_recente, UTC)


def kb_giorni_senza_fatti_nuovi() -> float | None:
    ""













    t = kb_ultimo_fatto_scritto()
    if t is None:
        return None
    return (datetime.now(UTC) - t).total_seconds() / 86400


def kb_fatti_creati_di_recente(giorni: int = 30) -> int | None:
    ""








    radice = DATA_ROOT / "knowledge" / "entities"
    if not radice.exists():
        return None
    limite = (datetime.now(UTC) - timedelta(days=giorni)).isoformat()
    n = 0
    for tipo in radice.iterdir():
        if not tipo.is_dir():
            continue
        for f in tipo.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for fatto in d.get("facts", []):
                if str(fatto.get("created_at") or "") >= limite:
                    n += 1
    return n




INTERACTION_WEIGHTS_FILE = DATA_ROOT / "interaction-weights.json"
RELATIONSHIP_DECAY_FILE = DATA_ROOT / "relationship-decay.json"
RQ_DIR = DATA_ROOT / "rq"
V5_BACKUP_PATH = DATA_ROOT / "contacts-merged-v5-backup.parquet"
RQ_SCORING_ENABLED = (RQ_DIR / "rq-enabled.flag").exists()
RQ_SEVERITY_ENABLED = (RQ_DIR / "rq-severity-enabled.flag").exists()



RQ_V2_FLAG = RQ_DIR / "rq-v2-enabled.flag"
RQ_SIGNALS_FILE = RQ_DIR / "signals.parquet"
RQ_SCORES_V2_FILE = RQ_DIR / "composite-scores-v2.parquet"
RQ_NAME_MATCHING_INDEX = RQ_DIR / "name-matching-index.json"
RQ_SCORING_CONFIG_V2 = RQ_DIR / "scoring-config-v2.json"


def is_rq_v2_enabled() -> bool:
    ""
    return RQ_V2_FLAG.exists()



RQ_V4_FLAG = RQ_DIR / "rq-v4-enabled.flag"
RQ_V4_DB = RQ_DIR / "events.db"


def is_rq_v4_enabled() -> bool:
    ""
    return RQ_V4_FLAG.exists()


def get_relationship_score(entity_id: str) -> dict | None:
    ""



    if RQ_SCORING_ENABLED:
        rq_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{entity_id}.json"
        if rq_file.exists():
            try:
                import json as _json

                data = _json.loads(rq_file.read_text(encoding="utf-8"))
                return {
                    "source": "rq",
                    "score": data.get("score"),
                    "state": data.get("state"),
                    "breakdown": data.get("breakdown"),
                    "dunbar_circle": data.get("dunbar_circle"),
                    "relationship_type": data.get("relationship_type"),
                }
            except Exception:
                log.warning("RQ score failed for %s, falling back to V5", entity_id)


    v5_file = ENRICHED_DIR / "contacts-merged.parquet"
    if v5_file.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(v5_file)
            match = (
                df[df["person_id"] == entity_id] if "person_id" in df.columns else pd.DataFrame()
            )
            if not match.empty:
                row = match.iloc[0]
                return {
                    "source": "v5",
                    "score": float(row.get("score", 0)),
                    "category": str(row.get("category", "")),
                }
        except Exception:
            pass

    return None




EVENTS_DIR = DATA_ROOT / "events"
L1_CHECKPOINT_DIR = DATA_ROOT / "l1-checkpoints"

# Automatic cascades (the event bus and the dashboard scheduler start the next step on their
# own): on, unless this file exists. `tools/util/sb-pipeline-ctl.py off` writes it, `on` removes it.
CASCADES_OFF_FLAG = DATA_ROOT / "CASCADES_OFF"


def automatic_cascades_on() -> bool:
    """False when automatic cascades are switched off (CASCADES_OFF_FLAG exists)."""
    try:
        return not CASCADES_OFF_FLAG.exists()
    except OSError:
        return True



CASCADE_RULES: dict[tuple[str, str], str] = {

    ("email", "l0"): "email/em-l1-enrich.py --incremental",
    ("slack", "l0"): "slack/sl-l1-enrich.py --incremental",
    ("slack-dm", "l0"): "slack/sl-l1-enrich.py --incremental",
    ("attio", "l0"): "attio/at-l1-enrich.py",
    ("calendar", "l0"): "cross-source/xs-pipeline-run.py --propagate",
    ("personio", "l0"): "personio/pe-l1-enrich.py",
    ("notion", "l0"): "notion/no-l1-enrich.py",
    ("gdrive", "l0"): "gdrive/gd-l1-enrich.py --incremental",
    ("tactiq", "l0"): "tactiq/tq-l1-enrich.py",
    ("plaud", "l0"): "plaud/pl-l1-enrich.py",
    ("linkedin", "l0"): "linkedin/li-l1-enrich.py --incremental",
    ("docusign", "l0"): "docusign/ds-l1-enrich.py",
    ("voicememos", "l0"): "voice-memos/vm-l1-enrich.py",
    ("whatsapp", "l0"): "whatsapp/wa-l1-enrich.py",
    ("chatgpt", "l0"): "chatgpt/cg-l1-enrich.py",

    ("email", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("slack", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("attio", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("personio", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("notion", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("gdrive", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("tactiq", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("plaud", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("linkedin", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("whatsapp", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("chatgpt", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("docusign", "l1"): "cross-source/xs-pipeline-run.py --propagate",
    ("voicememos", "l1"): "cross-source/xs-pipeline-run.py --propagate",

    ("cross-source", "l2"): "cross-source/xs-l3-graph.py",

    ("knowledge", "l2"): "cross-source/xs-l2-knowledge-extract.py",

    ("nlp", "l3"): "cross-source/xs-l3-shadow-extract.py",
}


CASCADE_DEBOUNCE: dict[str, int] = {
    "slack": 60,
    "slack-dm": 60,
    "email": 120,
    "calendar": 300,
    "attio": 300,
    "default": 300,
}


CASCADE_DEBOUNCE_SECONDS = CASCADE_DEBOUNCE["default"]


CASCADE_DEBOUNCE_FLOOR = 15
CASCADE_DEBOUNCE_CEILING = 600



SCRIPTS_DIR = DATA_ROOT / "scripts"






def _str_list(key: str) -> list[str]:
    value = user_cfg(key, [])
    if isinstance(value, str):
        value = [value]
    return [str(v).strip().lower() for v in value if str(v).strip()]


OWN_EMAILS: set[str] = set(_str_list("own_emails"))


# Your name as messages and transcripts write it, lower case. "owner" is
# always included; add nicknames, initials or spellings in "own_names".
OWN_NAMES_NORMALIZED: set[str] = set(_str_list("own_names")) | (
    {OWNER_NAME.lower()} if OWNER_NAME else set()
)

# Speaker labels that mean you in a transcript ("Alex", "Alex Demo"): your
# names plus your first name alone. Only for speaker labels, never to drop a
# contact (other people can share your first name).
OWNER_SPEAKER_LABELS: frozenset[str] = frozenset(
    OWN_NAMES_NORMALIZED | ({OWNER_FIRST_NAME} if OWNER_FIRST_NAME else set())
)

# Your person id in the knowledge base (p_...), once it exists. Empty = unknown.
OWN_PERSON_ID: str = str(user_cfg("own_person_id", "") or "").strip()

# The node that stands for you in the relationship graph (xs-l3-graph.py and
# the dashboard): your own_person_id when set, otherwise a fixed "p_owner".
OWNER_GRAPH_ID: str = OWN_PERSON_ID or "p_owner"


def owner_name_regex() -> str:
    """A regex alternation of OWNER_SPEAKER_LABELS (longest first), or a pattern
    that never matches when you have not set your name."""
    labels = sorted(OWNER_SPEAKER_LABELS, key=len, reverse=True)
    if not labels:
        return r"(?!x)x"
    return "(?:" + "|".join(re.escape(x) for x in labels) + ")"


def is_owner_speaker(label: str) -> bool:
    """True when a transcript speaker label is you (full name, first name, alias)."""
    if not label:
        return False
    n = " ".join(str(label).strip().lower().split())
    return n in OWNER_SPEAKER_LABELS


def _warn_missing_owner() -> None:
    missing = [k for k in ("owner", "own_emails") if not user_cfg(k)]
    if missing:
        log.warning(
            "sbk.config.json has no %s: SBK cannot tell which messages and voices are "
            "yours until you set it (see sbk.config.example.json)",
            " / ".join(missing),
        )


_warn_missing_owner()




STT_NAME_CORRECTIONS: dict[str, str] = {


}




# Generic nickname -> given name rules, lower case. They name nobody: they only let "bob smith"
# match a known "robert smith" (tools/cross-source/rq_name_matching.py, the shadow-contact
# filter). Ambiguous short forms (sam, alex, max, chris, pat...) are left out on purpose.
GENERIC_NICKNAMES: dict[str, str] = {
    "andy": "andrew",
    "ben": "benjamin",
    "bill": "william",
    "billy": "william",
    "bob": "robert",
    "bobby": "robert",
    "dave": "david",
    "jim": "james",
    "jimmy": "james",
    "joe": "joseph",
    "kate": "katherine",
    "liz": "elizabeth",
    "matt": "matthew",
    "mike": "michael",
    "nick": "nicholas",
    "rob": "robert",
    "steve": "stephen",
    "tom": "thomas",
    "tony": "anthony",
    "beppe": "giuseppe",
    "peppe": "giuseppe",
    "gianni": "giovanni",
    "gigi": "luigi",
    "sandro": "alessandro",
}


def _alias_map(raw, where: str) -> dict[str, str]:
    """{"nickname": "full name"} cleaned to lower case with single spaces; bad entries are skipped."""
    if not isinstance(raw, dict):
        if raw:
            log.warning("%s must be an object {\"nickname\": \"full name\"}: ignored", where)
        return {}
    out = {}
    for k, v in raw.items():
        nick, full = " ".join(str(k).lower().split()), " ".join(str(v or "").lower().split())
        if nick and full and not nick.startswith("_"):
            out[nick] = full
    return out


# The people YOU call by a nickname or a handle: {"nickname": "full name"}, lower case.
# They come from sbk.config.json "nickname_aliases", plus the aliases added on the
# dashboard's Shadows page (shadow-filters.json, loaded below). Nothing is built in.
CONFIG_NICKNAME_ALIASES: dict[str, str] = _alias_map(
    user_cfg("nickname_aliases", {}), "sbk.config.json nickname_aliases"
)
NICKNAME_ALIASES: dict[str, str] = dict(CONFIG_NICKNAME_ALIASES)


SHADOW_FILTERS_FILE = DATA_ROOT / "shadow-filters.json"


def _load_shadow_filter_aliases() -> dict[str, str]:
    ""
    if not SHADOW_FILTERS_FILE.exists():
        return {}
    try:
        import json as _json

        data = _json.loads(SHADOW_FILTERS_FILE.read_text())
        return _alias_map(data.get("aliases", {}), "shadow-filters.json aliases")
    except (ValueError, OSError, AttributeError):
        return {}


NICKNAME_ALIASES.update(_load_shadow_filter_aliases())



NOISE_DOMAINS: set[str] = {

    "ats-vendor.example",
    "hr-vendor.example",
    "personio.com",
    "hr-vendor-2.example",
    "pipedrive.com",
    "linear.app",

    "docusign.net",
    "esign-vendor.example",
    "pandadoc.com",
    "pandadoc.net",

    "notion.so",
    "slack.com",
    "github.com",
    "intercom.io",
    "intercom-mail.com",
    "slack-mail.com",

    "mailchimp.com",
    "sendinblue.com",
    "hubspot.com",
    "hubspotemail.net",
    "hubspotstarter.net",
    "mailgun.org",
    "sendgrid.net",
    "mandrillapp.com",
    "campaign-archive.com",
    "list-manage.com",
    "beehiiv.com",
    "substack.com",
    "medium.com",
    "buffermail.com",
    "mailjet.com",
    "customer.io",
    "lemlist-news.com",

    "notifications.google.com",
    "google.com",
    "docs.google.com",
    "googleapis.com",
    "calendar-notification",

    "amazonaws.com",
    "mailer-daemon",
    "postmaster",

    "meetup.com",
    "eventbrite.com",

    "facebookmail.com",
    "support.facebook.com",

    "calendly.com",
    "jotform.com",
    "typeform.com",

    "stripe.com",
    "shopify.com",

    "ghost.io",
    "dashlane.com",

    # Generic placeholder noise domains; extend via user config.
    "noise1.example",
    "noise2.example",
    "noise3.example",
    "reply.noise3.example",
    "noise4.example",
    "noise5.example",
    "noise6.example",
    "noise7.example",

    "support.example",

    "junkmail1.example",
    "junkmail2.example",
    "junkmail3.example",
    "junkmail4.example",
    "junkmail5.example",
    "junkmail6.example",
    "phishing1.example",
    "phishing2.example",

    "gtempaccount.com",
}




# Your own organisations (sbk.config.json "organisations"): the companies and brands you
# run or work for. Empty by default: nothing is treated as internal until you list it.
#   OWN_ORG_DISPLAY_NAMES  names as you wrote them; OWN_ORG_NAMES the same, lower case
#   OWN_ORG_ALIASES        {"other spelling or abbreviation": "Name"}
#   OWN_ORG_DOMAINS        {"Name": ["domain", ...]} when "domains" is given per organisation
#   INTERNAL_DOMAINS       every domain listed (sbk-settings.json "internal_domains_extra" adds more)
OWN_ORG_ALIASES: dict[str, str] = {
    str(k).strip(): str(v).strip()
    for k, v in (user_cfg("organisations.aliases", {}) or {}).items()
    if str(k).strip() and str(v).strip()
}
_org_domains_cfg = user_cfg("organisations.domains", []) or []
OWN_ORG_DOMAINS: dict[str, list[str]] = {}
if isinstance(_org_domains_cfg, dict):
    for _name, _doms in _org_domains_cfg.items():
        _doms = _doms if isinstance(_doms, list) else [_doms]
        OWN_ORG_DOMAINS[str(_name).strip()] = [
            str(d).strip().lower() for d in _doms if str(d).strip()
        ]
    _org_domains_flat = [d for _doms in OWN_ORG_DOMAINS.values() for d in _doms]
else:
    _org_domains_flat = [str(d).strip().lower() for d in _org_domains_cfg if str(d).strip()]
OWN_ORG_DISPLAY_NAMES: list[str] = _labels_from(
    user_cfg("organisations.names", []) or [], OWN_ORG_DOMAINS, OWN_ORG_ALIASES.values()
)
OWN_ORG_NAMES: set[str] = {n.lower() for n in OWN_ORG_DISPLAY_NAMES}
INTERNAL_DOMAINS: set[str] = set(_org_domains_flat)



NOISE_PREFIXES: set[str] = {
    "info",
    "billing",
    "support",
    "marketing",
    "team",
    "hello",
    "hr",
    "recruiting",
    "admin",
    "administration",
    "sales",
    "newsletter",
    "contact",
}





NOISE_EMAIL_PREFIXES: set[str] = {
    "notifications",
    "notification",
    "noreply",
    "no-reply",
    "no_reply",
    "donotreply",
    "do_not_reply",
    "do-not-reply",
    "donot_reply",
    "bounce",
    "bounce-back",
    "mailer-daemon",
    "postmaster",
    "unsubscribe",
    "tracking",
    "updates",
    "alert",
    "alerts",
    "billing",
    "invoice",
    "newsletter",
    "marketing",
    "marketing_squad",
    "advertise-noreply",
    "comments-noreply",
    "drive-shares-dm-noreply",
    "messages-noreply",
    "notifications-noreply",
    "shipment_notification",
    "order_acknowledgement",
    "monitoring",
    "pkginfo",
    "trackingupdates",
}




NOISE_PREFIXES_PER_DOMAIN: dict[str, set[str]] = {
    "meta.com": {"do_not_reply", "ar", "advertise-noreply"},
    "fb.com": {"donot_reply_ar", "do_not_reply"},
    "linkedin.com": {"notifications-noreply", "messages-noreply", "inmail-hit-reply"},
    "trustpilot.com": {"noreply", "notifications"},
    "superhuman.com": {"reminder", "sharing", "notification"},
}



NOISE_NAMES_PATTERNS: list[str] = [
    "hrvendor",
    "meta for business",
    "customer experience team",
    "staffing agency",
    "linkedin member",

    "calendar invite",
    "calendar notification",
    "tickets",
    "zapier",
    "cookiebot",
    "billing notification",
    "bounce back",
    "miro team",
    "anthropic team",
    "reminder",
    "loom",
    "clickup",
    "zendesk",
    "simple poll",
    "akiflow",
    "translate",
    "perplexity bot",
    "slack bot",
    "slackbot",
    "frontapp",
    "intercom",

    "notion",
    "asana",
    "trello",
    "superhuman",
    "figma",
    "canva",
    "airtable",
    "monday.com",
    "hubspot",
    "salesforce",
    "mailchimp",
    "sendgrid",
    "twilio",
    "stripe",
    "shopify",
    "typeform",
    "calendly",
    "docusign",
    "pandadoc",
    "jotform",
    "ghost",
    "beehiiv",
    "substack",
    "trustpilot",
    "glassdoor",
    "indeed",
    "workday",
    "bamboohr",
    "rippling",
    "gusto",
    "deel",

    # Organization-specific internal mailing-list names (HR, management,
    # department aliases) are not hardcoded. Generic "... team" names are
    # matched by _SERVICE_TEAM_RE and the regexes below; load any extra
    # org-specific noise names from your user config (noise_names_extra).
]




NOISE_NAMES_REGEX: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    # Generic department patterns only. Organization-specific mailing-list
    # patterns load from user config; generic "... team" names are matched
    # by _SERVICE_TEAM_RE.
    for p in [
        r"^security$",
        r"^finance$",
    ]
]




_SERVICE_TEAM_RE = re.compile(
    r"^the\s+.+\s+team$|^.+\s+team$|^team\s+\w+$",
    re.IGNORECASE,
)


COMPANY_SUFFIXES: set[str] = {
    "srl",
    "s.r.l.",
    "ltd",
    "ltd.",
    "gmbh",
    "inc",
    "inc.",
    "llc",
    "spa",
    "s.p.a.",
    "pbc",
    "corp",
    "corp.",
    "ag",
    "sa",
    "bv",
    "b.v.",
    "plc",
    "pty",
    "co",
    "co.",
    "oy",
    "ab",







    "societa benefit",
    "societa' benefit",
    "società benefit",
    "sb",
    "s.r.l",
    "s.p.a",
    "srls",
    "sas",
    "snc",
    "sagl",
    "fzco",
    "fz-llc",
    "fz llc",
    "n.v.",
    "sarl",
}


_SIGLE_IMPARATE: frozenset[str] | None = None


def sigle_societarie() -> frozenset[str]:
    ""


















    global _SIGLE_IMPARATE
    if _SIGLE_IMPARATE is None:
        imparate: set[str] = set()
        f = DATA_ROOT / "knowledge" / "meta" / "vocabolario-sigle.json"
        if f.exists():
            try:
                import json as _json

                imparate = set(_json.loads(f.read_text(encoding="utf-8")).get("imparate", {}))
            except Exception:  # pragma: no cover
                pass
        _SIGLE_IMPARATE = frozenset(imparate | set(COMPANY_SUFFIXES))
    return _SIGLE_IMPARATE






















CONFIDENZE = {"high": 0.85, "medium": 0.60, "low": 0.35}

CONFIDENZA_MEDIA = 0.60
CONFIDENZA_ALTA = 0.85


def confidenza(valore) -> float:
    ""
    if isinstance(valore, int | float) and not isinstance(valore, bool):
        return float(valore)
    return CONFIDENZE.get(str(valore or "").strip().lower(), 0.60)


def confidenza_almeno(colonna, soglia: float = CONFIDENZA_MEDIA):
    ""
    import pandas as pd

    numerica = pd.to_numeric(colonna, errors="coerce")
    parole = colonna.astype(str).str.strip().str.lower().map(CONFIDENZE)
    return numerica.fillna(parole).fillna(0.0) >= soglia


def chiave_organizzazione(nome: str) -> str:
    ""



























    import re as _re
    import unicodedata as _ud

    s = _re.sub(r"\(.*?\)", " ", str(nome or ""))
    s = _ud.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()





    s = s.replace(".", "")
    s = _re.sub(r"[^a-z0-9 ]", " ", s)
    parole = s.split()



    vocabolario = sigle_societarie()
    singole = {x.replace(".", "").replace(" ", "") for x in vocabolario}
    doppie = {x.replace(".", "") for x in vocabolario if " " in x}



    cambiato = True
    while cambiato and parole:
        cambiato = False
        if len(parole) >= 2 and " ".join(parole[-2:]) in doppie:
            del parole[-2:]
            cambiato = True
        elif parole[-1] in singole:
            parole.pop()
            cambiato = True

    return "".join(parole)









SOURCE_REGISTRY: dict[str, dict] = {
    "email": {
        "category": "instant",
        "update_freq": "hourly",
        "download_method": "api_auto",
        "scripts": {"l0": "email/em-l0-download.py", "l1": "email/em-l1-enrich.py"},
        "dependencies": [],
    },
    "slack": {
        "category": "instant",
        "update_freq": "hourly",
        "download_method": "api_auto",
        "scripts": {"l0": "slack/sl-l0-download.py", "l1": "slack/sl-l1-enrich.py"},
        "dependencies": [],
    },
    "whatsapp": {
        "category": "instant",
        "update_freq": "on_demand",
        "download_method": "file_drop",
        "scripts": {"l0": "whatsapp/wa-l0l3-full.py", "l1": "whatsapp/wa-l1-enrich.py"},
        "dependencies": [],
    },
    "calendar": {
        "category": "periodic",
        "update_freq": "daily",
        "download_method": "api_auto",
        "scripts": {"l0": "calendar/ca-l0-download.py"},
        "dependencies": [],
    },
    "attio": {
        "category": "periodic",
        "update_freq": "daily",
        "download_method": "api_auto",
        "scripts": {"l1": "attio/at-l1-enrich.py"},
        "dependencies": [],
    },
    "notion": {
        "category": "periodic",
        "update_freq": "daily",
        "download_method": "api_auto",
        "scripts": {"l0": "notion/no-l0-download.py", "l1": "notion/no-l1-enrich.py"},
        "dependencies": [],
    },
    "gdrive": {
        "category": "periodic",
        "update_freq": "daily",
        "download_method": "api_auto",
        "scripts": {"l0": "gdrive/gd-l0-download.py", "l1": "gdrive/gd-l1-enrich.py"},
        "dependencies": [],
    },
    "personio": {
        "category": "periodic",
        "update_freq": "weekly",
        "download_method": "api_auto",
        "scripts": {"l0": "personio/pe-l0-download.py", "l1": "personio/pe-l1-enrich.py"},
        "dependencies": [],
    },
    "tactiq": {
        "category": "meeting",
        "update_freq": "weekly",
        "download_method": "browser_session",
        "scripts": {"l0": "tactiq/tq-l0-download.py", "l1": "tactiq/tq-l1-enrich.py"},
        "dependencies": [],
    },
    "plaud": {
        "category": "meeting",
        "update_freq": "on_demand",
        "download_method": "app_session",
        "scripts": {"l0": "plaud/pl-l0-download.py", "l1": "plaud/pl-l1-enrich.py"},
        "dependencies": [],
    },
    "linkedin": {
        "category": "spot",
        "update_freq": "on_demand",
        "download_method": "file_drop",
        "scripts": {"l0": "linkedin/li-l0-import-export.py", "l1": "linkedin/li-l1-enrich.py"},
        "dependencies": [],
    },
    "docusign": {
        "category": "spot",
        "update_freq": "on_demand",
        "download_method": "api_manual",
        "scripts": {"l0": "docusign/ds-l0-api.py", "l1": "docusign/ds-l1-enrich.py"},
        "dependencies": [],
    },
    "chatgpt": {
        "category": "spot",
        "update_freq": "on_demand",
        "download_method": "file_drop",
        "scripts": {"l1": "chatgpt/cg-l1-enrich.py"},
        "dependencies": [],
    },
    "iphone": {
        "category": "spot",
        "update_freq": "on_demand",
        "download_method": "file_drop",
        "scripts": {},
        "dependencies": [],
    },
    "voicememos": {
        "category": "spot",
        "update_freq": "on_demand",
        "download_method": "file_drop",
        "scripts": {"l0": "voice-memos/vm-l0-transcribe.py", "l1": "voice-memos/vm-l1-enrich.py"},
        "dependencies": [],
    },
    "cross-source": {
        "category": "periodic",
        "update_freq": "daily",
        "download_method": "api_auto",
        "scripts": {},
        "dependencies": ["email", "slack", "attio", "personio", "linkedin", "whatsapp"],
    },
    "attio_calls": {
        "category": "meeting",
        "update_freq": "daily",
        "download_method": "api_auto",
        "scripts": {},
        "dependencies": ["attio"],
    },
    "tactiq_meetings": {
        "category": "meeting",
        "update_freq": "weekly",
        "download_method": "browser_scrape",
        "scripts": {},
        "dependencies": ["tactiq"],
    },
}




def is_own_email(email: str) -> bool:
    ""
    if not email:
        return False
    return email.strip().lower() in OWN_EMAILS


def is_own_name(name: str) -> bool:
    ""












    if not name:
        return False
    return name.strip().lower() in OWN_NAMES_NORMALIZED


def is_noise_domain(domain: str) -> bool:
    ""
    if not domain:
        return False
    d = domain.strip().lower()
    return any(noise in d for noise in NOISE_DOMAINS)


def is_bot_or_service(name: str) -> bool:
    ""













    if not name or not isinstance(name, str):
        return False
    n = name.strip()
    if not n:
        return False
    nl = n.lower()


    if any(pattern in nl for pattern in NOISE_NAMES_PATTERNS):
        return True


    if any(rx.search(nl) for rx in NOISE_NAMES_REGEX):
        return True


    if nl.endswith(" bot") or nl.endswith(" team"):
        return True


    if _SERVICE_TEAM_RE.match(nl):
        return True


    if "@" in n:
        return True


    if nl.startswith("deactivateduser"):
        return True


    if " " not in n and n.isupper() and len(n) >= 3:
        return True


    if "=" in n:
        return True


    if "unsubscribe" in nl:
        return True


    if len(n) > 60:
        return True

    return False


def is_gibberish_name(name: str) -> bool:
    ""












    if not name or not isinstance(name, str):
        return False
    n = name.strip()
    if not n or len(n) < 6:
        return False


    if " " in n:
        return False


    if n.isupper() and len(n) <= 5:
        return False


    if not n.isalpha():
        return False

    nl = n.lower()
    vowels = sum(1 for c in nl if c in "aeiou")
    ratio = vowels / len(nl)




    if ratio < 0.1:
        return True




    consonant_run = 0
    max_consonant_run = 0
    for c in nl:
        if c not in "aeiou":
            consonant_run += 1
            max_consonant_run = max(max_consonant_run, consonant_run)
        else:
            consonant_run = 0

    if max_consonant_run >= 5 and ratio < 0.4:
        return True

    return False


def is_non_human_node(name: str, email: str = "", score: float = 0) -> bool:
    ""















    if not name or not isinstance(name, str) or not name.strip():
        return True

    name_stripped = name.strip()


    if is_bot_or_service(name_stripped):
        return True


    if is_gibberish_name(name_stripped):
        return True


    name_lower = name_stripped.lower()
    name_parts = name_lower.split()
    if name_parts:
        last_word = name_parts[-1].rstrip(".,")
        if last_word in COMPANY_SUFFIXES:
            return True

        if last_word.replace(".", "") in {s.replace(".", "") for s in COMPANY_SUFFIXES}:
            return True

    return False


def extract_name_from_email(email: str) -> str | None:
    ""











    if not email or not isinstance(email, str) or "@" not in email:
        return None

    local = email.split("@")[0].lower()


    for sep in (".", "_", "-"):
        if sep in local:
            parts = local.split(sep)
            if len(parts) == 2 and all(p.isalpha() and len(p) >= 2 for p in parts):
                return f"{parts[0].title()} {parts[1].title()}"

    return None


def is_role_address(email: str) -> bool:
    ""




    if not email or not isinstance(email, str) or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    role_prefixes = {
        "info",
        "support",
        "hello",
        "team",
        "billing",
        "sales",
        "admin",
        "contact",
        "office",
        "help",
        "service",
        "segreteria",
        "amministrazione",
        "contabilita",
        "hr",
        "finance",
        "marketing",
        "newsletter",
        "events",
        "press",
        "media",
        "legal",
    }
    if local in role_prefixes:
        return True

    return any(
        local.startswith(p + ".") or local.startswith(p + "_") or local.startswith(p + "-")
        for p in role_prefixes
    )


def is_noise_email_prefix(email: str) -> bool:
    ""



    if not email or not isinstance(email, str) or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    domain = email.split("@")[1].lower()


    if domain in INTERNAL_DOMAINS:
        return False

    return local in NOISE_EMAIL_PREFIXES


def is_noise_per_domain(email: str) -> bool:
    ""




    if not email or not isinstance(email, str) or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    domain = email.split("@")[1].lower()

    prefixes = NOISE_PREFIXES_PER_DOMAIN.get(domain)
    if prefixes and local in prefixes:
        return True
    return False


def is_internal_domain(domain: str) -> bool:
    ""
    if not domain:
        return False
    return domain.strip().lower() in INTERNAL_DOMAINS





def _load_runtime_settings():
    ""




    import json as _json

    settings_path = DATA_ROOT / "sbk-settings.json"
    if not settings_path.exists():
        return

    try:
        data = _json.loads(settings_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return

    if not isinstance(data, dict):
        return


    cascade = data.get("cascade_debounce")
    if isinstance(cascade, dict):
        for key, val in cascade.items():
            if isinstance(val, (int, float)):  # noqa: UP038 — 3.10+, breaks on the system python 3.9
                CASCADE_DEBOUNCE[key] = int(val)


    extra_noise = data.get("noise_domains_extra")
    if isinstance(extra_noise, list):
        for d in extra_noise:
            if isinstance(d, str) and d.strip():
                NOISE_DOMAINS.add(d.strip().lower())


    extra_internal = data.get("internal_domains_extra")
    if isinstance(extra_internal, list):
        for d in extra_internal:
            if isinstance(d, str) and d.strip():
                INTERNAL_DOMAINS.add(d.strip().lower())


_load_runtime_settings()






LAST_RUNS_FILE = DATA_ROOT / "last-runs.json"


def mark_last_run(source: str) -> None:
    ""




    import fcntl
    import json as _json
    from datetime import datetime as _dt





    LAST_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_RUNS_FILE.with_name(LAST_RUNS_FILE.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data: dict = {}
        if LAST_RUNS_FILE.exists():
            try:
                data = _json.loads(LAST_RUNS_FILE.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        data[source] = _dt.now().isoformat()
        tmp = LAST_RUNS_FILE.with_name(f"{LAST_RUNS_FILE.name}.{os.getpid()}.tmp")
        tmp.write_text(_json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, LAST_RUNS_FILE)


def get_last_run(source: str):
    ""



    import json as _json
    from datetime import datetime as _dt

    if not LAST_RUNS_FILE.exists():
        return None
    try:
        data = _json.loads(LAST_RUNS_FILE.read_text(encoding="utf-8"))
        ts = data.get(source)
        if ts:
            return _dt.fromisoformat(ts)
    except (ValueError, OSError, KeyError):
        pass
    return None







def _compute_content_hash(path: Path) -> str:
    ""





    import hashlib

    try:
        st = path.stat()
        h = hashlib.md5(str(st.st_size).encode(), usedforsecurity=False)
        with open(path, "rb") as f:
            h.update(f.read(4096))
        return h.hexdigest()
    except OSError:
        return ""


def _collect_fingerprints(paths: list[Path]) -> dict[str, dict]:
    ""




    fingerprints: dict[str, dict] = {}
    for p in paths:
        if not p.exists():
            fingerprints[str(p)] = {"mtime": 0.0, "hash": ""}
        elif p.is_file():
            fingerprints[str(p)] = {
                "mtime": p.stat().st_mtime,
                "hash": _compute_content_hash(p),
            }
        elif p.is_dir():
            max_mtime = 0.0
            for f in p.rglob("*"):
                if f.is_file():
                    mt = f.stat().st_mtime
                    if mt > max_mtime:
                        max_mtime = mt
            fingerprints[str(p)] = {"mtime": max_mtime, "hash": ""}
    return fingerprints


def _collect_mtimes(paths: list[Path]) -> dict[str, float]:
    ""



    mtimes: dict[str, float] = {}
    for p in paths:
        if not p.exists():
            mtimes[str(p)] = 0.0
        elif p.is_file():
            mtimes[str(p)] = p.stat().st_mtime
        elif p.is_dir():
            max_mtime = 0.0
            for f in p.rglob("*"):
                if f.is_file():
                    mt = f.stat().st_mtime
                    if mt > max_mtime:
                        max_mtime = mt
            mtimes[str(p)] = max_mtime
    return mtimes


def check_inputs_changed(checkpoint_name: str, input_paths: list[Path]) -> bool:
    ""




    import json as _json

    ckpt_file = L1_CHECKPOINT_DIR / f"{checkpoint_name}-input-mtime.json"
    current_fp = _collect_fingerprints(input_paths)

    if ckpt_file.exists():
        try:
            saved_data = _json.loads(ckpt_file.read_text(encoding="utf-8"))


            if "fingerprints" in saved_data:
                saved_fp = saved_data["fingerprints"]
                if current_fp == saved_fp:
                    return False

                for path_key, cur in current_fp.items():
                    saved = saved_fp.get(path_key)
                    if saved and cur["mtime"] == saved["mtime"] and cur["hash"] != saved["hash"]:
                        if cur["hash"] and saved["hash"]:
                            log.warning(
                                f"Checkpoint {checkpoint_name}: {path_key} mtime unchanged "
                                f"but content hash differs — treating as changed"
                            )
                return True


            saved_mtimes = saved_data.get("mtimes", {})
            current_mtimes = {k: v["mtime"] for k, v in current_fp.items()}
            if current_mtimes == saved_mtimes:
                return False
        except (ValueError, OSError):
            pass
    return True


def save_input_checkpoint(checkpoint_name: str, input_paths: list[Path]) -> None:
    ""
    import json as _json
    from datetime import datetime as _dt

    ckpt_file = L1_CHECKPOINT_DIR / f"{checkpoint_name}-input-mtime.json"
    ckpt_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fingerprints": _collect_fingerprints(input_paths),
        "timestamp": _dt.now(UTC).isoformat(),
    }
    ckpt_file.write_text(_json.dumps(data, indent=2), encoding="utf-8")

























def percorso_sidecar(percorso) -> Path:
    ""
    p = Path(percorso)
    return p.with_name(p.name + ".meta.json")


def scrivi_sidecar_schema(percorso, versione: str, **extra) -> Path:
    ""




    meta = {
        "schema_version": str(versione),
        "scritto_da": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "unknown",
        "quando": datetime.now(UTC).isoformat(),
        **extra,
    }
    dove = percorso_sidecar(percorso)
    safe_write_json(dove, meta)
    return dove


def leggi_sidecar_schema(percorso) -> str | None:
    ""




    try:
        d = json.loads(percorso_sidecar(percorso).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    v = d.get("schema_version")
    return str(v) if v else None















REGISTRO_RIPARAZIONI = L3_DIR / "meta" / "riparazioni.json"


def registra_riparazione(nome: str, *, sintomo=None, quando: str | None = None, **extra) -> Path:
    ""













    try:
        registro = json.loads(REGISTRO_RIPARAZIONI.read_text(encoding="utf-8"))
        if not isinstance(registro, dict):
            registro = {}
    except (OSError, ValueError, TypeError):
        registro = {}
    registro[str(nome)] = {
        "quando": quando or datetime.now(UTC).isoformat(),


        "data_ricostruita": bool(quando),
        "sintomo_allora": sintomo,
        **extra,
    }
    safe_write_json(REGISTRO_RIPARAZIONI, registro)
    return REGISTRO_RIPARAZIONI





_BACKUP_FALLITI: dict[str, int] = {}


def backup_falliti() -> dict[str, int]:
    ""





    return dict(_BACKUP_FALLITI)


def _riepilogo_backup_falliti() -> None:




    if not _BACKUP_FALLITI:
        return
    try:
        sys.stderr.write(
            f"⚠️  pre-image (.backup) failed {sum(_BACKUP_FALLITI.values())} times "
            f"in this process: {_BACKUP_FALLITI}\n"
        )
    except (ValueError, OSError):  # pragma: no cover - stderr already closed
        pass


atexit.register(_riepilogo_backup_falliti)


def _backup_file(p: Path, keep: int = 3) -> None:
    ""













    import shutil as _shutil
    from datetime import datetime as _dt_local

    backup_dir = p.parent / ".backup"
    try:
        backup_dir.mkdir(exist_ok=True)
    except OSError as exc:
        _BACKUP_FALLITI[f"mkdir:{type(exc).__name__}"] = (
            _BACKUP_FALLITI.get(f"mkdir:{type(exc).__name__}", 0) + 1
        )
        log.warning("pre-image NOT created for %s: the .backup folder cannot be created (%s)", p, exc)
        return
    ts = _dt_local.now(UTC).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"{p.name}.{ts}"
    try:
        _shutil.copy2(p, dest)
        os.chmod(dest, 0o600)
    except OSError as exc:
        chiave = f"copy:{type(exc).__name__}"
        _BACKUP_FALLITI[chiave] = _BACKUP_FALLITI.get(chiave, 0) + 1
        log.warning("pre-image NOT created for %s (%s): the write continues WITHOUT a safety net", p, exc)
        return

    backups = sorted(backup_dir.glob(f"{p.name}.*"))
    for old in backups[:-keep]:
        try:
            log.debug("Removing old backup: %s", old)
            old.unlink()
        except OSError as exc:
            chiave = f"unlink:{type(exc).__name__}"
            _BACKUP_FALLITI[chiave] = _BACKUP_FALLITI.get(chiave, 0) + 1
            log.warning("old pre-image not removed (%s): %s", old, exc)


def safe_write_parquet(df, path, **kwargs) -> Path:
    ""






    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.exists():
        _backup_file(p, keep=3)

    tmp = p.with_name(p.name + ".tmp")
    try:
        df.to_parquet(tmp, **kwargs)
        tmp.rename(p)
    except Exception:

        if tmp.exists():
            tmp.unlink(missing_ok=True)
        log.error("Failed to write parquet: %s", p)
        raise
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    log.info("Wrote %d rows to %s", len(df), p)
    return p


def safe_write_json(
    path,
    data,
    *,
    indent=2,
    ensure_ascii=False,
    backup=False,
    fsync=False,
):
    ""








    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=str)
    if backup and p.exists():
        _backup_file(p, keep=3)
    tmp = p.with_name(p.name + ".tmp")







    fatto = False
    try:
        if fsync:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
        else:
            tmp.write_text(content, encoding="utf-8")
        tmp.rename(p)
        fatto = True
    finally:
        if not fatto and tmp.exists():
            tmp.unlink(missing_ok=True)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def safe_write_text(path, text, *, encoding="utf-8", mode=0o600, fsync=False):
    ""




















    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")




    fatto = False
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            if isinstance(text, str):
                fh.write(text)
            else:
                for pezzo in text:
                    fh.write(pezzo)
            if fsync:
                fh.flush()
                os.fsync(fh.fileno())
        os.replace(tmp, str(p))
        fatto = True
    finally:
        if not fatto and os.path.exists(tmp):
            os.unlink(tmp)
    if mode is not None:
        try:
            os.chmod(p, mode)
        except OSError:
            pass
    return p






def get_auto_since(source: str, overlap_days: int = 2) -> str:
    ""








    from datetime import timedelta

    last = get_last_run(source)
    if last:
        since = last - timedelta(days=overlap_days)
        return since.strftime("%Y-%m-%d")
    return "2020-01-01"


def load_record_hashes(source: str) -> dict:
    ""








    import json as _json

    path = DATA_ROOT / source / "record-hashes.json"
    if path.exists():
        try:
            return _json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def save_record_hashes(source: str, hashes: dict) -> None:
    ""





    import json as _json

    path = DATA_ROOT / source / "record-hashes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")


def compute_record_hash(data: dict) -> str:
    ""









    import hashlib
    import json as _json

    return hashlib.md5(_json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def load_conversations_cache() -> dict | None:
    ""




    import json as _json
    from datetime import datetime as _dt

    cache_path = DATA_ROOT / "slack" / "conversations-cache.json"
    if not cache_path.exists():
        return None
    try:
        data = _json.loads(cache_path.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at")
        if cached_at:
            age_hours = (
                _dt.now(UTC) - _dt.fromisoformat(cached_at).replace(tzinfo=UTC)
            ).total_seconds() / 3600
            if age_hours < 24:
                return data
    except (ValueError, OSError, KeyError):
        pass
    return None


def save_conversations_cache(channels: list[dict]) -> None:
    ""




    import json as _json
    from datetime import datetime as _dt

    cache_path = DATA_ROOT / "slack" / "conversations-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cached_at": _dt.now(UTC).isoformat(),
        "channel_count": len(channels),
        "channels": channels,
    }
    cache_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")






EVENT_WATERMARKS_FILE = DATA_ROOT / "event-watermarks.json"
EVENT_VELOCITY_FILE = DATA_ROOT / "event-velocity.json"


def load_event_watermarks() -> dict:
    ""




    import json as _json

    if EVENT_WATERMARKS_FILE.exists():
        try:
            return _json.loads(EVENT_WATERMARKS_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def save_event_watermark(source: str, stage: str, ts: str, count: int) -> None:
    ""







    import json as _json
    from datetime import datetime as _dt


    EVENT_WATERMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = EVENT_WATERMARKS_FILE.with_suffix(".lock")
    with open(lock_path, "w") as lock_fd:
        try:
            import fcntl

            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass

        watermarks = load_event_watermarks()
        key = f"{source}-{stage}"
        prev = watermarks.get(key, {})
        watermarks[key] = {
            "ts": ts,
            "count": prev.get("count", 0) + count,
            "updated": _dt.now(UTC).isoformat(),
        }
        EVENT_WATERMARKS_FILE.write_text(
            _json.dumps(watermarks, indent=2, sort_keys=True), encoding="utf-8"
        )


def get_event_watermark(source: str, stage: str) -> str | None:
    ""




    watermarks = load_event_watermarks()
    entry = watermarks.get(f"{source}-{stage}")
    if entry:
        return entry.get("ts")
    return None







def get_event_velocity(source: str) -> dict:
    ""




    import json as _json

    if not EVENT_VELOCITY_FILE.exists():
        return {"count": 0, "window_start": None, "last_event": None}
    try:
        data = _json.loads(EVENT_VELOCITY_FILE.read_text(encoding="utf-8"))
        return data.get(source, {"count": 0, "window_start": None, "last_event": None})
    except (ValueError, OSError):
        return {"count": 0, "window_start": None, "last_event": None}


def record_event_velocity(source: str) -> None:
    ""
    import json as _json
    from datetime import datetime, timedelta

    data: dict = {}
    if EVENT_VELOCITY_FILE.exists():
        try:
            data = _json.loads(EVENT_VELOCITY_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}

    now = datetime.now(UTC).isoformat()
    window_start_cutoff = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()

    entry = data.get(source, {"count": 0, "window_start": now, "last_event": now})


    if entry.get("window_start", now) < window_start_cutoff:
        entry = {"count": 1, "window_start": now, "last_event": now}
    else:
        entry["count"] = entry.get("count", 0) + 1
        entry["last_event"] = now

    data[source] = entry
    EVENT_VELOCITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENT_VELOCITY_FILE.write_text(_json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")




_interaction_weights_cache: dict | None = None


def load_interaction_weights() -> dict:
    ""
    global _interaction_weights_cache
    if _interaction_weights_cache is not None:
        return _interaction_weights_cache

    import json as _json

    if INTERACTION_WEIGHTS_FILE.exists():
        try:
            data = _json.loads(INTERACTION_WEIGHTS_FILE.read_text(encoding="utf-8"))
            _interaction_weights_cache = {k: v for k, v in data.items() if k != "_meta"}
            return _interaction_weights_cache
        except (ValueError, OSError) as exc:
            log.warning("Failed to load interaction weights: %s", exc)


    _interaction_weights_cache = {
        "email": {
            "direct_1to1": 1.0,
            "reply_substantive": 0.8,
            "small_group_2to5": 0.5,
            "reply_all_substantive": 0.3,
            "cc": 0.1,
            "bcc": 0.05,
            "mass_10plus": 0.02,
            "newsletter_mailinglist": 0.0,
        },
        "calendar": {
            "meeting_1to1": 1.0,
            "meeting_1to1_recurring": 1.2,
            "small_group_3to5": 0.7,
            "working_session": 0.8,
            "large_meeting_10plus": 0.1,
            "one_time_never_repeated": 0.3,
        },
        "slack": {
            "dm_1to1": 0.8,
            "thread_reply_small_channel": 0.5,
            "mention": 0.4,
            "channel_large": 0.1,
            "reaction_emoji": 0.05,
            "bot_automated": 0.0,
        },
        "plaud_tactiq": {"call_1to1": 1.0, "call_small_group": 0.7, "call_large_passive": 0.1},
        "attio": {"note_about_person": 0.6, "meeting_recorded": 0.8},
    }
    return _interaction_weights_cache


def get_interaction_weight(source: str, interaction_type: str) -> float:
    ""
    weights = load_interaction_weights()
    return weights.get(source, {}).get(interaction_type, 0.0)


_decay_config_cache: dict | None = None


def load_decay_config() -> dict:
    ""
    global _decay_config_cache
    if _decay_config_cache is not None:
        return _decay_config_cache

    import json as _json

    if RELATIONSHIP_DECAY_FILE.exists():
        try:
            data = _json.loads(RELATIONSHIP_DECAY_FILE.read_text(encoding="utf-8"))
            _decay_config_cache = {k: v for k, v in data.items() if k != "_meta"}
            return _decay_config_cache
        except (ValueError, OSError) as exc:
            log.warning("Failed to load decay config: %s", exc)

    _decay_config_cache = {
        "half_life_days": {"default": 30},
        "state_thresholds": {
            "active_max_gap_multiplier": 2.0,
            "cooling_max_gap_multiplier": 5.0,
            "dormant_above": 5.0,
        },
        "reactivation_min_interactions": 3,
        "reactivation_window_days": 30,
    }
    return _decay_config_cache


def get_half_life(relationship_type: str) -> int:
    ""
    config = load_decay_config()
    hl = config.get("half_life_days", {})
    return hl.get(relationship_type, hl.get("default", 30))


def compute_expected_cadence(
    interaction_dates: list,
    window_days: int = 365,
) -> float:
    ""








    from datetime import timedelta

    if len(interaction_dates) < 2:
        return float("inf")

    sorted_dates = sorted(interaction_dates)
    cutoff = sorted_dates[-1] - timedelta(days=window_days)
    recent = [d for d in sorted_dates if d >= cutoff]

    if len(recent) < 2:
        return float("inf")

    gaps = []
    for i in range(1, len(recent)):
        delta = (recent[i] - recent[i - 1]).total_seconds() / 86400.0
        gaps.append(delta)

    return sum(gaps) / len(gaps) if gaps else float("inf")






_active_lock_fds: dict[str, object] = {}


def acquire_pid_lock(name: str, *, logger: logging.Logger | None = None) -> bool:
    ""




    lock_path = DATA_ROOT / f"{name}.pid"
    # A data root that does not exist yet (first run, a fresh SBK_DATA_ROOT) must not
    # turn into a FileNotFoundError when the pid file is written.
    lock_path.parent.mkdir(parents=True, exist_ok=True)


    if lock_path.exists():
        try:
            old_pid = int(lock_path.read_text().strip())
            os.kill(old_pid, 0)

            msg = f"[{name}] Another instance running (PID {old_pid}). Skipping."
            if logger:
                logger.warning(msg)
            else:
                print(msg, file=sys.stderr)
            return False
        except ProcessLookupError:

            lock_path.unlink(missing_ok=True)
        except ValueError:

            lock_path.unlink(missing_ok=True)
        except PermissionError:

            return False


    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:

        return False










    try:
        import fcntl

        lock_dir = DATA_ROOT / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        flock_path = lock_dir / f"{name}.lock"
        fd = open(flock_path, "w")  # noqa: SIM115
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.set_inheritable(fd.fileno(), False)
            _active_lock_fds[name] = fd
        except BlockingIOError:

            fd.close()
            lock_path.unlink(missing_ok=True)
            msg = f"[{name}] Another instance holds the lock. Skipping."
            if logger:
                logger.warning(msg)
            else:
                print(msg, file=sys.stderr)
            return False
        except OSError:


            fd.close()
    except ImportError:
        pass

    atexit.register(lambda: release_pid_lock(name))
    return True


def release_pid_lock(name: str) -> None:
    ""

    fd = _active_lock_fds.pop(name, None)
    if fd is not None:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except (ImportError, OSError):
            pass

    try:
        (DATA_ROOT / f"{name}.pid").unlink(missing_ok=True)
    except OSError:
        pass


















# The repository root (the folder that holds tools/).
REPO_ROOT = Path(__file__).resolve().parent.parent


def scrivi_atomico(percorso, testo: str) -> None:
    ""











    import os
    import tempfile
    from pathlib import Path

    p = Path(percorso)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(testo)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
