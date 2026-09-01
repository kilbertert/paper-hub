import httpx

from paperhub.http import HostRateLimiter, HttpClient
from paperhub.models import PaperRecord
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
