"""Small FastAPI search surface over the connector and merge seams."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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
from .downloads import FullTextDownloader, ObjectStore
from .http import HttpClient
from .merge import MergedPaper, merge_records
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
    connectors: Iterable[LiteratureConnector] | None = None,
    *,
    http: HttpClient | None = None,
    object_store: ObjectStore | None = None,
) -> FastAPI:
    app = FastAPI(title="paper-hub", version="0.1.0")
    http_client = http or HttpClient(user_agent="paper-hub/0.1")
    configured = tuple(default_connectors(http_client) if connectors is None else connectors)
    paper_index: dict[str, MergedPaper] = {}
    downloader = FullTextDownloader(http_client, object_store or ObjectStore(Path("var/objects")))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

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
        filtered_records = (
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
        results = merge_records(filtered_records)
        indexed = {item.record.canonical_key: item for item in results}
        paper_index.update(indexed)
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

    @app.get("/papers/{canonical_key:path}", response_class=HTMLResponse)
    def paper_detail(canonical_key: str) -> HTMLResponse:
        item = paper_index.get(canonical_key)
        if item is None:
            return HTMLResponse("<h1>论文不存在</h1>", status_code=404)
        record = item.record
        doi_link = (
            f'<a href="https://doi.org/{quote(record.doi, safe="/")}" '
            'target="_blank" rel="noopener noreferrer">'
            f"{escape(record.doi)}</a>"
            if record.doi
            else "暂无 DOI"
        )
        abstract = escape(record.abstract or "暂无摘要")
        html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(record.title)} · paper-hub</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:auto;padding:2rem;background:#f5f7fb;color:#172033}}main{{background:#fff;padding:1.5rem;border-radius:12px}}.meta{{color:#64748b}}.placeholder{{border-left:4px solid #2563eb;padding:.6rem 1rem;background:#eff6ff}}button{{padding:.55rem .8rem;margin-right:.5rem}}</style></head>
<body><main><p><a href="/">← 返回搜索</a></p><h1>{escape(record.title)}</h1>
<p class="meta">来源：{escape(item.primary_badge)} · 年份：{record.publication_year or "未知"}</p>
<p class="meta">DOI：{doi_link}</p><h2>摘要</h2><p>{abstract}</p>
<h2>知识点</h2><p class="placeholder">知识点整理将在后续版本提供；当前仅展示来源摘要。</p>
<p><button type="button" disabled>下载</button><button type="button" disabled>收藏</button></p>
</main></body></html>"""
        return HTMLResponse(html)

    @app.get("/api/papers/{canonical_key:path}/download")
    def download(canonical_key: str):
        item = paper_index.get(canonical_key)
        if item is None:
            return JSONResponse({"status": "not_found"}, status_code=404)
        candidates = tuple(item.record.full_text_candidates)
        if not candidates:
            return JSONResponse(
                {"status": "metadata_only", "detail": "No open full-text asset"}, status_code=404
            )
        try:
            cached = downloader.acquire(candidates[0])
        except (ValueError, RuntimeError, httpx.HTTPError) as error:
            return JSONResponse(
                {"status": "not_downloadable", "detail": str(error)}, status_code=403
            )
        return FileResponse(cached.path, media_type=cached.media_type, filename=cached.path.name)

    return app


app = create_app()
