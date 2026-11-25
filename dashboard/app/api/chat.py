""














from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any

import anthropic
from fastapi import APIRouter, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.core.chat_tools import (
    TOOL_LABELS,
    TOOLS,
    apply_budget,
    execute_tool_raw,
    get_system_prompt,
    reset_context_budget_with_size,
)
from app.core.file_handler import get_content_blocks, process_upload
from app.core.task_utils import safe_create_task

logger = logging.getLogger("dashboard.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_HISTORY = 30
MAX_TOOL_ROUNDS = 10
TOOL_TIMEOUT = 45
API_TIMEOUT = 60
HEARTBEAT_INTERVAL = 15
IDLE_PING_INTERVAL = 20
CHAT_MODEL = os.getenv("SBK_CHAT_MODEL", "claude-sonnet-4-5-20250929")



MODEL_OPTIONS = {
    "auto": None,
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-5-20250929",
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
}

MODEL_CONTEXT_BUDGETS = {
    "claude-sonnet-4-5-20250929": 80_000,
    "claude-opus-4-6": 120_000,
    "claude-haiku-4-5-20251001": 80_000,
}

_COMPLEX_PATTERNS = re.compile(
    r"(?:dimmi di|parlami di|chi [eè]|analizza|confronta|strategia|approfondisci|"
    r"panoramica|deep dive|relazione tra|profilo di|tutto su|overview|riassumi tutto|"
    r"fammi un quadro|tell me about|who is)",
    re.IGNORECASE,
)
_SIMPLE_PATTERNS = re.compile(
    r"^(?:ciao|grazie|ok|si|no|quando|dove|quanti|stato|hey|buongiorno|salve)[\s?!.,]*$",
    re.IGNORECASE,
)

MODEL_LABELS = {
    "claude-sonnet-4-5-20250929": "Sonnet 4.5",
    "claude-opus-4-6": "Opus 4.6",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
}


def classify_query_complexity(text: str) -> str:
    ""
    text = text.strip()
    if _SIMPLE_PATTERNS.match(text) or len(text) < 15:
        return "claude-sonnet-4-5-20250929"
    if _COMPLEX_PATTERNS.search(text):
        return "claude-opus-4-6"
    return "claude-sonnet-4-5-20250929"





_state_lock = asyncio.Lock()


_session_ws: dict[str, WebSocket | None] = {}


_pending_turns: set[str] = set()





@router.get("/status")
def chat_status():
    ""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    has_key = bool(api_key and api_key.startswith("sk-"))
    return JSONResponse({"available": has_key, "model": CHAT_MODEL})


@router.get("/conversations")
def list_conversations(request: Request):
    ""
    store = request.app.state.conversation_store
    return JSONResponse({"conversations": store.list_all()})


@router.post("/conversations")
def create_conversation(request: Request):
    ""
    store = request.app.state.conversation_store
    conv = store.create()
    return JSONResponse({"id": conv["id"], "title": conv["title"]})


@router.delete("/conversations/{conv_id}")
def delete_conversation(request: Request, conv_id: str):
    ""
    store = request.app.state.conversation_store
    deleted = store.delete(conv_id)
    if not deleted:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)
    return JSONResponse({"ok": True})


@router.post("/upload/{conv_id}")
async def upload_file(conv_id: str, file: UploadFile):
    ""
    result = await process_upload(file, conv_id)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)





async def _ws_send(ws: WebSocket, data: dict) -> bool:
    ""
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False


async def _try_send(session_id: str, data: dict) -> bool:
    ""








    ws = _session_ws.get(session_id)
    if ws is None:
        return False
    try:
        data["session_id"] = session_id
        await ws.send_json(data)
        return True
    except Exception:
        _session_ws[session_id] = None
        return False


async def _send_heartbeat_session(session_id: str, stop_event: asyncio.Event):
    ""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL)
        except TimeoutError:
            await _try_send(session_id, {"type": "heartbeat"})


async def _send_idle_ping(ws: WebSocket, stop_event: asyncio.Event):
    ""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=IDLE_PING_INTERVAL)
        except TimeoutError:
            if not await _ws_send(ws, {"type": "ping"}):
                break


