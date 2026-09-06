from __future__ import annotations

import contextlib
import sys
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from filenote.config import ModelSettings, Settings
from filenote.llm import (
    ChatMessage,
    HFChatModel,
    ModelError,
    OpenAICompatibleChatModel,
    ScriptedChatModel,
    build_model,
)


def test_scripted_queue_rules_default() -> None:
    model = ScriptedChatModel(
        responses=["first"],
        rules=[("hello", "hi"), (r"\d+", lambda msgs: f"n={len(msgs)}")],
        default="dflt",
    )
    assert model.ready()
    assert model.name == "scripted"
    assert model.chat([ChatMessage("user", "hello")]).text == "first"
    assert model.chat([ChatMessage("user", "hello")]).text == "hi"
    assert model.chat([ChatMessage("user", "x 42")]).text == "n=1"
    assert model.chat([ChatMessage("user", "nothing")]).text == "dflt"
    assert model.chat([]).text == "dflt"
    assert len(model.calls) == 5
    assert ChatMessage("user", "x").to_dict() == {"role": "user", "content": "x"}


def _openai(handler: Any, **kw: Any) -> OpenAICompatibleChatModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleChatModel(
        "http://model/v1/", "qwen", client=client, sleep=lambda s: None, api_key="k", **kw
    )


def test_openai_success_and_ready() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        import json

        seen.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={
                "model": "qwen-served",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    model = _openai(handler)
    assert model.ready()
    resp = model.chat([ChatMessage("system", "s"), ChatMessage("user", "u")], max_tokens=50)
    assert resp.text == '{"ok": true}'
    assert resp.model == "qwen-served"
    assert (resp.prompt_tokens, resp.completion_tokens) == (11, 3)
    assert seen[0]["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    assert seen[0]["max_tokens"] == 50
    assert model.name == "openai[qwen]"
    model.close()


def test_openai_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    assert _openai(handler, max_retries=3).chat([ChatMessage("user", "u")]).text == "ok"
    assert calls["n"] == 3


def test_openai_gives_up_and_non_retriable() -> None:
    def always_503(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    with pytest.raises(ModelError, match="giving up"):
        _openai(always_503, max_retries=1).chat([ChatMessage("user", "u")])

    def bad_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad")

    with pytest.raises(ModelError) as exc:
        _openai(bad_request).chat([ChatMessage("user", "u")])
    assert exc.value.status == 400

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ModelError, match="transport error"):
        _openai(transport_error, max_retries=0).chat([ChatMessage("user", "u")])
    assert not _openai(transport_error).ready()

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelError, match="malformed"):
        _openai(malformed).chat([ChatMessage("user", "u")])


class _Tensor:
    def __init__(self, n: int) -> None:
        self.shape: tuple[int, ...] = (1, n)
        self.n = n

    def to(self, device: str) -> _Tensor:
        return self

    def __getitem__(self, key: Any) -> _Tensor:
        _, sl = key
        rest = _Tensor(self.n - sl.start)
        rest.shape = (self.n - sl.start,)
        return rest


class _Tokenizer:
    chat_template = "tmpl"
    pad_token_id = None
    eos_token_id = 2

    def apply_chat_template(self, messages: Any, **kw: Any) -> dict[str, _Tensor]:
        return {"input_ids": _Tensor(4)}

    def __call__(self, text: str, return_tensors: str = "pt") -> dict[str, _Tensor]:
        return {"input_ids": _Tensor(3)}

    def decode(self, tokens: _Tensor, skip_special_tokens: bool = True) -> str:
        return f"decoded {tokens.n}"


class _Model:
    def __init__(self) -> None:
        self.device = ""
        self.kwargs: dict[str, Any] = {}

    def to(self, device: str) -> _Model:
        self.device = device
        return self

    def eval(self) -> None:
        return None

    def generate(self, **kwargs: Any) -> _Tensor:
        self.kwargs = kwargs
        return _Tensor(9)


def _stub_torch(monkeypatch: pytest.MonkeyPatch, cuda: bool = False) -> None:
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        bfloat16="bf16",
        float32="f32",
        manual_seed=lambda s: None,
        no_grad=contextlib.nullcontext,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)


def test_hf_chat_with_stubbed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_torch(monkeypatch)
    model = _Model()
    hf = HFChatModel("tiny", model=model, tokenizer=_Tokenizer(), seed=3)
    assert hf.ready()
    assert hf.name == "hf[tiny]"
    resp = hf.chat([ChatMessage("user", "hi")], max_tokens=7, temperature=0.5)
    assert resp.text == "decoded 5"
    assert (resp.prompt_tokens, resp.completion_tokens) == (4, 5)
    assert model.device == "cpu"
    assert model.kwargs["max_new_tokens"] == 7
    assert model.kwargs["do_sample"] is True
    assert model.kwargs["pad_token_id"] == 2
    tok = _Tokenizer()
    tok.chat_template = ""
    resp2 = HFChatModel("tiny", device="cuda:0", model=model, tokenizer=tok).chat(
        [ChatMessage("user", "hi")]
    )
    assert resp2.prompt_tokens == 3
    assert model.device == "cuda:0"
    assert model.kwargs["do_sample"] is False


def test_hf_lazy_load_from_pretrained(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_torch(monkeypatch, cuda=True)
    loaded: dict[str, Any] = {}

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(name: str) -> _Tokenizer:
            loaded["tok"] = name
            return _Tokenizer()

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(name: str, dtype: str = "") -> _Model:
            loaded["model"] = (name, dtype)
            return _Model()

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoTokenizer=AutoTokenizer, AutoModelForCausalLM=AutoModelForCausalLM),
    )
    hf = HFChatModel("D:/models/some-dir")
    assert not hf.ready()
    assert hf.chat([ChatMessage("user", "hi")]).text == "decoded 5"
    assert loaded == {"tok": "D:/models/some-dir", "model": ("D:/models/some-dir", "bf16")}
    assert hf.ready()


def test_build_model_kinds(settings: Settings) -> None:
    fake = build_model(settings)
    assert fake.name.startswith("fake")
    openai = build_model(
        Settings(model=ModelSettings(kind="openai", model="m", base_url="http://x/v1"))
    )
    assert isinstance(openai, OpenAICompatibleChatModel)
    hf = build_model(Settings(model=ModelSettings(kind="hf", model="D:/models/x")))
    assert isinstance(hf, HFChatModel)
