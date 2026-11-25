#!/usr/bin/env python3
""

































from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path














JOB_RAM_CAP_FALLBACK = 0.90




ARRIVAL_HORIZON_S = 3600.0



DUCKDB_FRACTION_OF_JOB = 0.60





MARGIN_BASE = 0.10
MARGIN_SLOPE = 0.25





STEP_INVARIANT = 0.10





SEG_OK = 0.50
SEG_ADMIT_MAX = 0.65
SEG_WARN = 0.70
SEG_YIELD = 0.80
SEG_CRITICAL = 0.90
SEG_PANIC = 1.00


CPU_HEADROOM_FRACTION = 0.30



EXIT_BUSY = 75

PAGE_SIZE = 16384





def _sysctl(name: str) -> int | None:
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return int(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        pass
    return None


def total_ram_bytes() -> int:
    ""
    v = _sysctl("hw.memsize")
    if v:
        return v
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        return 8 * 1024**3


def cpu_count() -> int:
    return os.cpu_count() or 4


def _vm_stat() -> dict[str, int]:
    ""
    if not shutil.which("vm_stat"):
        return {}
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return {}
    res: dict[str, int] = {}
    for line in out.stdout.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip().rstrip(".")
        if v.isdigit():
            res[k.strip()] = int(v)
    return res


@dataclass(frozen=True)
class Pressure:
    ""

    seg_ratio: float
    seg_total: int
    seg_limit: int
    free_bytes: int
    compressed_bytes: int
    available_bytes: int

    @property
    def level(self) -> str:
        if self.seg_ratio >= SEG_CRITICAL:
            return "critical"
        if self.seg_ratio >= SEG_WARN:
            return "warn"
        if self.seg_ratio >= SEG_OK:
            return "elevated"
        return "ok"

    @property
    def should_pause(self) -> bool:
        ""
        return self.seg_ratio >= SEG_WARN

    @property
    def should_abort(self) -> bool:
        return self.seg_ratio >= SEG_CRITICAL

    def __str__(self) -> str:
        return (
            f"segments {self.seg_ratio * 100:.0f}% [{self.level}] · "
            f"free {self.free_bytes / 1024**3:.1f} GB · "
            f"compressed {self.compressed_bytes / 1024**3:.1f} GB"
        )


def pressure() -> Pressure:
    ""
    tot = _sysctl("vm.compressor.segment.total") or 0
    lim = _sysctl("vm.compressor.segment.limit") or 0
    ratio = (tot / lim) if lim > 0 else 0.0

    vs = _vm_stat()
    page = PAGE_SIZE
    free = vs.get("Pages free", 0) * page
    speculative = vs.get("Pages speculative", 0) * page
    inactive = vs.get("Pages inactive", 0) * page
    compressed = vs.get("Pages occupied by compressor", 0) * page




    if vs:
        available = free + speculative + int(inactive * 0.5)
    else:

        available = int(total_ram_bytes() * 0.5)

    return Pressure(
        seg_ratio=ratio,
        seg_total=tot,
        seg_limit=lim,
        free_bytes=free,
        compressed_bytes=compressed,
        available_bytes=available,
    )




_RUSAGE_INFO_CURRENT = 2





_PHYS_FOOTPRINT_OFFSET = 9


def phys_footprint(pid: int) -> int | None:
    ""





    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.dylib", use_errno=True)
        buf = (ctypes.c_uint64 * 32)()
        rc = libc.proc_pid_rusage(
            ctypes.c_int(pid), ctypes.c_int(_RUSAGE_INFO_CURRENT), ctypes.byref(buf)
        )
        if rc != 0:
            return None
        return int(buf[_PHYS_FOOTPRINT_OFFSET])
    except (OSError, AttributeError, ValueError):
        return None


def self_footprint() -> int | None:
    return phys_footprint(os.getpid())


def descendants(pid: int) -> list[int]:
    ""




    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, OSError):
        return []
    children: dict[int, list[int]] = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            c, p = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(p, []).append(c)
    seen: list[int] = []
    stack = list(children.get(pid, []))
    while stack:
        cur = stack.pop()
        if cur in seen or cur == pid:
            continue
        seen.append(cur)
        stack.extend(children.get(cur, []))
    return seen


def tree_footprint(pid: int) -> int:
    ""
    total = phys_footprint(pid) or 0
    for child in descendants(pid):
        total += phys_footprint(child) or 0
    return total
