async def _execute_tool_with_timeout(bridge, tool_name: str, tool_input: dict) -> str:
    ""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(execute_tool_raw, bridge, tool_name, tool_input),
            timeout=TOOL_TIMEOUT,
        )
    except TimeoutError:
        logger.warning("Tool %s timed out after %ds", tool_name, TOOL_TIMEOUT)
        return json.dumps(
            {"error": f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT}s. Try rephrasing."},
            ensure_ascii=False,
        )


def _trim_conversation(messages: list[dict], max_messages: int = MAX_HISTORY) -> list[dict]:
    ""




    if len(messages) <= max_messages:
        return messages

    trimmed = messages[-max_messages:]


    if trimmed and isinstance(trimmed[0].get("content"), list):
        content = trimmed[0]["content"]
        if isinstance(content, list) and content and isinstance(content[0], dict):
            if content[0].get("type") == "tool_result":
                idx = messages.index(trimmed[0])
                if idx > 0:
                    trimmed.insert(0, messages[idx - 1])

    return trimmed





@router.websocket("/ws/chat")
async def chat_websocket(ws: WebSocket):
    ""




    await ws.accept()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or not api_key.startswith("sk-"):
        await _ws_send(
            ws, {"type": "error", "content": "ANTHROPIC_API_KEY not configured in .env"}
        )
        await ws.close()
        return

    client = anthropic.AsyncAnthropic(api_key=api_key)
    store = ws.app.state.conversation_store
    bridge = ws.app.state.bridge
    session_id = None
    active_sessions: set[str] = set()
    owner_mode = False
    selected_model = "auto"


    idle_stop = asyncio.Event()
    idle_task = safe_create_task(_send_idle_ping(ws, idle_stop), name="chat-idle-ping")

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "init":

                session_id = str(uuid.uuid4())
                store.create(session_id)
                _session_ws[session_id] = ws
                active_sessions.add(session_id)
                await _ws_send(ws, {"type": "session", "session_id": session_id})

            elif msg_type == "resume":



                resume_id = data.get("session_id", "")
                conv = store.get(resume_id) if resume_id else None
                if conv:
                    session_id = resume_id
                    _session_ws[session_id] = ws
                    active_sessions.add(session_id)

                    for msg in conv["messages"]:
                        role = msg["role"]
                        content = msg["content"]
                        if role == "user":
                            if isinstance(content, str):
                                await _ws_send(
                                    ws,
                                    {
                                        "type": "history_user",
                                        "content": content,
                                        "session_id": session_id,
                                    },
                                )
                            elif isinstance(content, list):

                                is_tool_result = any(
                                    isinstance(b, dict) and b.get("type") == "tool_result"
                                    for b in content
                                )
                                if is_tool_result:
                                    continue

                                text_parts = [
                                    b["text"]
                                    for b in content
                                    if isinstance(b, dict) and b.get("type") == "text"
                                ]
                                has_attachments = any(
                                    isinstance(b, dict)
                                    and b.get("type") not in ("text", "tool_result")
                                    for b in content
                                )
                                await _ws_send(
                                    ws,
                                    {
                                        "type": "history_user",
                                        "content": "\n".join(text_parts),
                                        "has_attachments": has_attachments,
                                        "session_id": session_id,
                                    },
                                )
                        elif role == "assistant" and isinstance(content, str):
                            await _ws_send(
                                ws,
                                {
                                    "type": "history_assistant",
                                    "content": content,
                                    "session_id": session_id,
                                },
                            )


                    if session_id in _pending_turns:
                        await _ws_send(ws, {"type": "processing", "session_id": session_id})
                    await _ws_send(ws, {"type": "session", "session_id": session_id})
                else:

                    session_id = resume_id or str(uuid.uuid4())
                    store.create(session_id)
                    _session_ws[session_id] = ws
                    active_sessions.add(session_id)
                    await _ws_send(ws, {"type": "session", "session_id": session_id})

            elif msg_type == "message":
                user_text = data.get("content", "").strip()
                if not user_text:
                    continue

                attachment_ids = data.get("attachments", [])


                sid = data.get("session_id") or session_id


                if sid is None:
                    sid = str(uuid.uuid4())
                    store.create(sid)
                    _session_ws[sid] = ws
                    active_sessions.add(sid)
                    await _ws_send(ws, {"type": "session", "session_id": sid})


                if sid not in active_sessions:
                    store.get_or_create(sid)
                    _session_ws[sid] = ws
                    active_sessions.add(sid)

                session_id = sid


                async with _state_lock:
                    if session_id in _pending_turns:
                        await _ws_send(
                            ws,
                            {
                                "type": "error",
                                "content": "Processing in progress, please wait...",
                                "session_id": session_id,
                            },
                        )
                        continue

                    _pending_turns.add(session_id)


                if attachment_ids:
                    content_blocks = [{"type": "text", "text": user_text}]
                    content_blocks.extend(get_content_blocks(attachment_ids))
                    store.add_message(session_id, "user", content_blocks)
                else:
                    store.add_message(session_id, "user", user_text)


                messages = store.get_messages(session_id)
                messages = _trim_conversation(messages)
                store.set_messages(session_id, messages)



                safe_create_task(
                    _handle_chat_turn(
                        bridge,
                        client,
                        store,
                        session_id,
                        owner_mode=owner_mode,
                        selected_model=selected_model,
                        user_text=user_text,
                    ),
                    name=f"chat-turn-{session_id[:8]}",
                )

            elif msg_type == "set_model":
                model_val = data.get("model", "auto")
                if model_val in MODEL_OPTIONS:
                    selected_model = model_val
                    await _ws_send(ws, {"type": "model_set", "model": model_val})
                else:
                    await _ws_send(
                        ws, {"type": "error", "content": f"Model '{model_val}' is not valid."}
                    )

            elif msg_type == "set_owner_mode":
                owner_mode = data.get("enabled", False)
                await _ws_send(ws, {"type": "owner_mode", "enabled": owner_mode})

            elif msg_type == "clear":
                if session_id:
                    store.delete(session_id)
                    active_sessions.discard(session_id)
                session_id = str(uuid.uuid4())
                store.create(session_id)
                _session_ws[session_id] = ws
                active_sessions.add(session_id)
                await _ws_send(ws, {"type": "cleared", "session_id": session_id})

    except WebSocketDisconnect:
        logger.info(
            "Chat WebSocket disconnected (sessions: %s)",
            ", ".join(s[:8] for s in active_sessions) if active_sessions else "none",
        )
    except Exception as e:
        logger.exception("Chat WebSocket error")
        await _ws_send(ws, {"type": "error", "content": "Internal server error"})
    finally:


        for sid in active_sessions:
            if _session_ws.get(sid) is ws:
                _session_ws[sid] = None
        idle_stop.set()
        idle_task.cancel()
        try:
            await idle_task
        except asyncio.CancelledError:
            pass





