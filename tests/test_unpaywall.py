import httpx

from paperhub.http import HostRateLimiter, HttpClient
from paperhub.models import FullTextCandidate, PaperRecord
from paperhub.sources import FullTextFormat, SourceAccess, SourceName
from paperhub.unpaywall import UnpaywallClient, external_links, fallback_candidates


def _http(payload: dict) -> HttpClient:
    return HttpClient(
        user_agent="test",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
        rate_limiter=HostRateLimiter({}),
    )


def test_unpaywall_oa_location_becomes_approved_candidate() -> None:
    client = UnpaywallClient(
        _http(
            {
                "is_oa": True,
                "best_oa_location": {
                    "url_for_pdf": "https://repo.example/paper.pdf",
                    "license": "cc-by",
                },
            }
        ),
        email="reader@example.org",
    )
    candidate = client.find("10.1/fallback")
    assert candidate is not None
    assert candidate.source == SourceName.UNPAYWALL
    assert candidate.format == FullTextFormat.PDF
    assert candidate.access == SourceAccess.APPROVED_OPEN


def test_unpaywall_no_oa_and_missing_email_are_noop() -> None:
    assert (
        UnpaywallClient(_http({"is_oa": False}), email="reader@example.org").find("10.1/no") is None
    )
    assert UnpaywallClient(_http({"is_oa": True}), email=None).find("10.1/no") is None


def test_fallback_order_and_doi_external_link() -> None:
    record = PaperRecord(
        source=SourceName.CROSSREF, source_id="x", title="Paper", doi="10.1/fallback"
    )
    client = UnpaywallClient(
        _http(
            {"is_oa": True, "best_oa_location": {"url_for_pdf": "https://repo.example/paper.pdf"}}
        ),
        email="reader@example.org",
    )
    candidates = fallback_candidates(record, client)
    assert candidates[0].source == SourceName.UNPAYWALL
    assert external_links(record) == ("https://doi.org/10.1/fallback",)


def _native_xml_candidate() -> FullTextCandidate:
    return FullTextCandidate(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        url="https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML",
        format=FullTextFormat.JATS_XML,
        access=SourceAccess.APPROVED_OPEN,
        media_type="application/xml",
    )


def test_pdf_from_unpaywall_beats_native_xml() -> None:
    """ADR-0002: native 仅有 XML 时仍查 Unpaywall, 合法 PDF 排在 XML 前."""
    record = PaperRecord(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        title="OA paper",
        doi="10.1/xml-and-pdf",
        full_text_candidates=(_native_xml_candidate(),),
    )
    client = UnpaywallClient(
        _http({"is_oa": True, "best_oa_location": {"url_for_pdf": "https://repo.example/p.pdf"}}),
        email="reader@example.org",
    )
    candidates = fallback_candidates(record, client)
    assert [c.format for c in candidates] == [FullTextFormat.PDF, FullTextFormat.JATS_XML]
    assert candidates[0].source == SourceName.UNPAYWALL


def test_native_xml_falls_back_to_xml_when_unpaywall_has_no_pdf() -> None:
    record = PaperRecord(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        title="OA paper",
        doi="10.1/xml-only",
        full_text_candidates=(_native_xml_candidate(),),
    )
    client = UnpaywallClient(_http({"is_oa": False}), email="reader@example.org")
    candidates = fallback_candidates(record, client)
    assert [c.format for c in candidates] == [FullTextFormat.JATS_XML]


def test_native_pdf_skips_unpaywall_call() -> None:
    """ADR-0002: native PDF 已存在时不调 Unpaywall (省 API 调用)."""
    pdf_candidate = FullTextCandidate(
        source=SourceName.ARXIV,
        source_id="arxiv-1",
        url="https://arxiv.org/pdf/1",
        format=FullTextFormat.PDF,
        access=SourceAccess.APPROVED_OPEN,
        media_type="application/pdf",
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"is_oa": True})

    http = HttpClient(
        user_agent="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        rate_limiter=HostRateLimiter({}),
    )
    record = PaperRecord(
        source=SourceName.ARXIV,
        source_id="arxiv-1",
        title="Preprint",
        doi="10.1/pdf",
        full_text_candidates=(pdf_candidate,),
    )
    candidates = fallback_candidates(record, UnpaywallClient(http, email="reader@example.org"))
    assert [c.format for c in candidates] == [FullTextFormat.PDF]
    assert calls == []
