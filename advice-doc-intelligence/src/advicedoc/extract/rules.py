"""The rules extractor: section detection by headings, regexes for dates, fees and the risk
profile, table parsing for the recommendations / replacement / fee tables with a prose
fallback for the bullet-style layout, and fuzzy product matching against the master.
This is the baseline an engineer would write first, and it has to be decent."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

from advicedoc.classify.metadata import extract_metadata
from advicedoc.corpus.products import DEFAULT_MASTER, Product, ProductMaster
from advicedoc.extract import SECTION_NAMES, ExtractionResult
from advicedoc.extract.sections import Section, detect_sections
from advicedoc.ingest import Document, Table
from advicedoc.schema import (
    ACTIONS,
    INSURANCE_IMPACTS,
    PRODUCT_TYPES,
    RISK_PROFILES,
    SCOPE_AREAS,
    FeeSchedule,
    InsuranceImpact,
    ProductReplacement,
    ProductType,
    Recommendation,
    RiskProfile,
    ScopeArea,
    SoAExtraction,
)
from advicedoc.textutil import find_money, parse_money, parse_percent
from advicedoc.validate import validate_extraction

RISK_ALT = "|".join(sorted(RISK_PROFILES, key=len, reverse=True))
RISK_PATTERNS = (
    re.compile(rf"assessed your risk profile as (?:a |an )?({RISK_ALT})", re.IGNORECASE),
    re.compile(rf"risk profile\s*:\s*({RISK_ALT})", re.IGNORECASE),
    re.compile(rf"assessed as (?:a |an )?({RISK_ALT}) investor", re.IGNORECASE),
    re.compile(rf"\b({RISK_ALT})\b"),
)
SCOPE_KEYWORDS: dict[ScopeArea, tuple[str, ...]] = {
    "superannuation": ("superannuation", "super"),
    "retirement": ("retirement",),
    "insurance": ("insurance",),
    "investment": ("investment", "investing"),
    "debt": ("debt",),
}
COVERS = re.compile(r"advice covers\s*:?\s*(.+?)(?:\.|$)", re.IGNORECASE | re.DOTALL)
NOT_COVERS = re.compile(r"does not cover\s*:?\s*(.+?)(?:\.|$)", re.IGNORECASE | re.DOTALL)
LICENSEE = re.compile(r"([A-Z][A-Za-z&' ]+ Pty Ltd)")
AVAILABLE = re.compile(
    r"(?:funds available for investment|available funds for investment|investable funds)"
    r"\s*:?\s*([^\n]{0,40})",
    re.IGNORECASE,
)
ACTION_RE = re.compile(r"\b(" + "|".join(ACTIONS) + r")\b", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"account\s+([A-Z]{0,3}\d{4}-\d{4})", re.IGNORECASE)
REPL_PROSE = re.compile(
    r"we recommend replacing (?P<from>[^.]+?) with (?P<to>[^.]+?)\.\s*"
    r"Fee difference:\s*(?P<fee>[^.]*?) per annum\."
    r"\s*Insurance impact:\s*(?P<impact>[^.]+)\.\s*Reason:\s*(?P<reason>[^.]+)\.",
    re.IGNORECASE | re.DOTALL,
)
IMPACT_FROM_LABEL: dict[str, InsuranceImpact] = {
    "no change": "none",
    "none": "none",
    "reduced cover": "reduced_cover",
    "increased cover": "increased_cover",
    "cover lost": "cover_lost",
}
TYPE_FROM_LABEL: dict[str, ProductType] = {
    "superannuation": "super",
    "account-based pension": "pension",
    "investment (idps)": "idps",
    "managed portfolio": "managed_portfolio",
    "insurance": "insurance",
    "cash": "cash",
}
PRODUCT_MATCH_THRESHOLD = 85.0


@dataclass(frozen=True, slots=True)
class ProductHit:
    position: int
    product: Product
    score: float


def find_products(text: str, master: ProductMaster, *, threshold: float = 88.0) -> list[ProductHit]:
    """Master products mentioned in ``text`` (fuzzy, tolerant of OCR noise), by position."""
    hits: list[ProductHit] = []
    for product in master.products:
        alignment = fuzz.partial_ratio_alignment(product.name, text)
        if alignment is not None and alignment.score >= threshold:
            hits.append(ProductHit(alignment.dest_start, product, float(alignment.score)))
    hits.sort(key=lambda h: h.position)
    # Drop overlapping hits (a longer name containing a shorter one).
    kept: list[ProductHit] = []
    for h in hits:
        if kept and abs(h.position - kept[-1].position) < 6:
            if h.score > kept[-1].score or len(h.product.name) > len(kept[-1].product.name):
                kept[-1] = h
            continue
        kept.append(h)
    return kept


def _clean_prose(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\n- ", "\n").replace("- ", " ")).strip()


def _column(header: list[str], *names: str) -> int | None:
    lowered = [h.lower() for h in header]
    for name in names:
        for i, h in enumerate(lowered):
            if name in h:
                return i
    return None


def _cell(row: list[str], idx: int | None) -> str:
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def _to_type(label: str, product: Product | None) -> ProductType | None:
    if product is not None:
        return product.product_type
    lowered = label.lower().strip()
    if lowered in TYPE_FROM_LABEL:
        return TYPE_FROM_LABEL[lowered]
    for t in PRODUCT_TYPES:
        if t in lowered:
            return t
    return None


class RulesExtractor:
    def __init__(self, master: ProductMaster = DEFAULT_MASTER) -> None:
        self._master = master

    @property
    def name(self) -> str:
        return "rules"

    # ----- fields ---------------------------------------------------------------------------

    def _risk(self, sections: dict[str, Section], doc: Document) -> RiskProfile | None:
        texts = [sections["risk"].flat] if "risk" in sections else []
        texts.append(doc.text)
        for text in texts:
            for pattern in RISK_PATTERNS[:3]:
                m = pattern.search(text)
                if m:
                    return self._canon_risk(m.group(1))
        if "risk" in sections:
            m = RISK_PATTERNS[3].search(sections["risk"].flat)
            if m:
                return self._canon_risk(m.group(1))
        return None

    @staticmethod
    def _canon_risk(raw: str) -> RiskProfile | None:
        for rp in RISK_PROFILES:
            if rp.lower() == raw.lower():
                return rp
        return None

    @staticmethod
    def _scope(sections: dict[str, Section]) -> list[ScopeArea]:
        if "scope" not in sections:
            return []
        text = sections["scope"].flat
        covers = COVERS.search(text)
        excluded = NOT_COVERS.search(text)
        if not covers:
            return []
        covered_text = covers.group(1).lower()
        excluded_text = excluded.group(1).lower() if excluded else ""
        found: list[ScopeArea] = []
        for area in SCOPE_AREAS:
            in_cov = any(k in covered_text for k in SCOPE_KEYWORDS[area])
            in_exc = any(k in excluded_text for k in SCOPE_KEYWORDS[area])
            if in_cov and not in_exc:
                found.append(area)
        return found

    @staticmethod
    def _licensee(doc: Document) -> str | None:
        for line in doc.pages[0].lines if doc.pages else []:
            if "licensee" in line.lower():
                m = LICENSEE.search(line)
                if m:
                    return m.group(1).strip()
        m = LICENSEE.search(doc.text)
        return m.group(1).strip() if m else None

    @staticmethod
    def _available_funds(sections: dict[str, Section], doc: Document) -> Decimal | None:
        text = sections["situation"].flat if "situation" in sections else doc.text
        m = AVAILABLE.search(text)
        return parse_money(m.group(1)) if m else None

    def _match(self, name: str, scores: dict[str, float], key: str) -> Product | None:
        product, score = self._master.match(name, threshold=PRODUCT_MATCH_THRESHOLD)
        scores[key] = score
        return product

    def _recs_from_table(self, table: Table, scores: dict[str, float]) -> list[Recommendation]:
        header = table[0]
        i_action = _column(header, "action")
        i_product = _column(header, "product")
        i_type = _column(header, "type")
        i_amount = _column(header, "amount")
        i_account = _column(header, "account")
        recs: list[Recommendation] = []
        for row in table[1:]:
            # Cells can come back with words split across lines ("Contribut e"): compare
            # without whitespace.
            action_raw = _cell(row, i_action).lower().replace(" ", "")
            action = next((a for a in ACTIONS if a in action_raw), None)
            if action is None:
                continue
            product = self._match(_cell(row, i_product), scores, f"rec:{len(recs)}")
            ptype = _to_type(_cell(row, i_type), product)
            if ptype is None:
                continue
            account = re.sub(r"(?<=\S)\s+(?=\d)", "", _cell(row, i_account))
            recs.append(
                Recommendation(
                    action=action,
                    product_name=product.name if product else _cell(row, i_product),
                    product_type=ptype,
                    amount=parse_money(_cell(row, i_amount)),
                    account_ref=None if (not account or "new" in account.lower()) else account,
                )
            )
        return recs

    def _recs_from_prose(self, section: Section, scores: dict[str, float]) -> list[Recommendation]:
        text = _clean_prose(section.text)
        recs: list[Recommendation] = []
        for chunk in re.split(r"we recommend that you", text, flags=re.IGNORECASE)[1:]:
            sentence = chunk.split(". ")[0] + "."
            m = ACTION_RE.search(sentence)
            if not m:
                continue
            action = m.group(1).lower()
            hits = find_products(sentence, self._master)
            if not hits:
                continue
            chosen = hits[0]
            if action in {"switch", "rollover"} and len(hits) > 1:
                to_pos = sentence.lower().rfind(" to ")
                after = [h for h in hits if h.position > to_pos]
                chosen = after[0] if after else hits[-1]
            scores[f"rec:{len(recs)}"] = chosen.score
            money = find_money(sentence)
            acc = ACCOUNT_RE.search(sentence)
            recs.append(
                Recommendation.model_validate(
                    {
                        "action": action,
                        "product_name": chosen.product.name,
                        "product_type": chosen.product.product_type,
                        "amount": money[0][1] if money else None,
                        "account_ref": acc.group(1) if acc else None,
                    }
                )
            )
        return recs

    def _recommendations(
        self, sections: dict[str, Section], scores: dict[str, float]
    ) -> list[Recommendation]:
        section = sections.get("recommendations")
        if section is None:
            return []
        for table in section.tables:
            if _column(table[0], "action") is not None:
                return self._recs_from_table(table, scores)
        return self._recs_from_prose(section, scores)

    def _replacements(
        self, sections: dict[str, Section], scores: dict[str, float]
    ) -> list[ProductReplacement]:
        section = sections.get("replacement")
        if section is None:
            return []
        out: list[ProductReplacement] = []
        for table in section.tables:
            header = table[0]
            i_from = _column(header, "current")
            i_to = _column(header, "recommended")
            if i_from is None or i_to is None:
                continue
            i_fee = _column(header, "fee")
            i_impact = _column(header, "insurance")
            i_reason = _column(header, "reason")
            for row in table[1:]:
                out.append(
                    self._replacement(
                        _cell(row, i_from),
                        _cell(row, i_to),
                        _cell(row, i_fee),
                        _cell(row, i_impact),
                        _cell(row, i_reason),
                        scores,
                        len(out),
                    )
                )
            return out
        for m in REPL_PROSE.finditer(_clean_prose(section.text)):
            out.append(
                self._replacement(
                    m.group("from"),
                    m.group("to"),
                    m.group("fee"),
                    m.group("impact"),
                    m.group("reason"),
                    scores,
                    len(out),
                )
            )
        return out

    def _replacement(
        self,
        from_raw: str,
        to_raw: str,
        fee_raw: str,
        impact_raw: str,
        reason: str,
        scores: dict[str, float],
        index: int,
    ) -> ProductReplacement:
        from_p = self._match(from_raw, scores, f"repl:{index}:from")
        to_p = self._match(to_raw, scores, f"repl:{index}:to")
        impact: InsuranceImpact = IMPACT_FROM_LABEL.get(impact_raw.lower().strip(), "none")
        if impact_raw.lower().strip() not in IMPACT_FROM_LABEL:
            for candidate in INSURANCE_IMPACTS:
                if candidate.replace("_", " ") in impact_raw.lower():
                    impact = candidate
        return ProductReplacement(
            from_product=from_p.name if from_p else from_raw.strip(),
            to_product=to_p.name if to_p else to_raw.strip(),
            fee_difference_pa=parse_money(fee_raw) or Decimal(0),
            insurance_impact=impact,
            reason=reason.strip().rstrip("."),
        )

    @staticmethod
    def _after_label(text: str, label: str, width: int = 160) -> str | None:
        idx = text.lower().find(label)
        if idx < 0:
            return None
        return text[idx + len(label) : idx + len(label) + width]

    def _fees(self, sections: dict[str, Section], doc: Document) -> FeeSchedule | None:
        section = sections.get("fees")
        text = section.flat if section is not None else doc.text
        for table in section.tables if section is not None else []:
            if _column(table[0], "fee") is not None:
                text = " ".join(" ".join(row) for row in table) + " " + text
                break
        text = re.sub(r"\s+", " ", text)
        initial_raw = self._after_label(text, "initial advice fee")
        ongoing_raw = self._after_label(text, "ongoing advice fee")
        if initial_raw is None or ongoing_raw is None:
            return None
        initial = parse_money(initial_raw)
        if initial is None:
            return None
        percent = parse_percent(ongoing_raw[:40])
        ongoing_amount = parse_money(ongoing_raw)
        if ongoing_amount is None:
            return None
        admin_raw = self._after_label(text, "platform administration fee")
        premium_raw = self._after_label(text, "insurance premium")
        return FeeSchedule(
            initial_advice_fee=initial,
            ongoing_advice_fee_pa=ongoing_amount,
            ongoing_fee_basis="percent" if percent is not None else "flat",
            ongoing_fee_percent=percent,
            platform_admin_fee_pct=parse_percent(admin_raw) if admin_raw else None,
            insurance_premium_pa=parse_money(premium_raw) if premium_raw else None,
        )

    @staticmethod
    def _authority(sections: dict[str, Section]) -> bool | None:
        section = sections.get("authority")
        if section is None:
            return None
        text = section.flat.lower()
        if "signed electronically" in text:
            return True
        if "____" in text:
            return False
        return None

    # ----- entry point ----------------------------------------------------------------------

    def extract(self, doc: Document) -> ExtractionResult:
        started = time.perf_counter()
        sections = detect_sections(doc)
        meta = extract_metadata(doc)
        scores: dict[str, float] = {}
        extraction = SoAExtraction(
            client_names=meta.client_names,
            adviser_name=meta.adviser_name,
            licensee=self._licensee(doc),
            advice_date=meta.document_date,
            risk_profile=self._risk(sections, doc),
            scope=self._scope(sections),
            recommendations=self._recommendations(sections, scores),
            fees=self._fees(sections, doc),
            replacements=self._replacements(sections, scores),
            authority_to_proceed_signed=self._authority(sections),
        )
        found = {name: name in sections for name in SECTION_NAMES}
        missing = {name: "section heading not found" for name, ok in found.items() if not ok}
        available = self._available_funds(sections, doc)
        violations = validate_extraction(
            extraction,
            master=self._master,
            document_text=doc.text,
            available_funds=available,
            document_date=meta.document_date,
        )
        confidence = {
            key: min(1.0, score / 100.0) for key, score in scores.items() if key.startswith("rec:")
        }
        return ExtractionResult(
            strategy=self.name,
            doc_id=doc.source,
            extraction=extraction,
            sections_found=found,
            missing=missing,
            violations=violations,
            available_funds=available,
            latency_s=time.perf_counter() - started,
            field_confidence=confidence,
            product_scores=scores,
        )
