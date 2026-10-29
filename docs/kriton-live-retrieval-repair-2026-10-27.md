# Live retrieval repair and runtime verification — 27 October 2026

## Running application

The frontend uses `http://127.0.0.1:8010/api/v1`. The local Uvicorn server
runs this workspace with automatic reload. Its final `/health/version`
source hash matches the workspace and `/health/ready` returned HTTP 200.
No Railway deployment or manual server restart was necessary.

[Runtime identity and readiness](kriton-runtime-verification-final-2026-10-27.json)

## Additional root causes found in live checks

- Backup search was operational, but the relevance filter accepted generic
  “audit”/“compliance” matches unrelated to the technical subject. Core
  subject matching and source-framework matching now reject those pages.
- Conceptual questions received the same numeric-table scoring bonus as
  questions requesting figures. On the transfer-pricing guidelines this
  selected financial tables instead of the losses section. Numeric bonuses
  now apply only when the search asks for figures.
- Publication catalogue snippets were being used without reading their
  documents. Explicit same-publisher PDF downloads are followed; a small
  document catalogue can resolve a publisher-verified public download when
  its catalogue page is blocked. The catalogue maps publication identities,
  not question text or predetermined answers. The OECD 2022 guidelines entry
  was verified against the publication's own Download PDF link.
- Long PDFs exceeded the pure-Python reader's useful time budget. PDF text
  now comes from an isolated, bounded PDFium subprocess. This avoids sharing
  PDFium's native state across concurrent search/OCR threads and retains page
  locators. Declared PDF dependencies missing from the local environments
  were installed; `fonttools` was added to requirements.
- Extracted claim searches could still lose their single shared technical
  context after semantic planning. That context is retained in primary and
  alternative search phrases.
- A publisher's website can host academic submissions and discussion drafts.
  Those document types are excluded as governing evidence unless the question
  specifically asks about proposals or consultation material. Different
  passages from the same cited publication are retained together.
- Search-cache generations were advanced so old snippets and wrongly selected
  sources do not persist through the retrieval-policy changes. Unrelated Redis
  data was not cleared.

## Verification

- Final backend suite: **4,877 passed, 75 skipped, 22 expected failures**.
- `git diff --check`: passed.
- Direct public OECD PDF extraction: 2,994 characters including page locators
  in 0.8 seconds in a measured check.
- The three supplied claims were checked live through extraction, contextual
  search, public-document reading and model verification. The final check
  completed in 25.76 seconds: **one confirmed, one contradicted, one unverified**.
  Both substantive verdicts cited the official OECD guidelines; the academic
  consultation submission was not used as governing evidence.

[Final live claim-review result](kriton-live-claim-review-final-2026-10-27.json)

The live check called the same backend review functions using public test
text; it did not create user questions or audit records in the application
database. Routing, persistence boundaries and final response checks are
covered by the orchestration tests. Existing stored answers were not rewritten.

## Remaining limitation

The configured Tavily account still returned HTTP 432 (usage limit exhausted).
Some OECD catalogue HTML pages returned HTTP 403, while their verified public
PDF downloads were accessible. Backup search and direct publication reading
now supply useful evidence for the tested claims, but broader live coverage
still depends on search capacity and available authoritative content. No
account spending limit or API credential was changed. The royalty claim
remained unverified in the final check; no successful result is claimed for it.
