"""Chat-model backends behind one protocol.

The drafting strategies speak plain JSON (schema in the prompt, tolerant repair on the way
back) rather than a vendor's structured-output feature, so the same code runs on a scripted
model in tests, on any OpenAI-compatible server (vLLM, Ollama, Azure OpenAI, Vertex AI, the
owner's ``llm-gateway-release``) or on a local Hugging Face model.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

import httpx

if TYPE_CHECKING:
    from filenote.config import Settings

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
        max_tokens: int = 1800,
        temperature: float = 0.0,
    ) -> ChatResponse: ...

    def ready(self) -> bool: ...


def to_provider_messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [m.to_dict() for m in messages]


# ----- scripted -----------------------------------------------------------------------------

Responder = Callable[[Sequence[ChatMessage]], str]


@dataclass
class ScriptedChatModel:
    """Plays queued responses, then regex rules on the last message, then ``default``."""

    responses: Sequence[str] = ()
    rules: Sequence[tuple[str, str | Responder]] = ()
    default: str | Responder = "{}"
    name_: str = "scripted"
    calls: list[list[ChatMessage]] = field(default_factory=list)
    _queue: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._queue = list(self.responses)

    @property
    def name(self) -> str:
        return self.name_

    def ready(self) -> bool:
        return True

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1800,  # noqa: ARG002 - protocol signature
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

    def ready(self) -> bool:
        """``/readyz`` support: the model endpoint answers ``GET /models``."""
        try:
            resp = self._client.get(
                f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}
            )
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1800,
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
    """In-process ``transformers`` chat model; accepts a hub id or a local directory. ``torch``
    and ``transformers`` are imported lazily so the rest of the package imports fast."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "auto",
        model: Any | None = None,
        tokenizer: Any | None = None,
        seed: int | None = None,
    ) -> None:
        self._model_name = model_name
        self._device_spec = device
        self._model: Any = model
        self._tokenizer: Any = tokenizer
        self._seed = seed

    @property
    def name(self) -> str:
        return f"hf[{self._model_name}]"

    def ready(self) -> bool:
        return self._model is not None and self._tokenizer is not None

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
        max_tokens: int = 1800,
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
            if self._seed is not None:
                torch.manual_seed(self._seed)
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


def build_model(settings: Settings) -> ChatModel:
    model = _build_backend(settings)
    if settings.model.cache_path is not None:
        from filenote.cache import CachedChatModel

        return CachedChatModel(model, settings.model.cache_path)
    return model


def _build_backend(settings: Settings) -> ChatModel:
    kind = settings.model.kind
    if kind == "fake":
        from filenote.corpus import generate_corpus
        from filenote.fake import Corruption, GoldFakeChatModel

        meetings = generate_corpus(settings.fake.corpus_n, settings.fake.corpus_seed)
        return GoldFakeChatModel(
            {m.id: m for m in meetings},
            corruption=Corruption(p=settings.fake.corruption, seed=settings.fake.seed),
        )
    if kind == "openai":
        return OpenAICompatibleChatModel(
            settings.model.base_url,
            settings.model.model,
            api_key_env=settings.model.api_key_env,
            timeout_s=settings.model.timeout_s,
            max_retries=settings.model.max_retries,
        )
    return HFChatModel(settings.model.model, device=settings.model.device, seed=settings.seed)
