import asyncio
import threading
import time

from app.domains.risk_safety.schemas import ClassifyRequest
from app.orchestration import live_data
from app.orchestration import service as orchestration_service
from app.orchestration.websearch import WebSource


async def test_live_data_has_one_total_deadline_and_keeps_completed_sources(monkeypatch):
    cancelled = asyncio.Event()
    source = WebSource(title="Verified", url="https://example.test", snippet="value")

    async def fast(_query):
        await asyncio.sleep(0.005)
        return [source]

    async def slow(_query):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    async def failed(_query):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(live_data, "fetch_fx", fast)
    monkeypatch.setattr(live_data, "fetch_stats", slow)
    monkeypatch.setattr(live_data, "fetch_market_sources", failed)
    monkeypatch.setattr(live_data.settings, "LIVE_DATA_TIMEOUT_SECONDS", 0.03)

    started = time.monotonic()
    result = await live_data.fetch_live_data("query")

    assert result == [source]
    assert time.monotonic() - started < 0.2
    assert cancelled.is_set()


async def test_local_classifier_runs_in_a_worker_thread(monkeypatch):
    event_loop_thread = threading.get_ident()
    worker_thread = None
    sentinel = object()

    def blocking_classifier(*_args):
        nonlocal worker_thread
        worker_thread = threading.get_ident()
        time.sleep(0.03)
        return sentinel

    monkeypatch.setattr(
        orchestration_service.massarius_risk_safety,
        "classify_after_bundle",
        blocking_classifier,
    )
    result = await orchestration_service._classify_after_bundle_nonblocking(
        ClassifyRequest(query="What is accrual accounting?"), None
    )

    assert result is sentinel
    assert worker_thread != event_loop_thread
