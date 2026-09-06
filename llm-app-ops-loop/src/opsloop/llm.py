"""Chat-model backends behind one protocol.

The same ``ChatModel`` protocol serves the demo application, the LLM judge, the regression
gate and trace replay, so every one of them runs on a scripted model in tests and CI, on an
OpenAI-compatible HTTP endpoint (vLLM, Ollama, Azure OpenAI, the owner's ``llm-gateway-release``)
or on an in-process Hugging Face model, selected by ``--model {fake,openai,hf}``.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

Role = Literal["system", "user", "assistant", "tool"]
RETRIABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ModelError(RuntimeError):
    """A model call failed after bounded retries (or with a non-retriable status)."""

    def __init__(self, message: str, *, status: int | None = None, kind: str = "provider") -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind


def estimate_tokens(text: str) -> int:
    """Cheap length-based token estimate (≈ 4 characters per token) used by the scripted
    backend, the prompt linter and the fake model's usage report."""
    return max(1, round(len(text) / 4))


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class ChatResponse:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_s: float = 0.0


class ChatModel(Protocol):
    @property
    def name(self) -> str: ...

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 400,
        temperature: float = 0.0,
    ) -> ChatResponse: ...


def to_provider_messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """Tool results travel as ``user`` messages: every provider accepts user/assistant/system."""
    return [
        {"role": "user" if m.role == "tool" else m.role, "content": m.content} for m in messages
    ]


# ----- scripted -----------------------------------------------------------------------------

Responder = Callable[[Sequence[ChatMessage]], str]


@dataclass
class FakeChatModel:
    """Deterministic model for tests and CI.

    Resolution order: the next queued ``responses`` entry; else the first ``rules`` regex that
    matches the *last* message; else ``default`` (a string or a callable of the messages).
    """

    responses: Sequence[str] = ()
    rules: Sequence[tuple[str, str | Responder]] = ()
    default: str | Responder = "I don't know."
    name_: str = "fake"
    calls: list[list[ChatMessage]] = field(default_factory=list)
    _queue: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._queue = list(self.responses)

    @property
    def name(self) -> str:
        return self.name_

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 400,  # noqa: ARG002 - protocol signature
        temperature: float = 0.0,  # noqa: ARG002
    ) -> ChatResponse:
        self.calls.append(list(messages))
        if self._queue:
            text = self._queue.pop(0)
        else:
            last = messages[-1].content if messages else ""
            chosen: str | Responder = self.default
            for pattern, response in self.rules:
                if re.search(pattern, last, flags=re.DOTALL | re.IGNORECASE):
                    chosen = response
                    break
            text = chosen(messages) if callable(chosen) else chosen
        return ChatResponse(
            text=text,
            model=self.name_,
            prompt_tokens=sum(estimate_tokens(m.content) for m in messages),
            completion_tokens=estimate_tokens(text),
        )


# ----- OpenAI-compatible HTTP ---------------------------------------------------------------


class OpenAICompatibleChatModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        timeout_s: float = 60.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key or os.environ.get(api_key_env) or "not-needed"
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._client = client or httpx.Client(timeout=timeout_s)

    @property
    def name(self) -> str:
        return f"openai[{self._model}]"

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 400,
        temperature: float = 0.0,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": to_provider_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error = ""
        last_kind = "provider"
        for attempt in range(self._max_retries + 1):
            started = time.perf_counter()
            try:
                resp = self._client.post(
                    f"{self._base_url}/chat/completions", json=body, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error, last_kind = f"timeout: {exc}", "timeout"
            except httpx.TransportError as exc:
                last_error, last_kind = f"transport error: {exc}", "transport"
            else:
                if resp.status_code == 200:
                    payload = resp.json()
                    try:
                        text = payload["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as exc:
                        msg = f"malformed response: {payload!r}"
                        raise ModelError(msg, kind="malformed") from exc
                    usage = payload.get("usage") or {}
                    return ChatResponse(
                        text=str(text or ""),
                        model=str(payload.get("model", self._model)),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        latency_s=time.perf_counter() - started,
                    )
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                last_kind = "provider"
                if resp.status_code not in RETRIABLE_STATUS:
                    raise ModelError(last_error, status=resp.status_code)
            if attempt < self._max_retries:
                self._sleep(self._backoff_s * (2**attempt))
        msg = f"giving up after {self._max_retries + 1} attempts: {last_error}"
        raise ModelError(msg, kind=last_kind)

    def close(self) -> None:
        self._client.close()


# ----- local Hugging Face -------------------------------------------------------------------


class HFChatModel:  # pragma: no cover - needs torch/transformers; exercised by the GPU stage
    """In-process ``transformers`` chat model (hub id or local directory), greedy decoding,
    bf16 on CUDA. ``torch`` / ``transformers`` are imported lazily so the rest of the package
    imports fast and tests never touch them."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "auto",
        model: Any | None = None,
        tokenizer: Any | None = None,
    ) -> None:
        self._model_name = model_name
        self._device_spec = device
        self._model: Any = model
        self._tokenizer: Any = tokenizer

    @property
    def name(self) -> str:
        return f"hf[{self._model_name}]"

    def _load(self) -> tuple[Any, Any, str]:
        import torch

        device = self._device_spec
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._model is None or self._tokenizer is None:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            self._model = AutoModelForCausalLM.from_pretrained(self._model_name, dtype=dtype)
        self._model.to(device)
        self._model.eval()
        return self._model, self._tokenizer, device

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 400,
        temperature: float = 0.0,
    ) -> ChatResponse:
        import torch

        model, tokenizer, device = self._load()
        provider_messages = to_provider_messages(messages)
        if getattr(tokenizer, "chat_template", None):
            encoded = tokenizer.apply_chat_template(
                provider_messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
        else:
            flat = "\n\n".join(f"{m['role']}: {m['content']}" for m in provider_messages)
            encoded = tokenizer(flat + "\n\nassistant:", return_tensors="pt")
        inputs = {k: v.to(device) for k, v in encoded.items()}
        gen: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "do_sample": temperature > 0.0,
            "pad_token_id": tokenizer.pad_token_id
            if tokenizer.pad_token_id is not None
            else tokenizer.eos_token_id,
        }
        if temperature > 0.0:
            gen["temperature"] = temperature
        started = time.perf_counter()
        with torch.no_grad():
            out = model.generate(**inputs, **gen)
        n_prompt = int(inputs["input_ids"].shape[1])
        new_tokens = out[0, n_prompt:]
        return ChatResponse(
            text=tokenizer.decode(new_tokens, skip_special_tokens=True).strip(),
            model=self._model_name,
            prompt_tokens=n_prompt,
            completion_tokens=int(new_tokens.shape[0]),
            latency_s=time.perf_counter() - started,
        )


# ----- factory ------------------------------------------------------------------------------

_HF_MODELS: dict[str, HFChatModel] = {}

ModelKind = Literal["fake", "openai", "hf"]


def build_model(
    kind: str,
    *,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    fake: ChatModel | None = None,
) -> ChatModel:
    """Select a backend. ``fake`` lets callers supply their scripted model (the demo's
    ``DemoFakeModel`` or the judge's ``FakeJudgeModel``) for ``kind == "fake"``."""
    if kind == "fake":
        return fake or FakeChatModel()
    if kind == "openai":
        url = base_url or os.environ.get("OPENAI_BASE_URL") or "http://127.0.0.1:8000/v1"
        return OpenAICompatibleChatModel(url, model_name or "default", api_key=api_key)
    if kind == "hf":
        # One in-process copy per model name: the regression gate uses the same model as
        # answerer and judge, and two 4 B copies do not fit a 12 GB card.
        name = model_name or "Qwen/Qwen2.5-1.5B-Instruct"
        if name not in _HF_MODELS:
            _HF_MODELS[name] = HFChatModel(name)
        return _HF_MODELS[name]
    msg = f"unknown model kind {kind!r} (expected fake, openai or hf)"
    raise ValueError(msg)
