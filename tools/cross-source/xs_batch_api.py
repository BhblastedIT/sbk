""















from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("sbk-batch-api")



MAX_BATCH_SIZE_REQUESTS = 50_000
MAX_BATCH_SIZE_BYTES = 200_000_000


MAX_CUSTOM_ID_LEN = 64


SONNET_MODEL = "claude-sonnet-4-5-20250929"
HAIKU_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class BatchRequest:
    ""

    custom_id: str
    user_content: str
    system_prompt: str
    model: str = SONNET_MODEL
    max_tokens: int = 8192
    temperature: float = 0.1


def _shorten_id(custom_id: str) -> str:
    ""



    import re


    safe = custom_id.replace("/", "--")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", safe)

    if len(safe) <= MAX_CUSTOM_ID_LEN:
        return safe


    h = hashlib.md5(custom_id.encode()).hexdigest()[:16]
    prefix = safe[:20]

    suffix = ""
    if "--chunk_" in safe:
        suffix = "_c" + safe.split("--chunk_")[-1][:6]
    result = f"{prefix}_{h}{suffix}"
    return result[:MAX_CUSTOM_ID_LEN]


def id_stabile(sorgente: str, documento: str, pezzo: int, prefisso: str = "") -> str:
    ""





    impronta = hashlib.sha1(documento.encode()).hexdigest()[:16]
    return f"{prefisso}{sorgente}/{impronta}/chunk_{pezzo}"


def _estimate_request_bytes(req: BatchRequest) -> int:
    ""



    return 200 + len(req.system_prompt) + len(req.user_content)


def _get_client():
    ""
    from xs_anthropic_client import get_client

    return get_client(timeout=600.0)





_CHIAVE_DEL_LOTTO: dict[str, str] = {}
CHIAVE_DEI_LOTTI_VECCHI = "sbk"


def _usa_la_chiave_del_lotto(batch_id: str) -> None:
    nome = _CHIAVE_DEL_LOTTO.get(batch_id)
    if not nome:
        return
    from xs_anthropic_client import usa_chiave

    usa_chiave(nome)


def _crea_lotto(richieste: list, label: str) -> str:
    ""

    from xs_anthropic_client import chiave_in_uso, classify_error, passa_alla_riserva

    try:
        batch = _get_client().messages.batches.create(requests=richieste)
    except Exception as e:
        prima = chiave_in_uso()
        if classify_error(e) is None or not passa_alla_riserva():
            raise
        log.warning(
            f"[{label}] key «{prima}» is not working ({type(e).__name__}): retrying with «{chiave_in_uso()}»"
        )
        batch = _get_client().messages.batches.create(requests=richieste)
    nome = chiave_in_uso()
    if nome:
        _CHIAVE_DEL_LOTTO[batch.id] = nome
    return batch.id