LEASE_DIR = DATA_ROOT_FALLBACK = Path.home() / ".sbk-data" / "runtime" / "leases"


def _proc_starttime(pid: int) -> str:
    ""

    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def machine_footprint() -> tuple[int, dict[int, int]]:
    ""





    try:
        out = subprocess.run(["ps", "-axo", "pid="], capture_output=True, text=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        return 0, {}
    per_pid: dict[int, int] = {}
    total = 0
    for tok in out.stdout.split():
        try:
            pid = int(tok)
        except ValueError:
            continue
        f = phys_footprint(pid)
        if f:
            per_pid[pid] = f
            total += f
    return total, per_pid


def _read_leases() -> list[dict]:
    ""


    if not LEASE_DIR.exists():
        return []
    out = []
    for f in LEASE_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (ValueError, OSError):
            f.unlink(missing_ok=True)
            continue
        pid = d.get("pid")
        if not isinstance(pid, int):
            f.unlink(missing_ok=True)
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            f.unlink(missing_ok=True)
            continue
        except PermissionError:
            pass
        out.append(d)
    return out


@dataclass(frozen=True)
class Shared:
    ""

    seg: float
    tax_frac: float
    margin_frac: float
    pool_frac: float
    n_leases: int
    quota_frac: float
    total_ram: int

    @property
    def pool_bytes(self) -> int:
        return int(self.total_ram * self.pool_frac)

    @property
    def quota_bytes(self) -> int:
        return int(self.total_ram * self.quota_frac)

    def __str__(self) -> str:
        return (
            f"seg {self.seg * 100:.0f}% · tax {self.tax_frac * 100:.0f}% "
            f"(sessions+app) · margin {self.margin_frac * 100:.0f}% · "
            f"pool {self.pool_frac * 100:.0f}% · {self.n_leases} job → "
            f"quota {self.quota_bytes / 1024**3:.1f} GB"
        )


def margin_for(seg: float) -> float:
    ""
    return min(0.60, MARGIN_BASE + MARGIN_SLOPE * max(0.0, seg))


@dataclass(frozen=True)
class Sessions:
    ""


    count: int
    avg_bytes: int
    total_bytes: int
    opened_last_hour: int

    @property
    def rate_per_hour(self) -> float:
        return float(self.opened_last_hour)


def _etime_seconds(e: str) -> int:
    e = e.strip()
    days = 0
    if "-" in e:
        d, _, e = e.partition("-")
        try:
            days = int(d)
        except ValueError:
            days = 0
    parts = []
    for tok in e.split(":"):
        try:
            parts.append(int(tok))
        except ValueError:
            return 0
    while len(parts) < 3:
        parts.insert(0, 0)
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def sessions() -> Sessions:
    ""






    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,etime=,command="], capture_output=True, text=True, timeout=15
        )
    except (subprocess.SubprocessError, OSError):
        return Sessions(0, 0, 0, 0)
    total = 0
    n = 0
    recent = 0
    for line in out.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, etime, cmd = parts
        if "/.local/bin/claude" not in cmd:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        fp = tree_footprint(pid)
        if fp <= 0:
            continue
        total += fp
        n += 1
        if _etime_seconds(etime) < ARRIVAL_HORIZON_S:
            recent += 1
    _record_demand(total, n)
    return Sessions(
        count=n, avg_bytes=(total // n if n else 0), total_bytes=total, opened_last_hour=recent
    )


DEMAND_HISTORY = LEASE_DIR.parent / "demand-history.jsonl"


DEMAND_WINDOW_S = 1800.0


def _record_demand(total_bytes: int, count: int) -> None:
    ""

    try:
        DEMAND_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        rows = []
        if DEMAND_HISTORY.exists():
            for line in DEMAND_HISTORY.read_text(errors="replace").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if now - float(r.get("t", 0)) <= DEMAND_WINDOW_S:
                    rows.append(r)
            if rows and now - float(rows[-1].get("t", 0)) < 30:
                return
        rows.append({"t": now, "b": total_bytes, "n": count})
        tmp = DEMAND_HISTORY.with_suffix(".tmp")
        tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        os.replace(tmp, DEMAND_HISTORY)
    except OSError:
        pass


def demand_trend() -> float:
    ""












    try:
        if not DEMAND_HISTORY.exists():
            return 0.0
        now = time.time()
        pts = []
        for line in DEMAND_HISTORY.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = float(r.get("t", 0))
            if now - t <= DEMAND_WINDOW_S:
                pts.append((t, float(r.get("b", 0))))
    except OSError:
        return 0.0
    if len(pts) < 3:
        return 0.0
    pts.sort()
    span = pts[-1][0] - pts[0][0]
    if span < 60:
        return 0.0

    n = len(pts)
    mt = sum(p[0] for p in pts) / n
    mb = sum(p[1] for p in pts) / n
    num = sum((p[0] - mt) * (p[1] - mb) for p in pts)
    den = sum((p[0] - mt) ** 2 for p in pts)
    if den <= 0:
        return 0.0
    return (num / den) * 3600.0


def job_cap() -> float:
    ""


















    R = total_ram_bytes()
    s = sessions()
    seg = pressure().seg_ratio
    margin = margin_for(seg)

    if not s.count:

        return max(0.05, 1.0 - margin - 0.15)


    reserve = s.avg_bytes / R



    trend = demand_trend()
    if trend > 0:
        reaction_h = max(60.0, check_interval(seg)) / 3600.0
        reserve += (trend * reaction_h) / R

    cap = 1.0 - margin - reserve
    return max(0.05, min(JOB_RAM_CAP_FALLBACK, cap))


def shared_state() -> Shared:
    ""

    R = total_ram_bytes()
    seg = pressure().seg_ratio
    total_fp, per_pid = machine_footprint()





    all_leases = _read_leases()
    leases = [lz for lz in all_leases if lz.get("state") == "active"]
    lease_fp = 0
    for lz in leases:
        pid = lz.get("pid")
        fp = per_pid.get(pid)
        if fp is None:
            fp = phys_footprint(pid) or 0



        lease_fp += max(fp, int(R * float(lz.get("grant_frac") or 0.0)))

    tax = max(0.0, (total_fp - lease_fp) / R)
    margin = margin_for(seg)










    p = pressure()
    granted = sum(float(lz.get("grant_frac") or 0.0) for lz in leases)
    available_frac = p.available_bytes / R if p.available_bytes else max(0.0, 1.0 - tax)
    pool = max(0.0, min(1.0 - tax, available_frac - margin - granted))

    n = len(leases)


    quota = min(job_cap(), pool / max(1, n + 1)) if pool > 0 else 0.0
    return Shared(
        seg=seg,
        tax_frac=tax,
        margin_frac=margin,
        pool_frac=pool,
        n_leases=n,
        quota_frac=quota,
        total_ram=R,
    )


def check_interval(seg: float | None = None) -> float:
    ""






    s = pressure().seg_ratio if seg is None else seg
    return max(1.0, min(60.0, 60.0 * (1.0 - s) ** 2))


def level_for(seg: float) -> str:
    ""
    if seg >= SEG_CRITICAL:
        return "G4-terminare"
    if seg >= SEG_YIELD:
        return "G3-cedere"
    if seg >= SEG_WARN:
        return "G2-spill"
    if seg >= SEG_OK:
        return "G1-ridurre"
    return "G0-pieno"


class Lease:
    ""















    def __init__(self, script: str, *, need_frac: float = 0.10, klass: str = "batch"):
        self.script = script
        self.need_frac = min(job_cap(), max(0.01, need_frac))
        self.klass = klass
        self.pid = os.getpid()
        self.path = LEASE_DIR / f"{self.pid}-{abs(hash(self.script)) % 10**6}.json"
        self.granted = False
        self._grant_frac = 0.0
        self._seq = 0.0


    def _write(self, state: str, grant: float) -> None:
        LEASE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": self.pid,
            "starttime": _proc_starttime(self.pid),
            "script": self.script,
            "class": self.klass,
            "state": state,
            "grant_frac": grant,
            "need_frac": self.need_frac,
            "seq": getattr(self, "_seq", 0.0),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self.path)

    def acquire(self) -> bool:
        ""








        st = shared_state()
        if st.seg >= SEG_ADMIT_MAX:
            return False


        self._seq = time.time()
        self._write("intent", self.need_frac)



        time.sleep(0.2 + (os.getpid() % 30) / 100.0)

        st = shared_state()
        if st.seg >= SEG_ADMIT_MAX:
            self.path.unlink(missing_ok=True)
            return False


        before = 0.0
        for lz in _read_leases():
            if lz.get("pid") == self.pid:
                continue
            if lz.get("state") == "active":
                before += float(lz.get("grant_frac") or 0.0)
            elif float(lz.get("seq") or 0.0) < self._seq:
                before += float(lz.get("need_frac") or 0.0)

        libero = max(0.0, st.pool_frac - before)


        if libero < self.need_frac * 0.25:
            self.path.unlink(missing_ok=True)
            return False

        self._grant_frac = min(self.need_frac, libero, job_cap())
        self._write("active", self._grant_frac)
        self.granted = True
        return True

    def registra(self, grant_frac: float) -> None:
        ""






        self._grant_frac = max(0.0, min(1.0, grant_frac))
        self._write("active", self._grant_frac)
        self.granted = True

    def release(self) -> None:
        self.path.unlink(missing_ok=True)
        self.granted = False

    def __enter__(self):
        return self if self.acquire() else None

    def __exit__(self, *exc):
        self.release()
        return False


    @property
    def grant_bytes(self) -> int:
        return int(total_ram_bytes() * self._grant_frac)

    def should_yield(self) -> bool:
        ""
        st = shared_state()
        if st.seg >= SEG_YIELD:
            return True
        mine = tree_footprint(self.pid)
        return mine > self.grant_bytes and st.seg >= SEG_WARN

    def level(self) -> str:
        return level_for(pressure().seg_ratio)

    def authorize(self, nbytes: int) -> bool:
        ""


        st = shared_state()
        if st.seg >= SEG_YIELD:
            return False
        if nbytes > st.pool_bytes * STEP_INVARIANT:
            return False
        return tree_footprint(self.pid) + nbytes <= self.grant_bytes





