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

## 2026-09-05 · Issue #28 (PDF-preferred downloads, format badges, search-state restore)

| Case | Result | Evidence |
|---|---|---|
| QA-001 | pass | 61/61 tests (pytest), ruff check + format clean, commit 6e2fbfa |
| QA-012 | pass (live) | `doi:10.5213/inj.2652134.067` (Europe PMC native JATS XML + Unpaywall PDF `https://www.einj.org/upload/pdf/inj-2652134-067.pdf`): download returns HTTP 200, 1,531,859 bytes, `application/pdf`, `%PDF-1.4` magic — PDF won over native XML. Environment: production service `paper-hub.ranlei.work` (port 11422), commit 6e2fbfa, 2026-09-05 |
| QA-013 | pass (live) | `doi:10.2196/58454` (native XML; Unpaywall `url_for_pdf` `https://ai.jmir.org/2025/1/e58454/PDF` actually serves 202/text/html — no real PDF): download falls back to validated JATS XML (HTTP 200, `application/xml`), proving the XML fallback path and that a broken Unpaywall PDF URL does not break downloads. Same environment as above |
| QA-014 | partial (automated) | Homepage serves `formatBadge`/`saveState`/`restoreState` + sessionStorage logic (asserted in tests and present in served HTML); full browser click-through pending user acceptance on the live site |
| QA-015 | covered by silent try/catch design | storage failures degrade silently (code path wrapped; behavior asserted by design, browser-private-mode click-through pending user acceptance |

Notes: Unpaywall `url_for_pdf` reliability observed in the wild: of 9 sampled OA DOIs, 4 had no PDF URL, 2 served non-PDF content (202 HTML) — the PDF-then-XML candidate loop handles both cases without user-visible failure.
