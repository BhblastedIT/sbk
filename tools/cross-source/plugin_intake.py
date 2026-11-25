"""Generic intake for plugins that have no dedicated slot in the kernel.

A plugin that is not mail, calendar or address book can hand its data to the
kernel by writing two parquet files, and nothing in the kernel has to change:

    $DATA_ROOT/<plugin>/processed/plugin-contacts.parquet       one row per person
    $DATA_ROOT/<plugin>/processed/plugin-interactions.parquet   one row per event

plugin-contacts.parquet columns
    source        plugin id (empty = the <plugin> folder name)
    name          full name, may be empty if email or phone is there
    email         may be empty; "Display Name <address>" is accepted, a value
                  that is not an address (a login, a handle) is blanked
    phone         may be empty, any format (normalised by the kernel)
    company       may be empty
    title         job title or role, may be empty
    first_seen    ISO 8601 timestamp of the first interaction, may be empty
    last_seen     ISO 8601 timestamp of the last interaction, may be empty
    interactions  int, how many interactions you had with this person
    url           link to the person in the source app, may be empty

plugin-interactions.parquet columns
    source        plugin id (empty = the <plugin> folder name)
    ts            ISO 8601 timestamp of the event
    kind          meeting | issue | pr | review | message | record
    title         short title of the event
    text          body, may be empty
    participants  the other people, '|||'-joined emails, names or
                  "Name <address>" (a list column is accepted too)
    owner_role    your role: organizer | assignee | author | attendee | other
    due           ISO 8601 due date, may be empty
    url           link to the event in the source app, may be empty
    status        OPTIONAL. open | done (also: closed, merged, cancelled).
                  When it is missing every row counts as open, so an
                  assigned or dated item never closes: write it whenever the
                  source knows that an item is closed (one warning per file
                  otherwise).

Who reads them
    tools/cross-source/xs-l2-merge.py              contacts, matched by email,
                                                   then phone, then name
    tools/cross-source/xs-l2-knowledge-extract.py  person facts and commitments
                                                   (source "plugins")

A missing file is a no-op. A file with a required column missing is skipped
with one warning line, never a crash. A plugin left out of a non-empty
`enabled_sources` in sbk.config.json is skipped too.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger("sbk.plugin-intake")

CONTACTS_FILE = "plugin-contacts.parquet"
INTERACTIONS_FILE = "plugin-interactions.parquet"

CONTACT_COLUMNS: tuple[str, ...] = (
    "source",
    "name",
    "email",
    "phone",
    "company",
    "title",
    "first_seen",
    "last_seen",
    "interactions",
    "url",
)
INTERACTION_COLUMNS: tuple[str, ...] = (
    "source",
    "ts",
    "kind",
    "title",
    "text",
    "participants",
    "owner_role",
    "due",
    "url",
)
# A file must have at least these; the others are filled with empty values.
CONTACT_REQUIRED: frozenset[str] = frozenset({"name", "email"})
INTERACTION_REQUIRED: frozenset[str] = frozenset({"ts", "kind", "title", "participants"})

KINDS: frozenset[str] = frozenset({"meeting", "issue", "pr", "review", "message", "record"})
OWNER_ROLES: frozenset[str] = frozenset({"organizer", "assignee", "author", "attendee", "other"})
CLOSED_STATUSES: frozenset[str] = frozenset(
    {"done", "closed", "merged", "cancelled", "canceled", "resolved", "completed"}
)
PARTICIPANT_SEP = "|||"

# One address, or "Display Name <address>". Anything else in an email field
# (a login, a handle) is not an email and is blanked, never used as a key.
_EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
_NAMED_EMAIL_RE = re.compile(r"^\s*\"?([^\"<>]*?)\"?\s*<\s*([^<>\s]+@[^<>\s]+)\s*>\s*$")

# Contact rows that only come from interaction participants carry this flag,
# so the knowledge layer never coins a person out of a bare participant.
FROM_PARTICIPANTS = "from_participants"


def data_root(root: Path | str | None = None) -> Path:
    """The data root: the argument, else sbk_config.DATA_ROOT read now."""
    if root is not None:
        return Path(root)
    import sbk_config

    return Path(sbk_config.DATA_ROOT)


def _enabled(plugin: str) -> bool:
    try:
        import sbk_config

        return sbk_config.source_enabled(plugin)
    except Exception:  # noqa: BLE001 - config unreadable: keep the old behaviour
        return True


def plugin_key(plugin_id: str) -> str:
    """A plugin id usable inside a fact attribute: lowercase, [a-z0-9_]."""
    return re.sub(r"[^a-z0-9]+", "_", str(plugin_id or "").strip().lower()).strip("_") or "plugin"


def contact_files(root: Path | str | None = None) -> list[Path]:
    """Every $DATA_ROOT/*/processed/plugin-contacts.parquet, sorted."""
    base = data_root(root)
    if not base.is_dir():
        return []
    return sorted(base.glob(f"*/processed/{CONTACTS_FILE}"))


