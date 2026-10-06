# Governed knowledge and answer verification

Official guidance is ingested as immutable source versions with section locators, heading paths, procedure tags, rights records and local 384-dimensional embeddings. Changed content creates a new approved version and supersedes the previous version. Empty documents, invalid embeddings and failed downloads fail the refresh job.

Retrieval applies tenant visibility, operation-specific rights, jurisdiction, effective date and procedure filters before ranking. It combines BM25 and semantic ranks using reciprocal-rank fusion, then applies bounded authority, freshness and title relevance adjustments and document diversification. Exact lexical matches can qualify even when semantic similarity falls below the configured threshold. Saved bundles record the selected versions, passage hashes and as-of date; replay checks actual content hashes. Historical queries can use a superseded version when it was applicable on the requested date. Publication dates are version metadata; legal effective dates still require correct source metadata and interpretation.

The default embedding model is `BAAI/bge-small-en-v1.5`, baked into the backend image. `EMBEDDING_PROVIDER=none` selects lexical retrieval. Changing the model requires compatible dimensions and re-ingestion.

## Answer release

The preliminary specific-claim check can request a correction. After all rewrites, the final gate checks qualitative assertions as well as numeric claims against the exact cited REF identifiers. Every claim needs a complete supported verdict bound to its citation. The verifier checks jurisdiction, dates and the purpose of a rule. Missing evidence, disabled verification, unavailable providers, malformed verdicts, unsupported claims or an exceeded verification budget route authoritative model answers to human review. `FORCE_DIRECT_ANSWER` does not bypass this gate. Deterministic self-contained calculations and generated visual summaries use their own validation; arithmetic is rechecked after guidance rewrites.

Verifier questions, claims and evidence are redacted before external transmission. The verifier is a model judge: supported claims do not prove that every necessary rule has been included. Held-out tests and reviewer corrections remain necessary.

## Review and gold cases

Feedback refers to a server-recorded answer owned by the authenticated user and tenant. A negative rating opens a review case. Reviewers can inspect the draft, exact governed evidence and recorded external snippets. Current display rights are checked before governed text is returned; changed hashes or revoked rights withhold the text. Uploaded private document snippets are excluded from the external snapshot.

Review decisions are approve, correct, reject and request evidence. Approval/correction requires key facts present in the approved answer and creates a tenant-scoped gold case with category and source references. Request evidence keeps the case actionable. Raw conversations and unreviewed feedback are not training inputs. Gold evaluation requires the matching evaluation account and tenant. Legacy unscoped gold cases block the gate until assigned and validated.

## Local commands

Run from `backend`, with the intended database environment:

```bash
.venv/bin/python scripts/setup_database.py
.venv/bin/python scripts/ingest_govuk.py --dry-run
.venv/bin/python scripts/ingest_govuk.py
# Only after the India source rights have been approved:
GST_INGESTION_RIGHTS_APPROVED=true .venv/bin/python scripts/ingest_official.py
.venv/bin/python scripts/release_gate.py
```

Official PDF fetching verifies TLS. A trusted `OFFICIAL_DOCUMENT_CA_BUNDLE` can supply missing certificate authorities. The India corpus currently contains the configured GST Council FAQ; this does not constitute complete consolidated GST notifications. New documents require explicit source configuration and relevant evaluation cases.

## Evaluation and promotion

The release gate runs general regression, UK VAT tuning/holdout, India GST and reviewed gold cases. It reports and gates curated expected-source retrieval, citation attribution, calculation accuracy and safety separately. It blocks minimum-score failures, zero-tolerance safety failures, regressions, unavailable evaluations and exact gold-text contamination in runtime Python code. Empty mandatory sets fail; an empty reviewed gold set is allowed before the first approved review. Baseline updates require a complete passing run.

The automated promotion workflow deploys the CI-tested revision to staging, checks its reported revision and runtime configuration hash before and after evaluation, then deploys that revision to production and verifies identity. Provider secrets are excluded from the hash. The hash does not prove that staging and production databases contain identical source corpora. Exact-text contamination scanning cannot detect all paraphrases or provider training contamination.

Reports from older implementations are not evidence of accuracy for this implementation. Run the live gate after configuring accounts, source data and environments. See [production setup](production-readiness.md).
