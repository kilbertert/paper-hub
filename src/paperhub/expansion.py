"""Bounded query-intent expansion through an OpenAI-compatible DeepSeek API."""

from __future__ import annotations

import csv
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .http import HttpClient
from .sources import SourceName

MODEL = "deepseek-v4-flash-0731"
PROMPT_VERSION = "query-expansion-v1"
MAX_TERMS = 12
MAX_PHRASES = 6
MAX_TEXT_LENGTH = 80


class QueryExpansionError(ValueError):
    """The provider response cannot be accepted as a bounded expansion."""


@dataclass(frozen=True, slots=True)
class QueryExpansion:
    intent: str
    include_terms: tuple[str, ...]
    phrases: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "include_terms": list(self.include_terms),
            "phrases": list(self.phrases),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> QueryExpansion:
        return validate_expansion(value)

    @classmethod
    def fallback(cls, query: str) -> QueryExpansion:
        value = " ".join(query.split())
        return cls(intent=value, include_terms=(value,), phrases=(value,))

    def with_original(self, query: str) -> QueryExpansion:
        original = " ".join(query.split())
        terms = (original,) + tuple(
            term for term in self.include_terms if term.casefold() != original.casefold()
        )
        phrases = (original,) + tuple(
            phrase for phrase in self.phrases if phrase.casefold() != original.casefold()
        )
        return QueryExpansion(self.intent, terms[:MAX_TERMS], phrases[:MAX_PHRASES])


class QueryExpander(Protocol):
    model: str
    prompt_version: str

    def expand(self, query: str) -> QueryExpansion: ...


def validate_expansion(value: dict[str, object]) -> QueryExpansion:
    if set(value) != {"intent", "include_terms", "phrases"}:
        raise QueryExpansionError(
            "expansion must contain exactly intent, include_terms, and phrases"
        )
    intent = _text(value["intent"], "intent", max_length=200)
    include_terms = _texts(value["include_terms"], "include_terms", MAX_TERMS)
    phrases = _texts(value["phrases"], "phrases", MAX_PHRASES)
    if not include_terms or not phrases:
        raise QueryExpansionError("expansion terms and phrases must not be empty")
    return QueryExpansion(intent, include_terms, phrases)


def _text(value: object, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise QueryExpansionError(f"{field} must contain strings")
    result = " ".join(value.split())
    if not result or len(result) > max_length or any(ord(char) < 32 for char in result):
        raise QueryExpansionError(f"{field} has invalid length or control characters")
    return result


def _texts(value: object, field: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise QueryExpansionError(f"{field} must be a list of at most {maximum} strings")
    return tuple(dict.fromkeys(_text(item, field, max_length=MAX_TEXT_LENGTH) for item in value))


class DeepSeekQueryExpander:
    model = MODEL
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = MODEL,
    ) -> None:
        self.http = http
        self.api_key = api_key or os.getenv("PAPERHUB_QUERY_EXPANSION_API_KEY")
        key_file = os.getenv("PAPERHUB_QUERY_EXPANSION_KEY_FILE")
        if not self.api_key and key_file:
            self.api_key = _read_key_file(key_file)
        self.base_url = base_url or os.getenv(
            "PAPERHUB_QUERY_EXPANSION_BASE_URL", "https://api.deepseek.com/v1"
        )
        self.model = model

    def expand(self, query: str) -> QueryExpansion:
        if not self.api_key:
            raise QueryExpansionError("query expansion API key is not configured")
        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = self.http.post_json(
            endpoint,
            json={
                "model": self.model,
                "temperature": 0,
                "max_tokens": 2048,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Expand one scholarly search query into bounded bilingual concepts. "
                            "Return JSON only with exactly: intent (string), include_terms (array "
                            "of at most 12 strings), phrases (array of at most 6 strings). "
                            "Preserve the user's topic; do not judge papers, add exclusions, or "
                            "return prose."
                        ),
                    },
                    {"role": "user", "content": json.dumps({"query": query}, ensure_ascii=False)},
                ],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not a string")
            return validate_expansion(json.loads(content)).with_original(query)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise QueryExpansionError("provider response is not valid expansion JSON") from error


def source_query(source: SourceName, expansion: QueryExpansion) -> str:
    """Build a conservative OR query accepted by each source's native parser."""
    clauses = tuple(
        dict.fromkeys(_quote(term) for term in expansion.phrases + expansion.include_terms)
    )
    joined = " OR ".join(clauses)
    if len(clauses) == 1 and expansion.include_terms == expansion.phrases:
        return expansion.include_terms[0]
    if source == SourceName.EUROPE_PMC:
        return f"({joined})"
    if source == SourceName.ARXIV:
        return f"all:({joined})"
    if source == SourceName.DOAJ:
        return f"({joined})"
    return joined


def _quote(value: str) -> str:
    value = " ".join(value.replace('"', " ").split())
    return f'"{value}"'


def _read_key_file(filename: str) -> str:
    path = Path(filename).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise QueryExpansionError("query expansion key file is unavailable") from error
    if mode & 0o077:
        raise QueryExpansionError("query expansion key file must not be group/world readable")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2 and row[0].strip() == "apiKey" and row[1].strip():
                    return row[1].strip()
    except (OSError, csv.Error) as error:
        raise QueryExpansionError("query expansion key file is invalid") from error
    raise QueryExpansionError("query expansion key file has no apiKey entry")
