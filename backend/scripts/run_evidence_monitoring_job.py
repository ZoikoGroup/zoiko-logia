"""V8.5 — scheduled evidence-monitoring job.

This is the "command" half of requirement 2 (operational endpoint OR
command for scheduled monitoring), and the thing an external daily
scheduler actually invokes (requirement 3). It is deliberately a
short-lived script, not a long-running process: it iterates every tenant,
runs evidence monitoring once per tenant, closes its own database
connections, and exits — there is no loop, no sleep, no in-process
scheduler here or anywhere else in the web API (requirement 4).

Intended deployment: a second Railway service in this same project,
pointed at this repo/Dockerfile, with:
  - Start Command: python scripts/run_evidence_monitoring_job.py
  - Cron Schedule: e.g. "0 6 * * *" (daily at 06:00 UTC — keep in sync with
    EVIDENCE_MONITORING_SCHEDULE_HOUR_UTC/MINUTE_UTC in Settings, which only
    drives the admin panel's "next scheduled run" display, not the trigger
    itself)
Railway automatically skips a new cron invocation while the previous one is
still marked Active, so a slow run can never overlap itself at the infra
level — the application-level (tenant_id, monitoring_period) idempotency
check in run_evidence_monitoring is a second, independent guarantee that
holds even off Railway.

This script authenticates to nothing over HTTP — it runs inside the
trusted deployment environment with the same DATABASE_URL the web service
uses, which is the "service role" this operation is restricted to (no
human Supabase session/JWT is involved anywhere in this path). The
service-role-protected HTTP endpoint
(POST .../evidence-monitoring/scheduled-run) exists as an equivalent
alternative trigger for schedulers that can only speak HTTP; this script
does not call it and does not need to.

Never retries validation/authorization/schema failures — only a failure
classified as transient_infra_error is retried, and only a bounded number
of times with a short backoff, per tenant.
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
from app.orchestration import evidence_monitoring as monitoring

_logger = logging.getLogger("evidence_monitoring_job")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_MAX_TRANSIENT_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 5


async def _run_for_tenant(tenant_id: str) -> monitoring.MonitoringRunResult | None:
    attempt = 0
    while True:
        attempt += 1
        async with AsyncSessionLocal() as db:
            try:
                result = await monitoring.run_evidence_monitoring(
                    db, tenant_id, trigger_source="scheduled", triggered_by="scheduled:railway-cron",
                )
            except monitoring.MonitoringRunAlreadyActiveError:
                # A manual run is already in flight for this tenant today —
                # not a failure of THIS job; skip and let today's run stand.
                _logger.info("evidence_monitoring_skip_active tenant_id=%s", tenant_id)
                return None

        # Outcome fields only — never a raw exception message, query, chart
        # value, or any other content (requirement 6).
        _logger.info(
            "evidence_monitoring_run_outcome tenant_id=%s status=%s evidence_version=%s "
            "valid_event_count=%s draft_created=%s alert_created=%s failure_category=%s attempt=%s",
            result.tenant_id, result.status, result.evidence_version, result.valid_event_count,
            result.draft_created, result.alert_created, result.failure_category, attempt,
        )

        if result.status != "failed":
            return result
        if not monitoring.is_transient_failure_category(result.failure_category) or attempt > _MAX_TRANSIENT_RETRIES:
            return result

        _logger.info(
            "evidence_monitoring_retry tenant_id=%s attempt=%s backoff_seconds=%s",
            tenant_id, attempt, _RETRY_BACKOFF_SECONDS,
        )
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)


async def main() -> int:
    async with AsyncSessionLocal() as db:
        tenant_ids = [row[0] for row in (await db.execute(select(Tenant.id))).all()]

    _logger.info("evidence_monitoring_job_start tenant_count=%s", len(tenant_ids))
    failures = 0
    for tenant_id in tenant_ids:
        result = await _run_for_tenant(tenant_id)
        if result is not None and result.status == "failed":
            failures += 1

    _logger.info("evidence_monitoring_job_complete tenant_count=%s failed_count=%s", len(tenant_ids), failures)
    await async_engine.dispose()
    # A per-tenant failure is expected/handled (recorded, safe-categorized,
    # retried if transient) and must not fail the whole cron execution —
    # only a genuinely catastrophic error (can't even list tenants) should.
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
