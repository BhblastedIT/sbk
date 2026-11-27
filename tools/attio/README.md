<!-- generated from docs/CONNECTING.md -->
# Attio CRM (`at-`)

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
server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent ask your CRM questions live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#attio](../../docs/CONNECTING.md#attio). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
