<!-- generated from docs/CONNECTING.md -->
# AI history (`ai-`)

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

## What it reads

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

## What leaves your machine, and when

| Step | Leaves the machine |
|---|---|
| Reading Claude Code logs, importing exports | nothing |
| How you work, step 1 (statistics, recurring instructions) | nothing |
| How you work, `--dry-run` | nothing. It prints what step 2 would send and can save the exact text locally (`--show-payload`) |
| How you work, step 2 with `--yes` | a bounded sample of your typed messages plus the step 1 summary, redacted a second time (secrets, email addresses, phone numbers), sent to the model provider you choose (default Anthropic, key `ANTHROPIC_API_KEY`). Up to `--max-chars` characters of evidence per call (default 60000), one call per identity file |

Without `--yes` nothing is sent. With `--dry-run` nothing is sent even if `--yes` is there.

## Commands

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

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#ai-history](../../docs/CONNECTING.md#ai-history). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
