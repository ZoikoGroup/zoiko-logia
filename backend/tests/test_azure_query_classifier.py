import json

import httpx
import pytest

from app.core.config import get_settings
from app.orchestration.azure_query_classifier import AzureQueryClassifier
from app.orchestration import retrieve


def _configure(monkeypatch, *, mode: str = "fallback"):
    settings = get_settings()
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_CLASSIFIER_MODE", mode)
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_ENDPOINT", "https://example.search.windows.net")
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_API_KEY", "test-key")
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_CLASSIFICATION_INDEX", "kriton-query-classifications")
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_SEMANTIC_CONFIGURATION", "kriton-semantic")
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_CLASSIFICATION_MIN_SCORE", 1.5)
    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_CLASSIFICATION_MIN_MARGIN", 0.15)
    return settings


@pytest.mark.asyncio
async def test_azure_classifier_returns_clear_semantic_winner(monkeypatch):
    _configure(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api-key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["queryType"] == "semantic"
        return httpx.Response(200, json={"value": [
            {"classification_id": "audit-evidence", "category": "audit", "@search.rerankerScore": 3.2},
            {"classification_id": "accounting", "category": "accounting-fundamentals", "@search.rerankerScore": 2.1},
        ]})

    candidate = await AzureQueryClassifier(httpx.MockTransport(handler)).classify(
        "Do the evidence obtained support the audit conclusion?",
        allowed_categories={"audit", "accounting-fundamentals"},
    )
    assert candidate is not None
    assert candidate.category == "audit"
    assert candidate.score == 3.2


@pytest.mark.asyncio
async def test_azure_classifier_rejects_ambiguous_results(monkeypatch):
    _configure(monkeypatch)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [
            {"classification_id": "one", "category": "audit", "@search.rerankerScore": 2.4},
            {"classification_id": "two", "category": "accounting-fundamentals", "@search.rerankerScore": 2.3},
        ]})

    candidate = await AzureQueryClassifier(httpx.MockTransport(handler)).classify(
        "Review this balance", allowed_categories={"audit", "accounting-fundamentals"},
    )
    assert candidate is None


@pytest.mark.asyncio
async def test_multiple_examples_for_same_category_are_not_treated_as_conflict(monkeypatch):
    _configure(monkeypatch)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [
            {"classification_id": "audit-one", "category": "audit", "@search.rerankerScore": 3.1},
            {"classification_id": "audit-two", "category": "audit", "@search.rerankerScore": 3.0},
            {"classification_id": "tax-one", "category": "tax", "@search.rerankerScore": 2.2},
        ]})

    candidate = await AzureQueryClassifier(httpx.MockTransport(handler)).classify(
        "Evaluate the audit evidence", allowed_categories={"audit", "tax"},
    )
    assert candidate is not None and candidate.category == "audit"
    assert candidate.runner_up_score == 2.2


@pytest.mark.asyncio
async def test_deterministic_rule_wins_without_calling_azure(monkeypatch):
    _configure(monkeypatch)

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("Azure must not run for explicit deterministic matches")

    monkeypatch.setattr(AzureQueryClassifier, "classify", must_not_run)
    decision = await retrieve.classify_category("Create a bank-reconciliation checklist")
    assert decision.category == "bank-reconciliation"
    assert decision.method == "deterministic_rule"


@pytest.mark.asyncio
async def test_fallback_uses_azure_and_shadow_does_not_change_route(monkeypatch):
    settings = _configure(monkeypatch, mode="fallback")

    async def azure_result(*_args, **_kwargs):
        from app.orchestration.azure_query_classifier import AzureCategoryCandidate
        return AzureCategoryCandidate("audit", 3.0, 1.0, "audit-evidence")

    monkeypatch.setattr(AzureQueryClassifier, "classify", azure_result)
    decision = await retrieve.classify_category("Evaluate whether this evidence is persuasive")
    assert decision.category == "audit"
    assert decision.method == "azure_ai_search"

    monkeypatch.setattr(settings, "AZURE_AI_SEARCH_CLASSIFIER_MODE", "shadow")
    monkeypatch.setattr(retrieve, "_infer_category_semantic", lambda _query: None)
    shadow = await retrieve.classify_category("Evaluate whether this evidence is persuasive")
    assert shadow.category == "standards"
    assert shadow.shadow_category == "audit"
    assert shadow.method == "default_with_azure_shadow"


@pytest.mark.asyncio
async def test_azure_failure_preserves_existing_fallback(monkeypatch):
    _configure(monkeypatch)
    async def unavailable(*_args, **_kwargs):
        return None
    monkeypatch.setattr(AzureQueryClassifier, "classify", unavailable)
    monkeypatch.setattr(retrieve, "_infer_category_semantic", lambda _query: None)
    decision = await retrieve.classify_category("Unrecognized professional wording")
    assert decision.category == "standards"
    assert decision.method == "default"
