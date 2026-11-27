<!-- generated from docs/CONNECTING.md -->
# Google Analytics 4 (`ga-`)

Signs in through your own Google app, which you set up once for the Google plugins: [Google](../../docs/CONNECTING.md#google).

**Status** mature (feeds the domain inventory, not people) · registry `periodica`, every 30 days.
**Reads** the GA4 properties your Google account can see, with sessions, users, channels and top pages.
**You need** your Google app with the Google Analytics Admin API and Data API enabled, and a Google
account with at least Viewer access to the GA4 properties.
**Create it**
```bash
uv run python tools/analytics/ga-l0-inventory.py --login main   # browser login; prints how many properties it sees
```
**Where the code looks** Keychain `sbk-ga/<label>`, the labels in `<data root>/analytics/accounts.json`,
the OAuth client as for email.
**sbk.config.json** nothing.
**Download**
```bash
uv run python tools/analytics/ga-l0-inventory.py                  # last 28 days (--days N to change)
uv run python tools/analytics/ga-l0-inventory.py --account main   # one signed-in account only
```
**Check** `<data root>/analytics/property.json` and `<data root>/analytics/performance/`.
**Limits** Covers only GA4 properties (not Universal Analytics). A property seen by two of your
accounts is read once. Without any login the script stops with a message and does nothing.
**Alternative, an MCP server** Google publishes a read-only Google Analytics MCP server that runs on
your Mac (PyPI package `analytics-mcp`), with your own Google user login ([Using an MCP
server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent query your GA4 properties live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#analytics](../../docs/CONNECTING.md#analytics). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
