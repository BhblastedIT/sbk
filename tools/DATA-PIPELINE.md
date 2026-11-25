# Data Pipeline — overview

How data flows through SBK, from raw download to the knowledge layer. For the
source/plugin model see `docs/PLUGINS.md`. The data root is
`~/.sbk-data` unless you set `SBK_DATA_ROOT`.

## Levels

- **L0 — download.** Each source pulls its raw data into
  `<data root>/<source>/raw/`. Nothing is interpreted yet.
- **L1 — normalize/enrich.** Raw records are normalized and enriched into
  `<data root>/enriched/`. A source without L1 is not really ingested.
- **L2 — cross-source knowledge extraction.** Records from all enabled sources
  are combined; entities and facts are extracted.
- **L3 — knowledge layer / coverage.** Entity resolution and the living knowledge
  layer, plus coverage reporting.

## Running it

Always inspect the plan first, then run:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run     # plan only
uv run python tools/cross-source/xs-pipeline-run.py --ingest            # L1, L2, L3, free stages only
uv run python tools/cross-source/xs-pipeline-run.py --all               # the whole chain, paid stages included
uv run python tools/cross-source/xs-pipeline-run.py --propagate         # L2 and L3 from the snapshot on disk
uv run python tools/cross-source/xs-pipeline-run.py --rebuild           # L2 and L3 with every stage forced
```

None of them downloads. The L0 download of every source in the registry is
`uv run python tools/cross-source/xs-l0-refresh.py` (`--dry-run` shows the plan, `--then-ingest` runs
`--ingest` after it).

## Rule

A run that skips a stage reports what it skipped.
