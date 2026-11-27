<!-- generated from docs/CONNECTING.md -->
# Fireflies (`ff-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `fireflies`). Tested
with a mocked Fireflies API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `ff-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`ff-l1-enrich.py` (step `fireflies`). It writes the generic intake contract
(`tools/cross-source/plugin_intake.py`): the people you met reach the contact merge (`xs-l2-merge.py`)
and the person facts, and the action items that are yours become open commitments
(`xs-l2-knowledge-extract.py`, source `plugins`).

**Reads** with the API key of your own Fireflies account, GraphQL queries only (no mutation exists
in the plugin, a test checks it):
- your own user (id, email, name);
- the meetings where you are organizer or participant (`transcripts(user_id: <you>)`), or only those
  you organized with `--only-organized` (`transcripts(mine: true)`): title, date, organizer,
  participants' emails, attendees (name, email, phone when Fireflies has it), speakers, the AI
  summary (overview, short summary, gist, keywords, topics) and the action items text;
- the full transcript of each new meeting (sentences with speaker names), once;
- your Fireflies contact list (people who were in meetings with you).
Audio and video links, analytics and AI-app outputs are never asked.

**You need** a Fireflies account of your own. The API works on every plan, with different limits
(see Limits). Nothing on the team or admin side: the key reads what your own account can see, and
the plugin asks only for meetings tied to you.

**Create it** Sign in at [app.fireflies.ai](https://app.fireflies.ai/), open **Integrations**, then
**Fireflies API**, and copy your API key ([Fireflies: Authorization](https://docs.fireflies.ai/fundamentals/authorization)).
Fireflies' MCP page names the same place **Settings > Developer settings**. The key is personal: treat
it like a password. Put it in the Keychain:
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-fireflies', 'api-key', getpass.getpass('value: '))"
```
or, without a Keychain, as `FIREFLIES_API_KEY` in `.env` (the download script loads `.env` by itself).

**Where the code looks** Keychain `sbk-fireflies/api-key` first, then the env `FIREFLIES_API_KEY`
(`tools/fireflies/ff_api.py:237`, names at `:56`-`:58`). The key travels only in the
`Authorization: Bearer` header to `https://api.fireflies.ai/graphql` and is never written to disk.

**sbk.config.json** nothing is required. Optional section `fireflies`: `history_days` (first run,
default 90), `overlap_days` (later runs re-read this many days, default 3), `only_organized` (false),
`include_sentences` (true), `include_contacts` (true), `action_items` (`all`, `mine` or `none`,
default `all`), `max_requests` (cap per run, default 400), `request_delay_seconds` (2.1). If
`enabled_sources` is not empty, list `fireflies` there.

**Download**
```bash
uv run python tools/fireflies/ff-l0-download.py --check     # one request: whose key it is, writes nothing
uv run python tools/fireflies/ff-l0-download.py             # incremental after the first run
uv run python tools/fireflies/ff-l0-download.py --days 365  # first run further back
uv run python tools/fireflies/ff-l1-enrich.py               # raw -> the two intake parquet files (also run by --ingest)
```

**Check** `<data root>/fireflies/download-summary.json` (meetings, transcripts, contacts, requests
used and left, `stopped`, `summaries_pending`, `transcripts_pending`, `partial_errors`), the files in
`<data root>/fireflies/raw/`, then `<data root>/fireflies/processed/plugin-contacts.parquet` and
`plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.

**Limits**
- Rate limits (Fireflies, checked 2026-11-25): Free 30 requests a minute and 500 a day, Pro 60 a
  minute and 5,000 a day, Business and Enterprise 60 a minute per paid seat, pooled across the
  team, with no daily cap; the
  daily quota resets at midnight UTC; a Free account's first 14 days of API use run at Pro limits
  ([Limits](https://docs.fireflies.ai/fundamentals/limits)). The plugin sends one request every 2.1 s,
  stops at 400 requests per run by default, and stops cleanly when Fireflies says the daily quota is
  over, keeping what it downloaded. A run costs one request per 30-day window (one more per 50 meetings in it), two
  for your user and contact list, plus one per new
  meeting for its transcript text: the texts left over are asked first on the next run, after the
  quota resets. `--no-sentences` skips them.
- Whether summaries and action items are filled on your plan is decided by Fireflies; the API docs do
  not say it per field (they do for audio, video and analytics, which need Pro and are not read here).
- The action items arrive as one block of text per meeting. Fireflies does not document its layout;
  the plugin reads a bold name line (`**Name**`) as the owner of the items below it. An item is yours
  when that name is your Fireflies name, a name in `own_names`, or your first name alone when nobody
  else in the meeting shares it. If Fireflies changes the layout, items may come without an owner.
- Fireflies has no done state for these items: yours stay open commitments until you remove them in
  the knowledge layer (same as ClickUp tasks today). `action_items: "mine"` or `"none"` writes fewer.
- People: Fireflies lists participants' emails without names and speakers' names without emails; a
  name is joined to an email only when the attendee list or your contact list pairs them, so some
  people appear twice (once by email, once by name).
- The note-taker is recognised by name (`Notetaker`, `Fireflies.ai`) and by its own email address
  (`_BOT_EMAILS` in `tools/fireflies/ff_api.py`); Fireflies documents neither.
- Meetings still running (`is_live`) are skipped and read on the next run. A summary still
  `processing`, or still `default` ("no summary has been generated yet",
  [SummaryStatus](https://docs.fireflies.ai/schema/enum/summary-status)), is asked again by id on
  the next runs, for up to 14 days.
- Switching `only_organized` from true back to false starts again from `history_days`, because the
  saved date only covered the meetings you organized. A run stopped by an error (key refused,
  network down) saves its state first and does not move the saved date unless the listing finished.
- Paging relies on `skip` inside 30-day windows; Fireflies does not document the sort order or the
  largest `skip`.

**Alternative, an MCP server** Fireflies runs its own MCP server (`https://api.fireflies.ai/mcp`,
OAuth with your account or your API key, [MCP Server Configuration](https://docs.fireflies.ai/getting-started/mcp-configuration)).
It lets an agent ask about your meetings live; it shares the same rate limits and does not fill SBK's
data folder, so the knowledge layer still needs the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#fireflies](../../docs/CONNECTING.md#fireflies). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
