# SBK — Plugins and sources

In SBK every **source** is a plugin: a folder under `tools/` that knows how to download (L0) and
normalise (L1) one kind of data. Turn on only the ones you use. The **kernel** (pipeline, entity
resolution, knowledge layer) is the same for everyone.

## The plugin model

A typical plugin has these stages, with a short prefix per source (for example `em-` for email,
`sl-` for Slack):

```
tools/<source>/
  <p>-l0-download.py   # downloads the raw data into <data root>/<source>/raw/
  <p>-l1-enrich.py     # normalises and enriches it
  README.md            # what it needs, which keys, how it connects
```

The **registry** of all sources is `tools/sorgenti.py`: it declares the *nature* of each one and
its rhythm in days. That is where a source becomes known to the system. The natures keep the
registry's own names:

| Nature | Meaning |
|---|---|
| `continua` | continuous: new data keeps arriving; silence longer than the rhythm is a warning |
| `periodica` | periodic: it changes now and then, so it is checked against a longer rhythm |
| `a_richiesta` | on request: it runs only when you start it, with a reminder once the rhythm has passed |
| `spot` | one-off: data arrives when there is something new, and its age does not matter |
| `chiusa` | closed: no longer read; the data already fetched is kept |
| `da_costruire` | declared, not built yet: a source you plan to add, listed by the pipeline dry run |

A source you download but never re-read (no L1) is the quietest way to believe you have data you do
not have: the registry says so instead of leaving it implicit.

## How to turn on a source

**The guide for every plugin is [CONNECTING.md](CONNECTING.md)**: what it reads, which credential,
where you create it, the exact env variable or Keychain entry, the first command, how to check.

1. List it in `enabled_sources` in `sbk.config.json`, by folder name: the pipeline runs the L1 step
   only for the listed sources (an empty list runs every source that has data).
2. Create your own access on the vendor's side (an export, a personal token, or your own app) and
   put the secret in `.env` or the Keychain, as its section says. No step asks you to edit code.
3. Download with its L0 command.
4. Have the pipeline re-read it: `uv run python tools/cross-source/xs-pipeline-run.py --ingest`.

The `README.md` in each plugin folder repeats its section of the guide.

## The plugins in this repo

Categories and plugins in alphabetical order; the prefix is in brackets. *Partial* means the plugin
works in part, or was tested against mocked services only: its section in CONNECTING.md says which.

**AI history**
- `ai-history` (ai-): what you typed to AI assistants: your Claude Code logs, and the ChatGPT,
  Claude.ai or Manus exports of the tools you used. Builds the identity files the drafts read. On
  request; nothing goes to a model without your consent
- `chatgpt` (cg-): only if you used ChatGPT; its export is read by `ai-history`. The older
  `cg-l1-enrich.py` stays for a `conversations.json` you already have

**Code**
- `github` (gh-): repositories, collaborators, issues, pull requests and reviews, with your
  personal access token (partial: tested against a mocked GitHub only)

**Communication**
- `calendar` (ca-): past and future events of your Google calendars, with your own Google app
- `email` (em-): your Gmail, with your own Google app
- `imap-caldav` (ic-): any mailbox over IMAP and calendars over CalDAV or a calendar link, with your
  app password (partial: tested against mocked servers only)
- `microsoft365` (ms-): your Outlook mail, calendars and contacts, with your own app registration
  (partial: tested against a mocked Microsoft Graph only)
- `slack` (sl-): channels, threads and your DMs, with your own Slack app and user token
- `whatsapp` (wa-): chats you export from your phone, then import; on request. Live reading is not
  set up

**CRM**
- `attio` (at-): Attio CRM (companies, people, notes, calls)
- `databases` (db-): people and events from a SQLite, PostgreSQL or MySQL database you own, through
  read-only queries you write (partial: PostgreSQL and MySQL tested against fake drivers only)

**Documents**
- `gdrive` (gd-): Google Drive documents, with your own Google app
- `notion` (no-): pages and databases shared with your integration

**Health**
- `apple-health` (ah-): the Health app export (partial)
- `clinical` (cl-): clinical documents you add; the parsing step sends them to model APIs (partial)
- `whoop` (wp-): WHOOP wearable data (partial)

**HR tool**
- `personio` (pe-): your organisation's HR records (employees, absences, contracts), not only your
  own. An organisation source: its API credentials need admin rights in Personio

**Meetings & audio**
- `plaud` (pl-): recordings and transcripts of a Plaud recorder
- `tactiq` (tq-): meeting transcripts
- `voice-memos` (vm-): voice memos, transcribed on your machine
- `zoom` (zm-): your Zoom meetings, participants and cloud-recording transcripts (partial: tested
  against a mocked Zoom API only)
- `meetings`: a meeting utility, not a source

**Signing**
- `docusign` (ds-): envelopes, signers, signed documents

**Social**
- `linkedin` (li-): your LinkedIn data export

**Tasks**
- `clickup` (cu-): tasks, comments, docs; tasks become commitments

**Web**
- `analytics` (ga-): GA4 properties, with your own Google app
- `gsc` (gs-): Search Console properties, with your own Google app

