"""Tests for the three boundary properties of the LLM risk/semantic classifier:
it must not block the event loop, its two callers must not disagree about the
budget, and its query rewrite must not invert the question.

None of these change who classifies. The LLM remains the semantic and risk
authority in fallback/primary mode; these bound where it runs, how long it is
waited on, and what its rewrite is allowed to drop.
"""
import asyncio
import inspect
import re

import pytest

from app.domains.risk_safety import llm_classifier
from app.orchestration import service as orchestration_service
from app.orchestration.query_understanding import (
    _remote_timeout,
    _restricts_scope,
    _safe_remote_retrieval_query,
)


# ── 1. The classification call must not run on the event loop ────────────


def test_the_live_risk_classification_runs_off_the_event_loop():
    """classify_after_bundle() is synchronous and can block for seconds
    inside — a HuggingFace inference, an HTTPS call to the classification
    provider, or a threading.Event wait when another request holds the same
    query. Called directly from an async function, any of those stalls every
    other request the worker is serving."""
    source = inspect.getsource(orchestration_service.ask_kriton)
    assert "classify_after_bundle" in source
    for line in source.splitlines():
        if "classify_after_bundle" in line and not line.strip().startswith("#"):
            assert "to_thread" in line or "to_thread" in source.split(line)[0].splitlines()[-1], (
                "classify_after_bundle must be dispatched with asyncio.to_thread"
            )


def test_both_orchestration_paths_dispatch_classification_the_same_way():
    """The dormant KritonMediator sibling had the fix and the live path did
    not — the comment explaining why it mattered was attached to code that
    never ran."""
    module_source = inspect.getsource(orchestration_service)
    direct_calls = re.findall(
        r"^\s*decision = massarius_risk_safety\.classify_after_bundle", module_source, re.M,
    )
    assert direct_calls == [], "a synchronous classify_after_bundle call remains"


# ── 2. One budget, not two that drift ───────────────────────────────────


def test_the_understanding_budget_never_exceeds_the_classifier_budget(monkeypatch):
    # Waiting longer than the client can possibly take is a bound that can
    # never bind.
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "99")
    assert _remote_timeout() == 4.0


def test_a_shorter_understanding_budget_is_respected(monkeypatch):
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "2")
    assert _remote_timeout() == 2.0


def test_a_malformed_budget_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("QUERY_UNDERSTANDING_REMOTE_TIMEOUT_SECONDS", "not-a-number")
    assert _remote_timeout() == 3.0


