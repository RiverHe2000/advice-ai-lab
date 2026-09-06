"""Per-model prices → cost per call. An unknown model yields a *missing* cost (``usd=None``),
never zero: a zero would silently pull the cost-per-request SLO down. Prices are USD per one
million tokens, illustrative, and can be overridden from a YAML file (``OPSLOOP_PRICING``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float


@dataclass(frozen=True, slots=True)
class Cost:
    usd: float | None
    missing: bool
    model: str

    @property
    def value_or_zero(self) -> float:
        return 0.0 if self.usd is None else self.usd


# Local models carry an amortised GPU-hour price rather than zero so that "free" never hides
# a cost regression; hosted prices are public list prices at the time of writing.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "northshore-assistant-4b": ModelPrice(0.40, 1.60),  # the demo's fictional hosted model
    "northshore-judge-8b": ModelPrice(0.60, 2.40),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    "claude-3-5-haiku": ModelPrice(0.80, 4.00),
    "claude-sonnet-4": ModelPrice(3.00, 15.00),
    "qwen3-4b-local": ModelPrice(0.10, 0.30),
    "qwen2.5-1.5b-local": ModelPrice(0.05, 0.15),
}


class PriceTable:
    def __init__(self, prices: dict[str, ModelPrice] | None = None) -> None:
        self._prices = dict(DEFAULT_PRICES if prices is None else prices)

    @classmethod
    def from_yaml(cls, path: Path) -> PriceTable:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prices = {
            str(name): ModelPrice(float(row["input_per_million"]), float(row["output_per_million"]))
            for name, row in dict(raw).items()
        }
        return cls(prices)

    def known(self, model: str) -> bool:
        return self._normalise(model) in self._prices

    @staticmethod
    def _normalise(model: str) -> str:
        # "openai[gpt-4o-mini]" / "hf[D:/models/Qwen3-4B]" → the bare model id, lower-cased.
        name = model.strip()
        if "[" in name and name.endswith("]"):
            name = name[name.index("[") + 1 : -1]
        name = name.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
        return name.lower()

    def cost(self, model: str, prompt_tokens: int | None, completion_tokens: int | None) -> Cost:
        key = self._normalise(model)
        price = self._prices.get(key)
        if price is None or prompt_tokens is None or completion_tokens is None:
            return Cost(None, True, model)
        usd = (
            prompt_tokens * price.input_per_million + completion_tokens * price.output_per_million
        ) / 1_000_000.0
        return Cost(usd, False, model)

    def models(self) -> list[str]:
        return sorted(self._prices)
