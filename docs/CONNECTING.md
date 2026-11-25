# Connecting your sources

This guide comes after the install ([GETTING-STARTED.md](GETTING-STARTED.md)). For each source, it
says what SBK reads, what you create on the vendor's side, where the code looks for it, the command
to run and how to check that it worked. Each source is a plugin under `tools/<plugin>/`
([PLUGINS.md](PLUGINS.md)), and the `README.md` in its folder repeats its section.

Connect only the sources you use, in the order you like. The sections are grouped by category, and
categories and plugins are in alphabetical order: the order says nothing about where to begin. If you
work with an AI agent, [CLAUDE.md](../CLAUDE.md) tells it to walk you through this guide in the order
you choose.

Every connection is your own: an export you make, a personal token, or an app you create in your own
account. Where the vendor runs its own MCP server, the source's section names it and
[Using an MCP server](#using-an-mcp-server-instead-of-a-download) lists them all.

Five plugins are partial: `databases`, `github`, `imap-caldav`, `microsoft365` and `zoom`. They are in
the registry (`tools/sorgenti.py`) and in the pipeline, but they were tested only against mocked
services, never against a real account. Their **Status** line says so.

Each **Status** line also gives the source's *nature* in the registry and its rhythm: `continua`
(continuous: new data keeps arriving, and silence past the rhythm in days is a warning), `periodica`
(periodic: it changes now and then, checked against a longer rhythm), `a_richiesta` (on request: it
runs only when you start it, with a reminder after the rhythm), `spot` (one-off: its age does not
matter), `chiusa` (closed: no longer read, the data already fetched is kept), `da_costruire`
(declared, not built yet). The names are the registry's own values, so they stay as they are.

**Contents**

- [Before you start](#before-you-start) · [Google: your own Google app](#google) ·
  [Using an MCP server instead of a download](#using-an-mcp-server-instead-of-a-download)
- AI history [ai-history](#ai-history) · [chatgpt](#chatgpt)
- Code [github](#github)
- Communication [calendar](#calendar) · [email](#email) · [imap-caldav](#imap-caldav) ·
  [microsoft365](#microsoft365) · [slack](#slack) · [whatsapp](#whatsapp)
- CRM [attio](#attio) · [databases](#databases)
- Documents [gdrive](#gdrive) · [notion](#notion)
- Health [apple-health](#apple-health) · [clinical](#clinical) · [whoop](#whoop)
- HR tool [personio](#personio)
- Meetings & audio [plaud](#plaud) · [tactiq](#tactiq) · [voice-memos](#voice-memos) · [zoom](#zoom)
- Signing [docusign](#docusign) · Social [linkedin](#linkedin) · Tasks [clickup](#clickup)
- Web [analytics](#analytics) · [gsc](#gsc)
- [Also connectable (no plugin folder yet)](#also-connectable-no-plugin-folder-yet) · [Checklist](#checklist)

---

## Before you start

Every source below is connected with your own account: your export, your personal token, or your
own app, used only by you. Where a vendor asks for someone's approval or for admin rights in its
own product (Personio API credentials, a Slack workspace that approves apps, a work Microsoft
account), the plugin's section says so.

### Where secrets go

Two places: never the code, never git, never `sbk.config.json`.

1. **`.env`** at the repo root: `cp .env.example .env`, then fill only the lines of the sources you
   connect. Lines written `# NAME=` are optional overrides with a built-in default: remove the `# `
   only when you set a value.
2. **The Keychain** (macOS) or the system keyring (Linux), through the `keyring` library
   (`tools/secrets_adapter.py`). An entry has a *service* and an *account*, written here as
   `<service>/<account>`, for example `sbk-personio/client-id`. Add one without leaving the value in
   your shell history:

   ```bash
   uv run python -c "import keyring, getpass; keyring.set_password('sbk-personio', 'client-id', getpass.getpass('value: '))"
   ```

   On macOS the same works with `security add-generic-password -s sbk-personio -a client-id -w`
   (with `-w` last, it asks for the value). Some plugins write their own entries after a browser
   login (for example `sbk-whoop/access-token`): you do not create those.

**Container mode.** With `SBK_CONTAINERIZED=1`, `get_secret()` reads environment variables instead
of the Keychain, with the mapping `_ENV_MAP` in `tools/secrets_adapter.py` (the lines at the bottom of
`.env.example`), and `set_secret()` is ignored: run browser logins outside the container.

### Scripts that do not load `.env` by themselves

Most scripts load `.env` on start. These do not, so export the file into your shell before running
them:

```bash
set -a && source .env && set +a
```

| Script | Variables it reads |
|---|---|
| `tools/tactiq/tq-l0-download.py` | `TACTIQ_FIREBASE_API_KEY` |
| `tools/docusign/ds-l0-api.py` | `DOCUSIGN_*` |
| `tools/notion/no-l1-enrich.py` | `SBK_NOTION_*` (optional) |
| `tools/whatsapp/wa-l1-extract-photos.py` | `ANTHROPIC_API_KEY` (only with `--vision`) |
| `tools/microsoft365/ms-l0-auth.py`, `ms-l0-download.py` | `SBK_MS365_CLIENT_ID`, `SBK_MS365_TENANT` (or `microsoft365.client_id`, `microsoft365.tenant` in `sbk.config.json`) |
| `tools/zoom/zm-l0-auth.py`, `zm-l0-download.py` | `ZOOM_CLIENT_ID` (or `zoom.client_id` in `sbk.config.json`) |
| `tools/attio/at-l1-enrich.py` | `SBK_ATTIO_CONTACTS_WITHOUT_EMAIL` (optional) |

Exporting is always safe. Keep each value in one place: some scripts load `.env` over what your
shell already has (personio, whoop, clinical, apple-health), others keep the shell value (attio,
clickup, notion).

### Where data lands

Everything goes under the **data root**, `~/.sbk-data/` by default; this guide writes it
`<data root>`. To move it, set `SBK_DATA_ROOT` (read by `DATA_ROOT` in `tools/sbk_config.py`) in your
shell profile, not only in `.env`: a script that does not load `.env` before importing `sbk_config`
would otherwise use the default. Three things stay under `~/.sbk-data/` whatever you set:

- the DocuSign private key, unless you set `DOCUSIGN_PRIVATE_KEY_PATH`;
- the copy of the Plaud session, `~/.sbk-data/secrets/plaud-wt.json`;
- the Plaud speaker-naming helpers, which read `SBK_DATA` instead: set it to the same folder.

### What `sbk.config.json` holds

Copy `sbk.config.example.json` to `sbk.config.json`. SBK looks for it at the path in the env variable
`SBK_CONFIG`, then in `<data root>/sbk.config.json`, then at the repo root. Keys starting with `_help`
are notes and are ignored; an empty value keeps the built-in behaviour. Secrets never go here.

| Field | What it does |
|---|---|
| `owner` | your full name. SBK uses it to recognise you and leave you out of your own contact lists, in AI prompts ("you are drafting for …") and in the dashboard. Your first name alone also counts as a speaker label in transcripts. No built-in value: when it is missing SBK logs one warning and no stage can tell you apart from other people |
| `own_emails` | every address and alias that is you. Mail, calendar, documents and meetings from these addresses count as yours. No built-in value (missing = empty plus the same warning) |
| `own_names` | how your name is written in messages and transcripts, lower case: nicknames, initials, other spellings. `owner` is always included |
| `own_person_id` | optional: your own id (`p_…`) in the knowledge layer once the pipeline has built it. It pins your node in the relationship graph and keeps you out of your own scores. Empty = SBK uses a fixed `p_owner` node for you and finds you by name and email |
| `nickname_aliases` | optional: `{"<nickname or handle>": "<full name>"}`, lower case, for people you call by a short name in messages, transcripts or Slack group-DM names ([Names you use](#names-you-use)) |
| `email_accounts` | one label per mailbox; the same labels as the keys of `<data root>/emails/accounts.json` |
| `enabled_sources` | the plugins you connected, by folder name; `xs-pipeline-run.py --ingest` runs the L1 step only for these. Listing `microsoft365` or `imap-caldav` also keeps the `email` and `calendar` steps that read their files. Empty = every source |
| `slack.exclude_channel_patterns`, `slack.exclude_channel_ids`, `slack.user_names`, `slack.own_user_id` | optional: channels never downloaded, names Slack no longer resolves, your own Slack user id ([slack](#slack)) |
| `attio.extra_workspaces` | Attio workspaces beyond the primary one |
| `clickup.teams` | ClickUp workspaces to back up (empty = all the token sees) |
| `plaud.api_base` | API host of your Plaud region (env `SBK_PLAUD_API_BASE` wins) |
| `voice_memos.language` | transcription language, `auto` by default (env `SBK_VOICE_MEMOS_LANGUAGE` wins) |
| `voice_memos.people`, `voice_memos.companies` | optional: the people and companies to tag in your voice memos ([voice-memos](#voice-memos)) |
| `gdrive.large_shared_drives` | optional: exact names of your shared drives with heavier files ([gdrive](#gdrive)) |
| `organisations.names`, `organisations.domains`, `organisations.aliases`, `organisations.domain_aliases` | optional: your own companies and brands, the ones you run or work for. Their people count as your team, their mail domains as internal, and their names are never read as a person; `aliases` and `domain_aliases` merge other spellings and second domains. Empty = nothing is treated as internal |
| `calendar.account`, `calendar.exclude_addresses` | optional: the label of the Google account whose calendars the monitor watches for pre-meeting briefs (empty = the first mailbox), and shared team or list addresses that are never a contact ([calendar](#calendar)) |
| `network_profiles.people` | optional: the people `tools/cross-source/xs-l2-network-profiles.py` writes a profile for; copy the entry of `_example_people`. Empty = nobody is profiled |
| `chatgpt.people`, `chatgpt.companies` | optional, only with a ChatGPT export: names `cg-l1-enrich.py` tags in your conversations, besides your organisations ([chatgpt](#chatgpt)) |
| `notion.exclude_context_terms` | optional: text that marks your Notion template pages; people and companies found only next to it are dropped ([notion](#notion)) |
| `inspiration.projects` | optional: the projects the app's Inspiration triage can tag a saved idea with. Empty = your organisations' names |
| `pipeline_status.spreadsheet_id` | optional: a Google Sheet of yours that `tools/cross-source/xs-util-pipeline-status.py --push` writes the status table to. Empty = the table stays in `<data root>/pipeline-status.json` |
| `drafts.family_names`, `drafts.client_domains` | optional: who counts as family or friends, and which mail domains are clients, for the drafts ([AI history](#ai-history)) |
| `whatsapp`, `databases`, `github`, `imap_caldav`, `microsoft365`, `zoom` | options of those plugins, described in their sections |

These four fields (`owner`, `own_emails`, `own_names`, `own_person_id`) are the only place SBK learns
who you are: no script, prompt or default sets your name, your address or your id, so set at least
`owner` and `own_emails` before the first run.

The organisations and people SBK should know by name (your own companies, the nicknames you use,
the people to profile, the names some plugins tag) are set in this file too, in the rows above: the
code ships none of yours.

No step asks you to edit code. There is no `data_root` field: use `SBK_DATA_ROOT`. Times are shown in
UTC unless you set `SBK_DISPLAY_TZ` to a time zone name such as `Europe/Berlin`.

### Names you use

SBK ships no nicknames of its own. If you call someone by a short name or a handle in messages,
transcripts or Slack group-DM names, write it under `nickname_aliases`:

```json
"nickname_aliases": {"sammy": "sam demo", "samd": "sam demo"}
```

Keys and values are lower case; the value is the full name as SBK knows the person. Name matching,
the shadow-contact filter and the dashboard's Shadows page use these aliases. Aliases you add on the
Shadows page are kept in `<data root>/shadow-filters.json` and work the same way. Built in are only
generic nickname rules that name nobody (bob → robert, bill → william, beppe → giuseppe …): with them
a "Bob Smith" in a transcript can match a known "Robert Smith". A form that could point at two
different people is not used.

### After a download

The L1 step (normalise and enrich) of most plugins runs inside the pipeline:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --ingest
```

The scripts it runs are the `L1_SCRIPTS_*` lists in `tools/cross-source/xs-pipeline-run.py`, filtered by
`enabled_sources` when that list is not empty (the log names the sources it skipped).
`apple-health` and `clinical` are not in it: run their L1 by hand (commands in their sections).
`imap-caldav` and `microsoft365` write into the mail and calendar folders that the `email` and
`calendar` steps already read; the contacts that `microsoft365` writes are read by
`tools/cross-source/xs-l1-contacts-enrich.py`, which you run yourself. The WhatsApp extras
(documents and photos pulled out of exported chats) run only when you add `--whatsapp-extras`
([whatsapp](#whatsapp)).

`xs-pipeline-run.py` has four commands, and none of them downloads (L0):

| Command | What it runs |
|---|---|
| `--ingest` | L1, L2 and L3, free stages only: rereads what is on disk. The plan names the paid stages it leaves out |
| `--all` | the whole chain, the paid stages included (a model API key). Asks for your consent to spend; without a terminal it needs `--allow-spend` |
| `--propagate` | L2 and L3, incremental, from the snapshot already on disk (no L1) |
| `--rebuild` | L2 and L3 with every stage forced (no L1, no paid stages) |

`--dry-run` shows the plan of any of them without running it. The download of every source in the
registry, one after the other, is `uv run python tools/cross-source/xs-l0-refresh.py` (`--then-ingest`
runs `--ingest` after it, `--dry-run` shows the plan); sources you export by hand are listed as manual.

### How to check a source

- The file or folder named in the plugin's **Check** line exists and is recent.
- `<data root>/last-runs.json` gets a timestamp per source when a download completes
  (`mark_last_run` in `tools/sbk_config.py`).
- `uv run python tools/cross-source/xs-util-freshness.py` prints a freshness table per source
  (`--html` opens it as a page).
- `uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run` shows the plan without
  running anything, with the paid stages marked.

### The monitor and scheduled jobs (optional)

`tools/monitoring/sbk-monitor.py` keeps watching your connected sources while it runs: Slack and your
Slack DMs every 30 seconds, mail, calendars and Attio on a timer, new meeting transcripts every 15
minutes, plus freshness, disk and failed-job checks, and it alerts you ([slack](#slack), *Notifications*).
Start it with `uv run python tools/monitoring/sbk-monitor.py` (or `tools/monitoring/run-monitor.sh`, or
`uv run python tools/sbk_cli.py monitor`); `--once <check>` runs one check and exits.

**Model calls need your consent.** Five jobs of the monitor send your data to a model: new-mail
triage (sender, subject and a snippet of up to 30 new emails), pre-meeting briefs (the upcoming
meeting with its attendees' recent mail, Slack and notes), the 07:30 morning digest (your recent
mail, Slack and calendar), meeting capture (the full transcript of each new Plaud or Tactiq
recording) and retries of failed scripts that call a model. They run only if you set
`SBK_MONITOR_MODEL=1` in `.env` or start the monitor with `--with-model`; an `ANTHROPIC_API_KEY` in
`.env` is not consent. Without it the monitor still polls, downloads and alerts, and logs one line
for each job it skips. At start its log has a `Model calls:` line that says ON, or OFF with the jobs
it skips.

**Scheduled jobs.** Nothing runs on its own after the install. The `com.sbk.*.plist` files under
`tools/` (the monitor, the commitment tracker, the daily briefing, the weekly L3 cleanup and the L3
staleness alert) are macOS LaunchAgent templates with `__SBK_REPO__`, `__SBK_DATA__`, `__UV__` and
`__UV_DIR__` placeholders. The comment at the top of each file has the one `sed` line that fills them
in and the `launchctl load` command. The `run-*.sh` launchers they call find the repo from their own
location and `uv` from your PATH.

---

## Google

Five plugins read Google data: `email`, `calendar`, `gdrive`, `gsc` (Search Console) and
`analytics` (GA4). They all sign in the same way, through **your own Google app**: a Google Cloud
project of yours with an OAuth client of type *Desktop app*. Each Google account you want to read
signs in once in the browser, and the refresh token goes into the macOS Keychain. SBK reads only
what that account can open in Gmail, Calendar, Drive, Search Console or Analytics. No other kind of
Google credential is used anywhere in SBK.

### Create your Google app (once)

1. **Project.** Open <https://console.cloud.google.com/>, create a project (any name, for example
   `SBK`) and select it.
2. **APIs.** In *APIs & Services* → *Library*, enable the APIs of the plugins you will use:

   | Plugin | API to enable |
   |---|---|
   | email | Gmail API |
   | calendar | Google Calendar API |
   | gdrive | Google Drive API |
   | gsc | Google Search Console API |
   | analytics | Google Analytics Admin API and Google Analytics Data API |

3. **Consent screen.** Open *Google Auth Platform* (in older consoles: *OAuth consent screen*).
   - *Branding*: an app name (for example `SBK`) and your own address as support and developer
     contact.
   - *Audience*: user type **External**, publishing status **Testing**. Under *Test users* add every
     Google account you will sign in with (your personal Gmail, your work address, …). Only these
     accounts can use the app.
   - *Data access*: you can leave the scope list empty. Each script asks for its scopes when you sign
     in (table below).
4. **Client.** In *Clients* (older consoles: *Credentials* → *Create credentials* → *OAuth client
   ID*) create a client of type **Desktop app** and download its JSON. Save it where SBK looks:
   ```bash
   mkdir -p ~/.secrets/google-oauth
   mv ~/Downloads/client_secret_*.json ~/.secrets/google-oauth/client_secret.json
   chmod 600 ~/.secrets/google-oauth/client_secret.json
   ```
   Another path works too: put it in `.env` as `GOOGLE_OAUTH_CLIENT_SECRET_PATH=/path/to/file.json`.
   If you prefer, also copy the client id and secret into `.env` as `GOOGLE_OAUTH_CLIENT_ID` and
   `GOOGLE_OAUTH_CLIENT_SECRET`; the scripts use them first and fall back to the JSON file
   (`client_file()` and `client_id_secret()` in `tools/google_oauth.py`).

**Testing status and the 7-day login.** Google's documented rule: an app with user type External
in *Testing* gets refresh tokens that expire after 7 days. When that happens the scripts stop with
a Google `invalid_grant` error, and you run the same login command again. Two ways to keep the login:
- if your account belongs to a Google Workspace organisation and the project is created inside it,
  choose user type **Internal** instead of External (no test users, no 7-day limit, only accounts of
  that organisation can sign in);
- or set the publishing status to **In production** without asking Google for verification: the
  login then shows a "Google hasn't verified this app" page, and you continue with *Advanced* →
  *Go to SBK*. This is meant for your own accounts, the app stays yours.
(Rule checked against Google's documentation on 25/11/2026; Google may change it, look at the
consent screen page of your project.)

### What each plugin asks and where the login is kept

Every plugin keeps its own login, because each asks for different scopes. One account read by three
plugins means three browser logins, once each.

| Plugin | Scope asked at login | Login command (first time) | Keychain entry |
|---|---|---|---|
| email | `gmail.readonly` and `https://mail.google.com/` | `uv run python tools/email/em-l0-auth.py <label>` | `sbk-gmail/<label>` |
| email, inbox-zero filters only | `gmail.settings.basic` | `uv run python tools/email/em-l0-auth.py <label> --settings` | `sbk-gmail-settings/<label>` |
| calendar | `calendar.readonly` | `uv run python tools/calendar/ca-l0-download.py --account <label>` (opens the browser when no login is stored) | `sbk-gcal/<label>` |
| gdrive | `drive.readonly` | `uv run python tools/gdrive/gd-l0-auth.py --account <label>` | `sbk-gdrive/<label>` |
| gsc | `webmasters.readonly` | `uv run python tools/gsc/gs-l0-inventory.py --login <label>` | `sbk-gsc/<label>` |
| analytics | `analytics.readonly` | `uv run python tools/analytics/ga-l0-inventory.py --login <label>` | `sbk-ga/<label>` |

All scopes are under `https://www.googleapis.com/auth/` except `https://mail.google.com/`. The email
login asks the full Gmail scope next to the read-only one because the email tools that act in your
mailbox (drafts, reminders, inbox-zero labels and cleanup) use the same login; the download itself
uses only `gmail.readonly` (`SCOPES` in `tools/email/em-l0-auth.py` and `tools/email/em-l0-download.py`).

**Labels.** A label is the short name you give an account (`work`, `personal`, `main`). For email,
calendar and gdrive the labels and addresses live in `<data root>/emails/accounts.json`, written by
`em-l0-auth.py` when you sign a mailbox in:
```json
{
  "work": {"email": "you@yourcompany.example"},
  "personal": {"email": "you@personal.example"}
}
```
Sign each mailbox in to `email` first, then use the same label for calendar and gdrive. Put the same
labels in `email_accounts` in `sbk.config.json`. Search Console and Analytics keep their own list of
labels in `<data root>/gsc/accounts.json` and `<data root>/analytics/accounts.json`, written by
`--login`. The data root is `~/.sbk-data` unless you set `SBK_DATA_ROOT`.

**Where the token lives.** Only in the macOS Keychain, under the entry of the table: nothing is
written to disk next to the data. To sign an account out of SBK, delete its entry and remove the app
from your Google account:
```bash
security delete-generic-password -s sbk-gmail -a work
```
and <https://myaccount.google.com/permissions> → your app → *Delete all connections*. In container
mode (no Keychain) the scripts read `SBK_GMAIL_TOKEN_<LABEL>`, `SBK_GCAL_TOKEN_<LABEL>`,
`SBK_GDRIVE_TOKEN_<LABEL>` from the environment (`tools/secrets_adapter.py`).

**If the browser login fails**
- `Access blocked: … has not completed the Google verification process`: the account is not in the
  test users of step 3.
- `Error 403: access_denied` or a missing API: enable the API of step 2 in the same project as the
  client.
- `Google returned no refresh token`: remove the app at <https://myaccount.google.com/permissions>
  and sign in again (the scripts ask Google for consent every time, so this is rare).

---

## Using an MCP server instead of a download

For some sources the vendor runs its own MCP server. Connected to Claude Code, it lets the agent read that service
live with your own login, without a download script, a token in `.env` or anything stored in `~/.sbk-data`.

What changes:

- An MCP server answers questions in the moment. It does not fill the SBK pipeline: nothing goes to L1/L2/L3, the
  knowledge layer, the search index or the dashboard. If you want that source in your second brain, use the plugin.
- You sign in with your own account and see only what that account already sees.
- Some of these servers can also write (send, create, update). Check what the vendor lists before you connect, and
  keep the agent's write actions behind your approval.

Add a remote server with `claude mcp add --transport http <name> <url>`, then run `/mcp` in Claude Code to sign in.

_Checked on 2026-11-25._

| Source | Vendor server | URL | How you sign in | Vendor page |
|---|---|---|---|---|
| Gmail | Gmail MCP server (Developer Preview) | `https://gmailmcp.googleapis.com/mcp/v1` | an OAuth client in your own Google Cloud project; the page describes a "Personal mode onboarding" that makes a client working only for your Google account | https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server |
| Google Calendar | Google Calendar MCP server (Developer Preview) | `https://calendarmcp.googleapis.com/mcp/v1` | same as Gmail | https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server |
| Google Drive | Google Drive MCP server (Developer Preview) | `https://drivemcp.googleapis.com/mcp/v1` | same as Gmail | https://developers.google.com/workspace/drive/api/guides/configure-mcp-server |
| Google Analytics (GA4) | Google Analytics MCP server, read-only, runs on your Mac (PyPI package `analytics-mcp`, started with `uvx` or `pipx` as the page shows) | local | your own Google user login through Application Default Credentials (`gcloud auth application-default login`) with the read-only Analytics scope | https://developers.google.com/analytics/devguides/MCP |
| Slack | Slack MCP server | `https://mcp.slack.com/mcp` | your own Slack user; Slack lets only Marketplace apps and internal apps use the server, and your workspace may require approval for MCP client apps | https://docs.slack.dev/ai/slack-mcp-server/ |
| Notion | Notion MCP (hosted) | `https://mcp.notion.com/mcp` | OAuth with your Notion account | https://developers.notion.com/guides/mcp/get-started-with-mcp |
| ClickUp | ClickUp MCP server | `https://mcp.clickup.com/mcp` | OAuth with your ClickUp account (the vendor accepts OAuth only, no API key) | https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server |
| Attio | Attio MCP (hosted) | `https://mcp.attio.com/mcp` | OAuth with your Attio account, no API key | https://docs.attio.com/mcp/overview |
| DocuSign | Docusign MCP Server | the URL for your environment is on the vendor page | as described in the vendor's "Authentication & Scope" section | https://developers.docusign.com/platform/mcp-server |
| GitHub | GitHub MCP Server | `https://api.githubcopilot.com/mcp/` | OAuth, or a personal access token you create | https://github.com/github/github-mcp-server |
| Zoom | Zoom MCP server | `https://mcp.zoom.us/mcp/zoom/streamable` | OAuth with PKCE, with your Zoom account | https://developers.zoom.us/docs/mcp/ |

No vendor-run MCP server is listed here for WhatsApp, LinkedIn, Plaud, Tactiq, Whoop, Voice Memos, Apple Health
or Search Console: none was found on 2026-11-25. Third-party servers exist for some; SBK does not point to them.

---

## AI history

**What it is for.** SBK learns how you work from what you have already told your AI assistants:
the instructions you repeat, the corrections you make, how you write, how you decide. The result is
a set of identity files in `sbk/identity/` that the drafts and the dashboard chat read (the table
after the commands says which file each one reads).

> **A note from the author.** "At the start it helped me to give SBK all my past
> conversations in one go, from Manus, ChatGPT and Claude. I downloaded them and imported them, so
> it understood what I was working on and how I reason. Back then I did not have Claude Code. Now
> SBK reads the Claude Code logs too, so everything we tell it day by day and the way we talk
> to it count as well."

**Plugin**: `tools/ai-history/` · **registry id**: `ai-history`, on request (it never runs in the
full run, `tools/cross-source/xs-l0-refresh.py` lists it as manual) · **auth**: none for reading;
a model API key only for the last step, and only if you give consent.

### What it reads

| Where your messages are | Script | Notes |
|---|---|---|
| Claude Code's local logs, `~/.claude/projects/**/*.jsonl` (or `$CLAUDE_CONFIG_DIR/projects`) | `ai-l0-claude-code.py` | Keeps only what you typed at the prompt. Leaves out tool output, subagent transcripts, system reminders, slash-command and `!bash` wrappers, compaction summaries, task notifications, messages from teammates or other sessions, text put in the session by tools or scheduled prompts, prompts sent by scripts through the SDK or `claude -p` (`--include-sdk` keeps them), and blocks you pasted rather than typed. |
| A ChatGPT export (Settings > Data controls > Export data) | `ai-l0-import-export.py` | The zip as you downloaded it. Only your messages; no answers, custom instructions, hidden messages or attachments. |
| A Claude.ai export (Settings > Privacy > Export data) | `ai-l0-import-export.py` | Same: only the messages you sent, with project names. |
| Manus | `ai-l0-import-export.py --format manus` | Manus documents no readable export format (its backup tool makes encrypted archives). Save the tasks you want as `.md`, `.txt` or `.json` files in a folder. |
| Any other AI tool | `ai-l0-import-export.py --format generic --source <name>` | A folder of `.md`, `.txt` or `.json` files with turns marked (`User:`, `## You`, `"role": "user"`). |

Import only the tools you actually used. Each reader replaces its own lines in one local file,
`~/.sbk-data/ai-history/messages.jsonl` (or under `$SBK_DATA_ROOT` if you set it; mode 600), with five fields per message: `source`,
`session_id`, `project`, `ts`, `text`. Secrets in your messages (API keys, tokens, passwords in
`key = value`, private keys, credentials inside URLs) are replaced by `[REDACTED:<rule>]` before
anything is written. `--redact-emails` also replaces email addresses.

### What leaves your machine, and when

| Step | Leaves the machine |
|---|---|
| Reading Claude Code logs, importing exports | nothing |
| How you work, step 1 (statistics, recurring instructions) | nothing |
| How you work, `--dry-run` | nothing. It prints what step 2 would send and can save the exact text locally (`--show-payload`) |
| How you work, step 2 with `--yes` | a bounded sample of your typed messages plus the step 1 summary, redacted a second time (secrets, email addresses, phone numbers), sent to the model provider you choose (default Anthropic, key `ANTHROPIC_API_KEY`). Up to `--max-chars` characters of evidence per call (default 60000), one call per identity file |

Without `--yes` nothing is sent. With `--dry-run` nothing is sent even if `--yes` is there.

### Commands

```bash
# 1. your Claude Code logs: first the counts, then the real run
uv run python tools/ai-history/ai-l0-claude-code.py --dry-run
uv run python tools/ai-history/ai-l0-claude-code.py
#    narrow it if you want: --since 2026-01-01, --project <text>, --exclude-project <text>

# 2. exports of other AI chats you used (only those you have)
uv run python tools/ai-history/ai-l0-import-export.py ~/Downloads/<chatgpt-export>.zip --dry-run
uv run python tools/ai-history/ai-l0-import-export.py ~/Downloads/<chatgpt-export>.zip
uv run python tools/ai-history/ai-l0-import-export.py ~/Downloads/<claude-export>.zip
uv run python tools/ai-history/ai-l0-import-export.py ~/Documents/manus-tasks --format manus

# 3. how you work, step 1: local statistics only
uv run python tools/ai-history/ai-l3-how-you-work.py --stats-only

# 4. see exactly what step 2 would send, and how much (nothing is sent)
uv run python tools/ai-history/ai-l3-how-you-work.py --dry-run --show-payload

# 5. your consent: send it and write the identity files
uv run python tools/ai-history/ai-l3-how-you-work.py --yes
```

Step 5 writes five files in `sbk/identity/`:

| File | Read by |
|---|---|
| `profile.md` | the dashboard chat |
| `style-guide.md` | the drafts, the dashboard chat, email replies |
| `communication-playbook.md` | the drafts, the dashboard chat, email replies; one section per kind of person (`#### Investors`, `#### Clients`, `#### Partners`, `#### Team`, `#### Family / friends`, `#### Other`), the draft writer follows the section of the person you write to |
| `decision-framework.md` | the dashboard chat and its decision helper |
| `working-rules.md` | the dashboard chat; it is also the list of instructions you give your assistants, which you can paste into your `CLAUDE.md` or any assistant's custom instructions |

Who counts as Family / friends and as Clients in the playbook comes from `sbk.config.json`, section
`drafts` (`family_names`, `client_domains`); a CRM stage with "client" or "customer" in it counts as
a client too.

A file you already have is never overwritten: the new version goes next to it as `<name>.new.md`
(`--force` replaces it). Other options: `--provider anthropic|openai|gemini|deepseek`, `--model`,
`--only <file> ...`, `--lang it|es|fr|de|pt` (default: the language you use most).

`sbk/identity/` is in `.gitignore`, and your AI history lives in `~/.sbk-data/`, outside the repo:
none of it goes into git.

**Check**

- after step 1 or 2: `~/.sbk-data/ai-history/messages.jsonl` exists, is not empty, and every line
  has `"source"` set to a tool you read (`claude-code`, `chatgpt`, `claude-ai`, `manus`, or your
  `--source`);
- after step 3: `~/.sbk-data/ai-history/how-you-work-stats.json` exists and its `totals` count
  your messages (the terminal prints the same summary);
- after step 5: the five files are in `sbk/identity/` (or the `.new.md` versions next to yours), and
  `git status` does not list them.

### chatgpt

Only if you used ChatGPT. Your ChatGPT export is read by the AI history plugin, together with your
Claude.ai and Manus exports and your Claude Code logs: see [AI history](#ai-history).

The folder `tools/chatgpt/` also keeps an older script, `cg-l1-enrich.py`, which classifies a
`conversations.json` placed in `<data root>/chatgpt/`. The registry marks that source closed. If you
fill `enabled_sources` and leave `chatgpt` out, the pipeline does not run it. The names it tags are
your organisations plus `chatgpt.people` and `chatgpt.companies` in `sbk.config.json` (empty = only
your organisations).

---

## Code

### github

**Status** partial · tested with a mocked GitHub only, never against a real account. Registry `periodica`, every
7 days, inventory group (`tools/sorgenti.py`, entry `github`, `_INVENTARIO`): the inventory L1
(`xs-l1-inventario.py`) reads `repos.json` as before, and a second L1 step, `github_intake`
(`gh-l1-enrich.py`), writes the generic intake files. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`, step `inv-github`) runs `gh-l0-download.py`, and
`xs-pipeline-run.py --ingest` runs `gh-l1-enrich.py`; the kernel reads its two files through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own token, GET calls only: the repositories you own, collaborate on or reach
through an organization you belong to; their top-level folders and README (optional); the
collaborators of the repositories where you can push; issues and pull requests where you are
author or assignee, open pull requests where your review is requested from you by name (requests
made to a team you are on are left out), pull requests you reviewed and your reviews on them; the
public profile (name, public email, company) of the people found. Nothing is written on GitHub.
**You need** a personal access token of your own GitHub account; the plugin reads one token. A
fine-grained token is the safer one, but it reaches a single owner: either your own account or one
organization. If you want your own repositories and those of one or more organizations together, or
repositories where you are an outside collaborator, you need a classic token (see Limits).
**Create it** (fine-grained, read-only) On GitHub open your profile picture, **Settings**, **Developer
settings**, **Personal access tokens**, **Fine-grained tokens**, **Generate new token**. Give it a
name and an expiration. Under **Resource owner** pick your own account, or the one organization
you want to read (the token reaches only the owner you pick; the plugin uses one token at a time).
Under **Repository access** choose **All repositories** or **Only select repositories**. Under
**Permissions**, **Repository permissions**, set **Metadata: Read-only** (listing repositories and
collaborators needs it), **Issues: Read-only**, **Pull requests: Read-only** and, only if you want
folders and README, **Contents: Read-only**. Generate and copy the token.
Official steps: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
and the permission each endpoint needs:
https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens
(classic) Same path, **Tokens (classic)**, **Generate new token (classic)**, scopes `repo` and
`read:org` (`read:org` is needed to list collaborators,
https://docs.github.com/en/rest/collaborators/collaborators). `repo` also allows writing: the code
only sends GET requests (a test checks it), but the token itself could write, so keep it in the
Keychain and give it an expiration. Scopes: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
**Where the code looks** Keychain `sbk-github/token` first, then the env `GITHUB_TOKEN`, then
`GITHUB_PERSONAL_ACCESS_TOKEN` (`tools/github/gh_api.py:109`, names at `:62` and `:66`; the lines are in
`.env.example`, section "GitHub"). Both download scripts load `.env` by themselves.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-github', 'token', getpass.getpass('value: '))"
```
**sbk.config.json** nothing is required. Optional section `github` (`tools/github/gh-l0-download.py:106`,
every field with its `_help` in `sbk.config.example.json`): `since_days` (first-run window for issues
and PRs, default 365), `collaborator_affiliation` (the `affiliation` filter of GitHub's collaborators
endpoint: `direct` by default, `all` for every collaborator you can see, which on organization
repositories includes members with access through teams or base permissions, `outside` for outside
collaborators only), `skip_owners` (owners to leave out), `trees` (folders and README in the full
download, default false; the scheduled download follows this field), `max_profiles_per_run` (300),
`max_reviews_per_run` (500). If `enabled_sources` is not empty, list `github` there: it keeps the
`github_intake` step, and the generic intake reads the `github` folder only when it is listed.
**Download**
```bash
uv run python tools/github/gh-l0-download.py --dry-run   # checks the token, prints your login, writes nothing
uv run python tools/github/gh-l0-download.py             # repos, collaborators, issues, PRs, reviews
uv run python tools/github/gh-l1-enrich.py               # builds the two parquet files (also run by --ingest)
uv run python tools/github/gh-l0-inventory.py            # inventory only (repos + folders + README)
```
**Check** `<data root>/github/download-summary.json` (repos, items, people, API calls left),
`<data root>/github/repos.json`; after the L1, `<data root>/github/processed/plugin-contacts.parquet`
and `plugin-interactions.parquet`, then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- A fine-grained token reaches one owner (you or one organization), cannot reach several
  organizations at once, and cannot reach repositories where you are an outside or repository
  collaborator; those cases need a classic token (GitHub's list of gaps, managing-your-personal-
  access-tokens page above). With a fine-grained token on your own account, issues and pull
  requests in organization repositories are found only when the repository is public. An
  organization can also refuse fine-grained or classic tokens, or keep a fine-grained token pending
  until it is approved; until then it reads only public data.
- The scheduled download used to run `gh-l0-inventory.py`, which reads folders and README by default.
  It now runs `gh-l0-download.py`, which reads them only with `github.trees: true` (or `--trees`).
- Collaborators are listed only where you have write access (GitHub refuses it otherwise); the
  plugin skips the others and counts them in `collab_repos_denied`.
- People's email is the public one from their profile, so most rows have a name and a GitHub link
  but no email. `noreply` addresses are dropped. A person with no public name is written with their
  GitHub login as the name.
- Search returns at most 1,000 results per query and 30 searches per minute; the plugin pages by
  update date to go past 1,000 and waits between searches
  (https://docs.github.com/en/rest/search/search). The general limit is 5,000 requests per hour
  (https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
- A search GitHub rejects (422) stops the whole download with exit 1; what was already read stays in
  `raw/items.json`, but `state.json` and `download-summary.json` are not written for that run.
- Incremental: issues and PRs are searched from the last run minus one day. A role that changed on
  an item nobody updated since (for example you were unassigned) is fixed only by `--full`.
  Pending review requests on open pull requests are re-read in full every run. If GitHub answers a
  search with `incomplete_results`, or a search cannot get past the 1,000-results window, the
  watermark is not moved, so the next run searches the same period again
  (`watermark_kept` in `download-summary.json`).
- Review requests are only the ones made to you by name (`user-review-requested:@me`); a request
  made to a team you are on is not read, because it would count as your own commitment. The
  qualifier is on GitHub's search syntax page
  (https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests)
  and has not been tried against a real account.
- REST API version `2026-03-10` is pinned in the header (`gh_api.py`, `API_VERSION`); GitHub
  supports the previous version, `2022-11-28`, until 2028-03-10
  (https://docs.github.com/en/rest/about-the-rest-api/api-versions).
- The interaction date is the creation date of the issue or PR, the date of your last review for a
  review, and the last update for a pending review request: GitHub's search does not give the date
  you were assigned or asked.
**Alternative, an MCP server** GitHub runs its own GitHub MCP Server
(`https://api.githubcopilot.com/mcp/`), with OAuth or a personal access token you create ([Using an MCP
server](#using-an-mcp-server-instead-of-a-download)). It lets an agent read your repositories, issues
and pull requests live during a session; it does not fill SBK's data folder, so the knowledge layer and
the drafts still need the download above.

---

## Communication

### calendar

**Status** mature · registry `continua`, every 3 days.
**Reads** past and future events, with attendees, of every calendar in the account's calendar list
(holidays, birthdays, contacts and weather calendars are skipped; a calendar two of your accounts
can see is read once).
**You need** your Google app with the Google Calendar API enabled, and the mailbox labels in
`<data root>/emails/accounts.json` (sign them in to `email` first, see above).
**Create it** The first run opens the browser once per account that has no calendar login yet:
```bash
uv run python tools/calendar/ca-l0-download.py --account work --list   # sign in and list the calendars
```
**Where the code looks** the refresh token in Keychain `sbk-gcal/<label>`, the OAuth client as for
email. Container mode: `SBK_GCAL_TOKEN_<LABEL>`.
**sbk.config.json** nothing needed. Optional: `calendar.exclude_addresses`, shared team or list addresses
that are never a contact (e.g. `["team@yourcompany.example"]`), and `calendar.account`, the label of the
account whose calendars the monitor watches for pre-meeting briefs (empty = the first mailbox in
`<data root>/emails/accounts.json`).
**Download**
```bash
uv run python tools/calendar/ca-l0-download.py                 # every label; opens a login where missing
uv run python tools/calendar/ca-l0-download.py --no-login      # skip accounts with no login instead
```
**Check** `<data root>/calendars/<label>/events.parquet`; after `--ingest`,
`<data root>/enriched/contacts-calendar.parquet`.
**Limits** Without `--since` the first run reads the full history, later runs only what changed. A
login made for a different account than the label's address is refused for that label.
**Alternative, an MCP server** Google runs a Google Calendar MCP server (Developer Preview,
`https://calendarmcp.googleapis.com/mcp/v1`), with an OAuth client in your own Google Cloud project
([Using an MCP server](#using-an-mcp-server-instead-of-a-download)). It lets an agent read your
calendars live during a session; it does not fill SBK's data folder, so the knowledge layer and the
drafts still need the download above.

### email

**Status** mature · registry `continua`, every 3 days.
**Reads** your Gmail messages with their full body, the index of attachments, then contacts and who
writes to whom. It reads the mailboxes you sign in, one browser login each.
**You need** your Google app ([Google](#google)) with the Gmail API enabled.
**Create it** Sign each mailbox in:
```bash
uv run python tools/email/em-l0-auth.py work        # browser: pick the Google account of this mailbox
uv run python tools/email/em-l0-auth.py personal
uv run python tools/email/em-l0-auth.py --list      # the mailboxes signed in
```
**Where the code looks** the OAuth client (`GOOGLE_OAUTH_CLIENT_SECRET_PATH`, default
`~/.secrets/google-oauth/client_secret.json`, or `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`),
the refresh token in Keychain `sbk-gmail/<label>`, the labels in `<data root>/emails/accounts.json`.
Container mode: `SBK_GMAIL_TOKEN_<LABEL>`.
**sbk.config.json** `email_accounts` = the labels of `accounts.json`; `own_emails`, `owner`,
`own_names` so SBK recognises you in the mail.
**Download**
```bash
uv run python tools/email/em-l0-download.py --account work --dry-run   # counts only: checks the login
uv run python tools/email/em-l0-download.py --all                      # every mailbox signed in
uv run python tools/email/em-l0-download.py --account work --force     # one mailbox, full history from 2020
uv run python tools/email/em-l0-allegati.py --dry-run                  # attachments: how many and how big
uv run python tools/email/em-l0-allegati.py                            # download document attachments
```
Without `--since` or `--force` each run continues from the last completed one.
**Check** `<data root>/emails/<label>/messages.parquet` and `<data root>/emails/<label>/download.log`;
`<data root>/last-runs.json` gets `email-<label>` for each mailbox that finished without errors.
With `--all`, a mailbox that fails is named at the end and the others still run.
**Tools that act in your mailbox** (they use the same login, `https://mail.google.com/` scope):
- `tools/email/em-draft-create.py --account work --to … --subject … --body …` creates a draft
  (`--send` sends instead, `--reply-to <message id>` threads a reply).
- `tools/email/em-followup-watch.py --mailbox work --to someone@example.example --days 20` tells you
  when a mail you sent has had no reply.
- `tools/email/gsearch.py work "from:someone@example.example" 10` prints the matching messages.
- `tools/email/em-util-inbox-zero.py` keeps sender-to-label rules and turns them into Gmail filters.
  Filters need the extra login `em-l0-auth.py <label> --settings` (scope `gmail.settings.basic`).
**Limits**
- One login reads one mailbox: the account you pick in the browser. If the account does not match
  the address stored for the label, the download stops and writes nothing.
- Spam is skipped; trash is read.
- With a consent screen in *Testing*, the login has to be repeated when Google expires it (see
  [Google](#google)).
**Alternative, an MCP server** Google runs a Gmail MCP server (Developer Preview,
`https://gmailmcp.googleapis.com/mcp/v1`), with an OAuth client in your own Google Cloud project ([Using
an MCP server](#using-an-mcp-server-instead-of-a-download)). It lets an agent search and read your mail
live during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still
need the download above.

### imap-caldav

**Status** partial · registry `continua`, every 3 days (`tools/sorgenti.py`, entry `imap-caldav`). Tested
with a mocked IMAP server and a mocked CalDAV server only, never against a real account. The scheduled
download (`tools/cross-source/xs-l0-refresh.py`) runs `ic-l0-download.py` for every account. It writes
into the existing mail and calendar slots, so the kernel's own `email` and `calendar` steps of
`xs-pipeline-run.py --ingest` read it with no change.
**Reads** your mail over IMAP (TLS, read-only: nothing is marked as read, moved or deleted), by
default the Inbox and the Sent folder, and your calendars over CalDAV or from a calendar link
(ICS). Works with any provider that offers IMAP with an app password; ready-made settings for
iCloud, Fastmail, Yahoo and Outlook.com.
**You need** an account where IMAP is available to you (Fastmail: not on the Basic plan;
Outlook.com: switched off until you turn it on), and **one** of these per account:
- an **app-specific password** (iCloud, Fastmail, Yahoo, most other providers);
- for **Outlook.com**, an app registration of your own (Microsoft accepts no password on IMAP);
- for calendars without CalDAV, a **calendar link** (ICS).

**Create it** (pick your provider; each is your own password or your own app, used only by you)
- **iCloud**: two-factor authentication must be on. Sign in at
  [account.apple.com](https://account.apple.com/) → **Sign-In and Security** → **App-Specific
  Passwords** → **Generate an app-specific password**. Server `imap.mail.me.com:993`, user name
  usually the part of your address before the @ (the preset does this; put the full address in
  `username` if it is refused). Calendar: Apple documents no CalDAV address for other apps, so in
  Calendar on iCloud.com turn on **Public Calendar** for a calendar and **Copy** its link; anyone
  who has that link can view that calendar.
  [Mail server settings](https://support.apple.com/en-us/102525) ·
  [App-specific passwords](https://support.apple.com/en-us/102654) ·
  [Share a calendar](https://support.apple.com/guide/icloud/share-a-calendar-mm6b1a9479/icloud)
- **Fastmail**: **Settings → Privacy & Security → Connected apps & API tokens → Manage app
  passwords and access → New app password**, access **Mail, Contacts & Calendars**. One password
  serves IMAP (`imap.fastmail.com:993`) and CalDAV (`https://caldav.fastmail.com/`); the user name
  is your full Fastmail address.
  [Server names and ports](https://www.fastmail.help/hc/en-us/articles/1500000278342-Server-names-and-ports) ·
  [App passwords](https://www.fastmail.help/hc/en-us/articles/360058752854-App-passwords)
- **Yahoo**: [Account Security page](https://login.yahoo.com/account/security) → under
  **External connections** click **Create app password** → name it → **Generate password**. IMAP
  `imap.mail.yahoo.com:993`, CalDAV `https://caldav.calendar.yahoo.com` with the same app password.
  [IMAP settings](https://help.yahoo.com/kb/SLN4075.html) ·
  [App passwords](https://help.yahoo.com/kb/SLN15241.html) ·
  [Calendar sync](https://help.yahoo.com/kb/SLN4707.html)
- **Outlook.com** (personal Microsoft account):
  1. In Outlook.com: **Settings → Mail → Forwarding and IMAP** → turn on **Let devices and apps
     use IMAP** → **Save**.
  2. In the [Microsoft Entra admin center](https://entra.microsoft.com/): **Entra ID → App
     registrations → New registration**, any name, *Supported account types* **Personal accounts
     only** → **Register**. Copy the **Application (client) ID**.
  3. In that app: **Authentication → Advanced settings → Allow public client flows → Yes** (the
     sign-in uses the device code flow, which needs it). No client secret, no redirect URL.
  4. Put the client ID in `sbk.config.json` (`oauth_client_id` of that account) and sign in once:
     `uv run python tools/imap-caldav/ic-l0-auth.py --account <label> --xoauth2`. It prints a code
     and a Microsoft address; open it, enter the code, sign in with your Outlook.com account and
     accept. The plugin asks only `https://outlook.office.com/IMAP.AccessAsUser.All` and
     `offline_access` for your own mailbox.
  5. Calendar: Outlook.com has no CalDAV. **Settings → Calendar → Shared calendars → Publish a
     calendar** → choose the calendar → **Publish** → copy the **ICS** link. Anyone with the link
     can view or subscribe to that calendar.
  [IMAP settings](https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040) ·
  [OAuth for IMAP](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth) ·
  [Register an app](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) ·
  [Device code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) ·
  [Publish a calendar](https://support.microsoft.com/en-us/outlook/share-your-calendar-in-outlook-com)
- **Any other provider**: its help pages give the IMAP host (port 993, SSL/TLS) and, if it offers
  one, the CalDAV address; create an app password there if it has them.

Then store the secrets (hidden prompt, saved in the Keychain):
```bash
uv run python tools/imap-caldav/ic-l0-auth.py --account demo_fastmail --imap --caldav
uv run python tools/imap-caldav/ic-l0-auth.py --account demo_icloud --imap --ics
```
**Where the code looks** (Keychain first, then the env var; `<LABEL>` is the account label in upper case;
the env lines are in `.env.example`, section "IMAP / CalDAV / ICS")
- mailbox password: Keychain `sbk-mailbox/<label>`, env `SBK_MAILBOX_PASSWORD_<LABEL>`
  (`tools/imap-caldav/ic_common.py:100`)
- CalDAV password: `sbk-caldav/<label>`, env `SBK_CALDAV_PASSWORD_<LABEL>` (`ic_common.py:101`)
- calendar link: `sbk-ics/<label>`, env `SBK_ICS_URL_<LABEL>` (`ic_common.py:102`)
- Outlook.com: `sbk-imap-oauth/<label>`, env `SBK_IMAP_OAUTH_REFRESH_<LABEL>` (`ic_common.py:103`),
  rewritten when Microsoft hands out a new refresh token (`ic_common.py:443`)
**sbk.config.json** section `imap_caldav`: `accounts` (one entry per label: `preset`, `email`,
optional `username`, `folders` = `auto` / `all` / list, `mail_since`, `max_message_mb`,
`calendar` = `none` / `caldav` / `ics`, `caldav_url`, `calendar_include` / `calendar_exclude`,
`imap_host` / `imap_port` without a preset, `oauth_client_id` for Outlook.com), plus
`calendar_past_days` (730) and `calendar_future_days` (365) for recurring events.
`sbk.config.example.json` ships `accounts` empty and three worked entries under `_example_accounts`
(Fastmail, iCloud, Outlook.com) to copy into `accounts`. If `enabled_sources` is not empty, listing
`imap-caldav` there also keeps the `email` and `calendar` steps that read these slots. Add each address
you configure to `own_emails`, so the email L1 does not count you as a contact.
**Download**
```bash
uv run python tools/imap-caldav/ic-l0-download.py --check          # sign in and list folders / calendars
uv run python tools/imap-caldav/ic-l0-download.py                  # every account, incremental
uv run python tools/imap-caldav/ic-l0-download.py --account demo_fastmail --mail-only --since 2026-01-01
uv run python tools/cross-source/xs-pipeline-run.py --ingest       # the kernel rereads the slots
```
**Check** `<data root>/imap-caldav/download-summary.json` (per account: new messages, flag
changes, calendars fetched/removed, events, errors), then
`<data root>/emails/<label>/messages.parquet` and `<data root>/calendars/<label>/events.parquet`.
**Limits**
- Read-only and additive: a message deleted on the server stays in your copy; a calendar object
  deleted on the server leaves `events.parquet` and is kept in
  `<data root>/imap-caldav/raw/<label>/removed.parquet`.
- Mail folders are read in full on the first run (or from `mail_since`); later runs fetch only
  new UIDs. If a server renumbers a folder (UIDVALIDITY changes) that folder is read again, without
  duplicates. Flag changes (read, starred) are picked up only on servers with CONDSTORE.
- Messages above `max_message_mb` are cut; attachments are listed (name, type, size) but not saved.
- Recurring events are expanded only between `calendar_past_days` and `calendar_future_days`,
  at most 1,000 instances per series. Time zones with Windows names (some Outlook feeds) are kept
  as local time without offset.
- CalDAV sync-collection (RFC 6578) is not used: a changed calendar costs one listing of its
  ETags. Objects the server does not return in a `calendar-multiget` are asked again at the next
  run.
- A calendar link is downloaded whole when it changes, then stored per event: an event that is
  over and no longer in the feed (many links publish only a limited past) is kept; a future event
  that disappears from the feed is moved to `removed.parquet`. The last two copies of the whole
  feed are kept (`feed-current.ics`, `feed-previous.ics`).
- Large mailboxes: messages are requested in groups of at most 50 and about 32 MB, and written to
  disk every 500 messages, so memory stays bounded.
- Gmail and Google Calendar have their own plugins (`email`, `calendar`); a label already in
  `emails/accounts.json` is refused, so the two never write the same folder.
- Outlook.com: Microsoft's registration guide lists as prerequisites "An Azure account that has an
  active subscription", with at least the Application Developer role
  ([Register an app](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app),
  read 2026-11-25). Answers on Microsoft Q&A (not an official doc page) say a personal account can
  no longer create an app registration outside a directory. What that subscription costs was not
  checked. A work or school Microsoft 365 mailbox is out of scope here (the plugin uses the
  `consumers` sign-in only); the `microsoft365` plugin reads those through Graph.
- Fastmail Basic plans have no IMAP or CalDAV. Yahoo may refuse to create an app password from a
  browser you have not used to sign in for several days in a row.
- No provider page checked documents IMAP or CalDAV rate limits; Fastmail applies unnamed fair-use
  limits.

### microsoft365

**Status** partial · registry `continua`, every 3 days (`tools/sorgenti.py`, entry `microsoft365`). Tested
with a mocked Microsoft Graph and identity platform only, never against a real account. The scheduled
download (`tools/cross-source/xs-l0-refresh.py`) runs `ms-l0-download.py --all`. Its files go into the
kernel's existing mail, calendar and address-book slots, and the tests run the kernel's own readers
(`em-l1-enrich`, `ca-l1-extract`, `xs-l1-contacts-enrich`) on them; in `xs-pipeline-run.py --ingest` the
`email` and `calendar` steps read them.
**Reads** your Outlook mail (every folder except Junk, Deleted Items, Outbox and Outlook's system
folders), your own calendars (past and upcoming events, with attendees and their answers) and your
Outlook contacts. Works with a personal Microsoft account (Outlook.com, Hotmail, Live) and with a
work or school Microsoft 365 account **only if your organization lets you register an app and lets
users consent to these permissions**. If the sign-in shows a page asking for an administrator's
approval, this plugin cannot be used with that account: it never asks for admin consent.
**You need** a Microsoft account that can open the Microsoft Entra admin center and register an
app. Microsoft's registration guide lists as prerequisites an Azure account with an active
subscription (it links the free one), at least the Application Developer role, and a tenant,
for which your *Default Directory* is enough. Python and a browser for the one-time sign-in (or
`--device-code` to sign in from another device).
**Create it** You register your own app, used only by you:
1. Go to the [Microsoft Entra admin center](https://entra.microsoft.com), then **Entra ID** →
   **App registrations** → **New registration**.
2. Give it a name. Under **Supported account types** choose **Any Entra ID Tenant + Personal
   Microsoft accounts** (personal and work sign-in), or **Personal accounts only**, or, for a work
   account in your own organization's directory, **Single tenant only**. Click **Register**.
3. On **Overview**, copy the **Application (client) ID** (and, for a single-tenant app, the
   **Directory (tenant) ID**).
4. **Authentication** → **Add a platform** → **Mobile and desktop applications**, and add the
   redirect URI `http://localhost` exactly. The plugin listens on a free local port; Microsoft
   ignores the port of a localhost redirect.
5. Still in **Authentication**, under **Advanced settings**, set **Allow public client flows** to
   **Yes** (needed only for `--device-code`). Do not create a client secret: the app is a public
   client.
6. Nothing to add under **API permissions**: at the first sign-in the plugin asks, for your own
   account only, `User.Read`, `Mail.Read`, `Calendars.Read`, `Contacts.Read` and `offline_access`
   (`SCOPES` in `tools/microsoft365/ms_graph.py`), and you consent to them yourself. If you want
   them listed on the app, add the same five Microsoft Graph permissions there (not the
   *Application permissions* type, which this plugin never uses).
7. Put the client ID in `sbk.config.json` as `microsoft365.client_id` (and `microsoft365.tenant` =
   your tenant id for a single-tenant app), or export `SBK_MS365_CLIENT_ID` (and `SBK_MS365_TENANT`)
   in your shell: these scripts do not load `.env` by themselves. Then sign in once per mailbox,
   choosing a label that is not one of your Gmail labels:
   ```bash
   uv run python tools/microsoft365/ms-l0-auth.py --account outlook
   uv run python tools/microsoft365/ms-l0-auth.py --account outlook --device-code   # no browser here
   ```
   The browser opens on login.microsoftonline.com, you sign in and accept, and the sign-in is
   stored.

Official guides: [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) ·
[Desktop app registration (redirect `http://localhost`, public client flows)](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-registration) ·
[Authorization code flow with PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow) ·
[Device code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) ·
[Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) ·
[How users consent in an organization](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-user-consent).
**Where the code looks**
- client ID: the env variable `SBK_MS365_CLIENT_ID`, else `microsoft365.client_id` in `sbk.config.json`
  (`tools/microsoft365/ms_graph.py:191`); tenant: `SBK_MS365_TENANT`, else `microsoft365.tenant`,
  else `common` (`ms_graph.py:196`).
- the sign-in: Keychain `sbk-microsoft365/<label>` (`ms_graph.py:236`), written by `ms-l0-auth.py`
  and replaced by every download, because Microsoft returns a new refresh token at each use
  (`ms_graph.py:272`). Without a Keychain: `SBK_MS365_TOKEN_FILE` (a JSON file the plugin keeps up
  to date, mode 600), then `SBK_MS365_TOKEN_<LABEL>` as a read-only seed, both exported in your shell. The lines are in
  `.env.example`, section "Microsoft 365 / Outlook".
**sbk.config.json** section `microsoft365` (every field with its `_help` in `sbk.config.example.json`):
`client_id`, `tenant`, `accounts` (labels for `--all`, which the scheduled download uses),
`default_account`, `timezone`, `mail_history_days` (365), `mail_headers` (true),
`calendar_history_days` (365), `calendar_future_days` (90), `calendar_overlap_days` (14),
`page_size` (50). If `enabled_sources` is not empty, listing `microsoft365` there also keeps the
`email` and `calendar` steps that read this plugin's files.
**Download**
```bash
uv run python tools/microsoft365/ms-l0-download.py --account outlook          # incremental after the first run
uv run python tools/microsoft365/ms-l0-download.py --account outlook --since 2024-01-01 --full
uv run python tools/microsoft365/ms-l0-download.py --all                      # every label in microsoft365.accounts
uv run python tools/cross-source/xs-l1-contacts-enrich.py                     # contacts stage, outside the runner
uv run python tools/cross-source/xs-pipeline-run.py --ingest                  # mail and calendar L1 and the rest
```
**Check** `uv run python tools/microsoft365/ms-l0-auth.py --account outlook --check` (prints the
signed-in address), then `<data root>/microsoft365/outlook/download-summary.json` (folders, messages
changed and removed, calendar window, contacts read, `errors`), and the slot files
`<data root>/emails/outlook/messages.parquet`, `<data root>/calendars/outlook/events.parquet`,
`<data root>/contacts/contacts.parquet` (rows with `source` = `microsoft365:outlook`).
**Limits**
- Work or school accounts: if the organization blocks user consent, requires users to be assigned
  to apps, or blocks app registration, the plugin cannot be used there. Microsoft recommends that
  organizations block the device code flow, so `--device-code` may be refused on work accounts;
  use the browser sign-in.
- Only your own mailbox, calendars and contacts. Calendars other people share with you are
  skipped (the plugin asks for `Calendars.Read`, which covers your own calendars), and so are
  other mailboxes, the Exchange online archive and Teams chats.
- A mail folder or calendar that answers 403 or 404 is skipped for that run and named in the
  summary (`folders_skipped`, `calendars_skipped`); its rows stay as they are.
- Attachments are not listed: `has_attachments` is set, `attachment_count` stays 0.
- Contacts: the default folder and the contact folders Graph lists at the top level, not deeper ones.
- The calendar is re-read in a moving window: an event deleted before that window stays in the slot.
- The first mail download keeps the whole round in memory before writing; on a very large mailbox
  lower `mail_history_days` for the first run.
- The refresh token lasts 90 days by default and can be revoked earlier: if you do not download for
  longer, or the token is revoked, sign in again.
- Microsoft limits each app and mailbox pair to 10,000 requests per 10 minutes and 4
  concurrent requests; the plugin sends one request at a time, at most 10 per second
  (`MIN_INTERVAL_S`), and waits on 429 answers as told by `Retry-After`.
- Whether Graph accepts the Internet headers inside a mail delta query is not stated in Microsoft's
  docs; if a mailbox refuses them, the plugin goes on without (and the kernel then has fewer
  bulk-mail signals for that mailbox).
- The contacts step (`xs-l1-contacts-enrich.py`) is not run by `xs-pipeline-run.py`: run it yourself.
  Two downloads writing `contacts/contacts.parquet` at the same time are not coordinated: run one at
  a time.
- If `contacts/contacts.parquet` does not exist yet, or holds only rows this plugin wrote, the
  download also copies your `iphone-contacts.json` into it at every run (source
  `iphone-contacts-json`), because the kernel stops reading that JSON as the address book once
  the parquet exists. A parquet with rows from any other source is left as it is.
- A mail update that Graph returns with only some properties patches the row already in the
  slot; such an update for a message never downloaded is not written.
- Global Microsoft cloud only (login.microsoftonline.com, graph.microsoft.com), not national clouds.

### slack

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
[The monitor and scheduled jobs](#the-monitor-and-scheduled-jobs-optional).

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

### whatsapp

**Status** mature · registry `a_richiesta` (on request), a reminder every 30 days · no credential, no account to connect.
**How it works** You export your chats yourself and SBK imports the files. The export and import path
is the one the author uses; live reading of WhatsApp is not set up.
**Reads** the text of your chats, one file per chat, from two kinds of export:
- the chat export the WhatsApp app makes on your phone, one chat at a time
  (`tools/whatsapp/wa-l0l3-full.py`);
- a text export of every chat at once, one `.txt` per chat in the layout described below
  (`tools/whatsapp/wa-l0-import-history.py`). The author brought in his whole WhatsApp history this
  way, then added single chats with the phone export.

**You need** your phone with WhatsApp, a way to move the files to your Mac (AirDrop, Files, a cable,
your own cloud drive), and your name in `sbk.config.json` so SBK knows which messages are yours (see
below).

**Export from the phone** WhatsApp exports one chat at a time. For all your chats you repeat the steps
for each chat; every export becomes its own file, and SBK imports them all in one run.
- **iPhone** Open the chat → tap the contact's name or the group name at the top → *Export chat* →
  *Without Media* (SBK reads only the text) or *Attach Media* → save or send the file to your Mac.
  SBK looks for it as `WhatsApp Chat - <name>.zip` (or `.txt`).
- **Android** Open the chat → *More options* (the three vertical dots) → *More* → *Export chat* →
  *Without media* or *Include media* → choose where to send it. SBK looks for it as
  `WhatsApp Chat with <name>.txt` or `WhatsApp Chat with <name>.zip`.

Menu names are those of WhatsApp's own help pages for each phone; they can change with app updates.

**Export of every chat at once** The WhatsApp app has no single button for this. A text export of
every chat at once comes from a separate export tool on a computer that reads your phone's chats;
SBK does not include one. `wa-l0-import-history.py` reads it when it is a folder of `.txt` files, one
per chat, each message in this layout (a line of dashes between messages):
```
----------------------------------------------------
Nora Quinn
2025-03-02 10:15:00 from Nora Quinn (+44 7700 900123) - Read

Photo from the meeting
----------------------------------------------------
Nora Quinn
2025-03-02 10:16:42 to Nora Quinn - Read

Thanks Nora, very useful.
Talk next week
```
Each message is the chat name, a header line, a blank line and the text (one or more lines).
`from <name> (+<phone>)` is a message you received, `to <name>` a message you sent.
The status after the dash can be `Read`, `Delivered`, `Listened`, `Played` or `Received`; lines
`<date time> notification` are system messages and are skipped. Optional `--attachments-dir`: one
sub-folder per chat, files named `<YYYY-MM-DD HH MM SS> - <sender> - <file name>`.

**sbk.config.json**
- `owner`: your name as SBK writes it, e.g. `"Alex Demo"`. Your messages are stored under this name.
- `own_names`: every spelling of your name as your exports show it, lower case, e.g.
  `["alex demo", "alex"]`. If one is missing, your messages count as someone else's.
- Optional, under `whatsapp`: `name_overrides` (`{"<name as exported>": "<real name>"}`),
  `group_name_exclusions` (group names that appear as a sender and must never become a contact),
  `company_keywords` (company names counted in the per-chat analysis).

**Where to put the files** Phone exports (`.zip` or `.txt`, with the names the phone gives them) go in
`<data root>/whatsapp/raw/` or `<data root>/whatsapp/raw-exports/`. The data root is `~/.sbk-data`
unless you set `SBK_DATA_ROOT`. Any other folder works with `--zip-dir <folder>` (searched with its
sub-folders, repeatable). The text export of every chat can stay in any folder you pass with
`--text-dir`.

**Import**
```bash
# chats exported from the phone
uv run python tools/whatsapp/wa-l0l3-full.py --list                       # dry run: which exports it found, writes nothing
uv run python tools/whatsapp/wa-l0l3-full.py --skip-analysis              # import
uv run python tools/whatsapp/wa-l0l3-full.py --zip-dir ~/Downloads/whatsapp --skip-analysis

# a text export of every chat at once
uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder> --dry-run
uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder>
uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder> --attachments-dir <folder>

# then contacts and interactions (the pipeline runs this step for you with --ingest)
uv run python tools/whatsapp/wa-l1-enrich.py
uv run python tools/whatsapp/wa-check-ego-invariant.py                    # every row has you on one side
```
Both imports take `--declare complete` when the files are every chat of your phone, or
`--declare chat-only` when they are only some; it is written in the import receipt.

**Check**
- `<data root>/whatsapp/chats/<chat>.json`, one per chat, and `chats/chats-index.json`.
- `<data root>/whatsapp/_ricevute-import.jsonl`: one `start` and one `end` line per import, with how
  many chats came in, how many were new or updated and how many messages were added. A `start`
  without its `end` is an import that stopped half way.
- After `wa-l1-enrich.py` (or `xs-pipeline-run.py --ingest`):
  `<data root>/whatsapp/processed/contacts-whatsapp.parquet` and `interactions-whatsapp.parquet`.
- `wa-check-ego-invariant.py` prints `I-WA   green`. `I-WA2 RED` means many chats do not contain you:
  a spelling of your name is missing from `own_names`.

**Limits**
- Manual: SBK sees only what you exported. For newer messages you export again and import again; the
  same message is never written twice, nothing already imported is removed, and a chat file that a
  re-export replaces is kept in `chats/_superseded/`.
- When the same chat is exported twice, the phone import keeps the larger file.
- The phone import reads only the text of the export. Photos, voice notes and videos inside a `.zip`
  are not imported; they appear in the text only as "image omitted" or `<attached: …>` lines.
- The phone import looks only for the file names above (`WhatsApp Chat - <name>` and
  `WhatsApp Chat with <name>`, `.zip` or `.txt`). If your files have another name, rename them to
  that pattern before importing. Dates with `/`, `.` or `-`, day/month or month/day, and 24-hour or
  12-hour (AM/PM) clocks are read.
- Everything runs on your machine; the imports send nothing anywhere.

**Other WhatsApp scripts, not set up or tested by the author** They stay in `tools/whatsapp/` and each
says so at the top of the file:
- `wa-l0-chatstorage.py` reads a copy of the iPhone's chat database (`ChatStorage.sqlite`). SBK has no
  step that gets that copy from a phone.
- `wa-l1-transcribe-audio.py` and `wa-l1-inject-transcripts.py`: voice notes transcribed on your Mac
  with whisper.cpp, then written into the chats. The transcription needs the relationship scores of a
  later pipeline stage and stops without them.
- `wa-l1-process-videos.py`: video audio transcribed locally, keyframes with `ffmpeg`.
- `wa-l1-extract-docs.py` and `wa-l1-extract-photos.py`: text of documents and of screenshots from the
  attachments indexed by `--attachments-dir`. The pipeline runs them only when you ask, after the WhatsApp
  step: `uv run python tools/cross-source/xs-pipeline-run.py --ingest --whatsapp-extras` (or `--all
  --whatsapp-extras`). Without the flag the plan lists them as outside the run. With no attachments they do
  nothing. `wa-l1-extract-photos.py --vision` sends photos to the Anthropic API (needs `ANTHROPIC_API_KEY`)
  and runs only when you add that flag; the pipeline never adds it.
- `wa-l1-fetch-links.py --fetch` opens on the web every link shared in your chats; without `--fetch` it
  only counts them.

---

## CRM

### attio

**Status** mature · registry `continua`, every 7 days.
**Reads** companies, people, deals, lists, notes, meetings, call recordings and transcripts, tasks.
**You need** an Attio API token of your workspace with read access.
**Create it** In your Attio workspace settings, in the developer section, create an access token
with read scopes for the objects you want to export. Put it in `.env` as `ATTIO_API_KEY`.
**Where the code looks** `ATTIO_API_KEY` in `.env` for your primary workspace
(`get_api_key` in `tools/attio/at-l0-download.py`). If it is not set there and you already have an
Attio MCP server configured with an API key in Claude Code, the downloader reuses that key
(`~/.claude.json`, `mcpServers.attio.env.ATTIO_API_KEY`). Attio's own hosted MCP server signs in
with OAuth and has no key to reuse. Extra workspaces read the Keychain entry
`sbk-attio/<label>`.
**sbk.config.json** nothing for one workspace. More workspaces go in `attio.extra_workspaces`
(`{"<label>": "<name>"}`); their data lands in `<data root>/attio-<label>/`.
**Download**
```bash
uv run python tools/attio/at-l0-download.py                        # every configured workspace
uv run python tools/attio/at-l0-download.py --workspace primary    # one workspace
uv run python tools/attio/at-l0-download.py --only notes           # one section
```
**Check** `<data root>/attio/companies.parquet`, `people.parquet`, `notes.parquet`,
`meetings.parquet`, `transcripts/`; after `--ingest`,
`<data root>/attio/processed/contacts-attio.parquet`.
**Limits** Without a key it stops with a message and downloads nothing.
The lane for contacts without an email is off by default: turn it on with
`SBK_ATTIO_CONTACTS_WITHOUT_EMAIL=1` exported in your shell (`tools/attio/at-l1-enrich.py` does not load
`.env` by itself), or pass `--contacts-without-email` when you run that script by hand.
**Alternative, an MCP server** Attio runs its own hosted MCP server (`https://mcp.attio.com/mcp`), with
OAuth on your Attio account and no API key ([Using an MCP
server](#using-an-mcp-server-instead-of-a-download)). It lets an agent ask your CRM questions live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

### databases

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

---

## Documents

### gdrive

**Status** mature · registry `continua`, every 7 days.
**Reads** the text of your documents, their owners, the shared drives you are a member of, the files
shared with you.
**You need** your Google app with the Google Drive API enabled, and the labels in
`<data root>/emails/accounts.json`.
**Create it**
```bash
uv run python tools/gdrive/gd-l0-auth.py --account work   # browser login, once per account
```
**Where the code looks** Keychain `sbk-gdrive/<label>` (refresh token, client id and secret, the
account's address), fallback `sbk-gdrive/default` when the address matches. Container mode:
`SBK_GDRIVE_TOKEN_<LABEL>` or `SBK_GDRIVE_TOKEN_JSON`. L1 recognises you, and so your own
documents, from `owner`, `own_names` and `own_emails` in `sbk.config.json`.
**sbk.config.json** nothing needed. Optional, `gdrive.large_shared_drives`: the exact names of shared
drives whose files are heavier, for example `"gdrive": {"large_shared_drives": ["Design assets"]}`.
Their files may be up to the second size limit of the pipeline settings ("Files up to, in your large
shared drives", 50 MB by default, `--max-size-mb-large` for one run). Empty list = one size limit for
every drive.
**Download**
```bash
uv run python tools/gdrive/gd-l0-download.py --account work --mode recent --dry-run   # list only
uv run python tools/gdrive/gd-l0-download.py --mode full-sync --days 0   # first time, full history
uv run python tools/gdrive/gd-l0-download.py --mode full-sync            # afterwards, last 14 days
```
**Check** `<data root>/gdrive/<label>/` and `<data root>/gdrive/gdrive-index.json`; after `--ingest`,
`<data root>/gdrive/processed/contacts-gdrive.parquet`.
**Limits** Files above 15 MB are skipped unless you pass `--max-size-mb`; images, video and audio
only with `--include-media`.
**Alternative, an MCP server** Google runs a Google Drive MCP server (Developer Preview,
`https://drivemcp.googleapis.com/mcp/v1`), with an OAuth client in your own Google Cloud project ([Using
an MCP server](#using-an-mcp-server-instead-of-a-download)). It lets an agent search and read your
documents live during a session; it does not fill SBK's data folder, so the knowledge layer and the
drafts still need the download above.

### notion

**Status** works in code · registry `chiusa` (closed): the registry marks the downloader as no longer
maintained, but `no-l0-download.py` ships and pages already fetched are still read.
**Reads** the pages, databases, blocks and comments you share with your integration, read-only.
**You need** a Notion internal integration token of your own workspace.
**Create it** In Notion, open the integrations page (Settings → Connections → *Develop or manage
integrations*), create an internal integration with the *Read content* capability and copy its
secret. Then open each page or database you want SBK to read and add the integration to it
(*Connections* in the page menu): Notion lets an integration read only what is shared with it.
**Where the code looks** `NOTION_TOKEN` in `.env` (`tools/notion/no-l0-download.py`, line 35).
Optional, for the L1 step: `SBK_NOTION_PERSON_PROPERTIES`, `SBK_NOTION_PERSON_NAME_PROPERTIES`,
`SBK_NOTION_CONTACT_DB_TITLES`, `SBK_NOTION_COMPANY_DB_TITLES` (comma-separated, case-insensitive)
add your own property names and database titles to the built-in ones
(`tools/notion/no-l1-enrich.py`). That script does not load `.env` by itself: export it first if you
set them (see [Before you start](#before-you-start)).
**sbk.config.json** optional, `notion.exclude_context_terms`: text that marks your template pages, for
example a placeholder domain (`["template.example"]`); people and companies found only next to it are
dropped. Empty = nothing dropped.
**Download**
```bash
uv run python tools/notion/no-l0-download.py
uv run python tools/notion/no-l0-download.py --force   # download everything again
```
**Check** `<data root>/notion/pages/` and `<data root>/notion/download-summary.json`; after
`--ingest`, `<data root>/notion/processed/entities-notion.parquet`.
**Limits** See Status.
**Alternative, an MCP server** Notion runs its own hosted Notion MCP (`https://mcp.notion.com/mcp`),
with OAuth on your Notion account ([Using an MCP server](#using-an-mcp-server-instead-of-a-download)).
It lets an agent search and read your pages live during a session; it does not fill SBK's data folder,
so the knowledge layer and the drafts still need the download above.

---

## Health

### apple-health

**Status** partial: downloads and processes, but no kernel stage reads its output yet. Not in the registry.
**Reads** the export of the Health app on your iPhone.
**You need** the export zip.
**Create it** In the Health app, tap your profile picture → *Export All Health Data*. You get
`export.zip`; move it to your computer.
**Where the code looks** the newest `*.zip` in `<data root>/apple-health/imports/`
(`find_latest_zip` in `tools/apple-health/ah-l0-import.py`), or the file you pass with `--file <zip>`.
**sbk.config.json** none.
**Download**
```bash
uv run python tools/apple-health/ah-l0-import.py
uv run python tools/apple-health/ah-l1-process.py     # the pipeline does not run this step
```
**Check** `<data root>/apple-health/processed/metrics.parquet`.
**Limits** Health data, kept on your machine. Nothing in this repo reads `metrics.parquet` downstream.

### clinical

**Status** partial: read only by the dashboard's Performance view. Not in the registry.
**Reads** clinical documents you add yourself (PDF or image): blood tests, visits, vaccinations,
allergies, medications, ECG, imaging (`VALID_TYPES` in `tools/clinical/cl-l0-ingest.py`).
**You need** the documents, plus two API keys for the parsing step: `DEEPSEEK_API_KEY` and
`ANTHROPIC_API_KEY` in `.env`.
**Where the code looks** the files you pass with `--file` or `--batch <folder>`; the parsing step reads
`<data root>/clinical/incoming/`.
**sbk.config.json** none of its own. `--subject` is a label for the person the documents belong to.
Its default is your `owner` from `sbk.config.json`, in lower case, and the dashboard's Performance view
shows that subject. Pass `--subject <label>` for documents of someone else. Without an `owner` the
scripts ask for `--subject`.
**Download**
```bash
uv run python tools/clinical/cl-l0-ingest.py --file report.pdf --type blood_test --date 2026-01-31 --subject <label>
uv run python tools/clinical/cl-l1-parse.py         # the pipeline does not run this step
uv run python tools/clinical/cl-alerts.py --subject <label>
```
**Check** `<data root>/clinical/processed/values.parquet` and `alerts.json`.
**Limits** **The documents leave your machine during parsing.** `cl-l1-parse.py` sends the extracted
text to the DeepSeek API, and images, or texts under 100 characters, to the Anthropic API. Decide
before you run it whether that is acceptable for your data. Without the keys, the parsing stops with
an error and nothing is sent.

### whoop

**Status** partial: read only by the dashboard's Performance view, not by the knowledge layer ·
registry `continua`, every 7 days.
**Reads** recovery, sleep, cycles (strain), workouts of your WHOOP account.
**You need** a WHOOP developer app of your own (OAuth2).
**Create it** In the WHOOP developer dashboard create an app with the redirect URI
`http://localhost:8000/oauth/whoop/callback` and the scopes
`offline read:recovery read:sleep read:workout read:cycles read:profile`
(`tools/whoop/wp-l0-auth.py`). Copy its client ID and secret.
**Where the code looks** `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET` in `.env`, otherwise the Keychain
entries `sbk-whoop/client-id` and `sbk-whoop/client-secret`. The login stores your tokens in
`sbk-whoop/access-token` and `sbk-whoop/refresh-token`.
**sbk.config.json** none.
**Download**
```bash
uv run python tools/whoop/wp-l0-auth.py          # browser login, local callback on port 8000
uv run python tools/whoop/wp-l0-download.py --full
uv run python tools/whoop/wp-l0-download.py      # afterwards: the last 7 days (--days N)
```
**Check** `<data root>/whoop/raw/`; after `--ingest`, `<data root>/whoop/processed/daily.parquet`.
**Limits** Physiological data. Port 8000 must be free during the login. In container mode
(`SBK_CONTAINERIZED=1`) the login cannot store the tokens, so run it outside a container.

---

## HR tool

### personio

**Status** mature · registry `periodica`, every 7 days · **an organisation HR source that needs
admin rights in Personio.** Unlike the other plugins it does not read only your own data: it reads
your organisation's HR records, for everyone the credentials can see.
**Reads** employee records, absences and balances, employments (contract history), documents,
compensations, recruiting.
**You need** Personio API credentials (client ID and secret) with read access. Only a Personio
account with admin rights can create them: you are an admin of your organisation's Personio, or an
admin creates them for you.
**Create it** In Personio's API credentials settings, generate a client ID and secret and grant read
access to the attributes you want.
**Where the code looks** `PERSONIO_CLIENT_ID` and `PERSONIO_CLIENT_SECRET` in `.env`, otherwise the
Keychain entries `sbk-personio/client-id` and `sbk-personio/client-secret`
(`tools/personio/pe-l0-download.py`).
**sbk.config.json** none.
**Download**
```bash
uv run python tools/personio/pe-l0-download.py --dry-run
uv run python tools/personio/pe-l0-download.py
```
**Check** `<data root>/personio/employees-flat.json`; after `--ingest`,
`<data root>/personio/processed/employees.parquet`.
**Limits** HR data of other people, including compensation: it stays on your machine; decide with
your organisation who may run it and which attributes the credentials expose.
Attendance records are not downloaded.

---

## Meetings & audio

### plaud

**Status** mature · registry `continua`, every 7 days.
**Reads** recordings, transcripts and summaries of your Plaud recorder account.
**You need** macOS with the Plaud desktop app installed and logged in to your account at least once.
Node.js (`npm`) only for the fallback path below.
**Create it** Nothing to create: SBK reuses the session of your Plaud desktop app.
**Where the code looks** The session token of the Plaud desktop app, read locally
(`tools/plaud/pl_auth_refresh.py`); SBK keeps a copy in `~/.sbk-data/secrets/plaud-wt.json`
(fixed path, it does not follow `SBK_DATA_ROOT`). If that fails, it decrypts the app's storage
(`~/Library/Application Support/Plaud/encryption.json`) with an Electron helper in
`tools/plaud/electron-decrypt/` (installs Electron with `npm` on first use), using the Keychain entry
the Plaud app creates for itself (`Plaud Safe Storage` / `Plaud Key`). You do not add any key.
**sbk.config.json** `plaud.api_base`: the API host of your account's region, default
`https://api-euc1.plaud.ai` (EU); the env variable `SBK_PLAUD_API_BASE` wins.
**Download**
```bash
uv run python tools/plaud/pl-l0-download.py --dry-transcriptions   # how many transcriptions it would request, calls nothing
uv run python tools/plaud/pl-l0-download.py --no-transcribe        # download only, request no transcription
uv run python tools/plaud/pl-l0-download.py
```
**Check** `<data root>/plaud/raw/_file_index.json` and the recording files in `<data root>/plaud/raw/`.
**Limits** By default each run also asks Plaud to transcribe the recordings that have no
transcription yet (recordings of at least 40 seconds, up to 1,200 minutes a day), as the app's
*Auto generation* does: this uses the transcription minutes of your Plaud plan. The defaults live in
`<data root>/system/pipeline-settings.json`, section `plaud` (`transcribe`, `min_seconds`,
`minutes_per_day`, defined in `tools/impostazioni_pipeline.py`, and
`uv run python tools/impostazioni_pipeline.py` prints every setting in force); `--transcribe` /
`--no-transcribe` override them for one run. macOS only. `--chrome` is an older mode that reads through an open
plaud.ai tab in Chrome. The speaker analysis in the pipeline (`tools/plaud/pl-analyze-speakers.py`) recognises
you from `owner`, `own_names` and `own_emails` in `sbk.config.json`. If you move the data root, also set `SBK_DATA` to the same folder: the Plaud
speaker-naming helpers (`pl_lotto.py`, `pl_quadro.py`, `pl_lunghe.py`, `pl_dettagli.py`,
`pl_quadro_pagina.py`, `regole/*.py`) read that variable, not `SBK_DATA_ROOT`.

### tactiq

**Status** mature · registry `continua`, every 14 days.
**Reads** the meeting transcripts of your Tactiq account, including meetings shared with you
(`--no-shared` for your own only).
**You need** macOS, Google Chrome logged in to the Tactiq web app (`app.tactiq.io`) with your account,
and the Firebase web API key that the Tactiq web app itself uses.
**Create it** The key is public: it is the `key=` parameter of the requests the Tactiq web app sends
to `securetoken.googleapis.com` (Chrome → Developer tools → Network, with `app.tactiq.io` open).
Put it in `.env` as `TACTIQ_FIREBASE_API_KEY`.
**Where the code looks**
- default mode: runs JavaScript in your open Tactiq tab through AppleScript
  (`chrome_js` in `tools/tactiq/tq-l0-download.py`); in Chrome, allow *View → Developer → Allow
  JavaScript from Apple Events*. A still-valid session needs no key; an expired one is refreshed
  with `TACTIQ_FIREBASE_API_KEY`.
- `--direct`: reads the refresh token from Chrome's storage for the Tactiq site
  (`~/Library/Application Support/Google/Chrome/<profile>/IndexedDB/`), exchanges it with
  `TACTIQ_FIREBASE_API_KEY`, and keeps a copy in the Keychain entry `sbk-tactiq/refresh-token`,
  used when Chrome's copy has expired.
**sbk.config.json** none.
**Download** (this script does not load `.env` by itself: export it first, see
[Before you start](#before-you-start))
```bash
uv run python tools/tactiq/tq-l0-download.py
uv run python tools/tactiq/tq-l0-download.py --direct     # without AppleScript
uv run python tools/tactiq/tq-l0-download.py --verify     # completeness check
```
**Check** `<data root>/tactiq/raw/_meeting_index.json` and one `.json` + `.txt` per meeting; after
`--ingest`, `<data root>/tactiq/processed/contacts-tactiq.parquet`.
**Limits** macOS and Chrome only. When the same call exists in Attio and in Tactiq, the Attio
transcript takes precedence.

### voice-memos

**Status** mature · registry `spot` (only when there is something new).
**Reads** `.m4a` voice memos and transcribes them on your machine.
**You need** `ffmpeg` (with `ffprobe`), `whisper-cli` from whisper.cpp, and the model file at the fixed
path `~/whisper-models/ggml-large-v3-turbo.bin` (`WHISPER_MODEL` in
`tools/voice-memos/vm-l0-transcribe.py`).
**Create it** Copy your memos out of the Voice Memos app as `.m4a` files (on a Mac, drag them from the
app to a Finder folder; on an iPhone, share them and save to Files).
**Where the code looks** `<data root>/voice-memos/*.m4a` (`VOICE_MEMOS_DIR` in `tools/sbk_config.py`).
**sbk.config.json** `voice_memos.language`: `auto` (default, detected per memo) or a code such as
`en`, `it`, `de`. The env variable `SBK_VOICE_MEMOS_LANGUAGE` wins over the file. Optional,
`voice_memos.people` and `voice_memos.companies`: the names `vm-l1-enrich.py` tags when you say them
in a memo. It looks only for the names you list; empty = no person or company tags:

```json
"voice_memos": {"language": "auto", "people": ["Sam Demo"], "companies": ["Example Ltd"]}
```
**Download**
```bash
uv run python tools/voice-memos/vm-l0-transcribe.py
uv run python tools/voice-memos/vm-l0-transcribe.py --workers 2   # fewer parallel models, less memory
```
**Check** `<data root>/voice-memos/voice-memos.parquet` and the text files in
`<data root>/voice-memos/transcripts/`.
**Limits** Transcription runs locally; nothing is sent out. Each worker loads a Whisper model, so
the default number of workers is computed from the free memory.

### zoom

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `zoom`). Tested with a
mocked Zoom API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `zm-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`zm-l1-enrich.py` (step `zoom`). It writes the generic intake contract
(`tools/cross-source/plugin_intake.py`): the people you met reach the contact merge (`xs-l2-merge.py`)
and the person facts (`xs-l2-knowledge-extract.py`). Meetings are written as `done`, so they never
become commitments, and no kernel stage reads the transcript text yet.
**Reads** the meetings you host that have a cloud recording, the participant list of each one, and
the audio transcript (VTT) Zoom makes from the recording. With `--include-unrecorded` (or
`zoom.include_unrecorded`) also your past scheduled meetings without a recording (participants only).
**You need** a Zoom account on a **Pro plan or higher** with cloud recording on (Zoom lists
recordings and past participants only on paid plans), and **Create audio transcript** turned on in
your cloud-recording settings if you want transcripts (on your own Pro account you are the owner,
so you can turn it on: [Zoom support guide](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065911)).
Python and a browser on the same machine for the one-time login.
**Create it** You create your own app, used only by you:
1. Go to the [Zoom App Marketplace](https://marketplace.zoom.us/), sign in, click **Develop** →
   **Build an app** → **General app**.
2. On **Basic Info**, under *Select how the app is managed*, choose **User-managed** (the app sees
   only your own data).
3. In **App Credentials** turn on **Use Public Client OAuth** and copy the **public client ID**.
   You do not need the client secret.
4. Set the public client's redirect URL to `http://127.0.0.1/callback` and add the same URL to the
   OAuth allow list. Use `127.0.0.1`, not `localhost`; Zoom ignores the port.
5. On **Scopes** add these user-level scopes (no `:admin` ones):
   `user:read:user`, `cloud_recording:read:list_user_recordings`,
   `meeting:read:list_past_participants`, and optionally `meeting:read:list_meetings`.
6. Put the public client ID in `sbk.config.json` as `zoom.client_id` (or export `ZOOM_CLIENT_ID` in
   your shell: the Zoom scripts do not load `.env` by themselves), then sign in once:
   ```bash
   uv run python tools/zoom/zm-l0-auth.py
   ```
   The browser opens on zoom.us, you click **Allow**, and the login is stored.

Official guides: [Create an OAuth app](https://developers.zoom.us/docs/integrations/create/) ·
[PKCE and loopback redirect](https://developers.zoom.us/docs/integrations/PKCE/) ·
[OAuth scopes](https://developers.zoom.us/docs/integrations/oauth-scopes-overview/).
**Where the code looks**
- the env variable `ZOOM_CLIENT_ID`, else `zoom.client_id` in `sbk.config.json`, else Keychain
  `sbk-zoom/client-id` (`tools/zoom/zm_api.py:156`).
- the login: Keychain `sbk-zoom/default` (`tools/zoom/zm_api.py:180`), written by
  `zm-l0-auth.py` and replaced at every download, because Zoom hands out a new refresh token each
  time (`tools/zoom/zm_api.py:201`). Without a Keychain: `ZOOM_TOKEN_FILE` (a file the plugin
  keeps up to date, mode 600), then `ZOOM_REFRESH_TOKEN` as a one-time seed, both exported in your
  shell. The lines are in `.env.example`, section "Zoom".
**sbk.config.json** section `zoom` (with its `_help` lines in `sbk.config.example.json`): `client_id`
(optional), `history_days` (first run, default 90), `overlap_days` (default 7), `include_unrecorded`
(default false). If `enabled_sources` is not empty, list `zoom` there.
**Download**
```bash
uv run python tools/zoom/zm-l0-download.py            # incremental after the first run
uv run python tools/zoom/zm-l0-download.py --days 365 # first run further back
uv run python tools/zoom/zm-l1-enrich.py              # raw -> intake parquet (also run by --ingest)
```
**Check** `<data root>/zoom/download-summary.json` (meetings, transcripts, participant lists,
`missing_scopes`), the files in `<data root>/zoom/raw/`, then
`<data root>/zoom/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- Free plan: no cloud recordings and no past-participant lists through the API, so nothing to read.
- Only meetings you **host**. Meetings you joined as a guest are not in your recordings.
- Zoom shows the email of people outside your account only in some cases (registration, calendar
  invite through Zoom's calendar integration, authenticated join); otherwise they appear by name.
- Participant lists exist for the last 15 months and, by default, not for one-person meetings.
- Transcripts come only from cloud recordings with *Create audio transcript* on; local recordings
  and meetings without recording have none.
- Your refresh token lasts 90 days without use: if you do not download for longer, sign in again.
- Made for a Zoom account you own. If someone else runs your account, its settings may stop you
  from building the app or turning transcripts on; this plugin does not cover that case.
- A transcript or participant list that is not ready yet is asked again on the next run if the
  meeting still falls inside the re-read window (`overlap_days` before the last completed day).
  If Zoom keeps failing on one item (server or network error), the saved day does not move, so
  nothing is skipped for good.
- The plugin sends one request every 0.5 s and stops cleanly at Zoom's daily limit, keeping what
  it downloaded.
- Recording passcodes in Zoom's answer are never written to disk, and `pwd=` is removed from links.
**Alternative, an MCP server** Zoom runs its own Zoom MCP server
(`https://mcp.zoom.us/mcp/zoom/streamable`), with OAuth and PKCE on your Zoom account ([Using an MCP
server](#using-an-mcp-server-instead-of-a-download)). It lets an agent ask about your meetings live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

---

## Signing

### docusign

**Status** mature · registry `periodica` (periodic), every 30 days.
**Reads** envelopes, signers and signed documents of your DocuSign account.
**You need** a DocuSign app of your own with the JWT grant: its integration key, an RSA key pair,
your API user ID and, if you belong to more than one account, the account ID. Freemium accounts have
no API access (registry note).
**Create it** In DocuSign, open *Apps and Keys*: create an app, generate an RSA key pair and save the
private key as `~/.sbk-data/secrets/docusign-private.key` with permissions 600 (another path goes in
`DOCUSIGN_PRIVATE_KEY_PATH`; this default does not follow `SBK_DATA_ROOT`). Add the redirect URI
`http://localhost:8765/docusign/callback` (or your own, in `DOCUSIGN_REDIRECT_URI`). Copy the
integration key, your API user ID and the account ID into `.env`. Then give your consent once:
```bash
uv run python tools/docusign/ds-l0-api.py --consent-url    # open the printed URL and accept
```
**Where the code looks** env first, then the Keychain (`_cred` in `tools/docusign/ds-l0-api.py`):
`DOCUSIGN_INTEGRATION_KEY` or `sbk-docusign/integration-key`, `DOCUSIGN_USER_ID` or
`sbk-docusign/user-id`, `DOCUSIGN_ACCOUNT_ID` or `sbk-docusign/account-id` (optional: without it the
default account of your user is read). Key file at `DOCUSIGN_PRIVATE_KEY_PATH`.
`DOCUSIGN_AUTH_HOST` defaults to `account.docusign.com` (production).
**sbk.config.json** none.
**Download** (this script does not load `.env` by itself: export it first, see
[Before you start](#before-you-start))
```bash
uv run python tools/docusign/ds-l0-api.py --dry-run     # token, user, envelope count, writes nothing
uv run python tools/docusign/ds-l0-api.py
uv run python tools/docusign/ds-l0-api.py --since 2026-01-01
```
**Check** `<data root>/docusign/raw/envelopes-api.json` and `<data root>/docusign/contracts-metadata.json`;
after `--ingest`, `<data root>/docusign/processed/contacts-docusign.parquet`.
**Limits** The app asks the scopes `signature impersonation`: with the JWT grant the app acts as your
own user, after your consent. `DOCUSIGN_API_BASE` and `DOCUSIGN_FROM_DATE` are read only by the older
scraper `ds-l0-scrape.py`, which is not part of this path.
**Alternative, an MCP server** Docusign runs its own Docusign MCP Server (the URL and sign-in for your
environment are on the vendor page), with your own Docusign account ([Using an MCP
server](#using-an-mcp-server-instead-of-a-download)). It lets an agent look up your envelopes live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

---

## Social

### linkedin

**Status** mature · registry `a_richiesta` (on request), every 30 days.
**Reads** your connections, invitations, endorsements received and given, company follows, positions,
skills and profile, from LinkedIn's data export of your own account.
**You need** the export of your LinkedIn data. No token, no app.
**Create it** In LinkedIn, open Settings → Data privacy → *Get a copy of your data* and request the
archive. LinkedIn sends you an email when it is ready; download the zip and unzip it into
`<data root>/linkedin/raw/export-part1/`. Another folder name under `<data root>/linkedin/raw/` works
too: pass it with `--source <folder>`.
**Where the code looks** the CSV files of the export in that folder: `Connections.csv`,
`Invitations.csv`, `Endorsement_Received_Info.csv`, `Endorsement_Given_Info.csv`,
`Company Follows.csv`, `Positions.csv`, `Skills.csv`, `Profile.csv`
(`tools/linkedin/li-l0-import-export.py`, `main()`). A file that is missing from your export is skipped.
**sbk.config.json** none.
**Download**
```bash
uv run python tools/linkedin/li-l0-import-export.py --dry-run   # counts only, writes nothing
uv run python tools/linkedin/li-l0-import-export.py
```
**Check** `<data root>/linkedin/raw/export-connections.parquet`; after `--ingest`,
`<data root>/linkedin/processed/contacts-linkedin.parquet`.
**Limits** The export is the connection path. The folder also holds browser scripts
(`li-l0-scraper.js`, `scripts/`) with a safety module (`li_safety.py`): they are not part of this
path and this guide does not set them up; the registry asks to respect the provider's rate limits.
In the knowledge layer LinkedIn enriches people SBK already knows and does not create new ones
(`LINKEDIN_CONIA_NUOVI = False` in `tools/cross-source/xs-l2-knowledge-extract.py`).

---

## Tasks

### clickup

**Status** mature · registry `continua`, every 7 days.
**Reads** a backup of spaces, lists, tasks, comments, docs and time entries; becomes tasks and
`commitment` entities in the knowledge layer.
**You need** your ClickUp personal API token.
**Create it** In ClickUp, open your avatar → *Settings* → *Apps* and generate the personal API token.
Put it in `.env` as `CLICKUP_API_KEY`.
**Where the code looks** `CLICKUP_API_KEY` (`tools/clickup/cu-l0-backup.py`, read on start; the script
loads `.env` from the repo root).
**sbk.config.json** nothing needed: without `clickup.teams` the backup asks ClickUp which workspaces
your token sees and backs up each one. To limit it, list them in `clickup.teams`
(`{"<workspace id>": "<name>"}`; the id is the number in your ClickUp web addresses). `--team <id>`
runs one.
**Download**
```bash
uv run python tools/clickup/cu-l0-backup.py --dry-run
uv run python tools/clickup/cu-l0-backup.py
uv run python tools/clickup/cu-l0-backup.py --incremental   # only tasks changed since the last run
```
**Check** `<data root>/clickup/backup/_meta/manifest.json` and `<data root>/clickup/backup/spaces/`;
after `--ingest`, `<data root>/clickup/processed/tasks.parquet` and `people.parquet`.
**Limits** The first workspace is stored in `<data root>/clickup/backup/`, the others in
`<data root>/clickup/backup-<id>/`; the L1 reads all of them. `--skip-docs` and `--skip-time` leave
out docs and time entries.
**Alternative, an MCP server** ClickUp runs its own ClickUp MCP server (`https://mcp.clickup.com/mcp`),
with OAuth on your ClickUp account (no API key) ([Using an MCP
server](#using-an-mcp-server-instead-of-a-download)). It lets an agent read your tasks live during a
session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need the
download above.

---

## Web

### analytics

**Status** mature (feeds the domain inventory, not people) · registry `periodica`, every 30 days.
**Reads** the GA4 properties your Google account can see, with sessions, users, channels and top pages.
**You need** your Google app with the Google Analytics Admin API and Data API enabled, and a Google
account with at least Viewer access to the GA4 properties.
**Create it**
```bash
uv run python tools/analytics/ga-l0-inventory.py --login main   # browser login; prints how many properties it sees
```
**Where the code looks** Keychain `sbk-ga/<label>`, the labels in `<data root>/analytics/accounts.json`,
the OAuth client as for email.
**sbk.config.json** nothing.
**Download**
```bash
uv run python tools/analytics/ga-l0-inventory.py                  # last 28 days (--days N to change)
uv run python tools/analytics/ga-l0-inventory.py --account main   # one signed-in account only
```
**Check** `<data root>/analytics/property.json` and `<data root>/analytics/performance/`.
**Limits** Covers only GA4 properties (not Universal Analytics). A property seen by two of your
accounts is read once. Without any login the script stops with a message and does nothing.
**Alternative, an MCP server** Google publishes a read-only Google Analytics MCP server that runs on
your Mac (PyPI package `analytics-mcp`), with your own Google user login ([Using an MCP
server](#using-an-mcp-server-instead-of-a-download)). It lets an agent query your GA4 properties live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

### gsc

**Status** mature (feeds the domain inventory, not people) · registry `periodica`, every 30 days.
**Reads** the Search Console properties your Google account can see, with clicks, impressions, top
queries and top pages.
**You need** your Google app with the Google Search Console API enabled, and a Google account that
is an owner or user of the properties in Search Console.
**Create it**
```bash
uv run python tools/gsc/gs-l0-inventory.py --login main   # browser login; prints how many properties it sees
```
Repeat with another label for each other account that sees other properties.
**Where the code looks** Keychain `sbk-gsc/<label>`, the labels in `<data root>/gsc/accounts.json`,
the OAuth client as for email.
**sbk.config.json** nothing.
**Download**
```bash
uv run python tools/gsc/gs-l0-inventory.py --list-only     # list the properties only
uv run python tools/gsc/gs-l0-inventory.py                 # last 28 days (--days N to change)
uv run python tools/gsc/gs-l0-inventory.py --account main  # one signed-in account only
```
**Check** `<data root>/gsc/property.json` and `<data root>/gsc/performance/`.
**Limits** Search Console data lags by a few days. A property seen by two of your accounts is read
once. Without any login the script stops with a message and does nothing. The L1 is the shared kernel
`tools/cross-source/xs-l1-inventario.py`.

---

## Also connectable (no plugin folder yet)

A service without a folder under `tools/` has nothing to configure in SBK. An agent can still reach it
through the vendor's API, or through the vendor's own MCP server
([Using an MCP server](#using-an-mcp-server-instead-of-a-download)), with your OK for each call.

To make it a source of your own, follow [PLUGINS.md, "Adding a source of your own"](PLUGINS.md#adding-a-source-of-your-own).
The registry `tools/sorgenti.py` keeps an empty list, `_DA_COSTRUIRE`, where you can declare a source you
plan to build (an entry with the nature `da_costruire`): the pipeline dry run then lists it as declared
but never built.

---

## Checklist

Grouped by category, categories and plugins in alphabetical order. Env variables go in `.env` (the
scripts listed in [Before you start](#scripts-that-do-not-load-env-by-themselves) need them exported in
your shell), Keychain entries are written `<service>/<account>`. Plugins marked *partial* were tested
against mocked services only, or work in part: their section says which.

| Category | Plugin | Credential | Env vars · Keychain (`<service>/<account>`) | First command |
|---|---|---|---|---|
| AI history | ai-history | none to read (your local logs and exports); a model API key only for the last step, with `--yes` | `ANTHROPIC_API_KEY` (or the key of the `--provider` you choose), last step only | `uv run python tools/ai-history/ai-l0-claude-code.py --dry-run` |
| AI history | chatgpt | none, only if you used it: its export is read by ai-history | none | `uv run python tools/ai-history/ai-l0-import-export.py <export.zip> --dry-run` |
| Code | github (partial) | personal access token | `GITHUB_TOKEN` · `sbk-github/token` | `uv run python tools/github/gh-l0-download.py --dry-run` |
| Communication | calendar | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` · `sbk-gcal/<label>` | `uv run python tools/calendar/ca-l0-download.py --account <label> --list` |
| Communication | email | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` · `sbk-gmail/<label>` | `uv run python tools/email/em-l0-auth.py <label>` |
| Communication | imap-caldav (partial) | app password of your mailbox, or your own Microsoft app for Outlook.com | `SBK_MAILBOX_PASSWORD_<LABEL>`, `SBK_CALDAV_PASSWORD_<LABEL>`, `SBK_ICS_URL_<LABEL>`, `SBK_IMAP_OAUTH_REFRESH_<LABEL>` · `sbk-mailbox/<label>`, `sbk-caldav/<label>`, `sbk-ics/<label>`, `sbk-imap-oauth/<label>` | `uv run python tools/imap-caldav/ic-l0-auth.py --account <label> --imap` |
| Communication | microsoft365 (partial) | your own app registration (public client) + sign-in | `SBK_MS365_CLIENT_ID`, `SBK_MS365_TENANT` (exported, or `microsoft365.client_id` in `sbk.config.json`) · `sbk-microsoft365/<label>` | `uv run python tools/microsoft365/ms-l0-auth.py --account outlook` |
| Communication | slack | your own Slack app, user token (`xoxp-`) | `SLACK_USER_TOKEN` (optional `SLACK_BOT_TOKEN` for notifications) · `sbk-slack/user-token` | `uv run python tools/slack/sl-l0-channel-index.py --dry-run` |
| Communication | whatsapp | none: chats you export from the phone | none | `uv run python tools/whatsapp/wa-l0l3-full.py --list` |
| CRM | attio | API token of your workspace | `ATTIO_API_KEY` · `sbk-attio/<label>` for extra workspaces | `uv run python tools/attio/at-l0-download.py` |
| CRM | databases (partial) | connection string of your own database | `SBK_DB_URL_<NAME>` · `sbk-databases/<connection name>` | `uv run python tools/databases/db-l0-download.py --list` |
| Documents | gdrive | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` · `sbk-gdrive/<label>` | `uv run python tools/gdrive/gd-l0-auth.py --account <label>` |
| Documents | notion | your own internal integration token | `NOTION_TOKEN` (optional `SBK_NOTION_*`) | `uv run python tools/notion/no-l0-download.py` |
| Health | apple-health (partial) | none: Health export zip | none | `uv run python tools/apple-health/ah-l0-import.py` |
| Health | clinical (partial) | LLM API keys for parsing | `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY` | `uv run python tools/clinical/cl-l0-ingest.py --file <pdf> --type blood_test --subject <label>` |
| Health | whoop (partial) | your own WHOOP developer app (OAuth2) | `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET` · `sbk-whoop/client-id`, `sbk-whoop/client-secret` | `uv run python tools/whoop/wp-l0-auth.py` |
| HR tool | personio | organisation HR source: API client ID + secret, created with admin rights in Personio | `PERSONIO_CLIENT_ID`, `PERSONIO_CLIENT_SECRET` · `sbk-personio/client-id`, `sbk-personio/client-secret` | `uv run python tools/personio/pe-l0-download.py --dry-run` |
| Meetings & audio | plaud | your Plaud desktop app session | `SBK_PLAUD_API_BASE` optional · none to add | `uv run python tools/plaud/pl-l0-download.py --dry-transcriptions` |
| Meetings & audio | tactiq | your Chrome session + the public Firebase web key | `TACTIQ_FIREBASE_API_KEY` · `sbk-tactiq/refresh-token` (written by `--direct`) | `uv run python tools/tactiq/tq-l0-download.py` |
| Meetings & audio | voice-memos | none: local `.m4a` files | `SBK_VOICE_MEMOS_LANGUAGE` optional | `uv run python tools/voice-memos/vm-l0-transcribe.py` |
| Meetings & audio | zoom (partial) | your own user-managed Zoom app (public client) | `ZOOM_CLIENT_ID` (exported, or `zoom.client_id` in `sbk.config.json`) · `sbk-zoom/client-id`, `sbk-zoom/default` | `uv run python tools/zoom/zm-l0-auth.py` |
| Signing | docusign | your own DocuSign app (JWT: integration key + RSA key) | `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`, `DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_PRIVATE_KEY_PATH` · `sbk-docusign/integration-key`, `sbk-docusign/user-id`, `sbk-docusign/account-id` | `uv run python tools/docusign/ds-l0-api.py --consent-url` |
| Social | linkedin | none: data export | none | `uv run python tools/linkedin/li-l0-import-export.py --dry-run` |
| Tasks | clickup | personal API token | `CLICKUP_API_KEY`, `SBK_CLICKUP_TEAM` optional | `uv run python tools/clickup/cu-l0-backup.py --dry-run` |
| Web | analytics | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` · `sbk-ga/<label>` | `uv run python tools/analytics/ga-l0-inventory.py --login <label>` |
| Web | gsc | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` · `sbk-gsc/<label>` | `uv run python tools/gsc/gs-l0-inventory.py --login <label>` |
