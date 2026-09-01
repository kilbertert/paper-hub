"""Small FastAPI search surface over the connector and merge seams."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field, field_validator

from .connectors import (
    ArxivConnector,
    CrossrefConnector,
    DoajConnector,
    EuropePmcConnector,
    LiteratureConnector,
    OpenAlexConnector,
    PubmedConnector,
    search_connectors,
)
from .http import HttpClient
from .merge import merge_records
from .sources import SourceName


def default_connectors(http: HttpClient) -> tuple[LiteratureConnector, ...]:
    return (
        EuropePmcConnector(http),
        DoajConnector(http),
        ArxivConnector(http),
        OpenAlexConnector(http),
        CrossrefConnector(http),
        PubmedConnector(http),
    )


class SearchRequest(BaseModel):
    keywords: str = Field(min_length=1, max_length=300)
    sources: list[SourceName] | None = None
    year_from: int | None = Field(default=None, ge=1000, le=3000)
    year_to: int | None = Field(default=None, ge=1000, le=3000)
    only_oa: bool = False
    limit: int = Field(default=25, ge=1, le=100)

    @field_validator("keywords")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("keywords must not be blank")
        return value


def create_app(
    connectors: Iterable[LiteratureConnector] | None = None, *, http: HttpClient | None = None
) -> FastAPI:
    app = FastAPI(title="paper-hub", version="0.1.0")
    configured = tuple(
        default_connectors(http or HttpClient(user_agent="paper-hub/0.1"))
        if connectors is None
        else connectors
    )

    def run_search(request: SearchRequest) -> dict[str, object]:
        keywords = request.keywords
        sources = request.sources
        year_from = request.year_from
        year_to = request.year_to
        only_oa = request.only_oa
        limit = request.limit
        if year_from is not None and year_to is not None and year_from > year_to:
            return {"error": "year_from must be less than or equal to year_to", "results": []}
        selected = tuple(c for c in configured if not sources or c.source in sources)
        pages = search_connectors(selected, keywords.strip(), limit=limit)
        records = (
            record
            for page in pages.values()
            for record in page.records
            if (
                year_from is None
                or (record.publication_year is not None and record.publication_year >= year_from)
            )
            and (
                year_to is None
                or (record.publication_year is not None and record.publication_year <= year_to)
            )
            and (not only_oa or record.is_open_access is True)
        )
        results = merge_records(records)
        return {
            "query": keywords.strip(),
            "sources": [c.source.value for c in selected],
            "count": len(results),
            "results": [item.to_dict() for item in results],
        }

    @app.get("/api/search")
    def search(
        keywords: Annotated[str, Query(min_length=1, max_length=300)],
        sources: Annotated[list[SourceName] | None, Query()] = None,
        year_from: Annotated[int | None, Query(ge=1000, le=3000)] = None,
        year_to: Annotated[int | None, Query(ge=1000, le=3000)] = None,
        only_oa: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> dict[str, object]:
        return run_search(
            SearchRequest(
                keywords=keywords,
                sources=sources,
                year_from=year_from,
                year_to=year_to,
                only_oa=only_oa,
                limit=limit,
            )
        )

    @app.post("/api/search")
    def search_post(request: SearchRequest) -> dict[str, object]:
        return run_search(request)

    return app


app = create_app()
