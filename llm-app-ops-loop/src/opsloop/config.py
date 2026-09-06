"""Paths and defaults, every one overridable by ``OPSLOOP_*`` environment variables
(``OPSLOOP_STORE_PATH``, ``OPSLOOP_MODEL__KIND=openai``, ``OPSLOOP_MODEL__BASE_URL=...``)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseModel):
    kind: str = "fake"
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int = 400


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSLOOP_", env_nested_delimiter="__")

    store_path: Path = Path("runs/traces.sqlite")
    prompts_dir: Path = Path("prompts")
    releases_path: Path = Path("prompts/releases.yaml")
    slo_path: Path = Path("slos/default.yaml")
    datasets_dir: Path = Path("datasets")
    scenarios_dir: Path = Path("scenarios")
    pricing_path: Path | None = None
    environment: str = "prod"
    model: ModelSettings = Field(default_factory=ModelSettings)
