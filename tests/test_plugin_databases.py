"""Databases plugin (tools/databases/): no real account, no network.

SQLite runs for real on a temporary file (standard library). PostgreSQL and
MySQL are checked against fake psycopg / pymysql / duckdb modules that record
what the plugin sends, so the read-only settings, the incremental wrapper and
the redaction of connection strings are verified without a server.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "tools" / "databases"
for p in (DB, ROOT / "tools", ROOT / "tools" / "cross-source"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import db_reader as dr  # noqa: E402
import plugin_intake  # noqa: E402

PW = "s3cr3t-Pa55"


# --------------------------------------------------------------------------- fixtures


def make_sqlite(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE people (
            id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT,
            phone TEXT, company_id INTEGER, role TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY, person_email TEXT, subject TEXT, body TEXT,
            created_at TEXT, due_at TEXT, done INTEGER
        );
        INSERT INTO companies VALUES (1, 'Demo Corp'), (2, 'Sample Ltd');
        INSERT INTO people VALUES
            (1, 'Ada', 'Demo', 'ada@demo.example', '+1 555 0100', 1, 'CTO', '2025-01-02 09:00:00', '2026-01-01 10:00:00'),
            (2, 'Bo', 'Sample', 'BO@sample.example', NULL, 2, 'Buyer', '2025-03-04 09:00:00', '2026-02-01 10:00:00'),
            (3, 'Cy', 'Nomail', NULL, '+1 555 0199', NULL, NULL, '2025-05-06 09:00:00', '2026-03-01 10:00:00'),
            (4, NULL, NULL, NULL, NULL, 1, NULL, '2025-05-06 09:00:00', '2026-03-02 10:00:00');
        INSERT INTO notes VALUES
            (1, 'ada@demo.example', 'Kickoff call', 'Agenda; DELETE nothing', '2026-01-10 15:00:00', '2026-01-20 00:00:00', 0),
            (2, 'bo@sample.example', 'Quote sent', '', '2026-02-10 15:00:00', NULL, 1);
        """
    )
    con.commit()
    con.close()
    return path


PEOPLE_Q = (
    "SELECT p.id, p.first_name, p.last_name, p.email, p.phone, c.name AS company, p.role, "
    "p.created_at, p.updated_at FROM people p LEFT JOIN companies c ON c.id = p.company_id;"
)
NOTES_Q = "SELECT id, person_email, subject, body, created_at, due_at, CASE WHEN done = 1 THEN 'done' ELSE 'open' END AS status FROM notes"


def raw_settings(db_path: Path, **over) -> dict:
    s = {
        "_help": "demo",
        "connections": {"crm": {"engine": "sqlite", "path": str(db_path)}},
        "sources": [
            {
                "id": "crm-people",
                "connection": "crm",
                "intake": "contacts",
                "query": PEOPLE_Q,
                "columns": {
                    "name": ["first_name", "last_name"],
                    "email": "email",
                    "phone": "phone",
                    "company": "company",
                    "title": "role",
                    "first_seen": "created_at",
                    "last_seen": "updated_at",
                },
                "key": "id",
                "cursor": "updated_at",
                "url_template": "https://crm.example/people/{id}",
            },
            {
                "id": "crm-notes",
                "connection": "crm",
                "intake": "interactions",
                "query": NOTES_Q,
                "columns": {
                    "ts": "created_at",
                    "title": "subject",
                    "text": "body",
                    "participants": "person_email",
                    "due": "due_at",
                    "status": "status",
                },
                "kind": "record",
                "owner_role": "author",
                "key": ["id"],
            },
        ],
    }
    s.update(over)
    return s


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def sqlite_db(tmp_path):
    return make_sqlite(tmp_path / "crm.sqlite")


# --------------------------------------------------------------------------- guard


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from people;",
        "  WITH x AS (SELECT 1 AS a) SELECT a FROM x ;  -- trailing note; with semicolon",
        "SELECT 'DELETE FROM t; DROP TABLE t' AS s",
        'SELECT "update", "insert" FROM t',
        "SELECT replace(name, 'a', 'b') FROM t",
        "(SELECT 1) UNION (SELECT 2)",
        "SELECT created_at, updated_at, deleted_flag FROM t",
        "SELECT 1 /* ; insert */ AS a",
    ],
)
def test_guard_accepts_reads(sql):
    out = dr.check_select(sql, "sqlite")
    assert not out.rstrip().endswith(";")


