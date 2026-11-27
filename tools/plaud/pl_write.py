#!/usr/bin/env python3
"""Plaud write client: renames the speakers of a recording (raw and polished transcript), with a diff first and a
backup of the segments; --apply writes.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud.pl_write_base import RenameOp
    from tools.plaud.pl_wt_auth import (
        TokenKind,
        decode_jwt_header,
        decode_jwt_payload,
        select_token,
        strip_bearer_prefix,
    )
except ImportError:  # pragma: no cover
    from pl_write_base import RenameOp  # type: ignore[no-redef]
    from pl_wt_auth import (  # type: ignore[no-redef]
        TokenKind,
        decode_jwt_header,
        decode_jwt_payload,
        select_token,
        strip_bearer_prefix,
    )

_WRAPPER = Path(__file__).resolve().parent / "electron-decrypt"


_ENVELOPE = {
    "app-platform": "web",
    "edit-from": "web",
    "app-language": "en",
    "accept": "application/json, text/plain, */*",
}


class WriteError(RuntimeError):
    pass







# Region comes from the decrypted store (apiDomain); this is only a neutral
# fallback for open-source defaults, not a regional endpoint.
_DEFAULT_API = "https://api.plaud.ai"


def load_store() -> dict[str, Any]:
    ""
    electron = _WRAPPER / "node_modules" / ".bin" / "electron"
    if not electron.exists():
        raise WriteError(f"electron wrapper missing in {_WRAPPER}")
    r = subprocess.run(
        [str(electron), "main.js"], cwd=str(_WRAPPER), capture_output=True, text=True, timeout=60
    )
    if r.returncode != 0:
        raise WriteError(f"decrypt failed: {r.stderr[:200]}")
    return json.loads(r.stdout)


def is_real_wt(wt: str | None) -> bool:
    ""


    if not wt:
        return False
    t = strip_bearer_prefix(wt)
    if t.count(".") != 2:
        return False
    typ = str(decode_jwt_header(t).get("typ", "")).upper()
    if typ == "WT":
        return True

    p = decode_jwt_payload(t)
    return bool(p) and any(p.get(k) for k in ("workspace_id", "ws", "wid"))


def get_auth(store: dict[str, Any] | None = None) -> tuple[str, str]:
    ""







    if store is None:
        try:
            from tools.plaud import pl_auth_refresh
        except ImportError:  # pragma: no cover
            import pl_auth_refresh  # type: ignore[no-redef]
        fresh = pl_auth_refresh.load_saved_wt()
        if is_real_wt(fresh):
            try:
                api = (load_store().get("apiDomain") or _DEFAULT_API).rstrip("/")
            except Exception:
                api = _DEFAULT_API
            return strip_bearer_prefix(fresh), api
    store = store or load_store()
    wt = select_token(store, TokenKind.WT)
    if not is_real_wt(wt):
        raise WriteError(
            "Invalid WT in the store (Plaud desktop app logged out / placeholder token). "
            "A one-time desktop login is needed for bootstrap, then the refresh is headless."
        )
    api = store.get("apiDomain") or _DEFAULT_API
    return strip_bearer_prefix(wt), api.rstrip("/")


def _request_id() -> str:

    import secrets

    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(11))


def _http(method: str, api_base: str, path: str, wt: str, body: dict | None = None) -> Any:
    url = f"{api_base}{path}"
    headers = dict(_ENVELOPE)
    headers["Authorization"] = f"Bearer {wt}"
    headers["x-request-id"] = _request_id()
    headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise WriteError(f"HTTP {e.code} su {method} {path}: {e.read()[:200]!r}") from e
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw[:500].decode("utf-8", "replace")}







def _fetch_s3(url: str, attempts: int = 3, timeout: int = 120) -> bytes:
    ""

    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                gz = resp.headers.get("Content-Encoding") == "gzip"
            if raw[:2] == b"\x1f\x8b" or gz:
                raw = gzip.decompress(raw)
            return raw
        except (TimeoutError, urllib.error.URLError, OSError) as e:  # noqa: PERF203
            last = e
    raise WriteError(f"S3 fetch failed after {attempts} attempts: {last}")


def read_segments(file_id: str, wt: str, api_base: str) -> list[dict[str, Any]]:
    ""
    detail = _http("GET", api_base, f"/file/detail/{file_id}", wt)
    content_list = (detail.get("data") or detail).get("content_list") or detail.get(
        "content_list", []
    )
    link = None
    for item in content_list:
        if item.get("data_type") == "transaction":
            link = item.get("data_link")
            break
    if not link:
        raise WriteError("no data_link transaction in the detail (file not transcribed?)")
    segs = json.loads(_fetch_s3(link))
    if not isinstance(segs, list):
        segs = segs.get("segments") or segs.get("trans_result") or []
    return segs


_BODY_FIELDS = ("start_time", "end_time", "content", "speaker", "original_speaker")


def build_patch_body(segments: list[dict], rename_ops: list[RenameOp]) -> tuple[dict, int]:
    ""



    by_speaker = {op.speaker_id: op for op in rename_ops}
    out: list[dict] = []
    changed = 0
    for seg in segments:
        orig = seg.get("original_speaker") or seg.get("speaker")
        speaker = seg.get("speaker")
        op = by_speaker.get(orig)
        new_speaker = speaker
        if op is not None and op.new_name != speaker:
            new_speaker = op.new_name
            changed += 1
        out.append(
            {
                "start_time": seg.get("start_time"),
                "end_time": seg.get("end_time"),
                "content": seg.get("content", ""),
                "speaker": new_speaker,
                "original_speaker": orig,
            }
        )
    return {"trans_result": out, "support_mul_summ": True}, changed









POLISH_SOURCE_TYPE = "transaction_polish"


def read_source_segments(
    file_id: str, wt: str, api_base: str, data_type: str
) -> tuple[list[dict[str, Any]], str]:
    ""



    detail = _http("GET", api_base, f"/file/detail/{file_id}", wt)
    content_list = (detail.get("data") or detail).get("content_list") or []
    item = next((it for it in content_list if it.get("data_type") == data_type), None)
    if not item:
        return [], ""
    data_id = item.get("data_id", "")
    if not item.get("data_link"):
        return [], data_id
    segs = json.loads(_fetch_s3(item["data_link"]))
    if not isinstance(segs, list):
        segs = segs.get("segments") or segs.get("trans_result") or []
    return segs, data_id


def build_polish_segments(
    segments: list[dict], rename_ops: list[RenameOp]
) -> tuple[list[dict], int]:
    ""

    by_speaker = {op.speaker_id: op for op in rename_ops}
    out: list[dict] = []
    changed = 0
    for seg in segments:
        orig = seg.get("original_speaker") or seg.get("speaker")
        op = by_speaker.get(orig)
        if op is not None and op.new_name != seg.get("speaker"):
            out.append({**seg, "speaker": op.new_name})
            changed += 1
        else:
            out.append(seg)
    return out, changed


def write_polish(file_id: str, source_id: str, segments: list[dict], wt: str, api_base: str) -> Any:
    ""

    body = {
        "file_id": file_id,
        "source_id": source_id,
        "source_type": POLISH_SOURCE_TYPE,
        "source_content": json.dumps(segments, ensure_ascii=False),
    }
    return _http("POST", api_base, "/ai/update_source_info", wt, body)


def do_apply_both(file_id: str, rename_ops: list[RenameOp], apply: bool) -> dict[str, Any]:
    ""



    wt, api = get_auth()
    raw_segs = read_segments(file_id, wt, api)
    raw_body, raw_changed = build_patch_body(raw_segs, rename_ops)
    pol_segs, pol_id = read_source_segments(file_id, wt, api, POLISH_SOURCE_TYPE)
    pol_new, pol_changed = build_polish_segments(pol_segs, rename_ops)
    if raw_changed == 0 and pol_changed == 0:
        raise WriteError("abort-zero-match: no segment matches (raw+polish), not writing")
    if not apply:
        print(
            f"DRY-RUN: raw {raw_changed} segments, polish {pol_changed} segments. "
            "No write. Use --apply to write."
        )
        return {"dry_run": True, "raw_changed": raw_changed, "polish_changed": pol_changed}
    _backup_segments(file_id, raw_segs)
    resp_raw = _http("PATCH", api, f"/file/{file_id}", wt, raw_body) if raw_changed else None
    resp_pol = write_polish(file_id, pol_id, pol_new, wt, api) if (pol_changed and pol_id) else None
    print(f"APPLY both: raw={raw_changed} polish={pol_changed}")
    return {
        "dry_run": False,
        "raw_changed": raw_changed,
        "polish_changed": pol_changed,
        "raw_resp": str(resp_raw)[:80],
        "polish_resp": str(resp_pol)[:80],
    }


def parse_rename_arg(arg: str) -> RenameOp:
    ""
    if "=" not in arg:
        raise WriteError(f"rename format expected 'Speaker N=Name', got {arg!r}")
    sid, name = arg.split("=", 1)
    return RenameOp(speaker_id=sid.strip(), new_name=name.strip())







def current_labels(segments: list[dict]) -> dict[str, str]:
    ""
    out: dict[str, str] = {}
    for seg in segments:
        orig = seg.get("original_speaker") or seg.get("speaker")
        if orig and orig not in out:
            out[orig] = seg.get("speaker")
    return out


def do_diff(file_id: str, rename_ops: list[RenameOp]) -> None:
    wt, api = get_auth()
    segs = read_segments(file_id, wt, api)
    _body, changed = build_patch_body(segs, rename_ops)
    labels = current_labels(segs)
    print(f"File {file_id}: {len(segs)} segments. Current speakers: {labels}")
    for op in rename_ops:
        cur = labels.get(op.speaker_id, "(absent)")
        print(f"  {op.speaker_id}: '{cur}' -> '{op.new_name}'")
    print(f"Segments that would change: {changed}")
    if changed == 0:
        print("ABORT: zero segments match (no original_speaker corresponds).")


def do_apply(file_id: str, rename_ops: list[RenameOp], apply: bool) -> dict[str, Any]:
    wt, api = get_auth()
    segs = read_segments(file_id, wt, api)
    body, changed = build_patch_body(segs, rename_ops)
    if changed == 0:
        raise WriteError("abort-zero-match: no segment matches, not writing")
    if not apply:
        print(
            f"DRY-RUN: {changed} segments would change. No write. Use --apply to write."
        )
        return {"dry_run": True, "changed": changed}

    _backup_segments(file_id, segs)
    print(f"APPLY: PATCH /file/{file_id} ({changed} segments)...")
    resp = _http("PATCH", api, f"/file/{file_id}", wt, body)
    print(f"  PATCH ok. Response: {str(resp)[:120]}")
    return {"dry_run": False, "changed": changed, "response": resp}


def _backup_segments(file_id: str, segments: list[dict]) -> None:
    ""
    try:
        from tools.plaud.pl_backup import backup_transcript, file_bytes_fetcher
    except ImportError:  # pragma: no cover
        from pl_backup import backup_transcript, file_bytes_fetcher  # type: ignore[no-redef]
    import tempfile

    raw = json.dumps(segments, ensure_ascii=False).encode("utf-8")
    tmp = Path(tempfile.mkdtemp()) / "seg.json"
    tmp.write_bytes(raw)
    res = backup_transcript(file_id, file_bytes_fetcher(tmp))
    print(f"  Backup: {res.sha256_pre[:12]}... ({res.byte_len} bytes)")


def do_roundtrip(file_id: str, speaker_id: str, apply: bool) -> None:
    ""


    wt, api = get_auth()
    segs = read_segments(file_id, wt, api)
    labels = current_labels(segs)
    original = labels.get(speaker_id)
    if original is None:
        raise WriteError(f"{speaker_id} not present in the file. Speakers: {labels}")
    sentinel = "__ROUNDTRIP_TEST__"
    print(f"Round-trip on {file_id}: {speaker_id} '{original}' -> '{sentinel}' -> '{original}'")
    if not apply:
        print("DRY-RUN: no write. Use --apply to run the real round-trip.")
        return

    do_apply(file_id, [RenameOp(speaker_id=speaker_id, new_name=sentinel)], apply=True)

    segs_b = read_segments(file_id, wt, api)
    lab_b = current_labels(segs_b).get(speaker_id)
    print(f"  Check after write: {speaker_id} = '{lab_b}' (expected '{sentinel}')")
    ok_b = lab_b == sentinel

    emb_before = sum(1 for s in segs if s.get("embeddingKey"))
    emb_after = sum(1 for s in segs_b if s.get("embeddingKey"))
    print(
        f"  embeddingKey: before {emb_before}, after {emb_after} (preserved: {emb_before == emb_after})"
    )

    do_apply(file_id, [RenameOp(speaker_id=speaker_id, new_name=original)], apply=True)
    segs_a = read_segments(file_id, wt, api)
    lab_a = current_labels(segs_a).get(speaker_id)
    ok_a = lab_a == original
    print(f"  Check after revert: {speaker_id} = '{lab_a}' (expected '{original}')")
    print(
        f"ROUND-TRIP RESULT: write={'OK' if ok_b else 'FAIL'} revert={'OK' if ok_a else 'FAIL'} "
        f"net-zero={'OK' if ok_a else 'WARNING'}"
    )


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Plaud write client (speaker rename)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pd = sub.add_parser("diff")
    pd.add_argument("file_id")
    pd.add_argument("renames", nargs="+")
    pa = sub.add_parser("apply")
    pa.add_argument("file_id")
    pa.add_argument("renames", nargs="+")
    pa.add_argument("--apply", action="store_true")
    pb = sub.add_parser("apply-both", help="rename on RAW + POLISHED (transcriptions)")
    pb.add_argument("file_id")
    pb.add_argument("renames", nargs="+")
    pb.add_argument("--apply", action="store_true")
    pr = sub.add_parser("roundtrip")
    pr.add_argument("file_id")
    pr.add_argument("speaker_id")
    pr.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.cmd == "diff":
        do_diff(args.file_id, [parse_rename_arg(a) for a in args.renames])
    elif args.cmd == "apply":
        do_apply(args.file_id, [parse_rename_arg(a) for a in args.renames], apply=args.apply)
    elif args.cmd == "apply-both":
        do_apply_both(args.file_id, [parse_rename_arg(a) for a in args.renames], apply=args.apply)
    elif args.cmd == "roundtrip":
        do_roundtrip(args.file_id, args.speaker_id, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
