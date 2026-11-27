<!-- generated from docs/CONNECTING.md -->
# Fathom (`fa-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `fathom`). Tested
with a mocked Fathom API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `fa-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`fa-l1-enrich.py` (step `fathom`). It writes the generic intake contract
(`tools/cross-source/plugin_intake.py`): the people you met reach the contact merge (`xs-l2-merge.py`)
and the person facts (`xs-l2-knowledge-extract.py`); an open action item assigned to you becomes a
commitment. Meetings are written as `done`. No kernel stage reads the summary and transcript text yet.
**Reads** with one read-only call (`GET /meetings`) the meetings you recorded with Fathom: title,
time, calendar invitees (name and email), who recorded it, the summary (your default template,
Markdown), the transcript with speaker names, and the action items with their assignee and whether
they are ticked off. With `--all-visible` also the meetings shared with you or your team.
**You need** a Fathom account. Fathom includes API access (keys and webhooks) on every plan,
the free one too ([FAQ](https://developers.fathom.ai/faq)). Fathom's pricing page lists AI action
items under Premium and above, so on the free plan expect meetings, invitees, summaries and
transcripts but no action items ([pricing](https://www.fathom.ai/pricing)); this has not been
checked against a real free account.
**Create it** You create a key that belongs to you only:
1. Sign in to Fathom and open **User Settings → API Access**
   ([direct link](https://fathom.video/customize#api-access-header)).
2. Generate an API key and copy it. The key sees what you see in Fathom: meetings you recorded and
   meetings shared with you or your team, never other people's private meetings
   ([Quickstart](https://developers.fathom.ai/quickstart)).
3. Store it in the Keychain (it asks for the value, nothing goes in your shell history):
   ```bash
   uv run python -c "import keyring, getpass; keyring.set_password('sbk-fathom', 'api-key', getpass.getpass('value: '))"
   ```
   or `security add-generic-password -s sbk-fathom -a api-key -w` on macOS, or put it in `.env` as
   `FATHOM_API_KEY`. In container mode (`SBK_CONTAINERIZED=1`) set `FATHOM_API_KEY`.
4. Check it: `uv run python tools/fathom/fa-l0-download.py --dry-run`.

You do not need an OAuth app: Fathom's OAuth is for public apps that other Fathom users install
([Building with OAuth](https://developers.fathom.ai/oauth)).
**Where the code looks** Keychain `sbk-fathom/api-key` first, then `FATHOM_API_KEY`, then
`FATHOM_API_KEY_AUTH` (the name Fathom's own SDKs read) (`tools/fathom/fa_api.py:189`). Your emails,
used to ask only for the meetings you recorded: `fathom.recorded_by`, else `own_emails` of
`sbk.config.json` (`tools/fathom/fa_api.py:174`).
**sbk.config.json** section `fathom`: `recorded_by` (optional list of your Fathom login emails),
`all_visible` (default false), `history_days` (first run, default 365), `overlap_days` (default 14).
If `enabled_sources` is not empty, list `fathom` there.
**Download**
```bash
uv run python tools/fathom/fa-l0-download.py --dry-run   # checks the key, writes nothing
uv run python tools/fathom/fa-l0-download.py             # incremental after the first run
uv run python tools/fathom/fa-l0-download.py --full      # every meeting, no date limit
uv run python tools/fathom/fa-l1-enrich.py               # raw -> intake parquet (also run by --ingest)
```
**Check** `<data root>/fathom/download-summary.json` (meetings, with transcript, with summary,
action items, `filter`, `stopped`), the files in `<data root>/fathom/raw/meetings/`, then
`<data root>/fathom/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`.
**Limits**
- Only meetings recorded with Fathom. By default only the ones **you** recorded; with
  `--all-visible` also those shared with you or your team. In that mode the call carries no
  `recorded_by[]`, and Fathom then leaves out calls recorded by users outside your Fathom
  organisation, even when they were shared with you
  ([List meetings](https://developers.fathom.ai/api-reference/meetings/list-meetings)).
- If neither `fathom.recorded_by` nor `own_emails` is set, the download reads every meeting your key
  can see, and the L1 takes as yours the one address that recorded every meeting; with more than one
  recorder it cannot tell which is you, and you appear among the contacts. Set `own_emails`.
- Rate limits: 60 calls a minute, 30 a minute for calls that include summaries or transcripts,
  lowered by Fathom to 5 a minute at busy times; Fathom returns 10 meetings per call and the page
  size cannot be raised ([rate limiting](https://developers.fathom.ai/api-overview)). The plugin
  waits about two seconds between calls and honours `Retry-After`; a first run over many meetings is
  slow. `--no-transcript --no-summary` makes the calls light.
- Each run re-reads the last `overlap_days` (default 14) before the previous run, so action items you
  tick off later are picked up inside that window; older changes need `--full`. The saved point
  does not move after a lighter run (`--no-transcript`, `--no-summary`) or after a `--since` later
  than it, and it is ignored when you change the `recorded_by` filter: then the run goes back
  `history_days`, as a first run does. A run that stops halfway keeps what it saved and moves
  nothing.
- A meeting you delete in Fathom stays in `raw/meetings/` and in the intake files until you remove
  its file by hand.
- Summaries and action-item texts come from Fathom in English, in your default summary template.
- Contacts carry name and email only: Fathom gives no phone, company or job title.
- Calendar invitees are people who were invited, not proof that they joined. For a call with no
  calendar event the transcript speakers are used, by name unless Fathom matched them to an email.
- The plugin never calls the admin-only users endpoint, webhooks, downloads or OAuth: one `GET`
  endpoint, one personal key, and it refuses to send the key to any host but `api.fathom.ai`
  (it never follows a redirect, which would carry the key header to the new address).
- Fathom also runs an official MCP server for asking an assistant about your meetings live
  ([Fathom MCP](https://developers.fathom.ai/mcp-docs)); this plugin is the batch download into your
  data folder and does not use it.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#fathom](../../docs/CONNECTING.md#fathom). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
