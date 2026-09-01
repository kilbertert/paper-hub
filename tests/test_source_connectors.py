"""T02: official API payloads normalize through LiteratureConnector.search()."""

from __future__ import annotations

import httpx

from paperhub.connectors import (
    ArxivConnector,
    CrossrefConnector,
    DoajConnector,
    EuropePmcConnector,
    OpenAlexConnector,
    PubmedConnector,
    StubConnector,
    search_connectors,
)
from paperhub.http import HostRateLimiter, HttpClient
from paperhub.sources import SourceAccess, SourceName


def _http(handler) -> HttpClient:
    return HttpClient(
        user_agent="paperhub-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        rate_limiter=HostRateLimiter({}),
    )


def test_europe_pmc_connector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["resultType"] == "core"
        return httpx.Response(
            200,
            json={
                "hitCount": 1,
                "nextCursorMark": "next",
                "resultList": {
                    "result": [
                        {
                            "id": "123",
                            "title": "A paper",
                            "abstractText": "Abstract",
                            "doi": "10.1/ABC",
                            "pmid": "123",
                            "pmcid": "PMC123",
                            "pubYear": "2024",
                            "journalTitle": "Journal",
                            "isOpenAccess": "Y",
                            "authorList": {"author": [{"fullName": "Ada Lovelace"}]},
                        }
                    ]
                },
            },
        )

    page = EuropePmcConnector(_http(handler)).search("nutrition")
    record = page.records[0]
    assert (record.source, record.doi, record.publication_year) == (
        SourceName.EUROPE_PMC,
        "10.1/abc",
        2024,
    )
    assert record.abstract == "Abstract"
    assert record.full_text_candidates[0].access == SourceAccess.APPROVED_OPEN
    assert page.next_cursor == "next"


def test_doaj_connector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/nutrition")
        return httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "id": "doaj-1",
                        "bibjson": {
                            "title": "DOAJ paper",
                            "abstract": "Open abstract",
                            "year": "2023",
                            "identifier": [{"type": "doi", "id": "10.2/DOAJ"}],
                            "author": [{"name": "Grace Hopper"}],
                            "journal": {"title": "OA Journal", "issns": ["1234-5678"]},
                            "link": [
                                {
                                    "type": "fulltext",
                                    "content_type": "PDF",
                                    "url": "https://publisher.example/paper.pdf",
                                }
                            ],
                        },
                    }
                ],
            },
        )

    record = DoajConnector(_http(handler)).search("nutrition").records[0]
    assert (record.source, record.doi, record.publication_year) == (
        SourceName.DOAJ,
        "10.2/doaj",
        2023,
    )
    assert record.is_open_access is True
    assert record.full_text_candidates[0].access == SourceAccess.MANUAL_REVIEW


def test_arxiv_connector() -> None:
    atom = b"""<?xml version='1.0'?>
    <feed xmlns='http://www.w3.org/2005/Atom'
          xmlns:opensearch='http://a9.com/-/spec/opensearch/1.1/'
          xmlns:arxiv='http://arxiv.org/schemas/atom'>
      <opensearch:totalResults>1</opensearch:totalResults>
      <entry><id>http://arxiv.org/abs/2401.00001v1</id><published>2024-01-02</published>
      <title> Arxiv   paper </title><summary> Summary text </summary>
      <author><name>Alan Turing</name></author><arxiv:doi>10.3/ARXIV</arxiv:doi>
      <link href='https://arxiv.org/pdf/2401.00001v1' type='application/pdf'/></entry>
    </feed>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search_query"] == "all:nutrition"
        return httpx.Response(200, content=atom, headers={"content-type": "application/atom+xml"})

    record = ArxivConnector(_http(handler)).search("nutrition").records[0]
    assert (record.source, record.title, record.doi, record.publication_year) == (
        SourceName.ARXIV,
        "Arxiv paper",
        "10.3/arxiv",
        2024,
    )
    assert record.full_text_candidates[0].access == SourceAccess.MANUAL_REVIEW


def test_openalex_connector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["cursor"] == "*"
        return httpx.Response(
            200,
            json={
                "meta": {"count": 1, "next_cursor": "next"},
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "OpenAlex paper",
                        "doi": "https://doi.org/10.4/OA",
                        "publication_year": 2022,
                        "abstract_inverted_index": {"Hello": [0], "world": [1]},
                        "authorships": [{"author": {"display_name": "Katherine Johnson"}}],
                        "primary_location": {
                            "source": {"display_name": "Journal", "issn": ["1111-2222"]}
                        },
                        "open_access": {"is_oa": True},
                        "type": "article",
                    }
                ],
            },
        )

    page = OpenAlexConnector(_http(handler)).search("nutrition")
    record = page.records[0]
    assert (record.source, record.doi, record.abstract, record.publication_year) == (
        SourceName.OPENALEX,
        "10.4/oa",
        "Hello world",
        2022,
    )
    assert page.next_cursor == "next"


def test_crossref_connector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query.bibliographic"] == "nutrition"
        return httpx.Response(
            200,
            json={
                "message": {
                    "total-results": 1,
                    "next-cursor": "next",
                    "items": [
                        {
                            "DOI": "10.5/CROSSREF",
                            "title": ["Crossref paper"],
                            "abstract": "<p>Abstract text</p>",
                            "published": {"date-parts": [[2021, 1, 1]]},
                            "author": [{"given": "Dorothy", "family": "Vaughan"}],
                            "container-title": ["Journal"],
                            "ISSN": ["2222-3333"],
                            "type": "journal-article",
                        }
                    ],
                }
            },
        )

    record = CrossrefConnector(_http(handler)).search("nutrition").records[0]
    assert (record.source, record.doi, record.abstract, record.publication_year) == (
        SourceName.CROSSREF,
        "10.5/crossref",
        "Abstract text",
        2021,
    )


def test_pubmed_connector() -> None:
    article = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
    <Article><Journal><ISSN>1234-5678</ISSN><JournalIssue><PubDate><Year>2020</Year>
    </PubDate></JournalIssue><Title>Journal</Title></Journal><ArticleTitle>PubMed paper</ArticleTitle>
    <Abstract><AbstractText Label='BACKGROUND'>Abstract text</AbstractText></Abstract>
    <AuthorList><Author><ForeName>Mary</ForeName><LastName>Jackson</LastName></Author></AuthorList>
    <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
    </Article><KeywordList><Keyword>nutrition</Keyword></KeywordList></MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType='pubmed'>123</ArticleId>
    <ArticleId IdType='doi'>10.6/PUBMED</ArticleId></ArticleIdList></PubmedData>
    </PubmedArticle></PubmedArticleSet>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(
                200,
                json={"esearchresult": {"count": "1", "idlist": ["123"]}},
            )
        assert request.url.params["id"] == "123"
        return httpx.Response(200, content=article, headers={"content-type": "application/xml"})

    record = PubmedConnector(_http(handler)).search("nutrition").records[0]
    assert (record.source, record.doi, record.abstract, record.publication_year) == (
        SourceName.PUBMED,
        "10.6/pubmed",
        "Abstract text",
        2020,
    )
    assert record.authors == ("Mary Jackson",)


def test_connectors_have_a_concurrent_orchestration_seam() -> None:
    pages = search_connectors([StubConnector()], "nutrition")
    assert pages[SourceName.ARXIV].records == ()
