"""SoA extraction behind one ``Extractor`` protocol: ``rules`` (headings, regexes, tables,
fuzzy product matching), ``llm`` (section-aware prompts with JSON repair and pydantic
validation) and ``llm_validated`` (``llm`` plus one targeted re-ask per section whose hard
validation fails)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from advicedoc.ingest import Document
from advicedoc.schema import SoAExtraction
from advicedoc.validate import Violation

SECTION_NAMES: tuple[str, ...] = (
    "header",
    "scope",
    "risk",
    "recommendations",
    "replacement",
    "fees",
    "authority",
)


@dataclass(slots=True)
class ExtractionResult:
    strategy: str
    doc_id: str
    extraction: SoAExtraction
    sections_found: dict[str, bool] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    available_funds: Decimal | None = None
    repairs: int = 0
    parse_failures: int = 0
    retries: int = 0
    reasks: int = 0
    reasks_fixed: int = 0
    n_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    field_confidence: dict[str, float] = field(default_factory=dict)
    product_scores: dict[str, float] = field(default_factory=dict)

    @property
    def hard_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["extraction"] = self.extraction.model_dump(mode="json")
        d["violations"] = [v.to_dict() for v in self.violations]
        d["available_funds"] = str(self.available_funds) if self.available_funds else None
        return d


class Extractor(Protocol):
    @property
    def name(self) -> str: ...

    def extract(self, doc: Document) -> ExtractionResult: ...
