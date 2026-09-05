"""Official API adapters for paper-hub's six literature sources."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, ClassVar
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

from ..http import HttpClient
from ..models import FullTextCandidate, PaperRecord, SearchPage, normalize_title_text
from ..sources import FullTextFormat, RightsStatus, SourceAccess, SourceName
from .base import LiteratureConnector


def _year(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join("".join(element.itertext()).split())
    return value or None


def _abstract_from_inverted(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(words))


class EuropePmcConnector(LiteratureConnector):
    source = SourceName.EUROPE_PMC
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        params: dict[str, object] = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": limit,
        }
        if cursor:
            params["cursorMark"] = cursor
        payload = self.http.get_json(self.url, params=params)
        records = tuple(
            self._record(item) for item in payload.get("resultList", {}).get("result", [])
        )
        return SearchPage(
            records=records,
            next_cursor=payload.get("nextCursorMark"),
            total=payload.get("hitCount"),
        )

    def _record(self, item: dict[str, Any]) -> PaperRecord:
        pmcid = item.get("pmcid")
        candidates: tuple[FullTextCandidate, ...] = ()
        if pmcid and item.get("isOpenAccess") == "Y":
            candidates = (
                FullTextCandidate(
                    source=self.source,
                    source_id=pmcid,
                    url=(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"),
                    format=FullTextFormat.JATS_XML,
                    access=SourceAccess.APPROVED_OPEN,
                    rights_status=RightsStatus.UNKNOWN,
                    media_type="application/xml",
                ),
            )
        return PaperRecord(
            source=self.source,
            source_id=str(pmcid or item.get("id") or item.get("pmid") or ""),
            title=item.get("title") or "Untitled",
            abstract=item.get("abstractText"),
            doi=item.get("doi"),
            pmid=item.get("pmid"),
            pmcid=pmcid,
            journal=item.get("journalTitle"),
            publication_year=_year(item.get("pubYear")),
            authors=tuple(
                author.get("fullName", "")
                for author in item.get("authorList", {}).get("author", [])
                if author.get("fullName")
            ),
            is_open_access=item.get("isOpenAccess") == "Y",
            full_text_candidates=candidates,
            raw=item,
        )


class DoajConnector(LiteratureConnector):
    source = SourceName.DOAJ
    base_url = "https://doaj.org/api/search/articles"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.http.rate_limiter.intervals.setdefault("doaj.org", 0.5)

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        page = int(cursor or 1)
        payload = self.http.get_json(
            f"{self.base_url}/{quote(query, safe='')}",
            params={"page": page, "pageSize": limit},
        )
        total = int(payload.get("total", 0))
        return SearchPage(
            records=tuple(self._record(item) for item in payload.get("results", [])),
            next_cursor=str(page + 1) if page * limit < total else None,
            total=total,
        )

    def _record(self, item: dict[str, Any]) -> PaperRecord:
        data = item.get("bibjson", {})
        identifiers = {entry.get("type"): entry.get("id") for entry in data.get("identifier", [])}
        link = next(
            (entry for entry in data.get("link", []) if entry.get("type") == "fulltext"),
            None,
        )
        candidates: tuple[FullTextCandidate, ...] = ()
        if link and link.get("url"):
            content_type = str(link.get("content_type", "")).casefold()
            candidates = (
                FullTextCandidate(
                    source=self.source,
                    source_id=str(item.get("id", "")),
                    url=link["url"],
                    format=FullTextFormat.PDF if "pdf" in content_type else FullTextFormat.HTML,
                    access=SourceAccess.MANUAL_REVIEW,
                    media_type=content_type or None,
                ),
            )
        journal = data.get("journal", {})
        return PaperRecord(
            source=self.source,
            source_id=str(item.get("id", "")),
            title=data.get("title") or "Untitled",
            abstract=data.get("abstract"),
            doi=identifiers.get("doi"),
            journal=journal.get("title"),
            issns=tuple(journal.get("issns", [])),
            publication_year=_year(data.get("year")),
            authors=tuple(
                author.get("name", "") for author in data.get("author", []) if author.get("name")
            ),
            keywords=tuple(data.get("keywords", [])),
            is_open_access=True,
            full_text_candidates=candidates,
            raw=item,
        )


class ArxivConnector(LiteratureConnector):
    source = SourceName.ARXIV
    url = "https://export.arxiv.org/api/query"
    atom: ClassVar[dict[str, str]] = {
        "a": "http://www.w3.org/2005/Atom",
        "o": "http://a9.com/-/spec/opensearch/1.1/",
        "x": "http://arxiv.org/schemas/atom",
    }

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.http.rate_limiter.intervals.setdefault("export.arxiv.org", 3.0)

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        start = int(cursor or 0)
        response = self.http.get_bytes(
            self.url,
            params={"search_query": f"all:{query}", "start": start, "max_results": limit},
            max_bytes=5_000_000,
        )
        root = ET.fromstring(response.content)
        records = tuple(self._record(entry) for entry in root.findall("a:entry", self.atom))
        total = int(root.findtext("o:totalResults", "0", self.atom))
        next_cursor = str(start + len(records)) if start + len(records) < total else None
        return SearchPage(records=records, next_cursor=next_cursor, total=total)

    def _record(self, entry: ET.Element) -> PaperRecord:
        identifier = (_text(entry.find("a:id", self.atom)) or "").rsplit("/", 1)[-1]
        pdf_url = next(
            (
                link.get("href")
                for link in entry.findall("a:link", self.atom)
                if link.get("type") == "application/pdf"
            ),
            None,
        )
        candidates = (
            (
                FullTextCandidate(
                    source=self.source,
                    source_id=identifier,
                    url=pdf_url,
                    format=FullTextFormat.PDF,
                    access=SourceAccess.MANUAL_REVIEW,
                    rights_status=RightsStatus.UNKNOWN,
                    media_type="application/pdf",
                ),
            )
            if pdf_url
            else ()
        )
        return PaperRecord(
            source=self.source,
            source_id=identifier,
            title=_text(entry.find("a:title", self.atom)) or "Untitled",
            abstract=_text(entry.find("a:summary", self.atom)),
            doi=_text(entry.find("x:doi", self.atom)),
            journal=_text(entry.find("x:journal_ref", self.atom)),
            publication_year=_year(_text(entry.find("a:published", self.atom))),
            authors=tuple(
                value
                for author in entry.findall("a:author", self.atom)
                if (value := _text(author.find("a:name", self.atom)))
            ),
            keywords=tuple(
                category.get("term", "") for category in entry.findall("a:category", self.atom)
            ),
            is_open_access=True,
            full_text_candidates=candidates,
            raw={"arxiv_id": identifier},
        )


class OpenAlexConnector(LiteratureConnector):
    source = SourceName.OPENALEX
    url = "https://api.openalex.org/works"

    def __init__(self, http: HttpClient, *, mailto: str | None = None) -> None:
        self.http = http
        self.mailto = mailto

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        params: dict[str, object] = {"search": query, "per_page": limit, "cursor": cursor or "*"}
        if self.mailto:
            params["mailto"] = self.mailto
        payload = self.http.get_json(self.url, params=params)
        meta = payload.get("meta", {})
        return SearchPage(
            records=tuple(self._record(item) for item in payload.get("results", [])),
            next_cursor=meta.get("next_cursor"),
            total=meta.get("count"),
        )

    def _record(self, item: dict[str, Any]) -> PaperRecord:
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        return PaperRecord(
            source=self.source,
            source_id=str(item.get("id", "")).rsplit("/", 1)[-1],
            title=item.get("display_name") or item.get("title") or "Untitled",
            abstract=_abstract_from_inverted(item.get("abstract_inverted_index")),
            doi=item.get("doi"),
            journal=source.get("display_name"),
            issns=tuple(source.get("issn") or ()),
            publication_year=_year(item.get("publication_year")),
            authors=tuple(
                authorship.get("author", {}).get("display_name", "")
                for authorship in item.get("authorships", [])
                if authorship.get("author", {}).get("display_name")
            ),
            publication_types=(item.get("type"),) if item.get("type") else (),
            is_open_access=(item.get("open_access") or {}).get("is_oa"),
            raw=item,
        )


class CrossrefConnector(LiteratureConnector):
    source = SourceName.CROSSREF
    url = "https://api.crossref.org/works"

    def __init__(self, http: HttpClient, *, mailto: str | None = None) -> None:
        self.http = http
        self.mailto = mailto

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        # Crossref 的 cursor 深分页模式会改变相关性排序 (实测: 同一 query.bibliographic
        # 带 cursor=* 时标题精确匹配的论文被挤出前 75, 不带时排第 1). 首次搜索不发 cursor.
        params: dict[str, object] = {
            "query.bibliographic": query,
            "rows": limit,
        }
        if cursor:
            params["cursor"] = cursor
        if self.mailto:
            params["mailto"] = self.mailto
        message = self.http.get_json(self.url, params=params).get("message", {})
        return SearchPage(
            records=tuple(self._record(item) for item in message.get("items", [])),
            next_cursor=message.get("next-cursor"),
            total=message.get("total-results"),
        )

    def _record(self, item: dict[str, Any]) -> PaperRecord:
        dates = item.get("published") or item.get("issued") or {}
        parts = dates.get("date-parts") or []
        return PaperRecord(
            source=self.source,
            source_id=str(item.get("DOI", "")),
            title=(item.get("title") or ["Untitled"])[0],
            abstract=normalize_title_text(item["abstract"]) if item.get("abstract") else None,
            doi=item.get("DOI"),
            journal=(item.get("container-title") or [None])[0],
            issns=tuple(item.get("ISSN") or ()),
            publication_year=_year(parts[0][0] if parts and parts[0] else None),
            authors=tuple(
                " ".join(filter(None, (author.get("given"), author.get("family"))))
                for author in item.get("author", [])
            ),
            publication_types=(item.get("type"),) if item.get("type") else (),
            raw=item,
        )


class PubmedConnector(LiteratureConnector):
    source = SourceName.PUBMED
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(
        self, http: HttpClient, *, tool: str = "paper-hub", email: str | None = None
    ) -> None:
        self.http = http
        self.http.rate_limiter.intervals.setdefault("eutils.ncbi.nlm.nih.gov", 0.34)
        self.tool = tool
        self.email = email

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        start = int(cursor or 0)
        params: dict[str, object] = {
            "db": "pubmed",
            "term": query,
            "retstart": start,
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        result = self.http.get_json(self.search_url, params=params).get("esearchresult", {})
        ids = result.get("idlist", [])
        total = int(result.get("count", 0))
        records: tuple[PaperRecord, ...] = ()
        if ids:
            fetch_params: dict[str, object] = {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
                "tool": self.tool,
            }
            if self.email:
                fetch_params["email"] = self.email
            response = self.http.get_bytes(
                self.fetch_url, params=fetch_params, max_bytes=10_000_000
            )
            root = ET.fromstring(response.content)
            records = tuple(self._record(article) for article in root.findall("PubmedArticle"))
        next_cursor = str(start + len(ids)) if start + len(ids) < total else None
        return SearchPage(records=records, next_cursor=next_cursor, total=total)

    def _record(self, article: ET.Element) -> PaperRecord:
        citation = article.find("MedlineCitation")
        data = citation.find("Article") if citation is not None else None
        pubmed_data = article.find("PubmedData")
        identifiers = {
            node.get("IdType"): _text(node)
            for node in (
                pubmed_data.findall("ArticleIdList/ArticleId") if pubmed_data is not None else []
            )
        }
        journal = data.find("Journal") if data is not None else None
        year = _text(journal.find("JournalIssue/PubDate/Year")) if journal is not None else None
        if not year and journal is not None:
            year = _text(journal.find("JournalIssue/PubDate/MedlineDate"))
        return PaperRecord(
            source=self.source,
            source_id=_text(citation.find("PMID")) if citation is not None else "",
            title=_text(data.find("ArticleTitle")) if data is not None else "Untitled",
            abstract=" ".join(
                filter(None, (_text(node) for node in data.findall("Abstract/AbstractText")))
            )
            if data is not None
            else None,
            doi=identifiers.get("doi"),
            pmid=identifiers.get("pubmed")
            or (_text(citation.find("PMID")) if citation is not None else None),
            pmcid=identifiers.get("pmc"),
            journal=_text(journal.find("Title")) if journal is not None else None,
            issns=tuple(
                filter(
                    None,
                    (
                        _text(journal.find("ISSN")) if journal is not None else None,
                        _text(citation.find("MedlineJournalInfo/ISSNLinking"))
                        if citation is not None
                        else None,
                    ),
                )
            ),
            publication_year=_year(year),
            authors=tuple(
                " ".join(
                    filter(None, (_text(author.find("ForeName")), _text(author.find("LastName"))))
                )
                for author in (data.findall("AuthorList/Author") if data is not None else [])
            ),
            publication_types=tuple(
                filter(
                    None,
                    (
                        _text(node)
                        for node in (
                            data.findall("PublicationTypeList/PublicationType")
                            if data is not None
                            else []
                        )
                    ),
                )
            ),
            keywords=tuple(
                filter(
                    None,
                    (
                        _text(node)
                        for node in (
                            citation.findall("KeywordList/Keyword") if citation is not None else []
                        )
                    ),
                )
            ),
            raw={"pmid": identifiers.get("pubmed")},
        )


def search_connectors(
    connectors: Iterable[LiteratureConnector],
    query: str | Mapping[SourceName, str],
    *,
    limit: int = 25,
    failures: dict[SourceName, str] | None = None,
) -> dict[SourceName, SearchPage]:
    """Search independent source connectors concurrently."""
    connector_list = tuple(connectors)
    with ThreadPoolExecutor(max_workers=len(connector_list) or 1) as pool:
        futures = {
            pool.submit(
                connector.search,
                query.get(connector.source, "") if isinstance(query, Mapping) else query,
                limit=limit,
            ): connector
            for connector in connector_list
        }
        pages: dict[SourceName, SearchPage] = {}
        for future in as_completed(futures):
            connector = futures[future]
            try:
                pages[connector.source] = future.result()
            except (
                httpx.HTTPError,
                ET.ParseError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
            ) as error:
                if failures is not None:
                    failures[connector.source] = type(error).__name__
        return {
            connector.source: pages[connector.source]
            for connector in connector_list
            if connector.source in pages
        }
