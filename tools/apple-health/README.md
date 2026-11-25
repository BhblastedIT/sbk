<!-- generated from docs/CONNECTING.md -->
# Apple Health (`ah-`)

**Status** partial: downloads and processes, but no kernel stage reads its output yet. Not in the registry.
**Reads** the export of the Health app on your iPhone.
**You need** the export zip.
**Create it** In the Health app, tap your profile picture → *Export All Health Data*. You get
`export.zip`; move it to your computer.
**Where the code looks** the newest `*.zip` in `<data root>/apple-health/imports/`
(`find_latest_zip` in `tools/apple-health/ah-l0-import.py`), or the file you pass with `--file <zip>`.
**sbk.config.json** none.
**Download**
```bash
uv run python tools/apple-health/ah-l0-import.py
uv run python tools/apple-health/ah-l1-process.py     # the pipeline does not run this step
```
**Check** `<data root>/apple-health/processed/metrics.parquet`.
**Limits** Health data, kept on your machine. Nothing in this repo reads `metrics.parquet` downstream.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#apple-health](../../docs/CONNECTING.md#apple-health). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
