from fastapi.testclient import TestClient

from paperhub.connectors import LiteratureConnector
from paperhub.models import PaperRecord, SearchPage
from paperhub.sources import SourceName
from paperhub.web import create_app


class _Fake(LiteratureConnector):
    def __init__(self, source: SourceName, records: tuple[PaperRecord, ...]) -> None:
        self.source, self.records = source, records

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        assert query == "nutrition"
        return SearchPage(self.records, total=len(self.records))


def test_search_api_filters_sources_year_and_oa_and_merges() -> None:
    duplicate_a = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="a",
        title="Same paper",
        doi="10.1/same",
        publication_year=2022,
    )
    duplicate_b = PaperRecord(
        source=SourceName.EUROPE_PMC,
        source_id="b",
        title="Same paper",
        doi="10.1/SAME",
        publication_year=2022,
        is_open_access=True,
    )
    too_old = PaperRecord(
        source=SourceName.CROSSREF,
        source_id="old",
        title="Old",
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
