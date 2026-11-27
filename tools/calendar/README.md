<!-- generated from docs/CONNECTING.md -->
# Google Calendar (`ca-`)

Signs in through your own Google app, which you set up once for the Google plugins: [Google](../../docs/CONNECTING.md#google).

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
([Using an MCP server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent read your
calendars live during a session; it does not fill SBK's data folder, so the knowledge layer and the
drafts still need the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#calendar](../../docs/CONNECTING.md#calendar). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
