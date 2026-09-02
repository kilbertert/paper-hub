"""Deterministic relevance gating and ranking for normalized paper records."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .expansion import QueryExpansion
from .merge import MergedPaper

RULES_VERSION = "relevance-v2"
GENERIC_TERMS = frozenset({"ai", "artificial intelligence", "artificial", "intelligence"})


@dataclass(frozen=True, slots=True)
class RankedPaper:
    item: MergedPaper
    match_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]
    score: int

    def to_dict(self) -> dict[str, object]:
        return {
            **self.item.to_dict(),
            "match_fields": list(self.match_fields),
            "matched_terms": list(self.matched_terms),
        }


def rank_papers(
    papers: tuple[MergedPaper, ...],
    expansion: QueryExpansion,
    *,
    original_query: str,
    limit: int,
) -> tuple[RankedPaper, ...]:
    ranked = []
    for order, item in enumerate(papers):
        match = _match(item, expansion, original_query)
        if match is not None:
            fields, terms, score = match
            ranked.append((-(score), order, RankedPaper(item, fields, terms, score)))
    ranked.sort(key=lambda value: (value[0], value[1]))
    return tuple(value[2] for value in ranked[:limit])


def _match(
    item: MergedPaper, expansion: QueryExpansion, original_query: str
) -> tuple[tuple[str, ...], tuple[str, ...], int] | None:
    record = item.record
    texts = {
        "title": _normalize(record.title),
        "abstract": _normalize(record.abstract or ""),
        "keywords": _normalize(" ".join(record.keywords)),
    }
    fields: list[str] = []
    terms: list[str] = []
    score = 0
    phrase_hits = []
    for phrase in expansion.phrases:
        for field, text in texts.items():
            if _contains(text, phrase):
                phrase_hits.append((phrase, field))
                if phrase not in terms:
                    terms.append(phrase)
                if field not in fields:
                    fields.append(field)

    for term in expansion.include_terms:
        for field, text in texts.items():
            if _contains(text, term):
                if term not in terms:
                    terms.append(term)
                if field not in fields:
                    fields.append(field)

    if not fields:
        return None
    matched_non_generic = any(term.casefold() not in GENERIC_TERMS for term in terms)
    raw_is_generic = _normalize(original_query).casefold() in GENERIC_TERMS
    if not matched_non_generic and not raw_is_generic:
        return None
    title_phrases = sum(field == "title" for _, field in phrase_hits)
    abstract_phrases = sum(field == "abstract" for _, field in phrase_hits)
    keyword_phrases = sum(field == "keywords" for _, field in phrase_hits)
    title_terms = sum(
        _contains(texts["title"], term) and term.casefold() not in GENERIC_TERMS
        for term in expansion.include_terms
    )
    abstract_terms = sum(
        _contains(texts["abstract"], term) and term.casefold() not in GENERIC_TERMS
        for term in expansion.include_terms
    )
    keyword_terms = sum(
        _contains(texts["keywords"], term) and term.casefold() not in GENERIC_TERMS
        for term in expansion.include_terms
    )
    # Keep the product's declared order stable: exact title phrase, title terms,
    # abstract phrase/terms, then keyword phrase/terms.
    score = max(
        1000 + title_phrases if title_phrases else 0,
        700 + title_terms if title_terms else 0,
        400 + abstract_phrases if abstract_phrases else 0,
        300 + abstract_terms if abstract_terms else 0,
        200 + keyword_phrases if keyword_phrases else 0,
        150 + keyword_terms if keyword_terms else 0,
    )
    return tuple(fields), tuple(terms), score


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _contains(text: str, term: str) -> bool:
    value = _normalize(term)
    if not value:
        return False
    if re.search(r"[\u3400-\u9fff]", value):
        return value in text
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, flags=re.UNICODE) is not None