A service with no folder here has nothing to configure: see
[CONNECTING.md, "Also connectable"](CONNECTING.md#also-connectable-no-plugin-folder-yet).

## The kernel (not plugins, always on)

`cross-source` (L2/L3 pipeline, entity resolution, knowledge layer), `util`, `infrastructure`,
`monitoring`, `notify`, `jobs`, `registry`, `truth`, `ingestion`, `nlp`, `security`, `diag`, `edge`,
`briefing`, `lib`, plus the `dashboard/` and the `tools/secondbrain/` app.

## Adding a source of your own

1. Create `tools/<name>/` with at least `<p>-l0-download.py` and `<p>-l1-enrich.py`.
2. Register it in `tools/sorgenti.py` with its nature and rhythm, and its L1 script as `l1`.
3. Have L0 write to `<data root>/<name>/raw/`. For L1, write into a slot the kernel already reads
   (mail, calendar, address book, as `imap-caldav` and `microsoft365` do), or use the
   [generic intake](#generic-intake), as `github`, `zoom` and `databases` do.
4. Add a `README.md` in the folder: what it needs and how it connects. Only your own access: an
   export, a personal token, or an app in your own account.
5. Add its L1 script to `L1_SCRIPTS_BASE` in `tools/cross-source/xs-pipeline-run.py` and turn it on
   in `enabled_sources` in `sbk.config.json`.

Copying an existing connector close to yours (for example `slack`, `notion` or `github`) and
adapting it is the shortest path.

### Generic intake

A kernel feature, tested on synthetic files with the network blocked; the `github`, `zoom` and
`databases` plugins write it, and their tests load their output through the same loader. No real
account's data has gone through the merge and the knowledge extraction yet. It needs no registry entry
of its own: each plugin that writes it keeps its own entry in `tools/sorgenti.py` with its L1 script as
`l1` (or as an extra L1 step), and its L1 script in the `--ingest` list of
`tools/cross-source/xs-pipeline-run.py` (today `zoom`, `github_intake`, `databases`).

**The two files**, one folder per plugin under your data root:

- `<data root>/<plugin>/processed/plugin-contacts.parquet`, one row per person:
  `source, name, email, phone, company, title, first_seen, last_seen, interactions, url`
- `<data root>/<plugin>/processed/plugin-interactions.parquet`, one row per event:
  `source, ts, kind (meeting|issue|pr|review|message|record), title, text, participants ('|||'-joined emails or names), owner_role (organizer|assignee|author|attendee|other), due, url`,
  plus an optional `status` (`open`, or `done` / `closed` / `merged` / `cancelled`).

Write `status` whenever your source knows that an item is closed: without it every assigned or dated
item counts as an open commitment forever (the intake prints one warning per file).

Columns that must exist: `name` and `email` in the contacts file, `ts`, `kind`, `title` and
`participants` in the interactions file; a file without one of them is skipped with one warning, the
other columns may be missing. Dates are ISO 8601 (a date without a zone is read as UTC). Empty values
are fine, except that a contact needs a name, an email or a phone. An email may be written as
`Name <address>`; a value that is not an address (a login, a handle) is blanked. `participants` may
also be a list column. Write the files with `sbk_config.safe_write_parquet`. The full contract, with
every column, is the docstring of `tools/cross-source/plugin_intake.py`.

**Who reads them** `tools/cross-source/plugin_intake.py` (the loader), used by
`tools/cross-source/xs-l2-merge.py` (contacts: matched by email, then phone, then name; an unmatched
contact with an email becomes a new contact, one without email is counted and left out; uncertain name
matches go to the same verification list as the other sources) and by
`tools/cross-source/xs-l2-knowledge-extract.py` (source `plugins`: person facts; an open event where you
are the assignee, or one with a due date, becomes a commitment). In an incremental run
(`xs-pipeline-run.py --propagate`) the newest intake file is watched: when any plugin rewrites its
files, the merge and the knowledge extraction run again.

**sbk.config.json** none of its own. If `enabled_sources` is not empty, list the plugin folder name
there (for example `github`, `zoom`, `databases`).

**Run and check** There is nothing to download: run the plugin's own L0, then
`uv run python tools/cross-source/xs-pipeline-run.py --ingest` (which runs the plugin's L1, the merge
and the knowledge extraction). Then:

```bash
uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run
```

prints `Plugins: N people, N commitments, N facts`, or
`Plugins: no plugin-contacts / plugin-interactions files — skipping`. After a merge,
`enriched/contacts-merged.parquet` has `has_plugin`, `plugin_sources`, `plugin_interactions`,
`plugin_first_seen`, `plugin_last_seen`, `plugin_title`, `plugin_url`, `plugin_email`.

**Limits** A bare participant (a name inside an event, no contact row) never creates a new person in
the knowledge layer; it only enriches someone already known. Company and title from a plugin are kept
at low confidence, like LinkedIn. The per-plugin counts and dates (`communication.<plugin>_interactions`,
`_first_contact`, `_last_contact`) are aggregates: each run replaces the previous value, as for Slack and
LinkedIn. Plugin activity weighs in the relationship score with the same weight as Slack messages (up to
3 points). An item that stays open in your files stays an open commitment; one closed later is not
closed in the knowledge layer by itself (same as ClickUp tasks today). An item without `url` is
identified by time and title, so renaming it makes a new commitment. The `text` column is read but not
used yet. The freshness report (`xs-util-freshness.py`) does not list plugin sources.
