"""A content-addressed cache in front of any ``ChatModel``.

Greedy decoding is deterministic, and the drafting strategies share prompts (``verified``
re-runs the ``extract_then_compose`` calls before its repair pass), so caching model answers
keyed by the exact request halves the cost of an evaluation run and makes a re-run free.
Only ``temperature == 0`` requests are cached; anything sampled bypasses the cache.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from filenote.llm import ChatMessage, ChatModel, ChatResponse


def request_key(
    model_name: str, messages: Sequence[ChatMessage], *, max_tokens: int, temperature: float
) -> str:
    payload = {
        "model": model_name,
        "messages": [m.to_dict() for m in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class CachedChatModel:
    """Wraps a model; identical requests are served from a SQLite file after the first call."""

    def __init__(self, inner: ChatModel, path: Path) -> None:
        self._inner = inner
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, response TEXT NOT NULL)"
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    @property
    def name(self) -> str:
        return self._inner.name

    def ready(self) -> bool:
        return self._inner.ready()

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1800,
        temperature: float = 0.0,
    ) -> ChatResponse:
        if temperature != 0.0:
            return self._inner.chat(messages, max_tokens=max_tokens, temperature=temperature)
        key = request_key(self.name, messages, max_tokens=max_tokens, temperature=temperature)
        row = self._conn.execute("SELECT response FROM responses WHERE key = ?", (key,)).fetchone()
        if row is not None:
            self.hits += 1
            return ChatResponse(**json.loads(row[0]))
        response = self._inner.chat(messages, max_tokens=max_tokens, temperature=temperature)
        self.misses += 1
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (key, response) VALUES (?, ?)",
            (key, json.dumps(asdict(response))),
        )
        self._conn.commit()
        return response

    def close(self) -> None:
        self._conn.close()
