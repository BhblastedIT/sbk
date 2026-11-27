#!/usr/bin/env python3
"""Databases plugin, shared code for db-l0-download.py and db-l1-enrich.py.

Reads people (and the company they belong to) from a database YOU own or run:
SQLite, PostgreSQL or MySQL. You declare, in sbk.config.json, one read-only
query per source and a map from its result columns to the kernel's generic
intake fields (tools/cross-source/plugin_intake.py). Nothing is ever written
to your database.

Read-only, in three layers:

1. Every query is checked before it leaves this process (check_select): one
   statement only, it must start with SELECT or WITH, and words that change
   data or lock rows (INSERT, UPDATE, DELETE, MERGE, INTO, FOR SHARE, ...) and a
   short list of functions with side effects (nextval, setval, set_config,
   lo_import, query_to_xml, ...) are refused outside string literals and
   quoted names. MySQL /*! */ comments (executed by MySQL) are refused, and a
   query that reads differently depending on how the server treats
   backslashes in strings is refused too.
2. The connection itself is opened read-only where the driver allows it:
   * SQLite (standard library): URI `file:...?mode=ro`, `PRAGMA query_only = ON`,
     and an authorizer that lets through only SELECT, column reads, functions
     and recursive CTEs (every other action is denied by SQLite itself);
   * PostgreSQL with psycopg 3: `connection.read_only = True`, so every
     transaction is READ ONLY on the server, and a server-side cursor
     (DECLARE takes one SELECT); with the DuckDB `postgres`
     extension: ATTACH ... (READ_ONLY) and the libpq option
     `-c default_transaction_read_only=on`;
   * MySQL with PyMySQL: `SET SESSION TRANSACTION READ ONLY` at connect and
     `START TRANSACTION READ ONLY` before the query; with the DuckDB `mysql`
     extension: ATTACH ... (READ_ONLY) only (no session setting is applied,
     see Limits in docs/CONNECTING.md#databases).
3. Recommended, outside the code: connect as a database user that only has
   SELECT on the tables you map.

The connection string is never read from sbk.config.json: it comes from the
Keychain (service `sbk-databases`, account = the connection name) or from the
env var SBK_DB_URL_<NAME>. A SQLite file may also be given as a plain `path`
in sbk.config.json, because a path is not a secret. Error messages are
redacted: the connection string and its password never reach the terminal
or the summary file.

Vendor facts this code relies on (official docs, read 2026-11-25):
  * SQLite URI `mode=ro`: https://www.sqlite.org/uri.html
  * PRAGMA query_only: https://www.sqlite.org/pragma.html#pragma_query_only
  * authorizer and action codes: https://www.sqlite.org/c3ref/set_authorizer.html,
    https://www.sqlite.org/c3ref/c_alter_table.html,
    https://docs.python.org/3/library/sqlite3.html (set_authorizer, uri=True)
  * PostgreSQL read-only transactions: https://www.postgresql.org/docs/current/sql-set-transaction.html,
    default_transaction_read_only: https://www.postgresql.org/docs/current/runtime-config-client.html,
    libpq `options` and URI percent-encoding: https://www.postgresql.org/docs/current/libpq-connect.html
  * psycopg 3 `read_only`: https://www.psycopg.org/psycopg3/docs/api/connections.html,
    `%%` with parameters: https://www.psycopg.org/psycopg3/docs/basic/params.html,
    install `psycopg[binary]`: https://www.psycopg.org/psycopg3/docs/basic/install.html
  * MySQL SET TRANSACTION / START TRANSACTION READ ONLY:
    https://dev.mysql.com/doc/refman/8.4/en/set-transaction.html,
    https://dev.mysql.com/doc/refman/8.4/en/commit.html,
    WITH inside a derived table: https://dev.mysql.com/doc/refman/8.4/en/with.html
  * PyMySQL connect(init_command=...), SSCursor:
    https://pymysql.readthedocs.io/en/latest/modules/connections.html,
    https://pymysql.readthedocs.io/en/latest/modules/cursors.html
  * DuckDB postgres / mysql extensions (ATTACH READ_ONLY, postgres_query,
    mysql_query, autoload from the official extension repository, warning
    that a failed ATTACH can print the connection string):
    https://duckdb.org/docs/stable/core_extensions/postgres.html,
    https://duckdb.org/docs/stable/core_extensions/mysql.html
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import sqlite3
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_phone  # noqa: E402

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("db")

SOURCE_ID = "databases"

#: Data paths (own module, not sbk_config).
DB_DIR = cfg.DATA_ROOT / "databases"
RAW_DIR = "raw"
PROCESSED_DIR = "processed"
STATE_FILE = "state.json"
SUMMARY_FILE = "download-summary.json"
CONTACTS_FILE = "plugin-contacts.parquet"
INTERACTIONS_FILE = "plugin-interactions.parquet"

KEYCHAIN_SERVICE = "sbk-databases"
ENV_PREFIX = "SBK_DB_URL_"

ENGINES = ("sqlite", "postgres", "mysql")
DRIVERS = {
    "sqlite": ("sqlite3",),
    "postgres": ("psycopg", "duckdb"),
    "mysql": ("pymysql", "duckdb"),
}
INSTALL_HINT = {
    "psycopg": "uv add 'psycopg[binary]>=3.2'",
    "pymysql": "uv add 'pymysql>=1.1'",
    "duckdb": "duckdb is already a dependency of SBK; run `uv sync`",
}
#: Keys that would put a credential in sbk.config.json in clear: refused.
SECRET_KEYS = frozenset(
    {"url", "dsn", "uri", "conninfo", "connection_string", "password", "passwd", "secret"}
)

BATCH = 2000
DEFAULT_MAX_ROWS = 200_000
TEXT_MAX = 4000
CONNECT_TIMEOUT_S = 15

INTAKES = ("contacts", "interactions")
CONTACT_FIELDS = (
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
INTERACTION_FIELDS = (
    "ts",
    "kind",
    "title",
    "text",
    "participants",
    "owner_role",
    "due",
    "url",
    "status",
)
KINDS = ("meeting", "issue", "pr", "review", "message", "record")
OWNER_ROLES = ("organizer", "assignee", "author", "attendee", "other")
PARTICIPANT_SEP = "|||"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

NO_CONFIG_MSG = (
    'databases: no sources declared (sbk.config.json section "databases"); '
    "see docs/CONNECTING.md#databases"
)


class ConfigError(RuntimeError):
    """A problem in the sbk.config.json "databases" section (one clear line)."""


class NoSecret(RuntimeError):
    """A connection without a connection string (one clear line)."""


class DriverMissing(RuntimeError):
    """The Python driver for an engine is not installed (one clear line)."""


class NotReadOnly(ValueError):
    """A query that is not a single read-only SELECT/WITH statement."""


# --------------------------------------------------------------------------- guard

# Words that, inside a single SELECT/WITH statement, can only mean a write or a
# lock: data-modifying CTEs (PostgreSQL), SELECT ... INTO (a new table in
# PostgreSQL, a file or variable in MySQL), row locks. The statement-level words
# (CREATE, DROP, ...) are listed too: they cannot appear in a valid SELECT, so
# listing them costs nothing and catches odd dialects.
_FORBIDDEN_WORDS = (
    "insert",
    "update",
    "delete",
    "merge",
    "upsert",
    "into",
    "create",
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "copy",
    "call",
    "exec",
    "execute",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
    "lock",
    "unlock",
    "install",
)
# Functions with side effects in PostgreSQL / MySQL / SQLite / DuckDB.
_FORBIDDEN_FUNCTIONS = (
    "nextval",
    "setval",
    "set_config",
    "lo_import",
    "lo_export",
    "lo_unlink",
    "lo_create",
    "lo_put",
    "lo_from_bytea",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_promote",
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "pg_try_advisory_lock",
    "pg_try_advisory_xact_lock",
    "pg_create_restore_point",
    "pg_switch_wal",
    "dblink",
    "dblink_exec",
    "dblink_connect",
    "get_lock",
    "release_lock",
    "release_all_locks",
    "load_extension",
    "postgres_execute",
    "mysql_execute",
    # PostgreSQL functions that run the query text they are given, hidden from
    # this check inside a string (https://www.postgresql.org/docs/current/functions-xml.html).
    "query_to_xml",
    "query_to_xmlschema",
    "query_to_xml_and_xmlschema",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN_WORDS) + r")\b", re.I)
_FORBIDDEN_FN_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN_FUNCTIONS) + r")\s*\(", re.I)
_REPLACE_STMT_RE = re.compile(r"\breplace\b(?!\s*\()", re.I)
_LOCKING_RE = re.compile(r"\bfor\s+(no\s+key\s+update|key\s+share|share|update)\b", re.I)


def _mask(sql: str, engine: str, backslash: bool | None = None) -> str:
    """The query with comments removed and literals / quoted names blanked.

    The result has exactly the length of the input (everything blanked becomes
    spaces), so a position in it is the same position in the original.
    Handles '...' with '' escapes, "..." identifiers, `...` (MySQL, SQLite),
    $tag$...$tag$ and E'...' (PostgreSQL), -- and /* */ comments (nested in
    PostgreSQL), and # comments (MySQL).

    `backslash`: whether a backslash escapes the next character inside '...'
    (and "..." in MySQL). The default is the server default: True for MySQL,
    False otherwise. check_select() masks the query both ways, because the
    server setting (MySQL NO_BACKSLASH_ESCAPES, PostgreSQL
    standard_conforming_strings) decides it and the plugin cannot see it.

    MySQL runs the code inside /*! ... */ comments
    (https://dev.mysql.com/doc/refman/8.4/en/comments.html), so they are
    refused rather than blanked.
    """
    if backslash is None:
        backslash = engine == "mysql"
    quotes = ("'", '"', "`") if engine in ("mysql", "sqlite") else ("'", '"')
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if (c == "-" and nxt == "-") or (c == "#" and engine == "mysql"):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and nxt == "*":
            if engine == "mysql" and re.match(r"/\*M?!", sql[i : i + 4]):
                raise NotReadOnly(
                    "MySQL executable comments /*! ... */ are not allowed (MySQL runs their content)"
                )
            # PostgreSQL block comments nest (https://www.postgresql.org/docs/current/sql-syntax-lexical.html).
            depth, j = 1, i + 2
            while j < n and depth:
                if engine == "postgres" and sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise NotReadOnly("unterminated /* comment")
            out.append(" " * (j - i))
            i = j
            continue
        if c in quotes:
            q = c
            # PostgreSQL E'...' strings always take backslash escapes.
            e_string = (
                engine == "postgres"
                and q == "'"
                and i > 0
                and sql[i - 1] in "eE"
                and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] in "_$"))
            )
            esc = q != "`" and (e_string or (backslash and (q == "'" or engine == "mysql")))
            j = i + 1
            while j < n:
                if esc and sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == q:
                    if j + 1 < n and sql[j + 1] == q:
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise NotReadOnly(f"unterminated {q} quote")
            out.append(q + " " * (j - i - 1) + q)
            i = j + 1
            continue
        if c == "$" and engine == "postgres":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                if j < 0:
                    raise NotReadOnly("unterminated $-quoted string")
                out.append("'" + " " * (j + len(tag) - i - 2) + "'")
                i = j + len(tag)
                continue
        out.append(c)
        i += 1
    return "".join(out)


def check_select(sql: str, engine: str = "sqlite") -> str:
    """Return the query without trailing semicolons, or raise NotReadOnly.

    One statement, starting with SELECT or WITH (opening parentheses allowed),
    no write / lock keyword and no side-effect function outside literals.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise NotReadOnly("empty query")
    body = _check_masked(_mask(sql, engine), sql)
    # The same checks with backslashes read the other way: a query whose meaning
    # depends on a server setting the plugin cannot see is refused.
    if engine in ("mysql", "postgres"):
        try:
            _check_masked(_mask(sql, engine, backslash=engine != "mysql"), sql)
        except NotReadOnly as e:
            raise NotReadOnly(
                f"{e}, when the server reads backslashes in strings the other way "
                "(MySQL NO_BACKSLASH_ESCAPES, PostgreSQL standard_conforming_strings): "
                "write a quote inside a string as '' instead of \\'"
            ) from None
    # The original text, minus trailing semicolons, comments and blanks.
    return sql[: len(body)]


# A side-effect function written as a quoted name ("nextval"(...)): the masking
# blanks quoted names, so they are looked for in the original text.
_QUOTED_FN_RE = re.compile(r"[\"`]\s*(" + "|".join(_FORBIDDEN_FUNCTIONS) + r")\s*[\"`]\s*\(", re.I)


def _check_masked(masked: str, sql: str) -> str:
    """The checks of check_select on one masked form; returns the trimmed body."""
    body = masked.rstrip()
    while body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        raise NotReadOnly("only one statement is allowed (found ';' inside the query)")
    first = re.match(r"\s*\(*\s*([A-Za-z]+)", body)
    if not first or first.group(1).lower() not in ("select", "with"):
        word = first.group(1) if first else body.strip()[:20]
        raise NotReadOnly(f"only SELECT or WITH queries are allowed (it starts with {word!r})")
    m = _LOCKING_RE.search(body)
    if m:
        raise NotReadOnly(f"row locks are not allowed ({m.group(0).upper()})")
    m = _FORBIDDEN_RE.search(body)
    if m:
        raise NotReadOnly(
            f"the word {m.group(1).upper()!r} is not allowed in a read-only query "
            "(if it is a column name, put it in quotes)"
        )
    m = _REPLACE_STMT_RE.search(body)
    if m:
        raise NotReadOnly("the word 'REPLACE' is only allowed as the replace(...) function")
    m = _FORBIDDEN_FN_RE.search(body) or _QUOTED_FN_RE.search(sql)
    if m:
        raise NotReadOnly(f"the function {m.group(1)}() has side effects and is not allowed")
    return body


# --------------------------------------------------------------------------- settings


def _clean(d) -> dict:
    """A dict without the "_help"-style keys (notes for people)."""
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if not str(k).startswith("_")}


