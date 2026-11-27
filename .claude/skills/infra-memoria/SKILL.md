---
name: infra-memoria
description: How to claim memory on a single shared machine without crashing it — a budget shared across sessions and jobs, file-based leases, job_cap and demand_trend, exit(75), why SIGSTOP is the wrong way to pause, DuckDB memory_limit, on-demand pipeline. Invoke before writing or launching code that processes large data, before heavy parallel work, or when reasoning about the pipeline, RAM, and machine stability.
---

# Memory budget and stability — operational detail

> This skill describes the method, not live facts. Numbers and current state are not written here: generate them with the commands below.

## Why memory needs managing

On a workstation running the kernel, a runaway process can take the whole machine down. The failure
mode on macOS is specific and worth knowing before you write code that touches large data:

1. **macOS does not kill the offending process.** It compresses and swaps until the machine dies.
   There is no OOM killer that saves you, so the guard has to be built in application code.
2. **`ulimit`, `RLIMIT_AS`, launchd `HardResourceLimits`, `taskpolicy -m` do NOT work** on macOS:
   they are accepted and silently ignored. Never rely on them.
3. **`ps` RSS underestimates real usage** (it ignores compressed memory). Measure `phys_footprint`,
   not RSS.
4. **The single early-warning metric is** `vm.compressor.segment.total / .limit` — the compressor's
   "% of segments limit", which climbs well before pressure or swap figures do. `free %`, "memory
   pressure" and swap-used are noise by comparison.

## Tools (use these, do not reinvent them)

```bash
uv run python tools/sbk_resources.py               # dynamic budget for THIS machine
uv run python tools/util/sb-pipeline-ctl.py status # what is running, how heavy, current pressure
uv run python tools/util/sb-pipeline-ctl.py check  # did anything stay running?
(cd dashboard && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000)  # on-demand dashboard
```

**`tools/sbk_resources.py` is the single source of the limits.** Never hardcode megabytes: it
exposes everything as a **percentage of the machine**, recomputed at every start, so the same code
holds on a small laptop and on a large workstation. A heavy script calls `budget()` and respects its
`job_bytes` / `duckdb_settings()` / `batch_rows()`.

## The budget is SHARED across sessions and jobs

A single workstation can run many interactive sessions at once, each with a non-trivial memory
footprint (the full process tree, child MCP servers included). When several of those run together
they can take most of the machine's RAM on their own, which means a per-process budget is useless:
four jobs each claiming a quarter add up to the whole machine, and that is exactly the scenario that
triggers a crash.

How the shared budget works, and **what is NOT a fixed number**:

- **File-based lease registry** (`<data root>/runtime/leases/`, `~/.sbk-data/` by default), no daemon: a guardian process would
  die in exactly the window where it is needed, a file does not. Lazy reaping with `kill(pid, 0)`:
  a crash leaves no phantom reservations.
- **The tax is computed by subtraction**: anything without a lease is tax — sessions, the browser,
  containers, the OS, the runaway process nobody predicted. No name list to keep updated, and the
  number of concurrent consumers is discovered at runtime without anyone declaring it.
- **The per-job cap is NOT a constant**: `job_cap()` computes it as `1 − margin(pressure) − reserve`,
  where the reserve is *the cost of one more session* (it must always be possible to open another
  terminal immediately) plus *the observed growth* of interactive demand. A fixed cap leaves large
  amounts of RAM unused on an idle machine.
- **Trend matters, not the count of sessions**: `demand_trend()` reads the derivative of demand over
  a rolling window (linear regression over a ring history in `demand-history.jsonl`). Many idle
  sessions and few idle sessions yield the same cap; the cap only tightens *while* demand is
  actually rising and reopens on its own as soon as it stops. Counting opens instead of the trend is
  wrong: it never sees the closes and strangles on a transient spike.
- **Two-phase admission with a queue ticket**: only intents *older* than yours are counted. Without
  this rule several simultaneous jobs all back off together (livelock).
- **`Lease.authorize(nbytes)` is synchronous with the spend**, not with a timer: no single
  allocation beyond ~10% of the fresh pool. This is the only way to stop a process that jumps from
  0 to many GB between two periodic checks.
- **Checks get more frequent under load**: `check_interval(seg) = clamp(1, 60·(1−seg)², 60)` s —
  tens of seconds at rest, close to one second near the limit. Never a fixed cadence.
- **`exit(75)`** (`EXIT_BUSY`) is the canonical way to stand down: distinguishable from an error, so
  a wrapper can relaunch. ⚠️ **SIGSTOP as a parking mechanism is wrong**: frozen pages cool down,
  the compressor eats them, and pressure *rises*. It only survives as a bridge of a few seconds
  before termination.

**DuckDB**: without an explicit `memory_limit` it takes ~80% of RAM per connection. Always use
`configure_duckdb(con)`.

## What starts on its own and how to switch it off

Long-running, always-on services (dashboard, monitor) are off at startup and run only when you start
them. The reasoning: on a shared workstation the RAM is contended with interactive sessions. Some jobs
can still start on their own, and you can switch them off. The channels that can start jobs on their
own are the event bus (the next step after a download), the
monitor, and the scheduler in the dashboard (only the intervals set on its pipeline page, all off at
first). `sb-pipeline-ctl.py off` switches automatic cascades off: the event bus and the dashboard
scheduler then start nothing, and queued events are kept. `sb-pipeline-ctl.py on` switches automatic
cascades on again; the switch is the file `<data root>/CASCADES_OFF`, and cascades are on unless it
exists. Run the chain explicitly with the pipeline runner (see the `pipeline` skill).

| What | Why it is off at startup | How to start it |
|---|---|---|
| Dashboard | holds several GB fixed (vector store + local model) | `cd dashboard && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| Monitor | ingestion engine: polls sources on a schedule; every job that sends data to a model (new-mail triage, pre-meeting briefs, morning digest, meeting capture, DLQ retries of model scripts) runs only with `SBK_MONITOR_MODEL=1` or `--with-model` | `uv run python tools/monitoring/sbk-monitor.py` |

⚠️ **Consequence to know and to state when relevant**: with the monitor off, **the knowledge base
does not update itself** — messages, mail and calendar stay at the last run. Before answering
questions about communications or relationships, check data freshness
(`sb-pipeline-ctl.py status`) and, if needed, run the monitor or the pipeline by hand.

For memory, leases, `job_cap`, `demand_trend`, `exit(75)` and why SIGSTOP is wrong as applied to the
data pipeline, see the `pipeline` skill.