@dataclass(frozen=True)
class Budget:
    ""

    total_ram: int
    job_bytes: int
    duckdb_bytes: int
    threads: int
    pressure: Pressure



    @property
    def duckdb_memory_limit(self) -> str:
        ""
        gb = max(1, int(self.duckdb_bytes / 1024**3))
        return f"{gb}GB"

    @property
    def job_gb(self) -> float:
        return self.job_bytes / 1024**3

    def batch_rows(self, bytes_per_row: int, *, safety: float = 0.10) -> int:
        ""





        bytes_per_row = max(1, bytes_per_row)
        rows = int(self.job_bytes * safety / bytes_per_row)

        return max(10_000, min(rows, 5_000_000))

    def duckdb_settings(self) -> dict[str, str]:
        ""
        return {
            "memory_limit": self.duckdb_memory_limit,
            "threads": str(self.threads),



            "preserve_insertion_order": "false",
        }

    def __str__(self) -> str:
        return (
            f"budget: job {self.job_gb:.1f} GB · duckdb {self.duckdb_memory_limit} · "
            f"{self.threads} thread · RAM {self.total_ram / 1024**3:.0f} GB · {self.pressure}"
        )


def _memoria_minima_tranquillo() -> float:
    ""
    try:
        import impostazioni_pipeline

        return int(impostazioni_pipeline.leggi()["guardiano"]["memoria_minima"]) / 100
    except Exception:  # noqa: BLE001
        return 0.0