def load_settings(raw: dict | None = None) -> dict:
    """The "databases" section, validated. Raises ConfigError with one line."""
    if raw is None:
        raw = cfg.user_cfg("databases", {}) or {}
    raw = _clean(raw)
    conns_in = _clean(raw.get("connections") or {})
    sources_in = raw.get("sources") or []
    if not sources_in:
        raise ConfigError(NO_CONFIG_MSG)
    if not isinstance(sources_in, list):
        raise ConfigError('databases: "sources" must be a list; see docs/CONNECTING.md#databases')

    conns: dict[str, dict] = {}
    for name, c in conns_in.items():
        c = _clean(c)
        if not _ID_RE.match(str(name)):
            raise ConfigError(
                f"databases: connection name {name!r} must be lowercase letters, digits, - or _"
            )
        leaked = sorted(SECRET_KEYS & {str(k).lower() for k in c})
        if leaked:
            raise ConfigError(
                f"databases: connection {name!r} has {', '.join(leaked)} in sbk.config.json; "
                f"put the connection string in the Keychain ({KEYCHAIN_SERVICE}/{name}) "
                f"or in {env_name(name)}, never in the config file"
            )
        engine = str(c.get("engine", "")).lower()
        if engine in ("postgresql", "pg"):
            engine = "postgres"
        if engine not in ENGINES:
            raise ConfigError(
                f'databases: connection {name!r} needs "engine": one of {", ".join(ENGINES)}'
            )
        driver = str(c.get("driver") or DRIVERS[engine][0]).lower()
        if driver not in DRIVERS[engine]:
            raise ConfigError(
                f"databases: connection {name!r} driver {driver!r} is not one of "
                f"{', '.join(DRIVERS[engine])}"
            )
        env = str(c.get("env") or env_name(name))
        conns[name] = {
            "name": name,
            "engine": engine,
            "driver": driver,
            "path": str(c.get("path") or ""),
            "env": env,
        }
        if conns[name]["path"] and engine != "sqlite":
            raise ConfigError(f'databases: connection {name!r}: "path" is only for SQLite files')

    sources: list[dict] = []
    seen: set[str] = set()
    for i, s in enumerate(sources_in):
        s = _clean(s)
        sid = str(s.get("id", "")).strip()
        where = f"databases: source #{i + 1}" + (f" {sid!r}" if sid else "")
        if not _ID_RE.match(sid):
            raise ConfigError(f'{where} needs an "id" of lowercase letters, digits, - or _')
        if sid in seen:
            raise ConfigError(f"{where}: the id is used twice")
        seen.add(sid)
        conn = str(s.get("connection", ""))
        if conn not in conns:
            raise ConfigError(f'{where}: "connection" {conn!r} is not in databases.connections')
        intake = str(s.get("intake", "contacts")).lower()
        if intake not in INTAKES:
            raise ConfigError(f'{where}: "intake" must be contacts or interactions')
        query = s.get("query", "")
        try:
            check_select(query, conns[conn]["engine"])
        except NotReadOnly as e:
            raise ConfigError(f"{where}: query refused, {e}") from None
        columns = _clean(s.get("columns") or {})
        allowed = CONTACT_FIELDS if intake == "contacts" else INTERACTION_FIELDS
        bad = sorted(set(columns) - set(allowed))
        if bad:
            raise ConfigError(
                f"{where}: unknown field(s) {', '.join(bad)} in columns; allowed: {', '.join(allowed)}"
            )
        for field, col in columns.items():
            cols = col if isinstance(col, list) else [col]
            if not cols or not all(isinstance(x, str) and x for x in cols):
                raise ConfigError(
                    f"{where}: columns.{field} must be a column name or a list of them"
                )
        if intake == "contacts" and not ({"name", "email", "phone"} & set(columns)):
            raise ConfigError(f"{where}: map at least one of name, email, phone in columns")
        if intake == "interactions" and not ({"ts", "title"} <= set(columns)):
            raise ConfigError(f"{where}: map at least ts and title in columns")
        key = s.get("key") or []
        key = [key] if isinstance(key, str) else list(key)
        cursor_col = str(s.get("cursor") or "")
        if cursor_col and not _COL_RE.match(cursor_col):
            raise ConfigError(f'{where}: "cursor" must be a plain column name of the result')
        if cursor_col and not key:
            raise ConfigError(f'{where}: "cursor" needs a "key" (the column(s) unique per row)')
        kind = str(s.get("kind", "record")).lower()
        if kind not in KINDS:
            raise ConfigError(f'{where}: "kind" must be one of {", ".join(KINDS)}')
        role = str(s.get("owner_role", "other")).lower()
        if role not in OWNER_ROLES:
            raise ConfigError(f'{where}: "owner_role" must be one of {", ".join(OWNER_ROLES)}')
        try:
            max_rows = int(s.get("max_rows") or raw.get("max_rows_per_source") or DEFAULT_MAX_ROWS)
        except (TypeError, ValueError):
            raise ConfigError(f'{where}: "max_rows" must be a number') from None
        sources.append(
            {
                "id": sid,
                "connection": conn,
                "intake": intake,
                "query": query,
                "columns": columns,
                "key": key,
                "cursor": cursor_col,
                "kind": kind,
                "owner_role": role,
                "status": str(s.get("status") or ""),
                "url_template": str(s.get("url_template") or ""),
                "timezone": str(s.get("timezone") or "UTC"),
                "max_rows": max(1, max_rows),
            }
        )
    return {"connections": conns, "sources": sources}


