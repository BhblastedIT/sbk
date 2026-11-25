<!-- generated from docs/CONNECTING.md -->
# Personio, HR tool (`pe-`)

**Status** mature · registry `periodica`, every 7 days · **an organisation HR source that needs
admin rights in Personio.** Unlike the other plugins it does not read only your own data: it reads
your organisation's HR records, for everyone the credentials can see.
**Reads** employee records, absences and balances, employments (contract history), documents,
compensations, recruiting.
**You need** Personio API credentials (client ID and secret) with read access. Only a Personio
account with admin rights can create them: you are an admin of your organisation's Personio, or an
admin creates them for you.
**Create it** In Personio's API credentials settings, generate a client ID and secret and grant read
access to the attributes you want.
**Where the code looks** `PERSONIO_CLIENT_ID` and `PERSONIO_CLIENT_SECRET` in `.env`, otherwise the
Keychain entries `sbk-personio/client-id` and `sbk-personio/client-secret`
(`tools/personio/pe-l0-download.py`).
**sbk.config.json** none.
**Download**
```bash
uv run python tools/personio/pe-l0-download.py --dry-run
uv run python tools/personio/pe-l0-download.py
```
**Check** `<data root>/personio/employees-flat.json`; after `--ingest`,
`<data root>/personio/processed/employees.parquet`.
**Limits** HR data of other people, including compensation: it stays on your machine; decide with
your organisation who may run it and which attributes the credentials expose.
Attendance records are not downloaded.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#personio](../../docs/CONNECTING.md#personio). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
