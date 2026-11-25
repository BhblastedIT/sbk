<!-- generated from docs/CONNECTING.md -->
# DocuSign (`ds-`)

**Status** mature · registry `periodica` (periodic), every 30 days.
**Reads** envelopes, signers and signed documents of your DocuSign account.
**You need** a DocuSign app of your own with the JWT grant: its integration key, an RSA key pair,
your API user ID and, if you belong to more than one account, the account ID. Freemium accounts have
no API access (registry note).
**Create it** In DocuSign, open *Apps and Keys*: create an app, generate an RSA key pair and save the
private key as `~/.sbk-data/secrets/docusign-private.key` with permissions 600 (another path goes in
`DOCUSIGN_PRIVATE_KEY_PATH`; this default does not follow `SBK_DATA_ROOT`). Add the redirect URI
`http://localhost:8765/docusign/callback` (or your own, in `DOCUSIGN_REDIRECT_URI`). Copy the
integration key, your API user ID and the account ID into `.env`. Then give your consent once:
```bash
uv run python tools/docusign/ds-l0-api.py --consent-url    # open the printed URL and accept
```
**Where the code looks** env first, then the Keychain (`_cred` in `tools/docusign/ds-l0-api.py`):
`DOCUSIGN_INTEGRATION_KEY` or `sbk-docusign/integration-key`, `DOCUSIGN_USER_ID` or
`sbk-docusign/user-id`, `DOCUSIGN_ACCOUNT_ID` or `sbk-docusign/account-id` (optional: without it the
default account of your user is read). Key file at `DOCUSIGN_PRIVATE_KEY_PATH`.
`DOCUSIGN_AUTH_HOST` defaults to `account.docusign.com` (production).
**sbk.config.json** none.
**Download** (this script does not load `.env` by itself: export it first, see
[Before you start](../../docs/CONNECTING.md#before-you-start))
```bash
uv run python tools/docusign/ds-l0-api.py --dry-run     # token, user, envelope count, writes nothing
uv run python tools/docusign/ds-l0-api.py
uv run python tools/docusign/ds-l0-api.py --since 2026-01-01
```
**Check** `<data root>/docusign/raw/envelopes-api.json` and `<data root>/docusign/contracts-metadata.json`;
after `--ingest`, `<data root>/docusign/processed/contacts-docusign.parquet`.
**Limits** The app asks the scopes `signature impersonation`: with the JWT grant the app acts as your
own user, after your consent. `DOCUSIGN_API_BASE` and `DOCUSIGN_FROM_DATE` are read only by the older
scraper `ds-l0-scrape.py`, which is not part of this path.
**Alternative, an MCP server** Docusign runs its own Docusign MCP Server (the URL and sign-in for your
environment are on the vendor page), with your own Docusign account ([Using an MCP
server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent look up your envelopes live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#docusign](../../docs/CONNECTING.md#docusign). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