def env_name(conn_name: str) -> str:
    return ENV_PREFIX + re.sub(r"[^A-Z0-9]+", "_", conn_name.upper()).strip("_")


def resolve_secret(conn: dict) -> tuple[str, str]:
    """(connection string or SQLite path, where it came from). Never logged."""
    if conn["engine"] == "sqlite" and conn["path"]:
        return conn["path"], "sbk.config.json path"
    try:
        from secrets_adapter import get_secret

        val = get_secret(KEYCHAIN_SERVICE, conn["name"])
        if val and val.strip():
            return val.strip(), f"keychain {KEYCHAIN_SERVICE}/{conn['name']}"
    except Exception as exc:  # noqa: BLE001 - keyring missing or locked: try env
        log.debug("keychain lookup failed: %s", type(exc).__name__)
    val = (os.environ.get(conn["env"]) or "").strip()
    if val:
        return val, f"env {conn['env']}"
    what = "file path or connection string" if conn["engine"] == "sqlite" else "connection string"
    raise NoSecret(
        f"databases: connection {conn['name']!r} has no {what} "
        f"(Keychain {KEYCHAIN_SERVICE}/{conn['name']}, or {conn['env']} in .env"
        + (', or "path" in sbk.config.json' if conn["engine"] == "sqlite" else "")
        + "); see docs/CONNECTING.md#databases"
    )


