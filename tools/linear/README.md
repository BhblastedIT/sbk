<!-- generated from docs/CONNECTING.md -->
# Linear (`ln-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `linear`). Tested
with a mocked Linear API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `ln-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`ln-l1-enrich.py` (step `linear`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own personal API key, GraphQL queries only, in the one workspace the key belongs to:
the issues you are assigned to, the issues you created and the issues you are subscribed to (title,
identifier, description, status, team, project, priority, labels, due date, assignee, creator, up to 25
subscribers), and the comments on those issues with their author. For each person: name, email and job
title as Linear shows them. Nothing is written to Linear: the plugin refuses to send anything that is not
a read query.
**You need**
- a Linear account in the workspace you want to read, any plan;
- permission to create a personal API key. Admins can turn off API keys for members in **Settings** →
  **Administration** → **API** → **Member API keys**; admins can always create keys
  ([API and Webhooks](https://linear.app/docs/api-and-webhooks)). If member keys are off and you are
  not an admin, this plugin has no other route: ask an admin to turn them on;
- Python on the machine where you download.
**Create it** You create a key of your own, used only by you:
1. In Linear open **Settings** → **Account** → **Security & Access**
   ([direct link](https://linear.app/settings/account/security)), section **Personal API keys**, and create
   a new key.
2. Give it a name you will recognise (for example `sbk read-only`). Under permissions choose **Read**
   only instead of full access; the plugin needs nothing else. You can also limit the key to some teams:
   then the plugin sees only the issues of those teams.
3. Copy the key and put it in the Keychain, so it stays out of your shell history:
   ```bash
   uv run python -c "import keyring, getpass; keyring.set_password('sbk-linear', 'api-key', getpass.getpass('key: '))"
   ```
   Or put it in `.env` as `LINEAR_API_KEY=...`.
4. Check it:
   ```bash
   uv run python tools/linear/ln-l0-download.py --dry-run
   ```
   It prints your name and the workspace, and writes nothing.

Official guides: [Personal API keys and permissions](https://linear.app/docs/api-and-webhooks) ·
[Security & Access settings](https://linear.app/docs/security-and-access) ·
[GraphQL API, authentication](https://linear.app/developers/graphql) ·
[Rate limits](https://linear.app/developers/rate-limiting).
**Where the code looks**
- the key: Keychain `sbk-linear/api-key`, else `LINEAR_API_KEY` in `.env` or your shell
  (`resolve_key` in `tools/linear/ln_api.py`). It is sent only to `https://api.linear.app/graphql`, in the
  `Authorization` header, and never written to the data folder.
**sbk.config.json** section `linear`: `history_days` (first run, default 365; 0 = everything),
`overlap_hours` (default 24), `include_subscribed` (default true), `comments` (default true). If
`enabled_sources` is not empty, list `linear` there.
**Download**
```bash
uv run python tools/linear/ln-l0-download.py                 # incremental after the first run
uv run python tools/linear/ln-l0-download.py --since-days 0  # first run over your whole history
uv run python tools/linear/ln-l0-download.py --no-subscribed # only assigned and created issues
uv run python tools/linear/ln-l0-download.py --full          # forget the saved state, read your whole history
uv run python tools/linear/ln-l1-enrich.py                   # raw -> intake parquet (also run by --ingest)
```
**Check** `<data root>/linear/download-summary.json` (workspace, issues and comments read, open issues
re-checked, requests left this hour, the highest query complexity seen), the files in
`<data root>/linear/raw/`, then `<data root>/linear/processed/plugin-contacts.parquet` and
`plugin-interactions.parquet`. After the pipeline:
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**What becomes a commitment** An issue assigned to you that is not done, cancelled or closed. An issue you
created and left unassigned counts too when it has a due date. The due date of an issue assigned to
someone else stays in the text and is not your commitment. Issues you only follow are kept as context
(`owner_role` other) and never become commitments. Comments are written as done.
**Limits**
- One key reads one workspace. If you are in more than one Linear workspace, this plugin reads only the
  workspace of the key.
- Only what your user can see, and with a team-limited key only those teams.
- An issue that is moved to the trash, or that you can no longer see, stays in your files with its last
  known status until a download with `--full`. An open issue you were removed from is read again by id
  on the next run, so a new assignee does reach your files.
- An issue archived while still open is written as `closed`, because Linear hides it.
- Comments are read for the issues that are yours at the time of the download. An issue that became
  yours since the last run gets all its older comments once. Comments on project updates and documents
  are not read.
- Turning `include_subscribed` or `comments` on after the first run reads the first-run window again.
- Linear changes an issue's identifier (and so its link) when the issue moves to another team. The
  kernel keys a commitment on its link, so a moved issue can show up as a new commitment.
- Linear discourages polling the API for updates
  ([Rate limits](https://linear.app/developers/rate-limiting)). The plugin reads only what changed since
  the last run, sorted by update time, and the registry's rhythm is one run every 7 days.
- Only the first 25 subscribers of an issue are read.
- Description and comment text are cut at 4,000 characters.
- API limits for a personal key: 2,500 requests and 3,000,000 complexity points per hour, shared by all
  keys of the same user (twice that on Business, five times on Enterprise), at most 10,000 points per
  query ([Rate limits](https://linear.app/developers/rate-limiting)). The plugin waits when Linear says
  so and stops only after five refusals in a row; a run that stops keeps what it read and does not move
  the saved date, so nothing is skipped.
- Linear's docs do not say which status code a revoked key gets; HTTP 401 and the
  `AUTHENTICATION_ERROR` code are both read as a refused key.
**Alternative, an MCP server** Linear runs its own MCP server (`https://mcp.linear.app/mcp`, read-only
tools at `https://mcp.linear.app/mcp/readonly`, OAuth sign-in or your API key as a bearer token:
[Linear MCP server](https://linear.app/docs/mcp)). It lets an agent read and update your issues live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#linear](../../docs/CONNECTING.md#linear). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