def budget(*, share: bool = True, job_fraction: float | None = None) -> Budget:
    ""














    total = total_ram_bytes()
    p = pressure()

    if not share:
        frac = job_fraction if job_fraction is not None else job_cap()
        job = int(total * frac)
    else:




        mine = next(
            (
                lz
                for lz in _read_leases()
                if lz.get("pid") == os.getpid() and lz.get("state") == "active"
            ),
            None,
        )
        if mine:
            frac = float(mine.get("grant_frac") or 0.0)
        else:
            st = shared_state()

            frac = st.quota_frac if st.n_leases else min(job_cap(), st.pool_frac)
        if job_fraction is not None:
            frac = min(frac, job_fraction)
        job = int(total * frac)






    if share and p.seg_ratio < SEG_OK:
        minimo = min(_memoria_minima_tranquillo(), job_cap())
        if job_fraction is not None:
            minimo = min(minimo, job_fraction)
        job = max(job, int(total * minimo))



    job = max(job, int(total * 0.02))

    cores = cpu_count()
    threads = max(1, int(cores * (1 - CPU_HEADROOM_FRACTION)))
    duck = int(job * DUCKDB_FRACTION_OF_JOB)


    threads = max(1, min(threads, max(1, duck // (1024**3))))

    return Budget(
        total_ram=total,
        job_bytes=job,
        duckdb_bytes=duck,
        threads=threads,
        pressure=p,
    )


def io_workers(*, per_worker_bytes: int = 8 * 1024**2) -> int:
    ""









    b = budget()
    da_memoria = int(b.job_bytes * 0.25 / max(per_worker_bytes, 1))

    if pressure().seg_ratio >= SEG_WARN:
        da_memoria //= 2
    return max(2, min(64, da_memoria))


def cpu_workers() -> int:
    ""



    return budget().threads


def configure_duckdb(con, *, b: Budget | None = None) -> dict[str, str]:
    ""
    b = b or budget()
    applied = {}
    for k, v in b.duckdb_settings().items():
        try:
            con.execute(f"SET {k}='{v}'" if not v.isdigit() else f"SET {k}={v}")
            applied[k] = v
        except Exception:  # noqa: BLE001 — unsupported setting: continue
            continue
    return applied


def wait_for_headroom(
    *,
    threshold: float = SEG_WARN,
    timeout_s: float = 900,
    poll_s: float = 10,
    on_wait=None,
) -> bool:
    ""





    deadline = time.monotonic() + timeout_s
    waited = False
    while True:
        p = pressure()
        if p.seg_ratio < threshold:
            return True
        if time.monotonic() >= deadline:
            return False
        if on_wait and not waited:
            on_wait(p)
            waited = True
        time.sleep(poll_s)


if __name__ == "__main__":
    st = shared_state()
    b = budget()
    p = b.pressure
    R = st.total_ram
    print("── SBK · dynamic shared resource budget ──")
    print(f"  Total RAM          : {R / 1024**3:.0f} GB · {cpu_count()} cores")
    print(
        f"  pressure (segments): {st.seg * 100:.1f}%  [{level_for(st.seg)}]"
        f"   {p.seg_total:,}/{p.seg_limit:,}"
    )
    print()
    print("  HOW THE MACHINE IS SHARED RIGHT NOW")
    print(
        f"    tax (sessions, Chrome, Docker, system)    : {st.tax_frac * 100:5.1f}%  "
        f"{st.tax_frac * R / 1024**3:6.1f} GB"
    )
    print(
        f"    safety margin (grows with danger)         : {st.margin_frac * 100:5.1f}%  "
        f"{st.margin_frac * R / 1024**3:6.1f} GB"
    )
    print(
        f"    pool distributable to jobs                : {st.pool_frac * 100:5.1f}%  "
        f"{st.pool_bytes / 1024**3:6.1f} GB"
    )
    print(f"    registered jobs (active leases)           : {st.n_leases}")
    sx = sessions()
    print()
    print("  INTERACTIVE SESSIONS (measured, not declared)")
    print(
        f"    open now: {sx.count}  ·  {sx.avg_bytes / 1024**3:.2f} GB each  ·  "
        f"{sx.total_bytes / 1024**3:.1f} GB total"
    )
    tr = demand_trend()
    verso = "rising" if tr > 0.5 * 1024**3 else ("falling" if tr < -0.5 * 1024**3 else "steady")
    print(
        f"    interactive demand: {verso}  ({tr / 1024**3:+.1f} GB/hour)"
        "   ← this is what counts, not how many sessions there are"
    )
    print(
        f"    DYNAMIC CAP for a job: {job_cap() * 100:.1f}%  "
        f"({job_cap() * R / 1024**3:.1f} GB)  ← not a constant: it drops as you open sessions"
    )
    print()
    print(f"  → quota for this job   : {b.job_gb:.1f} GB ({100 * b.job_bytes / R:.1f}% of RAM)")
    print(f"  → DuckDB               : {b.duckdb_memory_limit} on {b.threads} threads")
    print(f"  → batch at 200 B/row   : {b.batch_rows(bytes_per_row=200):,} rows")
    print(f"  → next check in        : {check_interval(st.seg):.0f} s")
    me = self_footprint()
    if me:
        print(f"  my footprint           : {me / 1024**2:.0f} MB")
    print()
    per_sessione_gb = (me / 1024**3) if me else 1.0
    print(f"  IF MORE SESSIONS OPEN (~{per_sessione_gb:.2f} GB each, from the current sample):")
    avail0 = p.available_bytes / R
    for extra in (0, 5, 13, 16):

        avail2 = max(0.0, avail0 - extra * per_sessione_gb * 1024**3 / R)
        pool2 = max(0.0, avail2 - st.margin_frac)
        q2 = min(job_cap(), pool2 / max(1, st.n_leases + 1))
        print(
            f"    +{extra:>2} sessions → available {avail2 * 100:4.1f}% · "
            f"pool {pool2 * 100:4.1f}% · job quota {q2 * R / 1024**3:4.1f} GB"
        )
