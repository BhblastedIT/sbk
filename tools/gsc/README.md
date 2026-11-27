<!-- generated from docs/CONNECTING.md -->
# Google Search Console (`gs-`)

Signs in through your own Google app, which you set up once for the Google plugins: [Google](../../docs/CONNECTING.md#google).

**Status** mature (feeds the domain inventory, not people) · registry `periodica`, every 30 days.
**Reads** the Search Console properties your Google account can see, with clicks, impressions, top
queries and top pages.
**You need** your Google app with the Google Search Console API enabled, and a Google account that
is an owner or user of the properties in Search Console.
**Create it**
```bash
uv run python tools/gsc/gs-l0-inventory.py --login main   # browser login; prints how many properties it sees
```
Repeat with another label for each other account that sees other properties.
**Where the code looks** Keychain `sbk-gsc/<label>`, the labels in `<data root>/gsc/accounts.json`,
the OAuth client as for email.
**sbk.config.json** nothing.
**Download**
```bash
uv run python tools/gsc/gs-l0-inventory.py --list-only     # list the properties only
uv run python tools/gsc/gs-l0-inventory.py                 # last 28 days (--days N to change)
uv run python tools/gsc/gs-l0-inventory.py --account main  # one signed-in account only
```
**Check** `<data root>/gsc/property.json` and `<data root>/gsc/performance/`.
**Limits** Search Console data lags by a few days. A property seen by two of your accounts is read
once. Without any login the script stops with a message and does nothing. The L1 is the shared kernel
`tools/cross-source/xs-l1-inventario.py`.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#gsc](../../docs/CONNECTING.md#gsc). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
