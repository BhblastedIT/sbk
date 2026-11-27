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
`plaud` and `tactiq` reuse a login session that is already on your Mac (the Plaud desktop app, the
Tactiq web app in Chrome). The scheduled download runs them only when you list them in
`enabled_sources`, and their sections say exactly what they read.

Fifteen plugins are in the registry (`tools/sorgenti.py`) and in the pipeline but were tested only against
mocked services or hand-made files, never against a real account or a real export: `atlassian`,
`contacts`, `databases`, `fathom`, `fireflies`, `github`, `granola`, `hubspot`, `imap-caldav`, `linear`,
`microsoft365`, `pipedrive`, `teams`, `telegram` and `zoom`. Their **Status** line says *partial* and why.

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
  [microsoft365](#microsoft365) · [slack](#slack) · [teams](#teams) · [telegram](#telegram) ·
  [whatsapp](#whatsapp)
- CRM [attio](#attio) · [contacts](#contacts) · [databases](#databases) · [hubspot](#hubspot) ·
  [pipedrive](#pipedrive)
- Documents [gdrive](#gdrive) · [notion](#notion)
- Health [apple-health](#apple-health) · [clinical](#clinical) · [whoop](#whoop)
- HR tool [personio](#personio)
- Meetings & audio [fathom](#fathom) · [fireflies](#fireflies) · [granola](#granola) · [plaud](#plaud) ·
  [tactiq](#tactiq) · [voice-memos](#voice-memos) · [zoom](#zoom)
- Signing [docusign](#docusign) · Social [linkedin](#linkedin)
- Tasks [atlassian](#atlassian) · [clickup](#clickup) · [linear](#linear)
- Web [analytics](#analytics) · [gsc](#gsc)
- [Also connectable (no plugin folder yet)](#also-connectable-no-plugin-folder-yet) · [Checklist](#checklist)

---

## Before you start

Every source below is connected with your own account: your export, your personal token, or your
own app, used only by you. Where a vendor asks for someone's approval or for admin rights in its
own product (Personio API credentials, a Slack workspace that approves apps, a work Microsoft
account, the HubSpot permissions to install your own app, a Pipedrive or Linear company that can turn
API keys off), the plugin's section says so.

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
| `tools/hubspot/hs-l0-auth.py`, `hs-l0-download.py` | `HUBSPOT_CLIENT_ID` (or `hubspot.client_id` in `sbk.config.json`), `HUBSPOT_CLIENT_SECRET`, and without a Keychain `HUBSPOT_TOKEN_FILE`, `HUBSPOT_REFRESH_TOKEN` |
| `tools/granola/gr-l0-download.py` | `GRANOLA_API_KEY` (or the Keychain entry `sbk-granola/api-key`) |
| `tools/teams/tm-l0-auth.py`, `tm-l0-download.py` | `SBK_MS365_CLIENT_ID`, `SBK_MS365_TENANT` (or `microsoft365.client_id`, `microsoft365.tenant` in `sbk.config.json`) |
| `tools/contacts/ct-l0-auth.py`, `ct-l0-download.py` | `GOOGLE_OAUTH_CLIENT_SECRET_PATH`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (only if you use them instead of the default JSON path), and without a Keychain `SBK_GCONTACTS_TOKEN_<LABEL>` |
| `tools/attio/at-l1-enrich.py` | `SBK_ATTIO_CONTACTS_WITHOUT_EMAIL` (optional) |

Exporting is always safe. Keep each value in one place: some scripts load `.env` over what your
shell already has (personio, whoop, clinical, apple-health), others keep the shell value (atlassian,
attio, clickup, fathom, fireflies, linear, notion, pipedrive).

### Where data lands

Everything goes under the **data root**, `~/.sbk-data/` by default; this guide writes it
`<data root>`. To move it, set `SBK_DATA_ROOT` (read by `DATA_ROOT` in `tools/sbk_config.py`) in your
shell profile, not only in `.env`: a script that does not load `.env` before importing `sbk_config`
would otherwise use the default. Every path follows it, the default of the DocuSign key and the copy
of the Plaud session included. Your data is never written inside the repo: the only files SBK writes
there are the identity files of [AI history](#ai-history) in `sbk/identity/`, which `.gitignore`
leaves out, and the folders earlier versions wrote there (`sbk/raw/`, `sbk/network/`,
`sbk/companies/`, `scratchpad/`) are git-ignored as a safety net. One exception to the data root: the
Plaud speaker-naming judgement (`tools/plaud/regole/giudizio.py`) reads `SBK_DATA`, else
`~/.sbk-data`; if you move the data root, set `SBK_DATA` to the same folder.

Besides the plugins' own folders you may meet `<data root>/calendars/raw/` (a JSON copy of the events
of a first or `--since` calendar download), `<data root>/network/` (the profiles of
`network_profiles.people`), `<data root>/notes/` (your own Markdown notes, which the search index
reads) and `<data root>/backups-knowledge/` (the brain copies, see [After a download](#after-a-download)).

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
| `phone_country_code` | optional: the country calling code of your own phone numbers, digits only (`"44"`, `"1"`). A number written without it (`202 555 0123` with `"1"`) gets it in every step that reads phones: the address book, WhatsApp, Telegram, databases and the other plugins, and the merge, all through one normaliser. A national leading 0 is dropped (`07700 900123` with `"44"` is `+44 7700 900123`), except for the countries that keep it after the code (Italy, San Marino, Vatican City, Ivory Coast), and `(0)` after a code is read the same way (`+44 (0)7700 900123`, `0044 (0)7700 900123`). A number written without `+` or `00` is read as national even when its first digits are your own code (a mobile number whose national prefix starts with the same digits as your code stays national), unless it is too long to be a national number of your country (`447700900123` with `"44"` is `+44 7700 900123`). The book and the knowledge base store every number in one form, `+` and digits (`+447700900123`). So a WhatsApp chat, a Telegram contact and an address-book card with the same number become one person. Empty = no country is assumed, and only numbers written in full (`+1 202 555 0123`) match across sources. The `SBK_PHONE_CC` environment variable wins over it ([A first run](#after-a-download)) |
| `email_accounts` | one label per mailbox; the same labels as the keys of `<data root>/emails/accounts.json` |
| `enabled_sources` | the plugins you connected, by folder name. When the list is not empty, the download (`xs-l0-refresh.py`, also with `--only`) plans only these sources and prints the others as `(not run) <source>  not in enabled_sources`; `xs-pipeline-run.py --ingest` runs the L1 step only for these, reports the download age only for these, and shows the L1 phases and the inventory that read none of them as `SKIPPED (not in enabled_sources)`, which does not count as a failed step. Listing `microsoft365` or `imap-caldav` also keeps the `email` and `calendar` steps that read their files. Empty = every source: the download plans every source with a download script, and one you have not connected fails in it, so list the sources you connected. Either way `--ingest` skips at once, with no retry and no failure, the L1 step of a source that has no folder under the data root yet (`not downloaded yet`). Four need to be written in the list even then: the downloads of `plaud` and `tactiq` (they read a login session on your Mac, see their sections; their L1 step runs like the others), `linkedin` (only the status rows of its browser-cookie scripts) and the L1 step of `chatgpt` (closed, for an old ChatGPT export) |
| `slack.exclude_channel_patterns`, `slack.exclude_channel_ids`, `slack.user_names`, `slack.own_user_id` | optional: channels never downloaded, names Slack no longer resolves, your own Slack user id ([slack](#slack)) |
| `attio.extra_workspaces` | Attio workspaces beyond the primary one |
| `clickup.teams` | ClickUp workspaces to back up (empty = all the token sees) |
| `clickup.tasks_list`, `clickup.user_id` | optional, for the macOS app: the ClickUp list its Tasks page imports your open tasks from, and your ClickUp user id, set as the assignee of the tasks it creates from Inspiration. Empty = no import, no assignee ([clickup](#clickup)) |
| `plaud.api_base` | API host of your Plaud region (env `SBK_PLAUD_API_BASE` wins) |
| `voice_memos.language` | transcription language, `auto` by default (env `SBK_VOICE_MEMOS_LANGUAGE` wins) |
| `voice_memos.people`, `voice_memos.companies` | optional: the people and companies to tag in your voice memos ([voice-memos](#voice-memos)) |
| `gdrive.large_shared_drives` | optional: exact names of your shared drives with heavier files ([gdrive](#gdrive)) |
| `organisations.names`, `organisations.domains`, `organisations.aliases`, `organisations.domain_aliases` | optional: your own companies and brands, the ones you run or work for. Their people count as your team, their mail domains as internal, and their names are never read as a person; `aliases` and `domain_aliases` merge other spellings and second domains. Empty = nothing is treated as internal |
| `calendar.account`, `calendar.exclude_addresses` | optional: the label of the Google account whose calendars the monitor watches for pre-meeting briefs (empty = the first mailbox), and shared team or list addresses that are never a contact ([calendar](#calendar)) |
| `network_profiles.people` | optional: the people `tools/cross-source/xs-l2-network-profiles.py` writes a profile for, in `<data root>/network/<tier>/<id>.md`; copy the entry of `_example_people`. Empty = nobody is profiled |
| `chatgpt.people`, `chatgpt.companies` | optional, only with a ChatGPT export: names `cg-l1-enrich.py` tags in your conversations, besides your organisations ([chatgpt](#chatgpt)) |
| `notion.exclude_context_terms` | optional: text that marks your Notion template pages; people and companies found only next to it are dropped ([notion](#notion)) |
| `inspiration.archive_dir` | optional, for the macOS app: the folder of your own Inspiration archive of saved ideas (it holds `archivio/` and `scomponi/` with their own scripts, such as `archivio.py`, `leggi-dm.py` and `giro.py`). SBK does not ship that archive or its scripts. A relative path is read under your data root. Empty = Inspiration is off and the app says so ([Inspiration](#the-macos-apps-claude-code-sessions-optional)) |
| `inspiration.projects` | optional: the projects the app's Inspiration triage can tag a saved idea with. Empty = your organisations' names |
| `inspiration.clickup_lists` | optional: the ClickUp lists where the app's Inspiration puts a task (`main` is also where *Start* puts an idea's task). Empty = no task, and the app says the list is missing |
| `app.claude_sessions`, `app.claude_model` | the macOS app's background Claude Code sessions: `true` is your consent, off by default; one model alias for every session when your plan lacks the default ones ([The macOS app's Claude Code sessions](#the-macos-apps-claude-code-sessions-optional)) |
| `pipeline_status.spreadsheet_id` | optional: a Google Sheet of yours that `tools/cross-source/xs-util-pipeline-status.py --push` writes the status table to. Empty = the table stays in `<data root>/pipeline-status.json` |
| `search.synthesis` | `true` gives every `sbk search` a written answer from Claude, with your own `claude` login (the question and the results it found are sent). Off by default: search prints raw results ([Search answer](#search-answer-optional)) |
| `brief.synthesis` | `true` gives every `sbk brief` (and the dashboard's digest refresh) a written digest from Claude through the Anthropic API with your `ANTHROPIC_API_KEY` (today's stories with the text of the messages they come from are sent). Off by default: brief prints the stories ([Brief digest](#brief-digest-optional)) |
| `insights.synthesis` | `true` gives every run of `tools/cross-source/xs-temporal-analysis.py` (the weekly insights the dashboard home shows) insights written by Claude through the Anthropic API with your `ANTHROPIC_API_KEY` (a summary of your week with contact e-mail addresses and deal names is sent). Off by default: the analysis is local ([Weekly insights and signal summaries](#weekly-insights-and-signal-summaries-optional)) |
| `signals.synthesis` | `true` gives every `tools/monitoring/signal-detector.py --scan` a summary written by Claude for each new signal, through the Anthropic API with your `ANTHROPIC_API_KEY` (up to 8 facts per signal about the people involved are sent). Off by default: a one-line local summary ([Weekly insights and signal summaries](#weekly-insights-and-signal-summaries-optional)) |
| `contacts.google_accounts`, `teams.accounts` | the labels the scheduled download reads with `--all` for Google Contacts and for Microsoft Teams. Empty = nothing to download for that plugin ([contacts](#contacts), [teams](#teams)) |
| `drafts.family_names`, `drafts.client_domains` | optional: who counts as family or friends, and which mail domains are clients, for the drafts ([AI history](#ai-history)) |
| `whatsapp`, `databases`, `github`, `imap_caldav`, `microsoft365`, `zoom`, `atlassian`, `contacts`, `fathom`, `fireflies`, `granola`, `hubspot`, `linear`, `linkedin`, `pipedrive`, `teams`, `telegram` | options of those plugins, described in their sections. `teams` has no app of its own: it uses `microsoft365.client_id` and `microsoft365.tenant` |

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
`enabled_sources` when that list is not empty (the log names the sources it skipped, and an L1 phase that reads
none of the listed sources shows as `SKIPPED (not in enabled_sources)`, which is not a failed step).
The L1 step of a source you never downloaded or imported (no folder under the data root) is skipped at
once, with no retry: the log says `not downloaded yet, skipped (no folder under the data root): <sources>`.
`apple-health` and `clinical` are not in it: run their L1 by hand (commands in their sections).
`chatgpt` runs only when `enabled_sources` lists it (an empty list does not).
`imap-caldav` and `microsoft365` write into the mail and calendar folders that the `email` and
`calendar` steps already read; the contacts that `microsoft365` writes are read by
`tools/cross-source/xs-l1-contacts-enrich.py`. The `contacts` step (`ct-l1-enrich.py`) runs that kernel step
after its own import; with Outlook contacts alone, run it yourself ([microsoft365](#microsoft365)). A new
`contacts-iphone.parquet` makes `--propagate` run the merge again. The WhatsApp extras
(documents and photos pulled out of exported chats) run only when you add `--whatsapp-extras`
([whatsapp](#whatsapp)).

`xs-pipeline-run.py` has four commands, and none of them downloads (L0):

| Command | What it runs |
|---|---|
| `--ingest` | L1, L2 and L3, free stages only: rereads what is on disk. The plan names the paid stages it leaves out |
| `--all` | the whole chain, the paid stages included (your `ANTHROPIC_API_KEY`). Asks for your consent to spend; without a terminal it needs `--allow-spend` |
| `--propagate` | L2 and L3, incremental, from the snapshot already on disk (no L1) |
| `--rebuild` | L2 and L3 with every stage forced (no L1, no paid stages) |

`--dry-run` shows the plan of any of them without running it.

**The brain copy.** Before a run changes the knowledge store, the pipeline needs a recent copy of it: a tar
of `<data root>/knowledge` in `<data root>/backups-knowledge/` (`xs-l0-refresh.py --brain-copy` makes one;
the real run makes it by itself when it is missing or older than 7 days). On a new install there is no store
yet, so there is nothing to copy: the run says `brain copy not needed` and Knowledge Extract builds the
store. A copy that fails or is interrupted leaves no half file behind.

**The outcome line.** Every run ends with one line: `Pipeline Complete` (exit 0), `Pipeline INCOMPLETE`
(exit 2) or `Pipeline FAILED` (exit 1). `Complete` allows only the skips that do not count against a
run, and counts them in brackets: unchanged, resumed, `not in enabled_sources`, `nothing to read yet`.
Any other skip, a stage that did not close or a quality warning makes the run INCOMPLETE, with the
reason named.

**A first run.** On a new install most stages have nothing to read yet, and the run says so instead of
failing:

- With nothing downloaded or imported at all, every stage after L1 is skipped as `nothing to read yet`
  and the run ends `Pipeline Complete` at once.
- One source of any kind is enough to start. The merge starts a contact from mail, calendar,
  [WhatsApp](#whatsapp), [Telegram](#telegram), the address book ([contacts](#contacts)) or any plugin
  that brings people (`databases`, for example). A person who comes with a phone and no e-mail becomes
  a contact keyed by that phone; the same phone on someone who has an e-mail makes them one person. A
  WhatsApp chat partner you saved by name only becomes a contact keyed by that name. LinkedIn, Slack and
  the other sources only enrich the people found there: with only a LinkedIn export, the merge says
  `Nothing to merge yet`, every later stage is skipped as `nothing to read yet` and the knowledge stays
  empty. A merged book with 0 rows counts as no book.
- Phones are compared and stored after normalising them, by the same rule in every step. A number
  written without its country code (`202 555 0123`) gets the code in `phone_country_code` of
  `sbk.config.json` (or the `SBK_PHONE_CC` environment variable), and a national leading 0 is dropped
  (Italy, San Marino, Vatican City and Ivory Coast keep it); with neither set, only numbers written in
  full (`+1 202 555 0123`) match across sources. The merged book (`phone_primary`) and the knowledge
  base (`contact.phone`) keep the normalised form (`+12025550123`), whatever source wrote the number
  first. An e-mail always wins over a phone: when the address book (or a database) has someone with
  an e-mail and the same phone as a WhatsApp number or a Telegram contact, they are one person keyed
  by that e-mail, with the card's name, the phone, the organisation and every source. An unsaved
  WhatsApp number takes the name your address book (or Telegram) gives that number. In
  `<data root>/enriched/contacts-merged.parquet` the column `contact_key` is `tel:<phone>` for a
  phone-keyed contact, `name:<name>` for a name-keyed one and empty for an e-mail one, `started_by`
  names the source that started a row, and every row has a `person_id` (`p_…`), also on an install
  with no e-mail at all.
- The order the sources arrive in does not change the result, in the book or in the knowledge base:
  adding the address book after WhatsApp, a database after Telegram, or everything in one run gives
  the same people with the same facts. A person the knowledge base met first as an unsaved WhatsApp
  number (named by the number) joins the person the book names for that number once a card, a
  database or Telegram names it: the facts move to that person (the WhatsApp counts and dates follow
  them), and the number-only entity goes to `<data root>/knowledge/archive/merged/` with
  `merged_into`. A number the address book knows as a company card (`KIND:org`,
  `X-ABShowAs:COMPANY`) stops being a person and goes to `<data root>/knowledge/archive/retired/`.
  Nothing is deleted: each run that does this writes a journal
  `<data root>/knowledge/meta/fusioni-l2-knowledge-extract-book-<time>.jsonl`, and
  `uv run python tools/cross-source/xs-l4-disfa-fusione.py --journal <that file name>` shows what
  undoing it would bring back (`--apply` does it), as for any other merge. The log of the knowledge
  stage counts them (`book: N number-only persons merged into the named person, N retired as company
  numbers`). A number still known only by itself, or shared by two named people, stays as it is.
- The entity map (`<data root>/enriched/entity-map.json`, which joins the e-mails and names of one
  person) is rebuilt from the merged book on every `--ingest`, `--propagate` and `--rebuild` that
  runs the merge (stage `L2 Entity Map Cleanup`, through `tools/cross-source/xs-l2-entity-resolve.py`;
  it skips the work when the book did not change). When the map changed, the same stage merges the
  book once more, so a card with a second e-mail that arrives after a database joins that person
  with both e-mails, and the `person_id` is the one a single run gives. A `person_id` depends on the
  person's e-mails (or, with none, on the phone or name key), so it stays the same from run to run
  while those do not change. The later stages, the graph among them, read the map.
- The relationship scores (RQ-01, RQ-02b, RQ-02) read the interactions of mail, calendar, Slack,
  Plaud and Tactiq, Attio, WhatsApp and voice memos. With none of them yet (for example only
  `databases` or `telegram`), they are skipped as `nothing to read yet`.
- The search index (`L3 Index`, `tools/cross-source/xs-l3-index.py`) needs a local embedding model.
  The first run downloads it once from Hugging Face (`mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`,
  else `BAAI/bge-m3`, else `paraphrase-multilingual-MiniLM-L12-v2`), so it needs the network once; a
  model already in your Hugging Face cache works offline. Without either, that stage stops at once with
  one line saying so and is not retried (`class: setup missing, not retried`), every other stage runs,
  and the run ends `Pipeline INCOMPLETE` with `sources not closed: l3_index` (exit 2).
- The birthdays stage writes two calendars, Birthdays and Name days, into your Google account only after
  you sign in once with your own OAuth client (Keychain `sbk-gcal-write/<label>`, scope `calendar`):
  `uv run python tools/cross-source/xs-l3-birthday-calendar.py --login --account default`. Without that
  login the stage says so and writes nothing.

**The paid stages use one key, `ANTHROPIC_API_KEY`** (in `.env` or your environment). Without it `--all`
stops before them and says so. A key Anthropic refuses, or one out of credit, stops the stage with an
error that names `ANTHROPIC_API_KEY`; nothing switches to another key. The macOS app's "Spending and API
key" page shows only whether the key is set and where, never its value.

The download of every source in the
registry, one after the other, is `uv run python tools/cross-source/xs-l0-refresh.py` (`--then-ingest`
runs `--ingest` after it, `--dry-run` shows the plan, `--only <source>,<source>` limits it); the sources
you export or run by hand are listed as manual: `ai-history`, `databases`, `linkedin`, `telegram`,
`voicememos` and `whatsapp` (the registry ids; the plan, `xs-pipeline-run.py --help` and the `--all` plan
take the same list from `tools/sorgenti.py`). `plaud` and `tactiq` are planned only when `enabled_sources` lists
them, also with `--only`: otherwise the dry run prints `(not run) plaud` (or `tactiq`) with what it would
read. With `enabled_sources` set, only the sources it lists are in the plan (also with `--only`); the dry run
prints the others as `(not run) <source>  not in enabled_sources`. With an empty list every source with a
download script is in the plan: one you have not connected stops at once with one line saying what is
missing, the refresh tries it again and reports it as not finished, so either list your sources or use
`--only`. `contacts-google`
(Google Contacts) does nothing while `contacts.google_accounts` is empty, and `telegram` is listed as
manual.

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

**Automatic cascades.** Two things can start a step on their own: the event bus, which starts the next
step after a download, and the scheduler inside the dashboard, which runs the intervals you set on its
pipeline page while the dashboard is open (every interval is off until you set it, in
`<data root>/pipeline-schedule.json`). `uv run python tools/util/sb-pipeline-ctl.py off` switches automatic
cascades off: both then start nothing, and nothing queued is lost. `on` switches them back on, `status`
shows which it is. The switch is the file `<data root>/CASCADES_OFF`: cascades are on unless it exists.
The dashboard scheduler starts the `plaud` and `tactiq` downloads only when `enabled_sources` lists them.

### The macOS app's Claude Code sessions (optional)

Some features of the macOS app (`tools/secondbrain/`) hand work to a Claude Code session that runs in
the background on your Mac:

- a request you dictate or write on the Tasks page (`tools/secondbrain/sb_attivita_voce.py`), which
  sends the request and your task list;
- in Inspiration, understanding a saved idea, the re-read after your answer, the background sorting and
  the backlog re-read (`tools/secondbrain/sb_inspiration_azioni.py`), which send the idea, its files and
  your notes or answers.

Each session runs `claude -p` with **your own** Claude Code login, the one the `claude` command uses in
your terminal (your Claude plan, or your `ANTHROPIC_API_KEY`). There is no account switching. Claude
Code must be installed and signed in: `claude` in your PATH, or `SB_CLAUDE_CLI` set to its path.

**They are off until you allow them**, with this in `sbk.config.json`:

```json
"app": {"claude_sessions": true}
```

`SBK_APP_CLAUDE=1` (or `0`, which wins over the file) in the environment the app starts with does the
same; the app does not read `.env`, so the config key is the switch to use. Without your consent
nothing is sent: a Tasks request stops with a message that says how to turn the sessions on,
Inspiration says the same, and the automatic loops (understanding on its own, background sorting,
backlog re-read) start nothing. See the switch and which `claude` is used with:

```bash
uv run python tools/secondbrain/sb_own_claude.py status
```

Sessions run with `--permission-mode bypassPermissions`, only the tools each feature lists and no MCP
servers; the Tasks session also has a hook that checks every tool call
(`tools/secondbrain/attivita/guardia_voce.py`). The features ask for `opus`, the backlog re-read for
`haiku`. If your plan lacks one, set `"app": {"claude_model": "sonnet"}` (any alias or id that
`claude --model` accepts) and every session uses it.

**Inspiration (optional, off by default).** Inspiration works on an archive of saved ideas (reels,
posts, links, notes) that has its own scripts: `archivio.py` keeps the archive, `leggi-dm.py` reads
new ideas from your DMs, `trascrivi-audio.py` transcribes audio, and the tools under `scomponi/`
(`giro.py`, `scomponi.py` and the copy scripts) download and break down reels and pages. SBK does
not ship that archive or those scripts. Inspiration stays off until `inspiration.archive_dir` in
`sbk.config.json` names the folder that holds `archivio/` and `scomponi/`; a relative path is read
under your data root (`SBK_DATA_ROOT`). Off, the Inspiration page says so and nothing runs. On, any
feature whose script is missing from that folder says which script it needs instead of running.
Check with `uv run python tools/secondbrain/sb_inspiration_root.py`.

**ClickUp in the app.** The Tasks page imports your open tasks from the list in `clickup.tasks_list`,
the tasks created from Inspiration get `clickup.user_id` as assignee, and Inspiration's *Start* and
triage put tasks in `inspiration.clickup_lists.main` (and the other lists of that key). Nothing is
built in: an empty key turns that part off and the app says so.

**Pages view.** It lists the claude.ai pages your Claude Code sessions published, read locally from
`~/.claude/projects`; nothing is sent, and every page is shown as on your Claude account.

**Open in a terminal (optional).** "Open the agent" on an error and "open the idea's session in a
terminal" call a terminal-manager command named by `SB_AGENT_CLI` (default `agent-cli`). It is not part
of SBK. Without it, the error helper puts the text in your clipboard to paste into a Claude session,
and Inspiration says the terminal did not open. Both run your own `claude` in a visible terminal, only
when you click.

### Search answer (optional)

`uv run python tools/sbk_cli.py search "your question"` (the same engine is
`tools/cross-source/xs-l3-search.py`; `tools/util/sb-cerca.py` is a quieter wrapper) prints the matching
results from your local index, each with its source and date. Nothing is sent to a model.
The index is built by the pipeline's L3 Index stage with a local embedding model, downloaded once from
Hugging Face on the first run ([A first run](#after-a-download)); besides your sources it reads your own
Markdown notes in `<data root>/notes/` (files named `secrets-*` are skipped) and the profiles in
`<data root>/network/`. Before that stage has run once, `sbk search` says `No results: nothing is
indexed yet` and exits 0.
`sb-cerca.py` masks passwords, tokens and API keys in what it prints as `[MASKED]`: values written
after a label (`password:`, `token=`, `api key`) and the known key formats (Anthropic, OpenAI, Slack,
GitHub, GitLab, AWS, Google, Stripe, Hugging Face, Notion, JWTs, private key blocks, Bearer tokens);
`uv run python tools/util/sb-cerca.py --self-test` checks the masking.

A written answer is your choice: add `--synthesize` to one search, or turn it on for every search in
`sbk.config.json`:

```json
"search": {"synthesis": true}
```

Then your question and the results it found (the text of the matching pieces of your mail, chats,
transcripts and the other indexed sources, the top 10 by default, `--top N` to change) go to Claude
through `claude -p --model sonnet`, with **your own** `claude` login (your Claude plan, or your
`ANTHROPIC_API_KEY`). Each time the log says `Sending your question and N results (… characters) to
Claude with your own claude login (claude -p --model sonnet) for the answer`; `sb-cerca.py` prints the
same notice on its output. Claude Code must be installed and signed in. If the call fails, the raw
results are printed with the reason.

`--no-synthesis` forces raw results for one search even when `search.synthesis` is `true`;
`--synthesize` and `--no-synthesis` together are refused. The web dashboard's search page asks Claude
only when you click its *Summarise with Claude* button, which sends the same question and results with your own
`claude` login; the macOS app's search never asks for an answer.

### Brief digest (optional)

`uv run python tools/sbk_cli.py brief` (the engine is `tools/cross-source/xs-l3-digest-v2.py`) gathers the
last 24 hours of your calendar, mail, Slack and WhatsApp, the decay alerts, follow-ups, recent decisions and
knowledge changes, groups them into stories by person and topic, ranks them and prints them. Nothing is sent to
a model. It also writes the stories to `<data root>/briefs/digest-v2-<date>.json`, which the dashboard home
shows; `--dry-run` prints them and writes no stories file (only the run's log, in `<data root>/l3/logs/`).
The last line says how to turn the digest on and how many characters it would send.

A written digest is your choice: add `--synthesize` to one brief, or turn it on for every brief in
`sbk.config.json`:

```json
"brief": {"synthesis": true}
```

Then up to 15 stories go to Claude through the Anthropic API with your `ANTHROPIC_API_KEY`: each story's title,
the people in it with organisation, role and relationship score, up to 5 items with the first 300 characters of
the message, email or event text, the historical context the search index found, and up to 5 knowledge changes.
The log first says `Sending these N stories (… characters: titles, people, message text, knowledge changes) to
Claude through the Anthropic API with your ANTHROPIC_API_KEY for the digest`. The digest is written to
`<data root>/briefs/digest-v2-<date and time>.md`. Without the key, brief prints the stories, says the key is
missing and exits 0; if the call fails it prints the stories with the reason and exits 1. `--no-synthesis`
forces the stories only even when `brief.synthesis` is `true`; `--synthesize` and `--no-synthesis` together are
refused. The dashboard's digest refresh (`POST /api/pipeline/digest/refresh`) never adds `--synthesize`, so
it follows `brief.synthesis`. The monitor's 07:30 morning digest asks for the written digest only with your
monitor consent (`SBK_MONITOR_MODEL=1` or `--with-model`,
[The monitor and scheduled jobs](#the-monitor-and-scheduled-jobs-optional)). The older `xs-l3-digest.py`
follows the same rule.

A message from a number you never saved (a WhatsApp chat named after the number) shows, in the story's
title and its people, the name your address book gives that number, also when the number is on an
e-mail contact's card or database row; a number the book does not name stays a number.

### Weekly insights and signal summaries (optional)

Two manual tools add a written summary from Claude only when you ask. Neither runs in the pipeline.

`uv run python tools/cross-source/xs-temporal-analysis.py` reads the last four weeks (`--weeks N` to
change it) of your mail, Slack, calendar and CRM deals and works out your peak hours and days, your most
frequent contacts, the contacts who went quiet and the deals that have not moved, into
`<data root>/insights/weekly-<week>.json`, which the dashboard home shows. This is local and sends
nothing; the log says how much `--ai` would send. `--dry-run` shows the analysis and saves nothing.

Insights written by Claude are your choice: add `--ai` to one run, or turn them on in `sbk.config.json`:

```json
"insights": {"synthesis": true}
```

Then a summary of the week goes to Claude through the Anthropic API with your `ANTHROPIC_API_KEY`: your
name, the e-mail, Slack and meeting counts, your peak hours and day, the e-mail addresses of up to 5 top
and 5 dormant contacts, and up to 5 deal names with their stage and days in stage. The log first says
`Sending the week summary (… characters: …) to Claude through the Anthropic API with your
ANTHROPIC_API_KEY for the insights`. Without the key it says the key is missing and sends nothing.
`--no-ai` forces the local analysis even when `insights.synthesis` is `true`; `--ai` and `--no-ai`
together are refused.

`uv run python tools/monitoring/signal-detector.py --scan` looks for a topic or a person that shows up in
two or more sources within 48 hours (in the facts the extraction stages wrote), scores it and notifies
you of the new ones with a one-line local summary; `--stats` shows the history and `--dry-run` previews
without notifying or saving. A summary written by Claude is your choice: `--scan --synthesize` for one
scan, or:

```json
"signals": {"synthesis": true}
```

Then each new signal (at most 10 per scan) goes to Claude through the Anthropic API with your
`ANTHROPIC_API_KEY`: the topic, its sources and dates, up to 8 facts of up to 200 characters about the
people involved, and your name. The log first says `Sending signal '<topic>' (… characters: …)`.
`--no-synthesize` forces the local summary even when `signals.synthesis` is `true`; `--synthesize` and
`--no-synthesize` together are refused. The dashboard's *Scan* button and the monitor's signal check
never ask for it.

`tools/monitoring/commitment-tracker.py --verify` is the same kind of tool: only with that flag (never
with `--all` or the scheduled `--check --expire`) it sends each broken commitment (who, to whom, what,
deadline, its context) with up to 10 later facts to Claude through the Anthropic API with your
`ANTHROPIC_API_KEY`, and logs each one before sending; `--verify --dry-run` sends nothing.

---

## Google

Six plugins read Google data: `email`, `calendar`, `gdrive`, `gsc` (Search Console),
`analytics` (GA4) and, optionally, `contacts` (Google Contacts, next to the address-book exports it imports). They all sign in the same way, through **your own Google app**: a Google Cloud
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
   | contacts | People API |

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
| contacts | `contacts.readonly` | `uv run python tools/contacts/ct-l0-auth.py --account <label>` | `sbk-gcontacts/<label>` |

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
`--login`. Google Contacts uses the labels you give `ct-l0-auth.py --account`, listed in
`contacts.google_accounts` for the scheduled download. The data root is `~/.sbk-data` unless you set `SBK_DATA_ROOT`.

**Where the token lives.** Only in the macOS Keychain, under the entry of the table: nothing is
written to disk next to the data. To sign an account out of SBK, delete its entry and remove the app
from your Google account:
```bash
security delete-generic-password -s sbk-gmail -a work
```
and <https://myaccount.google.com/permissions> → your app → *Delete all connections*. In container
mode (no Keychain) the scripts read `SBK_GMAIL_TOKEN_<LABEL>`, `SBK_GCAL_TOKEN_<LABEL>`,
`SBK_GDRIVE_TOKEN_<LABEL>` from the environment (`tools/secrets_adapter.py`), and Google Contacts
`SBK_GCONTACTS_TOKEN_<LABEL>` ([contacts](#contacts)).

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
| HubSpot | HubSpot MCP server | `https://mcp.hubspot.com` | OAuth with PKCE, through an MCP connector you create in your HubSpot account; it sees what your user can see | https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server |
| Fireflies | Fireflies MCP server | `https://api.fireflies.ai/mcp` | OAuth with your Fireflies account, or your API key | https://docs.fireflies.ai/getting-started/mcp-configuration |
| Fathom | Fathom MCP server | `https://api.fathom.ai/mcp` | sign in with your Fathom account, as the vendor page describes | https://developers.fathom.ai/mcp-docs |
| Granola | Granola MCP server | `https://mcp.granola.ai/mcp` | OAuth in your browser, no API key; on the free plan the last 30 days, without transcripts | https://docs.granola.ai/help-center/sharing/integrations/mcp |
| Jira · Confluence | Atlassian remote MCP server | `https://mcp.atlassian.com/v2/mcp` | your Atlassian account, as the vendor page describes | https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/ |
| Linear | Linear MCP server | `https://mcp.linear.app/mcp` (read-only tools at `https://mcp.linear.app/mcp/readonly`) | OAuth, or your API key as a bearer token | https://linear.app/docs/mcp |

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
none of it goes into git. Like `messages.jsonl`, the files these steps write are readable by you only
(mode 600): `how-you-work-stats.json`, the text `--show-payload` saves, the `--stats-json` files of the
readers and the identity files.

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
`conversations.json` placed in `<data root>/chatgpt/`. The registry marks that source closed. The pipeline
runs it only when `enabled_sources` lists `chatgpt` (an empty list does not). The names it tags are
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
login made for a different account than the label's address is refused for that label. The first run,
and a run with `--since`, also keep a JSON copy of the events in
`<data root>/calendars/raw/cal-<label>.json`.
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
  Its commands are `status`, `list [--mailbox <label>]`, `move <mailbox> <sender> <category> --reason <text>`,
  `apply` (the filters) and `cleanup [--mailbox <label>]` (the mail already in the inbox); `apply`,
  `cleanup` and `undo <log>` (which reverts a cleanup from its log) only plan until you add `--execute`.
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
   stored. Signing a label in again asks for the same five permissions, plus `Chat.Read` if
   [teams](#teams) added it; any other scope recorded on that sign-in is not asked again, and the
   script names it.

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
- the sign-in: Keychain `sbk-microsoft365/<label>` (`ms_graph.py:237`), written by `ms-l0-auth.py`
  and replaced by every download, because Microsoft returns a new refresh token at each use
  (`ms_graph.py:273`). Without a Keychain: `SBK_MS365_TOKEN_FILE` (a JSON file the plugin keeps up
  to date, mode 600), then `SBK_MS365_TOKEN_<LABEL>` as a read-only seed, both exported in your shell. The lines are in
  `.env.example`, section "Microsoft 365 / Outlook". In container mode (`SBK_CONTAINERIZED=1`) the seed is
  read first, because it stands in for the Keychain (`tools/secrets_adapter.py`): set it for the first run,
  then unset it so the newer token in `SBK_MS365_TOKEN_FILE` is used.
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
  other mailboxes, the Exchange online archive and Teams chats (those are the [teams](#teams) plugin's).
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
- The contacts step (`xs-l1-contacts-enrich.py`) runs inside `xs-pipeline-run.py` only through the
  [contacts](#contacts) plugin's step, after an export or a Google Contacts download: with Outlook
  contacts alone, run it yourself.
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
**Reads** the workspace your own Slack app is installed in: the channels and private channels you are a
member of, their threads, your DMs and group DMs, and the user directory. Public channels you never
joined are not read. Archived conversations are skipped unless you add `--include-archived` to
`sl-l0-download.py`.
**You need** a personal Slack app in your workspace and its User OAuth Token (`xoxp-…`). You create
the app yourself; it is visible only in your workspace and acts as you.

**Create the app**
1. Open <https://api.slack.com/apps>, click *Create New App* → *From scratch*, give it a name (for
   example `SBK`), pick your workspace and click *Create App*.
2. In the app, open *OAuth & Permissions*. Under *Scopes* → **User Token Scopes** (not *Bot Token
   Scopes*) add these, which are the ones the code calls:

   | Scope | Used by |
   |---|---|
   | `channels:read`, `groups:read`, `im:read`, `mpim:read` | the lists of your channels, private channels, DMs and group DMs (`users.conversations`; the channel index also uses `conversations.list` for names) |
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
  alerts. Leave it empty and SBK asks Slack for it (`auth.test` on your user token). The
  signal-quality stage (`tools/cross-source/xs-l2-signal-quality.py`) also reads it, to score your
  participation in channels; that stage never asks Slack, so there an empty value means your
  participation is not scored.

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
channels will be read: the ones you are a member of, not excluded and not
archived), then `<data root>/slack/conversations/`, `<data root>/slack/dm/` and
`<data root>/slack/slack-users.json`. The data root is `~/.sbk-data` unless you set `SBK_DATA_ROOT`.

**Limits**
- One token reads one workspace. If you are in several workspaces, the download reads only the one
  the app is installed in.
- It never reads other people's DMs or channels you cannot open in Slack.
- The channel index (`sl-l0-channel-index.py`) lists the names, topics and member counts of every public
  channel of the workspace, to mark which ones you are in; the download reads messages only from the
  conversations you are a member of.
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

### teams

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
   [microsoft365](#microsoft365): Microsoft Entra admin center → **Entra ID** → **App registrations**
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

### telegram

**Status** partial · registry `a_richiesta` (on request), a reminder every 30 days (`tools/sorgenti.py`,
entry `telegram`). The scheduled download lists it as manual: you export, then import.
`xs-pipeline-run.py --ingest` runs `tg-l1-enrich.py` (step `telegram`). Tested only with exports made by
hand following Telegram's published schema, never with a real Telegram export. It writes the generic
intake contract (`tools/cross-source/plugin_intake.py`): the people you chat with reach the contact
merge (`xs-l2-merge.py`) and the person facts (`xs-l2-knowledge-extract.py`), and the promises found in
your messages can become commitments.

**How it works** You export your data yourself from Telegram Desktop and SBK imports the files, as
with WhatsApp. There is no Telegram login: no API id, no bot, no session, nothing goes to the network.

**Reads** from the export's `result.json`:
- your personal chats and your groups (private groups and private supergroups by default), both
  sides of the conversation in personal chats, and in groups only if you untick **Only my
  messages** (step 2 below); groups you have left come with your own messages only, because
  Telegram Desktop always exports them that way;
- the contacts list, used only to add a phone number to the people you chat with;
- your Telegram user id, so SBK knows which messages are yours.

It writes one interaction per chat and day (`kind=message`, the day's messages as text) and one
interaction per promise found in a message ("I'll send you the deck tomorrow", "ti mando il file
domani"). Bots, saved messages, channels and public groups are left out unless you list them.
Media files are never copied, only the kind of media a message had (`[photo]`, `[voice_message]`).

**You need** Telegram Desktop on a computer, signed in to your account
([desktop.telegram.org](https://desktop.telegram.org/)), and enough free disk for the export.

**Create it**
1. Open Telegram Desktop and go to **Settings → Advanced → Export Telegram data**.
2. Tick **Personal chats** and **Private groups**, and under Private groups **untick Only my
   messages**: it is ticked by default, and then your groups hold only what you wrote. Keep
   **Contacts list** ticked if you want phone numbers. Leave **Account information** ticked: it
   carries your user id, which tells SBK which messages are yours. Untick **Photos** (the only media
   type ticked by default) and leave the other media unticked: SBK reads only the text.
3. Under **Location and format**, choose **Machine-readable JSON** (or **Both**), pick a folder, and
   click **Export**.
4. If you signed in to Telegram Desktop only recently, Telegram makes you wait 24 hours, or confirm the
   request from another device you are signed in on, before the export starts.

Telegram writes a folder with a `result.json` in it. To export one chat only, open the chat's **⋮**
menu → **Export chat history**, also as JSON.

Official guides: [Telegram data export schema](https://core.telegram.org/import-export) ·
[Exporting Telegram data](https://bugs.telegram.org/c/60).

**Where the code looks** For the export folder you pass on the command line, or, when you pass none,
`<data root>/telegram/exports/` and its sub-folders. There is no credential, so nothing goes in `.env`
or the Keychain.

**sbk.config.json** set `owner`, and `own_names` if your Telegram name is written differently. The
export's user id identifies you whenever the export has **Account information**; your names are used
only when it does not. Optional section `telegram` (with its `_help` lines in `sbk.config.example.json`):
`chat_types` (default personal chats, private groups, private supergroups), `exclude_chats` (chat names
or ids to leave out), `group_contacts_max_senders` (default 30), `detect_promises` (default true),
`promise_patterns` (your own regular expressions, replacing the built-in English and Italian ones),
`promise_open_days` (default 30), `max_text_chars` (default 20000), `timezone` (only for exports made
before Telegram wrote `date_unixtime`), `own_user_id`. If `enabled_sources` is not empty, list `telegram`
there.

**Import**
```bash
uv run python tools/telegram/tg-l0-import.py ~/Downloads/Telegram\ Desktop/DataExport_2026-11-25 --dry-run   # counts, writes nothing
uv run python tools/telegram/tg-l0-import.py ~/Downloads/Telegram\ Desktop/DataExport_2026-11-25
uv run python tools/telegram/tg-l0-import.py                 # searches <data root>/telegram/exports/
uv run python tools/telegram/tg-l1-enrich.py                 # raw -> intake parquet
```
Import a newer export the same way: only new or edited messages are added. An export already imported
is skipped (`--force` reads it again).

**Check** `<data root>/telegram/download-summary.json` (export files read, chats, new messages, how you
were identified), the chats in `<data root>/telegram/raw/chats/`, then
`<data root>/telegram/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
`tg-l1-enrich.py` prints who it took to be "you" (`you = user id from the personal_information of the
export`). If it says `unknown`, set `owner` and `own_names`, or `telegram.own_user_id`. If the import
says `group(s) hold only your own messages`, the export was made with **Only my messages** ticked:
export again with it unticked.

**Limits**
- Import only: nothing arrives on its own. The 30 days are only a reminder to export again.
- Telegram writes no email addresses. People are matched in SBK by phone (when they are in your
  contacts list) or by name. A person who is not in your contacts list, or whose name differs from the
  name in your other sources, may stay a separate person. In the contact merge
  (`contacts-merged.parquet`) a Telegram person is matched to a contact you already have by phone or
  by name; otherwise one with a phone (everyone in your contacts list) becomes a contact keyed by that
  phone ([A first run](#after-a-download)). They also become a person in the knowledge base
  (`xs-l2-knowledge-extract.py`), so Telegram alone gives you people.
- Phone numbers come only from your contacts list: by user id, otherwise by a full name that appears
  only once in the list. Members of groups who are not in your contacts list have no phone.
- In groups where more than `group_contacts_max_senders` people wrote, the members are named in that
  day's interactions but get no contact row of their own, unless you also chat with them elsewhere.
  Large community groups would otherwise fill your contacts with strangers.
- Promise detection is a list of patterns, not a language model. It catches common first-person
  phrasings in English and Italian and misses everything else. It can also flag a sentence that is not
  a promise. A due date is found only for today, tomorrow, the day after, a weekday name, next week, or
  an ISO date written in the same sentence. Promises older than `promise_open_days` are written as
  `closed`, which means "no longer tracked", not "kept". A promise from someone else becomes a
  commitment only when it has a due date.
- Days follow the clock of the computer that made the export, as Telegram writes it.
- A message you deleted in Telegram stays in your data folder after a newer import. Delete the chat's
  file in `raw/chats/` if you want it gone.
- `result.json` is read in one piece. A very large export (years of big groups) needs several times its
  size in memory: export fewer chat types, or export the big chats one by one (only a single-chat
  export offers a date range), if the import runs out of memory.
- No kernel stage reads the message text yet (`text` column).
- Not covered: secret chats (Telegram's export documentation does not list them), channels and public
  groups (off by default), media files, live reading.

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

**What you get** With WhatsApp alone, `--ingest` gives you people: each one-to-one chat partner, and
everyone who wrote from a number you have not saved, becomes a contact and a person in the knowledge
base. A chat partner you saved by name is keyed by that name (the phone's export writes the saved name,
not the number); a number you have not saved is keyed by the number, and is also its name until another
source names it. Group members you saved by name only, who never chat with you one to one, stay out.
When another source knows the same phone, or the same full name that no one else has, the two become
one person ([A first run](#after-a-download)).

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
  with whisper.cpp, then written into the chats. The transcription needs `--attachments-dir <folder>`
  (your exported attachments, one sub-folder per chat; there is no default folder) and the relationship
  scores of a later pipeline stage, and stops without them.
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
(`{"<label>": "<name>"}`); their data lands in `<data root>/attio-<label>/`. The workspace of
`ATTIO_API_KEY` has the label `primary` (data in `<data root>/attio/`): `--workspace` takes `primary`, one
of your labels, or `all`.
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

### contacts

**Status** partial · registry `periodica`, every 30 days (`tools/sorgenti.py`, entry `contacts`).
Tested with synthetic vCard and CSV files and a mocked People API only, never with a real Google
account or a real export; the test runs the kernel's own contacts step (`xs-l1-contacts-enrich.py`) on
what the plugin writes. The scheduled download (`tools/cross-source/xs-l0-refresh.py`) runs
`ct-l0-download.py --all` (step `contacts-google`; nothing to do while `contacts.google_accounts` is
empty), and `xs-pipeline-run.py --ingest` runs `ct-l1-enrich.py` (step `contacts`). The plugin writes
into the kernel's existing address-book slot, `<data root>/contacts/contacts.parquet`, and then runs
that kernel step for you, so the contact merge (`xs-l2-merge.py`, iPhone lane) sees your address
book. A new `contacts-iphone.parquet` also makes `xs-pipeline-run.py --propagate` run the merge again.
**Reads** your own address book, in either of two ways, or both:
- an **export** you make: a vCard file (`.vcf`, versions 2.1, 3.0 and 4.0) from the macOS Contacts
  app, iCloud.com, the iPhone Contacts app, Google Contacts or Outlook desktop (one `.vcf` per
  contact), or a CSV file from Google Contacts, Outlook or Outlook.com (Outlook.com exports CSV
  only). A folder holding several of them works too;
- **Google Contacts** read live through the People API with your own Google app, read-only, only
  the contacts you saved (not your "Other contacts", not a company directory).

For each contact: name, every phone and e-mail (the preferred one first), organization, job title
and birthday.
**You need** for an export, nothing but the file. For Google Contacts, the Google app you already
made for the other Google plugins ([Google](#google)), with the **People API** enabled in the same
project.
**Create it**
- *An export.* On a Mac: Contacts → select the contacts → **File → Export → Export vCard**
  ([Apple guide](https://support.apple.com/guide/contacts/export-or-archive-contacts-adrbdcfd32e6/mac)).
  On iCloud.com: Contacts → select them → the Actions button → **Export vCard**
  ([Apple guide](https://support.apple.com/guide/icloud/import-export-and-print-contacts-mmfba748b2/icloud)).
  On an iPhone: Contacts → **Lists** → touch and hold a list → **Export**, then save the file
  ([Apple guide](https://support.apple.com/guide/iphone/export-contacts-iph075ddebf2/ios)). In Google
  Contacts: select the contacts → **More actions → Export**, as vCard or Google CSV
  ([Google guide](https://support.google.com/contacts/answer/7199294)). In Outlook.com or Outlook on
  the web: **People → Manage contacts → Export contacts**, which gives a `.csv`
  ([Microsoft guide](https://support.microsoft.com/en-us/outlook/export-contacts-from-outlook-com-or-outlook-on-the-web)).
  Then import it, giving it a label you choose:
  ```bash
  uv run python tools/contacts/ct-l0-import.py ~/Downloads/contacts.vcf --label phone
  ```
- *Google Contacts.* In your Google Cloud project, *APIs & Services* → *Library*, enable the
  **People API** ([Google guide](https://developers.google.com/people/v1/getting-started)). Then sign
  each Google account in once; the browser asks you to allow "See and download your contacts"
  (`https://www.googleapis.com/auth/contacts.readonly`, the only scope this plugin asks):
  ```bash
  uv run python tools/contacts/ct-l0-auth.py --account personal
  ```

Official references: [people.connections.list](https://developers.google.com/people/api/rest/v1/people.connections/list) ·
[Read and manage contacts](https://developers.google.com/people/v1/contacts) ·
[Person resource](https://developers.google.com/people/api/rest/v1/people) ·
[OAuth scopes](https://developers.google.com/identity/protocols/oauth2/scopes) ·
[Refresh token expiration](https://developers.google.com/identity/protocols/oauth2) ·
[vCard 4.0, RFC 6350](https://www.rfc-editor.org/rfc/rfc6350) ·
[vCard 3.0, RFC 2426](https://www.rfc-editor.org/rfc/rfc2426).
**Where the code looks**
- your Google app: `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`, else the Desktop-app JSON
  (`GOOGLE_OAUTH_CLIENT_SECRET_PATH`, else `~/.secrets/google-oauth/client_secret.json`), through
  `tools/google_oauth.py` (`tools/contacts/ct_google.py:125`). The first browser login
  (`ct-l0-auth.py`) reads only the JSON file (`google_oauth.browser_login`); the two variables are
  enough afterwards, to refresh the login.
- the Google login: Keychain `sbk-gcontacts/<label>` (`ct_google.py:114`), written by `ct-l0-auth.py`;
  without a Keychain, the env variable `SBK_GCONTACTS_TOKEN_<LABEL>` (`ct_google.py:117`), a refresh
  token or `{"refresh_token": …}`, exported in your shell. The lines are in `.env.example`, section
  "Contacts".
- exports: nothing secret; the copy lives in `<data root>/contacts/raw/imports/<label>/`.
**sbk.config.json** section `contacts` (with its `_help` lines in `sbk.config.example.json`):
`google_accounts`, the labels `ct-l0-download.py --all` reads (the scheduled download uses it; empty
= nothing to download). If `enabled_sources` is not empty, list `contacts` there.
**Download**
```bash
uv run python tools/contacts/ct-l0-import.py ~/Downloads/contacts.vcf --label phone   # an export, any time you make a new one
uv run python tools/contacts/ct-l0-download.py --account personal                     # Google Contacts, incremental after the first run
uv run python tools/contacts/ct-l0-download.py --all                                  # every label in contacts.google_accounts
uv run python tools/contacts/ct-l1-enrich.py                                          # writes the slot, then runs xs-l1-contacts-enrich.py
```
**Check** `uv run python tools/contacts/ct-l0-auth.py --account personal --check` (prints how many
contacts the login can read), then `<data root>/contacts/download-summary.json` (one entry per export
label and per Google label: contacts read, added, changed, removed, birthdays not understood), the rows
of `<data root>/contacts/contacts.parquet` whose `source` is `contacts:import:<label>` or
`contacts:google:<label>` (their `kind` column is `org`, `group` or `location` for a card that is not a
person, empty otherwise), and `<data root>/contacts/processed/contacts-iphone.parquet` (the kernel step's
output, read by the merge).
**Limits**
- The address book enriches people other sources know (phone, organization), matched by phone, e-mail
  or name. A card nobody else knows becomes a contact of its own: keyed by its e-mail when it has one,
  otherwise by its phone (`xs-l2-merge.py`, iPhone lane). Company cards (`KIND:org` in a vCard 4, or the
  `X-ABShowAs:COMPANY` flag of Apple Contacts) stay out: the slot writes `kind` `org` for them (`group`
  and `location` cards likewise), the kernel step marks them `is_business`, and the merge never turns
  them into people, nor a WhatsApp chat from a company card's number. With only the address book
  connected, `--ingest` builds a knowledge base of those people; they have no
  relationship score until a source with interactions (mail, calendar, WhatsApp...) arrives.
- Birthdays are written in the slot's `birthday` column (`YYYY-MM-DD`, or `--MM-DD` when the year is
  unknown), but the kernel step reads birthdays only from `iphone-contacts.json`, so today they do not
  reach the later stages.
- Job title is written in the slot; the kernel contacts step reads it but does not carry it into
  `contacts-iphone.parquet`, so it does not reach the merge.
- A contact without a name is left out by the kernel contacts step (its log counts them), so e-mail-only
  or phone-only entries do not reach `contacts-iphone.parquet`.
- A new export of a label replaces the previous one (kept once in `raw/imports/<label>/previous/`):
  import the whole address book, not a part of it, or use another label for the part.
- The same person in two exports, or in an export and Google, is written once only when name, first
  e-mail and first phone are all equal; otherwise there are two rows, which the merge matches to the
  same person.
- CSV: Google and Microsoft show their column names only as pictures, so the column map is built on the
  usual names (`First Name`, `Last Name`, `Company`/`Organization Name`, `Job Title`/`Organization
  Title`, `E-mail Address`/`E-mail 1 - Value`, `… Phone`/`Phone 1 - Value`, `Birthday`) and tested on
  synthetic files only. Outlook's `Title` column is the honorific and is not read as a job title. A
  birthday written like `4/15/1985` depends on your locale and is left out (counted in the summary).
- vCard 2.1 (Outlook desktop, older phones) is not an RFC: its quoted-printable form is read the
  common way. Photos, notes and addresses are not read. Fax numbers are left out. The copy of
  your export kept in `raw/imports/<label>/` is the whole file as you exported it (mode 600),
  photos, notes and addresses included. A file with a UTF-8 or UTF-16 byte-order mark is read too.
- Google Contacts: only the contacts you saved (`READ_SOURCE_TYPE_CONTACT`), not "Other contacts"
  (another scope) and not a Workspace directory. Google keeps a sync token for 7 days: after a longer
  pause the next run reads the whole list again (automatic), and so does a run that finds
  `people.json` missing or the requested fields changed (Google wants a sync request to repeat the
  first call's parameters). Google applies an extra fixed quota to the first page of a full read and
  answers 429 when it is exceeded; the plugin retries up to five times, waiting as long as a
  `Retry-After` header asks or, without one, a growing pause (Google does not document that header
  for this API), and sends one request at a time, at most two per second. The per-minute quota numbers
  are in your project's console (APIs & Services → People API → Quotas): no public Google page with
  them was found.
- With your Google app in *Testing*, the login lasts 7 days ([Google](#google), *Testing status and
  the 7-day login*): sign in again with `ct-l0-auth.py`.
- In container mode (`SBK_CONTAINERIZED=1`) there is no Keychain to store a login: run
  `ct-l0-auth.py` outside the container and give the container `SBK_GCONTACTS_TOKEN_<LABEL>`;
  inside it the login command stops with one line that says so.
- `contacts/contacts.parquet` is shared with `microsoft365`: run one of them at a time. While that file
  holds only plugin rows, `ct-l1-enrich.py` also copies your `iphone-contacts.json` into it (source
  `iphone-contacts-json`), the same rule `microsoft365` follows; a file with rows of any other origin is
  left as it is, apart from this plugin's own rows.

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
name with `"env"` on the connection), `tools/databases/db_reader.py:550` (names at `:106` and `:107`;
the lines are in `.env.example`, section "Databases"). For SQLite, a `"path"` in sbk.config.json comes
first. A connection string written in sbk.config.json (`url`, `dsn`, `password`, ...) is refused with an
error. Both scripts load `.env` by themselves.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-databases', 'shop', getpass.getpass('connection string: '))"
```

**sbk.config.json** section `databases` (`tools/databases/db_reader.py:420`). `sbk.config.example.json`
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

### hubspot

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `hubspot`). Tested
with a mocked HubSpot only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `hs-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`hs-l1-enrich.py` (step `hubspot`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own user-level app, read-only: the contacts, deals, notes and tasks you own (or,
with `only_mine` off, every one your HubSpot user can see), the contacts and companies linked to them,
and the stage names of your deal pipelines. For each contact: name, email, phone, company, job title.
For each deal: name, stage, pipeline, amount, close date, owner. For each note: its text and date. For
each task: subject, body, status, priority, due date. Nothing is written to HubSpot: the plugin only
reads (GET, plus the search and batch-read endpoints).
**You need**
- a HubSpot user in the account (any plan; the API limits differ by plan);
- the **Developer tools access** permission on your user, to upload the app to HubSpot
  ([HubSpot permissions guide](https://knowledge.hubspot.com/user-management/hubspot-user-permissions-guide));
- the **HubSpot Marketplace access** permission on your user, plus the permissions that match the
  app's scopes (view contacts, companies, deals), to install it
  ([who can install an app](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/manage-apps-in-hubspot)).
  HubSpot's user-level page says instead that each user whose permissions match the app's scopes can
  install a user-level app
  ([User-level access](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/user-level-apps));
  which of the two rules applies to a private user-level app was not verified. If your user is not
  allowed, HubSpot refuses the install and this plugin has no other route;
- Node.js 20 or newer and the HubSpot CLI 8.15.0 or newer (the version HubSpot names for user-level
  apps), on the machine where you upload the app;
- Python and a browser on the machine where you sign in.

The app is **user-level**: HubSpot ties its API access to your own user permissions, so the plugin
sees what you see in HubSpot and nothing more. If you can see only your own records in HubSpot, that is all
it reads.
**Create it** You build your own app from the project in this folder, used only by you:
1. Install the HubSpot CLI and connect it to your account
   ([Install the HubSpot CLI](https://developers.hubspot.com/docs/developer-tooling/local-development/hubspot-cli/install-the-cli)):
   ```bash
   npm install -g @hubspot/cli@latest
   hs account auth
   ```
   Follow the prompts: HubSpot asks you to make a personal access key for the CLI and paste it.
2. Upload the app. The project is `tools/hubspot/hubspot-project/` (read-only scopes, `"isUserLevel": true`,
   `"distribution": "private"`, redirect URL `http://localhost:8723/oauth-callback`):
   ```bash
   cd tools/hubspot/hubspot-project
   hs project upload
   ```
3. In HubSpot open **Development** → **Projects** → **sbk-hubspot-reader**, click the app
   (`sbk_hubspot_reader`), open the **Auth** tab and copy the **Client ID** and the **Client secret**
   ([Create a new app using the CLI](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/create-an-app)).
   If the **Distribution** tab asks for approved accounts, add the account you are in
   ([Install a privately distributed OAuth app](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/manage-apps-in-hubspot#install-a-privately-distributed-oauth-app)).
4. Put the client ID in `sbk.config.json` as `hubspot.client_id` (or export `HUBSPOT_CLIENT_ID` in
   your shell: the HubSpot scripts do not load `.env` by themselves) and the client secret in the
   Keychain, so it stays out of your shell history:
   ```bash
   uv run python -c "import keyring, getpass; keyring.set_password('sbk-hubspot', 'client-secret', getpass.getpass('value: '))"
   ```
5. Sign in once:
   ```bash
   uv run python tools/hubspot/hs-l0-auth.py
   ```
   The browser opens on HubSpot, you pick your account and click **Connect app**, and the login is
   stored. If HubSpot shows an error about the scopes, copy the install URL from the app's **Auth** tab
   and pass it: `uv run python tools/hubspot/hs-l0-auth.py --install-url "<that URL>"`.

Official guides: [User-level access](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/user-level-apps) ·
[Working with OAuth](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/oauth/working-with-oauth) ·
[OAuth v3 tokens](https://developers.hubspot.com/docs/api-reference/legacy/authentication/manage-oauth-tokens) ·
[Scopes](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes).
**Where the code looks**
- client ID: the env variable `HUBSPOT_CLIENT_ID`, else `hubspot.client_id` in `sbk.config.json`, else Keychain
  `sbk-hubspot/client-id` (`client_id` in `tools/hubspot/hs_api.py`).
- client secret: Keychain `sbk-hubspot/client-secret`, else `HUBSPOT_CLIENT_SECRET` (`client_secret` in
  `tools/hubspot/hs_api.py`). Never in `sbk.config.json`.
- the login: Keychain `sbk-hubspot/default` (another name with `--label`), written by `hs-l0-auth.py`
  and replaced whenever HubSpot hands out a new refresh token. Without a Keychain: `HUBSPOT_TOKEN_FILE`
  (a file the plugin keeps up to date, mode 600), then `HUBSPOT_REFRESH_TOKEN` as a one-time seed, both
  exported in your shell (`load_refresh_token` in `tools/hubspot/hs_api.py`). The lines are in
  `.env.example`, section "HubSpot".
**sbk.config.json** section `hubspot`: `client_id` (optional), `only_mine` (default true),
`redirect_port` (default 8723), `overlap_hours` (default 24), `history_days` (first run, default 0 =
everything), `max_details` (default 2000), `app_host` (default `app.hubspot.com`). If `enabled_sources` is not empty, list `hubspot` there.
**Download**
```bash
uv run python tools/hubspot/hs-l0-download.py                 # incremental after the first run
uv run python tools/hubspot/hs-l0-download.py --all-visible   # everything you can see, not only yours
uv run python tools/hubspot/hs-l0-download.py --full          # forget the saved state, read again
uv run python tools/hubspot/hs-l1-enrich.py                   # raw -> intake parquet (also run by --ingest)
```
**Check** `<data root>/hubspot/download-summary.json` (records found per type, `only_mine_applied`,
`user_level`, `warnings`, what is left for the next run), the files in `<data root>/hubspot/raw/`, then
`<data root>/hubspot/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`. After the
pipeline: `uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- A token that HubSpot reports as account-level is refused, because it would read every record the
  scopes allow, whoever you are in HubSpot. HubSpot cannot turn an existing app into a user-level one:
  build a new app from the project in this folder.
- "Only mine" needs your owner id, read from HubSpot's owners API, which is not in HubSpot's list of
  APIs for user-level apps. If HubSpot refuses it, the download reads everything you can see, says so in
  `download-summary.json`, and writes no due dates, so other people's deals and tasks never become your
  commitments.
- Due dates (deal close date, task due date) reach the intake only for items you own; for the others the
  date stays in the text. Likewise only items you own count as your interactions with a person
  (`interactions`, `first_seen`, `last_seen`); a contact with none of yours has those empty, and the
  CRM's own dates (when the record was created, when anyone last contacted it) are not used.
- Deals, notes and tasks are linked to contacts and companies with one read per record; with many
  records the links arrive over more runs (`max_details`).
- A record deleted in HubSpot stays in your files until a download with `--full`.
- One search returns at most 10,000 records; the plugin starts again from the last date it saw, so a
  bigger account is read in more queries.
- API limits of a privately distributed app: 100 requests every 10 seconds on Free and Starter, 190 on
  Professional and Enterprise, with a daily cap
  ([usage guidelines](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines);
  that page names platform versions 2025.2 and 2026.03, this app is 2026.09, so the same limits are
  assumed); search: 5 requests per second
  ([CRM search](https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm)).
  At the daily cap the run stops, keeps what it read and continues next time.
- The login listens on `localhost` (HubSpot accepts `http://localhost` and no IP address as a redirect).
  If port 8723 is busy, change `redirect_port` and the redirect URL in `app-hsmeta.json`, upload again.
**Alternative, an MCP server** HubSpot runs its own MCP server (`https://mcp.hubspot.com`, OAuth with PKCE
through an MCP connector you create in your HubSpot account, limited to what your user can see:
[HubSpot MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server)).
It lets an agent ask your CRM questions live during a session; it does not fill SBK's data folder, so
the knowledge layer and the drafts still need the download above.

### pipedrive

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `pipedrive`). Tested
with a mocked Pipedrive API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `pd-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`pd-l1-enrich.py` (step `pipedrive`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** what your Pipedrive user can see, GET calls only, nothing is written in Pipedrive:
organizations (name), persons (name, emails, phones, organization, job title when Pipedrive sends
it), deals (title, status, value, owner, person, organization, expected close date; archived deals
too), activities (subject, type, due date and time, done, linked persons, attendees, note) and notes
(text, author, what they are attached to). Left out on purpose: custom fields, birthdays, postal
addresses, contact-sync notes, conference links (they can carry passcodes). By default the L1 keeps
only what is yours: deals you own or created, activities you own, created or attend, notes you wrote,
and the persons you own or who appear in those (`pipedrive.scope`, see below).
**You need** a Pipedrive user of your own, with API access. Two ways in, pick one:
- your **personal API token** (the simple route). It is tied to you and to one company:
  if you belong to several Pipedrive companies, each has its own token, and the plugin reads one.
  You have one active token at a time, so regenerating it stops every other tool that uses it.
- an **OAuth app you register yourself** (optional, more steps): a private app in the Developer Hub
  of a free developer sandbox account, with read-only scopes, installed for yourself only.

An admin of your company can turn off API use for your permission set: then the API page is not in
your settings and you cannot get a token. That choice is the company's; ask your admin, the plugin
cannot work around it. Every call also spends your company's shared daily API budget (see Limits).
**Create it** (API token) In Pipedrive open your account name at the top right, **Company settings**
(or **Settings**), **Personal preferences**, **API**, or go straight to
https://app.pipedrive.com/settings/api while signed in. Copy the token. If there is no **API** entry,
your permission set does not allow API use.
Official steps: https://support.pipedrive.com/en/article/how-can-i-find-my-personal-api-key and
https://pipedrive.readme.io/docs/how-to-find-the-api-token; API access per permission set:
https://pipedrive.readme.io/docs/enabling-api-for-company-users
(OAuth, optional) Get a developer sandbox account (https://developers.pipedrive.com/, form on the page),
open **Developer Hub** from its settings menu, **Create an app**, **Create private app**. App name
of your choice; OAuth callback URL `http://127.0.0.1:8765/callback` (one URL per app; another port:
`pipedrive.oauth_redirect_port`). Under **OAuth & access scopes** tick only **Deals: Read only**,
**Contacts: Read only** and **Activities: Read only** (basic user information is always on), never
**Administer account** or a *Full access* scope. Copy the client ID and client secret. A draft app can
be installed only inside the sandbox company; to use it in your real company you make it live with
**Change to live** and install it from its installation link, for yourself (do not add it to other
users). Pipedrive checks the callback URL when you go live, and whether it accepts a loopback address
is not documented: if it refuses, use the API token. Then run `pd-l0-auth.py` once.
Official steps: https://pipedrive.readme.io/docs/developer-sandbox-account,
https://pipedrive.readme.io/docs/marketplace-registering-a-private-app,
https://pipedrive.readme.io/docs/marketplace-oauth-authorization, scopes:
https://pipedrive.readme.io/docs/marketplace-scopes-and-permissions-explanations
**Where the code looks** API token: Keychain `sbk-pipedrive/api-token` first, then the env
`PIPEDRIVE_API_TOKEN` (`tools/pipedrive/pd_api.py:171`, names at `:60-70`). OAuth: client ID from the
Keychain `sbk-pipedrive/client-id`, the env `PIPEDRIVE_CLIENT_ID` or `pipedrive.client_id`; client
secret from `sbk-pipedrive/client-secret` or `PIPEDRIVE_CLIENT_SECRET`; refresh token (written by
`pd-l0-auth.py`) in `sbk-pipedrive/refresh-token`, or the file named by `PIPEDRIVE_TOKEN_FILE`, or
`PIPEDRIVE_REFRESH_TOKEN`. With both set, the API token wins unless `pipedrive.auth` says `oauth`.
The lines are in `.env.example`, section "Pipedrive". The scripts load `.env` by themselves.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-pipedrive', 'api-token', getpass.getpass('value: '))"
```
**sbk.config.json** nothing is required. Optional section `pipedrive` (every field with its `_help`
in `sbk.config.example.json`): `auth` (`auto`, `api_token` or `oauth`), `scope` (`mine` by default,
`all` keeps every deal, activity, note and person the download saw), `since_days` (first run only:
how many days back by last update; empty = everything you can see), `include_archived_deals`
(default true), `max_requests_per_run` (default 2000; a run that reaches it stops and the next run
continues), `client_id` and `oauth_redirect_port` (OAuth only). If `enabled_sources` is not empty,
list `pipedrive` there: the generic intake reads the `pipedrive` folder only when it is listed.
**Download**
```bash
uv run python tools/pipedrive/pd-l0-download.py --dry-run   # checks the credential, prints your user and company, writes nothing
uv run python tools/pipedrive/pd-l0-download.py             # organizations, persons, deals, activities, notes
uv run python tools/pipedrive/pd-l1-enrich.py               # builds the two parquet files (also run by --ingest)
uv run python tools/pipedrive/pd-l0-auth.py                 # OAuth route only: sign in once in the browser
```
**Check** `<data root>/pipedrive/download-summary.json` (counts per entity, `complete`, `api_calls`,
`api_tokens_estimate`, `burst_limit_per_2s`); after the L1, `<data root>/pipedrive/processed/plugin-contacts.parquet`
and `plugin-interactions.parquet`, then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
In your Pipedrive company, admins see API usage in the **API Usage Dashboard** of Company settings.
**Limits**
- Daily API budget: one budget per company, shared by every user and every integration, 30,000
  tokens x plan multiplier (Lite 1, Growth 2, Premium 5, Ultimate 7) x seats, reset at midnight
  server time; admins get an email at 75% and 100%, and once it is used up every call gets HTTP 429
  for everyone in the company until the reset. One page of up to 500 records costs 10 tokens on the
  v2 lists, 20 for archived deals and for notes (v1), 2 for your user. The plugin caps each run at
  `max_requests_per_run` and writes its estimate in `api_tokens_estimate`
  (https://pipedrive.readme.io/docs/core-api-concepts-rate-limiting; costs from the `x-token-cost`
  of each endpoint in the API reference, https://developers.pipedrive.com/docs/api/v1).
- Burst limit: per token, rolling 2-second window (API token 20 to 120 requests per plan, OAuth 80 to
  480). The plugin sends at most one request every 0.2 seconds, waits on 429 as the headers say and
  gives up after five tries (exit 1, what was read is kept). Pipedrive blocks with a Cloudflare 403
  the token integrations that keep calling after a 429.
- Incremental by `update_time`: each entity is asked for what changed since its last complete pass
  minus one hour, on Pipedrive's clock. A run stopped by the cap or by a 429 resumes from the newest
  record it read. Notes come from the v1 endpoint with offset pages; each page starts ten records
  early, so a note edited or deleted while the run pages through them does not make it skip
  another one (more than ten such changes inside one page still could; `--full` brings it back).
- Deletions: deals deleted in the last 30 days are removed from the local copy on each run (Pipedrive
  keeps them that long). Deleted persons, organizations, activities and notes are not seen by an
  incremental run and stay in the local copy until `--full`, which re-reads every list and drops
  what Pipedrive no longer lists (a `--full` run cut short by the cap prunes only the lists it read
  to the end).
- Persons: job title arrives only when contact sync is on for the company (Pipedrive's rule). Only
  the primary (else the first) email and phone go into the contact row.
- Commitments: every open activity you own becomes a commitment (due = its due date), and so does
  every open deal you own (due = its expected close date, when set): many open deals mean many
  commitments. A colleague's deal or activity never carries a due date
  in your files, so it does not become your commitment even with `scope: all`. Won deals are written
  as `done`, lost deals as `closed`, the outcome stays in the title. Activity types meeting, lunch and
  call become `meeting`, email becomes `message`, task, deadline and custom types become `record`.
- A person's first and last contact dates come from past events only: a planned call does not
  count until its date has passed.
- Links: Pipedrive's API docs do not describe the web app URLs. The plugin writes
  `https://<company>.pipedrive.com/person/<id>`, `/deal/<id>`, `/organization/<id>`, and for
  activities and notes the page they are attached to plus `#activity-<id>` / `#note-<id>`: the pattern
  has not been checked against a real account.
- Leads, products, projects, files, email sync, custom fields and user lists are not read. People who
  are only colleagues in Pipedrive (users) appear only as activity attendees.
- OAuth: the access token lasts 60 minutes and is refreshed by the plugin; the refresh token expires
  if unused for 60 days, then `pd-l0-auth.py` again. A sandbox account with no app created within 45
  days, or no private app made live within six months, is deleted by Pipedrive.

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
**Values by hand** `cl-build-values.py` adds lab values you type yourself, without the parsing step:

```bash
uv run python tools/clinical/cl-build-values.py --file my-values.csv --subject <label>
```

The CSV has the columns `date` (YYYY-MM-DD), `marker`, `value`, `unit`, `ref_min`, `ref_max` and,
optionally, `subject`. The rows are merged into `values.parquet`: a row with the same date, marker and
subject replaces the old one, and the values the parsing step wrote stay. Nothing leaves your machine.
`--demo` adds five synthetic rows instead, only while the table is empty, to try `cl-alerts.py`.

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

### fathom

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

### fireflies

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

### granola

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

### plaud

**Status** mature · registry `continua`, every 7 days.
**Reads** recordings, transcripts and summaries of your Plaud recorder account.
**You need** macOS with the Plaud desktop app installed and logged in to your account at least once.
Node.js (`npm`) only for the fallback path below.
**Create it** Nothing to create: SBK reuses the session of your Plaud desktop app.
**Where the code looks** The session token of the Plaud desktop app, read locally
(`tools/plaud/pl_auth_refresh.py`); SBK keeps a copy in `<data root>/secrets/plaud-wt.json`.
If that fails, it decrypts the app's storage
(`~/Library/Application Support/Plaud/encryption.json`) with an Electron helper in
`tools/plaud/electron-decrypt/` (installs Electron with `npm` on first use), using the Keychain entry
the Plaud app creates for itself (`Plaud Safe Storage` / `Plaud Key`). You do not add any key.
**When it runs** The scheduled download (`tools/cross-source/xs-l0-refresh.py`, also with `--only`, and the
dashboard scheduler) runs Plaud only when `plaud` is in `enabled_sources`: it then runs
`pl-l0-download.py --direct`, which reads the session token of your Plaud desktop app as described
above. A `pl-l0-download.py` you run yourself is not gated.
**sbk.config.json** `"plaud"` in `enabled_sources` for the scheduled download; `plaud.api_base`: the API
host of your account's region, default
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
you from `owner`, `own_names` and `own_emails` in `sbk.config.json`. The Plaud
speaker-naming helpers (`pl_lotto.py`, `pl_quadro.py`, `pl_lunghe.py`, `pl_dettagli.py`,
`pl_quadro_pagina.py`, `regole/*.py`) follow `SBK_DATA_ROOT`, and `SBK_DATA` wins when you set it;
`regole/giudizio.py` reads only `SBK_DATA` (default `~/.sbk-data`), so set it too if you moved the data
root. Their options:
`tools/plaud/pl_lotto.py --new` picks a batch of voices for you to confirm (`--count N`, default 50) and
`--answer N TEXT` records your answer to one of them; `tools/plaud/pl_lunghe.py list` (then `plan`, `upload`,
`check` with an id, or `all`) splits single-voice recordings over three hours at silences (`--minutes M` with
`all`, `--wait` with `check`); `tools/plaud/pl_quadro.py --print-only` and
`tools/plaud/regole/r3_incroci.py --print-only` compute without writing;
`tools/plaud/regole/r1_fonti.py --no-cache` and `tools/plaud/regole/r2_testo.py --from-scratch` rebuild their
caches.

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
**When it runs** The scheduled download (`tools/cross-source/xs-l0-refresh.py`, also with `--only`, and the
dashboard scheduler) runs Tactiq only when `tactiq` is in `enabled_sources`. It then runs
`tq-l0-download.py --direct`: it reads the refresh token from Chrome's storage for `app.tactiq.io`,
exchanges it with `TACTIQ_FIREBASE_API_KEY` and keeps a copy in the Keychain entry
`sbk-tactiq/refresh-token`. A `tq-l0-download.py` you run yourself is not gated.
**sbk.config.json** `"tactiq"` in `enabled_sources` for the scheduled download; nothing else.
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
  shell. The lines are in `.env.example`, section "Zoom". In container mode (`SBK_CONTAINERIZED=1`) the
  seed is read first, because it stands in for the Keychain (`tools/secrets_adapter.py`). Zoom replaces the
  refresh token at every refresh, so unset `ZOOM_REFRESH_TOKEN` after the first run, or the next run uses a
  token Zoom no longer accepts.
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
private key as `<data root>/secrets/docusign-private.key` with permissions 600 (another path goes in
`DOCUSIGN_PRIVATE_KEY_PATH`). Add the redirect URI
`http://localhost:8765/docusign/callback` (or your own, in `DOCUSIGN_REDIRECT_URI`). Copy the
integration key, your API user ID and the account ID into `.env`. Then give your consent once:
```bash
uv run python tools/docusign/ds-l0-api.py --consent-url    # open the printed URL and accept
```
**Where the code looks** env first, then the Keychain (`_cred` in `tools/docusign/ds-l0-api.py`):
`DOCUSIGN_INTEGRATION_KEY` or `sbk-docusign/integration-key`, `DOCUSIGN_USER_ID` or
`sbk-docusign/user-id`, `DOCUSIGN_ACCOUNT_ID` or `sbk-docusign/account-id` (optional: without it the
default account of your user is read). Key file at `DOCUSIGN_PRIVATE_KEY_PATH`, else
`<data root>/secrets/docusign-private.key`.
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
**sbk.config.json** none for the export. Optional `linkedin.own_urn`, only for the browser scripts
(see Limits).
**Download**
```bash
uv run python tools/linkedin/li-l0-import-export.py --dry-run   # counts only, writes nothing (no files, no last-runs.json, no metrics)
uv run python tools/linkedin/li-l0-import-export.py
```
**Check** `<data root>/linkedin/raw/export-connections.parquet`; after `--ingest`,
`<data root>/linkedin/processed/contacts-linkedin.parquet`.
**Limits** The export is the connection path. The folder also holds browser scripts
(`li-l0-scraper.js`, `scripts/`) with a safety module (`li_safety.py`): they are not part of this
path and this guide does not set them up; the registry asks to respect the provider's rate limits.
If you ever run them, they too write under `<data root>/linkedin/raw/` (their session file
`linkedin-session.json` included), never in the repo or the current folder. They tell your messages
apart by your own member id, read from LinkedIn for your own login; to fix it, set
`"linkedin": {"own_urn": "ACoA..."}` in `sbk.config.json` (the id at the end of your profile URN) or
`SBK_LINKEDIN_OWN_URN`. There is nothing to edit in the scripts.
The pipeline status table (`tools/cross-source/xs-util-pipeline-status.py`) shows the rows of those
cookie-based scripts only when `linkedin` is in `enabled_sources`. The dashboard's LinkedIn download
runs the export importer above.
In the knowledge layer LinkedIn enriches people SBK already knows and does not create new ones
(`LINKEDIN_CONIA_NUOVI = False` in `tools/cross-source/xs-l2-knowledge-extract.py`). With only LinkedIn
connected, `--ingest` says `Nothing to merge yet` and the knowledge stays empty
([A first run](#after-a-download)).

---

## Tasks

### atlassian

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `atlassian`). Tested
with a mocked Jira and Confluence only, never against a real site. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `as-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`as-l1-enrich.py` (step `atlassian`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own API token, GET calls only, on your Atlassian Cloud site: the Jira issues you
created or reported, are assigned to, or watch, with status, due date, project, type, description
(first 4,000 characters), reporter, creator, assignee and, when an issue has more than one watcher,
the watcher list; the Confluence pages you created or edited, with space, version, creator, last
editor and contributors. Nothing is written in Jira or Confluence.
**You need** your Atlassian Cloud site address (for example `https://your-site.atlassian.net`), the
email of your Atlassian account, and an API token you create yourself in your account. No admin
role and no app to install.
**Create it** You open https://id.atlassian.com/manage-profile/security/api-tokens (your Atlassian
account, **Security**, **Create and manage API tokens**). If you log in with a password or Google,
Atlassian first emails you a one-time code. Then either:
- **Create API token** (without scopes): give it a name and an expiry (1 to 365 days), **Create**,
  **Copy to clipboard**. One token covers Jira and Confluence. This is the simplest route.
- **Create API token with scopes** (Atlassian recommends it as more secure): name, expiry, then
  pick the **app** and the scopes. For Jira choose `read:jira-work` and `read:jira-user`; for
  Confluence `search:confluence` and `read:confluence-user`. If the list offers only granular
  scopes, the ones the endpoints name are, for Jira, `read:issue-details:jira`,
  `read:issue-meta:jira`, `read:field-configuration:jira`, `read:audit-log:jira`,
  `read:avatar:jira`, `read:issue.watcher:jira`, `read:user:jira`, `read:group:jira`,
  `read:application-role:jira`, and for Confluence `read:content-details:confluence`. The creation page asks for one app, so
  for both products you create two tokens and store them as the Jira and the Confluence token below.
  A scoped token cannot call your site address: the plugin then goes through
  `https://api.atlassian.com/ex/jira/<cloud id>` and `.../ex/confluence/<cloud id>`, and finds the
  cloud id of your site by itself.
You copy the token at once: Atlassian does not show it again.
Official steps: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/
Basic auth with email and token: https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/
Scopes: https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/ and
https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3LO-and-forge-apps/
**Where the code looks** (`tools/atlassian/as_api.py`, `resolve_token` and `load_settings`)
- token for Jira: Keychain `sbk-atlassian/jira-token`, env `ATLASSIAN_JIRA_API_TOKEN`, then the
  shared token Keychain `sbk-atlassian/api-token`, env `ATLASSIAN_API_TOKEN`;
- token for Confluence: Keychain `sbk-atlassian/confluence-token`, env
  `ATLASSIAN_CONFLUENCE_API_TOKEN`, then the same shared token;
- site: `atlassian.site` in `sbk.config.json`, else env `ATLASSIAN_SITE`; email: `atlassian.email`,
  else `ATLASSIAN_EMAIL`; cloud id (only for scoped tokens, optional): `atlassian.cloud_id`, else
  `ATLASSIAN_CLOUD_ID`.
The download script loads `.env` by itself.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-atlassian', 'api-token', getpass.getpass('value: '))"
```
**sbk.config.json** section `atlassian`: `site` and `email` (required unless set in `.env`);
optional `token_kind` (`auto` by default: tries your site, then the api.atlassian.com route for a
scoped token; `unscoped` or `scoped` to skip the try), `cloud_id`, `products` (default
`["jira", "confluence"]`), `jira_projects` and `confluence_spaces` (keys to restrict the reading,
empty = all you can see), `since_days` (first Jira download, 365), `confluence_since_days` (first
Confluence download, 180), `max_watcher_calls_per_run` (200). List `atlassian` in `enabled_sources`
if that list is not empty.
**Download**
```bash
uv run python tools/atlassian/as-l0-download.py --dry-run   # checks the token(s), prints who you are and the route, writes nothing
uv run python tools/atlassian/as-l0-download.py             # Jira issues and Confluence pages, incremental
uv run python tools/atlassian/as-l0-download.py --full      # re-reads everything, drops what no longer matches
uv run python tools/atlassian/as-l1-enrich.py               # builds the two parquet files (also run by --ingest)
```
**Check** `<data root>/atlassian/download-summary.json` (route per product, issues, pages,
watcher lists read, API calls, `products_skipped` if one product refused); after the L1,
`<data root>/atlassian/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- Atlassian Cloud only (`*.atlassian.net`); Jira and Confluence Data Center or Server are not read.
- People's email is the one their profile shows you: depending on each person's profile visibility
  it comes back empty, and the contact is then matched by name only. App accounts (automation, bots)
  are left out, and so are deleted accounts, which Atlassian shows as "Former user"
  (https://support.atlassian.com/confluence-cloud/docs/what-happens-when-an-account-is-deactivated-vs-deleted/):
  otherwise every deleted person would merge into one contact.
- A due date counts as your commitment only on issues you are assigned to or created or reported:
  on an issue you only watch the due date is not written, because the kernel would count every open
  issue with a due date as yours. Jira can make you watch every issue you create or comment on
  (the autowatch setting of your profile or of the site), so "issues you watch" can be many.
- An issue is `done` when its status category is done or it has a resolution date; any other
  status is `open`. The status name, project and type go in the `text` column. The Jira status
  category keys in Atlassian's example (`in-flight`, `completed`) differ from the usual `done`; the
  resolution date is the fallback. Not checked against a real site.
- Watcher lists are read only for issues with more than one watcher, again only when the issue
  changed (or after 30 days), at most `max_watcher_calls_per_run` per run; the rest waits for the
  next run (`watchers_left_for_next_run`). Seeing other watchers needs the "View voters and
  watchers" permission in the project; otherwise the list is skipped (`watchers_denied`).
- Incremental: Jira issues updated since the last run plus one hour (relative JQL minutes, so the
  time zone of your Jira profile does not matter), Confluence pages modified since the day before
  the last run. An issue that stopped matching (you were unassigned, stopped watching) stays until
  `--full`.
- Confluence contributors come from the search expansion `content.history.contributors.publishers`;
  if Confluence does not return it, creator and last editor are still read. Atlassian's example
  `_links.next` carries only the query, the limit and the cursor, so the plugin adds the
  expansions back when it follows that link. The interaction date
  of a page is its last modification, not the date of your own edit.
- A scoped token for Jira alone, with Confluence enabled, makes the Confluence part fail: the plugin
  skips it, names it in `products_skipped` and still writes Jira. With `--only confluence` it stops
  with the error instead.
- The cloud id comes from `https://<your-site>/_edge/tenant_info`, which Atlassian documents in a
  support article (https://support.atlassian.com/jira/kb/retrieve-my-atlassian-sites-cloud-id/) but
  not in the versioned REST API: if it ever stops answering, set `atlassian.cloud_id` by hand.
- Rate limits: a 429 or 5xx is retried after `Retry-After` when present, otherwise with exponential
  backoff and jitter, five times at most. Atlassian says API-token traffic follows the burst limits
  (https://developer.atlassian.com/cloud/jira/platform/rate-limiting/,
  https://developer.atlassian.com/cloud/confluence/rate-limiting/).
- API tokens expire after at most one year; an organization using Atlassian Guard can block API
  tokens of external users
  (https://support.atlassian.com/security-and-access-policies/docs/set-api-token-access/). Both show
  up as HTTP 401.
- Jira issue search uses the enhanced endpoint `GET /rest/api/3/search/jql`; the older
  `/rest/api/3/search` is marked "currently being removed"
  (https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).
- Atlassian also offers an official remote MCP server (`https://mcp.atlassian.com/v2/mcp`)
  (https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/);
  SBK does not use it, the plugin calls the REST APIs directly.

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
runs one. For the macOS app (optional, nothing built in): `clickup.tasks_list`, the list its Tasks page
imports your open tasks from; `clickup.user_id`, your ClickUp user id, the assignee of the tasks it
creates from Inspiration; `inspiration.clickup_lists.main`, where Inspiration's *Start* and triage put
an idea's task. Empty = that part is off and the app says so
([The macOS app's Claude Code sessions](#the-macos-apps-claude-code-sessions-optional)).
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

### linear

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

A few widely used tools whose vendor runs an official MCP server (checked on 2026-11-25; vendor pages
change, so read the page before you connect). Add one with
`claude mcp add --transport http <name> <url>` and sign in with `/mcp` in Claude Code:

| Tool | Vendor server | Vendor page |
|---|---|---|
| Asana | `https://mcp.asana.com/v2/mcp`, sign-in with your Asana account | https://developers.asana.com/docs/using-asanas-mcp-server |
| Figma | remote Figma MCP server, `https://mcp.figma.com/mcp` | https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Figma-MCP-server |

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
| Communication | teams (partial) | the microsoft365 app registration + a sign-in with `Chat.Read` (work or school account) | `SBK_MS365_CLIENT_ID`, `SBK_MS365_TENANT` (exported, or the `microsoft365` keys in `sbk.config.json`) · `sbk-microsoft365/<label>` | `uv run python tools/teams/tm-l0-auth.py --account work` |
| Communication | telegram (partial) | none: the data export you make in Telegram Desktop | none | `uv run python tools/telegram/tg-l0-import.py <export folder> --dry-run` |
| Communication | whatsapp | none: chats you export from the phone | none | `uv run python tools/whatsapp/wa-l0l3-full.py --list` |
| CRM | attio | API token of your workspace | `ATTIO_API_KEY` · `sbk-attio/<label>` for extra workspaces | `uv run python tools/attio/at-l0-download.py` |
| CRM | contacts (partial) | none for an export; for Google Contacts your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` optional, `SBK_GCONTACTS_TOKEN_<LABEL>` without a Keychain · `sbk-gcontacts/<label>` | `uv run python tools/contacts/ct-l0-import.py <file.vcf> --label <label>` |
| CRM | databases (partial) | connection string of your own database | `SBK_DB_URL_<NAME>` · `sbk-databases/<connection name>` | `uv run python tools/databases/db-l0-download.py --list` |
| CRM | hubspot (partial) | your own user-level HubSpot app (a HubSpot permission is needed) + browser sign-in | `HUBSPOT_CLIENT_ID` (exported, or `hubspot.client_id` in `sbk.config.json`), `HUBSPOT_CLIENT_SECRET` · `sbk-hubspot/client-secret`, `sbk-hubspot/default` | `uv run python tools/hubspot/hs-l0-auth.py` |
| CRM | pipedrive (partial) | personal API token, or a private OAuth app you register | `PIPEDRIVE_API_TOKEN` (OAuth: `PIPEDRIVE_CLIENT_ID`, `PIPEDRIVE_CLIENT_SECRET`) · `sbk-pipedrive/api-token` | `uv run python tools/pipedrive/pd-l0-download.py --dry-run` |
| Documents | gdrive | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` · `sbk-gdrive/<label>` | `uv run python tools/gdrive/gd-l0-auth.py --account <label>` |
| Documents | notion | your own internal integration token | `NOTION_TOKEN` (optional `SBK_NOTION_*`) | `uv run python tools/notion/no-l0-download.py` |
| Health | apple-health (partial) | none: Health export zip | none | `uv run python tools/apple-health/ah-l0-import.py` |
| Health | clinical (partial) | LLM API keys for parsing | `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY` | `uv run python tools/clinical/cl-l0-ingest.py --file <pdf> --type blood_test --subject <label>` |
| Health | whoop (partial) | your own WHOOP developer app (OAuth2) | `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET` · `sbk-whoop/client-id`, `sbk-whoop/client-secret` | `uv run python tools/whoop/wp-l0-auth.py` |
| HR tool | personio | organisation HR source: API client ID + secret, created with admin rights in Personio | `PERSONIO_CLIENT_ID`, `PERSONIO_CLIENT_SECRET` · `sbk-personio/client-id`, `sbk-personio/client-secret` | `uv run python tools/personio/pe-l0-download.py --dry-run` |
| Meetings & audio | fathom (partial) | personal API key | `FATHOM_API_KEY` · `sbk-fathom/api-key` | `uv run python tools/fathom/fa-l0-download.py --dry-run` |
| Meetings & audio | fireflies (partial) | personal API key | `FIREFLIES_API_KEY` · `sbk-fireflies/api-key` | `uv run python tools/fireflies/ff-l0-download.py --check` |
| Meetings & audio | granola (partial) | personal API key (Business plan), or the CSV export of your notes | `GRANOLA_API_KEY` (exported) · `sbk-granola/api-key` | `uv run python tools/granola/gr-l0-download.py` |
| Meetings & audio | plaud | your Plaud desktop app session; scheduled download only with `plaud` in `enabled_sources` | `SBK_PLAUD_API_BASE` optional · none to add | `uv run python tools/plaud/pl-l0-download.py --dry-transcriptions` |
| Meetings & audio | tactiq | your Chrome session + the public Firebase web key; scheduled download only with `tactiq` in `enabled_sources` | `TACTIQ_FIREBASE_API_KEY` · `sbk-tactiq/refresh-token` (written by `--direct`) | `uv run python tools/tactiq/tq-l0-download.py` |
| Meetings & audio | voice-memos | none: local `.m4a` files | `SBK_VOICE_MEMOS_LANGUAGE` optional | `uv run python tools/voice-memos/vm-l0-transcribe.py` |
| Meetings & audio | zoom (partial) | your own user-managed Zoom app (public client) | `ZOOM_CLIENT_ID` (exported, or `zoom.client_id` in `sbk.config.json`) · `sbk-zoom/client-id`, `sbk-zoom/default` | `uv run python tools/zoom/zm-l0-auth.py` |
| Signing | docusign | your own DocuSign app (JWT: integration key + RSA key) | `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`, `DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_PRIVATE_KEY_PATH` · `sbk-docusign/integration-key`, `sbk-docusign/user-id`, `sbk-docusign/account-id` | `uv run python tools/docusign/ds-l0-api.py --consent-url` |
| Social | linkedin | none: data export | none | `uv run python tools/linkedin/li-l0-import-export.py --dry-run` |
| Tasks | atlassian (partial) | your own Atlassian API token + your account email | `ATLASSIAN_SITE`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` (scoped tokens: `ATLASSIAN_JIRA_API_TOKEN`, `ATLASSIAN_CONFLUENCE_API_TOKEN`) · `sbk-atlassian/api-token`, `sbk-atlassian/jira-token`, `sbk-atlassian/confluence-token` | `uv run python tools/atlassian/as-l0-download.py --dry-run` |
| Tasks | clickup | personal API token | `CLICKUP_API_KEY`, `SBK_CLICKUP_TEAM` optional | `uv run python tools/clickup/cu-l0-backup.py --dry-run` |
| Tasks | linear (partial) | personal API key (Read) | `LINEAR_API_KEY` · `sbk-linear/api-key` | `uv run python tools/linear/ln-l0-download.py --dry-run` |
| Web | analytics | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` · `sbk-ga/<label>` | `uv run python tools/analytics/ga-l0-inventory.py --login <label>` |
| Web | gsc | your own Google app (OAuth, Desktop app) + browser login | `GOOGLE_OAUTH_CLIENT_SECRET_PATH` · `sbk-gsc/<label>` | `uv run python tools/gsc/gs-l0-inventory.py --login <label>` |
