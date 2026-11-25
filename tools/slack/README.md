<!-- generated from docs/CONNECTING.md -->
# Slack (`sl-`)

**Status** mature · registry `continua`, every 3 days.
**Reads** the workspace your own Slack app is installed in: its public and private channels, the
threads, your DMs and group DMs, the user directory. It reads only what your own account can see in
Slack.
**You need** a personal Slack app in your workspace and its User OAuth Token (`xoxp-…`). You create
the app yourself; it is visible only in your workspace and acts as you.

**Create the app**
1. Open <https://api.slack.com/apps>, click *Create New App* → *From scratch*, give it a name (for
   example `SBK`), pick your workspace and click *Create App*.
2. In the app, open *OAuth & Permissions*. Under *Scopes* → **User Token Scopes** (not *Bot Token
   Scopes*) add these, which are the ones the code calls:

   | Scope | Used by |
   |---|---|
   | `channels:read`, `groups:read`, `im:read`, `mpim:read` | the lists of channels, private channels, DMs and group DMs (`conversations.list`, `users.conversations`) |
   | `channels:history`, `groups:history`, `im:history`, `mpim:history` | the messages and thread replies (`conversations.history`, `conversations.replies`) |
   | `users:read` | names of people (`users.list`, `users.info`) |
   | `users:read.email` | the email of each person in the user directory, so SBK can match them with your other sources |
   | `search:read` | thread replies that arrive after the download window, the DM fallback, `tools/util/slack_search.py` (`search.messages`) |
   | `files:read` | only if you run `tools/slack/sl-l1-extract-files.py --download` (text of shared PDFs and documents) |

3. At the top of *OAuth & Permissions* click *Install to Workspace* and then *Allow*.
4. Copy the **User OAuth Token** shown on the same page. It starts with `xoxp-`.

**Where to put the token** In the Keychain, service `sbk-slack`, account `user-token`:
```bash
security add-generic-password -s sbk-slack -a user-token -w 'xoxp-...'
```
or in `.env` at the repo root as `SLACK_USER_TOKEN=xoxp-...`. The scripts look in the Keychain first,
then in the environment (`tools/slack/sl-l0-download.py`, `get_slack_token`).

**sbk.config.json** nothing is needed to connect: the workspace is the one your token belongs to, as
Slack reports it (`auth.test`). Optional fields under `slack`:
- `exclude_channel_patterns`: regular expressions on channel names that are never downloaded
  (e.g. `["^client-"]`); run the channel index again after changing them.
- `exclude_channel_ids`: conversation ids never downloaded, channels or DMs (e.g. `["C0123456789"]`).
- `user_names`: `{"<user id>": "<name>"}` for people Slack no longer resolves (deactivated accounts,
  guests from other organisations).

**Monitor and health check** The monitor (`tools/monitoring/sbk-monitor.py`, also `uv run python tools/sbk_cli.py monitor`) and
the dashboard's connection check read Slack with the same user token as the download (Keychain
`sbk-slack` / `user-token`, then `SLACK_USER_TOKEN`). Slack shows as healthy when that token answers
`auth.test`. Nothing else is needed. What the monitor does, and the consent its model calls need:
[The monitor and scheduled jobs](../../docs/CONNECTING.md#the-monitor-and-scheduled-jobs-optional).

One more optional field under `slack` in `sbk.config.json`:
- `own_user_id`: your own Slack user id (`U…`), used to spot mentions of you and as the DM target of
  alerts. Leave it empty and SBK asks Slack for it (`auth.test` on your user token).

**Notifications (optional)** Alerts from the monitor, the dashboard's send box and
`tools/notify/slack_notify.py` post messages. They need one of these, on the same app you created
above:
- your user token with one more User Token Scope, `chat:write` (and `im:write` to open a DM with
  someone). The messages are sent as you. After adding a scope, reinstall the app and copy the
  token again.
- or, as an optional extra, a bot token of the same app: under *Bot Token Scopes* add `chat:write`,
  `im:write` and `users:read.email`, reinstall, and copy the **Bot User OAuth Token** (`xoxb-…`) into
  the Keychain (service `sbk-slack`, account `bot-token`) or into `.env` as `SLACK_BOT_TOKEN`. The
  messages then come from the app. When a bot token is present it is used for notifications only;
  reading always uses the user token.

To keep the monitor from alerting on its own alerts, put the id of the DM where they land
(`D…`) in `.env` as `SBK_SELF_ALERT_CHANNEL`.

**Download**
```bash
uv run python tools/slack/sl-l0-channel-index.py --dry-run   # counts only: checks the token and the scopes
uv run python tools/slack/sl-l0-channel-index.py
uv run python tools/slack/sl-l0-download.py
uv run python tools/slack/sl-l0-download-dm.py
```
The channel index comes first: the download refuses to start without it, because it is where your
exclusions are applied.

**Check** `<data root>/slack/channel-index.json` (the line `Downloadable: N` in the log says how many
channels will be read), then `<data root>/slack/conversations/`, `<data root>/slack/dm/` and
`<data root>/slack/slack-users.json`. The data root is `~/.sbk-data` unless you set `SBK_DATA_ROOT`.

**Limits**
- One token reads one workspace. If you are in several workspaces, the download reads only the one
  the app is installed in.
- It never reads other people's DMs or channels you cannot open in Slack.
- If your workspace requires approval for apps, *Install to Workspace* becomes *Request to Install*
  and the app works only after the people who manage your workspace approve it.
- On the free Slack plan only the last 90 days of messages are visible
  ([Slack help, free plan limits](https://slack.com/help/articles/27204752526611-Feature-limitations-on-the-free-version-of-Slack));
  SBK can download only what Slack shows you.
- Rate limits: an app you create for your own workspace is an internal app, so the 2025 limits on
  `conversations.history` and `conversations.replies` for apps distributed outside the Marketplace do
  not apply to it ([Slack changelog, 29 May 2025](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps)).
  The download still pauses between calls (`API_DELAY` in `sl-l0-download.py`) and waits when Slack
  answers 429.
- The token acts as you. To revoke it, remove the app from your workspace (or reinstall it to get a
  new token).
- Optional, not part of the steps above: `tools/slack/sl-realtime.py` saves new messages as they
  arrive. It needs, on the same app, Socket Mode on, an app-level token (`xapp-…`, scope
  `connections:write`, stored as Keychain `sbk-slack` / `app-level-token` or `SLACK_APP_LEVEL_TOKEN`)
  and Event Subscriptions on behalf of users for the message events.

**Alternative, an MCP server** Slack publishes an official MCP server, `https://mcp.slack.com/mcp`
([Slack MCP server overview](https://docs.slack.dev/ai/slack-mcp-server)). In Claude Code you add it
with `claude plugin install slack` and log in to your workspace in the browser
([Connect to Claude](https://docs.slack.dev/ai/slack-mcp-server/connect-to-claude)); your workspace
may require approval for it. It lets Claude search and read Slack live during a
session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need the app
above. (Checked on Slack's site on 2026-11-25.)

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#slack](../../docs/CONNECTING.md#slack). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
