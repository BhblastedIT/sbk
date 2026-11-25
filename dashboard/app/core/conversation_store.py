""





from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sbk_config import DATA_ROOT

logger = logging.getLogger("dashboard.chat")

MAX_CONVERSATIONS = 50
CONVERSATIONS_DIR = DATA_ROOT / "conversations"


# Title of a conversation before its first message. Older stores wrote the Italian one.
NEW_TITLE = "New conversation"
OLD_NEW_TITLES = ("Nuova conversazione",)


class ConversationStore:
    ""


    _VALID_ID = re.compile(r"^[a-f0-9][a-f0-9\-]+$")

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or CONVERSATIONS_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}
        self._lock = threading.RLock()

    def _file_path(self, conv_id: str) -> Path | None:
        ""
        if not self._VALID_ID.match(conv_id):
            logger.warning("Invalid conversation ID rejected: %s", conv_id[:50])
            return None
        return self.base_dir / f"{conv_id}.json"

    def _load(self, conv_id: str) -> dict | None:
        ""
        with self._lock:
            if conv_id in self._cache:

                return self._cache[conv_id]
            fp = self._file_path(conv_id)
            if fp is None:
                return None
            if fp.exists():
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                    self._cache[conv_id] = data
                    return data
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load conversation %s: %s", conv_id, e)
            return None

    def _save(self, conv_id: str) -> None:
        ""
        data = self._cache.get(conv_id)
        if data is None:
            return
        fp = self._file_path(conv_id)
        if fp is None:
            return
        try:

            fd, tmp_path = tempfile.mkstemp(dir=str(self.base_dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, default=str)
                os.replace(tmp_path, str(fp))
            except BaseException:

                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            logger.warning("Failed to save conversation %s: %s", conv_id, e)

    def create(self, conv_id: str | None = None) -> dict:
        ""
        cid = conv_id or str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        conv = {
            "id": cid,
            "title": NEW_TITLE,
            "created": now,
            "updated": now,
            "messages": [],
        }
        self._cache[cid] = conv
        self._save(cid)
        self._prune()
        return conv

    def get(self, conv_id: str) -> dict | None:
        ""
        return self._load(conv_id)

    def get_or_create(self, conv_id: str) -> dict:
        ""
        conv = self._load(conv_id)
        if conv is None:
            conv = self.create(conv_id)
        return conv

    def add_message(self, conv_id: str, role: str, content) -> None:
        ""
        with self._lock:
            conv = self._load(conv_id)
            if conv is None:
                return
            conv["messages"].append({"role": role, "content": content})
            conv["updated"] = datetime.now(UTC).isoformat()

            if role == "user" and conv["title"] in (NEW_TITLE, *OLD_NEW_TITLES):
                text = content if isinstance(content, str) else str(content)
                conv["title"] = text[:60].strip() or NEW_TITLE
            self._save(conv_id)

    def set_messages(self, conv_id: str, messages: list[dict]) -> None:
        ""
        with self._lock:
            conv = self._load(conv_id)
            if conv is None:
                return
            conv["messages"] = messages
            conv["updated"] = datetime.now(UTC).isoformat()
            self._save(conv_id)

    def get_messages(self, conv_id: str) -> list[dict]:
        ""
        conv = self._load(conv_id)
        if conv is None:
            return []
        return list(conv["messages"])

    def list_all(self) -> list[dict]:
        ""
        convs = []
        for fp in self.base_dir.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                convs.append(
                    {
                        "id": data["id"],
                        "title": data.get("title", "Untitled"),
                        "created": data.get("created", ""),
                        "updated": data.get("updated", ""),
                        "message_count": len(data.get("messages", [])),
                    }
                )
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        convs.sort(key=lambda c: c.get("updated", ""), reverse=True)
        return convs

    def delete(self, conv_id: str) -> bool:
        ""
        with self._lock:
            self._cache.pop(conv_id, None)
            fp = self._file_path(conv_id)
            if fp is None:
                return False
            if fp.exists():
                try:
                    fp.unlink()
                    return True
                except OSError:
                    return False
            return False

    def _prune(self) -> None:
        ""




        all_convs = self.list_all()


        now = datetime.now(UTC)
        one_hour_ago = now - __import__("datetime").timedelta(hours=1)
        kept = []
        for conv in all_convs:
            if conv.get("message_count", 0) == 0:
                created = conv.get("created", "")
                if created:
                    try:
                        dt = datetime.fromisoformat(created)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=UTC)
                        if dt < one_hour_ago:
                            self.delete(conv["id"])
                            continue
                    except (ValueError, TypeError):
                        pass
            kept.append(conv)


        if len(kept) <= MAX_CONVERSATIONS:
            return
        for conv in kept[MAX_CONVERSATIONS:]:
            self.delete(conv["id"])
