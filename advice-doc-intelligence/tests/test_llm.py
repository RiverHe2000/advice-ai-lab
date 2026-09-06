from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import httpx
import pytest

from advicedoc.llm import (
    ChatMessage,
    FakeChatModel,
    HFChatModel,
    ModelError,
    OpenAICompatibleChatModel,
    build_model,
    repair_json,
)


def test_fake_model_resolution_order() -> None:
    def responder(messages: Sequence[ChatMessage]) -> str:
        return f"echo:{messages[-1].content}"

    model = FakeChatModel(responses=["first"], rules=[("hello", "matched")], default=responder)
    assert model.chat([ChatMessage("user", "hello")]).text == "first"
    assert model.chat([ChatMessage("user", "say hello")]).text == "matched"
    assert model.chat([ChatMessage("user", "other")]).text == "echo:other"
    assert FakeChatModel(default="d").chat([]).text == "d"
    assert model.name == "fake" and len(model.calls) == 3
    assert model.chat([ChatMessage("user", "a b c")]).prompt_tokens == 3


@pytest.mark.parametrize(
    ("raw", "expected", "repaired"),
    [
        ('{"a": 1}', {"a": 1}, False),
        ('```json\n{"a": [1, 2]}\n```', {"a": [1, 2]}, True),
        ('Here you go: {"a": 1, "b": "x"} thanks', {"a": 1, "b": "x"}, True),
        ('{"a": 1, "b": [1, 2,],}', {"a": 1, "b": [1, 2]}, True),
        # truncation: close the open string and brackets first (the evaluator or validator
        # then catches the truncated value)
        (
            '{"recs": [{"action": "establish", "name": "Nor',
            {"recs": [{"action": "establish", "name": "Nor"}]},
            True,
        ),
        ('{"a": [1, 2, 3', {"a": [1, 2, 3]}, True),
        ('{"a": 1, "b": {"c": [1,', {"a": 1, "b": {"c": [1]}}, True),
        ('{"a": "unterminated', {"a": "unterminated"}, True),
        ("[1, 2, 3]", [1, 2, 3], False),
    ],
)
def test_repair_json_cases(raw: str, expected: object, repaired: bool) -> None:
    result = repair_json(raw)
    assert result.ok and result.value == expected
    assert result.repaired is repaired


def test_repair_json_failures() -> None:
    assert repair_json("").error == "empty response"
    assert repair_json("no json here").error == "no JSON object found"
    bad = repair_json("{{{{")
    assert not bad.ok and bad.repaired


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_backend_success_reads_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    model = OpenAICompatibleChatModel(
        "http://x/v1/", "m", api_key="secret", client=_transport(handler)
    )
    resp = model.chat([ChatMessage("system", "s"), ChatMessage("user", "u")])
    assert resp.text == '{"ok": true}' and resp.prompt_tokens == 10 and resp.completion_tokens == 3
    assert model.name == "openai[m]"
    model.close()


def test_openai_backend_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    sleeps: list[float] = []
    model = OpenAICompatibleChatModel(
        "http://x/v1", "m", client=_transport(handler), max_retries=3, sleep=sleeps.append
    )
    assert model.chat([ChatMessage("user", "u")]).text == "done"
    assert calls["n"] == 3 and sleeps == [0.5, 1.0]


def test_openai_backend_errors() -> None:
    def bad_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="nope")

    with pytest.raises(ModelError) as exc:
        OpenAICompatibleChatModel("http://x", "m", client=_transport(bad_request)).chat(
            [ChatMessage("user", "u")]
        )
    assert exc.value.status == 400

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelError, match="malformed"):
        OpenAICompatibleChatModel("http://x", "m", client=_transport(malformed)).chat(
            [ChatMessage("user", "u")]
        )

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ModelError, match="giving up"):
        OpenAICompatibleChatModel(
            "http://x", "m", client=_transport(down), max_retries=1, sleep=lambda _s: None
        ).chat([ChatMessage("user", "u")])


def test_build_model_kinds() -> None:
    assert isinstance(build_model("fake"), FakeChatModel)
    openai = build_model("openai", model_name="m", base_url="http://x/v1")
    assert isinstance(openai, OpenAICompatibleChatModel)
    hf = build_model("hf", model_name="D:/models/some-dir")
    assert isinstance(hf, HFChatModel) and hf.name == "hf[D:/models/some-dir]"