@pytest.mark.parametrize(
    "sql,engine,why",
    [
        ("INSERT INTO t VALUES (1)", "sqlite", "SELECT or WITH"),
        ("SELECT 1; DROP TABLE t", "sqlite", "one statement"),
        ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "postgres", "DELETE"),
        ("WITH u AS (UPDATE t SET a = 1 RETURNING a) SELECT a FROM u", "postgres", "UPDATE"),
        ("SELECT * INTO new_t FROM t", "postgres", "INTO"),
        ("SELECT * FROM t INTO OUTFILE '/tmp/x'", "mysql", "INTO"),
        ("SELECT * FROM t FOR UPDATE", "postgres", "row locks"),
        ("SELECT * FROM t FOR SHARE", "postgres", "row locks"),
        ("SELECT nextval('s')", "postgres", "nextval"),
        ("SELECT set_config('x', 'y', false)", "postgres", "set_config"),
        ("PRAGMA writable_schema = 1", "sqlite", "SELECT or WITH"),
        ("ATTACH 'x.db' AS x", "sqlite", "SELECT or WITH"),
        ("", "sqlite", "empty"),
        ("SELECT 'open", "sqlite", "unterminated"),
        ("SELECT 1 # ; DROP TABLE t", "postgres", "one statement"),
        ("SELECT postgres_execute('db', 'DROP TABLE t')", "postgres", "postgres_execute"),
        ("REPLACE INTO t VALUES (1)", "mysql", "SELECT or WITH"),
    ],
)
def test_guard_refuses_writes(sql, engine, why):
    with pytest.raises(dr.NotReadOnly) as e:
        dr.check_select(sql, engine)
    assert why.lower() in str(e.value).lower()


def test_guard_dialects():
    # '#' is a comment only in MySQL; $$ quoting only in PostgreSQL.
    assert dr.check_select("SELECT 1 # ; DROP TABLE t", "mysql") == "SELECT 1"
    assert dr.check_select("SELECT $q$ delete; drop $q$ AS s", "postgres").startswith("SELECT $q$")
    assert dr.check_select("SELECT 'it''s; insert' AS s", "mysql")
    assert dr.check_select("SELECT E'it\\'s' AS s, 'C:\\path' AS p", "postgres")
    assert dr.check_select("SELECT 1 /* a /* nested */ comment */ AS a", "postgres")
    assert dr.check_select("SELECT 1 /*+ MAX_EXECUTION_TIME(1000) */ AS a", "mysql")
    # A backslash-escaped quote reads differently under NO_BACKSLASH_ESCAPES: refused.
    with pytest.raises(dr.NotReadOnly, match="instead of"):
        dr.check_select("SELECT 'it\\'s; insert' AS s", "mysql")


@pytest.mark.parametrize(
    "sql,engine",
    [
        # MySQL runs the content of /*! ... */ comments.
        ("SELECT * FROM t /*! INTO OUTFILE '/tmp/x' */", "mysql"),
        ("SELECT * FROM t /*!50000 FOR UPDATE */", "mysql"),
        ("SELECT * FROM t /*M! FOR UPDATE */", "mysql"),
        # PostgreSQL block comments nest: the text after the inner */ is still a comment
        # for the server, and the quote that follows hid a second statement.
        ("SELECT 1 /* /* */ ' */ ; DELETE FROM t; SELECT 'x' -- '", "postgres"),
        # E'...' takes backslash escapes: \' does not close the string.
        ("SELECT E'\\' a ' ; DELETE FROM t; SELECT ' -- '", "postgres"),
        # The same query with standard_conforming_strings off.
        ("SELECT '\\' a ' ; DELETE FROM t; SELECT ' -- '", "postgres"),
        # NO_BACKSLASH_ESCAPES: '\' is a whole string and INTO OUTFILE is code.
        ("SELECT '\\' , 1 INTO OUTFILE '/tmp/x' -- '", "mysql"),
        # A backtick is an operator character in PostgreSQL, not a quote.
        ("SELECT 1 `; DELETE FROM t; --`", "postgres"),
        # Side-effect functions written as quoted names, or running query text.
        ("SELECT \"nextval\"('s')", "postgres"),
        ("SELECT `get_lock`('x', 1)", "mysql"),
        ("SELECT query_to_xml('DELETE FROM t RETURNING 1', true, false, '')", "postgres"),
    ],
)
def test_guard_bypasses_refused(sql, engine):
    with pytest.raises(dr.NotReadOnly):
        dr.check_select(sql, engine)


