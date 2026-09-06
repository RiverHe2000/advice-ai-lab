"""Small text utilities for the verifier: content words with light stemming, note boilerplate
treated as stop words, and the advice-domain lexicon that separates a claim about a
contribution cap from one about the footy."""

from __future__ import annotations

import re

from filenote.numbers import NUMBER_WORDS

_TOKEN_RE = re.compile(r"[a-z][a-z'-]*[a-z]|[a-z]")

_STOPWORD_TEXT = """
a an the and or of to in on at for with by from is are was were be been has have had will
would could should this that these those it its as per about now new next also may might
than then there their they them we our you your i me my he she his her him who what which
when where how all any some such no not only own same so too very can just do does did done
into over under up down out off again further once here more most other than
client clients adviser advisers discussed agreed agree noted note meeting year years month
months approximately around following currently previously expects expected wants want like
one two three get got going go make made confirmed confirm still
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())

_DOMAIN_TEXT = """
super superannuation pension contribution concessional non-concessional cap caps salary
sacrifice bring-forward insurance cover premium premiums life tpd income protection fee fees
platform advice risk profile balanced growth conservative portfolio portfolios investment invest
option fund funds retire retirement retiring mortgage inheritance estate probate dependant
dependants beneficiary nomination binding death benefit centrelink age consent statement
disclosure soa roa fact-find fact goal goals budget deposit emergency school job employer
promotion role salary wage hours work health surgery hospital medical baby child children
spouse partner bereavement bereaved depression hearing language writing paperwork capacity
understanding vulnerability review appointment follow-up switch switching product compare
comparison underwriting drawdown assets asset tax taxed lodge claim renewal renew level
northshore licensee related conflict conflicts related-party volatility return returns
"""
DOMAIN_LEXICON = frozenset(_DOMAIN_TEXT.split())


def stem(word: str) -> str:
    w = word.removesuffix("'s")
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def content_words(text: str) -> set[str]:
    """Stemmed content words: no stop words, no possessive suffixes, and no spoken-number
    words (figures are compared separately after normalisation)."""
    out: set[str] = set()
    for t in tokens(text):
        base = t.removesuffix("'s")
        if base in STOPWORDS or base in NUMBER_WORDS or len(base) <= 2:
            continue
        out.add(stem(base))
    return out


_DOMAIN_STEMS = frozenset(stem(w) for w in DOMAIN_LEXICON)
# Words that occur in transition chatter ("let's go through your goals", "I just need to find
# that statement") and do not on their own make a sentence advice content.
GENERIC_DOMAIN = frozenset({"goal", "goals", "review", "statement", "appointment", "plan"})
_GENERIC_STEMS = frozenset(stem(w) for w in GENERIC_DOMAIN)


def domain_terms(text: str, *, substantive: bool = True) -> set[str]:
    terms = {t for t in content_words(text) if t in _DOMAIN_STEMS}
    return terms - _GENERIC_STEMS if substantive else terms


def overlap(claim: str, evidence: str) -> float:
    """Fraction of the claim's content words that appear in the evidence (1.0 if no words)."""
    cw = content_words(claim)
    if not cw:
        return 1.0
    return len(cw & content_words(evidence)) / len(cw)
