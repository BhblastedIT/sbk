# SBK — Instructions for the AI agent

> You are the agent that helps the person install, configure and run **SBK
> (Super Brain Kernel)**: their local second brain. This file says **how to work**
> on this repo. The facts (which sources are active, what is fresh, what runs) are
> **generated** with commands, not read from here.

## What SBK is (the minimum you need)

A **kernel + plugins**. The kernel is the **L0→L3** data pipeline plus the Living
Knowledge Layer (people, companies, deals, commitments). The **plugins** are the
sources the person connects (email, calendar, Slack, meetings, chat, CRM, docs…).
On top: a FastAPI dashboard, an `sbk` CLI, a macOS app.

- Code: `tools/` (kernel + plugins), `lib/`, `dashboard/`.
- Central config: `tools/sbk_config.py` (paths, constants; reads `SBK_DATA_ROOT`).
- Source registry: `tools/sorgenti.py` (nature and cadence of each source).
- Data: **outside the repo**, in `~/.sbk-data/` (never in git).

## First thing to do in a session

1. Understand the real state, don't assume it. Generate, don't read:
   ```bash
   uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run   # the plan
   ```
2. Look at what is configured: `sbk.config.json` (if missing, see "Onboarding").
3. Only then, act.

## Onboarding: connecting the person's sources

This is the main work you do with a new user.

1. **Identity and sources.** `cp sbk.config.example.json sbk.config.json`, then
   fill it in with them: who they are, which mailboxes/accounts, and which plugins
   to turn on, by folder name in `enabled_sources`.
2. **Secrets.** `cp .env.example .env`. For each plugin you turn on, obtain the
   keys/OAuth (the person creates them on the respective services; the exact names
   are in `docs/CONNECTING.md`). **Never write a secret in the code or commit it**:
   only in `.env` or the Keychain.
3. **Plugins, one at a time, with `docs/CONNECTING.md`.** Each source folder under
   `tools/` is a plugin; its `README.md` summarises the same facts. Walk the person
   source by source, in the order they choose. For each source:
   - ask whether they want it, and say what it reads and what leaves the machine
     (the guide flags the plugins that call external APIs, e.g. `clinical`);
   - tell them what to create on the vendor side and where the code reads it
     (env var name, or the Keychain service and account names); they type the
     secret themselves, you never see or paste it;
   - every connection is the person's own: for Google, their own OAuth client
     ("Desktop app") and a browser login per account; for Slack, their own Slack
     app with a user token. Where the guide lists an MCP server for a source, you
     may offer it as the simpler alternative;
   - run the first command from the guide, then **verify** with its "Check" line
     (the file under `~/.sbk-data/` exists and is not empty) before moving on;
   - if it fails, read the error and the cited `file:line`, fix the setup, retry.
     Do not move to the next source with this one broken or unverified.
   **Switch sources on and off only with `enabled_sources` in `sbk.config.json`**,
   never by editing `tools/sorgenti.py` or other code. `plaud` and `tactiq` read a
   login session on the person's Mac (the Plaud desktop app, Tactiq in Chrome) and
   run in the scheduled download only when listed: say what they read before you
   add them.
4. **First run.** The free stages, no money spent:
   ```bash
   uv run python tools/cross-source/xs-pipeline-run.py --ingest
   ```
   then look at the dashboard.
   On a new install, `not downloaded yet` and `nothing to read yet` are harmless skips (the run still
   says `Pipeline Complete`). The search index downloads its embedding model from Hugging Face once:
   without the network the run ends INCOMPLETE with `sources not closed: l3_index`
   (`docs/CONNECTING.md#after-a-download`, *A first run*).
5. **Teach SBK how you work.** On request only (registry id `ai-history`, never in
   the full run; guide: `docs/CONNECTING.md#ai-history`). It turns what the person
   has typed to AI assistants into the identity files the drafts and the chat read.
   - **Read their Claude Code logs.** `uv run python tools/ai-history/ai-l0-claude-code.py --dry-run`
     prints counts only; then run it without `--dry-run`. It keeps only what they
     typed, redacts secrets and writes `~/.sbk-data/ai-history/messages.jsonl`.
     Nothing leaves the machine.
   - **Import their AI chat exports**, only for tools they actually used: they
     download the export themselves, you run
     `uv run python tools/ai-history/ai-l0-import-export.py <export.zip|folder>`
     (`--format manus` for a folder of saved Manus tasks), `--dry-run` first.
   - **Dry run.** `uv run python tools/ai-history/ai-l3-how-you-work.py --dry-run --show-payload`:
     tell them the provider, the model, how many messages and characters would be
     sent, and where the exact text is saved so they can read it. Do not open their
     messages or that text in this conversation unless they ask.
   - **Consent.** Only after they say yes, run the same command with `--yes` instead
     of `--dry-run`. Never pass `--yes` on your own.
   - **Build the identity files.** That run writes `sbk/identity/profile.md`,
     `style-guide.md`, `communication-playbook.md`, `decision-framework.md` and
     `working-rules.md` (git-ignored; an existing file gets a `.new.md` next to it).
     Verify with the guide's "Check" line, then let them read and edit the files.

## The pipeline is viewed WHOLE, never in pieces

