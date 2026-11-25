<!-- generated from docs/CONNECTING.md -->
# WHOOP (`wp-`)

**Status** partial: read only by the dashboard's Performance view, not by the knowledge layer ·
registry `continua`, every 7 days.
**Reads** recovery, sleep, cycles (strain), workouts of your WHOOP account.
**You need** a WHOOP developer app of your own (OAuth2).
**Create it** In the WHOOP developer dashboard create an app with the redirect URI
`http://localhost:8000/oauth/whoop/callback` and the scopes
`offline read:recovery read:sleep read:workout read:cycles read:profile`
(`tools/whoop/wp-l0-auth.py`). Copy its client ID and secret.
**Where the code looks** `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET` in `.env`, otherwise the Keychain
entries `sbk-whoop/client-id` and `sbk-whoop/client-secret`. The login stores your tokens in
`sbk-whoop/access-token` and `sbk-whoop/refresh-token`.
**sbk.config.json** none.
**Download**
```bash
uv run python tools/whoop/wp-l0-auth.py          # browser login, local callback on port 8000
uv run python tools/whoop/wp-l0-download.py --full
uv run python tools/whoop/wp-l0-download.py      # afterwards: the last 7 days (--days N)
```
**Check** `<data root>/whoop/raw/`; after `--ingest`, `<data root>/whoop/processed/daily.parquet`.
**Limits** Physiological data. Port 8000 must be free during the login. In container mode
(`SBK_CONTAINERIZED=1`) the login cannot store the tokens, so run it outside a container.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#whoop](../../docs/CONNECTING.md#whoop). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
