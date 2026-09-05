"""Unpaywall legal-OA fallback and DOI/source link planning."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .http import HttpClient
from .models import FullTextCandidate, PaperRecord
from .sources import FullTextFormat, RightsStatus, SourceAccess, SourceName


@dataclass(frozen=True, slots=True)
class UnpaywallClient:
    http: HttpClient
    email: str | None = None

    def find(self, doi: str) -> FullTextCandidate | None:
        if not self.email:
            return None
        payload = self.http.get_json(
            f"https://api.unpaywall.org/v2/{quote(doi, safe='')}", params={"email": self.email}
        )
        if payload.get("is_oa") is not True:
            return None
        location = payload.get("best_oa_location") or next(
            (
                item
                for item in payload.get("oa_locations", [])
                if item.get("url_for_pdf") or item.get("url")
            ),
            None,
        )
        if not location:
            return None
        url = location.get("url_for_pdf")
        if not url:
            return None
        return FullTextCandidate(
            source=SourceName.UNPAYWALL,
            source_id=doi,
            url=url,
            format=FullTextFormat.PDF,
            access=SourceAccess.APPROVED_OPEN,
            rights_status=RightsStatus.REDISTRIBUTABLE
            if location.get("license")
            else RightsStatus.UNKNOWN,
            media_type="application/pdf",
        )


def fallback_candidates(
    record: PaperRecord, unpaywall: UnpaywallClient
) -> tuple[FullTextCandidate, ...]:
    """按格式优先级返回候选: PDF 优先, XML 兜底 (ADR-0002).

    native PDF 已存在时不查 Unpaywall (省 API 调用); native 仅有 XML 时
    仍尝试 Unpaywall 的合法 PDF, 命中则 PDF 排在 XML 之前.
    """
    native = tuple(
        candidate
        for candidate in record.full_text_candidates
        if candidate.access in {SourceAccess.APPROVED_OPEN, SourceAccess.APPROVED_LICENSED}
    )
    native_pdf = any(candidate.format == FullTextFormat.PDF for candidate in native)
    fallback = unpaywall.find(record.doi) if record.doi and not native_pdf else None
    return _pdf_first(native + ((fallback,) if fallback else ()))


def _pdf_first(candidates: tuple[FullTextCandidate, ...]) -> tuple[FullTextCandidate, ...]:
    return tuple(sorted(candidates, key=lambda candidate: candidate.format != FullTextFormat.PDF))


def external_links(record: PaperRecord) -> tuple[str, ...]:
    return (f"https://doi.org/{quote(record.doi, safe='/')}",) if record.doi else ()