# --------------------------------------------------------------------------- settings


def test_settings_validation(sqlite_db):
    s = dr.load_settings(raw_settings(sqlite_db))
    assert [x["id"] for x in s["sources"]] == ["crm-people", "crm-notes"]
    assert s["connections"]["crm"]["env"] == "SBK_DB_URL_CRM"
    with pytest.raises(dr.ConfigError) as e:
        dr.load_settings({})
    assert str(e.value) == dr.NO_CONFIG_MSG
    bad = raw_settings(sqlite_db)
    bad["connections"]["shop"] = {"engine": "postgres", "url": f"postgresql://u:{PW}@h/db"}
    with pytest.raises(dr.ConfigError) as e:
        dr.load_settings(bad)
    assert "Keychain" in str(e.value) and PW not in str(e.value)
    bad = raw_settings(sqlite_db)
    bad["sources"][0]["query"] = "DELETE FROM people"
    with pytest.raises(dr.ConfigError, match="query refused"):
        dr.load_settings(bad)
    bad = raw_settings(sqlite_db)
    bad["sources"][0]["columns"]["nickname"] = "x"
    with pytest.raises(dr.ConfigError, match="unknown field"):
        dr.load_settings(bad)
    bad = raw_settings(sqlite_db)
    bad["sources"][0]["key"] = []
    with pytest.raises(dr.ConfigError, match='needs a "key"'):
        dr.load_settings(bad)
    bad = raw_settings(sqlite_db)
    bad["connections"]["crm"]["driver"] = "psycopg"
    with pytest.raises(dr.ConfigError, match="driver"):
        dr.load_settings(bad)


def test_resolve_secret_order(monkeypatch):
    import secrets_adapter

    conn = dr.load_settings(
        {
            "connections": {"shop": {"engine": "postgres"}},
            "sources": [
                {"id": "s", "connection": "shop", "query": "SELECT 1", "columns": {"name": "n"}}
            ],
        }
    )["connections"]["shop"]
    monkeypatch.setattr(
        secrets_adapter,
        "get_secret",
        lambda s, a: "from-keychain" if (s, a) == ("sbk-databases", "shop") else None,
    )
    monkeypatch.setenv("SBK_DB_URL_SHOP", "from-env")
    assert dr.resolve_secret(conn) == ("from-keychain", "keychain sbk-databases/shop")
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: None)
    assert dr.resolve_secret(conn) == ("from-env", "env SBK_DB_URL_SHOP")
    monkeypatch.delenv("SBK_DB_URL_SHOP")
    with pytest.raises(dr.NoSecret) as e:
        dr.resolve_secret(conn)
    assert "\n" not in str(e.value) and "sbk-databases/shop" in str(e.value)


# --------------------------------------------------------------------------- SQLite, for real


