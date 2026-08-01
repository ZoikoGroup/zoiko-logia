import asyncio
from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import update

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domains.live_sources.models import LiveSourceProvider
from app.domains.live_sources.service import fetch_live_data
from app.domains.live_sources.sanctions_service import refresh_snapshot

settings = get_settings()
celery_app = Celery("kriton_jobs", broker=settings.CELERY_BROKER_URL or "redis://localhost:6379/0")

# Without a beat schedule these tasks were defined but never invoked by
# anything — the sanctions snapshots in particular are a hard prerequisite
# for every screening query (sanctions_service.get_snapshot() fails closed
# on a missing/stale file), so "the task exists" was not the same as "the
# feature works". Cadences are set against each feed's own publication
# rhythm and SANCTIONS_SNAPSHOT_TTL_SECONDS, not an arbitrary interval.
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    # Official sanctions lists are amended on no fixed public timetable, so
    # this runs more often than any list actually changes. Each refresh is
    # content-hashed, so a no-op day costs one download, not a re-index.
    # 02:10/14:10 UTC deliberately avoids the top of the hour, where these
    # government hosts are measurably slower.
    "sync-sanctions-snapshots": {
        "task": "app.jobs.live_sources_tasks.sync_sanctions_snapshots",
        "schedule": crontab(hour="2,14", minute="10"),
    },
    # Macro indicators publish quarterly-to-annually; this only pre-warms
    # the request-path cache so the first user of the day doesn't pay the
    # upstream latency.
    "sync-macro-economic-indicators": {
        "task": "app.jobs.live_sources_tasks.sync_macro_economic_indicators",
        "schedule": crontab(hour="5", minute="0"),
    },
    # ECB publishes reference rates once each working day at ~16:00 CET.
    "sync-fx-rates": {
        "task": "app.jobs.live_sources_tasks.sync_fx_rates",
        "schedule": crontab(hour="16", minute="30", day_of_week="mon-fri"),
    },
}

async def _sync_indicator(query: str, jurisdiction: str):
    async with AsyncSessionLocal() as db:
        # fetch_live_data detects intent, performs fetch if cache is empty/expired,
        # and automatically updates the LiveFetchCache DB table.
        outcome = await fetch_live_data(
            db, query=query, tenant_id="GLOBAL_CONTROL", jurisdiction=jurisdiction
        )
        return outcome

@celery_app.task
def sync_macro_economic_indicators():
    """Sync primary macroeconomic indicators for US, UK, India, and World."""
    targets = [
        # (query, jurisdiction)
        ("What is the GDP growth?", ""),
        ("What is the inflation rate?", ""),
        ("What is the unemployment rate?", ""),
        ("What is the GDP growth in the UK?", "UK"),
        ("What is the inflation rate in the UK?", "UK"),
        ("What is the unemployment rate in the UK?", "UK"),
        ("What is the Bank Rate?", "UK"),
        ("What is the Fed Funds Rate?", "US"),
        ("What is the Treasury Yield?", "US"),
        ("What is the GDP growth in the US?", "US"),
        ("What is the inflation rate in the US?", "US"),
        ("What is the unemployment rate in the US?", "US"),
        ("What is the GDP growth in India?", "India"),
        ("What is the inflation rate in India?", "India"),
        ("What is the unemployment rate in India?", "India"),
    ]
    for query, jur in targets:
        try:
            # Run the async fetch synchronously within the Celery worker thread
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If Celery runs in an active loop event model (e.g. eventlet)
                coro = _sync_indicator(query, jur)
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.result()
            else:
                asyncio.run(_sync_indicator(query, jur))
            print(f"[Celery Sync] Cached live indicator: '{query}' ({jur})")
        except Exception as e:
            print(f"[Celery Sync] Failed to cache '{query}' ({jur}): {e}")

@celery_app.task
def sync_fx_rates():
    """Sync primary ECB foreign exchange currency pairs."""
    pairs = [
        "USD to GBP exchange rate",
        "EUR to USD exchange rate",
        "USD to INR exchange rate",
        "EUR to GBP exchange rate",
    ]
    for query in pairs:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                coro = _sync_indicator(query, "")
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.result()
            else:
                asyncio.run(_sync_indicator(query, ""))
            print(f"[Celery Sync] Cached FX pair: '{query}'")
        except Exception as e:
            print(f"[Celery Sync] Failed to cache FX pair '{query}': {e}")


@celery_app.task
def sync_sanctions_snapshots():
    """Warm hash-addressed official sanctions snapshots outside user requests."""
    results = asyncio.run(_sync_all_sanctions_snapshots())
    for provider, outcome in results.items():
        print(f"[Celery Sync] Sanctions snapshot {provider}: {outcome}")
    # A partial failure is normal and must not lose the providers that did
    # sync — but a total failure means every screening query will fail
    # closed until the next tick, which the task result has to surface
    # rather than reporting success with four error dicts inside it.
    if results and all(item["status"] == "failed" for item in results.values()):
        raise RuntimeError(f"every sanctions feed failed to sync: {results}")
    return results


async def _record_sync_provenance(provider_key: str, content_sha256: str) -> None:
    """Write last_successful_sync/last_content_hash onto the registry row.

    The catalogue requires both as source metadata, and without them nothing
    can answer "when was this list last actually refreshed" except by
    stat-ing a file on the worker's disk — which the API container cannot
    see and an auditor certainly cannot.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(LiveSourceProvider)
            .where(LiveSourceProvider.provider_key == provider_key)
            .values(last_successful_sync=datetime.now(timezone.utc), last_content_hash=content_sha256)
        )
        await db.commit()


async def _sync_all_sanctions_snapshots():
    results = {}
    for provider in ("ofac", "un_sanctions", "uk_sanctions", "eu_sanctions"):
        try:
            snapshot = await refresh_snapshot(provider)
            results[provider] = {"status": "live", "records": len(snapshot.entries),
                                 "sha256": snapshot.content_sha256}
            try:
                await _record_sync_provenance(provider, snapshot.content_sha256)
            except Exception as exc:
                # A snapshot that downloaded and parsed is usable whether or
                # not the registry row could be stamped; losing the whole
                # sync over a bookkeeping write would be the wrong trade.
                results[provider]["provenance_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        except Exception as exc:
            results[provider] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return results
