import asyncio
from celery import Celery
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domains.live_sources.service import fetch_live_data

settings = get_settings()
celery_app = Celery("kriton_jobs", broker=settings.CELERY_BROKER_URL or "redis://localhost:6379/0")

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
