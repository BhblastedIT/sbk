<!-- generated from docs/CONNECTING.md -->
# Clinical documents (`cl-`)

**Status** partial: read only by the dashboard's Performance view. Not in the registry.
**Reads** clinical documents you add yourself (PDF or image): blood tests, visits, vaccinations,
allergies, medications, ECG, imaging (`VALID_TYPES` in `tools/clinical/cl-l0-ingest.py`).
**You need** the documents, plus two API keys for the parsing step: `DEEPSEEK_API_KEY` and
`ANTHROPIC_API_KEY` in `.env`.
**Where the code looks** the files you pass with `--file` or `--batch <folder>`; the parsing step reads
`<data root>/clinical/incoming/`.
**sbk.config.json** none of its own. `--subject` is a label for the person the documents belong to.
Its default is your `owner` from `sbk.config.json`, in lower case, and the dashboard's Performance view
shows that subject. Pass `--subject <label>` for documents of someone else. Without an `owner` the
scripts ask for `--subject`.
**Download**
```bash
uv run python tools/clinical/cl-l0-ingest.py --file report.pdf --type blood_test --date 2026-01-31 --subject <label>
uv run python tools/clinical/cl-l1-parse.py         # the pipeline does not run this step
uv run python tools/clinical/cl-alerts.py --subject <label>
```
**Check** `<data root>/clinical/processed/values.parquet` and `alerts.json`.
**Limits** **The documents leave your machine during parsing.** `cl-l1-parse.py` sends the extracted
text to the DeepSeek API, and images, or texts under 100 characters, to the Anthropic API. Decide
before you run it whether that is acceptable for your data. Without the keys, the parsing stops with
an error and nothing is sent.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#clinical](../../docs/CONNECTING.md#clinical). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