# --------------------------------------------------------------------------- redaction


def _secret_bits(secret: str) -> list[str]:
    bits = {secret}
    try:
        parts = urlsplit(secret)
        if parts.password:
            bits.add(parts.password)
            bits.add(unquote(parts.password))
    except ValueError:
        pass
    for m in re.finditer(r"(?:password|passwd|pwd)\s*=\s*('(?:[^']|'')*'|\S+)", secret, re.I):
        v = m.group(1).strip("'")
        if v:
            bits.add(v)
    # The forms the plugin itself writes the password in (DuckDB key=value
    # string, percent-encoded URI), so an error that echoes them is redacted too.
    for b in list(bits):
        bits.add(b.replace("\\", "\\\\").replace("'", "\\'"))
        bits.add(quote(b, safe=""))
    return sorted((b for b in bits if b and len(b) >= 3), key=len, reverse=True)


def redact(text: str, secret: str | None) -> str:
    out = str(text)
    if secret:
        for b in _secret_bits(secret):
            out = out.replace(b, "***")
    out = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1***@", out)
    out = re.sub(r"((?:password|passwd|pwd)\s*=\s*)('(?:[^']|'')*'|\S+)", r"\1***", out, flags=re.I)
    return out[:500]


# --------------------------------------------------------------------------- values