def test_the_classifier_budget_is_the_whole_worst_case_not_half_of_it(monkeypatch):
    """max_retries was 1 against a PER-ATTEMPT timeout, so the real worst
    case was double the configured budget. Every caller already treats a
    None return as a soft failure, so the retry bought nothing."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", "5")
    llm_classifier.clear_cache()
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop after construction")

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    assert llm_classifier.classify("Assess this contract") is None
    assert captured["timeout"] == 5.0
    assert captured["max_retries"] == 0


def test_the_classifier_timeout_is_exported_for_both_callers():
    # Two independent os.getenv() calls for the same operation is how 1.25s
    # and 8s ended up six times apart.
    assert callable(llm_classifier.risk_classifier_timeout)
    assert llm_classifier.risk_classifier_timeout() > 0


# ── 3. The rewrite may simplify, never invert ────────────────────────────


def test_a_dropped_negation_rejects_the_rewrite():
    """'which leases are not in scope' and 'which leases are in scope' are
    opposite questions that retrieve the same documents and support opposite
    answers."""
    original = "Which leases are not in scope of IFRS 16?"
    assert _safe_remote_retrieval_query(original, "leases in scope of IFRS 16", "") != (
        "leases in scope of IFRS 16"
    )


def test_a_rephrased_negation_is_accepted():
    # The guard requires that SOME inversion survives, not the same word —
    # otherwise it would reject the paraphrasing the rewrite exists to do.
    original = "Which leases are not in scope of IFRS 16?"
    proposed = "leases excluded from IFRS 16 scope"
    assert _safe_remote_retrieval_query(original, proposed, "") == proposed


def test_a_dropped_exclusion_rejects_the_rewrite():
    original = "Revenue excluding intercompany sales for 2026"
    assert _safe_remote_retrieval_query(original, "revenue for 2026", "") == original


def test_a_dropped_restriction_rejects_the_rewrite():
    original = "Only UK-resident companies: what is the rate?"
    assert _safe_remote_retrieval_query(original, "rate for UK companies", "") == original


def test_a_dropped_contraction_negation_rejects_the_rewrite():
    # \b does not fall where the apostrophe does, so "doesn't" needs its own
    # pattern or it registers as no negation at all.
    original = "Doesn't ASC 842 require this?"
    assert _safe_remote_retrieval_query(original, "ASC 842 requirement", "") == original


def test_a_query_with_no_scope_terms_is_still_freely_rewritten():
    original = "What is the UK corporation tax rate for 2026?"
    proposed = "UK corporation tax rate 2026"
    assert _safe_remote_retrieval_query(original, proposed, "") == proposed


def test_the_numeric_guard_still_applies():
    original = "What was the rate in 2026?"
    assert _safe_remote_retrieval_query(original, "what was the rate", "") == original


def test_scope_detection_covers_inflections_not_just_exact_words():
    for text in ("excluded from scope", "excluding intercompany", "exclusion applies",
                 "except where stated", "not applicable", "doesn't apply",
                 "other than leases", "rather than IFRS", "solely for UK"):
        assert _restricts_scope(text), text
    for text in ("IFRS 16 lease scope", "corporation tax rate 2026",
                 "compare IFRS and GAAP", "notable disclosures"):
        assert not _restricts_scope(text), text


# ── The LLM keeps its role ──────────────────────────────────────────────


def test_none_of_this_changes_who_classifies(monkeypatch):
    """The guards bound the rewrite and the waiting, not the verdict. A
    rejected rewrite still leaves the LLM's risk_level, intent and
    advice_signal in force — only retrieval_query falls back.

    Runs in `primary` because that is the mode where understand() always
    consults the model. In `fallback` it short-circuits on a confident
    deterministic result, which is a separate inconsistency covered by the
    test below and deliberately left unchanged here.
    """
    import json
    import sys
    from types import SimpleNamespace

    from app.orchestration.query_understanding import understand

    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "primary")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm_classifier.clear_cache()

    payload = {
        "risk_level": "HIGH", "confidence": 0.93, "resolved_query": "x",
        "intent": "RECOMMENDATION", "secondary_intents": [], "advice_signal": True,
        "missing_context": [], "reason_codes": ["personalized_advice"], "domain": "tax",
        # A rewrite that drops the negation — must be rejected...
        "retrieval_query": "leases in scope of IFRS 16",
        "response_format": "concise", "requested_depth": "brief",
        "requires_current_sources": True, "situation_type": "REAL",
        "subject_type": "CLIENT", "actionability": "DECISION_SUPPORT",
        "professional_consequences": [], "harm_intent": "NONE",
        "clarification_question": "",
    }

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        OpenAI=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))))

    result = asyncio.run(understand("Which leases are not in scope of IFRS 16 for my client?"))

    # ...while every semantic and risk field the model produced survives.
    assert result.source == "semantic_fallback"
    assert result.personalized is True
    assert result.confidence == 0.93
    assert result.response_format == "concise"
    assert result.requires_current_sources is True
    assert "personalized_advice" in result.risk_signals
    assert result.retrieval_query != "leases in scope of IFRS 16"


def test_fallback_mode_still_short_circuits_understanding_on_a_confident_query(monkeypatch):
    """Documents a known asymmetry, not a fix: understand() consults the
    model only when the deterministic result scores below 0.65, while
    risk_classifier consults it whenever the local classifier is uncertain —
    which, with ENABLE_ML_CLASSIFIER off, is nearly always. So in `fallback`
    the LLM can be the risk authority on a query it never saw for semantic
    understanding. Left unchanged deliberately; the short-circuit is what
    keeps most requests off the network."""
    import sys
    from types import SimpleNamespace

    from app.orchestration.query_understanding import understand

    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "fallback")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm_classifier.clear_cache()

    called = []

    class ExplodingCompletions:
        def create(self, **kwargs):
            called.append(1)
            raise AssertionError("should not be reached for a confident query")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        OpenAI=lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=ExplodingCompletions()))))

    # "lease" resolves the accounting domain, which lifts the deterministic
    # confidence to 0.78 — above the 0.65 short-circuit.
    result = asyncio.run(understand("Which leases are not in scope of IFRS 16 for my client?"))
    assert result.source == "deterministic"
    assert called == []
