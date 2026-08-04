import asyncio

import pytest

from app.domains.risk_safety.llm_classifier import LLMClassification
from app.orchestration import query_understanding as qu


@pytest.mark.parametrize(
    ("query", "intent", "response_format", "current"),
    [
        ("Explain accrual accounting simply.", "explain", "plain_language", False),
        ("Compare IFRS 16 and ASC 842 in a table.", "compare", "table", False),
        ("Calculate the current tax amount step by step.", "calculate", "step_by_step", True),
        ("Summarize the key points briefly.", "summarize", "summary", False),
        ("What is the latest federal funds rate?", "find_current_value", "adaptive", True),
        ("Assess the revenue recognition treatment.", "interpret", "adaptive", False),
        ("Show a decision flowchart for choosing a deduction.", "information", "flowchart", False),
        ("Calculate depreciation and show it as a chart.", "calculate", "chart", False),
    ],
)
def test_fast_understanding_covers_common_query_requirements(
    query,
    intent,
    response_format,
    current,
):
    qu.understand_fast.cache_clear()
    result = qu.understand_fast(query, "")

    assert result.primary_intent == intent
    assert result.response_format == response_format
    assert result.requires_current_sources is current
    assert result.source == "deterministic"


def test_retrieval_rewrite_preserves_numbers_and_adds_trusted_jurisdiction():
    qu.understand_fast.cache_clear()
    result = qu.understand_fast(
        "Hello, could you please explain simply the 2026 deduction for $32,000 income?",
        "US",
    )

    assert "2026" in result.retrieval_query
    assert "32,000" in result.retrieval_query
    assert "Jurisdiction: US" in result.retrieval_query
    assert "simply" not in result.retrieval_query.lower()


def test_personalized_recommendation_is_exposed_as_risk_signal():
    qu.understand_fast.cache_clear()
    result = qu.understand_fast(
        "What should our client claim as a tax deduction?",
        "US",
    )

    assert result.primary_intent == "recommend"
    assert result.personalized is True
    assert "personalized_advice" in result.risk_signals
    assert "recommendation" in result.risk_signals


@pytest.mark.parametrize(
    "query",
    [
        "What are the impairment indicators under IAS 36?",
        "Explain the complete bank-reconciliation process step by step.",
        "Create a timeline for completing a month-end financial close.",
    ],
)
def test_accounting_standard_and_procedure_queries_classify_as_accounting(query):
    qu.understand_fast.cache_clear()
    assert qu.understand_fast(query).domain == "accounting"


async def test_clear_domain_query_never_calls_remote_classifier(monkeypatch):
    qu.understand_fast.cache_clear()
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "fallback")

    def forbidden(*args, **kwargs):
        raise AssertionError("clear domain queries must stay on the fast path")

    monkeypatch.setattr(qu.llm_classifier, "classify", forbidden)
    result = await qu.understand(
        "Explain the ASC 606 revenue recognition model.",
        jurisdiction="US",
    )

    assert result.source == "deterministic"
    assert result.confidence >= 0.65


async def test_uncertain_query_uses_one_structured_remote_fallback(monkeypatch):
    qu.understand_fast.cache_clear()
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "fallback")
    calls = 0

    def classify(*args, **kwargs):
        nonlocal calls
        calls += 1
        return LLMClassification(
            risk_level="MEDIUM",
            confidence=0.92,
            intent="compare_reporting_options",
            advice_signal=False,
            missing_context=(),
            reason_codes=("interpretation",),
            model="test-model",
            domain="accounting",
            retrieval_query="Compare reporting options for section 2026",
            response_format="comparison",
            requested_depth="standard",
            requires_current_sources=False,
        )

    monkeypatch.setattr(qu.llm_classifier, "classify", classify)
    result = await qu.understand("Unusual reporting options section 2026")

    assert calls == 1
    assert result.source == "semantic_fallback"
    assert result.response_format == "comparison"
    assert "2026" in result.retrieval_query


async def test_remote_timeout_returns_fast_result_without_blocking_pipeline(monkeypatch):
    qu.understand_fast.cache_clear()
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "fallback")
    monkeypatch.setenv("QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "0.01")

    def slow_classifier(*args, **kwargs):
        import time

        time.sleep(0.50)
        return None

    monkeypatch.setattr(qu.llm_classifier, "classify", slow_classifier)
    started = asyncio.get_running_loop().time()
    result = await qu.understand("Unusual reporting choices without recognizable terminology")
    elapsed = asyncio.get_running_loop().time() - started

    assert result.source == "deterministic"
    assert elapsed < 0.25


def test_response_instruction_preserves_material_details():
    qu.understand_fast.cache_clear()
    result = qu.understand_fast("Explain the tax rule simply.", "US")
    instruction = qu.build_response_instruction(result)

    assert "plain language" in instruction.lower()
    assert "must not remove dates, thresholds, jurisdiction, exceptions, or citations" in instruction
