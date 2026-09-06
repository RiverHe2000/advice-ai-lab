"""Configuration: every knob is an ``ADVICEDOC_*`` environment variable; nested groups use
``__`` (e.g. ``ADVICEDOC_MODEL__KIND=openai``, ``ADVICEDOC_MODEL__BASE_URL=http://vllm:8000/v1``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelKind = Literal["fake", "openai", "hf"]
Strategy = Literal["rules", "llm", "llm_validated"]


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ModelKind = "fake"
    model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    base_url: str = "http://localhost:8000/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_s: float = Field(120.0, gt=0)
    max_retries: int = Field(3, ge=0)
    device: str = "auto"
    max_tokens: int = Field(800, ge=1)
    corruption: float = Field(0.0, ge=0.0, le=1.0)  # fake backend only


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ADVICEDOC_", env_nested_delimiter="__", extra="ignore"
    )

    model: ModelSettings = Field(default_factory=ModelSettings)
    strategy: Strategy = "rules"
    corpus_dir: Path = Path("data/corpus")
    classifier_path: Path = Path("runs/classifier.joblib")
    router_path: Path | None = None
    tau: float = Field(0.5, ge=0.0, le=1.0)
    abstain_threshold: float = Field(0.6, ge=0.0, le=1.0)
    db_path: Path | None = None
    inbox_dir: Path = Path("inbox")
    max_retries: int = Field(2, ge=0)
    seed: int = 0
    log_level: str = "INFO"
