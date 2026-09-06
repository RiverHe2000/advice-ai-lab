"""The LLM extractor: each SoA section is its own prompt carrying the JSON schema for that
part; answers go through tolerant JSON repair and pydantic validation with bounded retries;
a section that cannot be found or parsed yields ``None``/empty with a recorded reason, never
a silent default. Section results are merged into one ``SoAExtraction``."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from advicedoc.classify.metadata import extract_metadata
from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.extract import SECTION_NAMES, ExtractionResult
from advicedoc.extract.rules import RulesExtractor
from advicedoc.extract.sections import Section, detect_sections
from advicedoc.ingest import Document
from advicedoc.llm import ChatMessage, ChatModel, repair_json
from advicedoc.schema import (
    FeeSchedule,
    ProductReplacement,
    Recommendation,
    RiskProfile,
    ScopeArea,
    SoAExtraction,
)
from advicedoc.validate import Violation, validate_extraction


class HeaderSection(BaseModel):
    client_names: list[str] = Field(default_factory=list)
    adviser_name: str | None = None
    licensee: str | None = None
    advice_date: date | None = None
    confidence: float | None = None


class ScopeSection(BaseModel):
    scope: list[ScopeArea] = Field(default_factory=list)
    confidence: float | None = None


class RiskSection(BaseModel):
    risk_profile: RiskProfile | None = None
    confidence: float | None = None


class RecommendationsSection(BaseModel):
    recommendations: list[Recommendation] = Field(default_factory=list)
    confidence: float | None = None


class ReplacementSection(BaseModel):
    replacements: list[ProductReplacement] = Field(default_factory=list)
    confidence: float | None = None


class FeesSection(BaseModel):
    fees: FeeSchedule | None = None
    confidence: float | None = None


class AuthoritySection(BaseModel):
    authority_to_proceed_signed: bool | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class SectionSpec:
    name: str
    model: type[BaseModel]
    instructions: str
    example: str
    sources: tuple[str, ...]  # detected section names whose text feeds this prompt


SECTION_SPECS: dict[str, SectionSpec] = {
    "header": SectionSpec(
        "header",
        HeaderSection,
        "Extract the client name(s), the adviser's name (person, not the licensee), the "
        "licensee company and the date of the advice.",
        '{"client_names": ["Jane Citizen"], "adviser_name": "Sam Adviser", '
        '"licensee": "Example Advice Pty Ltd", "advice_date": "2026-03-12", "confidence": 0.9}',
        ("header",),
    ),
    "scope": SectionSpec(
        "scope",
        ScopeSection,
        "List the areas the advice covers, using only: superannuation, retirement, insurance, "
        "investment, debt. Exclude areas the document says are not covered.",
        '{"scope": ["superannuation", "retirement"], "confidence": 0.9}',
        ("scope",),
    ),
    "risk": SectionSpec(
        "risk",
        RiskSection,
        "State the client's assessed risk profile, exactly one of: Conservative, Moderately "
        "Conservative, Balanced, Growth, High Growth. Ignore profiles mentioned for comparison.",
        '{"risk_profile": "Balanced", "confidence": 0.9}',
        ("risk",),
    ),
    "recommendations": SectionSpec(
        "recommendations",
        RecommendationsSection,
        "List every recommendation: action (establish, contribute, switch, retain, redeem, "
        "rollover, insure), product_name (the product recommended, as written), product_type "
        "(super, pension, idps, managed_portfolio, insurance, cash), amount in AUD as a number "
        "or null, account_ref or null. Do not include products merely considered.",
        '{"recommendations": [{"action": "rollover", "product_name": "Example Super", '
        '"product_type": "super", "amount": 250000, "account_ref": null}], "confidence": 0.9}',
        ("recommendations",),
    ),
    "replacement": SectionSpec(
        "replacement",
        ReplacementSection,
        "List each product replacement: from_product, to_product, fee_difference_pa in AUD "
        "(positive when the recommended product costs more), insurance_impact (none, "
        "reduced_cover, increased_cover, cover_lost) and the reason.",
        '{"replacements": [{"from_product": "Old Fund", "to_product": "New Fund", '
        '"fee_difference_pa": -1200, "insurance_impact": "reduced_cover", '
        '"reason": "lower fees"}], "confidence": 0.9}',
        ("replacement",),
    ),
    "fees": SectionSpec(
        "fees",
        FeesSection,
        "Extract the fee schedule: initial_advice_fee, ongoing_advice_fee_pa (dollar amount per "
        "year), ongoing_fee_basis (flat or percent), ongoing_fee_percent or null, "
        "platform_admin_fee_pct or null, insurance_premium_pa or null. Numbers only.",
        '{"fees": {"initial_advice_fee": 2200, "ongoing_advice_fee_pa": 3300, '
        '"ongoing_fee_basis": "flat", "ongoing_fee_percent": null, "platform_admin_fee_pct": 0.3, '
        '"insurance_premium_pa": null}, "confidence": 0.9}',
        ("fees",),
    ),
    "authority": SectionSpec(
        "authority",
        AuthoritySection,
        "Say whether the authority to proceed has been signed (true), is unsigned (false) or "
        "cannot be determined (null).",
        '{"authority_to_proceed_signed": false, "confidence": 0.8}',
        ("authority",),
    ),
}
SYSTEM_PROMPT = (
    "You extract structured data from Australian Statements of Advice. Answer with a single "
    "JSON object matching the schema in the request and nothing else. Use null for anything "
    "the text does not state; never invent values."
)
DOC_ID_PATTERN = re.compile(r"^Document: (\S+)$", re.MULTILINE)
SECTION_PATTERN = re.compile(r"^\[section: (\w+)\]$", re.MULTILINE)
RETRY_MARKER = "PARSE FEEDBACK"
REASK_MARKER = "VALIDATION FEEDBACK"


def build_section_prompt(
    doc_id: str, spec: SectionSpec, text: str, *, max_chars: int
) -> list[ChatMessage]:
    body = (
        f"Document: {doc_id}\n[section: {spec.name}]\n{spec.instructions}\n"
        f"Schema example: {spec.example}\n\nText:\n{text[:max_chars]}\n\nJSON:"
    )
    return [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", body)]


def section_text(sections: dict[str, Section], spec: SectionSpec, doc: Document) -> str | None:
    if spec.name == "header":
        return doc.pages[0].text if doc.pages else None
    parts: list[str] = []
    for name in spec.sources:
        section = sections.get(name)
        if section is None:
            continue
        parts.append(section.text)
        for table in section.tables:
            parts.append("\n".join(" | ".join(row) for row in table))
    return "\n".join(parts) if parts else None


@dataclass(slots=True)
class SectionOutcome:
    name: str
    value: BaseModel | None
    reason: str | None = None
    raw: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    repairs: int = 0
    parse_failures: int = 0
    retries: int = 0
    n_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


class LLMExtractor:
    def __init__(
        self,
        model: ChatModel,
        *,
        master: ProductMaster = DEFAULT_MASTER,
        max_parse_retries: int = 1,
        max_chars: int = 6000,
        max_tokens: int = 800,
        name: str = "llm",
    ) -> None:
        self._model = model
        self._master = master
        self._max_parse_retries = max_parse_retries
        self._max_chars = max_chars
        self._max_tokens = max_tokens
        self._name = name
        self._rules = RulesExtractor(master)

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> ChatModel:
        return self._model

    def ask_section(
        self, doc_id: str, spec: SectionSpec, text: str, *, feedback: str | None = None
    ) -> SectionOutcome:
        """Ask for one section; retry on parse/validation failure up to the bound. With
        ``feedback`` (a validation re-ask) the violations are explained in the prompt."""
        outcome = SectionOutcome(spec.name, None)
        messages = build_section_prompt(doc_id, spec, text, max_chars=self._max_chars)
        if feedback is not None:
            messages.append(
                ChatMessage("user", f"{REASK_MARKER}: {feedback}\nReturn corrected JSON only.")
            )
        error = "no attempt"
        for attempt in range(self._max_parse_retries + 1):
            if attempt > 0:
                outcome.retries += 1
                messages = [
                    *messages,
                    ChatMessage("assistant", outcome.raw),
                    ChatMessage("user", f"{RETRY_MARKER}: {error}\nReply with valid JSON only."),
                ]
            started = time.perf_counter()
            response = self._model.chat(messages, max_tokens=self._max_tokens)
            outcome.latency_s += time.perf_counter() - started
            outcome.n_calls += 1
            outcome.prompt_tokens += response.prompt_tokens or 0
            outcome.completion_tokens += response.completion_tokens or 0
            outcome.raw = response.text
            parsed = repair_json(response.text)
            if parsed.repaired:
                outcome.repairs += 1
            if not parsed.ok or not isinstance(parsed.value, dict):
                outcome.parse_failures += 1
                error = parsed.error or "not a JSON object"
                continue
            try:
                outcome.value = spec.model.model_validate(parsed.value)
            except ValidationError as exc:
                outcome.parse_failures += 1
                error = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:4]
                )
                continue
            outcome.messages = messages
            return outcome
        outcome.reason = f"unparseable after {self._max_parse_retries + 1} attempts: {error}"
        outcome.messages = messages
        return outcome

    def extract_sections(
        self, doc: Document
    ) -> tuple[dict[str, SectionOutcome], dict[str, bool], dict[str, str]]:
        sections = detect_sections(doc)
        outcomes: dict[str, SectionOutcome] = {}
        found: dict[str, bool] = {}
        missing: dict[str, str] = {}
        for name in SECTION_NAMES:
            spec = SECTION_SPECS[name]
            text = section_text(sections, spec, doc)
            found[name] = text is not None
            if text is None:
                missing[name] = "section not found"
                outcomes[name] = SectionOutcome(name, None, "section not found")
                continue
            outcome = self.ask_section(doc.source, spec, text)
            outcomes[name] = outcome
            if outcome.value is None:
                missing[name] = outcome.reason or "unparseable"
        return outcomes, found, missing

    def _validate(
        self, extraction: SoAExtraction, doc: Document, available: Any
    ) -> list[Violation]:
        return validate_extraction(
            extraction,
            master=self._master,
            document_text=doc.text,
            available_funds=available,
            document_date=extract_metadata(doc).document_date,
        )

    def assemble(
        self,
        doc: Document,
        outcomes: dict[str, SectionOutcome],
        found: dict[str, bool],
        missing: dict[str, str],
    ) -> ExtractionResult:
        extraction = merge_sections({k: v.value for k, v in outcomes.items()})
        sections = detect_sections(doc)
        available = RulesExtractor._available_funds(sections, doc)
        result = ExtractionResult(
            strategy=self.name,
            doc_id=doc.source,
            extraction=extraction,
            sections_found=found,
            missing=missing,
            available_funds=available,
            violations=self._validate(extraction, doc, available),
        )
        for name, o in outcomes.items():
            result.repairs += o.repairs
            result.parse_failures += o.parse_failures
            result.retries += o.retries
            result.n_calls += o.n_calls
            result.prompt_tokens += o.prompt_tokens
            result.completion_tokens += o.completion_tokens
            result.latency_s += o.latency_s
            conf = getattr(o.value, "confidence", None)
            if isinstance(conf, int | float):
                result.field_confidence[name] = float(conf)
        for i, rec in enumerate(extraction.recommendations):
            result.product_scores[f"rec:{i}"] = self._master.match(rec.product_name)[1]
        return result

    def extract(self, doc: Document) -> ExtractionResult:
        started = time.perf_counter()
        outcomes, found, missing = self.extract_sections(doc)
        result = self.assemble(doc, outcomes, found, missing)
        result.latency_s = max(result.latency_s, time.perf_counter() - started)
        return result


def merge_sections(values: dict[str, BaseModel | None]) -> SoAExtraction:
    data: dict[str, Any] = {}
    for value in values.values():
        if value is None:
            continue
        for key, item in value.model_dump().items():
            if key != "confidence":
                data[key] = item
    return SoAExtraction.model_validate(data)


def dump_messages(messages: Sequence[ChatMessage]) -> str:
    return json.dumps([m.to_dict() for m in messages], ensure_ascii=False)