Four commands, the name says the scope (`xs-pipeline-run.py --help` lists them):
```bash
uv run python tools/cross-source/xs-pipeline-run.py --all          # the whole chain (incl. paid stages: asks consent to spend)
uv run python tools/cross-source/xs-pipeline-run.py --ingest       # only the free L1+L2+L3
uv run python tools/cross-source/xs-pipeline-run.py --propagate    # L2+L3 incremental, from what is already on disk
uv run python tools/cross-source/xs-pipeline-run.py --rebuild      # L2+L3 with every stage forced; never L1, L0 or paid stages
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run     # the plan, without running
```
None of them downloads (L0): that is `tools/cross-source/xs-l0-refresh.py` (`--then-ingest` runs
`--ingest` after it).
Rules: no completion percentage without saying over which denominator; a run that
skips a stage is **not complete** (name what was skipped), except the harmless skips the
outcome line counts in brackets (unchanged, resumed, not in `enabled_sources`, nothing to read yet);
paid stages cost money (they use the person's one `ANTHROPIC_API_KEY`), so ask first.
With `enabled_sources` set, `xs-l0-refresh.py` plans only the sources it lists; with an
empty list every source with a download script is in the plan, also the ones the person
never connected (those fail at once): list them, or run it with `--only <source>,<source>`.

## Running the interfaces

```bash
uv run python dashboard/run.py          # web dashboard (FastAPI)
uv run python tools/sbk_cli.py --help   # CLI: search, brief, lookup, pipeline, tasks, draft
# macOS app:
cd tools/secondbrain/app && swift build
```

Six features send data to a model only with the person's consent, and you never
give it for them: the monitor's model jobs (`SBK_MONITOR_MODEL=1` or `--with-model`),
the macOS app's background Claude Code sessions (`"app": {"claude_sessions": true}`,
which use their own `claude` login), the answer of `sbk search` (`--synthesize` or
`"search": {"synthesis": true}`: the question and the retrieved results go to Claude with
their own `claude` login; by default search prints raw results), the digest of `sbk brief`
(`--synthesize` or `"brief": {"synthesis": true}`: today's stories, with the text of the
messages they come from, go to Claude through the Anthropic API with their
`ANTHROPIC_API_KEY`; by default brief prints the stories), the weekly insights of
`tools/cross-source/xs-temporal-analysis.py` (`--ai` or `"insights": {"synthesis": true}`: a
summary of the week with contact e-mail addresses and deal names goes to Claude through the
Anthropic API; by default the analysis is local) and the signal summaries of
`tools/monitoring/signal-detector.py --scan` (`--synthesize` or `"signals": {"synthesis": true}`:
up to 8 facts per signal about the people involved go to Claude through the Anthropic API; by
default a local one-line summary). Say what each one sends
(`docs/CONNECTING.md#the-monitor-and-scheduled-jobs-optional`,
`docs/CONNECTING.md#the-macos-apps-claude-code-sessions-optional`,
`docs/CONNECTING.md#search-answer-optional`, `docs/CONNECTING.md#brief-digest-optional`,
`docs/CONNECTING.md#weekly-insights-and-signal-summaries-optional`) and let them decide.

## Memory and stability (if the machine is small)

Processing large data can saturate RAM. Don't hard-code budgets in MB: use
`tools/sbk_resources.py` (`budget()`, `configure_duckdb(con)`). Avoid
`itertuples()` + `append(dict)` on large tables. DuckDB without an explicit
`memory_limit` takes too much RAM.

## Working rules (non-negotiable)

1. **Secrets**: never hard-code, never print/paste tokens and keys. `.env` or
   Keychain. Read before you modify.
2. **External communications** (email, Slack, messages, posts): never send
   external messages without the user's explicit approval.
3. **Destructive operations** (deleting data, dropping, overwriting history):
   never without explicit confirmation. Look at the target first.
4. **Verify, don't assume**: treat a claim from a doc or a sub-agent as unproven
   until you check it against the code. Cite `file:line`, not from memory.
5. **The data is the person's**: don't send it to external services (header, URL,
   payload) without their explicit OK.

## Development

- Python 3.12+ with **uv**. Lint/format: `ruff`. Gate: pre-commit
  (`uv run pre-commit install`).
- Tests: `uv run pytest tests/<file> -q` (start from the smoke suite). On small
  machines don't run the whole suite blindly.
- Branch for risky work; Conventional Commits. Commit/push only on request.

## Where things are

| Need | Go to |
|---|---|
| Pipeline state | generated: `xs-pipeline-run.py --all --dry-run` |
| Config, paths, constants | `tools/sbk_config.py` |
| Which sources are on | `enabled_sources` in `sbk.config.json` |
| Source/plugin registry | `tools/sorgenti.py` · `docs/PLUGINS.md` |
| Runtime data L0/L1/L2/L3 | `~/.sbk-data/` (never in git) |
| Pipeline (overview) | `tools/DATA-PIPELINE.md` |
| Dashboard | `dashboard/` |
| macOS app | `tools/secondbrain/app/` |
| How the person works (identity files) | `sbk/identity/` (git-ignored) · built by `tools/ai-history/` |
| How to connect a source | `docs/CONNECTING.md` (per plugin) · `docs/PLUGINS.md` (overview) |
