"""
Tests for the semantic query-understanding layer (query_intent.py,
query_classifier_llm.py, query_classifier.py).

Groq is mocked throughout — no network/API key needed to run this file. A
few tests exercise a REAL Groq call only when GROQ_API_KEY is actually
configured (skipped otherwise), as a live smoke check that the strict
JSON-schema mode this module relies on hasn't silently broken.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration.query_intent import QueryIntent, QueryEntity
from app.orchestration.query_classifier_llm import (
    _to_strict_schema, classify_query_llm,
)
from app.orchestration.query_classifier import (
    classify_query, _fallback_classify, _apply_deterministic_overrides,
)


# ── Schema ───────────────────────────────────────────────────────────────

def test_query_intent_default_construction():
    qi = QueryIntent()
    assert qi.domain == "GENERAL"
    assert qi.intent is None
    assert qi.wants_visualization is False
    assert qi.source == "fallback"


def test_query_intent_rejects_unknown_intent_label():
    with pytest.raises(Exception):
        QueryIntent(intent="MADE_UP_INTENT")


def test_strict_schema_marks_every_object_no_additional_properties():
    schema = _to_strict_schema(QueryIntent.model_json_schema())
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())
    # Nested $defs (QueryEntity, TimeContext) must be strict too.
    for name, definition in schema.get("$defs", {}).items():
        if definition.get("type") == "object" and "properties" in definition:
            assert definition["additionalProperties"] is False, name
            assert set(definition["required"]) == set(definition["properties"].keys()), name


# ── Fallback classifier (no LLM) ────────────────────────────────────────

def test_fallback_classify_resolves_trend_and_country():
    result = _fallback_classify("Show UK inflation as a horizontal bar chart.")
    assert result.source == "fallback"
    assert result.intent == "TREND"
    assert "United Kingdom" in result.jurisdictions
    assert result.wants_visualization is True
    assert result.explicitly_requested_chart_words == "HORIZONTAL_BAR"


def test_fallback_classify_plain_definitional_question_has_no_intent():
    result = _fallback_classify("What is a deferred tax liability?")
    assert result.intent is None
    assert result.wants_visualization is False


def test_fallback_classify_relationship_graph():
    result = _fallback_classify(
        "Show this as a network: Auditor reviews Company; Company controls Subsidiary."
    )
    assert result.intent == "RELATIONSHIP"


# ── classify_query_llm() — mocked Groq ──────────────────────────────────

def _mock_groq_response(content: str):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_classify_query_llm_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = await classify_query_llm("Show UK inflation as a line chart.")
    assert result is None


@pytest.mark.asyncio
async def test_classify_query_llm_parses_valid_structured_response(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    valid_json = QueryIntent(
        domain="TAX", intent="TREND", jurisdictions=["United Kingdom"],
        entities=[QueryEntity(name="United Kingdom", type="country")],
        wants_visualization=True, confidence=0.9,
    ).model_dump_json()

    mock_create = AsyncMock(return_value=_mock_groq_response(valid_json))
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create
    monkeypatch.setattr(
        "app.orchestration.query_classifier_llm.AsyncGroq",
        lambda api_key: mock_client,
    )

    result = await classify_query_llm("Has UK tax gone up since 2020?")
    assert result is not None
    assert result.domain == "TAX"
    assert result.intent == "TREND"
    assert result.source == "llm"  # set by classify_query_llm, not the mocked content
    mock_create.assert_called_once()
    # Strict structured-output mode must actually be requested.
    _, kwargs = mock_create.call_args
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_classify_query_llm_fails_soft_on_malformed_json(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_groq_response("{not valid json")
    )
    monkeypatch.setattr(
        "app.orchestration.query_classifier_llm.AsyncGroq",
        lambda api_key: mock_client,
    )
    result = await classify_query_llm("Show UK inflation as a line chart.")
    assert result is None


@pytest.mark.asyncio
async def test_classify_query_llm_fails_soft_on_network_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=ConnectionError("boom"))
    monkeypatch.setattr(
        "app.orchestration.query_classifier_llm.AsyncGroq",
        lambda api_key: mock_client,
    )
    result = await classify_query_llm("Show UK inflation as a line chart.")
    assert result is None


# ── classify_query() — resilience + overrides ───────────────────────────

@pytest.mark.asyncio
async def test_classify_query_falls_back_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.orchestration.query_classifier.classify_query_llm",
        AsyncMock(return_value=None),
    )
    result = await classify_query("Show UK inflation as a horizontal bar chart.")
    assert result.source == "fallback"
    assert result.intent == "TREND"


@pytest.mark.asyncio
async def test_classify_query_uses_llm_result_when_available(monkeypatch):
    llm_result = QueryIntent(domain="TAX", intent="TREND", source="llm")
    monkeypatch.setattr(
        "app.orchestration.query_classifier.classify_query_llm",
        AsyncMock(return_value=llm_result),
    )
    result = await classify_query("Has UK tax gone up since 2020?")
    assert result.source == "llm"
    assert result.domain == "TAX"


def test_deterministic_override_forces_visualization_for_named_chart():
    """An explicit chart-type word in the query must win even if the LLM
    (or a fallback response, for unrelated reasons) said no visual needed."""
    intent = QueryIntent(wants_visualization=False)
    result = _apply_deterministic_overrides(
        "Show UK inflation as a horizontal bar chart.", intent,
    )
    assert result.wants_visualization is True
    assert result.explicitly_requested_chart_words == "HORIZONTAL_BAR"


def test_deterministic_override_leaves_llm_result_alone_when_no_explicit_chart():
    intent = QueryIntent(wants_visualization=True, source="llm")
    result = _apply_deterministic_overrides("What is a deferred tax liability?", intent)
    # No explicit chart word in the query — override must not clear a
    # semantically-correct wants_visualization the LLM already set.
    assert result.wants_visualization is True


# ── Live smoke test (only runs with a real key) ─────────────────────────

@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY") or os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="set RUN_LIVE_LLM_TESTS=1 with GROQ_API_KEY to run live model tests",
)
@pytest.mark.asyncio
async def test_live_classify_query_llm_handles_paraphrase_with_no_keywords():
    """The whole point of the semantic layer over regex: a paraphrase with
    none of the obvious trigger words must still classify correctly."""
    result = await classify_query_llm(
        "Has the burden on UK companies become heavier or lighter since 2020?"
    )
    assert result is not None
    assert result.domain in {"TAX", "FINANCE", "GENERAL"}
    assert "United Kingdom" in result.jurisdictions or any(
        "UK" in j or "United Kingdom" in j for j in result.jurisdictions
    )


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY") or os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="set RUN_LIVE_LLM_TESTS=1 with GROQ_API_KEY to run live model tests",
)
@pytest.mark.asyncio
async def test_live_classify_query_llm_flags_out_of_scope():
    result = await classify_query_llm("What is the weather like in London tomorrow?")
    assert result is not None
    assert result.out_of_scope is True
