#!/usr/bin/env python3
""













































































from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import signal
import stat as stat_mod
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secrets_adapter import get_secret, set_secret

from sbk_config import DATA_ROOT, acquire_pid_lock, release_pid_lock

log = logging.getLogger("sbk.backup")




SCRIPT_VERSION = (
    "2.1.0"
)




DEFAULT_DESTINATION = Path.home() / "Backups" / "sbk"
DEFAULT_KEEP = 4
DEFAULT_MIN_FREE_RATIO = 0.8
MIN_FREE_ABS_BYTES = 20 * 1024**3
MIN_FREE_PERCENT = 0.03


ENC_SERVICE = "sbk-backup"
ENC_ACCOUNT = "enc-key"


ENC_MAGIC = b"SBKP"
ENC_VERSION = b"\x02"
ENC_HEADER_SIZE = 4 + 1 + 32 + 16
ENC_HMAC_SIZE = 32
PBKDF2_ITERATIONS = 600_000
LEGACY_OPENSSL_MAGIC = b"Salted__"



IMPRONTA_ETICHETTA = b"sbk-backup-impronta-v1"


SUFFISSO_PARZIALE = ".parziale"


SOGLIA_CALO_ROTAZIONE = 0.10




REPO_SBK_DIR = Path.home() / "Projects" / "SBK" / "sbk"

# Claude Code encodes a project's path into its sessions/memory folder name by
# replacing every "/" with "-". Derive it from the repo location.
_CLAUDE_PROJECT_ROOT = REPO_SBK_DIR.parent
_CLAUDE_MEMORY_DIR = (
    Path.home()
    / ".claude"
    / "projects"
    / str(_CLAUDE_PROJECT_ROOT).replace("/", "-")
    / "memory"
)
_CLAUDE_PROJECT_DIR = _CLAUDE_MEMORY_DIR.parent
VAULT_DIR = Path.home() / ".sbk-credentials"

SOURCES: list[tuple[str, Path]] = [
    ("sbk-data", DATA_ROOT),
    ("repo-sbk", REPO_SBK_DIR),
    ("claude-memory", _CLAUDE_MEMORY_DIR),
    ("vault", VAULT_DIR),
]

TRANSCRIPT_SOURCE: tuple[str, Path] = ("transcripts", _CLAUDE_PROJECT_DIR)






EXCLUDE_DIR_BASENAMES = frozenset(
    {
        "secrets",
        "node_modules",
        ".venv",
        ".next",
        ".turbo",
        "__pycache__",
        ".backup",
        "pgdata",
        "dist",
        "__MACOSX",
    }
)


EXCLUDE_DIR_PREFIXES = ("backups-",)









EXCLUDE_DIR_SUFFIXES = (".unzipped",)


EXCLUDE_DIRS_SBK_DATA = frozenset(
    {
        "l3/vectordb",
        "l3/logs",
        "logs",
        "events",
    }
)


EXCLUDE_FILE_NAMES = frozenset({".DS_Store"})


EXCLUDE_FILE_SUFFIXES = frozenset({".log", ".tmp", ".lock"})


_BLOAT_RE = re.compile(
    r"\.bak($|\.)"
    r"|\.good-"
    r"|\.partial-"
    r"|\.pre-fix"
    r"|\.log\.\d+$"
)


TRANSCRIPT_EXT = ".jsonl"




CONFIG_FILES = [
    "noise-config.json",
    "pipeline-schedule.json",
    ".sync-state.json",
    ".realtime-state.json",
    "sbk-settings.json",
    "record-hashes.json",
    "last-runs.json",
    "event-watermarks.json",
]
CONFIG_DIRS = ["l1-checkpoints", "decisions"]


def _collect_config_files() -> list[Path]:
    ""
    files: list[Path] = []
    for name in CONFIG_FILES:
        p = DATA_ROOT / name
        if p.exists():
            files.append(p)
        if name == "record-hashes.json":
            for sub in DATA_ROOT.iterdir():
                if sub.is_dir():
                    rh = sub / name
                    if rh.exists():
                        files.append(rh)
    for dirname in CONFIG_DIRS:
        d = DATA_ROOT / dirname
        if d.exists() and d.is_dir():
            for f in d.rglob("*"):
                if f.is_file():
                    files.append(f)
    return files







def _should_exclude_dir(dirname: str, alla_radice: bool = True) -> bool:
    ""



    if dirname in EXCLUDE_DIR_BASENAMES:
        return True
    for prefix in EXCLUDE_DIR_PREFIXES if alla_radice else ():
        if dirname.startswith(prefix):
            return True
    for suffix in EXCLUDE_DIR_SUFFIXES:
        if dirname.endswith(suffix):
            return True
    return False


def _should_exclude_file(basename: str) -> bool:
    ""
    if basename in EXCLUDE_FILE_NAMES:
        return True
    for suffix in EXCLUDE_FILE_SUFFIXES:
        if basename.endswith(suffix):
            return True
    if _BLOAT_RE.search(basename):
        return True
    return False


def _is_excluded_sbk_root(rel_dir: str) -> bool:
    ""
    for excl in EXCLUDE_DIRS_SBK_DATA:
        if rel_dir == excl or rel_dir.startswith(excl + "/"):
            return True
    return False



def _should_exclude(member_name: str) -> bool:
    ""
    for excl_dir in EXCLUDE_DIRS_SBK_DATA:
        if member_name.startswith(excl_dir + "/") or member_name == excl_dir:
            return True
    if any(part in EXCLUDE_DIR_BASENAMES for part in member_name.split("/")):
        return True
    base = os.path.basename(member_name)
    if _should_exclude_file(base):
        return True
    return False


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    ""
    rel = tarinfo.name
    if rel == ".":
        return tarinfo
    if rel.startswith("./"):
        rel = rel[2:]
    if _should_exclude(rel):
        return None
    return tarinfo







class ChiaveNonDisponibile(RuntimeError):
    ""


def impronta_chiave(passphrase: str) -> str:
    ""
    return hmac.new(passphrase.encode(), IMPRONTA_ETICHETTA, hashlib.sha256).hexdigest()[:16]


def _file_chiave_vault() -> Path:
    return VAULT_DIR / "files" / "sbk" / "backup-enc-key.txt"


def _ultima_impronta(destination: Path) -> str | None:
    ""
    if not destination.exists():
        return None
    for m in sorted(destination.glob("sbk-*.manifest.json"), reverse=True):
        try:
            imp = json.loads(m.read_text()).get("impronta_chiave")
        except (OSError, ValueError):
            continue
        if imp:
            return imp
    return None


def _ensure_encryption_key(destination: Path | None = None) -> str:
    ""







    key = get_secret(ENC_SERVICE, ENC_ACCOUNT)
    if key:
        attesa = _ultima_impronta(destination) if destination is not None else None
        if attesa and impronta_chiave(key) != attesa:
            raise ChiaveNonDisponibile(
                f"the key in the Keychain has fingerprint {impronta_chiave(key)}, the last archive {attesa}: "
                "I will not write archives with a different key. Put the stored key back in the Keychain (L0 kit)"
            )
        return key

    vault_file = _file_chiave_vault()
    esistenti = (
        sorted(destination.glob("sbk-*.tar.gz.enc"))
        if destination is not None and destination.exists()
        else []
    )
    if vault_file.exists() or esistenti:
        raise ChiaveNonDisponibile(
            "backup key not readable from the Keychain "
            f"({ENC_SERVICE}/{ENC_ACCOUNT}), but there are "
            + (f"{len(esistenti)} encrypted archives" if esistenti else "")
            + (" and " if esistenti and vault_file.exists() else "")
            + ("the vault copy" if vault_file.exists() else "")
            + ": I will not generate a new one (the existing archives would become unreadable). "
            "Put the key back in the Keychain from the stored copy (L0 kit)"
        )

    log.info("No encryption key and no archive anywhere: generating the first one")
    raw = subprocess.run(["openssl", "rand", "-base64", "32"], capture_output=True, text=True)
    if raw.returncode != 0:
        raise RuntimeError("openssl rand failed -- cannot generate encryption key")
    key = raw.stdout.strip()

    set_secret(ENC_SERVICE, ENC_ACCOUNT, key)
    log.info("Encryption key saved to Keychain (%s/%s)", ENC_SERVICE, ENC_ACCOUNT)


    vault_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(vault_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key + "\n")
    log.info("Encryption key copy saved to vault (fingerprint %s)", impronta_chiave(key))
    return key







