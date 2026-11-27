<!-- generated from docs/CONNECTING.md -->
# Granola (`gr-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `granola`). Tested
with a mocked Granola API and a hand-made CSV only, never against a real account or a real export. The
scheduled download (`tools/cross-source/xs-l0-refresh.py`) runs `gr-l0-download.py`, and
`xs-pipeline-run.py --ingest` runs `gr-l1-enrich.py` (step `granola`). The scheduled download is the API
route; a CSV export you import by hand. It writes the
generic intake contract (`tools/cross-source/plugin_intake.py`): the people in your meetings reach the
contact merge (`xs-l2-merge.py`) and the person facts (`xs-l2-knowledge-extract.py`). Notes are
written as `done`, so they never become commitments, and no kernel stage reads the note text yet.

**Reads** your Granola meeting notes: title, date, the AI summary, your private notes, the transcript,
the attendees and the calendar invitees, and the link to the note. Two routes, pick the one your plan
allows:

| Your plan | Route | What you get |
|---|---|---|
| Business or Enterprise | the Granola API with your **personal API key** (`gr-l0-download.py`) | every note you own or that is shared with you, with transcript, updated incrementally |
| Basic (free), or any plan | the **CSV export** of your own notes (`gr-l0-import-csv.py`) | your full note history, as Granola writes it in the CSV, once every 24 hours |

**You need**
- For the API: a Granola workspace on the **Business** plan (or Enterprise). On the free Basic plan
  Granola gives no API key. You can upgrade only yourself by creating a personal workspace and
  upgrading that one ([Subscriptions and billing](https://docs.granola.ai/help-center/managing-your-account/subscriptions-and-billing)).
  The Granola desktop app, to create the key.
- For the CSV: any Granola account, and access to the mailbox of that account (Granola emails you the
  file).

**Create it**

*Route 1, personal API key (Business)*
1. Open the Granola desktop app and go to **Settings → Connectors → API keys**.
2. Click **Create new key**, select only the **Personal notes** access scope (your notes and the notes
   shared with you), then click **Generate API Key**. Leave **Public notes** off: it reads the notes
   everyone in your workspace can see, which is not your own data, and their owners would then
   outnumber you when the plugin works out which address is yours.
3. Copy the key (it starts with `grn_`) and store it in the Keychain:
   ```bash
   uv run python -c "import keyring, getpass; keyring.set_password('sbk-granola', 'api-key', getpass.getpass('value: '))"
   ```
   or put `GRANOLA_API_KEY=grn_...` in your shell environment.

You never need a *workspace* API key: those belong to the workspace and only admins create them.

Official guides: [Granola API, get a personal API key](https://docs.granola.ai/introduction) ·
[Granola API in the Help Center](https://docs.granola.ai/help-center/sharing/integrations/granola-api).

*Route 2, CSV export (free)*
1. In Granola, click your workspace name in the bottom-left corner, then **Settings → Profile**.
2. Click **Generate CSV** and choose your workspace. Granola emails you a link within a few hours.
3. Open the link (signed in with the same Granola account) within 24 hours and download the CSV.

Official guide: [Exporting notes](https://docs.granola.ai/help-center/sharing/exporting-notes).

**Where the code looks**
- the API key: Keychain `sbk-granola/api-key`, then the env `GRANOLA_API_KEY`
  (`tools/granola/gr_api.py:164`). The lines are in `.env.example`, section "Granola"; the Granola
  scripts do not load `.env` by themselves, so export it in your shell.
- the CSV: the file you pass on the command line; nothing is stored.

**sbk.config.json** section `granola` (with its `_help` lines in `sbk.config.example.json`):
`history_days` (first API run, default 365), `overlap_days` (default 3), `own_email` (your Granola
login, if it is not in `own_emails`), `text_include_transcript` (default true), `csv_columns` (only if
the importer does not recognise a column of your CSV). If `enabled_sources` is not empty, list
`granola` there.

**Download**
```bash
uv run python tools/granola/gr-l0-download.py              # API: last 365 days, then incremental
uv run python tools/granola/gr-l0-download.py --all        # API: every note the key can read (any run)
uv run python tools/granola/gr-l0-import-csv.py ~/Downloads/granola-export.csv   # CSV route
uv run python tools/granola/gr-l1-enrich.py                # raw -> intake parquet (also run by --ingest)
```

**Check** `<data root>/granola/download-summary.json` (`route`, notes listed and downloaded, with
transcript, errors; for the CSV `columns_found` and `columns_missing`), the files in
`<data root>/granola/raw/notes/`, then `<data root>/granola/processed/plugin-contacts.parquet` and
`plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
`gr-l1-enrich.py` prints who it took to be "you" (`you = configured` or `you = inferred: ...`): if the
inferred address is wrong, set `granola.own_email`.

**Limits**
- Free Basic plan: no API. The CSV route works, but Granola does not document the CSV's column names:
  the importer recognises the usual spellings (title, date, summary, transcript, attendees, id, url)
  and prints what it found. If your file names a column differently, map it in
  `granola.csv_columns`. Whether the CSV has an attendees column is not documented; without it the
  CSV route gives notes but no contacts.
- The API returns only notes that have a generated AI summary; a note still processing appears on a
  later run.
- Your own private notes come back only for notes you created; for notes shared with you they are
  empty.
- A note you delete in Granola stays in your data folder: with a personal key the API does not report
  deleted notes. Delete its file in `raw/notes/` if you want it gone.
- Attendee names come from Granola; invitees come with an email only. People Granola does not list
  are not seen.
- One request every 0.25 s (Granola allows 5 per second, 25 in a burst); a `429` waits and retries.
- If Granola keeps failing on a note or refuses it (server, network or request error), the saved point
  does not move, so the next run asks for it again. A `--since` run moves the saved point only when
  its date is not later than the incremental window; a `--limit` run never moves it.
- The CSV's date format is not documented. ISO dates are read as they are; a date written as
  `01/02/2026 10:00` is read day first, so check a few dates in `plugin-interactions.parquet` if your
  export uses the US order.
- If you switch route (CSV first, API later), a CSV row that the API also downloaded (same title, same
  day) is left out by `gr-l1-enrich.py`, so a meeting is not counted twice.
- Not covered: workspace API keys, Enterprise admin controls, webhooks.

**Alternative, an MCP server** Granola runs its own MCP server (`https://mcp.granola.ai/mcp`), with
OAuth in your browser and no API key ([Granola MCP](https://docs.granola.ai/help-center/sharing/integrations/mcp)).
On Basic it sees your notes of the last 30 days, without transcripts, and `get_meetings` is limited to
10 calls an hour, so SBK uses it only for live questions in Claude Code
(`claude mcp add granola --transport http https://mcp.granola.ai/mcp`, then `/mcp` → **Authenticate**),
not as a download. It does not fill SBK's data folder.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#granola](../../docs/CONNECTING.md#granola). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
