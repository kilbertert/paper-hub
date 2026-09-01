"""Canonical data models shared by paper-hub source connectors."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any

from .sources import FullTextFormat, RightsStatus, SourceAccess, SourceName

# 六源: 前三者有开放全文资产, 后三者偏元数据+摘要.
PUBLISHED_SOURCES = (
    SourceName.EUROPE_PMC,
    SourceName.DOAJ,
    SourceName.ARXIV,
    SourceName.OPENALEX,
    SourceName.CROSSREF,
    SourceName.PUBMED,
)


def normalize_doi(value: str | None) -> str | None:
    """把各种带前缀/大小写的 DOI 归一化为裸 DOI (小写)."""
    if not value:
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi or None


class _TitleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def normalize_title_text(value: str) -> str:
    """去 HTML 实体并折叠空白, 得到干净的标题文本."""
    parser = _TitleTextParser()
    parser.feed(unescape(value))
    parser.close()
    return " ".join("".join(parser.parts).split())


def normalize_title(value: str) -> str:
    """NFKC + 小写 + 抽取单词, 用于标题指纹."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


@dataclass(frozen=True, slots=True)
class FullTextCandidate:
    """指向某来源的一篇全文资产 (下载校验与合规门控的依据)."""

    source: SourceName
    source_id: str
    url: str
    format: FullTextFormat
    access: SourceAccess
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    media_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.value
        data["format"] = self.format.value
        data["access"] = self.access.value
        data["rights_status"] = self.rights_status.value
        return data


@dataclass(slots=True)
class PaperRecord:
    """一个来源返回的一条归一化论文记录."""

    source: SourceName
    source_id: str
    title: str
    abstract: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    journal: str | None = None
    issns: tuple[str, ...] = ()
    publication_year: int | None = None
    authors: tuple[str, ...] = ()
    publication_types: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    is_open_access: bool | None = None
    full_text_candidates: tuple[FullTextCandidate, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        self.pmid = self.pmid.strip() if self.pmid else None
        self.pmcid = self.pmcid.strip().upper() if self.pmcid else None
        self.title = normalize_title_text(self.title)

    @property
    def canonical_key(self) -> str:
        """跨源合并去重的稳定键.

        优先级: DOI → PMID → PMCID → (归一化标题+年份) 指纹.
        """
        if self.doi:
            return f"doi:{self.doi}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.pmcid:
            return f"pmcid:{self.pmcid}"
        fingerprint = f"{normalize_title(self.title)}|{self.publication_year or ''}"
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        return f"title:{digest}"

    def to_dict(self, *, include_raw: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source": self.source.value,
            "source_id": self.source_id,
            "canonical_key": self.canonical_key,
            "title": self.title,
            "abstract": self.abstract,
            "doi": self.doi,
            "pmid": self.pmid,
            "pmcid": self.pmcid,
            "journal": self.journal,
            "issns": list(self.issns),
            "publication_year": self.publication_year,
            "authors": list(self.authors),
            "publication_types": list(self.publication_types),
            "keywords": list(self.keywords),
            "is_open_access": self.is_open_access,
            "full_text_candidates": [
                candidate.to_dict() for candidate in self.full_text_candidates
            ],
        }
        if include_raw:
            data["raw"] = self.raw
        return data


@dataclass(frozen=True, slots=True)
class SearchPage:
    """一次 connector search 返回的一页结果."""

    records: tuple[PaperRecord, ...]
    next_cursor: str | None = None
    total: int | None = None


def canonical_key(record: PaperRecord) -> str:
    """模块级便捷入口, 返回记录的跨源合并键."""
    return record.canonical_key


def paper_record_from_dict(data: dict[str, Any]) -> PaperRecord:
    """Restore a stored result snapshot without retaining raw API payloads."""
    candidates = tuple(
        FullTextCandidate(
            source=SourceName(item["source"]),
            source_id=item["source_id"],
            url=item["url"],
            format=FullTextFormat(item["format"]),
            access=SourceAccess(item["access"]),
            rights_status=RightsStatus(item.get("rights_status", RightsStatus.UNKNOWN.value)),
            media_type=item.get("media_type"),
        )
        for item in data.get("full_text_candidates", [])
    )
    return PaperRecord(
        source=SourceName(data["source"]),
        source_id=data["source_id"],
        title=data["title"],
        abstract=data.get("abstract"),
        doi=data.get("doi"),
        pmid=data.get("pmid"),
        pmcid=data.get("pmcid"),
        journal=data.get("journal"),
        issns=tuple(data.get("issns", [])),
        publication_year=data.get("publication_year"),
        authors=tuple(data.get("authors", [])),
        publication_types=tuple(data.get("publication_types", [])),
        keywords=tuple(data.get("keywords", [])),
        is_open_access=data.get("is_open_access"),
        full_text_candidates=candidates,
    )
