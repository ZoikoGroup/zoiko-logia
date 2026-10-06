# Kriton roadmap implementation status

The requested implementation is present in the working tree. Existing uncommitted changes were preserved. No commit or production deployment was made.

| Roadmap area | Implementation |
|---|---|
| Foundation | Explicit Alembic setup/pre-deploy command; read-only application startup; required RLS verification; additional lookup indexes; consistent terminal idempotency; baseline datasets |
| Knowledge ingestion | HTTPS official HTML/PDF loaders, structure-aware sections/questions, versioned passages, rights metadata, finite 384-dimensional embeddings, refresh failure reporting and cron configuration |
| Hybrid retrieval | BM25 plus local semantic search, RRF, bounded authority/freshness/title reranking, procedure/jurisdiction/rights/date filters, historical version selection and document diversification |
| Evidence bundles | Exact selected passage/version IDs, hashes, source URLs, authority and effective/as-of metadata; replay verifies actual content |
| Deterministic tools | Existing calculation engines retained; arithmetic correction/validation retained and final guidance rewrites rechecked; tool evidence uses consistent REF identifiers |
| Claim verification | Dedicated verification stage after rewrites; qualitative and numeric claims; complete per-claim verdicts; exact citation binding; missing/failed verification routes authoritative answers to review; inputs redacted |
| Feedback/review | Server-recorded answers, user/tenant ownership, structured reasons, reviewer evidence display, approve/correct/reject/request evidence, required facts and notes |
| Reviewed gold cases | Tenant-scoped approved/corrected cases with categories/source references; matching evaluation tenant required; legacy unscoped cases block release |
| Evaluation gates | Overall scores, curated source-retrieval/citation expectations, calculation/safety metrics, zero tolerance, regressions, dataset availability and exact-text contamination checks; JSON/Markdown reports |
| CI/CD | Unit/build CI followed by exact-revision staging evaluation and production promotion; runtime configuration identity checked before/after evaluation and after deployment |
| Gradual refactor | Separate ranking, verification and review modules; existing security, retrieval, calculation, model gateway and audit components retained |

No fine-tuning, RLHF or automatic training from raw chats was introduced, as requested by the roadmap.

## Validation

- Backend: **1,873 passed, 13 skipped, 2 expected failures**.
- Frontend: **37 passed**, lint and TypeScript checks passed.
- Next.js production build passed.
- Clean temporary SQLite migration/setup passed; repeated setup passed.
- Git whitespace checks passed.

Tests use isolated databases and stubbed providers. PostgreSQL/pgvector/RLS behavior against the production database and live model accuracy were not exercised here. Historical accuracy figures must not be presented as results of this change. Source-retrieval metrics measure curated source coverage, not exhaustive passage relevance; citation metrics measure expected source attribution, while runtime claim verification checks semantic support.

## External setup still required

Follow [production-readiness.md](production-readiness.md) to enable pgvector through the database administrator, prepare each database, populate the official corpus, assign reviewers, configure separate GitHub/Railway environments and evaluation credentials, disable direct production auto-deploy, and run the live staging gate. India source rights require approval before ingestion. The configured India FAQ is a narrow initial corpus; broader jurisdictions and notifications require further source onboarding.

The requested gradual refactor is implemented incrementally; `ask_kriton` remains a substantial coordinator. Model claim verification cannot guarantee answer completeness, exact-text scanning cannot detect every paraphrase, and configuration hashing does not compare staging and production corpus contents.