async def _handle_chat_turn(
    bridge,
    client: anthropic.AsyncAnthropic,
    store,
    session_id: str,
    *,
    owner_mode: bool = False,
    selected_model: str = "auto",
    user_text: str = "",
):
    ""







    messages = store.get_messages(session_id)


    messages = _trim_conversation(messages)
    store.set_messages(session_id, messages)


    if selected_model == "auto" or selected_model not in MODEL_OPTIONS:
        resolved_model = classify_query_complexity(user_text)
        auto_resolved = True
    else:
        resolved_model = MODEL_OPTIONS[selected_model]
        auto_resolved = False


    budget = MODEL_CONTEXT_BUDGETS.get(resolved_model, 80_000)
    reset_context_budget_with_size(budget)


    model_label = MODEL_LABELS.get(resolved_model, resolved_model)
    await _try_send(
        session_id,
        {
            "type": "model_info",
            "model": resolved_model,
            "label": model_label,
            "auto": auto_resolved,
        },
    )


    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(_send_heartbeat_session(session_id, heartbeat_stop))

    try:
        for _round in range(MAX_TOOL_ROUNDS + 1):
            full_text = ""
            tool_calls = []
            current_tool = None
            stop_reason = None

            try:


                create_kwargs: dict[str, Any] = {
                    "model": resolved_model,
                    "max_tokens": 4096,
                    "system": get_system_prompt(owner_mode),
                    "messages": messages,
                    "stream": True,
                }
                if _round < MAX_TOOL_ROUNDS:
                    create_kwargs["tools"] = TOOLS

                stream = await asyncio.wait_for(
                    client.messages.create(**create_kwargs),
                    timeout=API_TIMEOUT,
                )

                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input_json": "",
                            }
                            label = TOOL_LABELS.get(
                                event.content_block.name, event.content_block.name
                            )

                            await _try_send(
                                session_id,
                                {
                                    "type": "tool_start",
                                    "name": event.content_block.name,
                                    "label": label,
                                    "tool_id": event.content_block.id,
                                },
                            )

                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            full_text += event.delta.text

                            await _try_send(
                                session_id,
                                {"type": "token", "content": event.delta.text},
                            )
                        elif event.delta.type == "input_json_delta":
                            if current_tool:
                                current_tool["input_json"] += event.delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_tool:
                            tool_calls.append(current_tool)
                            current_tool = None

                    elif event.type == "message_delta":
                        stop_reason = event.delta.stop_reason

            except TimeoutError:
                logger.warning("Anthropic API timeout after %ds", API_TIMEOUT)
                await _try_send(
                    session_id,
                    {
                        "type": "error",
                        "content": f"API timeout after {API_TIMEOUT}s. Try again.",
                    },
                )
                return
            except anthropic.RateLimitError:
                await _try_send(
                    session_id,
                    {
                        "type": "error",
                        "content": "Anthropic rate limit reached. Try again in a few seconds.",
                    },
                )
                return
            except anthropic.AuthenticationError:
                await _try_send(
                    session_id,
                    {
                        "type": "error",
                        "content": "Invalid Anthropic API key. Check ANTHROPIC_API_KEY in .env.",
                    },
                )
                return
            except anthropic.APIError as e:
                error_msg = getattr(e, "message", str(e))
                await _try_send(
                    session_id,
                    {
                        "type": "error",
                        "content": f"Anthropic API error: {error_msg}",
                    },
                )
                return


            if stop_reason != "tool_use" or not tool_calls:
                if full_text:

                    store.add_message(session_id, "assistant", full_text)

                sent = await _try_send(
                    session_id,
                    {"type": "done", "full_text": full_text if full_text else None},
                )

                if not sent and full_text:
                    await asyncio.sleep(2)
                    await _try_send(
                        session_id,
                        {"type": "done", "full_text": full_text},
                    )
                return


            if _round >= MAX_TOOL_ROUNDS:
                if full_text:
                    store.add_message(session_id, "assistant", full_text)
                sent = await _try_send(
                    session_id,
                    {"type": "done", "full_text": full_text if full_text else None},
                )
                if not sent and full_text:
                    await asyncio.sleep(2)
                    await _try_send(
                        session_id,
                        {"type": "done", "full_text": full_text},
                    )
                return


            assistant_content = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})




            tool_tasks = []
            for tc in tool_calls:
                try:
                    tool_input = json.loads(tc["input_json"]) if tc["input_json"] else {}
                except json.JSONDecodeError:
                    tool_input = {}

                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tool_input,
                    }
                )

                tool_tasks.append((tc, tool_input))


            async def _run_tool(tc_item, t_input):
                return await _execute_tool_with_timeout(bridge, tc_item["name"], t_input)

            raw_results = await asyncio.gather(*[_run_tool(tc, ti) for tc, ti in tool_tasks])


            tool_results = []
            for (tc, _), raw_result in zip(tool_tasks, raw_results):
                budgeted = apply_budget(tc["name"], raw_result)

                await _try_send(
                    session_id,
                    {
                        "type": "tool_done",
                        "name": tc["name"],
                        "label": TOOL_LABELS.get(tc["name"], tc["name"]),
                        "tool_id": tc["id"],
                    },
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": budgeted,
                    }
                )


            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
            store.set_messages(session_id, messages)


        await _try_send(session_id, {"type": "done", "full_text": None})

    finally:


        _pending_turns.discard(session_id)
        heartbeat_stop.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