def _build_single_api_request(req: BatchRequest, short_id: str):
    ""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    return Request(
        custom_id=short_id,
        params=MessageCreateParamsNonStreaming(
            model=req.model,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            system=[
                {
                    "type": "text",
                    "text": req.system_prompt,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            ],
            messages=[{"role": "user", "content": req.user_content}],
        ),
    )


class BudgetSuperato(RuntimeError):
    ""



def uscita_media(
    cartella: Path | None, escludi: tuple[str, ...] = ("_consolidated",)
) -> int | None:
    ""




    if cartella is None or not Path(cartella).is_dir():
        return None
    totale = n = 0
    for radice, _cartelle, nomi in os.walk(cartella):
        for nome in nomi:
            if not nome.endswith(".json") or nome.startswith("batch-state"):
                continue
            if any(x in nome for x in escludi):
                continue
            try:
                totale += os.path.getsize(os.path.join(radice, nome))
            except OSError:
                continue
            n += 1
    return round(totale / n / 4) if n >= 50 else None


def stima_costo_richieste(requests, uscita_token: int | None = None) -> dict:
    ""







    from xs_l3_common import PRICING

    n = 0
    tot_in = 0
    tot_out = 0
    costo = 0.0
    for r in requests:
        n += 1
        t_in = (len(r.user_content) + len(r.system_prompt)) / 4
        t_out = min(uscita_token, r.max_tokens) if uscita_token else r.max_tokens / 4
        pricing = PRICING.get(r.model, {"input": 3.0, "output": 15.0})
        costo += (t_in * pricing["input"] + t_out * pricing["output"]) / 1_000_000
        tot_in += t_in
        tot_out += t_out
    return {
        "richieste": n,
        "est_input_tokens": int(tot_in),
        "est_output_tokens": int(tot_out),
        "est_cost_usd_batch": round(costo * 0.5, 2),
        "est_cost_usd_sync": round(costo, 2),
        "uscita_token": uscita_token,
    }


def submit_batch(
    requests: list[BatchRequest],
    label: str = "sbk",
    al_lotto=None,
) -> tuple[list[str], dict[str, str]]:
    ""






    id_mapping: dict[str, str] = {}
    batch_ids = []

    current_batch = []
    current_bytes = 0

    for req in requests:
        short_id = _shorten_id(req.custom_id)
        id_mapping[short_id] = req.custom_id

        api_req = _build_single_api_request(req, short_id)
        req_bytes = _estimate_request_bytes(req)


        if current_batch and (
            len(current_batch) >= MAX_BATCH_SIZE_REQUESTS
            or current_bytes + req_bytes > MAX_BATCH_SIZE_BYTES
        ):

            batch_id = _crea_lotto(current_batch, label)
            batch_ids.append(batch_id)
            if al_lotto:
                al_lotto(batch_ids, id_mapping)
            log.info(
                f"[{label}] Batch {batch_id} submitted: {len(current_batch)} requests "
                f"(~{current_bytes / 1_000_000:.1f}MB)"
            )
            current_batch = []
            current_bytes = 0

        current_batch.append(api_req)
        current_bytes += req_bytes


    if current_batch:
        batch_id = _crea_lotto(current_batch, label)
        batch_ids.append(batch_id)
        if al_lotto:
            al_lotto(batch_ids, id_mapping)
        log.info(
            f"[{label}] Batch {batch_id} submitted: {len(current_batch)} requests "
            f"(~{current_bytes / 1_000_000:.1f}MB)"
        )

    log.info(f"[{label}] Total: {len(batch_ids)} batch(es), {len(requests)} requests")
    return batch_ids, id_mapping


def poll_batch(
    batch_id: str,
    label: str = "",
    poll_interval: int = 30,
) -> dict:
    ""
    _usa_la_chiave_del_lotto(batch_id)
    client = _get_client()
    prefix = f"[{label}] " if label else ""

    while True:
        batch = client.messages.batches.retrieve(batch_id)
        c = batch.request_counts
        total = c.processing + c.succeeded + c.errored + c.canceled + c.expired
        done = c.succeeded + c.errored + c.canceled + c.expired
        pct = (done / max(1, total)) * 100

        log.info(
            f"{prefix}Batch {batch_id}: {pct:.0f}% | "
            f"ok={c.succeeded} err={c.errored} exp={c.expired} "
            f"processing={c.processing}"
        )

        if batch.processing_status == "ended":
            return {
                "batch_id": batch_id,
                "succeeded": c.succeeded,
                "errored": c.errored,
                "expired": c.expired,
                "canceled": c.canceled,
            }

        time.sleep(poll_interval)


def collect_results(
    batch_ids: list[str],
    id_mapping: dict[str, str] | None = None,
) -> dict[str, dict]:
    ""




    results = {}

    for batch_id in batch_ids:
        _usa_la_chiave_del_lotto(batch_id)
        client = _get_client()
        for result in client.messages.batches.results(batch_id):

            short_id = result.custom_id
            original_id = id_mapping.get(short_id, short_id) if id_mapping else short_id

            entry = {"custom_id": original_id}

            if result.result.type == "succeeded":
                msg = result.result.message
                text = "".join(b.text for b in msg.content if b.type == "text")
                entry["text"] = text
                entry["input_tokens"] = msg.usage.input_tokens
                entry["output_tokens"] = msg.usage.output_tokens
                entry["error"] = None


                cache_read = getattr(msg.usage, "cache_read_input_tokens", 0)
                cache_creation = getattr(msg.usage, "cache_creation_input_tokens", 0)
                if cache_read or cache_creation:
                    entry["cache_read_tokens"] = cache_read
                    entry["cache_creation_tokens"] = cache_creation
            else:
                entry["text"] = None
                entry["input_tokens"] = 0
                entry["output_tokens"] = 0
                entry["error"] = str(getattr(result.result, "error", result.result.type))

            results[original_id] = entry


    ok = sum(1 for r in results.values() if r["error"] is None)
    errs = len(results) - ok
    total_input = sum(r["input_tokens"] for r in results.values())
    total_output = sum(r["output_tokens"] for r in results.values())
    total_cache_read = sum(r.get("cache_read_tokens", 0) for r in results.values())

    log.info(
        f"Collected {len(results)} results: {ok} ok, {errs} errors | "
        f"tokens: {total_input:,} in + {total_output:,} out | "
        f"cache hits: {total_cache_read:,} tokens"
    )

    return results


def run_batch_pipeline(
    requests: list[BatchRequest],
    label: str = "sbk",
    poll_interval: int = 30,
    state_dir: Path | None = None,
    tieni_stato: bool = False,
) -> dict[str, dict]:
    ""







    if not requests:
        log.info(f"[{label}] No requests to process")
        return {}






    stima = stima_costo_richieste(requests, uscita_token=uscita_media(state_dir))
    log.info(
        f"[{label}] pre-submit estimate: {stima['richieste']} req, "
        f"~${stima['est_cost_usd_batch']} batch (${stima['est_cost_usd_sync']} sync)"
    )
    _cap = os.environ.get("SBK_BATCH_MAX_USD")
    if _cap:
        try:
            cap_usd = float(_cap)
        except ValueError:
            cap_usd = None
        if cap_usd is not None and stima["est_cost_usd_batch"] > cap_usd:
            raise BudgetSuperato(
                f"[{label}] estimate ${stima['est_cost_usd_batch']} batch > cap "
                f"SBK_BATCH_MAX_USD=${cap_usd}: submit DENIED (no spend committed)"
            )

    state_file = state_dir / f"batch-state-{label}.json" if state_dir else None


    if state_file:
        saved = load_batch_state(state_file)
        if saved:
            batch_ids, id_mapping = saved
            log.info(f"[{label}] Resuming from saved state: {len(batch_ids)} batch(es)")
        else:
            log.info(f"[{label}] Starting batch pipeline: {len(requests)} requests")
            batch_ids, id_mapping = submit_batch(
                requests,
                label=label,
                al_lotto=lambda b, m: save_batch_state(b, m, state_file),
            )
            save_batch_state(batch_ids, id_mapping, state_file)
            log.info(f"[{label}] State saved to {state_file}")
    else:
        log.info(f"[{label}] Starting batch pipeline: {len(requests)} requests")
        batch_ids, id_mapping = submit_batch(requests, label=label)


    for batch_id in batch_ids:
        poll_batch(batch_id, label=label, poll_interval=poll_interval)


    results = collect_results(batch_ids, id_mapping=id_mapping)


    if state_file and state_file.exists() and not tieni_stato:
        state_file.unlink()
        log.info(f"[{label}] State file cleaned up")

    return results


def chiudi_stato(label: str, state_dir: Path | None) -> None:
    ""


    if state_dir is None:
        return
    state_file = state_dir / f"batch-state-{label}.json"
    if state_file.exists():
        state_file.unlink()
        log.info(f"[{label}] State file cleaned up")


def save_batch_state(batch_ids: list[str], id_mapping: dict[str, str], state_file: Path):
    ""
    state = {
        "batch_ids": batch_ids,
        "id_mapping": id_mapping,
        "submitted_at": time.time(),

        "chiavi": {b: _CHIAVE_DEL_LOTTO[b] for b in batch_ids if b in _CHIAVE_DEL_LOTTO},
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)

    tmp = state_file.with_name(f"{state_file.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, state_file)


def load_batch_state(state_file: Path) -> tuple[list[str], dict[str, str]] | None:
    ""
    if not state_file.exists():
        return None
    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    batch_ids = state.get("batch_ids")
    chiavi = state.get("chiavi") or {}
    for b in batch_ids or []:
        _CHIAVE_DEL_LOTTO.setdefault(b, chiavi.get(b, CHIAVE_DEI_LOTTI_VECCHI))
    return batch_ids, state.get("id_mapping", {})
