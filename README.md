# SBK — Super Brain Kernel

**Version 0.1.0** · by **salvatoresng** · an open-source project published by **[Bhblasted](https://www.bhblasted.com)**

Website: **[superbrainkernel.com](https://superbrainkernel.com)**

> Your second brain, local. SBK collects, normalizes and cross-references all
> your communications (email, meetings, calls, chat, CRM, documents) to build a
> living knowledge base about people, companies and decisions, with a dashboard,
> a CLI and an app on top. Then it acts on what it knows: tasks, messages and
> email drafts, each one weighed against the full context and approved by you.
>
> **No SBK cloud.** Data, index and graph stay on your disk; model calls go to
> the provider you choose, with your key.

SBK is a **kernel + plugins**. The kernel is the engine (L0→L3 pipeline, entity
resolution, knowledge layer). The plugins are the **sources** you connect: yours,
not anyone else's. Turn on only the ones you need.

---

## What it does, in one line

Take your scattered data → download it (L0) → enrich it (L1) → unify it (L2) →
extract knowledge (L3) → act on it (tasks, follow-ups, message and email
drafts, after a full-context check and your approval) → query it from the
dashboard, CLI or app.

## Architecture

```
                 ┌───────────────────────────────────────────┐
   YOUR          │                  KERNEL                    │
   SOURCES       │                                            │
  (plugins)      │   L0 download → L1 enrich → L2 merge →      │
 ┌──────────┐    │   L2 entity-resolution → L3 knowledge       │
 │ email    │───▶│                                            │
 │ calendar │───▶│   Living Knowledge Layer                   │
 │ slack    │───▶│   (people · companies · deals · commits)   │
 │ meeting  │───▶│                                            │
 │ chat     │───▶│                                            │
 │ CRM      │───▶│                                            │
 │ docs     │───▶│                                            │
 │ …        │    │                                            │
 └──────────┘    └───────────────┬───────────────────────────┘
                                  │
                    ACT  (full-context evaluation → you approve)
              tasks · follow-ups · Slack messages · email drafts
                                  │
            ┌─────────────────────┼─────────────────────┐
            ▼                     ▼                     ▼
       Dashboard              CLI `sbk`            App (macOS)
    (FastAPI, web)      search/brief/lookup…      Second-brain
```

- **Kernel** (`tools/`, `lib/`) — the pipeline and the logic that doesn't change
  from person to person. See `tools/DATA-PIPELINE.md`.
- **Plugins / sources** — each connector folder under `tools/` is a plugin, listed
  [below](#the-plugins). The registry lives in `tools/sorgenti.py`. See
  [docs/PLUGINS.md](docs/PLUGINS.md).
- **Act** — `tools/cross-source/xs-l3-tasks.py` (daily tasks from seven
  collectors, scored by urgency, deadline and how many sources agree, sorted
  into Eisenhower quadrants), `xs-l3-followup.py` (promises from meetings with
  their deadlines), `xs-l3-draft.py` and the dashboard `draft_reply` tool
  (drafts in your voice, built from the recipient's profile, recent
  interactions, facts and similar past emails). Email is never sent on its own;
  Slack messages leave the dashboard only when you send them.
- **Dashboard** (`dashboard/`) — FastAPI + HTMX, status and search over your data.
- **CLI** (`tools/sbk_cli.py`, `sbk` command) — search, brief, lookup, pipeline.
- **App** (`tools/secondbrain/app/`) — native macOS app (SwiftUI).

## The plugins

One folder under `tools/` each, in alphabetical order, with its prefix. Every one connects
with your own access only: an export you make, a personal token, or an app in your own
account. The one organisation source is `personio`, whose credentials need admin rights in
Personio. Turn on only the ones you use. How each one connects:
[docs/CONNECTING.md](docs/CONNECTING.md) and the `README.md` in its folder. *Partial* means
it works in part, or was tested only against mocked services.

- `ai-history` (`ai-`): what you typed to your AI assistants, to learn how you work:
  your Claude Code logs, and the ChatGPT, Claude.ai or Manus exports of the tools you
  used. On request; nothing goes to a model without your consent.
- `analytics` (`ga-`): your Google Analytics 4 properties, with your own Google app.
- `apple-health` (`ah-`): the export of the Health app (partial).
- `attio` (`at-`): Attio CRM: companies, people, deals, notes, calls.
- `calendar` (`ca-`): your Google calendars, with your own Google app.
- `chatgpt` (`cg-`): only if you used ChatGPT: its export is read by `ai-history`.
- `clickup` (`cu-`): tasks, comments and docs; tasks become commitments.
- `clinical` (`cl-`): clinical documents you add yourself; the parsing step sends them
  to a model API (partial).
- `databases` (`db-`): people and events from a SQLite, PostgreSQL or MySQL database
  you own, through read-only queries you write (partial).
- `docusign` (`ds-`): envelopes, signers and signed documents.
- `email` (`em-`): your Gmail, with your own Google app.
- `gdrive` (`gd-`): your Google Drive documents, with your own Google app.
- `github` (`gh-`): your repositories, collaborators, issues, pull requests and
  reviews, with your personal access token (partial).
- `gsc` (`gs-`): your Search Console properties, with your own Google app.
- `imap-caldav` (`ic-`): any mailbox over IMAP and any calendar over CalDAV or a
  calendar link, with your app password (partial).
- `linkedin` (`li-`): the data export of your LinkedIn account.
- `microsoft365` (`ms-`): your Outlook mail, calendars and contacts, with your own app
  registration (partial).
- `notion` (`no-`): pages and databases you share with your integration.
- `personio` (`pe-`): HR tool. Your organisation's employees, absences and contracts: an
  organisation source whose API credentials need admin rights in Personio.
- `plaud` (`pl-`): recordings and transcripts of your Plaud recorder.
- `slack` (`sl-`): channels, threads and your DMs, with your own Slack app and user token.
- `tactiq` (`tq-`): your meeting transcripts.
- `voice-memos` (`vm-`): voice memos, transcribed on your machine.
- `whatsapp` (`wa-`): the chats you export from your phone, then import. Live reading
  of WhatsApp is not set up.
- `whoop` (`wp-`): WHOOP wearable data (partial).
- `zoom` (`zm-`): your Zoom meetings, participants and cloud-recording transcripts
  (partial).

## Data levels (L0→L3)

| Level | What it is | Where |
|---|---|---|
| **L0** | raw data downloaded from the source | `~/.sbk-data/<source>/raw/` |
| **L1** | normalized and enriched data | `~/.sbk-data/enriched/` |
| **L2** | unified cross-source data, entities resolved | `~/.sbk-data/exports/` |
| **L3** | knowledge (profiles, relationships, alerts) | `~/.sbk-data/l3/` |

Data lives **outside the repo**, in `~/.sbk-data/` (configurable with
`SBK_DATA_ROOT`). The repo contains only code.

## Setting it up

1. **Have Claude Code (or an AI agent)?** Open the repo and tell it *"read
   CLAUDE.md and help me set up SBK with my sources"*. SBK is designed to be
   installed with an agent guiding you. → [CLAUDE.md](CLAUDE.md)
2. **By hand?** → [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)

In short:
```bash
# 1. get the code
git clone https://github.com/BhblastedIT/sbk
cd sbk
# 2. dependencies (needs uv: https://docs.astral.sh/uv/)
uv sync
# 3. configure who you are and which sources you turn on
cp sbk.config.example.json sbk.config.json   # then edit it
cp .env.example .env                          # add your keys
# 4. see the pipeline plan without running it
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run
# 5. dashboard
uv run python dashboard/run.py
```

## Principles

- **Local and plain-text.** No mandatory cloud. Your data stays yours.
- **Secrets are never hard-coded.** Keys in `.env` / Keychain, never in code.
- **Config points to how to verify, not to hard facts.** Prefer generated or
  queried state over hand-written values, which drift out of date.
- **The pipeline is viewed whole.** A run that skips a stage isn't complete even
  if it exits OK.

## Requirements

- macOS or Linux · Python 3.12+ · [uv](https://docs.astral.sh/uv/)
- The keys/OAuth of the sources you want to connect (see `.env.example`)
- (App) Xcode / Swift toolchain, macOS only

## License

MIT. See [LICENSE](LICENSE).
