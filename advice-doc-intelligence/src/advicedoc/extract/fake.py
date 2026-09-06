"""A gold-derived scripted responder for the extraction prompts: it reads the document id and
section name from the prompt and answers from the gold ``SoAExtraction``, corrupting the
answer with probability ``corruption`` (wrong amounts, dropped items, invalid enums, wrong
names, shifted dates, truncated JSON) so that the evaluator, the validators, the retry
path and the re-ask path are all exercised in CI. On a validation re-ask it returns the
gold answer with probability ``p_fix_on_reask``."""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any

from advicedoc.extract.llm import DOC_ID_PATTERN, REASK_MARKER, SECTION_PATTERN
from advicedoc.llm import ChatMessage, Responder
from advicedoc.schema import RISK_PROFILES, SoAExtraction

CORRUPTIONS: dict[str, tuple[str, ...]] = {
    "header": ("wrong_date", "drop_client", "wrong_adviser", "truncate"),
    "scope": ("drop_item", "truncate"),
    "risk": ("invalid_enum", "wrong_profile", "truncate"),
    "recommendations": ("wrong_amount", "drop_item", "wrong_name", "invalid_enum", "truncate"),
    "replacement": ("drop_item", "wrong_fee_diff", "empty_reason", "truncate"),
    "fees": ("wrong_amount", "wrong_basis", "truncate"),
    "authority": ("flip", "truncate"),
}


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def gold_section(gold: SoAExtraction, section: str) -> dict[str, Any]:
    g = gold.model_dump(mode="json")
    if section == "header":
        return {k: g[k] for k in ("client_names", "adviser_name", "licensee", "advice_date")}
    if section == "scope":
        return {"scope": g["scope"]}
    if section == "risk":
        return {"risk_profile": g["risk_profile"]}
    if section == "recommendations":
        return {"recommendations": g["recommendations"]}
    if section == "replacement":
        return {"replacements": g["replacements"]}
    if section == "fees":
        return {"fees": g["fees"]}
    return {"authority_to_proceed_signed": g["authority_to_proceed_signed"]}


def _scale(value: Any, factor: str) -> str:
    return str((Decimal(str(value)) * Decimal(factor)).quantize(Decimal("1")))


def corrupt(payload: dict[str, Any], section: str, mode: str, rng: random.Random) -> str:
    """Apply one corruption mode; returns the response text (possibly invalid JSON)."""
    data = json.loads(_json(payload))
    if mode == "truncate":
        text = _json(data)
        return text[: max(10, int(len(text) * 0.6))]
    if section == "header":
        if mode == "wrong_date" and data.get("advice_date"):
            from datetime import date

            d = date.fromisoformat(data["advice_date"]) + timedelta(days=3 * 365 + 40)
            data["advice_date"] = d.isoformat()
        elif mode == "drop_client" and len(data.get("client_names", [])) > 1:
            data["client_names"] = data["client_names"][:1]
        elif mode == "drop_client":
            data["client_names"] = []
        elif mode == "wrong_adviser":
            data["adviser_name"] = "Northshore Financial Advice Pty Ltd"
    elif section == "scope":
        if data["scope"]:
            data["scope"] = data["scope"][:-1]
        else:
            data["scope"] = ["estate"]
    elif section == "risk":
        if mode == "invalid_enum":
            data["risk_profile"] = "Aggressive"
        else:
            data["risk_profile"] = rng.choice(
                [r for r in RISK_PROFILES if r != data["risk_profile"]]
            )
    elif section == "recommendations":
        recs = data["recommendations"]
        if mode == "wrong_amount" and recs:
            i = rng.randrange(len(recs))
            recs[i]["amount"] = _scale(recs[i]["amount"] or 1000, "1.5")
        elif mode == "drop_item" and recs:
            recs.pop(rng.randrange(len(recs)))
        elif mode == "wrong_name" and recs:
            recs[rng.randrange(len(recs))]["product_name"] = "Zenith Alpha Fund"
        elif mode == "invalid_enum" and recs:
            recs[rng.randrange(len(recs))]["action"] = "purchase"
        else:
            data["recommendations"] = []
    elif section == "replacement":
        reps = data["replacements"]
        if mode == "drop_item" and reps:
            reps.pop(rng.randrange(len(reps)))
        elif mode == "wrong_fee_diff" and reps:
            reps[rng.randrange(len(reps))]["fee_difference_pa"] = _scale(
                reps[0]["fee_difference_pa"] or 100, "-2"
            )
        elif mode == "empty_reason" and reps:
            reps[rng.randrange(len(reps))]["reason"] = ""
        else:
            data["replacements"] = [
                {
                    "from_product": "Zenith Alpha Fund",
                    "to_product": "",
                    "fee_difference_pa": 0,
                    "insurance_impact": "none",
                    "reason": "",
                }
            ]
    elif section == "fees" and data.get("fees"):
        if mode == "wrong_amount":
            data["fees"]["ongoing_advice_fee_pa"] = _scale(
                data["fees"]["ongoing_advice_fee_pa"], "1.5"
            )
        else:
            data["fees"]["ongoing_fee_basis"] = "percent"
            data["fees"]["ongoing_fee_percent"] = None
    elif section == "authority":
        current = data["authority_to_proceed_signed"]
        data["authority_to_proceed_signed"] = not current if current is not None else True
    return _json(data)


def make_extraction_responder(
    gold_by_id: dict[str, SoAExtraction],
    *,
    corruption: float = 0.0,
    seed: int = 0,
    p_fix_on_reask: float = 0.7,
) -> Responder:
    def respond(messages: Sequence[ChatMessage]) -> str:
        user_messages = [m.content for m in messages if m.role == "user"]
        first = user_messages[0] if user_messages else ""
        doc_m = DOC_ID_PATTERN.search(first)
        sec_m = SECTION_PATTERN.search(first)
        doc_id = doc_m.group(1) if doc_m else ""
        section = sec_m.group(1) if sec_m else ""
        gold = gold_by_id.get(doc_id)
        if gold is None or section not in CORRUPTIONS:
            return "Sorry, I cannot help with that."
        attempt = len(messages)  # grows with retries / re-asks -> fresh draws
        rng = random.Random(f"{seed}:{doc_id}:{section}:{attempt}")
        payload = gold_section(gold, section)
        is_reask = any(REASK_MARKER in m for m in user_messages)
        payload["confidence"] = round(0.75 + 0.2 * rng.random(), 2)
        if is_reask and rng.random() < p_fix_on_reask:
            return _json(payload)
        if rng.random() < corruption:
            if rng.random() < 0.5:
                payload["confidence"] = round(0.4 + 0.3 * rng.random(), 2)
            mode = rng.choice(CORRUPTIONS[section])
            return corrupt(payload, section, mode, rng)
        text = _json(payload)
        return f"```json\n{text}\n```" if rng.random() < 0.2 else text

    return respond
