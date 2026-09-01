"""Merge duplicate source records into display-ready search results."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import PaperRecord
from .sources import SourceAccess, SourceName


@dataclass(frozen=True, slots=True)
class MergedPaper:
    record: PaperRecord
    sources: tuple[SourceName, ...]

    @property
    def primary_badge(self) -> str:
        doi = f" · {self.record.doi}" if self.record.doi else ""
        return f"{self.record.source.value}{doi}"

    @property
    def secondary_badges(self) -> tuple[str, ...]:
        return tuple(source.value for source in self.sources if source != self.record.source)

    def to_dict(self) -> dict[str, object]:
        return {
            **self.record.to_dict(include_raw=False),
            "sources": [source.value for source in self.sources],
            "primary_badge": self.primary_badge,
            "secondary_badges": list(self.secondary_badges),
        }


def _quality(record: PaperRecord) -> tuple[int, int]:
    downloadable = any(
        candidate.access in {SourceAccess.APPROVED_OPEN, SourceAccess.APPROVED_LICENSED}
        for candidate in record.full_text_candidates
    )
    fields = (
        record.abstract,
        record.doi,
        record.pmid,
        record.pmcid,
        record.journal,
        record.publication_year,
        record.authors,
        record.keywords,
    )
    return int(downloadable), sum(bool(value) for value in fields)


def merge_records(records: Iterable[PaperRecord]) -> tuple[MergedPaper, ...]:
    """Deduplicate records while preserving first-seen group order."""
    groups: dict[str, list[PaperRecord]] = {}
    for record in records:
        groups.setdefault(record.canonical_key, []).append(record)

    merged = []
    for candidates in groups.values():
        primary = max(candidates, key=_quality)
        sources = tuple(dict.fromkeys(record.source for record in candidates))
        merged.append(MergedPaper(record=primary, sources=sources))
    return tuple(merged)
