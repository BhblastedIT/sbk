<!-- generated from docs/CONNECTING.md -->
# LinkedIn (`li-`)

**Status** mature · registry `a_richiesta` (on request), every 30 days.
**Reads** your connections, invitations, endorsements received and given, company follows, positions,
skills and profile, from LinkedIn's data export of your own account.
**You need** the export of your LinkedIn data. No token, no app.
**Create it** In LinkedIn, open Settings → Data privacy → *Get a copy of your data* and request the
archive. LinkedIn sends you an email when it is ready; download the zip and unzip it into
`<data root>/linkedin/raw/export-part1/`. Another folder name under `<data root>/linkedin/raw/` works
too: pass it with `--source <folder>`.
**Where the code looks** the CSV files of the export in that folder: `Connections.csv`,
`Invitations.csv`, `Endorsement_Received_Info.csv`, `Endorsement_Given_Info.csv`,
`Company Follows.csv`, `Positions.csv`, `Skills.csv`, `Profile.csv`
(`tools/linkedin/li-l0-import-export.py`, `main()`). A file that is missing from your export is skipped.
**sbk.config.json** none for the export. Optional `linkedin.own_urn`, only for the browser scripts
(see Limits).
**Download**
```bash
uv run python tools/linkedin/li-l0-import-export.py --dry-run   # counts only, writes nothing (no files, no last-runs.json, no metrics)
uv run python tools/linkedin/li-l0-import-export.py
```
**Check** `<data root>/linkedin/raw/export-connections.parquet`; after `--ingest`,
`<data root>/linkedin/processed/contacts-linkedin.parquet`.
**Limits** The export is the connection path. The folder also holds browser scripts
(`li-l0-scraper.js`, `scripts/`) with a safety module (`li_safety.py`): they are not part of this
path and this guide does not set them up; the registry asks to respect the provider's rate limits.
If you ever run them, they too write under `<data root>/linkedin/raw/` (their session file
`linkedin-session.json` included), never in the repo or the current folder. They tell your messages
apart by your own member id, read from LinkedIn for your own login; to fix it, set
`"linkedin": {"own_urn": "ACoA..."}` in `sbk.config.json` (the id at the end of your profile URN) or
`SBK_LINKEDIN_OWN_URN`. There is nothing to edit in the scripts.
The pipeline status table (`tools/cross-source/xs-util-pipeline-status.py`) shows the rows of those
cookie-based scripts only when `linkedin` is in `enabled_sources`. The dashboard's LinkedIn download
runs the export importer above.
In the knowledge layer LinkedIn enriches people SBK already knows and does not create new ones
(`LINKEDIN_CONIA_NUOVI = False` in `tools/cross-source/xs-l2-knowledge-extract.py`). With only LinkedIn
connected, `--ingest` says `Nothing to merge yet` and the knowledge stays empty
([A first run](../../docs/CONNECTING.md#after-a-download)).

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#linkedin](../../docs/CONNECTING.md#linkedin). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
