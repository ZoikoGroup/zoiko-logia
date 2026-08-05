"""V10 — scheduled visualization-personalization profile recomputation.

Same shape and rationale as scripts/run_evidence_monitoring_job.py (V8.5):
a short-lived script, not a long-running process — iterates every tenant,
recomputes personalization profiles once per tenant, closes its own
database connections, and exits. There is no in-process scheduler loop
here or anywhere else in the web API.

Intended deployment: a third Railway service in the same project (alongside
`backend` and `evidence-monitoring-cron`), pointed at this repo/Dockerfile:
  - Start Command: python scripts/recompute_personalization_profiles.py
  - Cron Schedule: daily, e.g. "0 7 * * *" (after evidence monitoring's
    06:00 UTC run, to keep the two jobs from contending for the same
    Postgres connections at the exact same minute)

This script authenticates to nothing over HTTP — it runs inside the
trusted deployment environment with the same DATABASE_URL the web service
uses. The service-role-protected HTTP endpoint
(POST .../visualization-personalization/scheduled-recompute) exists as an
equivalent alternative trigger for schedulers that can only speak HTTP;
this script does not call it and does not need to.

Only retries a transient_infra_error failure, and only a bounded number of
times with a short backoff, per tenant — never a validation/authorization/
schema failure.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, async_engine
from app.domains.identity.models import Tenant
from app.orchestration import visualization_personalization as personalization

_logger = logging.getLogger("visualization_personalization_job")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_MAX_TRANSIENT_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 5


async def _run_for_tenant(tenant_id: str) -> personalization.RecomputationRunResult | None:
    attempt = 0
    while True:
        attempt += 1
        async with AsyncSessionLocal() as db:
            try:
                result = await personalization.recompute_tenant_profiles(
                    db, tenant_id, triggered_by="scheduled:railway-cron",
                )
            except personalization.MonitoringRunAlreadyActiveError:
                _logger.info("personalization_recompute_skip_active tenant_id=%s", tenant_id)
                return None

        # Outcome fields only — never a raw exception message, query, chart
        # value, or any other content.
        _logger.info(
            "personalization_recompute_outcome tenant_id=%s status=%s profiles_recomputed_count=%s "
            "event_count=%s failure_category=%s attempt=%s",
            result.tenant_id, result.status, result.profiles_recomputed_count,
            result.event_count, result.failure_category, attempt,
        )

        if result.status != "failed":
            return result
        if not personalization.is_transient_failure_category(result.failure_category) or attempt > _MAX_TRANSIENT_RETRIES:
            return result

        _logger.info(
            "personalization_recompute_retry tenant_id=%s attempt=%s backoff_seconds=%s",
            tenant_id, attempt, _RETRY_BACKOFF_SECONDS,
        )
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)


async def main() -> int:
    async with AsyncSessionLocal() as db:
        tenant_ids = [row[0] for row in (await db.execute(select(Tenant.id))).all()]

    _logger.info("personalization_recompute_job_start tenant_count=%s", len(tenant_ids))
    failures = 0
    for tenant_id in tenant_ids:
        result = await _run_for_tenant(tenant_id)
        if result is not None and result.status == "failed":
            failures += 1

    _logger.info("personalization_recompute_job_complete tenant_count=%s failed_count=%s", len(tenant_ids), failures)
    await async_engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
