""



















from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("sbk-registry.schema")

MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"


VALID_STATES = ("off", "shadow", "canary", "on", "paused", "deprecated")


RUNNABLE_STATES = frozenset({"shadow", "canary", "on"})



KNOWN_ADAPTER_TYPES = frozenset(
    {
        "official-api",
        "official-cli",
        "sanctioned-export",
        "reverse-eng",
        "manual-export",
        "local",
    }
)


VALID_BACKENDS = frozenset({"subprocess", "python-module", "external"})


class JobManifestError(ValueError):
    ""


@dataclass
class JobManifest:
    ""






    job_id: str
    cmd: str
    args: list[str] = field(default_factory=list)
    timeout_s: int = 1800
    lock: str = ""
    paid: bool = False
    cadence_minutes: int = 0
    night_ok: bool = False
    cascade: bool = False
    state: str = "off"
    owner_area: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    backend: str = "subprocess"
    fragile: bool = False
    forbidden_adapter_types: list[str] = field(default_factory=list)
    campaign: str | None = None
    perimeter: str | None = None
    cwd: str = ""
    description: str = ""

    @property
    def runnable(self) -> bool:
        ""
        return self.state in RUNNABLE_STATES


def _validate(job_id: str, raw: dict) -> JobManifest:
    if not isinstance(raw, dict):
        raise JobManifestError(f"{job_id}: manifest is not a YAML mapping")
    if raw.get("job_id") != job_id:
        raise JobManifestError(
            f"{job_id}: field 'job_id' ({raw.get('job_id')!r}) != file name ({job_id!r})"
        )
    for req in ("cmd", "state"):
        if req not in raw:
            raise JobManifestError(f"{job_id}: missing required field {req!r}")

    cmd = raw["cmd"]
    if not isinstance(cmd, str) or not cmd.strip():
        raise JobManifestError(f"{job_id}: 'cmd' must be a non-empty string")

    args = raw.get("args", []) or []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise JobManifestError(f"{job_id}: 'args' must be a list of strings")

    state = raw["state"]
    if state not in VALID_STATES:
        raise JobManifestError(
            f"{job_id}: invalid state {state!r}. Allowed: {', '.join(VALID_STATES)}"
        )

    timeout_s = int(raw.get("timeout_s", 1800))
    if timeout_s <= 0:
        raise JobManifestError(f"{job_id}: 'timeout_s' must be > 0 (was {timeout_s})")

    cadence = int(raw.get("cadence_minutes", 0))
    if cadence < 0:
        raise JobManifestError(f"{job_id}: 'cadence_minutes' cannot be negative")

    backend = raw.get("backend", "subprocess")
    if backend not in VALID_BACKENDS:
        raise JobManifestError(
            f"{job_id}: invalid backend {backend!r}. Allowed: {', '.join(sorted(VALID_BACKENDS))}"
        )

    forbidden = raw.get("forbidden_adapter_types", []) or []
    if not isinstance(forbidden, list):
        raise JobManifestError(f"{job_id}: 'forbidden_adapter_types' must be a list")
    bad = set(forbidden) - KNOWN_ADAPTER_TYPES
    if bad:
        raise JobManifestError(
            f"{job_id}: unknown forbidden_adapter_types: {', '.join(sorted(bad))}"
        )

    artifact_refs = raw.get("artifact_refs", []) or []
    if not isinstance(artifact_refs, list):
        raise JobManifestError(f"{job_id}: 'artifact_refs' must be a list")

    return JobManifest(
        job_id=job_id,
        cmd=cmd,
        args=list(args),
        timeout_s=timeout_s,
        lock=str(raw.get("lock", "") or ""),
        paid=bool(raw.get("paid", False)),
        cadence_minutes=cadence,
        night_ok=bool(raw.get("night_ok", False)),
        cascade=bool(raw.get("cascade", False)),
        state=state,
        owner_area=str(raw.get("owner_area", "") or ""),
        artifact_refs=list(artifact_refs),
        backend=backend,
        fragile=bool(raw.get("fragile", False)),
        forbidden_adapter_types=list(forbidden),
        campaign=raw.get("campaign"),
        perimeter=raw.get("perimeter"),
        cwd=str(raw.get("cwd", "") or ""),
        description=str(raw.get("description", "") or ""),
    )


def load_job(job_id: str, manifests_dir: Path | None = None) -> JobManifest:
    ""
    d = manifests_dir or MANIFESTS_DIR
    path = d / f"{job_id}.yaml"
    if not path.exists():
        raise JobManifestError(f"job manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _validate(job_id, raw)


def load_all_jobs(manifests_dir: Path | None = None) -> dict[str, JobManifest]:
    ""
    d = manifests_dir or MANIFESTS_DIR
    out: dict[str, JobManifest] = {}
    if not d.exists():
        return out
    for path in sorted(d.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        job_id = path.stem
        out[job_id] = load_job(job_id, manifests_dir=d)
    return out





@dataclass
class ExternalJob:
    ""






    id: str
    owner: str
    project: str = ""
    runs_repo_code: bool = False
    plist: str = ""
    note: str = ""


def load_external(manifests_dir: Path | None = None) -> list[ExternalJob]:
    ""
    d = manifests_dir or MANIFESTS_DIR
    path = d / "_external.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return []
    entries = raw.get("external") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise JobManifestError("_external.yaml: expected a list under 'external'")
    out: list[ExternalJob] = []
    for i, e in enumerate(entries):
        if "id" not in e:
            raise JobManifestError(f"_external.yaml entry #{i}: missing 'id'")
        owner = e.get("owner", "other-project")
        out.append(
            ExternalJob(
                id=e["id"],
                owner=owner,
                project=e.get("project", ""),
                runs_repo_code=bool(e.get("runs_repo_code", False)),
                plist=e.get("plist", ""),
                note=e.get("note", ""),
            )
        )
    return out
