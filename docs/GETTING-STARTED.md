# SBK — Step-by-step install

The manual guide. If you work with Claude Code or another AI agent, let it read
[CLAUDE.md](../CLAUDE.md) first: it walks you through the same steps.

## 0. Prerequisites

- macOS or Linux (some plugins are macOS only; their section in [CONNECTING.md](CONNECTING.md) says so)
- Python 3.12 or higher
- [git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- For the macOS app: Xcode or the Swift toolchain

## 1. Get the code

```bash
git clone https://github.com/BhblastedIT/sbk
cd sbk
```

## 2. Dependencies

```bash
uv sync
```

Two database drivers are optional and not installed by `uv sync`: add one only if you use the
`databases` plugin with that database, `uv add 'psycopg[binary]>=3.2'` for PostgreSQL or
`uv add 'pymysql>=1.1'` for MySQL ([databases](CONNECTING.md#databases)).

## 3. Who you are and which sources you turn on

```bash
cp sbk.config.example.json sbk.config.json
```

Open `sbk.config.json` and fill in your own data:

- `owner`: your full name, so SBK recognises you and leaves you out of your own contact lists
- `own_emails`: every address and alias that is you
- `own_names`: how your name is written in your messages, lower case
- `own_person_id`: leave it empty for now (it is your id in the knowledge layer, once it exists)
- `email_accounts`: one label per mailbox you connect
- `enabled_sources`: the plugins you connect (see [PLUGINS.md](PLUGINS.md)); the pipeline runs the
  L1 step only for these. Empty runs every source that has data
- `nickname_aliases`: optional, the short names and handles you use for people
  ([Names you use](CONNECTING.md#names-you-use))
- `organisations`: optional, your own companies and brands (their people count as your team, their
  mail domains as internal)
- the other sections (`slack`, `attio`, `clickup`, `gdrive`, `calendar`, `plaud`, `voice_memos`,
  `whatsapp`, `chatgpt`, `notion`, `drafts`, `network_profiles`, `inspiration`, `pipeline_status`,
  `microsoft365`, `imap_caldav`, `zoom`, `github`, `databases`): leave them empty unless
  [CONNECTING.md](CONNECTING.md#what-sbkconfigjson-holds) names a field you want. Every field has a
  `_help` note. No step asks you to edit code

`owner`, `own_emails`, `own_names` and `own_person_id` are the only place SBK learns who you are:
no script, prompt or default sets your name or your address. Without `owner` and `own_emails` SBK logs
one warning and cannot tell you apart from the people you talk to.

## 4. Your keys and logins

```bash
cp .env.example .env
```

Fill in only the lines of the plugins you turn on. Every connection is your own: an export you make,
a personal token, or an app you create in your own account (for Google, your own OAuth client of
type *Desktop app* and a browser login per account; for Slack, your own Slack app with a user token).
The one exception is `personio`, an HR tool: it reads your organisation's HR records, and its API
credentials need admin rights in Personio.

**Connect your sources with [CONNECTING.md](CONNECTING.md)**, in the order you like. For each plugin
it says what SBK reads, what you create on the vendor's side, the exact env variable or Keychain
entry, the first command and how to check that it worked. Where a vendor runs its own MCP server, the
guide names it as an alternative.

> Secrets live only in `.env` or in the Keychain (macOS) / system keyring (Linux). Never in code,
> never in `sbk.config.json`, never in git. `.env` is already in `.gitignore`.

## 5. Where the data ends up

Everything downloaded and processed lives in `~/.sbk-data/`, outside the repo. Change it with the
`SBK_DATA_ROOT` variable, set in your shell profile (the guide's
[Where data lands](CONNECTING.md#where-data-lands) lists the few paths that stay fixed).

## 6. First pipeline run

Look at the plan first, without running anything:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run
```

Then run the free stages, which reread what your downloads put on disk:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --ingest
```

The paid stages (knowledge extraction with a model) run with `--all`, which asks you to confirm the
spend (`--allow-spend` gives that consent when no terminal is attached). `--propagate` and `--rebuild`
redo only the later stages from what is already processed. None of the four downloads anything: the
download of every source in the registry is `uv run python tools/cross-source/xs-l0-refresh.py`
(`--dry-run` shows its plan). The WhatsApp extras run only when you add `--whatsapp-extras` to
`--ingest` or `--all`; they are not set up or tested by the author. Details:
[After a download](CONNECTING.md#after-a-download).

## 7. Teach SBK how you work (optional)

SBK can read what you have typed to AI assistants (your Claude Code logs, and the ChatGPT, Claude.ai
or Manus exports of the tools you used) and build the identity files its drafts and dashboard chat read. Nothing leaves
your machine until you pass `--yes`, and `--dry-run` shows what would be sent. Steps:
[CONNECTING.md#ai-history](CONNECTING.md#ai-history).

## 8. The interfaces

```bash
# Web dashboard
uv run python dashboard/run.py
# CLI
uv run python tools/sbk_cli.py --help
# macOS app
cd tools/secondbrain/app && swift build && swift run
```

The monitor (`uv run python tools/monitoring/sbk-monitor.py`) watches your connected sources while it
runs and alerts you. Its jobs that send your data to a model (new-mail triage, pre-meeting briefs, the
morning digest, meeting capture) run only with `SBK_MONITOR_MODEL=1` in `.env` or `--with-model`.
Nothing is scheduled after the install; the LaunchAgent templates and how to turn them on:
[The monitor and scheduled jobs](CONNECTING.md#the-monitor-and-scheduled-jobs-optional).

## 9. Quality gate

```bash
uv run pre-commit install        # ruff, format, gitleaks
uv run pre-commit run --all-files
```

## Common problems

- **`ModuleNotFoundError: sbk_config`**: run the scripts with `uv run` from the repo root, so
  `tools/` is on the path.
- **A source does not download**: check its section in [CONNECTING.md](CONNECTING.md), the exact env
  variable or Keychain entry, and whether the script loads `.env` by itself (some need
  `set -a && source .env && set +a` first, listed in
  [Before you start](CONNECTING.md#scripts-that-do-not-load-env-by-themselves)).
- **`sbk.config.json has no owner / own_emails`**: fill `owner` and `own_emails` (step 3).
- **A Google login stops working after a week**: your Google app is in *Testing*; see
  [Google](CONNECTING.md#google).
- **The pipeline looks complete but something is missing**: a run that skips a stage is not
  complete. Read the output: it names what was skipped and why.
