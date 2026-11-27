<!-- generated from docs/CONNECTING.md -->
# ClickUp (`cu-`)

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
([The macOS app's Claude Code sessions](../../docs/CONNECTING.md#the-macos-apps-claude-code-sessions-optional)).
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
server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent read your tasks live during a
session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need the
download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#clickup](../../docs/CONNECTING.md#clickup). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
