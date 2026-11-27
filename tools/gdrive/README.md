<!-- generated from docs/CONNECTING.md -->
# Google Drive (`gd-`)

Signs in through your own Google app, which you set up once for the Google plugins: [Google](../../docs/CONNECTING.md#google).

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
an MCP server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent search and read your
documents live during a session; it does not fill SBK's data folder, so the knowledge layer and the
drafts still need the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#gdrive](../../docs/CONNECTING.md#gdrive). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
