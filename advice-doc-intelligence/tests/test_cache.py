from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from advicedoc.cache import CachedChatModel, request_key
from advicedoc.llm import ChatMessage, ChatResponse


class CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "counting"

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> ChatResponse:
        self.calls += 1
        return ChatResponse(
            text=f"answer {self.calls} to {messages[-1].content} @{max_tokens}/{temperature}",
            model="counting",
            prompt_tokens=3,
            completion_tokens=4,
            latency_s=0.5,
        )


def test_identical_requests_hit_the_cache(tmp_path: Path) -> None:
    inner = CountingModel()
    cached = CachedChatModel(inner, tmp_path / "cache" / "responses.sqlite")
    msgs = [ChatMessage("user", "hello")]
    first = cached.chat(msgs, max_tokens=10)
    second = cached.chat(msgs, max_tokens=10)
    assert first == second
    assert inner.calls == 1
    assert (cached.hits, cached.misses) == (1, 1)
    assert cached.name == "counting"


def test_cache_key_covers_request_parameters(tmp_path: Path) -> None:
    inner = CountingModel()
    cached = CachedChatModel(inner, tmp_path / "c.sqlite")
    msgs = [ChatMessage("user", "hello")]
    cached.chat(msgs, max_tokens=10)
    cached.chat(msgs, max_tokens=20)
    cached.chat([ChatMessage("user", "hello!")], max_tokens=10)
    assert inner.calls == 3
    assert request_key("m", msgs, max_tokens=10, temperature=0.0) != request_key(
        "other", msgs, max_tokens=10, temperature=0.0
    )


def test_sampled_requests_bypass_the_cache(tmp_path: Path) -> None:
    inner = CountingModel()
    cached = CachedChatModel(inner, tmp_path / "c.sqlite")
    msgs = [ChatMessage("user", "hello")]
    cached.chat(msgs, temperature=0.7)
    cached.chat(msgs, temperature=0.7)
    assert inner.calls == 2
    assert (cached.hits, cached.misses) == (0, 0)


def test_cache_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    msgs = [ChatMessage("user", "persist")]
    first = CachedChatModel(CountingModel(), path)
    answer = first.chat(msgs)
    first.close()
    second_inner = CountingModel()
    second = CachedChatModel(second_inner, path)
    assert second.chat(msgs) == answer
    assert second_inner.calls == 0
    second.close()