def test_sqlite_connection_is_read_only(sqlite_db):
    before = sha(sqlite_db)
    conn = dr.load_settings(raw_settings(sqlite_db))["connections"]["crm"]
    r = dr.open_reader(conn, str(sqlite_db))
    try:
        cols, rows, trunc = r.query("SELECT count(*) AS n FROM people")
        assert cols == ["n"] and rows == [(4,)] and not trunc
        # Past the guard, SQLite itself refuses (authorizer + mode=ro + query_only).
        for stmt in (
            "INSERT INTO companies VALUES (9, 'X')",
            "DELETE FROM people",
            "PRAGMA query_only = OFF",
            "ATTACH DATABASE ':memory:' AS other",
            "CREATE TABLE z (a)",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                r._db.execute(stmt)
        with pytest.raises(dr.NotReadOnly):
            r.query("DELETE FROM people")
    finally:
        r.close()
    assert sha(sqlite_db) == before


def test_sqlite_url_forms(tmp_path, sqlite_db):
    conn = {"name": "crm", "engine": "sqlite", "driver": "sqlite3", "path": "", "env": "X"}
    for s in (f"sqlite:///{sqlite_db}", sqlite_db.as_uri(), str(sqlite_db)):
        r = dr.open_reader(conn, s)
        assert r.query("SELECT 1 AS a")[1] == [(1,)]
        r.close()
    with pytest.raises(RuntimeError, match="no SQLite file"):
        dr.open_reader(conn, str(tmp_path / "missing.sqlite"))


def test_end_to_end_sqlite(tmp_path, sqlite_db):
    root = tmp_path / "data"
    dest = root / "databases"
    before = sha(sqlite_db)
    settings = dr.load_settings(raw_settings(sqlite_db))
    summary = dr.run_download(settings, dest)
    assert summary["errors"] == {}
    assert summary["sources"]["crm-people"]["mode"] == "full"
    assert summary["sources"]["crm-people"]["rows_total"] == 4
    assert (dest / "raw" / "crm-people.parquet").exists()
    state = json.loads((dest / dr.STATE_FILE).read_text())
    assert state["sources"]["crm-people"]["watermark"] == {
        "type": "str",
        "value": "2026-03-02 10:00:00",
    }
    on_disk = json.loads((dest / dr.SUMMARY_FILE).read_text())
    assert on_disk["sources"]["crm-notes"]["rows_read"] == 2

    stats = dr.write_frames(settings, dest)
    assert stats["contacts"] == 3  # the row with no name, email or phone is dropped
    c = pd.read_parquet(dest / "processed" / dr.CONTACTS_FILE)
    i = pd.read_parquet(dest / "processed" / dr.INTERACTIONS_FILE)
    assert list(c.columns) == list(plugin_intake.CONTACT_COLUMNS)
    assert list(i.columns) == [*plugin_intake.INTERACTION_COLUMNS, "status"]
    ada = c[c["email"] == "ada@demo.example"].iloc[0]
    assert ada["name"] == "Ada Demo" and ada["company"] == "Demo Corp" and ada["title"] == "CTO"
    assert ada["url"] == "https://crm.example/people/1"
    assert ada["first_seen"] == "2025-01-02T09:00:00+00:00"
    assert ada["interactions"] == 1  # one note names her email
    bo = c[c["email"] == "bo@sample.example"].iloc[0]
    assert bo["last_seen"] == "2026-02-10T15:00:00+00:00"  # the note is later than updated_at
    cy = c[c["name"] == "Cy Nomail"].iloc[0]
    assert cy["email"] == "" and cy["phone"] == "+1 555 0199"
    kick = i[i["title"] == "Kickoff call"].iloc[0]
    assert kick["kind"] == "record" and kick["owner_role"] == "author"
    assert kick["participants"] == "ada@demo.example" and kick["status"] == "open"
    assert kick["due"] == "2026-01-20T00:00:00+00:00"
    assert i[i["title"] == "Quote sent"].iloc[0]["status"] == "done"

    # The kernel loader reads both files without a warning.
    lc = plugin_intake.load_contacts(root)
    li = plugin_intake.load_interactions(root)
    assert (
        len(lc) == 3 and set(lc["plugin"]) == {"databases"} and set(lc["source"]) == {"databases"}
    )
    assert len(li) == 2
    assert sha(sqlite_db) == before


def test_incremental_and_full(tmp_path, sqlite_db):
    dest = tmp_path / "data" / "databases"
    settings = dr.load_settings(raw_settings(sqlite_db))
    dr.run_download(settings, dest)
    con = sqlite3.connect(sqlite_db)
    con.execute(
        "INSERT INTO people VALUES (5, 'Di', 'New', 'di@new.example', NULL, 2, NULL, '2026-04-01 09:00:00', '2026-04-01 09:00:00')"
    )
    con.execute("UPDATE people SET role = 'CEO', updated_at = '2026-04-02 09:00:00' WHERE id = 1")
    con.commit()
    con.close()
    s2 = dr.run_download(settings, dest, only=["crm-people"])
    res = s2["sources"]["crm-people"]
    # cursor >= last watermark: the boundary row again plus the two changed ones
    assert res["mode"] == "incremental" and res["rows_read"] == 3 and res["rows_total"] == 5
    raw = pd.read_parquet(dest / "raw" / "crm-people.parquet")
    assert raw.loc[raw["id"] == "1", "role"].item() == "CEO"
    assert "crm-notes" not in s2["sources"]
    s3 = dr.run_download(settings, dest, full=True, only=["crm-people"])
    assert (
        s3["sources"]["crm-people"]["mode"] == "full"
        and s3["sources"]["crm-people"]["rows_read"] == 5
    )
    # A changed query is a full re-read.
    raw2 = raw_settings(sqlite_db)
    raw2["sources"][0]["query"] = PEOPLE_Q.rstrip(";") + " WHERE p.id > 0"
    s4 = dr.run_download(dr.load_settings(raw2), dest, only=["crm-people"])
    assert s4["sources"]["crm-people"]["mode"] == "full"
    with pytest.raises(dr.ConfigError, match="unknown --source"):
        dr.run_download(settings, dest, only=["nope"])


def test_max_rows_and_missing_columns(tmp_path, sqlite_db):
    raw = raw_settings(sqlite_db)
    raw["sources"][0]["max_rows"] = 2
    raw["sources"][1]["key"] = ["no_such_column"]
    dest = tmp_path / "databases"
    summary = dr.run_download(dr.load_settings(raw), dest)
    assert summary["sources"]["crm-people"]["truncated"] is True
    assert summary["sources"]["crm-people"]["rows_total"] == 2
    assert "no_such_column" in summary["errors"]["crm-notes"]


def test_truncated_full_read_loses_nothing(tmp_path, sqlite_db):
    """max_rows cuts a full read: the next incremental runs pick up every row left out."""
    con = sqlite3.connect(sqlite_db)
    # Insert order differs from cursor order, so an unordered read would keep a random subset.
    con.execute("UPDATE people SET updated_at = '2026-09-01 10:00:00' WHERE id = 1")
    con.commit()
    con.close()
    raw = raw_settings(sqlite_db)
    raw["sources"][0]["max_rows"] = 2
    settings = dr.load_settings(raw)
    dest = tmp_path / "databases"
    s1 = dr.run_download(settings, dest, only=["crm-people"])
    assert s1["sources"]["crm-people"]["truncated"] is True
    for _ in range(3):
        dr.run_download(settings, dest, only=["crm-people"])
    got = pd.read_parquet(dest / "raw" / "crm-people.parquet")
    assert sorted(got["id"]) == ["1", "2", "3", "4"]


def test_status_column_only_when_declared(tmp_path, sqlite_db):
    raw = raw_settings(sqlite_db)
    del raw["sources"][1]["columns"]["status"]
    settings = dr.load_settings(raw)
    dest = tmp_path / "data" / "databases"
    dr.run_download(settings, dest)
    dr.write_frames(settings, dest)
    i = pd.read_parquet(dest / "processed" / dr.INTERACTIONS_FILE)
    # No status column: the kernel then warns that dated items all count as open.
    assert list(i.columns) == list(plugin_intake.INTERACTION_COLUMNS)
    raw["sources"][1]["status"] = "open"
    dr.write_frames(dr.load_settings(raw), dest)
    i = pd.read_parquet(dest / "processed" / dr.INTERACTIONS_FILE)
    assert set(i["status"]) == {"open"}


def test_watermark_types():
    from decimal import Decimal

    v = Decimal("12345678901234567890.000000001")
    assert dr.wm_unpack(dr.wm_pack(v)) == v  # exact, no float rounding
    assert dr.wm_literal(v) == "12345678901234567890.000000001"
    assert dr.wm_literal("it's") == "'it''s'"
    with pytest.raises(ValueError, match="backslash"):
        dr.wm_literal("a\\")


# --------------------------------------------------------------------------- fakes for servers


class FakeCursor:
    def __init__(self, log, rows=((1, "Ada", "2026-01-01"),), cols=("id", "name", "updated_at")):
        self.log = log
        self.rows = list(rows)
        self.description = [(c,) for c in cols]

    def execute(self, sql, params=None):
        self.log.append(("execute", sql, params))
        return self

    def fetchmany(self, n):
        out, self.rows = self.rows[:n], self.rows[n:]
        return out

    def close(self):
        self.log.append(("close_cursor",))


class FakeConn:
    def __init__(self, log):
        self.log = log
        self._ro = None

    @property
    def read_only(self):
        return self._ro

    @read_only.setter
    def read_only(self, v):
        self.log.append(("read_only", v))
        self._ro = v

    def cursor(self, name=None):
        self.log.append(("cursor", name))
        return FakeCursor(self.log)

    def rollback(self):
        self.log.append(("rollback",))

    def commit(self):  # pragma: no cover - must never be called
        raise AssertionError("commit called")

    def close(self):
        self.log.append(("close",))


def pg_conn():
    return {
        "name": "shop",
        "engine": "postgres",
        "driver": "psycopg",
        "path": "",
        "env": "SBK_DB_URL_SHOP",
    }


def my_conn(driver="pymysql"):
    return {
        "name": "legacy",
        "engine": "mysql",
        "driver": driver,
        "path": "",
        "env": "SBK_DB_URL_LEGACY",
    }


def test_psycopg_read_only_and_incremental(monkeypatch):
    log: list = []
    fake = types.SimpleNamespace(
        connect=lambda conninfo, **kw: (log.append(("connect", conninfo, kw)), FakeConn(log))[1]
    )
    monkeypatch.setattr(
        dr, "_import", lambda name: fake if name == "psycopg" else pytest.fail(name)
    )
    r = dr.open_reader(pg_conn(), f"postgresql://demo:{PW}@db.example/crm")
    assert ("read_only", True) in log
    cols, rows, _ = r.query(
        "SELECT id, name, updated_at FROM people WHERE name LIKE 'A%'", "updated_at", "2026-01-01"
    )
    ex = [e for e in log if e[0] == "execute"][-1]
    assert (
        "LIKE 'A%%'" in ex[1] and 'sbk_q."updated_at" >= %s' in ex[1] and ex[2] == ("2026-01-01",)
    )
    assert log[-1] == ("rollback",) and cols == ["id", "name", "updated_at"] and rows
    # A named (server-side) cursor: rows in batches, never the whole result in memory.
    assert ("cursor", "sbk_read") in log
    # Without parameters the query is sent as written (no %% doubling).
    r.query("SELECT 'A%' AS p")
    assert [e for e in log if e[0] == "execute"][-1] == ("execute", "SELECT 'A%' AS p", None)
    # A full read of a source with a cursor is ordered by it, still without parameters.
    r.query("SELECT 'A%' AS p, updated_at FROM people", "updated_at", None)
    ex = [e for e in log if e[0] == "execute"][-1]
    assert ex[2] is None and "'A%'" in ex[1] and ex[1].endswith('ORDER BY sbk_q."updated_at"')
    assert "WHERE" not in ex[1]
    r.close()


def test_pymysql_session_read_only(monkeypatch):
    log: list = []
    cursors = types.SimpleNamespace(SSCursor=object)
    fake = types.SimpleNamespace(
        connect=lambda **kw: (log.append(("connect", kw)), FakeConn(log))[1]
    )
    monkeypatch.setattr(
        dr, "_import", lambda name: {"pymysql": fake, "pymysql.cursors": cursors}[name]
    )
    r = dr.open_reader(my_conn(), "mysql://demo:p%40ss%3Aword@db.example:3307/crm")
    kw = log[0][1]
    assert kw["init_command"] == "SET SESSION TRANSACTION READ ONLY"
    assert kw["password"] == "p@ss:word" and kw["port"] == 3307 and kw["database"] == "crm"
    assert kw["cursorclass"] is object and kw["autocommit"] is False
    r.query("SELECT id, name, updated_at FROM people", "id", 7)
    ex = [e for e in log if e[0] == "execute"]
    assert ex[0][1] == "START TRANSACTION READ ONLY"
    assert "sbk_q.`id` >= %s" in ex[1][1] and ex[1][2] == (7,)
    assert ("rollback",) in log


class FakeDuck:
    def __init__(self, log, fail_attach=None):
        self.log = log
        self.fail_attach = fail_attach

    def execute(self, sql, *a):
        self.log.append(sql)
        if sql.startswith("ATTACH") and self.fail_attach:
            raise RuntimeError(self.fail_attach)
        if sql.startswith("SET"):
            return self
        return FakeCursor([], rows=[(1,)], cols=("ok",))

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_budget(monkeypatch):
    """The DuckDB path asks sbk_resources for a memory budget; not on the test machine."""
    monkeypatch.setitem(
        sys.modules, "sbk_resources", types.SimpleNamespace(configure_duckdb=lambda con: {})
    )


def test_duckdb_postgres_and_redaction(monkeypatch):
    log: list = []
    secret = f"postgresql://demo:{PW}@db.example:5432/crm?sslmode=require"
    fake = types.SimpleNamespace(connect=lambda path: FakeDuck(log))
    monkeypatch.setattr(dr, "_import", lambda name: fake)
    conn = dict(pg_conn(), driver="duckdb")
    r = dr.open_reader(conn, secret)
    attach = [s for s in log if s.startswith("ATTACH")][0]
    assert "READ_ONLY" in attach and "TYPE postgres" in attach
    assert "options=-c%20default_transaction_read_only%3Don" in attach
    r.query("SELECT name FROM people WHERE name = 'O''Neil'", "id", 5)
    q = log[-1]
    assert q.startswith("SELECT * FROM postgres_query('sbk_src', '") and "O''''Neil" in q
    assert 'sbk_q."id" >= 5' in q
    # A failing ATTACH may echo the connection string: the password never comes out.
    fake2 = types.SimpleNamespace(
        connect=lambda path: FakeDuck([], fail_attach=f"could not connect: {secret}")
    )
    monkeypatch.setattr(dr, "_import", lambda name: fake2)
    with pytest.raises(RuntimeError) as e:
        dr.open_reader(conn, secret)
    assert PW not in str(e.value) and "***" in str(e.value)


def test_duckdb_mysql_conninfo(monkeypatch):
    log: list = []
    monkeypatch.setattr(
        dr, "_import", lambda name: types.SimpleNamespace(connect=lambda p: FakeDuck(log))
    )
    r = dr.open_reader(my_conn("duckdb"), "mysql://demo:pw%20x@db.example/crm")
    attach = [s for s in log if s.startswith("ATTACH")][0]
    assert (
        "TYPE mysql, READ_ONLY" in attach
        and "host=db.example" in attach
        and "database=crm" in attach
    )
    r.query("SELECT 1 AS ok")
    assert log[-1].startswith("SELECT * FROM mysql_query('sbk_src', ")


def test_pg_conninfo_variants():
    assert dr.pg_read_only_conninfo("dbname=crm host=db.example") == (
        "dbname=crm host=db.example options='-c default_transaction_read_only=on'"
    )
    out = dr.pg_read_only_conninfo("dbname=crm options='-c search_path=app'")
    assert out == "dbname=crm options='-c search_path=app -c default_transaction_read_only=on'"
    out = dr.pg_read_only_conninfo(
        "postgres://u@h/db?options=-c%20search_path%3Dapp&sslmode=require"
    )
    assert (
        "sslmode=require" in out
        and "options=-c%20search_path%3Dapp%20-c%20default_transaction_read_only%3Don" in out
    )


def test_driver_missing_is_one_line(monkeypatch):
    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr(dr, "_import", boom)
    with pytest.raises(dr.DriverMissing) as e:
        dr.open_reader(pg_conn(), "postgresql://h/db")
    msg = str(e.value)
    assert (
        "\n" not in msg and "uv add 'psycopg[binary]>=3.2'" in msg and '"driver": "duckdb"' in msg
    )


def test_redact():
    s = f"host=h user=u password={PW} dbname=d"
    assert PW not in dr.redact(f"error near {s}", s)
    assert PW not in dr.redact(f"postgresql://u:{PW}@h/db failed", None)
    # The DuckDB key=value form escapes a quote in the password; that form is redacted too.
    url = "mysql://demo:pa%27ss%20word@db.example/crm"
    echoed = f"connect failed: {dr.mysql_duckdb_conninfo(url)}"
    out = dr.redact(echoed, url)
    assert "pa\\'ss word" not in out and "ss word" not in out


def test_no_write_call_in_code():
    src = (DB / "db_reader.py").read_text()
    assert ".commit(" not in src and "executemany" not in src and "executescript" not in src


# --------------------------------------------------------------------------- scripts


def run_script(name, *args, env_extra=None, cwd=ROOT):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("SBK_DB_URL_", "SBK_CONFIG", "SBK_DATA_ROOT"))
    }
    env["SBK_CONTAINERIZED"] = "1"  # no Keychain lookups from the test
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(DB / name), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=120,
    )


