# Production setup

The local implementation is complete and regression-tested. Production rollout and live accuracy evaluation have not been performed by this change.

## Database and knowledge setup

1. Have the database administrator enable pgvector on PostgreSQL. The setup script requires it to be installed and does not install extensions.
2. Run `python scripts/setup_database.py` from `backend` with the target database configuration. `backend/railway.json` runs this as its pre-deploy command. It applies Alembic migrations, compatibility setup, seeds, indexes and forced tenant RLS policies, then records the schema fingerprint. Application startup only checks the prepared schema and policies. `FORCE_STARTUP_SETUP` is deprecated and ignored.
3. A database stamped with an earlier version of revision `p5i6j7k8l9m0` (missing `query_answer_records`, tenant/category columns, indexes or RLS policies, so startup refuses it) is repaired by `q6j7k8l9m0n1` through the same setup command; that revision also moves legacy unscoped gold cases to their tenant when one resolved review case identifies it. The shared Supabase database was repaired this way on 2026-10-04.
4. An existing database without an Alembic revision is rejected. Audit and back it up before explicitly using `--adopt-existing` once. Do not use this option for normal deployments.
5. Populate staging and production source corpora with `scripts/ingest_govuk.py`. Run `scripts/ingest_official.py` only after source rights approval, with `GST_INGESTION_RIGHTS_APPROVED=true`. No production rights approval or ingestion was performed here.
6. Provision a refresh service with `backend/railway.refresh.json`: `python scripts/refresh_knowledge.py`, daily schedule `0 3 * * *`, no automatic restart. Supply the intended database variables and an existing ingestion user. India refresh is included only when its rights approval variable is true. TLS verification remains enabled.

## Automated release configuration

`.github/workflows/promote.yml` follows successful main-branch push CI. It deploys staging, runs the live gate, then promotes the same revision and checks the production revision/configuration hash.

Configure separate GitHub `staging` and `production` environments:

| Configuration | Staging | Production |
|---|---|---|
| Variables | `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID` | Same names, scoped to production |
| Railway credential | Environment-scoped `RAILWAY_TOKEN` | Environment-scoped `RAILWAY_TOKEN` |
| API endpoint secret | `BASELINE_API_URL` | `PRODUCTION_API_URL` |
| Evaluation secrets | `DATABASE_URL`, `EVAL_EMAIL`, `EVAL_PASSWORD`, `EVAL_TENANT_ID`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Not required by the identity smoke check |

Disable direct production GitHub auto-deploy so it cannot bypass the gate. The workflow uploads `backend` with `--path-as-root`; configure the Railway service root as `/` and use the uploaded Dockerfile/railway.json. Staging and production must have equivalent model/verification settings and compatible knowledge corpora. `/health/version` exposes the packaged candidate revision and a runtime configuration hash. Environment approval requirements, if desired, belong in GitHub environment settings.

Set backend `CLAIM_VERIFICATION=on`, `EMBEDDING_PROVIDER=local`, the supported embedding model, and the configured answer/verifier provider credentials. A missing verifier credential causes authoritative answers to require review. A staging evaluation account must exist in the selected Supabase project and belong to `EVAL_TENANT_ID`. Never use a production user's password as an evaluation fixture.

The optional manual CI gate uses the corresponding repository secrets. The automated path uses environment-scoped secrets. Gate reports include the tested revision, configuration hash, contamination results and per-set verdicts. A live passing report is required before claiming production accuracy.

## Reviewer operations and limits

Admin, Governance Ops Lead and Risk Admin can resolve review cases; System Auditor can read them. Assign an actual reviewer and process the queue. Approve/correct requires explicit key facts, which become tenant-private gold checks. Rejection and requests for more evidence require a note. Legacy gold data without tenant ownership requires reviewer validation before evaluation.

The final verifier reduces unsupported answers but cannot guarantee completeness or correctness. Retrieval and thresholds need validation on representative cases. Source publication/effective metadata must be curated accurately. Daily refresh cannot eliminate changes between refreshes. Consolidated India GST notifications beyond the configured FAQ require further source onboarding; trusted certificates and approved rights alone do not add documents automatically.

The orchestration refactor is incremental: ranking and final verification now have dedicated modules, while `ask_kriton` still coordinates the existing pipeline. No fine-tuning, reinforcement learning or training on raw conversations was added.
