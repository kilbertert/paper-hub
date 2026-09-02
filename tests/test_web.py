from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from paperhub.connectors import LiteratureConnector
from paperhub.downloads import ObjectStore
from paperhub.expansion import QueryExpansion, QueryExpansionError
from paperhub.http import HostRateLimiter, HttpClient
from paperhub.models import FullTextCandidate, PaperRecord, SearchPage
from paperhub.sources import FullTextFormat, SourceAccess, SourceName
from paperhub.storage import Library
from paperhub.web import create_app


class _Fake(LiteratureConnector):
    def __init__(self, source: SourceName, records: tuple[PaperRecord, ...]) -> None:
        self.source, self.records = source, records
        self.queries: list[str] = []

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        self.queries.append(query)
        return SearchPage(self.records, total=len(self.records))


class _FixedExpander:
    model = "deepseek-v4-flash-0731"
    prompt_version = "fixture-v1"

    def __init__(self, expansion: QueryExpansion | None = None) -> None:
        self.expansion = expansion or QueryExpansion(
            intent="AI customer service",
            include_terms=("AI", "customer service", "chatbot", "conversational AI"),
            phrases=("AI客服", "customer service chatbot"),
        )

    def expand(self, query: str) -> QueryExpansion:
        return self.expansion


class _FailingExpander(_FixedExpander):
    def expand(self, query: str) -> QueryExpansion:
        raise QueryExpansionError("fixture provider failure")


def test_search_api_filters_sources_year_and_oa_and_merges() -> None:
    duplicate_a = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="a",
        title="Nutrition same paper",
        doi="10.1/same",
        publication_year=2022,
    )
    duplicate_b = PaperRecord(
        source=SourceName.EUROPE_PMC,
        source_id="b",
        title="Nutrition same paper",
        doi="10.1/SAME",
        publication_year=2022,
        is_open_access=True,
    )
    too_old = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="old",
        title="Nutrition old",
        doi="10.1/old",
        publication_year=2018,
        is_open_access=True,
    )
    app = create_app(
        [
            _Fake(SourceName.CROSSREF, (duplicate_a, too_old)),
            _Fake(SourceName.EUROPE_PMC, (duplicate_b,)),
        ]
    )
    response = TestClient(app).get(
        "/api/search",
        params={
            "keywords": "nutrition",
            "sources": ["crossref", "europe_pmc"],
            "year_from": 2020,
            "year_to": 2024,
            "only_oa": "true",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["source"] == "europe_pmc"
    assert payload["results"][0]["doi"] == "10.1/same"


def test_search_api_rejects_reversed_year_range() -> None:
    response = TestClient(create_app([])).get(
        "/api/search", params={"keywords": "x", "year_from": 2025, "year_to": 2020}
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "year_from must be less than or equal to year_to",
        "results": [],
    }


def test_search_api_accepts_post_json() -> None:
    app = create_app([_Fake(SourceName.CROSSREF, ())])
    response = TestClient(app).post(
        "/api/search", json={"keywords": "nutrition", "sources": ["crossref"]}
    )
    assert response.status_code == 200
    assert response.json()["sources"] == ["crossref"]


def test_year_filter_excludes_records_without_a_year() -> None:
    record = PaperRecord(source=SourceName.CROSSREF, source_id="x", title="Unknown year")
    app = create_app([_Fake(SourceName.CROSSREF, (record,))])
    response = TestClient(app).get(
        "/api/search", params={"keywords": "nutrition", "year_from": 2020}
    )
    assert response.json()["count"] == 0


def test_homepage_contains_filters_and_security_headers() -> None:
    response = TestClient(create_app([])).get("/")
    assert response.status_code == 200
    assert "Europe PMC" in response.text
    assert 'id="only-oa"' in response.text
    assert "fetch('/api/search?" in response.text
    assert "show-favorites" in response.text
    assert "'/api/' + kind" in response.text
    assert "'/favorite'" in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_detail_page_renders_escaped_abstract_and_doi_link_after_search() -> None:
    record = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="x",
        title="A <paper>",
        abstract="<script>alert(1)</script>",
        doi="10.1/detail",
        publication_year=2024,
        keywords=("nutrition",),
    )
    client = TestClient(create_app([_Fake(SourceName.CROSSREF, (record,))]))
    search = client.get("/api/search", params={"keywords": "nutrition"})
    key = search.json()["results"][0]["canonical_key"]
    response = client.get(f"/papers/{key}")
    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "https://doi.org/10.1/detail" in response.text
    assert "知识点" in response.text


def test_detail_page_returns_404_for_unknown_key() -> None:
    assert TestClient(create_app([])).get("/papers/doi%3Amissing").status_code == 404


def test_download_endpoint_delivers_approved_asset(tmp_path: Path) -> None:
    candidate = FullTextCandidate(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        url="https://example.test/fulltext",
        format=FullTextFormat.PDF,
        access=SourceAccess.APPROVED_OPEN,
        media_type="application/pdf",
    )
    record = PaperRecord(
        source=SourceName.EUROPE_PMC,
        source_id="PMC1",
        title="Downloadable",
        doi="10.1/download",
        full_text_candidates=(candidate,),
        keywords=("nutrition",),
    )
    http = HttpClient(
        user_agent="test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, content=b"%PDF-1.7\nbody", headers={"content-type": "application/pdf"}
                )
            )
        ),
        rate_limiter=HostRateLimiter({}),
    )
    client = TestClient(
        create_app(
            [_Fake(SourceName.EUROPE_PMC, (record,))],
            http=http,
            object_store=ObjectStore(tmp_path / "objects"),
            library=Library(tmp_path / "library.sqlite"),
        )
    )
    key = client.get("/api/search", params={"keywords": "nutrition"}).json()["results"][0][
        "canonical_key"
    ]
    response = client.get(f"/api/papers/{key}/download")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert client.get("/api/downloads").json()["results"][0]["canonical_key"] == key