def to_text(v) -> str | None:
    """One cell as text for the raw parquet (ISO for dates, None stays None)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, bytes | bytearray | memoryview):
        return None  # binary columns are not kept
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, float) and v != v:  # NaN
        return None
    return str(v)


def wm_pack(v) -> dict | None:
    """A watermark value with its type, so the next run binds it with the same type."""
    if v is None:
        return None
    if isinstance(v, bool):
        return {"type": "int", "value": int(v)}
    if isinstance(v, int):
        return {"type": "int", "value": v}
    if isinstance(v, Decimal):  # kept exact: a float could round past a row
        return {"type": "decimal", "value": format(v, "f")}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, datetime):
        return {"type": "datetime", "value": v.isoformat()}
    if isinstance(v, date):
        return {"type": "date", "value": v.isoformat()}
    return {"type": "str", "value": str(v)}


def wm_unpack(w: dict | None):
    if not w:
        return None
    t, v = w.get("type"), w.get("value")
    if t == "int":
        return int(v)
    if t == "float":
        return float(v)
    if t == "decimal":
        return Decimal(v)
    if t == "datetime":
        return datetime.fromisoformat(v)
    if t == "date":
        return date.fromisoformat(v)
    return str(v)


def wm_literal(v) -> str:
    """A watermark as an SQL literal (only for DuckDB pass-through queries).

    The value comes from the database itself. A text value with a backslash is
    refused: MySQL (and PostgreSQL with standard_conforming_strings off) would
    read it as an escape and the literal could end early.
    """
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, datetime):
        return "'" + v.isoformat(sep=" ") + "'"
    if isinstance(v, date):
        return "'" + v.isoformat() + "'"
    s = str(v)
    if "\\" in s or "\x00" in s:
        raise ValueError(
            "the cursor value has a backslash, which the duckdb driver cannot pass safely; "
            'use the native driver or another "cursor" column, or run with --full'
        )
    return "'" + s.replace("'", "''") + "'"


def _wm_max(a, b):
    if a is None:
        return b
    if b is None:
        return a
    try:
        return b if b > a else a
    except TypeError:
        return b if str(b) > str(a) else a


# --------------------------------------------------------------------------- readers


def _import(name: str):
    """importlib.import_module, kept separate so tests can swap drivers."""
    return importlib.import_module(name)


def _require(module: str, conn: dict):
    try:
        return _import(module)
    except ImportError:
        raise DriverMissing(
            f"databases: connection {conn['name']!r} ({conn['engine']}) needs the Python driver "
            f"{module!r}, not installed: {INSTALL_HINT.get(module, 'install it')}"
            + (' (or set "driver": "duckdb" for this connection)' if module != "duckdb" else "")
        ) from None


def wrap_incremental(sql: str, cursor_col: str, engine: str, placeholder: str | None) -> str:
    """SELECT * FROM (<sql>) AS sbk_q [WHERE <cursor> >= <placeholder>] ORDER BY <cursor>.

    A full read of a source with a cursor is ordered too (placeholder None): if
    max_rows cuts it, the watermark is the last row actually kept, so the next
    incremental run starts there and nothing in between is skipped.
    """
    q = f"`{cursor_col}`" if engine == "mysql" else f'"{cursor_col}"'
    where = f" WHERE sbk_q.{q} >= {placeholder}" if placeholder is not None else ""
    return f"SELECT * FROM (\n{sql}\n) AS sbk_q{where} ORDER BY sbk_q.{q}"


# SQLite authorizer action codes allowed (everything else is denied).
def _sqlite_allowed() -> frozenset[int]:
    names = ("SQLITE_SELECT", "SQLITE_READ", "SQLITE_FUNCTION", "SQLITE_RECURSIVE")
    return frozenset(getattr(sqlite3, n) for n in names if hasattr(sqlite3, n))


_FORBIDDEN_FN_NAMES = frozenset(_FORBIDDEN_FUNCTIONS)


def sqlite_authorizer(action, arg1, arg2, dbname, source):
    if action not in _sqlite_allowed():
        return sqlite3.SQLITE_DENY
    if (
        action == getattr(sqlite3, "SQLITE_FUNCTION", -1)
        and str(arg2 or "").lower() in _FORBIDDEN_FN_NAMES
    ):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class Reader:
    """One open, read-only connection. query() yields (columns, batches)."""

    def __init__(self, conn: dict, secret: str):
        self.conn = conn
        self.secret = secret
        self.engine = conn["engine"]
        self.driver = conn["driver"]
        self._db = None
        self._duck_name = "sbk_src"

    # -- open
    def open(self) -> Reader:
        try:
            getattr(self, f"_open_{self.driver}")()
        except (DriverMissing, NoSecret):
            raise
        except Exception as e:  # noqa: BLE001 - redacted, re-raised as one line
            raise RuntimeError(
                f"databases: cannot open {self.conn['name']!r} ({self.engine}/{self.driver}): "
                + redact(f"{type(e).__name__}: {e}", self.secret)
            ) from None
        return self

    def _open_sqlite3(self):
        s = self.secret
        if s.startswith("sqlite:///"):
            s = s[len("sqlite:///") :]  # sqlite:////abs/path -> /abs/path
        elif s.startswith("file:"):
            s = urlsplit(s).path
        p = Path(s).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"no SQLite file at {p}")
        uri = p.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=CONNECT_TIMEOUT_S, check_same_thread=False)
        db.execute("PRAGMA query_only = ON")
        db.set_authorizer(sqlite_authorizer)
        self._db = db

    def _open_psycopg(self):
        psycopg = _require("psycopg", self.conn)
        db = psycopg.connect(self.secret, connect_timeout=CONNECT_TIMEOUT_S, autocommit=False)
        db.read_only = True  # every transaction READ ONLY on the server
        self._db = db

    def _open_pymysql(self):
        pymysql = _require("pymysql", self.conn)
        kw = mysql_params(self.secret)
        cursors = _import("pymysql.cursors")
        db = pymysql.connect(
            **kw,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=CONNECT_TIMEOUT_S,
            init_command="SET SESSION TRANSACTION READ ONLY",
            cursorclass=cursors.SSCursor,
        )
        self._db = db

    def _open_duckdb(self):
        duckdb = _require("duckdb", self.conn)
        db = duckdb.connect(":memory:")
        try:
            import sbk_resources

            sbk_resources.configure_duckdb(db)
        except Exception:  # noqa: BLE001 - no budget helper: DuckDB defaults
            pass
        if self.engine == "postgres":
            target, typ = pg_read_only_conninfo(self.secret), "postgres"
        else:
            target, typ = mysql_duckdb_conninfo(self.secret), "mysql"
        lit = target.replace("'", "''")
        db.execute(f"ATTACH '{lit}' AS {self._duck_name} (TYPE {typ}, READ_ONLY)")
        self._db = db

    # -- query
    def query(self, sql: str, cursor_col: str = "", since=None, max_rows: int = DEFAULT_MAX_ROWS):
        """(columns, rows as tuples, truncated). Re-checks the query first."""
        sql = check_select(sql, self.engine)
        try:
            return getattr(self, f"_query_{self.driver}")(sql, cursor_col, since, max_rows)
        except NotReadOnly:
            raise
        except Exception as e:  # noqa: BLE001
            self._rollback()
            raise RuntimeError(redact(f"{type(e).__name__}: {e}", self.secret)) from None

    @staticmethod
    def _drain(cur, max_rows: int):
        rows: list[tuple] = []
        truncated = False
        while True:
            batch = cur.fetchmany(BATCH)
            if not batch:
                break
            room = max_rows - len(rows)
            if len(batch) > room:
                rows.extend(tuple(r) for r in batch[:room])
                truncated = True
                break
            rows.extend(tuple(r) for r in batch)
        return rows, truncated

    def _query_sqlite3(self, sql, cursor_col, since, max_rows):
        params: tuple = ()
        if cursor_col and since is not None:
            sql, params = wrap_incremental(sql, cursor_col, "sqlite", "?"), (since,)
        elif cursor_col:
            sql = wrap_incremental(sql, cursor_col, "sqlite", None)
        cur = self._db.execute(sql, params)
        cols = [d[0] for d in cur.description or ()]
        rows, truncated = self._drain(cur, max_rows)
        cur.close()
        return cols, rows, truncated

    def _query_psycopg(self, sql, cursor_col, since, max_rows):
        params = None
        if cursor_col and since is not None:
            # With parameters, a literal % must be written %% (psycopg docs).
            sql = wrap_incremental(sql.replace("%", "%%"), cursor_col, "postgres", "%s")
            params = (since,)
        elif cursor_col:
            sql = wrap_incremental(sql, cursor_col, "postgres", None)
        # A server-side (named) cursor: rows come in batches of BATCH instead of
        # the whole result in memory, and DECLARE takes exactly one SELECT
        # (https://www.psycopg.org/psycopg3/docs/advanced/cursors.html,
        # https://www.postgresql.org/docs/current/sql-declare.html).
        cur = self._db.cursor(name="sbk_read")
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description or ()]
        rows, truncated = self._drain(cur, max_rows)
        cur.close()
        self._db.rollback()  # nothing to keep: end the read-only transaction
        return cols, rows, truncated

    def _query_pymysql(self, sql, cursor_col, since, max_rows):
        params = None
        if cursor_col and since is not None:
            sql = wrap_incremental(sql.replace("%", "%%"), cursor_col, "mysql", "%s")
            params = (since,)
        elif cursor_col:
            sql = wrap_incremental(sql, cursor_col, "mysql", None)
        cur = self._db.cursor()
        cur.execute("START TRANSACTION READ ONLY")
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description or ()]
        rows, truncated = self._drain(cur, max_rows)
        cur.close()
        self._db.rollback()
        return cols, rows, truncated

    def _query_duckdb(self, sql, cursor_col, since, max_rows):
        if cursor_col:
            lit = wm_literal(since) if since is not None else None
            sql = wrap_incremental(sql, cursor_col, self.engine, lit)
        fn = "postgres_query" if self.engine == "postgres" else "mysql_query"
        lit = sql.replace("'", "''")
        cur = self._db.execute(f"SELECT * FROM {fn}('{self._duck_name}', '{lit}')")
        cols = [d[0] for d in cur.description or ()]
        rows, truncated = self._drain(cur, max_rows)
        return cols, rows, truncated

    def _rollback(self):
        try:
            if self.driver in ("psycopg", "pymysql") and self._db is not None:
                self._db.rollback()
        except Exception:  # noqa: BLE001
            pass

    def ping(self) -> None:
        """A trivial read, to prove the connection works (dry run)."""
        self.query("SELECT 1 AS ok", max_rows=1)

    def close(self) -> None:
        try:
            if self._db is not None:
                self._db.close()
        except Exception:  # noqa: BLE001
            pass
        self._db = None


def open_reader(conn: dict, secret: str) -> Reader:
    return Reader(conn, secret).open()


# --------------------------------------------------------------------------- connection strings


def pg_read_only_conninfo(conninfo: str) -> str:
    """The libpq string/URI with `-c default_transaction_read_only=on` added to options."""
    flag = "-c default_transaction_read_only=on"
    s = conninfo.strip()
    if s.startswith(("postgresql://", "postgres://")):
        parts = urlsplit(s)
        q = parse_qsl(parts.query, keep_blank_values=True)
        opts = [v for k, v in q if k == "options"]
        rest = [(k, v) for k, v in q if k != "options"]
        merged = (opts[0] + " " + flag) if opts else flag
        query = urlencode(rest + [("options", merged)], quote_via=quote)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    m = re.search(r"\boptions\s*=\s*('((?:[^'\\]|\\.)*)'|(\S+))", s)
    if m:
        old = m.group(2) if m.group(2) is not None else m.group(3)
        return s[: m.start()] + f"options='{old} {flag}'" + s[m.end() :]
    return f"{s} options='{flag}'"


def mysql_params(url: str) -> dict:
    """mysql://user:pass@host:port/db?ssl_ca=... -> PyMySQL keyword arguments."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("mysql", "mysql+pymysql", "mariadb"):
        raise ValueError(
            "a MySQL connection string must look like mysql://user:password@host:3306/database"
        )
    kw: dict = {
        "host": parts.hostname or "localhost",
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "port": parts.port or 3306,
    }
    db = parts.path.lstrip("/")
    if db:
        kw["database"] = unquote(db)
    for k, v in parse_qsl(parts.query):
        if k in ("ssl_ca", "ssl_cert", "ssl_key"):
            kw[k] = v
        elif k == "unix_socket":
            kw["unix_socket"] = v
    return kw


