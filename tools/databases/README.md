<!-- generated from docs/CONNECTING.md -->
# Databases: SQLite, PostgreSQL, MySQL (`db-`)

**Status** partial · registry `a_richiesta`, every 30 days (`tools/sorgenti.py`, entry `databases`): the
download runs on request only, it is not in the scheduled download (`xs-l0-refresh.py` lists it among
the manual sources). `xs-pipeline-run.py --ingest` runs `db-l1-enrich.py` (step `databases`), and the
kernel reads its two files through the generic intake (`tools/cross-source/plugin_intake.py`). SQLite
is tested end to end on a temporary file (download, mapping, read by the kernel's intake); PostgreSQL and
MySQL are tested only against fake drivers that record what the plugin sends (no real server yet).

**Reads** people, and the company they belong to, from a database you own or run: SQLite, PostgreSQL
or MySQL. You write one query per source (`SELECT` or `WITH` only) and say which result column is
the name, the email, the phone, the company, the title, the first and last date you saw the person.
A second kind of source maps rows to events (a notes table, an orders table): date, title, text,
the people involved, a due date, a status. Companies come in as the `company` of each person: join
your companies table in the query. Nothing is ever written to your database.

**You need** the connection string of your own database, and for PostgreSQL or MySQL one Python
driver. SBK does not install either driver: you add the one you use.
- SQLite: nothing, Python's standard library reads it.
- PostgreSQL: `uv add 'psycopg[binary]>=3.2'`
  (https://www.psycopg.org/psycopg3/docs/basic/install.html). Or set `"driver": "duckdb"` on the
  connection: DuckDB is already an SBK dependency, and on first use it downloads its `postgres`
  extension from DuckDB's official extension repository
  (https://duckdb.org/docs/stable/core_extensions/postgres.html), so that first run needs network.
- MySQL: `uv add 'pymysql>=1.1'`
  (https://pymysql.readthedocs.io/en/latest/user/installation.html). Or `"driver": "duckdb"`, which
  uses DuckDB's `mysql` extension (https://duckdb.org/docs/stable/core_extensions/mysql.html).
- Without the driver the download stops with one line that names the `uv add` command.

**Create it** The safest setup is a database user of your own that can only read the tables you map.
This is optional, the plugin is read-only anyway, but it is the one layer that does not depend on the
plugin's code.
- PostgreSQL, as the owner of the database: `CREATE ROLE sbk_reader LOGIN PASSWORD '...';` then
  `GRANT SELECT ON people, companies TO sbk_reader;` (and `GRANT USAGE ON SCHEMA ...` if the tables
  are not in `public`). Syntax: https://www.postgresql.org/docs/current/sql-grant.html. Your
  connection string is then `postgresql://sbk_reader:PASSWORD@HOST:5432/DBNAME` or the key=value
  form `host=HOST dbname=DBNAME user=sbk_reader password=PASSWORD`
  (https://www.postgresql.org/docs/current/libpq-connect.html; percent-encode special characters in
  a URI).
- MySQL: `CREATE USER 'sbk_reader'@'%' IDENTIFIED BY '...';` then
  `GRANT SELECT ON crm.* TO 'sbk_reader'@'%';` (https://dev.mysql.com/doc/refman/8.4/en/grant.html).
  Connection string: `mysql://sbk_reader:PASSWORD@HOST:3306/DBNAME` (percent-encode `@`, `:`, `/`
  in the password); `?ssl_ca=/path/ca.pem` is passed on to the driver.
- SQLite: the path of the file (or `sqlite:///path`). It is opened read-only.

**Where the code looks** Keychain `sbk-databases/<connection name>` first, then the env variable
`SBK_DB_URL_<NAME>` (connection name in uppercase, every other character turned into `_`; another
name with `"env"` on the connection), `tools/databases/db_reader.py:548` (names at `:104` and `:105`;
the lines are in `.env.example`, section "Databases"). For SQLite, a `"path"` in sbk.config.json comes
first. A connection string written in sbk.config.json (`url`, `dsn`, `password`, ...) is refused with an
error. Both scripts load `.env` by themselves.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-databases', 'shop', getpass.getpass('connection string: '))"
```

**sbk.config.json** section `databases` (`tools/databases/db_reader.py:418`). `sbk.config.example.json`
ships `connections` and `sources` empty, with their `_help`, and a worked example under
`_example_connections` and `_example_sources` (a SQLite people table joined to its companies, and a
notes table as events) to copy and change:
- `connections`: `{"<name>": {"engine": "sqlite" | "postgres" | "mysql", "driver": ..., "path": ..., "env": ...}}`.
  `driver` is optional: `psycopg` (default) or `duckdb` for PostgreSQL, `pymysql` (default) or `duckdb` for MySQL.
- `sources`: a list, each with `id` (lowercase, used for the file name), `connection`, `intake`
  (`contacts` or `interactions`), `query`, and `columns`, a map from intake fields to result columns.
  Contacts: `name`, `email`, `phone`, `company`, `title`, `first_seen`, `last_seen`, `interactions`,
  `url` (at least one of name, email, phone). Interactions: `ts`, `title` (both required), `text`,
  `participants`, `owner_role`, `due`, `url`, `kind`, `status`. A list of columns is joined (a space
  for names, `|||` for participants).
- Optional per source: `key` (column or columns unique per row), `cursor` (a column that only grows,
  such as `updated_at` or an id; needs `key`), `url_template` (`"https://crm.example/people/{id}"`),
  `kind` (default `record`), `owner_role` (default `other`), `status` (fixed value), `timezone` for
  dates written without one (default `UTC`), `max_rows` (default 200000, or `max_rows_per_source`).
- If `enabled_sources` is not empty, list `databases` there.

**Download**
```bash
uv run python tools/databases/db-l0-download.py --list      # the sources as understood, no connection
uv run python tools/databases/db-l0-download.py --dry-run   # opens each connection read-only, runs SELECT 1, writes nothing
uv run python tools/databases/db-l0-download.py             # runs every query
uv run python tools/databases/db-l0-download.py --full --source crm-people
uv run python tools/databases/db-l1-enrich.py               # applies the column map, writes the two intake files (also run by --ingest)
```
A changed column map needs only the L1, not a new download.

**Check** `<data root>/databases/download-summary.json` (rows read and kept per source, full or
incremental, errors with passwords removed), `<data root>/databases/raw/<source>.parquet`; after the
L1, `<data root>/databases/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`; then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.

**Limits**
- Read-only, how far it goes. Every query is checked first: one statement, it starts with `SELECT` or
  `WITH`, and words that write or lock (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `INTO`, `FOR UPDATE`,
  `FOR SHARE`, ...) and a list of functions with side effects (`nextval`, `setval`, `set_config`,
  `lo_import`, `dblink_exec`, `pg_terminate_backend`, `get_lock`, `load_extension`, `query_to_xml`,
  which runs the query text it is given, https://www.postgresql.org/docs/current/functions-xml.html,
  ...) are refused outside quotes, and also when written as a quoted name. A column really named like
  one of those words must be quoted. MySQL `/*! ... */` comments are refused, because MySQL runs their
  content (https://dev.mysql.com/doc/refman/8.4/en/comments.html); PostgreSQL nested `/* */` comments
  and `E'...'` strings are read the way PostgreSQL reads them
  (https://www.postgresql.org/docs/current/sql-syntax-lexical.html). A string with a backslash before a
  quote (`'it\'s'`) is refused: whether the server reads it as an escape depends on a setting the
  plugin cannot see (MySQL `NO_BACKSLASH_ESCAPES`, PostgreSQL `standard_conforming_strings`); write
  `'it''s'` instead. Then the connection:
  SQLite is opened with `mode=ro`, `PRAGMA query_only = ON` and an authorizer that allows only reads
  (https://www.sqlite.org/uri.html, https://www.sqlite.org/pragma.html#pragma_query_only,
  https://www.sqlite.org/c3ref/set_authorizer.html); PostgreSQL with psycopg runs every transaction
  READ ONLY (`connection.read_only`, https://www.psycopg.org/psycopg3/docs/api/connections.html) and
  reads through a server-side cursor, so rows arrive in batches instead of the whole result in memory
  and `DECLARE` accepts one `SELECT` only (https://www.psycopg.org/psycopg3/docs/advanced/cursors.html,
  https://www.postgresql.org/docs/current/sql-declare.html), and
  through DuckDB it attaches with `READ_ONLY` and adds `-c default_transaction_read_only=on` to the
  libpq options; MySQL with PyMySQL sets `SET SESSION TRANSACTION READ ONLY` at connect and
  `START TRANSACTION READ ONLY` before the query (https://dev.mysql.com/doc/refman/8.4/en/set-transaction.html).
  PostgreSQL itself says a read-only transaction "does not prevent all writes to disk"
  (https://www.postgresql.org/docs/current/sql-set-transaction.html), and the MySQL route through
  DuckDB has no session setting at all (`mysql_query` passes the query to the server as written): for
  those cases the user with only SELECT is what really protects the data.
- The DuckDB route was checked only against a fake DuckDB module: whether DuckDB's `postgres`
  extension passes the libpq `options` through, and how its `mysql` extension wants a password with
  spaces or quotes written, is not verified on a real server. DuckDB warns that a failed ATTACH can
  print the full connection string; the plugin replaces the connection string and its password with
  `***` in every message and in `download-summary.json`, but DuckDB's own logs are outside its reach.
- Incremental runs read rows with `cursor >= last value seen` and merge them by `key`. Rows deleted in
  your database stay in the download until `--full`. A cursor that can go backwards (a date someone
  edits by hand) misses rows; use `--full` from time to time. A changed query is re-read in full.
  Rows whose cursor is NULL are read by a full run only. With the `duckdb` driver a text cursor value
  that contains a backslash stops the incremental run with an error (it cannot be passed safely); run
  `--full` or pick another cursor column.
- At most `max_rows` rows per source per run (200000 by default); the summary says `truncated` when the
  limit was hit. A source with a cursor is always read in cursor order, so a cut run keeps the lowest
  values and the next run continues from there without skipping rows. If more than `max_rows` rows
  share the same cursor value, the runs cannot get past it: raise `max_rows` for that source. Binary
  columns are dropped; every other value is stored as text.
- `status` is written to `plugin-interactions.parquet` only when a source maps or fixes it. Without
  it the kernel counts every assigned or dated event as open and says so once per file; an events
  source with no status next to one with a status gets an empty status, which counts as open.
- If a contacts source maps an `interactions` count and an events source also names the same person,
  both add up: map the count or the events, not both, when the count already includes those events.
- A table of companies alone cannot enter: the generic intake has people and events, not companies.
  Join the company into the people query. A row without name, email and phone is dropped.
- People found only inside an event (`participants`) are not created as contacts; they only add to the
  count and dates of a contact with the same email.
- `--dry-run` with an unknown `--source` ignores it silently; the normal run refuses it with one line.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#databases](../../docs/CONNECTING.md#databases). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
