"""Tests for the classifier observability counters.

The point of these counters is to answer two questions that were previously
unanswerable — is the provider answering, and is the understanding budget
buying anything — so the tests are mostly about keeping the *distinctions*
that make them answerable, rather than about the arithmetic.
"""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.domains.risk_safety.router as safety_router
from app.core.database import get_sync_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.risk_safety import classifier_metrics, llm_classifier
from app.orchestration.query_understanding import understand


@pytest.fixture(autouse=True)
def _clean_counters():
    classifier_metrics.reset()
    llm_classifier.clear_cache()
    yield
    classifier_metrics.reset()


def _payload(**overrides) -> dict:
    base = {
        "risk_level": "MEDIUM", "confidence": 0.91, "resolved_query": "x",
        "intent": "INTERPRETATION", "secondary_intents": [], "advice_signal": False,
        "missing_context": [], "reason_codes": [], "domain": "accounting",
        "retrieval_query": "lease classification under IFRS 16",
        "response_format": "adaptive", "requested_depth": "standard",
        "requires_current_sources": False, "situation_type": "GENERAL",
        "subject_type": "NONE", "actionability": "ANALYTICAL",
        "professional_consequences": [], "harm_intent": "NONE",
        "clarification_question": "", "presentation_hint": "none",
    }
    return {**base, **overrides}


def _fake_openai(monkeypatch, *, content: str | None = None, raises: Exception | None = None,
                 delay: float = 0.0):
    class FakeCompletions:
        def create(self, **kwargs):
            if raises is not None:
                raise raises
            if delay:
                import time as _time
                _time.sleep(delay)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        OpenAI=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))))


# ── The three deterministic paths must stay distinguishable ─────────────


def test_a_query_that_never_reached_the_model_is_not_counted_as_a_failure(monkeypatch):
    """`not_consulted` vs `provider_failed` is the whole point: one is normal
    operation, the other means the provider is down."""
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "off")
    asyncio.run(understand("What is the current UK corporation tax rate?"))
    counts = classifier_metrics.snapshot()["query_understanding"]["counts"]
    assert counts == {"not_consulted": 1}


def test_a_provider_returning_nothing_is_counted_as_a_failure(monkeypatch):
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "primary")
    _fake_openai(monkeypatch, raises=RuntimeError("provider down"))
    asyncio.run(understand("tell me about it"))
    counts = classifier_metrics.snapshot()["query_understanding"]["counts"]
    assert counts == {"provider_failed": 1}


def test_a_budget_expiry_is_counted_separately_from_a_provider_failure(monkeypatch):
    # Timing out means the timeout is too tight, not that the provider is
    # broken — and the request is not wasted, since its result still warms the
    # classifier cache for the post-bundle risk call.
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "primary")
    monkeypatch.setenv("QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "0.1")
    _fake_openai(monkeypatch, content=json.dumps(_payload()), delay=0.5)
    asyncio.run(understand("tell me about it"))
    counts = classifier_metrics.snapshot()["query_understanding"]["counts"]
    assert counts == {"timed_out": 1}


def test_a_successful_remote_result_is_counted_as_applied(monkeypatch):
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "primary")
    monkeypatch.setenv("QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "5")
    _fake_openai(monkeypatch, content=json.dumps(_payload()))
    result = asyncio.run(understand("tell me about it"))
    assert result.source == "semantic_fallback"
    assert classifier_metrics.snapshot()["query_understanding"]["counts"] == {"semantic_applied": 1}


# ── Rates ───────────────────────────────────────────────────────────────


def test_rates_are_none_before_anything_happens():
    """A 0% success rate and "no requests yet" are different states, and
    reporting the first for the second makes a healthy deployment look broken
    in its first minute."""
    snapshot = classifier_metrics.snapshot()
    assert snapshot["classification"]["llm_answer_rate"] is None
    assert snapshot["query_understanding"]["within_budget_rate"] is None


def test_the_answer_rate_counts_only_calls_actually_made():
    # Deterministic and skipped-sensitive outcomes are not attempts, so they
    # must not dilute the rate that tells you whether the provider works.
    classifier_metrics.record_classification("deterministic")
    classifier_metrics.record_classification("llm_skipped_sensitive")
    classifier_metrics.record_classification("llm_applied")
    classifier_metrics.record_classification("llm_unavailable")
    snapshot = classifier_metrics.snapshot()
    assert snapshot["classification"]["llm_answer_rate"] == 0.5
    assert snapshot["classification"]["total"] == 4


def test_the_budget_rate_counts_only_calls_actually_made():
    classifier_metrics.record_understanding("not_consulted")
    classifier_metrics.record_understanding("not_consulted")
    classifier_metrics.record_understanding("semantic_applied")
    classifier_metrics.record_understanding("timed_out")
    classifier_metrics.record_understanding("provider_failed")
    snapshot = classifier_metrics.snapshot()
    assert snapshot["query_understanding"]["within_budget_rate"] == round(1 / 3, 4)


def test_counters_are_thread_safe():
    # Risk classification is dispatched through asyncio.to_thread, so these
    # increments genuinely run off the event loop thread.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: classifier_metrics.record_classification("llm_applied"), range(400)))
    assert classifier_metrics.snapshot()["classification"]["counts"]["llm_applied"] == 400


# ── Endpoint ────────────────────────────────────────────────────────────


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(safety_router.router, prefix="/api/v1")
    app.dependency_overrides[get_sync_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="u1", tenant_id="t1", email="u@example.test", role="analyst")
    return app


def test_the_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(safety_router.router, prefix="/api/v1")
    app.dependency_overrides[get_sync_db] = lambda: object()
    with TestClient(app) as client:
        assert client.get("/api/v1/safety/classifier-metrics").status_code == 401


def test_the_endpoint_reports_the_mode_and_the_counters(monkeypatch):
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "fallback")
    classifier_metrics.record_classification("llm_applied")
    with TestClient(_app()) as client:
        body = client.get("/api/v1/safety/classifier-metrics").json()
    assert body["mode"] == "fallback"
    assert body["classification"]["counts"]["llm_applied"] == 1
    assert body["classification"]["llm_answer_rate"] == 1.0


def test_the_endpoint_flags_when_fallback_is_effectively_primary(monkeypatch):
    """With the local model disabled, "fallback" fires the LLM on every query
    no deterministic pattern already settled. That config interaction is the
    one that surprises people, so it is stated rather than inferred."""
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "fallback")
    monkeypatch.setenv("ENABLE_ML_CLASSIFIER", "false")
    with TestClient(_app()) as client:
        body = client.get("/api/v1/safety/classifier-metrics").json()
    assert body["local_ml_enabled"] is False
    assert body["llm_is_effective_primary"] is True

    monkeypatch.setenv("ENABLE_ML_CLASSIFIER", "true")
    with TestClient(_app()) as client:
        body = client.get("/api/v1/safety/classifier-metrics").json()
    assert body["llm_is_effective_primary"] is False


def test_mode_off_is_never_reported_as_effective_primary(monkeypatch):
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "off")
    monkeypatch.setenv("ENABLE_ML_CLASSIFIER", "false")
    with TestClient(_app()) as client:
        body = client.get("/api/v1/safety/classifier-metrics").json()
    assert body["llm_is_effective_primary"] is False
