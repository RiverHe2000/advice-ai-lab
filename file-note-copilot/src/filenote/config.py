"""Configuration: every knob is a ``FILENOTE_*`` environment variable; nested groups use ``__``
(e.g. ``FILENOTE_MODEL__KIND=openai``, ``FILENOTE_MODEL__BASE_URL=http://vllm:8000/v1``,
``FILENOTE_VERIFIER__SUPPORT_OVERLAP=0.6``). Thresholds are configuration, not magic numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from filenote.verify.verifier import VerifierConfig

ModelKind = Literal["fake", "openai", "hf"]
Strategy = Literal["single_shot", "extract_then_compose", "verified", "verified_single_shot"]
STRATEGIES: tuple[Strategy, ...] = (
    "single_shot",
    "extract_then_compose",
    "verified",
    "verified_single_shot",
)


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ModelKind = "fake"
    model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    base_url: str = "http://localhost:8000/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_s: float = Field(120.0, gt=0)
    max_retries: int = Field(3, ge=0)
    device: str = "auto"
    max_tokens: int = Field(1800, ge=1)
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    cache_path: Path | None = Field(
        None,
        description="SQLite file caching greedy (temperature 0) responses by exact request; "
        "identical prompts across strategies and re-runs are then free",
    )


class FakeSettings(BaseModel):
    """The scripted backend derives its answers from the gold note of the meeting it is shown,
    corrupted with probability ``corruption`` per item (see ``fake.py``)."""

    model_config = ConfigDict(extra="forbid")

    corruption: float = Field(0.0, ge=0.0, le=1.0)
    seed: int = 0
    corpus_n: int = Field(20, ge=1, description="meetings the fake knows about when serving")
    corpus_seed: int = 11


class DraftSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Strategy = "verified"
    window_size: int = Field(20, ge=1, description="segments per extraction window")
    max_parse_retries: int = Field(2, ge=0)
    repair_passes: int = Field(1, ge=0)
    candidate_segments: int = Field(5, ge=0, description="extra segments offered in repair")


class WebSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(8080, ge=1, le=65535)
    heartbeat_s: float = Field(5.0, gt=0)
    max_transcript_chars: int = Field(200_000, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FILENOTE_", env_nested_delimiter="__", extra="ignore"
    )

    model: ModelSettings = Field(default_factory=ModelSettings)
    fake: FakeSettings = Field(default_factory=FakeSettings)
    draft: DraftSettings = Field(default_factory=DraftSettings)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    web: WebSettings = Field(default_factory=WebSettings)

    pseudonymise: bool = True
    # Durable state. ``None`` keeps everything in memory (tests, CI).
    db_path: Path | None = None
    audit_path: Path | None = None
    seed: int = 0
    log_level: str = "INFO"
