---
name: pipeline
description: The SBK data pipeline is judged WHOLE, never in pieces — the four commands (--all, --ingest, --propagate, --rebuild) and what each one does NOT do, the paid stages, the real proof that a stage actually ran, and the per-source freshness check (/pipeline). Invoke before running, reporting on, or judging a pipeline run, when talking about completion percentages, or when asked for the state of the sources.
---

# SBK pipeline — judged whole, and its state is generated

> This skill describes the method. State is NOT written here: generate it with the commands at the end.

## 1. The pipeline is judged as a whole

A pipeline run can report every step done and a large count of facts and still be wrong in two ways
at once. First, a step can die silently (out of memory, timeout) and still be closed as "complete".
Second, the stages behind a paid flag can be skipped *by construction* — and those are the ones that
produce the semantic part: facts extracted from text, relationships, the names that emerge from a
meeting, the people who connect to other people. Those can stay stale while the tally says
"complete". So the chain is judged together, not one piece at a time.

The practical consequences, always valid:

- **No completion percentage without stating the denominator.** "N of N done" can be true of the
  free pipeline and false of the full chain.
- **A run that skips a step is not a complete run**, even if it exits OK. Whatever was skipped is
  named, every time, together with the reason.
- **KB quality metrics are not read after a partial run**: half of the material that determines them
  did not pass, and the numbers lie in both directions.
- **A paid step is a stop for the user**, but the plan always accounts for it; you never design one
  piece of the chain while pretending the other does not exist.

Whether something is running or blocked right now is a **state**, not part of this method: ask the
machine (`tools/util/sb-pipeline-ctl.py status`, `xs-pipeline-run.py --all --dry-run`), not this skill.

## 2. The commands are four and the name states the scope

Contract between the commands. `xs-pipeline-run.py --help` lists the names it accepts.

```bash
uv run python tools/cross-source/xs-pipeline-run.py --all             # the WHOLE chain, paid stages included; asks for spend consent
uv run python tools/cross-source/xs-pipeline-run.py --ingest          # free L1+L2+L3; paid stages stay OUT and the plan names them
uv run python tools/cross-source/xs-pipeline-run.py --propagate       # incremental L2+L3: propagates the snapshot already on disk; reads neither L0 nor L1
uv run python tools/cross-source/xs-pipeline-run.py --rebuild         # L2+L3 rebuilt: facts without incremental, cited people and fact index forced; the
                                                                       # search index and event log are updated and not discarded; never L1, never L0, never paid stages
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run   # the plan without executing, PAID stages marked
```

What they do NOT do:

- `--propagate` and `--rebuild` **never run L1**: with L1 stalled they close "OK" without a single
  new fact (new facts only enter through L1).
- ⚠️ **None of the four commands fetch L0**, not even `--all`: the L1 scripts read the L0 files
  already on disk, and every run prints at the top how old L0 is, source by source. **The L0 pass is
  `tools/cross-source/xs-l0-refresh.py`.** A "full run" is `xs-l0-refresh.py --then-ingest`: every
  live source in sequence, a few attempts each, then a KB backup and `--ingest` (paid stages stay
  out). `--dry-run` shows the plan; per-run outcomes land in an `esiti.tsv` (outcomes) file in the
  run's folder; manual sources are named with the reason. `xs-l0-refresh.py --check` and
  `tests/test_registry_scripts.py` fail if a live source is left out of the pass and not declared
  manual.
- The **paid stages** (knowledge extract and deep analysis: model calls, hours of run time) only run
  inside `--all` (`xs-pipeline-run.py --help`). Paid steps charge against your
  `ANTHROPIC_API_KEY`, in batches, with an estimate and your consent first.

## 3. Proof that a stage actually ran

- Proof that **semantic** extraction ran is NOT `last-extraction.json` on its own: it advances even
  for partial free extractions (check its `sources` field). The real proof is the **timestamp of the
  paid outputs**: `ls -l ~/.sbk-data/l3/nlp/entities.parquet ~/.sbk-data/l3/nlp/deep-facts.parquet`.
- Birthdays and name-days (stages `l2_ricorrenze` and `l3_calendario_ricorrenze`): the proof is
  `~/.sbk-data/knowledge/meta/ricorrenze-stadio.json` being newer than
  `~/.sbk-data/knowledge/meta/last-extraction.json`, plus the calendar in
  `~/.sbk-data/knowledge/meta/ricorrenze-calendario-stadio.json`. The check is
  `tools/cross-source/xs-l2-birthdays.py --check`, proven with `--self-test` (break it on
  purpose and see it fail).
- Harmless skips: `Pipeline Complete` (exit 0) still counts in brackets the skips that do not count
  against a run, unchanged, resumed, `not in enabled_sources` and `nothing to read yet` (a first
  install: an L1 source with no folder under the data root, or a stage whose input nothing has
  produced yet). Every other skip makes the run INCOMPLETE (exit 2) and is named with its reason.
- "success" counts in the metrics include dry-runs; a run that exits 0 with the KB unchanged is
  labelled INCOMPLETE (exit 2).
- A run is reported with: the command launched, steps executed / skipped (with reason), paid stages
  yes/no, and the timestamp of the paid outputs.
- Memory, leases, `job_cap`, `demand_trend`, `exit(75)`, why SIGSTOP is wrong: skill `infra-memoria`.

## 4. /pipeline — source freshness check

Check the freshness of every SBK data source. First of all:

```bash
uv run python tools/cross-source/xs-pipeline-run.py --all --dry-run   # "L0 age" section: how old each L0 is; closed sources say so
uv run python tools/cross-source/xs-l0-refresh.py --dry-run           # which sources the L0 pass downloads, and the manual ones with the reason
uv run python tools/util/sb-pipeline-ctl.py status                    # what is running now, how heavy
```

Then, for what the commands do not cover:

1. **Read the config**: `tools/sbk_config.py` for the source paths (which ones: `ls -d ~/.sbk-data/*/`)
2. **Check each L0 source**: last modified file, number of records/files, days since last update
3. **Check L1/L2**: freshness of the files in `enriched/` and `exports/`
4. **Check L3**: vector index, knowledge graph, digest, NLP (`~/.sbk-data/l3/`)
5. **Check the Knowledge Layer**: freshness of the profiles in `~/.sbk-data/knowledge/entities/`

### Output

Summary table:

```
| Source      | L0 Records | L0 Last Update | L1 Status | Stale?   |
|-------------|-----------|----------------|-----------|----------|
| Mail        | …         | YYYY-MM-DD     | OK        | No       |
| Chat        | …         | YYYY-MM-DD     | OK        | N days   |
```

Then:
- **STALE** (past the threshold for the nature declared in the registry `tools/sorgenti.py`; a closed
  source is not "late"): list with the command to update
- **FRESH**: count only
- **Suggestion**: which source to update first and why

### Rules
- Do not launch scripts automatically, only show the commands (paid stages are a stop for the user)
- Flag any source that needs a manual action (an open browser tab, an OAuth refresh)
- No number in this skill is a fact: counts are generated every time
