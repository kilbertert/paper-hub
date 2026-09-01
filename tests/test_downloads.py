from pathlib import Path

import httpx
import pytest

from paperhub.downloads import FullTextDownloader, InvalidFullText, ObjectStore, validate_full_text
from paperhub.http import HostRateLimiter, HttpClient
from paperhub.models import FullTextCandidate
from paperhub.sources import FullTextFormat, SourceAccess, SourceName


def _candidate(format: FullTextFormat = FullTextFormat.PDF) -> FullTextCandidate:
    return FullTextCandidate(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        url="https://example.test/fulltext",
        format=format,
        access=SourceAccess.APPROVED_OPEN,
        media_type="application/pdf" if format == FullTextFormat.PDF else "application/xml",
    )


def test_pdf_and_article_xml_magic_validation() -> None:
    validate_full_text(b"%PDF-1.7\n", FullTextFormat.PDF)
    validate_full_text(b"<article><body/></article>", FullTextFormat.JATS_XML)
    with pytest.raises(InvalidFullText):
        validate_full_text(b"<html/>", FullTextFormat.JATS_XML)
    with pytest.raises(InvalidFullText):
        validate_full_text(b"not a pdf", FullTextFormat.PDF)


def test_downloader_caches_valid_content(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, content=b"%PDF-1.7\ncontent", headers={"content-type": "application/pdf"}
        )

    http = HttpClient(
        user_agent="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        rate_limiter=HostRateLimiter({}),
    )
    downloader = FullTextDownloader(http, ObjectStore(tmp_path / "objects"))
    first = downloader.acquire(_candidate())
    second = downloader.acquire(_candidate())
    assert first.path == second.path
    assert first.path.read_bytes().startswith(b"%PDF-")
    assert calls == 1


def test_invalid_content_does_not_leave_a_cache_file(tmp_path: Path) -> None:
    http = HttpClient(
        user_agent="test",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"html"))
        ),
        rate_limiter=HostRateLimiter({}),
    )
    store = ObjectStore(tmp_path / "objects")
    with pytest.raises(InvalidFullText):
        FullTextDownloader(http, store).acquire(_candidate())
    assert list(store.root.iterdir()) == []
