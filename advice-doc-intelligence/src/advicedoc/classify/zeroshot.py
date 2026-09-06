"""Zero-shot LLM document classifier: a prompt listing the ten types with one-line
definitions, JSON output with repair, and a gold-derived fake responder (with corruption)
so the comparison code path runs in CI."""

from __future__ import annotations

import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from advicedoc.ingest import Document
from advicedoc.llm import ChatMessage, ChatModel, Responder, repair_json
from advicedoc.schema import DOC_TYPE_DEFINITIONS, DOC_TYPE_LABELS, DOC_TYPES

SYSTEM_PROMPT = (
    "You are a document classifier for an Australian financial-advice platform. Classify the "
    "document into exactly one of these types:\n"
    + "\n".join(f"- {t}: {DOC_TYPE_DEFINITIONS[t]}" for t in DOC_TYPES)
    + '\nReply with JSON only: {"doc_type": "<type>", "confidence": <0-1>}.'
)
DOC_ID_PATTERN = re.compile(r"^Document: (\S+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class ZeroShotResult:
    label: str | None
    confidence: float | None
    repaired: bool
    raw: str
    reason: str | None = None


def build_prompt(doc: Document, *, max_chars: int = 3000) -> list[ChatMessage]:
    text = doc.head_text(2)[:max_chars]
    return [
        ChatMessage("system", SYSTEM_PROMPT),
        ChatMessage("user", f"Document: {doc.source}\n\n{text}\n\nJSON:"),
    ]


def _label_from_text(raw: str) -> str | None:
    lowered = raw.lower()
    for t in DOC_TYPES:
        if re.search(rf"\b{re.escape(t)}\b", lowered) or DOC_TYPE_LABELS[t].lower() in lowered:
            return t
    return None


def classify_zero_shot(model: ChatModel, doc: Document, *, max_chars: int = 3000) -> ZeroShotResult:
    response = model.chat(build_prompt(doc, max_chars=max_chars), max_tokens=60)
    parsed = repair_json(response.text)
    if isinstance(parsed.value, dict):
        label = str(parsed.value.get("doc_type", "")).strip().lower()
        conf_raw = parsed.value.get("confidence")
        conf = float(conf_raw) if isinstance(conf_raw, int | float) else None
        if label in DOC_TYPES:
            return ZeroShotResult(label, conf, parsed.repaired, response.text)
    fallback = _label_from_text(response.text)
    if fallback is not None:
        return ZeroShotResult(fallback, None, True, response.text, "label recovered from prose")
    return ZeroShotResult(None, None, parsed.repaired, response.text, "unparseable answer")


def make_gold_responder(
    labels_by_id: Mapping[str, str], *, corruption: float = 0.0, seed: int = 0
) -> Responder:
    """A scripted classifier that answers from the gold label of the document named in the
    prompt; with probability ``corruption`` it answers a wrong type, prose, or garbage."""

    def respond(messages: Sequence[ChatMessage]) -> str:
        last = messages[-1].content if messages else ""
        m = DOC_ID_PATTERN.search(last)
        doc_id = m.group(1) if m else ""
        gold = labels_by_id.get(doc_id)
        rng = random.Random(f"{seed}:zeroshot:{doc_id}")
        if gold is None:
            return "I cannot tell."
        if rng.random() < corruption:
            mode = rng.choice(["wrong", "prose", "garbage"])
            if mode == "wrong":
                wrong = rng.choice([t for t in DOC_TYPES if t != gold])
                return f'{{"doc_type": "{wrong}", "confidence": 0.7}}'
            if mode == "prose":
                wrong = rng.choice([t for t in DOC_TYPES if t != gold])
                return f"I think this is a {DOC_TYPE_LABELS[wrong]}."
            return '```json\n{"doc_type": "' + gold[:3]
        if rng.random() < 0.3:
            return f'```json\n{{"doc_type": "{gold}", "confidence": 0.9}}\n```'
        return f'{{"doc_type": "{gold}", "confidence": 0.9}}'

    return respond
