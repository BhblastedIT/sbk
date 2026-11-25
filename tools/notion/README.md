<!-- generated from docs/CONNECTING.md -->
# Notion (`no-`)

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
set them (see [Before you start](../../docs/CONNECTING.md#before-you-start)).
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
with OAuth on your Notion account ([Using an MCP server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)).
It lets an agent search and read your pages live during a session; it does not fill SBK's data folder,
so the knowledge layer and the drafts still need the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#notion](../../docs/CONNECTING.md#notion). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