def _derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    ""
    from cryptography.hazmat.primitives import hashes as c_hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=c_hashes.SHA256(),
        length=64,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    derived = kdf.derive(passphrase.encode("utf-8"))
    return derived[:32], derived[32:]







class _EncryptingWriter:
    ""




    def __init__(self, path: Path, passphrase: str):
        from cryptography.hazmat.primitives import hashes as c_hashes
        from cryptography.hazmat.primitives import hmac as c_hmac
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        self.salt = os.urandom(32)
        self.iv = os.urandom(16)
        enc_key, mac_key = _derive_keys(passphrase, self.salt)

        cipher = Cipher(algorithms.AES(enc_key), modes.CTR(self.iv))
        self._encryptor = cipher.encryptor()
        self._mac = c_hmac.HMAC(mac_key, c_hashes.SHA256())
        self._sha256 = hashlib.sha256()
        self._f = open(path, "wb")  # noqa: SIM115
        self._finalized = False


        header = ENC_MAGIC + ENC_VERSION + self.salt + self.iv
        self._f.write(header)
        self._mac.update(header)

    def write(self, data: bytes) -> int:
        self._sha256.update(data)
        ct = self._encryptor.update(data)
        self._mac.update(ct)
        self._f.write(ct)
        return len(data)

    def flush(self) -> None:
        self._f.flush()

    def tell(self) -> int:
        return self._f.tell()

    def finalize(self) -> str:
        ""
        if self._finalized:
            return self._sha256.hexdigest()
        ct = self._encryptor.finalize()
        if ct:
            self._mac.update(ct)
            self._f.write(ct)
        tag = self._mac.finalize()
        self._f.write(tag)
        self._finalized = True
        return self._sha256.hexdigest()

    def close(self) -> None:
        if not self._finalized:
            self.finalize()
        self._f.close()

    @property
    def plaintext_sha256(self) -> str:
        return self._sha256.hexdigest()







class _DecryptingReader:
    ""

    def __init__(self, path: Path, passphrase: str):
        from cryptography.hazmat.primitives import hashes as c_hashes
        from cryptography.hazmat.primitives import hmac as c_hmac
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        self._f = open(path, "rb")  # noqa: SIM115
        file_size = os.fstat(self._f.fileno()).st_size

        header = self._f.read(ENC_HEADER_SIZE)
        if len(header) < ENC_HEADER_SIZE:
            raise ValueError("File too short for SBKP v2")
        if header[:5] != ENC_MAGIC + ENC_VERSION:
            raise ValueError(f"Not SBKP v2 (magic: {header[:5]!r})")

        salt = header[5:37]
        iv = header[37:53]
        enc_key, mac_key = _derive_keys(passphrase, salt)

        cipher = Cipher(algorithms.AES(enc_key), modes.CTR(iv))
        self._decryptor = cipher.decryptor()
        self._mac = c_hmac.HMAC(mac_key, c_hashes.SHA256())
        self._mac.update(header)

        self._ct_remaining = file_size - ENC_HEADER_SIZE - ENC_HMAC_SIZE
        if self._ct_remaining < 0:
            raise ValueError("File too short: no ciphertext")
        self._finalized_decryptor = False

    def read(self, size: int = -1) -> bytes:
        if self._ct_remaining <= 0:
            return b""
        if size < 0:
            size = self._ct_remaining
        to_read = min(size, self._ct_remaining)
        chunk = self._f.read(to_read)
        if not chunk:
            return b""
        self._ct_remaining -= len(chunk)
        self._mac.update(chunk)
        plaintext = self._decryptor.update(chunk)
        if self._ct_remaining <= 0 and not self._finalized_decryptor:
            final = self._decryptor.finalize()
            if final:
                plaintext += final
            self._finalized_decryptor = True
        return plaintext

    def verify(self) -> bool:
        ""
        from cryptography.exceptions import InvalidSignature

        stored_tag = self._f.read(ENC_HMAC_SIZE)
        if len(stored_tag) != ENC_HMAC_SIZE:
            log.error("HMAC tag missing or truncated")
            return False
        try:
            self._mac.verify(stored_tag)
            return True
        except InvalidSignature:
            log.error("HMAC verification FAILED")
            return False

    def close(self) -> None:
        self._f.close()

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False







def _verify_encrypted_archive(
    enc_path: Path,
    expected_sha256: str,
    passphrase: str,
) -> tuple[bool, str]:
    ""
    try:
        reader = _DecryptingReader(enc_path, passphrase)
    except Exception as e:
        return False, f"Cannot open archive: {e}"
    sha = hashlib.sha256()
    try:
        chunk_size = 4 * 1024 * 1024
        while True:
            chunk = reader.read(chunk_size)
            if not chunk:
                break
            sha.update(chunk)
        if not reader.verify():
            return False, "HMAC verification failed"
        actual = sha.hexdigest()
        if actual != expected_sha256:
            return False, (
                f"SHA-256 mismatch: expected {expected_sha256[:16]}..., got {actual[:16]}..."
            )
        return True, "OK"
    except Exception as e:
        return False, f"Verification error: {e}"
    finally:
        reader.close()