def interaction_files(root: Path | str | None = None) -> list[Path]:
    """Every $DATA_ROOT/*/processed/plugin-interactions.parquet, sorted."""
    base = data_root(root)
    if not base.is_dir():
        return []
    return sorted(base.glob(f"*/processed/{INTERACTIONS_FILE}"))


def _plugin_of(path: Path) -> str:
    # <root>/<plugin>/processed/<file>
    return path.parent.parent.name


def _clean_str(series: pd.Series) -> pd.Series:
    s = series.astype("string").fillna("").str.strip()
    return s.mask(s.str.lower().isin({"nan", "none", "nat", "<na>", "null"}), "").astype(object)


def parse_person(value) -> tuple[str, str]:
    """'Bo Demo <BO@x.example>' -> ('Bo Demo', 'bo@x.example'); 'bo@x.example' -> ('', 'bo@x.example');
    'Bo Demo' -> ('Bo Demo', ''). A value that looks like neither an address nor a
    'Name <address>' pair is returned as a name."""
    v = str(value or "").strip()
    if not v:
        return "", ""
    m = _NAMED_EMAIL_RE.match(v)
    if m and _EMAIL_RE.match(m.group(2)):
        return m.group(1).strip(), m.group(2).lower()
    if _EMAIL_RE.match(v):
        return "", v.lower()
    return v, ""


def valid_email(value) -> str:
    """The lowercase address inside `value`, or '' when there is none."""
    return parse_person(value)[1]