def test_favorite_and_download_lists_are_session_scoped(tmp_path: Path) -> None:
    record = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="x",
        title="Saved",
        doi="10.1/saved",
        keywords=("nutrition",),
    )
    app = create_app(
        [_Fake(SourceName.CROSSREF, (record,))],
        library=Library(tmp_path / "library.sqlite"),
    )
    client = TestClient(app)
    key = client.get("/api/search", params={"keywords": "nutrition"}).json()["results"][0][
        "canonical_key"
    ]
    assert client.post(f"/api/papers/{key}/favorite").json()["favorite"] is True
    assert client.get("/api/favorites").json()["results"][0]["canonical_key"] == key
    assert TestClient(app).get("/api/favorites").json()["results"] == []
    assert client.delete(f"/api/papers/{key}/favorite").json()["favorite"] is False
    assert client.get("/api/favorites").json()["results"] == []


def test_search_cache_skips_connector_until_refresh(tmp_path: Path) -> None:
    class CountingFake(_Fake):
        calls = 0

        def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
            self.calls += 1
            return super().search(query, limit=limit, cursor=cursor)

    fake = CountingFake(SourceName.CROSSREF, ())
    client = TestClient(create_app([fake], library=Library(tmp_path / "cache.sqlite")))
    params = {"keywords": "nutrition", "sources": ["crossref"]}
    client.get("/api/search", params=params)
    client.get("/api/search", params=params)
    client.get("/api/search", params={**params, "refresh": "true"})
    assert fake.calls == 2


def test_search_cache_ttl_expiry_triggers_new_search(tmp_path: Path) -> None:
    class CountingFake(_Fake):
        calls = 0

        def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
            self.calls += 1
            return super().search(query, limit=limit, cursor=cursor)

    library = Library(tmp_path / "cache.sqlite")
    fake = CountingFake(SourceName.CROSSREF, ())
    client = TestClient(create_app([fake], library=library))
    params = {"keywords": "nutrition", "sources": ["crossref"]}
    client.get("/api/search", params=params)
    library._db.execute("UPDATE search_cache SET created_at=0")
    library._db.commit()
    client.get("/api/search", params=params)
    assert fake.calls == 2


def test_cached_snapshot_can_render_in_a_new_app_instance(tmp_path: Path) -> None:
    record = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="x",
        title="Persisted detail",
        abstract="Stored abstract",
        doi="10.1/persisted",
        publication_year=2024,
        keywords=("nutrition",),
    )
    library = Library(tmp_path / "persistent.sqlite")
    first = TestClient(create_app([_Fake(SourceName.CROSSREF, (record,))], library=library))
    key = first.get("/api/search", params={"keywords": "nutrition"}).json()["results"][0][
        "canonical_key"
    ]
    second = TestClient(create_app([_Fake(SourceName.CROSSREF, ())], library=library))
    cached = second.get("/api/search", params={"keywords": "nutrition"})
    assert cached.json()["count"] == 1
    assert second.get(f"/papers/{key}").status_code == 200