@pytest.mark.parametrize("name", ["db-l0-download.py", "db-l1-enrich.py"])
def test_help(name):
    p = run_script(name, "--help")
    assert p.returncode == 0 and "Traceback" not in p.stderr and "usage" in p.stdout


def test_no_config_and_no_credentials(tmp_path):
    cfgf = tmp_path / "sbk.config.json"
    # The owner fields are set in both configs below, so the kernel's "no owner" warning
    # stays out of the one-line error checks.
    owner = {"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}
    cfgf.write_text(json.dumps({**owner, "databases": {}}))
    env = {"SBK_CONFIG": str(cfgf), "SBK_DATA_ROOT": str(tmp_path / "root")}
    for name in ("db-l0-download.py", "db-l1-enrich.py"):
        p = run_script(name, env_extra=env)
        assert p.returncode == 1 and "Traceback" not in p.stderr
        assert p.stderr.strip() == dr.NO_CONFIG_MSG
    cfgf.write_text(
        json.dumps(
            {
                **owner,
                "databases": {
                    "connections": {"shop": {"engine": "postgres"}},
                    "sources": [
                        {
                            "id": "shop-people",
                            "connection": "shop",
                            "query": "SELECT 1",
                            "columns": {"name": "n"},
                        }
                    ],
                },
            }
        )
    )
    p = run_script("db-l0-download.py", env_extra=env)
    lines = p.stderr.strip().splitlines()
    assert p.returncode == 1 and len(lines) == 1 and "Traceback" not in p.stderr
    assert "has no connection string" in lines[0] and "SBK_DB_URL_SHOP" in lines[0]
    p = run_script("db-l0-download.py", "--dry-run", env_extra=env)
    assert p.returncode == 1 and "Traceback" not in p.stderr and "SBK_DB_URL_SHOP" in p.stderr


def test_scripts_end_to_end(tmp_path, sqlite_db):
    cfgf = tmp_path / "sbk.config.json"
    cfgf.write_text(json.dumps({"databases": raw_settings(sqlite_db)}))
    env = {"SBK_CONFIG": str(cfgf), "SBK_DATA_ROOT": str(tmp_path / "root")}
    p = run_script("db-l0-download.py", "--list", env_extra=env)
    assert p.returncode == 0 and "crm-people: contacts from crm (sqlite/sqlite3)" in p.stdout
    p = run_script("db-l0-download.py", "--dry-run", env_extra=env)
    assert p.returncode == 0, p.stderr
    assert not (tmp_path / "root" / "databases" / "raw").exists()
    p = run_script("db-l1-enrich.py", env_extra=env)
    assert p.returncode == 1 and "run tools/databases/db-l0-download.py first" in p.stderr
    p = run_script("db-l0-download.py", env_extra=env)
    assert p.returncode == 0, p.stderr
    p = run_script("db-l1-enrich.py", env_extra=env)
    assert p.returncode == 0, p.stderr
    out = tmp_path / "root" / "databases" / "processed"
    assert len(pd.read_parquet(out / dr.CONTACTS_FILE)) == 3
    assert len(pd.read_parquet(out / dr.INTERACTIONS_FILE)) == 2
