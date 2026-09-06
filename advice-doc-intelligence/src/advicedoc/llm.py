"""Chat-model backends behind one protocol, plus tolerant JSON repair.

The extractors and the zero-shot classifier ask the model for JSON. The same code runs on a
scripted model in tests and CI (``FakeChatModel`` driven by a gold-derived responder), on an
OpenAI-compatible HTTP endpoint (vLLM, Ollama, Azure OpenAI, the owner's ``llm-gateway-release``)
or on an in-process Hugging Face model. ``torch``/``transformers`` are imported lazily inside
the HF backend so the package imports fast and tests never touch them.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

Role = Literal["system", "user", "assistant"]
RETRIABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ModelError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> ChatResponse: ...


# ----- scripted -----------------------------------------------------------------------------

Responder = Callable[[Sequence[ChatMessage]], str]


@dataclass
class FakeChatModel:
    """Deterministic model for tests and CI.

    Resolution order: the next queued ``responses`` entry; else the first ``rules`` regex that
    matches the *last* message; else ``default`` (a string or a responder callable — the
    gold-derived responders in ``extract/fake.py`` and ``classify/zeroshot.py`` plug in here).
    """

    responses: Sequence[str] = ()
    rules: Sequence[tuple[str, str | Responder]] = ()
    default: str | Responder = "{}"
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
        max_tokens: int = 800,  # noqa: ARG002 - protocol signature
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
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
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
        timeout_s: float = 120.0,
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
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error = ""
        for attempt in range(self._max_retries + 1):
            started = time.perf_counter()
            try:
                resp = self._client.post(
                    f"{self._base_url}/chat/completions", json=body, headers=headers
                )
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc}"
            else:
                if resp.status_code == 200:
                    payload = resp.json()
                    try:
                        text = payload["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as exc:
                        msg = f"malformed response: {payload!r}"
                        raise ModelError(msg) from exc
                    usage = payload.get("usage") or {}
                    return ChatResponse(
                        text=str(text or ""),
                        model=str(payload.get("model", self._model)),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        latency_s=time.perf_counter() - started,
                    )
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code not in RETRIABLE_STATUS:
                    raise ModelError(last_error, status=resp.status_code)
            if attempt < self._max_retries:
                self._sleep(self._backoff_s * (2**attempt))
        msg = f"giving up after {self._max_retries + 1} attempts: {last_error}"
        raise ModelError(msg)

    def close(self) -> None:
        self._client.close()


# ----- local Hugging Face -------------------------------------------------------------------


class HFChatModel:
    """In-process ``transformers`` chat model; ``model_name`` is a hub id or a local directory."""

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

    def _load(self) -> tuple[Any, Any, str]:  # pragma: no cover - needs torch/transformers
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

    def chat(  # pragma: no cover - needs torch/transformers
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> ChatResponse:
        import torch

        model, tokenizer, device = self._load()
        provider_messages = [m.to_dict() for m in messages]
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


ModelKind = Literal["fake", "openai", "hf"]


def build_model(
    kind: ModelKind,
    *,
    model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
    base_url: str = "http://localhost:8000/v1",
    api_key_env: str = "OPENAI_API_KEY",
    device: str = "auto",
    timeout_s: float = 120.0,
    max_retries: int = 3,
    fake_default: str | Responder = "{}",
) -> ChatModel:
    if kind == "fake":
        return FakeChatModel(default=fake_default)
    if kind == "openai":
        return OpenAICompatibleChatModel(
            base_url,
            model_name,
            api_key_env=api_key_env,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
    return HFChatModel(model_name, device=device)


# ----- JSON repair --------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_OPEN_TO_CLOSE = {"{": "}", "[": "]"}


@dataclass(frozen=True, slots=True)
class JsonRepair:
    value: Any | None
    repaired: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None


def _try_load(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _balance(text: str) -> str:
    """Close an unterminated string and any open brackets, in the right order."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _OPEN_TO_CLOSE:
            stack.append(_OPEN_TO_CLOSE[ch])
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()
    out = text + ('"' if in_string else "")
    out = re.sub(r"[\s,:]+$", "", out)
    return out + "".join(reversed(stack))


def repair_json(text: str) -> JsonRepair:
    """Parse model output as JSON, tolerating fences, prose around the object, trailing
    commas and truncation. ``repaired`` is True when the raw text did not parse as-is."""
    raw = text.strip()
    if not raw:
        return JsonRepair(None, False, "empty response")
    direct = _try_load(raw)
    if direct is not None:
        return JsonRepair(direct, False)
    candidate = _FENCE.sub("", raw).strip()
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if not starts:
        return JsonRepair(None, False, "no JSON object found")
    start = min(starts)
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    body = candidate[start : end + 1] if end > start else candidate[start:]
    attempts = [body, _TRAILING_COMMA.sub(r"\1", body)]
    balanced = _balance(_TRAILING_COMMA.sub(r"\1", body))
    attempts.append(balanced)
    # Truncation: drop the last (possibly partial) element and re-balance, a few times.
    cut = body
    for _ in range(6):
        comma = cut.rfind(",")
        if comma <= 0:
            break
        cut = cut[:comma]
        attempts.append(_balance(_TRAILING_COMMA.sub(r"\1", cut)))
    for attempt in attempts:
        value = _try_load(attempt)
        if value is not None:
            return JsonRepair(value, True)
    return JsonRepair(None, True, "unrepairable JSON")
