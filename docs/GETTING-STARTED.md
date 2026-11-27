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
- `enabled_sources`: the plugins you connect (see [PLUGINS.md](PLUGINS.md)); the download and the
  pipeline run only these. Empty means every source: the download plans all of them, and one you
  never connected fails in it, so list yours (`--ingest` skips a source you never downloaded or
  imported, `not downloaded yet`). Four run only when they are written here: `plaud` and `tactiq`
  (their download reads a login session on your Mac), `linkedin` (only the status rows of its
  browser-cookie scripts) and `chatgpt` (closed)
- `nickname_aliases`: optional, the short names and handles you use for people
  ([Names you use](CONNECTING.md#names-you-use))
- `organisations`: optional, your own companies and brands (their people count as your team, their
  mail domains as internal)
- the other sections (`slack`, `attio`, `clickup`, `gdrive`, `calendar`, `plaud`, `voice_memos`,
  `whatsapp`, `chatgpt`, `notion`, `drafts`, `network_profiles`, `inspiration`, `pipeline_status`,
  `microsoft365`, `imap_caldav`, `zoom`, `github`, `databases`, `hubspot`, `pipedrive`, `fireflies`,
  `fathom`, `granola`, `telegram`, `teams`, `atlassian`, `linear`, `contacts`, `app`, `search`): leave
  them empty unless [CONNECTING.md](CONNECTING.md#what-sbkconfigjson-holds) names a field you want. Every field has a
  `_help` note. No step asks you to edit code
- `inspiration` stays off unless you have your own Inspiration archive of saved ideas
  (`inspiration.archive_dir`); SBK does not ship that archive

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
credentials need admin rights in Personio. `hubspot` uses your own user-level app, and HubSpot asks for
the matching permissions on your user before you can upload and install it.

**Connect your sources with [CONNECTING.md](CONNECTING.md)**, in the order you like. For each plugin
it says what SBK reads, what you create on the vendor's side, the exact env variable or Keychain
entry, the first command and how to check that it worked. Where a vendor runs its own MCP server, the
guide names it as an alternative.

> Secrets live only in `.env` or in the Keychain (macOS) / system keyring (Linux). Never in code,
> never in `sbk.config.json`, never in git. `.env` is already in `.gitignore`.

## 5. Where the data ends up

Everything downloaded and processed lives in `~/.sbk-data/`, outside the repo. Change it with the
`SBK_DATA_ROOT` variable, set in your shell profile: every path follows it
([Where data lands](CONNECTING.md#where-data-lands) names the one Plaud helper that reads `SBK_DATA`).

## 6. First pipeline run

Look at the plan first, without running anything:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run
```

Then run the free stages, which reread what your downloads put on disk:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --ingest
```

It ends with one outcome line: `Pipeline Complete` (exit 0), `Pipeline INCOMPLETE` (exit 2) or
`Pipeline FAILED` (exit 1). On a new install most stages have nothing to read yet, and the run says so:
a source with no folder under the data root is skipped (`not downloaded yet`), the stages with no input
yet are skipped as `nothing to read yet`, and these skips still give `Pipeline Complete`. The search
index downloads its local embedding model once from Hugging Face, so the first run needs the network
once; without it that stage stops at once and is not retried (`setup missing, not retried`),
everything else runs, and the run ends INCOMPLETE with `sources not closed: l3_index`.

One source of any kind is enough for a first knowledge base: WhatsApp, Telegram, your address book or
a database alone gives you people. People who come with only a phone number become contacts keyed by
that number, and become one person with someone another source knows by the same number; set
`phone_country_code` in `sbk.config.json` if your contacts write numbers without the country code
(a national leading 0, as in `07700 900123`, is handled too).
LinkedIn only enriches people other sources bring, so with a LinkedIn export alone the knowledge stays
empty. More on a first run:
[After a download](CONNECTING.md#after-a-download), *A first run*.

The paid stages (knowledge extraction with a model, through your `ANTHROPIC_API_KEY`) run with `--all`,
which asks you to confirm the spend (`--allow-spend` gives that consent when no terminal is attached). `--propagate` and `--rebuild`
redo only the later stages from what is already processed. None of the four downloads anything: the
download of every source in the registry is `uv run python tools/cross-source/xs-l0-refresh.py`
(`--dry-run` shows its plan; with `enabled_sources` set it plans only those sources; `plaud` and `tactiq`
are in it only when `enabled_sources` lists them; with an empty list a source you have not connected
fails at once in it, so list yours or use `--only <source>,<source>`).
The WhatsApp extras run only when you add `--whatsapp-extras` to
`--ingest` or `--all`; they are not set up or tested by the author. Details:
[After a download](CONNECTING.md#after-a-download).

## 7. Teach SBK how you work (optional)

SBK can read what you have typed to AI assistants (your Claude Code logs, and the ChatGPT, Claude.ai
or Manus exports of the tools you used) and build the identity files its drafts and dashboard chat read. Nothing leaves
your machine until you pass `--yes`, and `--dry-run` shows what would be sent. Steps:
[CONNECTING.md#ai-history](CONNECTING.md#ai-history).

## 8. The interfaces

```bash
# Web dashboard (http://127.0.0.1:8000; --port to change it)
uv run python dashboard/run.py
# CLI
uv run python tools/sbk_cli.py --help
# macOS app
cd tools/secondbrain/app && swift build && swift run
```

`search` in the CLI prints the matching results with their source and date, and sends nothing. A written
answer is your choice: `--synthesize` for one search, or `"search": {"synthesis": true}` in
`sbk.config.json`; the question and the results then go to Claude with your own `claude` login
([Search answer](CONNECTING.md#search-answer-optional)).

`brief` prints today's stories from your sources and sends nothing. A written digest from Claude is your choice:
`--synthesize` for one brief, or `"brief": {"synthesis": true}` in `sbk.config.json`; the stories, with the text
of the messages they come from, then go to Claude through the Anthropic API with your `ANTHROPIC_API_KEY`
([Brief digest](CONNECTING.md#brief-digest-optional)).

The weekly insights (`tools/cross-source/xs-temporal-analysis.py`) and the signal detector
(`tools/monitoring/signal-detector.py --scan`) work the same way: local by default, a summary from Claude only
with `--ai` / `--synthesize` or `"insights"` / `"signals": {"synthesis": true}` in `sbk.config.json`
([Weekly insights and signal summaries](CONNECTING.md#weekly-insights-and-signal-summaries-optional)).

On a fresh install the dashboard and the CLI open with empty lists: the pages fill as your sources come
in. `sbk search` says `nothing is indexed yet` until the L3 Index stage of `--ingest` has built the
search index, and the dashboard's follow-ups appear only after the L3 extract (a paid stage, `--all`).

The monitor (`uv run python tools/monitoring/sbk-monitor.py`) watches your connected sources while it
runs and alerts you. Its jobs that send your data to a model (new-mail triage, pre-meeting briefs, the
morning digest, meeting capture) run only with `SBK_MONITOR_MODEL=1` in `.env` or `--with-model`.
Nothing is scheduled after the install; the LaunchAgent templates and how to turn them on:
[The monitor and scheduled jobs](CONNECTING.md#the-monitor-and-scheduled-jobs-optional). While the
dashboard is open, its scheduler runs only the intervals you set on its pipeline page (all off at
first); `uv run python tools/util/sb-pipeline-ctl.py off` stops every automatic start, `on` allows it
again.

### The macOS app

`swift build && swift run` in `tools/secondbrain/app` finds your clone from the folder it runs in.
To keep it in /Applications, run `uv run python tools/secondbrain/installa.py` from your clone: it records
the clone's folder, and the app runs the engine of that clone wherever it is. If you move the clone,
use *Choose the folder…* on the app's "Can't find SBK" page, or run `installa.py` again.
`uv run python tools/secondbrain/installa.py --update` replaces the installed app in place, and
`--roll-back-to <version>` reinstalls an archived version without building it again.

**Its AI features use your own Claude Code login and are off until you allow them.** A request you
dictate or write on the Tasks page and the Inspiration jobs (understanding a saved idea, the re-read
after your answer, the background sorting, the backlog re-read) run `claude -p` in the background with
the login of your own `claude` command. They start only with `"app": {"claude_sessions": true}` in
`sbk.config.json`; without it nothing is sent. What each one sends, the model setting and the check
command `uv run python tools/secondbrain/sb_own_claude.py status`:
[The macOS app's Claude Code sessions](CONNECTING.md#the-macos-apps-claude-code-sessions-optional).

Optional, also in that section: the ClickUp list of the Tasks page (`clickup.tasks_list`), your
ClickUp user id (`clickup.user_id`) and Inspiration's lists (`inspiration.clickup_lists`), none built
in; and the terminal-manager command that *Open in a terminal* needs (`SB_AGENT_CLI`), without which
the app copies the text to your clipboard. The Pages view reads your local Claude Code logs and sends
nothing. Inspiration stays off unless `inspiration.archive_dir` names your own archive of saved ideas,
which SBK does not ship.

Task areas come from the code at the start of a task title, such as `[W-12] Call the bank`, or from an
`Area: ...` line in its description. The defaults are generic, at the top of
`tools/secondbrain/sb_cose.py` (`AREE_FORMA`, `AREE`, `AREE_DESCRIZIONE`): change them to your own
codes. The `W-` prefix puts a task in the "Waiting on you" view.

## 9. Quality gate

```bash
uv run pre-commit install        # ruff, format, gitleaks
uv run pre-commit run --all-files
```

## 10. Encrypted backup (optional)

```bash
uv run python tools/infrastructure/sb-backup.py --level 1 --dry-run   # what one layer would copy, and the space check
uv run python tools/infrastructure/sb-backup.py --level 1             # an encrypted, verified archive of that layer
```

The first backup creates the encryption key and keeps it only in your Keychain (service `sbk-backup`,
account `enc-key`): SBK writes it to no file and never prints it, and without it no archive can be
opened. Keep your own offline copy (a password manager, paper). This prints the key, so run it only
where you mean to:

```bash
uv run python -c "import keyring; print(keyring.get_password('sbk-backup', 'enc-key'))"
```

In container mode (`SBK_CONTAINERIZED=1`) there is no Keychain: the key comes from `SBK_BACKUP_ENC_KEY`,
which you generate (for example `openssl rand -base64 32`) and keep yourself; without it the backup
stops. `--help` lists the destination and the other options; the layers, the restore trial and how to
put the key back on a new machine are in [.claude/skills/backup/SKILL.md](../.claude/skills/backup/SKILL.md).

What it covers: your data root, the repo's `sbk/` folder (your identity files), this project's Claude
Code files (its sessions and memory, your Claude Code rules and settings, your prompt history) and, in
layer 1, a git bundle of the repo. Your `~/Downloads` folder is never in it unless you ask for it in
`sbk.config.json`:

```json
"backup": {"include_downloads": true}
```

It then goes, encrypted, into layer 3, which is written only to an external disk.

## Common problems

- **What does a script do?** Every Python script answers `--help` (or `-h`): it prints its options,
  exits with code 0 and writes nothing.
- **`ModuleNotFoundError: sbk_config`**: run the scripts with `uv run` from the repo root, so
  `tools/` is on the path.
- **`plaud` or `tactiq` is `(not run)` in the download plan**: write it in `enabled_sources`; their
  download reads a login session on your Mac, so it never runs unless you list it.
- **A source does not download**: check its section in [CONNECTING.md](CONNECTING.md), the exact env
  variable or Keychain entry, and whether the script loads `.env` by itself (some need
  `set -a && source .env && set +a` first, listed in
  [Before you start](CONNECTING.md#scripts-that-do-not-load-env-by-themselves)).
- **`sbk.config.json has no owner / own_emails`**: fill `owner` and `own_emails` (step 3).
- **The download fails for sources you never connected**: with an empty `enabled_sources` every source
  with a download script is in the plan of `xs-l0-refresh.py`; list the sources you connected in
  `enabled_sources` (the download then plans only those), or run it with `--only <source>,<source>`.
- **`--ingest` says `not downloaded yet` or `nothing to read yet`**: nothing is wrong. A source with no
  folder under the data root is skipped until you download or import it, and a stage whose input does
  not exist yet is skipped; the run still ends `Pipeline Complete`.
- **`Pipeline INCOMPLETE … sources not closed: l3_index`**: the search index could not load its local
  embedding model (the log says `setup missing, not retried`). Run once with the network so it
  downloads from Hugging Face.
- **The app says Claude Code sessions are off**: that is the default; set `app.claude_sessions` to
  `true` only if you want those features ([details](CONNECTING.md#the-macos-apps-claude-code-sessions-optional)).
- **A PDF of a Markdown dossier**: `tools/util/gen-dossier-pdf.py <input.md> [output.pdf]` needs the
  optional package reportlab, `uv add reportlab`; nothing else needs it. Without an output path the PDF
  goes to `<data root>/dossiers/<input name>.pdf`, never into the repo (`*.pdf` is git-ignored as a
  safety net).
- **A Google login stops working after a week**: your Google app is in *Testing*; see
  [Google](CONNECTING.md#google).
- **The pipeline looks complete but something is missing**: `Pipeline Complete` allows only the
  skips it counts in brackets (unchanged, resumed, not in `enabled_sources`, nothing to read yet);
  any other skip makes the run INCOMPLETE. Read the output: it names what was skipped and why.