def mysql_duckdb_conninfo(url: str) -> str:
    """The same URL as the key=value string the DuckDB mysql extension reads."""
    kw = mysql_params(url)
    out = []
    names = {
        "host": "host",
        "user": "user",
        "password": "password",
        "port": "port",
        "database": "database",
        "unix_socket": "socket",
        "ssl_ca": "ssl_ca",
        "ssl_cert": "ssl_cert",
        "ssl_key": "ssl_key",
    }
    for k, v in kw.items():
        if v in ("", None):
            continue
        sv = str(v)
        if re.search(r"[\s'\\]", sv):
            sv = "'" + sv.replace("\\", "\\\\").replace("'", "\\'") + "'"
        out.append(f"{names[k]}={sv}")
    return " ".join(out)


# --------------------------------------------------------------------------- L0


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def query_fingerprint(src: dict) -> str:
    h = hashlib.sha256()
    for part in (src["connection"], src["query"], src["cursor"], ",".join(src["key"])):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def download_source(reader: Reader, src: dict, dest: Path, state: dict, full: bool) -> dict:
    """Run one source's query and update raw/<id>.parquet. Returns its summary."""
    import pandas as pd

    raw_path = dest / RAW_DIR / f"{src['id']}.parquet"
    fp = query_fingerprint(src)
    prev = state.get(src["id"]) or {}
    incremental = bool(
        src["cursor"] and not full and prev.get("fingerprint") == fp and raw_path.exists()
    )
    since = wm_unpack(prev.get("watermark")) if incremental else None
    # With a cursor the result is always ordered by it (full reads too), so a
    # max_rows cut keeps the lowest values and the watermark never skips rows.
    cols, rows, truncated = reader.query(src["query"], src["cursor"], since, src["max_rows"])
    if src["cursor"] and src["cursor"] not in cols:
        raise ValueError(f"the cursor column {src['cursor']!r} is not in the query result")
    missing_key = [k for k in src["key"] if k not in cols]
    if missing_key:
        raise ValueError(f"key column(s) {', '.join(missing_key)} not in the query result")
    wm = wm_unpack(prev.get("watermark")) if incremental else None
    if src["cursor"]:
        ci = cols.index(src["cursor"])
        for r in rows:
            wm = _wm_max(wm, r[ci])
    df_new = pd.DataFrame([[to_text(v) for v in r] for r in rows], columns=cols, dtype="string")
    if incremental:
        old = pd.read_parquet(raw_path).astype("string")
        df = pd.concat([old, df_new], ignore_index=True)
        df = df.drop_duplicates(subset=src["key"], keep="last")
    else:
        df = df_new.drop_duplicates(subset=src["key"], keep="last") if src["key"] else df_new
    cfg.safe_write_parquet(df.reset_index(drop=True), raw_path, index=False)
    state[src["id"]] = {
        "fingerprint": fp,
        "watermark": wm_pack(wm),
        "last_run": _now_iso(),
        "rows": int(len(df)),
    }
    return {
        "mode": "incremental" if incremental else "full",
        "rows_read": len(rows),
        "rows_total": int(len(df)),
        "truncated": truncated,
        "columns": cols,
    }