def test_search_api_applies_expansion_gate_ranking_and_match_explanations() -> None:
    records = (
        PaperRecord(
            source=SourceName.CROSSREF,
            source_id="generic",
            title="Artificial intelligence in pediatric education",
        ),
        PaperRecord(
            source=SourceName.CROSSREF,
            source_id="title",
            title="Customer service chatbot evaluation",
        ),
        PaperRecord(
            source=SourceName.CROSSREF,
            source_id="abstract",
            title="Support systems",
            abstract="We evaluate conversational AI for customer service.",
        ),
    )
    fake = _Fake(SourceName.CROSSREF, records)
    client = TestClient(create_app([fake], query_expander=_FixedExpander()))
    payload = client.get(
        "/api/search", params={"keywords": "AI客服", "sources": ["crossref"], "limit": 10}
    ).json()

    assert payload["expansion_status"] == "model"
    assert payload["expanded_terms"][0] == "AI客服"
    assert len(payload["results"]) == 2
    assert [item["source_id"] for item in payload["results"]] == ["title", "abstract"]
    assert payload["results"][0]["match_fields"] == ["title"]
    assert "customer service chatbot" in payload["results"][0]["matched_terms"]
    assert " OR " in fake.queries[0]


def test_search_api_falls_back_without_unfiltered_results() -> None:
    fake = _Fake(
        SourceName.CROSSREF,
        (
            PaperRecord(
                source=SourceName.CROSSREF,
                source_id="generic",
                title="Artificial intelligence in medicine",
            ),
            PaperRecord(source=SourceName.CROSSREF, source_id="exact", title="AI客服系统"),
        ),
    )
    payload = (
        TestClient(create_app([fake], query_expander=_FailingExpander()))
        .get("/api/search", params={"keywords": "AI客服", "sources": ["crossref"]})
        .json()
    )
    assert payload["expansion_status"] == "fallback"
    assert [item["source_id"] for item in payload["results"]] == ["exact"]


def test_search_api_returns_available_sources_when_one_fails() -> None:
    class Failing(_Fake):
        def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
            raise httpx.HTTPStatusError(
                "upstream unavailable",
                request=httpx.Request("GET", "https://crossref.org"),
                response=httpx.Response(502),
            )

    available = _Fake(
        SourceName.EUROPE_PMC,
        (PaperRecord(source=SourceName.EUROPE_PMC, source_id="ok", title="AI客服系统"),),
    )
    payload = (
        TestClient(
            create_app(
                [Failing(SourceName.CROSSREF, ()), available],
                query_expander=_FailingExpander(),
            )
        )
        .get("/api/search", params={"keywords": "AI客服"})
        .json()
    )
    assert payload["count"] == 1
    assert payload["source_errors"] == {"crossref": "HTTPStatusError"}


def test_query_expansion_is_cached_and_prompt_version_invalidates_it(tmp_path: Path) -> None:
    class CountingExpander(_FixedExpander):
        calls = 0

        def __init__(self, version: str) -> None:
            super().__init__()
            self.prompt_version = version

        def expand(self, query: str) -> QueryExpansion:
            self.calls += 1
            return super().expand(query)

    library = Library(tmp_path / "expansion.sqlite")
    first_expander = CountingExpander("fixture-v1")
    first = TestClient(
        create_app(
            [_Fake(SourceName.CROSSREF, ())],
            query_expander=first_expander,
            library=library,
        )
    )
    params = {"keywords": "AI客服", "sources": ["crossref"]}
    first.get("/api/search", params=params)
    first.get("/api/search", params={**params, "refresh": "true"})
    assert first_expander.calls == 1

    second_expander = CountingExpander("fixture-v2")
    second = TestClient(
        create_app(
            [_Fake(SourceName.CROSSREF, ())],
            query_expander=second_expander,
            library=library,
        )
    )
    second.get("/api/search", params=params)
    assert second_expander.calls == 1


def test_corrupt_expansion_cache_falls_back_to_provider(tmp_path: Path) -> None:
    library = Library(tmp_path / "corrupt-expansion.sqlite")
    expander = _FixedExpander()
    client = TestClient(
        create_app([_Fake(SourceName.CROSSREF, ())], query_expander=expander, library=library)
    )
    key = '{"model": "deepseek-v4-flash-0731", "prompt_version": "fixture-v1", "query": "a"}'
    library.put_cached_expansion(key, {"invalid": True})
    response = client.get("/api/search", params={"keywords": "a", "sources": ["crossref"]})
    assert response.status_code == 200
    assert response.json()["expansion_status"] == "model"
