<!-- generated from docs/CONNECTING.md -->
# Plaud recorder (`pl-`)

**Status** mature · registry `continua`, every 7 days.
**Reads** recordings, transcripts and summaries of your Plaud recorder account.
**You need** macOS with the Plaud desktop app installed and logged in to your account at least once.
Node.js (`npm`) only for the fallback path below.
**Create it** Nothing to create: SBK reuses the session of your Plaud desktop app.
**Where the code looks** The session token of the Plaud desktop app, read locally
(`tools/plaud/pl_auth_refresh.py`); SBK keeps a copy in `~/.sbk-data/secrets/plaud-wt.json`
(fixed path, it does not follow `SBK_DATA_ROOT`). If that fails, it decrypts the app's storage
(`~/Library/Application Support/Plaud/encryption.json`) with an Electron helper in
`tools/plaud/electron-decrypt/` (installs Electron with `npm` on first use), using the Keychain entry
the Plaud app creates for itself (`Plaud Safe Storage` / `Plaud Key`). You do not add any key.
**sbk.config.json** `plaud.api_base`: the API host of your account's region, default
`https://api-euc1.plaud.ai` (EU); the env variable `SBK_PLAUD_API_BASE` wins.
**Download**
```bash
uv run python tools/plaud/pl-l0-download.py --dry-transcriptions   # how many transcriptions it would request, calls nothing
uv run python tools/plaud/pl-l0-download.py --no-transcribe        # download only, request no transcription
uv run python tools/plaud/pl-l0-download.py
```
**Check** `<data root>/plaud/raw/_file_index.json` and the recording files in `<data root>/plaud/raw/`.
**Limits** By default each run also asks Plaud to transcribe the recordings that have no
transcription yet (recordings of at least 40 seconds, up to 1,200 minutes a day), as the app's
*Auto generation* does: this uses the transcription minutes of your Plaud plan. The defaults live in
`<data root>/system/pipeline-settings.json`, section `plaud` (`transcribe`, `min_seconds`,
`minutes_per_day`, defined in `tools/impostazioni_pipeline.py`, and
`uv run python tools/impostazioni_pipeline.py` prints every setting in force); `--transcribe` /
`--no-transcribe` override them for one run. macOS only. `--chrome` is an older mode that reads through an open
plaud.ai tab in Chrome. The speaker analysis in the pipeline (`tools/plaud/pl-analyze-speakers.py`) recognises
you from `owner`, `own_names` and `own_emails` in `sbk.config.json`. If you move the data root, also set `SBK_DATA` to the same folder: the Plaud
speaker-naming helpers (`pl_lotto.py`, `pl_quadro.py`, `pl_lunghe.py`, `pl_dettagli.py`,
`pl_quadro_pagina.py`, `regole/*.py`) read that variable, not `SBK_DATA_ROOT`.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#plaud](../../docs/CONNECTING.md#plaud). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