def run_download(
    settings: dict,
    dest: Path,
    *,
    only: Iterable[str] | None = None,
    full: bool = False,
    secrets: dict[str, str] | None = None,
) -> dict:
    """The whole L0. Writes under `dest`, returns the summary it also writes.

    `secrets` maps connection name -> connection string (tests); otherwise each
    one is resolved from the Keychain / env.
    """
    dest = Path(dest)
    (dest / RAW_DIR).mkdir(parents=True, exist_ok=True)
    state_path = dest / STATE_FILE
    state_all = _read_json(state_path, {})
    state = state_all.setdefault("sources", {})
    only_set = set(only or [])
    todo = [s for s in settings["sources"] if not only_set or s["id"] in only_set]
    if only_set - {s["id"] for s in settings["sources"]}:
        raise ConfigError(
            "databases: unknown --source "
            + ", ".join(sorted(only_set - {s["id"] for s in settings["sources"]}))
        )
    summary: dict = {"run_at": _now_iso(), "full": full, "sources": {}, "errors": {}}
    by_conn: dict[str, list[dict]] = {}
    for s in todo:
        by_conn.setdefault(s["connection"], []).append(s)
    for name, srcs in by_conn.items():
        conn = settings["connections"][name]
        secret = (secrets or {}).get(name)
        try:
            if secret is None:
                secret, where = resolve_secret(conn)
            else:
                where = "argument"
            reader = open_reader(conn, secret)
        except (NoSecret, DriverMissing, RuntimeError) as e:
            for s in srcs:
                summary["errors"][s["id"]] = str(e)
            log.error("%s", e)
            continue
        log.info(
            "databases: %s (%s/%s), connection string from %s",
            name,
            conn["engine"],
            conn["driver"],
            where,
        )
        try:
            for s in srcs:
                try:
                    res = download_source(reader, s, dest, state, full)
                    summary["sources"][s["id"]] = res
                    log.info(
                        "  %-24s %s, %d rows read, %d kept%s",
                        s["id"],
                        res["mode"],
                        res["rows_read"],
                        res["rows_total"],
                        f" (stopped at max_rows={s['max_rows']})" if res["truncated"] else "",
                    )
                except Exception as e:  # noqa: BLE001 - one source failing does not stop the others
                    msg = redact(str(e), secret)
                    summary["errors"][s["id"]] = msg
                    log.error("  %-24s failed: %s", s["id"], msg)
        finally:
            reader.close()
    state_all["sources"] = state
    cfg.safe_write_json(state_path, state_all)
    cfg.safe_write_json(dest / SUMMARY_FILE, summary)
    return summary


# --------------------------------------------------------------------------- L1


def _cell(row: dict, spec) -> list[str]:
    cols = spec if isinstance(spec, list) else [spec]
    vals = []
    for c in cols:
        v = row.get(c)
        if v is None:
            continue
        v = str(v).strip()
        if v and v.lower() not in ("nan", "none", "<na>", "null"):
            vals.append(v)
    return vals


def _join(row: dict, spec, sep: str = " ") -> str:
    return sep.join(_cell(row, spec)) if spec else ""


def _iso(value: str, tz: str) -> str:
    import pandas as pd

    if not value:
        return ""
    try:
        t = pd.Timestamp(value)
    except (ValueError, TypeError):
        try:
            t = pd.Timestamp(float(value), unit="s")  # epoch seconds
        except (ValueError, TypeError, OverflowError):
            return ""
    if pd.isna(t):
        return ""
    if t.tzinfo is None:
        try:
            t = t.tz_localize(tz)
        except Exception:  # noqa: BLE001 - unknown zone: UTC
            t = t.tz_localize("UTC")
    return t.tz_convert("UTC").isoformat()


