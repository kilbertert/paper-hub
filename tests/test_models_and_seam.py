"""T01 测试 seam: 归一化模型 + LiteratureConnector 契约 + 存根 connector."""

from __future__ import annotations

import httpx

from paperhub.connectors import LiteratureConnector, StubConnector
from paperhub.http import HostRateLimiter, HttpClient
from paperhub.models import (
    FullTextCandidate,
    FullTextFormat,
    PaperRecord,
    SearchPage,
    SourceAccess,
    SourceName,
    canonical_key,
    normalize_doi,
    normalize_title,
)
from paperhub.policy import SourcePolicyError, SourcePolicyRegistry
from paperhub.sources import RightsStatus


def _http_with_handler(handler: httpx.MockTransport) -> HttpClient:
    client = httpx.Client(transport=handler)
    return HttpClient(
        user_agent="paperhub-test",
        client=client,
        rate_limiter=HostRateLimiter({}),
    )


class _EchoStubConnector(LiteratureConnector):
    """一个实现 seam 的存根: 回声 query, 返回一条固定 PaperRecord."""

    source = SourceName.ARXIV

    def __init__(self) -> None:
        self.last_query: str | None = None

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        self.last_query = query
        return SearchPage(
            records=(
                PaperRecord(
                    source=self.source,
                    source_id="arxiv:0101",
                    title="A Test Paper",
                    abstract="An abstract",
                    doi="10.1000/xyz",
                    publication_year=2024,
                ),
            ),
            total=1,
        )


def test_normalize_doi_strips_prefixes_and_folds_case() -> None:
    assert normalize_doi("https://doi.org/10.1000/XYZ") == "10.1000/xyz"
    assert normalize_doi("doi:10.1000/xyz") == "10.1000/xyz"
    assert normalize_doi("  10.1000/AbC  ") == "10.1000/abc"
    assert normalize_doi(None) is None
    assert normalize_doi("") is None


def test_normalize_title_drops_punct_and_folds_case() -> None:
    assert normalize_title("  Nutrition  & Healthy Ageing ") == "nutrition healthy ageing"
    assert normalize_title("Café-café?") == "café café"  # NFKC composes é (not strip é here)


def test_canonical_key_priorities() -> None:
    # doi wins
    record = PaperRecord(
        source=SourceName.ARXIV,
        source_id="x",
        title="T",
        doi="10.1/x",
        pmid="123",
        pmcid="PMC1",
    )
    assert canonical_key(record) == "doi:10.1/x"

    # pmid wins over pmcid, no doi
    record2 = PaperRecord(
        source=SourceName.ARXIV, source_id="x", title="T", pmid="123", pmcid="PMC1"
    )
    assert canonical_key(record2) == "pmid:123"

    # pmcid wins over title fingerprint
    record3 = PaperRecord(source=SourceName.ARXIV, source_id="x", title="T", pmcid="PMC1")
    assert canonical_key(record3) == "pmcid:PMC1"

    # title fingerprint last
    record4 = PaperRecord(source=SourceName.ARXIV, source_id="x", title="T")
    assert canonical_key(record4).startswith("title:")


def test_connector_seam_returns_normalized_record() -> None:
    stub = _EchoStubConnector()
    page = stub.search("nutrition")
    assert page.records
    record = page.records[0]
    assert record.source == SourceName.ARXIV
    assert record.title == "A Test Paper"
    assert record.doi == "10.1000/xyz"
    assert record.canonical_key == "doi:10.1000/xyz"


def test_stub_connectore_policy() -> None:
    # StubConnector 默认不联网, 返回空页
    stub = StubConnector()
    page = stub.search("anything")
    assert page.records == ()
    assert page.total == 0


def test_full_text_candidate_dict_uses_enum_values() -> None:
    candidate = FullTextCandidate(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        url="https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML",
        format=FullTextFormat.JATS_XML,
        access=SourceAccess.APPROVED_OPEN,
        rights_status=RightsStatus.REDISTRIBUTABLE,
        media_type="application/xml",
    )
    data = candidate.to_dict()
    assert data["source"] == "europe_pmc"
    assert data["format"] == "jats_xml"
    assert data["access"] == "approved_open"
    assert data["rights_status"] == "redistributable"


def test_paper_record_to_dict_roundtrip() -> None:
    record = PaperRecord(
        source=SourceName.DOAJ,
        source_id="doaj-1",
        title="  Nutrition  & Healthy Ageing ",
        doi="10.1000/ABC",
        publication_year=2025,
        authors=("Alice Example",),
    )
    data = record.to_dict(include_raw=False)
    assert data["source"] == "doaj"
    assert data["doi"] == "10.1000/abc"
    assert data["title"] == "Nutrition & Healthy Ageing"
    assert data["canonical_key"] == "doi:10.1000/abc"


def test_http_client_get_json_with_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "query=%22nutrition%22" in str(request.url) or "nutrition" in str(request.url)
        return httpx.Response(200, json={"total": 1})

    http = _http_with_handler(httpx.MockTransport(handler))
    payload = http.get_json("https://example.org/search", params={"query": "nutrition"})
    assert payload == {"total": 1}


def test_source_policy_allows_open_asset_and_blocks_bypass_url() -> None:
    policy = SourcePolicyRegistry()
    policy.require_download_allowed(
        FullTextCandidate(
            source=SourceName.ARXIV,
            source_id="1234.5678",
            url="https://arxiv.org/pdf/1234.5678",
            format=FullTextFormat.PDF,
            access=SourceAccess.APPROVED_OPEN,
        )
    )

    blocked = FullTextCandidate(
        source=SourceName.ARXIV,
        source_id="blocked",
        url="https://sci-hub.example/blocked",
        format=FullTextFormat.PDF,
        access=SourceAccess.APPROVED_OPEN,
    )
    try:
        policy.require_download_allowed(blocked)
    except SourcePolicyError:
        pass
    else:
        raise AssertionError("paywall-bypass URLs must be rejected")
