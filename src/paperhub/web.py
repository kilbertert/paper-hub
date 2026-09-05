"""Small FastAPI search surface over the connector and merge seams."""

from __future__ import annotations

import json
import os
import secrets
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
from .expansion import (
    DeepSeekQueryExpander,
    QueryExpander,
    QueryExpansion,
    QueryExpansionError,
    source_query,
)
from .http import HttpClient
from .merge import MergedPaper, merge_records
from .models import paper_record_from_dict
from .relevance import RULES_VERSION, rank_papers
from .sources import SourceName
from .storage import Library
from .unpaywall import UnpaywallClient, fallback_candidates


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
    refresh: bool = False

    @field_validator("keywords")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("keywords must not be blank")
        return value


def _download_failure(request: Request, status_code: int, status: str, message: str):
    """下载失败时按 Accept 内容协商: 浏览器导航得到友好 HTML, API 调用得到 JSON."""
    accept = request.headers.get("accept", "")
    if "text/html" not in accept:
        return JSONResponse({"status": status, "detail": message}, status_code=status_code)
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>下载不可用 · paper-hub</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:600px;margin:auto;padding:2rem;background:#f5f7fb;color:#172033}}main{{background:#fff;padding:1.5rem;border-radius:12px}}.warn{{border-left:4px solid #d97706;padding:.6rem 1rem;background:#fffbeb}}</style></head>
<body><main><h1>无法下载</h1>
<p class="warn">{message}</p>
<p><a href="/">← 返回搜索</a></p>
</main></body></html>""",
        status_code=status_code,
    )


def create_app(
    connectors: Iterable[LiteratureConnector] | None = None,
    *,
    http: HttpClient | None = None,
    object_store: ObjectStore | None = None,
    library: Library | None = None,
    query_expander: QueryExpander | None = None,
) -> FastAPI:
    app = FastAPI(title="paper-hub", version="0.1.0")
    http_client = http or HttpClient(user_agent="paper-hub/0.1")
    configured = tuple(default_connectors(http_client) if connectors is None else connectors)
    paper_index: dict[str, MergedPaper] = {}
    downloader = FullTextDownloader(http_client, object_store or ObjectStore(Path("var/objects")))
    library = library or Library(
        Path(":memory:" if connectors is not None else "var/paperhub.sqlite")
    )
    unpaywall = UnpaywallClient(http_client, email=os.getenv("PAPERHUB_UNPAYWALL_EMAIL"))
    query_expander = query_expander or DeepSeekQueryExpander(http_client)

    def get_item(canonical_key: str, session_id: str) -> MergedPaper | None:
        item = paper_index.get(canonical_key)
        if item is not None:
            return item
        payload = library.get_paper(session_id, canonical_key)
        if not payload:
            return None
        restored = paper_record_from_dict(payload)
        sources = tuple(
            SourceName(value) for value in payload.get("sources", [restored.source.value])
        )
        item = MergedPaper(restored, sources)
        paper_index[canonical_key] = item
        return item

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        session_id = request.cookies.get("paperhub_session") or secrets.token_urlsafe(18)
        request.state.session_id = session_id
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not request.cookies.get("paperhub_session"):
            response.set_cookie("paperhub_session", session_id, httponly=True, samesite="lax")
        return response

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    def run_search(request: SearchRequest, session_id: str) -> dict[str, object]:
        keywords = request.keywords
        sources = request.sources
        year_from = request.year_from
        year_to = request.year_to
        only_oa = request.only_oa
        limit = request.limit
        if year_from is not None and year_to is not None and year_from > year_to:
            return {"error": "year_from must be less than or equal to year_to", "results": []}
        normalized_query = " ".join(keywords.strip().casefold().split())
        expansion_key = json.dumps(
            {
                "query": normalized_query,
                "model": query_expander.model,
                "prompt_version": query_expander.prompt_version,
            },
            sort_keys=True,
        )
        expansion_status = "model"
        cached_expansion = library.get_cached_expansion(expansion_key)
        try:
            expansion = (
                QueryExpansion.from_dict(cached_expansion) if cached_expansion is not None else None
            )
        except (QueryExpansionError, TypeError):
            expansion = None
        if expansion is None:
            try:
                expansion = query_expander.expand(keywords.strip())
                library.put_cached_expansion(expansion_key, expansion.to_dict())
            except (QueryExpansionError, httpx.HTTPError, TimeoutError):
                expansion = QueryExpansion.fallback(keywords.strip())
                expansion_status = "fallback"
        cache_key = json.dumps(
            {
                "rules_version": RULES_VERSION,
                "keywords": normalized_query,
                "sources": sorted(source.value for source in sources or []),
                "year_from": year_from,
                "year_to": year_to,
                "only_oa": only_oa,
                "limit": limit,
                "expansion_status": expansion_status,
                "expansion": expansion.to_dict(),
                "expansion_model": query_expander.model,
                "expansion_prompt_version": query_expander.prompt_version,
            },
            sort_keys=True,
        )
        if not request.refresh:
            cached = library.get_cached_search(cache_key)
            if cached is not None:
                library.save_payloads(session_id, cached.get("results", []))
                return cached
        selected = tuple(c for c in configured if not sources or c.source in sources)
        source_queries = {
            connector.source: source_query(connector.source, expansion) for connector in selected
        }
        source_limit = min(100, max(limit * 3, 50))
        source_failures: dict[SourceName, str] = {}
        pages = search_connectors(
            selected, source_queries, limit=source_limit, failures=source_failures
        )
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
        merged = merge_records(filtered_records)
        ranked = rank_papers(merged, expansion, original_query=keywords.strip(), limit=limit)
        indexed = {item.item.record.canonical_key: item.item for item in ranked}
        paper_index.update(indexed)
        library.save_payloads(session_id, (item.to_dict() for item in ranked))
        payload = {
            "query": keywords.strip(),
            "query_intent": expansion.intent,
            "expanded_terms": list(dict.fromkeys(expansion.phrases + expansion.include_terms)),
            "expansion_status": expansion_status,
            "source_errors": source_failures,
            "sources": [c.source.value for c in selected],
            "count": len(ranked),
            "results": [item.to_dict() for item in ranked],
        }
        if not source_failures:
            library.put_cached_search(cache_key, payload)
        return payload

    @app.get("/api/search")
    def search(
        request: Request,
        keywords: Annotated[str, Query(min_length=1, max_length=300)],
        sources: Annotated[list[SourceName] | None, Query()] = None,
        year_from: Annotated[int | None, Query(ge=1000, le=3000)] = None,
        year_to: Annotated[int | None, Query(ge=1000, le=3000)] = None,
        only_oa: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        refresh: bool = False,
    ) -> dict[str, object]:
        return run_search(
            SearchRequest(
                keywords=keywords,
                sources=sources,
                year_from=year_from,
                year_to=year_to,
                only_oa=only_oa,
                limit=limit,
                refresh=refresh,
            ),
            request.state.session_id,
        )

    @app.post("/api/search")
    def search_post(body: SearchRequest, request: Request) -> dict[str, object]:
        return run_search(body, request.state.session_id)

    @app.get("/papers/{canonical_key:path}", response_class=HTMLResponse)
    def paper_detail(canonical_key: str, request: Request) -> HTMLResponse:
        item = get_item(canonical_key, request.state.session_id)
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
<p><a href="/api/papers/{quote(record.canonical_key, safe="")}/download">下载</a> · <a href="/">返回首页收藏</a></p>
</main></body></html>"""
        return HTMLResponse(html)

    @app.get("/api/papers/{canonical_key:path}/download")
    def download(canonical_key: str, request: Request):
        item = get_item(canonical_key, request.state.session_id)
        if item is None:
            return _download_failure(request, 404, "not_found", "论文不存在或会话已过期。")
        candidates = fallback_candidates(item.record, unpaywall)
        if not candidates:
            return _download_failure(request, 404, "metadata_only", "暂无开放全文，仅提供元数据。")
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                cached = downloader.acquire(candidate)
                library.record_download(request.state.session_id, canonical_key, cached.path)
                return FileResponse(
                    cached.path, media_type=cached.media_type, filename=cached.path.name
                )
            except (ValueError, RuntimeError, httpx.HTTPError) as error:
                last_error = error
        return _download_failure(request, 403, "not_downloadable", f"下载失败：{last_error}")

    @app.post("/api/papers/{canonical_key:path}/favorite")
    def favorite(canonical_key: str, request: Request) -> dict[str, object]:
        session_id = request.state.session_id
        if get_item(canonical_key, session_id) is None:
            return {"status": "not_found", "favorite": False}
        library.set_favorite(session_id, canonical_key, True)
        return {"status": "ok", "favorite": True, "canonical_key": canonical_key}

    @app.delete("/api/papers/{canonical_key:path}/favorite")
    def unfavorite(canonical_key: str, request: Request) -> dict[str, object]:
        library.set_favorite(request.state.session_id, canonical_key, False)
        return {"status": "ok", "favorite": False, "canonical_key": canonical_key}

    @app.get("/api/favorites")
    def favorites(request: Request) -> dict[str, object]:
        return {"results": library.list_papers(request.state.session_id, "favorites")}

    @app.get("/api/downloads")
    def downloads(request: Request) -> dict[str, object]:
        return {"results": library.list_papers(request.state.session_id, "downloads")}

    return app


app = create_app()