class _Fmt(dict):
    def __missing__(self, key):
        return ""


def _url(row: dict, src: dict) -> str:
    if src["columns"].get("url"):
        return _join(row, src["columns"]["url"])
    if src["url_template"]:
        try:
            return src["url_template"].format_map(
                _Fmt({k: ("" if v is None else v) for k, v in row.items()})
            )
        except (ValueError, IndexError, AttributeError):
            return ""
    return ""


def _contact_key(email: str, phone: str, name: str) -> str:
    if email:
        return "e:" + email.lower()
    # the shared normaliser (phone_country_code): national and international forms agree
    digits = re.sub(r"\D", "", normalize_phone(phone) or phone)
    if digits:
        return "p:" + digits
    return "n:" + re.sub(r"\s+", " ", name.strip().lower())


def build_frames(settings: dict, dest: Path):
    """(contacts DataFrame, interactions DataFrame, stats) from raw/*.parquet."""
    import pandas as pd

    contacts: dict[str, dict] = {}
    interactions: list[dict] = []
    stats = {"sources_read": 0, "sources_missing": [], "contacts_rows": 0, "interactions_rows": 0}
    for src in settings["sources"]:
        p = Path(dest) / RAW_DIR / f"{src['id']}.parquet"
        if not p.exists():
            stats["sources_missing"].append(src["id"])
            continue
        df = pd.read_parquet(p)
        stats["sources_read"] += 1
        m = src["columns"]
        tz = src["timezone"]
        for row in df.astype(object).where(df.notna(), None).to_dict("records"):
            if src["intake"] == "contacts":
                email = _join(row, m.get("email")).lower() if m.get("email") else ""
                if email and "@" not in email:
                    email = ""
                name = _join(row, m.get("name"))
                phone = _join(row, m.get("phone"))
                if not (email or name or phone):
                    continue
                stats["contacts_rows"] += 1
                rec = {
                    "source": SOURCE_ID,
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "company": _join(row, m.get("company")),
                    "title": _join(row, m.get("title")),
                    "first_seen": _iso(_join(row, m.get("first_seen")), tz)
                    if m.get("first_seen")
                    else "",
                    "last_seen": _iso(_join(row, m.get("last_seen")), tz)
                    if m.get("last_seen")
                    else "",
                    "interactions": 0,
                    "url": _url(row, src),
                }
                if m.get("interactions"):
                    try:
                        rec["interactions"] = max(0, int(float(_join(row, m["interactions"]) or 0)))
                    except ValueError:
                        rec["interactions"] = 0
                k = _contact_key(email, phone, name)
                old = contacts.get(k)
                if old is None:
                    contacts[k] = rec
                else:
                    for f in ("name", "email", "phone", "company", "title", "url"):
                        if not old[f] and rec[f]:
                            old[f] = rec[f]
                    old["interactions"] += rec["interactions"]
                    if rec["first_seen"] and (
                        not old["first_seen"] or rec["first_seen"] < old["first_seen"]
                    ):
                        old["first_seen"] = rec["first_seen"]
                    if rec["last_seen"] and rec["last_seen"] > old["last_seen"]:
                        old["last_seen"] = rec["last_seen"]
            else:
                ts = _iso(_join(row, m.get("ts")), tz)
                title = _join(row, m.get("title"))
                if not ts or not title:
                    continue
                stats["interactions_rows"] += 1
                kind = (_join(row, m.get("kind")) or src["kind"]).lower()
                role = (_join(row, m.get("owner_role")) or src["owner_role"]).lower()
                parts: list[str] = []
                for v in _cell(row, m.get("participants")) if m.get("participants") else []:
                    for piece in v.split(PARTICIPANT_SEP):
                        piece = piece.strip()
                        if piece and piece not in parts:
                            parts.append(piece)
                interactions.append(
                    {
                        "source": SOURCE_ID,
                        "ts": ts,
                        "kind": kind if kind in KINDS else "record",
                        "title": title[:300],
                        "text": _join(row, m.get("text"), "\n")[:TEXT_MAX] if m.get("text") else "",
                        "participants": PARTICIPANT_SEP.join(parts),
                        "owner_role": role if role in OWNER_ROLES else "other",
                        "due": _iso(_join(row, m.get("due")), tz) if m.get("due") else "",
                        "url": _url(row, src),
                        "status": (
                            _join(row, m.get("status")) if m.get("status") else src["status"]
                        ).lower(),
                    }
                )
    # Interactions that name a known contact by email count for that contact.
    for it in interactions:
        for p in it["participants"].split(PARTICIPANT_SEP):
            c = contacts.get("e:" + p.strip().lower()) if "@" in p else None
            if c is None:
                continue
            c["interactions"] += 1
            if not c["first_seen"] or it["ts"] < c["first_seen"]:
                c["first_seen"] = it["ts"]
            if it["ts"] > c["last_seen"]:
                c["last_seen"] = it["ts"]
    cdf = pd.DataFrame(list(contacts.values()), columns=["source", *CONTACT_FIELDS])
    cdf["interactions"] = cdf["interactions"].astype("int64")
    idf = pd.DataFrame(interactions, columns=["source", *INTERACTION_FIELDS])
    # status is optional in the contract. Written only when a source declares
    # it: an all-empty column would silence the kernel's warning that, without
    # a status, assigned or dated items all stay open.
    if not any(
        s["intake"] == "interactions" and (s["columns"].get("status") or s["status"])
        for s in settings["sources"]
    ):
        idf = idf.drop(columns=["status"])
    stats["contacts"] = int(len(cdf))
    stats["interactions"] = int(len(idf))
    return cdf, idf, stats


def write_frames(settings: dict, dest: Path) -> dict:
    cdf, idf, stats = build_frames(settings, dest)
    out = Path(dest) / PROCESSED_DIR
    cfg.safe_write_parquet(cdf, out / CONTACTS_FILE, index=False)
    cfg.safe_write_parquet(idf, out / INTERACTIONS_FILE, index=False)
    return stats
