"""``llm_validated``: the LLM extractor plus one targeted re-ask per section whose *hard*
validation fails, with the violations explained; bounded to one re-ask per section, and the
number of re-asks that actually cleared the violation is reported."""

from __future__ import annotations

import time

from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.extract import ExtractionResult
from advicedoc.extract.llm import SECTION_SPECS, LLMExtractor, SectionOutcome, section_text
from advicedoc.extract.sections import detect_sections
from advicedoc.ingest import Document
from advicedoc.llm import ChatModel
from advicedoc.validate import hard, violations_by_section


class ValidatedLLMExtractor(LLMExtractor):
    def __init__(
        self,
        model: ChatModel,
        *,
        master: ProductMaster = DEFAULT_MASTER,
        max_parse_retries: int = 1,
        max_chars: int = 6000,
        max_tokens: int = 800,
        name: str = "llm_validated",
    ) -> None:
        super().__init__(
            model,
            master=master,
            max_parse_retries=max_parse_retries,
            max_chars=max_chars,
            max_tokens=max_tokens,
            name=name,
        )

    def extract(self, doc: Document) -> ExtractionResult:
        started = time.perf_counter()
        outcomes, found, missing = self.extract_sections(doc)
        result = self.assemble(doc, outcomes, found, missing)
        failing = violations_by_section(hard(result.violations))
        sections = detect_sections(doc)
        reasked = False
        for name, violations in failing.items():
            if name not in SECTION_SPECS or not found.get(name):
                continue
            spec = SECTION_SPECS[name]
            text = section_text(sections, spec, doc)
            if text is None:
                continue
            feedback = "; ".join(f"{v.field}: {v.message}" for v in violations)
            retry = self.ask_section(doc.source, spec, text, feedback=feedback)
            result.reasks += 1
            reasked = True
            prior = outcomes[name]
            if retry.value is not None:
                outcomes[name] = _accumulate(retry, prior)
                missing.pop(name, None)
            else:
                _accumulate(prior, retry)
        if reasked:
            reasks = result.reasks
            result = self.assemble(doc, outcomes, found, missing)
            result.reasks = reasks
            after = violations_by_section(hard(result.violations))
            result.reasks_fixed = sum(
                1 for name in failing if name in SECTION_SPECS and name not in after
            )
        result.latency_s = max(result.latency_s, time.perf_counter() - started)
        return result


def _accumulate(keep: SectionOutcome, other: SectionOutcome) -> SectionOutcome:
    """Fold ``other``'s call counters into ``keep`` (whose value is retained)."""
    keep.n_calls += other.n_calls
    keep.repairs += other.repairs
    keep.parse_failures += other.parse_failures
    keep.retries += other.retries
    keep.prompt_tokens += other.prompt_tokens
    keep.completion_tokens += other.completion_tokens
    keep.latency_s += other.latency_s
    return keep
