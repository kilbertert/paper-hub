# QA Results: Search Relevance (#22)

- Build identity: `76b5691be27a9ad0085f37d393e6dea524b21161` (merged `origin/main`)
- Environment: Python 3.13.13, local Linux user service, `paperhub` wheel build
- Timestamp: 2026-09-02T05:12:19Z
- Deterministic checks: `55 passed`; Ruff check and format check passed; wheel build passed
- Coverage: 95% overall on the changed search path and full package suite
- Provider canary: `deepseek-v4-flash-0731` returned strict JSON with 12 terms and 6 phrases; credentials were read from a private runtime key-file and no key value was recorded
- Local relevance probe: an AI-only medical title was filtered; customer-service title ranked above customer-service abstract match; `match_fields` and `matched_terms` were present
- Online smoke: HTTPS `/` and `/api/search` returned 200 through `paper-hub.ranlei.work`; Crossref `nutrition` returned a relevant result; Crossref `AI客服` returned zero unqualified results rather than broad AI-only matches
- Source resilience: simulated DOAJ/one-source 502 returned available source results with `source_errors`; failed-source responses were not cached

Traceability: `acceptance.feature` relevance scenarios map to QA-006 through QA-009 in `qa-plan.md`; this file records the implementation and verification identity.
