<!-- generated from docs/CONNECTING.md -->
# Microsoft Teams (`tm-`)

**Status** partial · registry `continua`, every 3 days (`tools/sorgenti.py`, entry `teams`). Tested with
a mocked Microsoft Graph and identity platform only, never against a real account. The scheduled
download (`tools/cross-source/xs-l0-refresh.py`) runs `tm-l0-download.py --all`, and `xs-pipeline-run.py
--ingest` runs `tm-l1-enrich.py` (step `teams`). It writes the generic intake contract
(`tools/cross-source/plugin_intake.py`): the people in your chats reach the contact merge
(`xs-l2-merge.py`) and the person facts (`xs-l2-knowledge-extract.py`). Chat-days are written as `done`,
so they never become commitments, and no kernel stage reads the message text yet.
**Reads** your Microsoft Teams 1:1 chats and group chats: who is in each chat, and the messages (new
and edited ones at every run). Chats attached to online meetings only with `--include-meeting-chats`.
It does **not** read channel messages in teams, nor meeting transcripts: Microsoft asks for an
administrator's consent for both (`ChannelMessage.Read.All`, `OnlineMeetingTranscript.Read.All`), and
this plugin never asks for one.
**You need** a **work or school** Microsoft 365 account with Teams: Microsoft Graph does not serve
Teams chats to personal Microsoft accounts (Outlook.com, Hotmail, Live). Your organization must let you
register an app and consent to the permission `Chat.Read` for your own account yourself; if the sign-in page asks
for an administrator's approval, this plugin cannot be used with that account. Python and a browser
for the one-time sign-in (or `--device-code`).
**Create it** You use the same app you register for the `microsoft365` plugin, used only by you:
1. If you have not registered it yet, follow steps 1 to 5 of
   [microsoft365](../../docs/CONNECTING.md#microsoft365): Microsoft Entra admin center → **Entra ID** → **App registrations**
   → **New registration**, a public client with the redirect URI `http://localhost` under **Mobile and
   desktop applications**, no client secret. For a work account choose **Single tenant only** (your
   organization's directory) or **Any Entra ID Tenant + Personal Microsoft accounts**.
2. Nothing to add under **API permissions**: at sign-in the plugin asks, for your own account only,
   `Chat.Read`, `User.Read` and `offline_access` (`TEAMS_SCOPES` in `tools/teams/tm_graph.py`), and
   you consent yourself. If you want it listed on the app, add the Microsoft Graph permission
   `Chat.Read` there (not the *Application permissions* type, which this plugin never uses).
3. Put the client ID in `sbk.config.json` as `microsoft365.client_id` (and `microsoft365.tenant` =
   your tenant id or `organizations`), or export `SBK_MS365_CLIENT_ID` (and `SBK_MS365_TENANT`) in
   your shell. Then sign in once, with the same label you use for that account in `microsoft365`:
   ```bash
   uv run python tools/teams/tm-l0-auth.py --account work
   uv run python tools/teams/tm-l0-auth.py --account work --device-code   # no browser here
   ```
   If that label already holds a `microsoft365` sign-in (one with `Mail.Read`, `Calendars.Read` or
   `Contacts.Read`), this sign-in also asks again for the Outlook scopes, so one stored sign-in serves
   both plugins; a Teams-only sign-in stays Teams-only when you sign in again. `--teams-only` asks
   only for the Teams scopes; `--with-outlook` asks for both on a new label. If you sign in with a
   different account than the one the label already holds, nothing is stored: use another label.

Official guides: [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) ·
[Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) ·
[List chats](https://learn.microsoft.com/en-us/graph/api/chat-list) ·
[List messages in a chat](https://learn.microsoft.com/en-us/graph/api/chat-list-messages) ·
[List members of a chat](https://learn.microsoft.com/en-us/graph/api/chat-list-members) ·
[Teams throttling limits](https://learn.microsoft.com/en-us/graph/throttling-limits) ·
[How users consent in an organization](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-user-consent).
**Where the code looks**
- client ID and tenant: the `microsoft365` plugin's own lookup (`SBK_MS365_CLIENT_ID`, else
  `microsoft365.client_id`, `tools/microsoft365/ms_graph.py:191`; `SBK_MS365_TENANT`, else
  `microsoft365.tenant`, else `common`, `ms_graph.py:196`).
- the sign-in: the same Keychain entry `sbk-microsoft365/<label>` (`ms_graph.py:237`, read through
  `tools/teams/tm_graph.py:332`), written by `tm-l0-auth.py` (`tools/teams/tm-l0-auth.py:158`) and
  replaced at every download, because Microsoft returns a new refresh token at each use. Without a
  Keychain: `SBK_MS365_TOKEN_FILE`, then `SBK_MS365_TOKEN_<LABEL>`, as for `microsoft365` (in container
  mode the seed is read first: unset it after the first run).
- the Teams check of that sign-in (`Chat.Read` present, not a personal-accounts tenant):
  `tools/teams/tm_graph.py:301`.
**sbk.config.json** section `teams` (every field with its `_help` in `sbk.config.example.json`):
`account` (default `microsoft365.default_account`, else `outlook`), `accounts` (labels for `--all`),
`chat_types` (`["oneOnOne", "group"]`), `history_days` (365), `overlap_minutes` (10), `page_size` (50),
`timezone` (empty = `SBK_DISPLAY_TZ`), `text_max_chars` (20000). If `enabled_sources` is not empty, list
`teams` there.
**Download**
```bash
uv run python tools/teams/tm-l0-download.py --account work          # incremental after the first run
uv run python tools/teams/tm-l0-download.py --account work --full   # re-read teams.history_days
uv run python tools/teams/tm-l0-download.py --all                   # every label in teams.accounts
uv run python tools/teams/tm-l1-enrich.py                           # raw -> intake parquet
uv run python tools/cross-source/xs-pipeline-run.py --ingest        # runs tm-l1-enrich.py (step teams)
```
With `--all`, an account whose sign-in expired or whose organization refuses the chats prints one
line `teams/<label>: ...` and the others still run (exit code 1).
**Check** `uv run python tools/teams/tm-l0-auth.py --account work --check` (prints the signed-in
address and whether chats are readable), then `<data root>/teams/raw/work/download-summary.json`
(chats listed, read, left out and skipped, messages new or changed, `errors`), then
`<data root>/teams/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- Work or school accounts only. Personal Microsoft accounts are not supported by the chat APIs.
- Channel messages, meeting transcripts, and the all-chats endpoints (`getAllMessages` and its delta)
  are out: they need admin consent or application permissions.
- An organization can block user consent, or allow it only for apps from verified publishers and apps
  registered in its own directory, and only for permissions it classifies as low impact; then the
  sign-in stops at an approval page. An app you register in your organization's own directory
  (**Single tenant only**) is the kind that second setting can let through.
- One request every 1.25 seconds (`MIN_INTERVAL_S`): Microsoft allows 1 request per second per user
  on the chat list and per chat on its messages, with a sustained limit near 83 percent. Every run asks
  each included chat once (plus pages), so a long chat list takes a while.
- A group chat listed with 25 members is re-read with List members, because the expanded list stops at
  25.
- Each chat is re-read from its newest change minus `overlap_minutes`. An edited message replaces the
  stored one; a deleted message keeps its row without text. That deleted messages come back in this
  list with `deletedDateTime` set is not stated in Microsoft's docs; tested only on mocked answers.
- Chats you left stay on disk and in the intake files; their members are not refreshed.
- In a group chat a day counts for the people who wrote that day; if only you wrote, for every other
  member (at most 50). Members who never wrote are contacts with 0 interactions.
- Microsoft asks that the scopes of a refresh be the same as, or a subset of, those of the original
  sign-in. If you sign a label in again with `ms-l0-auth.py`, it asks again for `Chat.Read` when
  `tm-l0-auth.py` recorded it on that label (`requested_scopes`), so it is kept; any other recorded
  scope is not asked again, and the script names it (`not asked again: …`); not on a
  personal-accounts tenant (`consumers`), where Teams cannot be read. A label signed in before that
  record existed has no `Chat.Read`: the Teams download then stops with one line telling you to run
  `tm-l0-auth.py`, which asks for both.
- The refresh token lasts 90 days by default and can be revoked earlier: sign in again then.
- Global Microsoft cloud only (login.microsoftonline.com, graph.microsoft.com).

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#teams](../../docs/CONNECTING.md#teams). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
