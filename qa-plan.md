# QA Plan

| ID | Environment | Preconditions | Test data | Actions | Expected observable result | Cleanup |
|---|---|---|---|---|---|---|
| QA-001 | Python 3.11+, local test runner | Dependencies installed | Mock responses for six sources | Run unit/integration suite | All deterministic tests pass; no network required | Remove test cache |
| QA-002 | Local `127.0.0.1` app | SQLite database initialized | Keyword `nutrition`, years `2020-2025` | Submit search with two sources and OA-only | Results are deduplicated and show source, DOI, year, and OA state | Delete temporary DB |
| QA-003 | Local `127.0.0.1` app | A result has an approved-open PDF/XML candidate | Small valid PDF/XML fixture | Open detail and select download | Response is returned only after magic-byte validation and is cached | Delete cached object |
| QA-004 | Local `127.0.0.1` app | A result has metadata but no open asset | DOI-only fixture | Open detail | Abstract/metadata and legal external link are shown; no bypass URL is offered | Delete temporary DB |
| QA-005 | Local `127.0.0.1` app | SQLite writable | One result | Toggle favorite, download once, reload | Favorite and downloaded list survive reload | Delete temporary DB |

Traceability: `acceptance.feature` scenarios map to QA-002 through QA-005; QA-001 covers the shared connector seam and deterministic checks.