def _join_participants(value) -> str:
    """A list / array of participants (some plugins write one) -> the '|||'-joined string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        items = list(value)
    except TypeError:
        return str(value)
    return PARTICIPANT_SEP.join(str(x).strip() for x in items if x is not None and str(x).strip())


def _iso(series: pd.Series) -> pd.Series:
    """ISO 8601 strings in UTC, empty when unparseable."""
    ts = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
    return ts.map(lambda t: t.isoformat() if pd.notna(t) else "").astype(object)


def _read(path: Path, required: frozenset[str], columns: tuple[str, ...]) -> pd.DataFrame | None:
    try:
        df = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("plugin intake: %s unreadable (%s), skipped", path, exc)
        return None
    missing = sorted(required - set(df.columns))
    if missing:
        log.warning(
            "plugin intake: %s has no column %s, skipped (contract in tools/cross-source/plugin_intake.py)",
            path,
            ", ".join(missing),
        )
        return None
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df


def load_contacts(root: Path | str | None = None) -> pd.DataFrame | None:
    """Every plugin-contacts.parquet in one frame, normalised. None if there is none.

    Columns: CONTACT_COLUMNS plus `plugin` (folder name) and `from_participants` (False).
    """
    frames = []
    for path in contact_files(root):
        plugin = _plugin_of(path)
        if not _enabled(plugin):
            log.info("plugin intake: %s not in enabled_sources, skipped", plugin)
            continue
        df = _read(path, CONTACT_REQUIRED, CONTACT_COLUMNS)
        if df is None or df.empty:
            continue
        out = pd.DataFrame(index=df.index)
        for col in ("source", "name", "email", "phone", "company", "title", "url"):
            out[col] = _clean_str(df[col])
        out["source"] = out["source"].mask(out["source"] == "", plugin)
        # "Name <address>" gives both; a login or handle in the email field is blanked
        # (it would otherwise become a contact keyed by a non-address in the merge).
        pairs = out["email"].map(parse_person)
        bad = int(((out["email"] != "") & (pairs.str[1] == "")).sum())
        if bad:
            log.warning("plugin intake: %s, %d email values are not addresses, blanked", path, bad)
        out["name"] = out["name"].mask((out["name"] == "") & (pairs.str[1] != ""), pairs.str[0])
        out["email"] = pairs.str[1].astype(object)
        out["first_seen"] = _iso(df["first_seen"])
        out["last_seen"] = _iso(df["last_seen"])
        out["interactions"] = (
            pd.to_numeric(df["interactions"], errors="coerce").fillna(0).clip(lower=0).astype(int)
        )
        out["plugin"] = plugin
        out[FROM_PARTICIPANTS] = False
        out = out[(out["name"] != "") | (out["email"] != "") | (out["phone"] != "")]
        log.info("plugin intake: %s, %d contacts", path, len(out))
        frames.append(out)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def load_interactions(root: Path | str | None = None) -> pd.DataFrame | None:
    """Every plugin-interactions.parquet in one frame, normalised. None if there is none.

    Columns: INTERACTION_COLUMNS plus `status` (lowercase, may be empty) and `plugin`.
    Rows with an unknown kind become "record", an unknown owner_role becomes "other".
    """
    frames = []
    for path in interaction_files(root):
        plugin = _plugin_of(path)
        if not _enabled(plugin):
            log.info("plugin intake: %s not in enabled_sources, skipped", plugin)
            continue
        df = _read(path, INTERACTION_REQUIRED, INTERACTION_COLUMNS)
        if df is None or df.empty:
            continue
        has_status = "status" in df.columns
        if not has_status:
            df["status"] = ""
        df["participants"] = df["participants"].map(_join_participants)
        out = pd.DataFrame(index=df.index)
        for col in (
            "source",
            "kind",
            "title",
            "text",
            "participants",
            "owner_role",
            "url",
            "status",
        ):
            out[col] = _clean_str(df[col])
        out["source"] = out["source"].mask(out["source"] == "", plugin)
        out["kind"] = out["kind"].str.lower()
        out["kind"] = out["kind"].where(out["kind"].isin(KINDS), "record")
        out["owner_role"] = out["owner_role"].str.lower()
        out["owner_role"] = out["owner_role"].where(out["owner_role"].isin(OWNER_ROLES), "other")
        out["status"] = out["status"].str.lower()
        out["ts"] = _iso(df["ts"])
        out["due"] = _iso(df["due"])
        out["plugin"] = plugin
        if not has_status:
            n_open = int(((out["owner_role"] == "assignee") | (out["due"] != "")).sum())
            if n_open:
                log.warning(
                    "plugin intake: %s has no status column: %d assigned or dated items all count "
                    "as OPEN commitments (write status open|done to close them)",
                    path,
                    n_open,
                )
        log.info("plugin intake: %s, %d interactions", path, len(out))
        frames.append(out)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def split_participants(value) -> list[str]:
    """'a@x.example|||Bo Demo' -> ['a@x.example', 'Bo Demo'] (stripped, no empties, no repeats)."""
    if value is None:
        return []
    seen: list[str] = []
    for part in _join_participants(value).split(PARTICIPANT_SEP):
        p = part.strip()
        if p and p.lower() not in {"nan", "none"} and p not in seen:
            seen.append(p)
    return seen


def participant_contacts(interactions: pd.DataFrame | None) -> pd.DataFrame | None:
    """One contact row per (source, participant) seen in the interactions.

    An email participant fills `email`, anything else fills `name`. interactions,
    first_seen and last_seen are counted from the events. `from_participants` is True.
    """
    if interactions is None or interactions.empty:
        return None
    acc: dict[tuple[str, str], dict] = {}
    for row in interactions.itertuples(index=False):
        ts = row.ts or ""
        for p in split_participants(row.participants):
            p_name, p_email = parse_person(p)
            key = (row.source, (p_email or p_name).lower())
            cur = acc.get(key)
            if cur is None:
                cur = acc[key] = {
                    "source": row.source,
                    "name": p_name,
                    "email": p_email,
                    "phone": "",
                    "company": "",
                    "title": "",
                    "first_seen": ts,
                    "last_seen": ts,
                    "interactions": 0,
                    "url": "",
                    "plugin": row.plugin,
                    FROM_PARTICIPANTS: True,
                }
            cur["interactions"] += 1
            if ts and (not cur["first_seen"] or ts < cur["first_seen"]):
                cur["first_seen"] = ts
            if ts and (not cur["last_seen"] or ts > cur["last_seen"]):
                cur["last_seen"] = ts
    if not acc:
        return None
    return pd.DataFrame(list(acc.values()))


def load_people(root: Path | str | None = None) -> pd.DataFrame | None:
    """Contacts of every plugin, plus the interaction participants the contacts lack.

    A participant is dropped when the same plugin already lists that email or that
    name in its plugin-contacts.parquet: the contacts file is the plugin's own
    summary and wins. None when there is nothing at all.
    """
    contacts = load_contacts(root)
    extra = participant_contacts(load_interactions(root))
    if extra is not None and contacts is not None:
        known = set()
        for r in contacts.itertuples(index=False):
            if r.email:
                known.add((r.source, r.email.lower()))
            if r.name:
                known.add((r.source, r.name.lower()))
        keep = [
            (s, (e or n).lower()) not in known
            for s, e, n in zip(extra["source"], extra["email"], extra["name"], strict=True)
        ]
        extra = extra[keep]
    parts = [f for f in (contacts, extra) if f is not None and not f.empty]
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True)


def is_open(row) -> bool:
    """True unless the optional status says the item is closed."""
    return str(getattr(row, "status", "") or "").strip().lower() not in CLOSED_STATUSES


def is_commitment(row) -> bool:
    """An interaction is a commitment when it is open and you are the assignee or it has a due date."""
    return is_open(row) and (row.owner_role == "assignee" or bool(row.due))