def _verify_archive_gzip(archive_path: Path) -> bool:
    ""
    try:
        result = subprocess.run(
            ["gzip", "-t", str(archive_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.error("gzip -t: %s", (result.stderr or "").strip())
        return result.returncode == 0
    except Exception as e:
        log.warning("Could not run gzip -t on %s: %s", archive_path, e)
        return False



_verify_archive = _verify_archive_gzip


def _sha256_file(path: Path) -> str:
    ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



_sha256 = _sha256_file







def _check_disk_guard(
    destination: Path,
    estimated_bytes: int,
    ratio: float,
    skip: bool = False,
) -> tuple[bool, str]:
    ""



    gb = 1024**3
    usage = shutil.disk_usage(destination)
    free = usage.free
    total = usage.total
    needed_ratio = int(estimated_bytes * ratio)
    after_backup = free - estimated_bytes

    issues: list[str] = []
    if after_backup < needed_ratio:
        issues.append(
            f"ratio: {free / gb:.1f} GB free, need {needed_ratio / gb:.1f} GB "
            f"({ratio:.0%} of {estimated_bytes / gb:.1f} GB)"
        )
    if after_backup < MIN_FREE_ABS_BYTES:
        issues.append(
            f"absolute: {after_backup / gb:.1f} GB would remain, "
            f"min {MIN_FREE_ABS_BYTES / gb:.0f} GB"
        )
    if total > 0 and after_backup / total < MIN_FREE_PERCENT:
        pct = after_backup / total * 100
        issues.append(f"percent: {pct:.1f}% would remain, min {MIN_FREE_PERCENT * 100:.0f}%")

    if issues and not skip:
        return False, (
            "Insufficient free space. "
            + "; ".join(issues)
            + ". Pass --skip-space-check to override."
        )
    return True, (
        f"Free space OK: {free / gb:.1f} GB free, "
        f"~{estimated_bytes / gb:.1f} GB needed, "
        f"{after_backup / gb:.1f} GB would remain"
    )



_check_free_space = _check_disk_guard


def _spazio_richiesto(total: int, estimated_bytes: int, ratio: float) -> int:
    ""





    floor = max(int(estimated_bytes * ratio), MIN_FREE_ABS_BYTES, int(total * MIN_FREE_PERCENT))
    return estimated_bytes + floor


def _motivo_spazio(destination: Path, estimated_bytes: int, ratio: float) -> str:
    ""
    gb = 1024**3
    try:
        usage = shutil.disk_usage(destination)
    except OSError:
        return f"not enough free disk (raw estimate {estimated_bytes / gb:.1f} GiB)"
    need = _spazio_richiesto(usage.total, estimated_bytes, ratio)
    return (
        f"not enough free disk: {usage.free / gb:.1f} GiB free, guard needs {need / gb:.1f} GiB "
        f"(raw estimate {estimated_bytes / gb:.1f} GiB)"
    )


def _esito(outcome: str, detail: str = "") -> None:
    ""









    try:
        from jb_auto import esito

        esito(outcome, detail)
    except Exception:  # noqa: BLE001 -- the ledger must never break the backup
        pass







def _archiviati_su_drive() -> dict[str, int]:
    ""

    try:
        reg = json.loads((DATA_ROOT / "archivio-drive" / "registro.json").read_text())
        return {k: int(v["byte"]) for k, v in reg.items()}
    except Exception:
        return {}


def _walk_source(
    source_root: Path,
    prefix: str,
    tar: tarfile.TarFile | None,
    *,
    root_excl: frozenset[str] | None = None,
    transcript_only: bool = False,
) -> dict:
    ""



    root_excl = root_excl or frozenset()
    is_vault = prefix == "vault"
    su_drive = _archiviati_su_drive() if prefix == "sbk-data" else {}
    stats: dict = {
        "prefix": prefix,
        "root": str(source_root),
        "files": 0,
        "bytes": 0,
        "excluded_files": 0,
        "excluded_dirs": 0,
        "vanished": 0,
        "errors": 0,
        "symlinks": 0,
        "su_drive": 0,
    }

    if not source_root.exists():
        log.warning("Source does not exist: %s", source_root)
        return stats

    for dirpath, dirnames, filenames in os.walk(str(source_root), followlinks=False):
        rel_dir = os.path.relpath(dirpath, str(source_root))
        if rel_dir == ".":
            rel_dir = ""


        if rel_dir and root_excl:
            if _is_excluded_sbk_root(rel_dir):
                dirnames.clear()
                stats["excluded_dirs"] += 1
                continue


        new_dirs: list[str] = []
        for d in sorted(dirnames):
            full_d = os.path.join(dirpath, d)
            try:
                if os.path.islink(full_d):
                    stats["symlinks"] += 1
                    continue
            except OSError:
                continue
            if _should_exclude_dir(d, alla_radice=not rel_dir and bool(root_excl)):
                stats["excluded_dirs"] += 1
                continue
            new_dirs.append(d)
        dirnames[:] = new_dirs

        for fname in sorted(filenames):
            if transcript_only and not fname.endswith(TRANSCRIPT_EXT):
                continue

            if _should_exclude_file(fname):
                stats["excluded_files"] += 1
                continue

            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, str(source_root))
            arcname = f"{prefix}/{rel}"

            try:
                lst = os.lstat(full)

                if stat_mod.S_ISLNK(lst.st_mode):
                    stats["symlinks"] += 1
                    continue
                if not stat_mod.S_ISREG(lst.st_mode):
                    continue
                if su_drive.get(rel) == lst.st_size:
                    stats["su_drive"] += 1
                    continue

                if tar is not None:
                    tar.add(full, arcname=arcname, recursive=False)

                stats["files"] += 1
                stats["bytes"] += lst.st_size

            except FileNotFoundError:
                stats["vanished"] += 1
                if is_vault:
                    log.warning("File vanished in vault source")
                else:
                    log.warning("File vanished: %s/%s", prefix, rel)
            except OSError as e:
                stats["errors"] += 1
                if is_vault:
                    log.warning("Cannot read file in vault: %s", type(e).__name__)
                else:
                    log.warning("Cannot read %s/%s: %s", prefix, rel, e)

    return stats


def _estimate_sources(
    sources: list[tuple[str, Path]],
    with_transcripts: bool = False,
) -> tuple[int, list[dict]]:
    ""
    all_stats: list[dict] = []
    total_bytes = 0

    for prefix, root in sources:
        root_excl = EXCLUDE_DIRS_SBK_DATA if prefix == "sbk-data" else None
        st = _walk_source(root, prefix, tar=None, root_excl=root_excl)
        all_stats.append(st)
        total_bytes += st["bytes"]

    if with_transcripts:
        tp, tr = TRANSCRIPT_SOURCE
        st = _walk_source(tr, tp, tar=None, transcript_only=True)
        all_stats.append(st)
        total_bytes += st["bytes"]

    return total_bytes, all_stats







def _write_manifest(
    manifest_path: Path,
    all_stats: list[dict],
    archive_sha256: str,
    duration_s: float,
    encrypted: bool,
    with_transcripts: bool,
    impronta: str | None = None,
    verificato: bool | None = None,
    extra: dict | None = None,
) -> None:
    ""




    sources: dict = {}




    totals = {
        "files": 0,
        "bytes": 0,
        "excluded": 0,
        "vanished": 0,
        "unreadable": 0,
        "symlinks": 0,
    }

    for st in all_stats:
        sources[st["prefix"]] = {
            "files": st["files"],
            "bytes": st["bytes"],
            "excluded_files": st["excluded_files"],
            "excluded_dirs": st["excluded_dirs"],
            "vanished": st["vanished"],
            "unreadable": st.get("errors", 0),
            "symlinks": st["symlinks"],
            "su_drive": st.get("su_drive", 0),
        }
        totals["files"] += st["files"]
        totals["bytes"] += st["bytes"]
        totals["excluded"] += st["excluded_files"] + st["excluded_dirs"]
        totals["vanished"] += st["vanished"]
        totals["unreadable"] += st.get("errors", 0)
        totals["symlinks"] += st["symlinks"]

    manifest = {
        "version": SCRIPT_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "encrypted": encrypted,
        "with_transcripts": with_transcripts,
        "archive_sha256": archive_sha256,
        "sources": sources,
        "totals": totals,
        "duration_seconds": round(duration_s, 1),
    }
    if impronta:
        manifest["impronta_chiave"] = impronta
    if verificato is not None:
        manifest["verificato"] = verificato
    if extra:
        manifest.update(extra)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        os.chmod(manifest_path, 0o600)
    except OSError:
        pass







def _tighten_permissions(destination: Path) -> None:
    ""
    try:
        os.chmod(destination, 0o700)
    except OSError as e:
        log.warning("Could not chmod 0700 %s: %s", destination, e)
    for pattern in (
        "sbk-*.tar.gz",
        "sbk-*.tar.gz.enc",
        "sbk-*.manifest.json",
    ):
        for f in destination.glob(pattern):
            try:
                os.chmod(f, 0o600)
            except OSError as e:
                log.warning("Could not chmod 0600 %s: %s", f, e)







def _self_check_encryption() -> bool:
    ""
    test_key = "sbk-selfcheck-not-a-real-secret"
    tmpdir = Path(tempfile.mkdtemp(prefix="sbk-selfcheck-"))
    try:
        fixture = tmpdir / "fixture.tar.gz"
        with tarfile.open(str(fixture), "w:gz") as tar:
            data_file = tmpdir / "test.txt"
            data_file.write_text("self-check fixture data " * 100)
            tar.add(str(data_file), arcname="test.txt")

        plaintext_sha = _sha256_file(fixture)

        enc_path = tmpdir / "fixture.tar.gz.enc"
        writer = _EncryptingWriter(enc_path, test_key)
        with open(fixture, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
        pt_sha = writer.finalize()
        writer.close()

        if pt_sha != plaintext_sha:
            log.error("Self-check: SHA mismatch after encrypt")
            return False

        ok, msg = _verify_encrypted_archive(enc_path, pt_sha, test_key)
        if not ok:
            log.error("Self-check verify failed: %s", msg)
            return False

        restore_dir = tmpdir / "restored"
        restore_dir.mkdir()
        reader = _DecryptingReader(enc_path, test_key)
        try:
            with tarfile.open(mode="r|gz", fileobj=reader) as tar:
                tar.extractall(str(restore_dir), filter="data")
            if not reader.verify():
                log.error("Self-check: HMAC failed during restore")
                return False
        finally:
            reader.close()

        if not (restore_dir / "test.txt").exists():
            log.error("Self-check: restored file missing")
            return False

        return True
    except Exception as e:
        log.error("Self-check error: %s", e)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)







def do_backup(
    destination: Path,
    config_only: bool = False,
    keep: int = DEFAULT_KEEP,
    dry_run: bool = False,
    min_free_ratio: float = DEFAULT_MIN_FREE_RATIO,
    skip_space_check: bool = False,
    verify: bool = True,
    encrypt: bool = True,
    with_transcripts: bool = False,
    livello: int | None = None,
    per_drive: bool = False,
) -> Path | None:
    ""



    destination.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    suffix = "config" if config_only else "full"

    if livello is not None:
        if not dry_run and not acquire_pid_lock("sb-backup", logger=log):
            log.warning("Another backup is running: exiting without doing anything (lock sb-backup)")
            _esito("nothing", "another backup is running (lock sb-backup)")
            return None
        try:
            return _do_level_backup(
                destination,
                livello,
                per_drive,
                ts,
                keep,
                min_free_ratio,
                skip_space_check,
                verify,
                dry_run=dry_run,
            )
        finally:
            if not dry_run:
                release_pid_lock("sb-backup")


    if config_only:
        files = _collect_config_files()
        if not files:
            log.warning("No config files found")
            _esito("failed", "config backup: no config files found")
            return None
        if dry_run:
            log.info("[dry-run] Config files: %d", len(files))
            for f in sorted(files):
                log.info("  %s", f.relative_to(DATA_ROOT))
            _esito("nothing", "dry run")
            return None

        archive_path = destination / f"sbk-{suffix}-{ts}.tar.gz"
        log.info("Creating config backup: %s", archive_path)
        with tarfile.open(str(archive_path), "w:gz") as tar:
            for f in files:
                tar.add(str(f), arcname=str(f.relative_to(DATA_ROOT)))
        log.info(
            "Config backup complete: %.1f MB, %d files",
            archive_path.stat().st_size / (1024 * 1024),
            len(files),
        )
        _tighten_permissions(destination)
        _rotate_backups(destination, suffix, keep, dry_run=False)
        _esito(
            "ok",
            f"config backup: {archive_path.stat().st_size / (1024 * 1024):.1f} MB, "
            f"{len(files)} files",
        )
        return archive_path


    if not dry_run:

        if not acquire_pid_lock("sb-backup", logger=log):
            log.warning("Another backup is running: exiting without doing anything (lock sb-backup)")
            _esito("nothing", "another backup is running (lock sb-backup)")
            return None
        try:
            return _do_full_backup(
                destination,
                suffix,
                ts,
                keep,
                min_free_ratio,
                skip_space_check,
                verify,
                encrypt,
                with_transcripts,
            )
        finally:
            release_pid_lock("sb-backup")
    return _do_full_backup(
        destination,
        suffix,
        ts,
        keep,
        min_free_ratio,
        skip_space_check,
        verify,
        encrypt,
        with_transcripts,
        dry_run=True,
    )


class _Interrotto(BaseException):
    ""


def _parziali(destination: Path) -> list[Path]:
    return sorted(destination.glob(f"sbk-*{SUFFISSO_PARZIALE}"))


def _scrivi_cifrato(
    destination: Path,
    archive_name: str,
    passphrase: str,
    riempi: Callable[[tarfile.TarFile], list[dict]],
    verify: bool,
) -> tuple[Path, list[dict], str] | None:
    ""



    gb = 1024**3
    final_path = destination / archive_name
    archive_path = destination / (archive_name + SUFFISSO_PARZIALE)

    def _su_sigterm(_signum, _frame):
        raise _Interrotto()

    precedente = signal.signal(signal.SIGTERM, _su_sigterm)
    writer = _EncryptingWriter(archive_path, passphrase)
    try:
        with tarfile.open(mode="w|gz", fileobj=writer) as tar:
            stats = riempi(tar)
        plaintext_sha = writer.finalize()
    except BaseException:
        writer.close()
        archive_path.unlink(missing_ok=True)
        log.error("Backup interrupted: partial removed (%s)", archive_path.name)
        raise
    finally:
        signal.signal(signal.SIGTERM, precedente)

    writer.close()
    log.info("Encrypted backup written: %.1f GB", archive_path.stat().st_size / gb)

    if verify:
        log.info("Verifying (streaming decrypt + SHA-256)...")
        ok, vmsg = _verify_encrypted_archive(archive_path, plaintext_sha, passphrase)
        if ok:
            log.info("Integrity check passed")
        else:
            log.error("Integrity check FAILED: %s", vmsg)
            log.error("Removing corrupt archive; rotation skipped")
            archive_path.unlink(missing_ok=True)
            _esito(
                "failed",
                f"integrity check failed ({vmsg}): new archive removed, old backups kept",
            )
            return None

    archive_sha256 = _sha256_file(archive_path)
    os.replace(archive_path, final_path)
    return final_path, stats, archive_sha256


def _do_full_backup(
    destination: Path,
    suffix: str,
    ts: str,
    keep: int,
    min_free_ratio: float,
    skip_space_check: bool,
    verify: bool,
    encrypt: bool,
    with_transcripts: bool,
    dry_run: bool = False,
) -> Path | None:
    start_time = time.monotonic()
    sources = list(SOURCES)
    gb = 1024**3

    log.info("Estimating backup size...")
    total_bytes, est_stats = _estimate_sources(sources, with_transcripts)

    if dry_run:
        ok, msg = _check_disk_guard(destination, total_bytes, min_free_ratio)
        log.info("[dry-run] Estimated source: %.1f GB", total_bytes / gb)
        for st in est_stats:
            log.info(
                "[dry-run]   %s: %d files, %.2f GB, %d excluded, %d symlinks",
                st["prefix"],
                st["files"],
                st["bytes"] / gb,
                st["excluded_files"] + st["excluded_dirs"],
                st["symlinks"],
            )
        log.info("[dry-run] Disk guard: %s -- %s", "PASS" if ok else "FAIL", msg)
        log.info(
            "[dry-run] Encryption: %s",
            "AES-256-CTR + HMAC-SHA256" if encrypt else "disabled",
        )
        if not with_transcripts:
            tp, tr = TRANSCRIPT_SOURCE
            tst = _walk_source(tr, tp, tar=None, transcript_only=True)
            if tst["files"] > 0:
                log.info(
                    "[dry-run] Transcripts (--with-transcripts): %d files, %.1f MB",
                    tst["files"],
                    tst["bytes"] / (1024 * 1024),
                )
        _esito("nothing", "dry run")
        return None


    ok, msg = _check_disk_guard(destination, total_bytes, min_free_ratio, skip=skip_space_check)
    if not ok:
        log.error(msg)
        _esito("failed", _motivo_spazio(destination, total_bytes, min_free_ratio))
        return None
    log.info(msg)


    vecchi_parziali = _parziali(destination)
    if vecchi_parziali:
        log.warning(
            "Partials from interrupted runs in %s: %s (%.1f GiB), remove by hand",
            destination,
            ", ".join(p.name for p in vecchi_parziali),
            sum(p.stat().st_size for p in vecchi_parziali) / gb,
        )


    impronta = None
    if encrypt:
        archive_name = f"sbk-{suffix}-{ts}.tar.gz.enc"
        try:
            passphrase = _ensure_encryption_key(destination)
        except ChiaveNonDisponibile as e:
            log.error("%s", e)
            _esito("failed", f"key: {e}")
            return None
        impronta = impronta_chiave(passphrase)

        log.info(
            "Creating encrypted backup: %s (key fingerprint %s)",
            destination / archive_name,
            impronta,
        )
        scritto = _scrivi_cifrato(
            destination,
            archive_name,
            passphrase,
            lambda tar: _add_all_sources(tar, sources, with_transcripts),
            verify,
        )
        if scritto is None:
            return None
        archive_path, actual_stats, archive_sha256 = scritto

    else:
        archive_name = f"sbk-{suffix}-{ts}.tar.gz"
        archive_path = destination / archive_name

        log.info("Creating plaintext backup: %s", archive_path)
        log.warning("Archive is NOT encrypted -- sensitive roots in cleartext")

        with tarfile.open(str(archive_path), "w:gz") as tar:
            actual_stats = _add_all_sources(tar, sources, with_transcripts)

        if verify:
            if _verify_archive_gzip(archive_path):
                log.info("Integrity check passed: %s", archive_path.name)
            else:
                log.error("Integrity check FAILED: %s", archive_path.name)
                log.error("Removing corrupt archive; rotation skipped")
                archive_path.unlink(missing_ok=True)
                _esito(
                    "failed", "integrity check failed (gzip): new archive removed, old backups kept"
                )
                return None

        archive_sha256 = _sha256_file(archive_path)


    _tighten_permissions(destination)

    duration = time.monotonic() - start_time
    manifest_path = Path(str(archive_path) + ".manifest.json")
    _write_manifest(
        manifest_path,
        actual_stats,
        archive_sha256,
        duration,
        encrypt,
        with_transcripts,
        impronta=impronta,
        verificato=verify,
    )
    log.info("Manifest: %s", manifest_path.name)

    ruotato = _rotate_backups(
        destination, suffix, keep, dry_run=False, encrypted=encrypt, nuovo=archive_path
    )

    total_files = sum(s["files"] for s in actual_stats)
    total_vanished = sum(s["vanished"] for s in actual_stats)
    total_unreadable = sum(s.get("errors", 0) for s in actual_stats)
    size_gb = archive_path.stat().st_size / gb
    log.info(
        "Backup complete: %d files, %.1f GB, %d vanished, %d unreadable, %.0fs",
        total_files,
        size_gb,
        total_vanished,
        total_unreadable,
        duration,
    )
    riepilogo = _riepilogo_ok(size_gb, total_files, total_unreadable, total_vanished)
    if not ruotato:
        riepilogo += "; rotation skipped due to size drop (see log)"
    _esito("ok", riepilogo)
    return archive_path


def _riepilogo_ok(size_gb: float, files: int, unreadable: int, vanished: int) -> str:
    ""
    out = f"{size_gb:.1f} GiB, {files} files, {unreadable} unreadable"
    if vanished:
        out += f", {vanished} vanished"
    return out


def _add_all_sources(
    tar: tarfile.TarFile,
    sources: list[tuple[str, Path]],
    with_transcripts: bool,
) -> list[dict]:
    ""
    gb = 1024**3
    actual_stats: list[dict] = []
    for prefix, root in sources:
        root_excl = EXCLUDE_DIRS_SBK_DATA if prefix == "sbk-data" else None
        st = _walk_source(root, prefix, tar, root_excl=root_excl)
        actual_stats.append(st)
        log.info(
            "  %s: %d files (%.1f GB), %d vanished",
            prefix,
            st["files"],
            st["bytes"] / gb,
            st["vanished"],
        )
    if with_transcripts:
        tp, tr = TRANSCRIPT_SOURCE
        st = _walk_source(tr, tp, tar, transcript_only=True)
        actual_stats.append(st)
        log.info(
            "  %s: %d files (%.1f MB)",
            tp,
            st["files"],
            st["bytes"] / (1024 * 1024),
        )
    return actual_stats







REPO_DIR = Path.home() / "Projects" / "SBK"

REPO_NON_TRACCIATO_MAX = 50 * 1024**2

PREFISSI_LIVELLO = {"memoria-claude": "claude-memory", "sessioni-claude": "transcripts"}


def _sb_livelli():
    ""
    cartella = str(Path(__file__).resolve().parent)
    if cartella not in sys.path:
        sys.path.insert(0, cartella)
    import sb_livelli

    return sb_livelli


def _stats_vuote(prefix: str, root: Path) -> dict:
    return {
        "prefix": prefix,
        "root": str(root),
        "files": 0,
        "bytes": 0,
        "excluded_files": 0,
        "excluded_dirs": 0,
        "vanished": 0,
        "errors": 0,
        "symlinks": 0,
        "su_drive": 0,
    }


def _voci_livello(livello: int, per_drive: bool):
    ""
    lv = _sb_livelli()
    basi = {f.nome: f.base for f in lv.FUORI}
    for sorgente, p, size, es in lv.elenco(livello, "drive" if per_drive else "disco"):
        if sorgente == "sbk-data":
            prefisso, base = "sbk-data", DATA_ROOT
        else:
            prefisso, base = PREFISSI_LIVELLO.get(sorgente, sorgente), basi[sorgente]
        yield prefisso, base, f"{prefisso}/{os.path.relpath(p, base)}", p, size, es.regola


def _codice_repo(cartella_tmp: Path) -> tuple[list[tuple[str, Path]], int]:
    ""


    out: list[tuple[str, Path]] = []
    if not (REPO_DIR / ".git").exists():
        log.warning("SBK repo not found in %s: the code stays out of L1", REPO_DIR)
        return out, 0
    git = ["git", "-C", str(REPO_DIR)]
    bundle = cartella_tmp / "sbk.bundle"
    r = subprocess.run(
        [*git, "bundle", "create", str(bundle), "--all"],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if r.returncode == 0 and bundle.exists():
        out.append(("repo-git/sbk.bundle", bundle))
    else:
        log.error("git bundle failed: %s", (r.stderr or "").strip()[-300:])
    patch = cartella_tmp / "non-committato.patch"
    with open(patch, "wb") as f:
        r = subprocess.run(
            [*git, "diff", "--binary", "HEAD"], stdout=f, stderr=subprocess.PIPE, timeout=600
        )
    if r.returncode == 0:
        out.append(("repo-git/non-committato.patch", patch))
    else:
        log.error("git diff failed: the uncommitted work stays out of L1")
    r = subprocess.run(
        [*git, "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        timeout=600,
    )
    troppo_grandi = 0
    for rel in r.stdout.decode(errors="surrogateescape").split("\0"):
        if not rel:
            continue
        p = REPO_DIR / rel
        try:
            s = p.lstat()
        except OSError:
            continue
        if not stat_mod.S_ISREG(s.st_mode):
            continue
        if s.st_size > REPO_NON_TRACCIATO_MAX:
            troppo_grandi += 1
            continue
        out.append((f"repo-git/non-tracciati/{rel}", p))
    return out, troppo_grandi


def _aggiungi_livello(
    tar: tarfile.TarFile,
    livello: int,
    per_drive: bool,
    cartella_tmp: Path,
    per_regola: dict,
    per_radice: dict | None = None,
) -> list[dict]:
    ""


    su_drive = _archiviati_su_drive()
    stats: dict[str, dict] = {}
    for prefisso, base, arcname, p, size, regola in _voci_livello(livello, per_drive):
        st = stats.setdefault(prefisso, _stats_vuote(prefisso, base))
        vault = prefisso == "vault"
        if prefisso == "sbk-data" and su_drive.get(arcname.split("/", 1)[1]) == size:
            st["su_drive"] += 1
            continue
        try:
            lst = os.lstat(p)
            if stat_mod.S_ISLNK(lst.st_mode):
                tar.add(str(p), arcname=arcname, recursive=False)
                st["symlinks"] += 1
                continue
            if not stat_mod.S_ISREG(lst.st_mode):
                continue
            tar.add(str(p), arcname=arcname, recursive=False)
            st["files"] += 1
            st["bytes"] += lst.st_size
            c = per_regola.setdefault(regola, [0, 0])
            c[0] += 1
            c[1] += lst.st_size
            if per_radice is not None and prefisso == "sbk-data":
                radice = arcname.split("/")[1]
                per_radice[radice] = per_radice.get(radice, 0) + 1
        except FileNotFoundError:
            st["vanished"] += 1
            log.warning("File vanished: %s", "(vault)" if vault else arcname)
        except OSError as e:
            st["errors"] += 1
            log.warning("Cannot read %s: %s", "(vault)" if vault else arcname, type(e).__name__)
    if livello == 1:
        codice, troppo_grandi = _codice_repo(cartella_tmp)
        st = stats.setdefault("repo-git", _stats_vuote("repo-git", REPO_DIR))
        st["excluded_files"] = troppo_grandi
        for arcname, p in codice:
            try:
                tar.add(str(p), arcname=arcname, recursive=False)
                st["files"] += 1
                st["bytes"] += p.stat().st_size
            except FileNotFoundError:
                st["vanished"] += 1
            except OSError:
                st["errors"] += 1
    gb = 1024**3
    for st in stats.values():
        log.info(
            "  %s: %d files (%.2f GB), %d vanished, %d unreadable",
            st["prefix"],
            st["files"],
            st["bytes"] / gb,
            st["vanished"],
            st["errors"],
        )
    return list(stats.values())


def _do_level_backup(
    destination: Path,
    livello: int,
    per_drive: bool,
    ts: str,
    keep: int,
    min_free_ratio: float,
    skip_space_check: bool,
    verify: bool,
    dry_run: bool = False,
) -> Path | None:
    ""
    start_time = time.monotonic()
    gb = 1024**3
    suffix = f"l{livello}" + ("-drive" if per_drive else "")
    log.info(
        "Level %d %s: estimating files...",
        livello,
        "for the Drive (without disk-only)" if per_drive else "for the disk (the whole level)",
    )
    stima_regole: dict[str, list[int]] = {}
    stima_radici: dict[str, int] = {}
    stima = 0
    for pre, _base, arc, _p, size, regola in _voci_livello(livello, per_drive):
        stima += size
        c = stima_regole.setdefault(regola, [0, 0])
        c[0] += 1
        c[1] += size
        if pre == "sbk-data":
            radice = arc.split("/")[1]
            stima_radici[radice] = stima_radici.get(radice, 0) + 1
    if livello == 1:
        stima += sum(f.stat().st_size for f in (REPO_DIR / ".git").rglob("*") if f.is_file())
    ok, msg = _check_disk_guard(destination, stima, min_free_ratio, skip=skip_space_check)

    if dry_run:
        n = sum(c[0] for c in stima_regole.values())
        log.info("[dry-run] level %d: %d files, %.1f GB raw", livello, n, stima / gb)
        for regola, (nf, b) in sorted(stima_regole.items(), key=lambda kv: -kv[1][1]):
            log.info("[dry-run]   %8d file %8.2f GB  %s", nf, b / gb, regola)
        log.info("[dry-run] Disk guard: %s -- %s", "PASS" if ok else "FAIL", msg)
        _esito("nothing", "dry run")
        return None
    if not ok:
        log.error(msg)
        _esito("failed", _motivo_spazio(destination, stima, min_free_ratio))
        return None
    log.info(msg)

    vecchi_parziali = _parziali(destination)
    if vecchi_parziali:
        log.warning(
            "Partials from interrupted runs in %s: %s, remove by hand",
            destination,
            ", ".join(p.name for p in vecchi_parziali),
        )

    archive_name = f"sbk-{suffix}-{ts}.tar.gz.enc"
    try:
        passphrase = _ensure_encryption_key(destination)
    except ChiaveNonDisponibile as e:
        log.error("%s", e)
        _esito("failed", f"key: {e}")
        return None
    impronta = impronta_chiave(passphrase)
    log.info(
        "Creating encrypted level backup: %s (key fingerprint %s)",
        destination / archive_name,
        impronta,
    )
    per_regola: dict[str, list[int]] = {}
    per_radice: dict[str, int] = {}
    with tempfile.TemporaryDirectory(
        prefix="sbk-codice-", suffix=SUFFISSO_PARZIALE, dir=destination
    ) as tmp:
        scritto = _scrivi_cifrato(
            destination,
            archive_name,
            passphrase,
            lambda tar: _aggiungi_livello(
                tar, livello, per_drive, Path(tmp), per_regola, per_radice
            ),
            verify,
        )
    if scritto is None:
        return None
    archive_path, actual_stats, archive_sha256 = scritto

    vuote = sorted(r for r, n in stima_radici.items() if n and not per_radice.get(r))
    if vuote:
        log.error(
            "Roots with L%d files in the live data and none in the archive: %s", livello, ", ".join(vuote)
        )

    _tighten_permissions(destination)
    duration = time.monotonic() - start_time
    manifest_path = Path(str(archive_path) + ".manifest.json")
    _write_manifest(
        manifest_path,
        actual_stats,
        archive_sha256,
        duration,
        True,
        False,
        impronta=impronta,
        verificato=verify,
        extra={
            "livello": livello,
            "per_drive": per_drive,

            "radici": {s["prefix"]: s["root"] for s in actual_stats if s["prefix"] != "repo-git"},

            "regole": {r: {"files": n, "bytes": b} for r, (n, b) in sorted(per_regola.items())},
            "radici_vuote": vuote,
        },
    )
    log.info("Manifest: %s", manifest_path.name)
    ruotato = _rotate_backups(
        destination, suffix, keep, dry_run=False, encrypted=True, nuovo=archive_path
    )
    total_files = sum(s["files"] for s in actual_stats)
    total_vanished = sum(s["vanished"] for s in actual_stats)
    total_unreadable = sum(s.get("errors", 0) for s in actual_stats)
    size_gb = archive_path.stat().st_size / gb
    log.info(
        "Level backup complete: L%d, %d files, %.1f GB, %d vanished, %d unreadable, %.0fs",
        livello,
        total_files,
        size_gb,
        total_vanished,
        total_unreadable,
        duration,
    )
    riepilogo = f"L{livello}: " + _riepilogo_ok(
        size_gb, total_files, total_unreadable, total_vanished
    )
    if not ruotato:
        riepilogo += "; rotation skipped due to size drop (see log)"
    if vuote:
        _esito("failed", riepilogo + f"; empty roots in the archive: {', '.join(vuote)}")
        return archive_path
    _esito("ok", riepilogo)
    return archive_path







def _leggi_chiave_ripristino(chiave_da_stdin: bool) -> str | None:
    ""



    if not chiave_da_stdin:
        return get_secret(ENC_SERVICE, ENC_ACCOUNT)
    if sys.stdin.isatty():
        import getpass

        return getpass.getpass("Backup key (not shown): ").strip() or None
    return sys.stdin.readline().strip() or None


def _impronta_del_manifest(archive_path: Path) -> str | None:
    try:
        return json.loads(Path(str(archive_path) + ".manifest.json").read_text()).get(
            "impronta_chiave"
        )
    except (OSError, ValueError):
        return None


def do_restore(
    archive_path: Path,
    target_dir: Path,
    *,
    chiave_da_stdin: bool = False,
    consenti_legacy: bool = False,
    consenti_in_chiaro: bool = False,
) -> bool:
    ""






    if target_dir.exists() and any(target_dir.iterdir()):
        log.error("The restore directory must be empty: %s", target_dir)
        return False
    target_dir.mkdir(parents=True, exist_ok=True)

    with open(archive_path, "rb") as f:
        magic = f.read(8)

    if magic[:5] == ENC_MAGIC + ENC_VERSION:
        return _restore_sbkp_v2(archive_path, target_dir, chiave_da_stdin=chiave_da_stdin)
    if magic[:8] == LEGACY_OPENSSL_MAGIC:
        if not consenti_legacy:
            log.error("Old openssl-CBC archive, not authenticated: --allow-legacy is required")
            return False
        return _restore_legacy_openssl(archive_path, target_dir)
    if not consenti_in_chiaro:
        log.error(
            "Archive not encrypted and not authenticated: rejected. If you know where it comes from, --allow-plaintext "
            "(it is extracted anyway with the safety filter)"
        )
        return False
    return _restore_plaintext(archive_path, target_dir)


def _hmac_valido(archive_path: Path, passphrase: str) -> bool:
    ""
    try:
        reader = _DecryptingReader(archive_path, passphrase)
    except Exception as e:  # noqa: BLE001
        log.error("Archive not openable: %s", e)
        return False
    try:
        while reader.read(4 * 1024 * 1024):
            pass
        return reader.verify()
    finally:
        reader.close()


def _radici_dei_prefissi(manifest: dict) -> dict[str, Path]:
    ""
    radici = {p: r for p, r in SOURCES}
    radici[TRANSCRIPT_SOURCE[0]] = TRANSCRIPT_SOURCE[1]
    try:
        for f in _sb_livelli().FUORI:
            radici.setdefault(PREFISSI_LIVELLO.get(f.nome, f.nome), f.base)
    except Exception:  # noqa: BLE001 -- without the levels registry only the usual prefixes are tried
        pass
    radici["repo-git/non-tracciati"] = REPO_DIR
    if "livello" in manifest and "radici" not in manifest:


        radici["claude-memory"] = _CLAUDE_PROJECT_DIR
    for p, r in (manifest.get("radici") or {}).items():
        radici[p] = Path(r)
    return radici


def _vivo_di(arcname: str, radici: dict[str, Path]) -> Path | None:
    ""
    for prefisso in sorted(radici, key=len, reverse=True):
        if arcname.startswith(prefisso + "/"):
            return radici[prefisso] / arcname[len(prefisso) + 1 :]
    return None


def prova_campione(archive_path: Path, quanti: int = 500, *, chiave_da_stdin: bool = False) -> bool:
    ""



    import random

    passphrase = _leggi_chiave_ripristino(chiave_da_stdin)
    if not passphrase:
        log.error(
            "No key: Keychain empty. Use --key-from-stdin with your offline copy of the key."
        )
        return False
    attesa = _impronta_del_manifest(archive_path)
    if attesa and impronta_chiave(passphrase) != attesa:
        log.error("The key has a different fingerprint from the manifest: wrong key")
        return False
    try:
        manifest = json.loads(Path(str(archive_path) + ".manifest.json").read_text())
    except (OSError, ValueError):
        manifest = {}
    totale = int((manifest.get("totals") or {}).get("files") or 0) or 1
    try:
        inizio = datetime.fromisoformat(manifest["timestamp"]).timestamp() - float(
            manifest.get("duration_seconds") or 0
        )
    except (KeyError, ValueError, TypeError):
        inizio = archive_path.stat().st_mtime
    radici = _radici_dei_prefissi(manifest)
    scelta = random.Random(archive_path.name)
    p = min(1.0, quanti / totale)
    conti = {
        "membri": 0,
        "provati": 0,
        "uguali": 0,
        "cambiati_dopo": 0,
        "spariti": 0,
        "generati": 0,
    }
    diversi: list[str] = []
    spariti: list[str] = []
    reader = _DecryptingReader(archive_path, passphrase)
    try:
        with tarfile.open(mode="r|gz", fileobj=reader) as tar:
            for m in tar:
                if not m.isfile():
                    continue
                conti["membri"] += 1
                if scelta.random() >= p:
                    continue
                vivo = _vivo_di(m.name, radici)
                if vivo is None:
                    conti["generati"] += 1
                    continue
                conti["provati"] += 1
                h = hashlib.sha256()
                src = tar.extractfile(m)
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    h.update(chunk)
                try:
                    s = vivo.lstat()
                except FileNotFoundError:
                    conti["spariti"] += 1
                    spariti.append("(vault)" if m.name.startswith("vault/") else m.name)
                    continue
                if s.st_mtime > inizio:
                    conti["cambiati_dopo"] += 1
                    continue
                if _sha256_file(vivo) == h.hexdigest():
                    conti["uguali"] += 1
                else:
                    diversi.append("(vault)" if m.name.startswith("vault/") else m.name)
        while reader.read(4 * 1024 * 1024):
            pass
        autentico = reader.verify()
    except Exception as e:  # noqa: BLE001
        log.error("Could not read the archive: %s", e)
        return False
    finally:
        reader.close()
    log.info(
        "Sample test of %s: %d members, %d tested, %d equal to live, %d changed after the backup, "
        "%d gone from live, %d generated (bundle, patch), %d different; HMAC %s",
        archive_path.name,
        conti["membri"],
        conti["provati"],
        conti["uguali"],
        conti["cambiati_dopo"],
        conti["spariti"],
        conti["generati"],
        len(diversi),
        "valid" if autentico else "NOT valid",
    )
    for d in diversi[:20]:
        log.error("  different from live without being changed after: %s", d)
    for d in spariti[:20]:
        log.warning("  no longer in live (moved or removed after the backup): %s", d)
    if manifest.get("totals") and conti["membri"] != int(manifest["totals"]["files"]):
        log.warning(
            "The manifest says %s files, the archive contains %d",
            manifest["totals"]["files"],
            conti["membri"],
        )
    return autentico and not diversi and conti["provati"] > 0


def _restore_sbkp_v2(
    archive_path: Path, target_dir: Path, *, chiave_da_stdin: bool = False
) -> bool:
    ""
    passphrase = _leggi_chiave_ripristino(chiave_da_stdin)
    if not passphrase:
        log.error(
            "No key: Keychain empty (%s/%s). Use --key-from-stdin with your offline copy of the key.",
            ENC_SERVICE,
            ENC_ACCOUNT,
        )
        return False

    attesa = _impronta_del_manifest(archive_path)
    if attesa and impronta_chiave(passphrase) != attesa:
        log.error(
            "The key has fingerprint %s, the archive manifest %s: wrong key",
            impronta_chiave(passphrase),
            attesa,
        )
        return False

    log.info("Full authentication of %s before extracting...", archive_path.name)
    if not _hmac_valido(archive_path, passphrase):
        log.error("HMAC verification FAILED: nothing was extracted")
        return False

    log.info("Restoring SBKP v2: %s -> %s", archive_path.name, target_dir)
    reader = _DecryptingReader(archive_path, passphrase)
    try:
        with tarfile.open(mode="r|gz", fileobj=reader) as tar:
            tar.extractall(str(target_dir), filter="data")
        log.info("Restore complete (authenticated before extraction)")
        return True
    except Exception as e:
        log.error("Restore failed: %s", e)
        return False
    finally:
        reader.close()


def _restore_legacy_openssl(archive_path: Path, target_dir: Path) -> bool:
    ""
    passphrase = get_secret(ENC_SERVICE, ENC_ACCOUNT)
    if not passphrase:
        log.error("No encryption key in Keychain (%s/%s)", ENC_SERVICE, ENC_ACCOUNT)
        return False

    log.info("Restoring legacy openssl-CBC: %s -> %s", archive_path.name, target_dir)
    try:
        decrypt = subprocess.Popen(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-pbkdf2",
                "-in",
                str(archive_path),
                "-pass",
                "stdin",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        extract = subprocess.Popen(
            ["tar", "xzf", "-", "-C", str(target_dir)],
            stdin=decrypt.stdout,
        )
        decrypt.stdin.write(passphrase.encode() + b"\n")
        decrypt.stdin.close()
        if decrypt.stdout:
            decrypt.stdout.close()
        extract.wait()
        decrypt.wait()

        if decrypt.returncode != 0 or extract.returncode != 0:
            log.error(
                "Restore failed: openssl=%d, tar=%d",
                decrypt.returncode,
                extract.returncode,
            )
            return False
        log.info("Legacy restore complete")
        return True
    except Exception as e:
        log.error("Restore failed: %s", e)
        return False


def _restore_plaintext(archive_path: Path, target_dir: Path) -> bool:
    ""
    log.info("Restoring plaintext: %s -> %s", archive_path.name, target_dir)
    try:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            tar.extractall(str(target_dir), filter="data")
        log.info("Restore complete")
        return True
    except Exception as e:
        log.error("Restore failed: %s", e)
        return False







def _byte_del_manifest(archive: Path) -> int | None:
    try:
        return int(json.loads(Path(str(archive) + ".manifest.json").read_text())["totals"]["bytes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _rotate_backups(
    destination: Path,
    suffix: str,
    keep: int,
    *,
    dry_run: bool,
    encrypted: bool = True,
    nuovo: Path | None = None,
) -> bool:
    ""





    if encrypted:
        pattern = f"sbk-{suffix}-*.tar.gz.enc"
    else:
        pattern = f"sbk-{suffix}-*.tar.gz"

    backups = sorted(
        f
        for f in destination.glob(pattern)
        if not f.name.endswith(".manifest.json") and Path(str(f) + ".manifest.json").exists()
    )

    if len(backups) <= keep:
        return True

    to_remove = backups[: len(backups) - keep]
    if nuovo is not None:
        nuovo_b = _byte_del_manifest(nuovo)
        altri = [b for b in (_byte_del_manifest(x) for x in to_remove) if b]
        if nuovo_b is not None and altri and nuovo_b < max(altri) * (1 - SOGLIA_CALO_ROTAZIONE):
            log.error(
                "Rotation SKIPPED: the new archive reads %.1f GiB, the one I would remove %.1f GiB "
                "(drop over %d%%). Nothing was deleted.",
                nuovo_b / 1024**3,
                max(altri) / 1024**3,
                int(SOGLIA_CALO_ROTAZIONE * 100),
            )
            return False
    for old in to_remove:
        if dry_run:
            log.info("[dry-run] Would remove: %s", old.name)
        else:
            old.unlink()
            log.info("Removed old backup: %s", old.name)
            manifest = Path(str(old) + ".manifest.json")
            if manifest.exists():
                manifest.unlink()
                log.info("Removed old manifest: %s", manifest.name)
    return True







def list_backups(destination: Path) -> None:
    ""
    if not destination.exists():
        print(f"No backup directory at {destination}")
        return

    backups = sorted(
        f
        for f in destination.glob("sbk-*")
        if (f.suffix in (".gz", ".enc")) and not f.name.endswith(".manifest.json")
    )
    if not backups:
        print(f"No backups found in {destination}")
        return

    gb = 1024**3
    mb = 1024**2
    print(f"Backups in {destination}:")
    print()
    total_size = 0
    for b in backups:
        size = b.stat().st_size
        total_size += size
        mtime = datetime.fromtimestamp(b.stat().st_mtime).astimezone()
        size_str = f"{size / gb:.1f} GB" if size >= gb else f"{size / mb:.1f} MB"
        enc = " [encrypted]" if b.name.endswith(".enc") else ""
        has_m = Path(str(b) + ".manifest.json").exists()
        mani = " +manifest" if has_m else ""
        print(f"  {b.name}  {size_str}  ({mtime:%Y-%m-%d %H:%M %Z}){enc}{mani}")
    print()
    total_str = f"{total_size / gb:.1f} GB" if total_size >= gb else f"{total_size / mb:.0f} MB"
    print(f"Total: {len(backups)} backups, {total_str}")







def main() -> None:
    parser = argparse.ArgumentParser(
        description="SBK Backup -- multi-source encrypted backup with rotation"
    )
    parser.add_argument("--config-only", action="store_true", help="Config files only")
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help=f"Destination dir (default: {DEFAULT_DESTINATION})",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
        help=f"Backups to retain (default: {DEFAULT_KEEP})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    parser.add_argument("--list", action="store_true", help="List backups")
    parser.add_argument(
        "--min-free-ratio",
        type=float,
        default=DEFAULT_MIN_FREE_RATIO,
        help=f"Free-space guard ratio (default: {DEFAULT_MIN_FREE_RATIO})",
    )
    parser.add_argument(
        "--skip-space-check",
        action="store_true",
        help="Skip the pre-backup free-space guard",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-backup integrity check",
    )
    parser.add_argument(
        "--no-encrypt",
        action="store_true",
        help="Write plaintext .tar.gz (NOT recommended)",
    )
    parser.add_argument(
        "--with-transcripts",
        action="store_true",
        help="Include Claude session transcripts",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Encryption round-trip self-check",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        metavar="FILE",
        help="Restore an archive",
    )
    parser.add_argument(
        "--to",
        type=Path,
        metavar="DIR",
        help="Target directory for --restore",
    )
    parser.add_argument(
        "--key-from-stdin",
        dest="chiave_da_stdin",
        action="store_true",
        help="--restore: ask for the key (or read it from stdin) instead of the Keychain, e.g. on a new Mac",
    )
    parser.add_argument(
        "--allow-legacy",
        dest="consenti_legacy",
        action="store_true",
        help="--restore: accept the old openssl-CBC archives",
    )
    parser.add_argument(
        "--allow-plaintext",
        dest="consenti_in_chiaro",
        action="store_true",
        help="--restore: accept an unencrypted tar.gz (extracted anyway with the safety filter)",
    )
    parser.add_argument(
        "--trial",
        dest="prova",
        type=Path,
        metavar="ARCHIVE",
        help="restore trial without writing: HMAC and a sample of files compared with the live data",
    )
    parser.add_argument(
        "--sample",
        dest="campione",
        type=int,
        metavar="N",
        default=500,
        help="with --trial: how many files to compare with the live data (default 500)",
    )
    parser.add_argument(
        "--level",
        dest="livello",
        type=int,
        choices=(1, 2, 3),
        help="only the files of one level (tools/infrastructure/sb_livelli.py), always encrypted",
    )
    parser.add_argument(
        "--per-drive",
        action="store_true",
        help="with --level: leave out what is only on the disk (the roots marked disk-only)",
    )

    parser.add_argument("--encrypt", action="store_true", help=argparse.SUPPRESS)
    # Older Italian names, kept as hidden aliases.
    parser.add_argument("--chiave-da-stdin", dest="chiave_da_stdin", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--consenti-legacy", dest="consenti_legacy", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--consenti-in-chiaro", dest="consenti_in_chiaro", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--prova", dest="prova", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--campione", dest="campione", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--livello", dest="livello", type=int, choices=(1, 2, 3), help=argparse.SUPPRESS)

    args = parser.parse_args()
    if args.livello is not None and (args.no_encrypt or args.config_only or args.with_transcripts):
        parser.error(
            "--level is always encrypted and chooses the transcripts itself: no --no-encrypt, --config-only, --with-transcripts"
        )
    if args.per_drive and args.livello is None:
        parser.error("--per-drive only applies with --level")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",

        datefmt="%d/%m/%Y %H:%M:%S %z",
    )

    if args.self_check:
        ok = _self_check_encryption()
        print("PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)

    if args.restore:
        if not args.to:
            parser.error("--restore requires --to <directory>")
        if not args.restore.exists():
            log.error("Archive not found: %s", args.restore)
            sys.exit(1)
        ok = do_restore(
            args.restore,
            args.to,
            chiave_da_stdin=args.chiave_da_stdin,
            consenti_legacy=args.consenti_legacy,
            consenti_in_chiaro=args.consenti_in_chiaro,
        )
        sys.exit(0 if ok else 1)

    if args.list:
        list_backups(args.destination)
        return

    if args.prova:
        ok = prova_campione(args.prova, args.campione, chiave_da_stdin=args.chiave_da_stdin)
        sys.exit(0 if ok else 1)

    result = do_backup(
        destination=args.destination,
        config_only=args.config_only,
        keep=args.keep,
        dry_run=args.dry_run,
        min_free_ratio=args.min_free_ratio,
        skip_space_check=args.skip_space_check,
        verify=not args.no_verify,
        encrypt=not args.no_encrypt,
        with_transcripts=args.with_transcripts,
        livello=args.livello,
        per_drive=args.per_drive,
    )

    if result:
        print(f"\nBackup saved: {result}")
    elif not args.dry_run and not args.list:
        sys.exit(1)


if __name__ == "__main__":


    import sys as _sys
    from pathlib import Path as _P

    _sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools" / "jobs"))

    def _uscita(_codice) -> None:
        return None

    try:
        from jb_auto import aggancia as _aggancia
        from jb_auto import uscita as _uscita

        _aggancia("com.sbk.backup")
    except Exception:  # noqa: BLE001 -- the ledger must not break the work
        pass



    try:
        main()
    except SystemExit as _e:
        _uscita(_e.code)
        raise
