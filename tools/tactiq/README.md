<!-- generated from docs/CONNECTING.md -->
# Tactiq (`tq-`)

**Status** mature · registry `continua`, every 14 days.
**Reads** the meeting transcripts of your Tactiq account, including meetings shared with you
(`--no-shared` for your own only).
**You need** macOS, Google Chrome logged in to the Tactiq web app (`app.tactiq.io`) with your account,
and the Firebase web API key that the Tactiq web app itself uses.
**Create it** The key is public: it is the `key=` parameter of the requests the Tactiq web app sends
to `securetoken.googleapis.com` (Chrome → Developer tools → Network, with `app.tactiq.io` open).
Put it in `.env` as `TACTIQ_FIREBASE_API_KEY`.
**Where the code looks**
- default mode: runs JavaScript in your open Tactiq tab through AppleScript
  (`chrome_js` in `tools/tactiq/tq-l0-download.py`); in Chrome, allow *View → Developer → Allow
  JavaScript from Apple Events*. A still-valid session needs no key; an expired one is refreshed
  with `TACTIQ_FIREBASE_API_KEY`.
- `--direct`: reads the refresh token from Chrome's storage for the Tactiq site
  (`~/Library/Application Support/Google/Chrome/<profile>/IndexedDB/`), exchanges it with
  `TACTIQ_FIREBASE_API_KEY`, and keeps a copy in the Keychain entry `sbk-tactiq/refresh-token`,
  used when Chrome's copy has expired.
**sbk.config.json** none.
**Download** (this script does not load `.env` by itself: export it first, see
[Before you start](../../docs/CONNECTING.md#before-you-start))
```bash
uv run python tools/tactiq/tq-l0-download.py
uv run python tools/tactiq/tq-l0-download.py --direct     # without AppleScript
uv run python tools/tactiq/tq-l0-download.py --verify     # completeness check
```
**Check** `<data root>/tactiq/raw/_meeting_index.json` and one `.json` + `.txt` per meeting; after
`--ingest`, `<data root>/tactiq/processed/contacts-tactiq.parquet`.
**Limits** macOS and Chrome only. When the same call exists in Attio and in Tactiq, the Attio
transcript takes precedence.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#tactiq](../../docs/CONNECTING.md#tactiq). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
