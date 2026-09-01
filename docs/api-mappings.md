# Official API Mappings

The connector contract is `LiteratureConnector.search() -> SearchPage`. Each adapter maps only fields needed by paper-hub's search result and detail views.

| Source | Official interface | Query/paging | Observable mapping |
|---|---|---|---|
| Europe PMC | REST `/search`, JSON `resultType=core` | `query`, `pageSize`, `cursorMark` | `title`, `abstractText`, DOI/PMID/PMCID, `pubYear`, authors, OA JATS candidate |
| DOAJ | API v4 `/search/articles/{query}` | `page`, `pageSize` | `bibjson` title, abstract, DOI, year, authors, journal, publisher full-text link |
| arXiv | Legacy API `/api/query`, Atom 1.0 | `search_query`, `start`, `max_results` | Atom title, summary, DOI, published year, authors, PDF link |
| OpenAlex | Works API `/works` | `search`, `cursor`, `per_page` | display name, reconstructed abstract, DOI, year, authors, OA status |
| Crossref | REST `/works` polite pool | `query.bibliographic`, `cursor`, `rows` | title, JATS abstract text, DOI, issued year, authors, container title |
| PubMed | NCBI ESearch + EFetch | `retstart`, `retmax`, UID fetch | PubMed XML title, abstract, DOI/PMID/PMCID, year, authors, journal |

Compliance mapping: arXiv PDF links are `MANUAL_REVIEW` external links because the arXiv API terms do not grant blanket third-party redistribution rights. Europe PMC exposes an approved-open JATS candidate only when the API reports both a PMCID and open-access status. Metadata-only indexes do not produce proxy-download candidates.
