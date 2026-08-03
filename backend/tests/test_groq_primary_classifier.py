import json
import sys
from types import SimpleNamespace

from app.domains.risk_safety.llm_classifier import LLMClassification


def _classification(**overrides):
    values = dict(
        risk_level="HIGH",
        confidence=0.93,
        intent="RECOMMENDATION",
        advice_signal=True,
        missing_context=(),
        reason_codes=("REAL_CLIENT_CONTEXT",),
        model="test-groq-model",
        domain="tax",
        resolved_query="Should our client claim the deduction in India?",
        situation_type="REAL",
        subject_type="CLIENT",
        actionability="DECISION_SUPPORT",
        provider="groq",
    )
    values.update(overrides)
    return LLMClassification(**values)


def test_primary_mode_skips_regex_and_local_intent_classifiers(monkeypatch):
    import app.domains.risk_safety.risk_classifier as rc

    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "primary")
    monkeypatch.setattr(rc, "_get_classifier_pipeline", lambda: (_ for _ in ()).throw(
        AssertionError("local classifier must not run in primary mode")
    ))
    monkeypatch.setattr(rc.llm_classifier, "classify", lambda *args, **kwargs: _classification())

    decision = rc.classify(
        "What about in India?",
        jurisdiction="India",
        history=["Should our client claim this tax deduction?"],
    )

    assert decision["risk_level"] == "HIGH"
    assert "l2-llm-primary-applied" in decision["rules_applied"]
    assert not any(rule.startswith("l2-deterministic-") for rule in decision["rules_applied"])
    assert decision["classification_metadata"]["llm"]["resolved_query"].endswith("India?")


def test_primary_mode_routes_confident_restricted_intent_to_review(monkeypatch):
    import app.domains.risk_safety.risk_classifier as rc

    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODE", "primary")
    monkeypatch.setattr(
        rc.llm_classifier,
        "classify",
        lambda *args, **kwargs: _classification(
            risk_level="RESTRICTED", intent="EVASION", advice_signal=False,
            harm_intent="EVASION", reason_codes=("TAX_EVASION",),
        ),
    )

    decision = rc.classify("Describe a disguised way to hide taxable revenue")

    assert decision["risk_level"] == "RESTRICTED"
    assert decision["route"] == "HUMAN_REVIEW"
    assert decision["requires_human_review"] is True


def test_groq_provider_uses_openai_compatible_endpoint_and_context(monkeypatch):
    from app.domains.risk_safety import llm_classifier

    llm_classifier.clear_cache()
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("RISK_LLM_CLASSIFIER_MODEL", "test-groq-model")
    observed = {}
    payload = {
        "risk_level": "HIGH", "confidence": 0.94,
        "resolved_query": "Should our client claim the deduction in India?",
        "intent": "RECOMMENDATION", "secondary_intents": ["INTERPRETATION"],
        "advice_signal": True, "missing_context": [],
        "reason_codes": ["REAL_CLIENT_CONTEXT"], "domain": "tax",
        "retrieval_query": "India client tax deduction eligibility",
        "response_format": "adaptive", "requested_depth": "standard",
        "requires_current_sources": True, "situation_type": "REAL",
        "subject_type": "CLIENT", "actionability": "DECISION_SUPPORT",
        "professional_consequences": ["TAX_FILING"], "harm_intent": "NONE",
        "clarification_question": "",
    }

    class FakeCompletions:
        def create(self, **kwargs):
            observed["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            observed["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    result = llm_classifier.classify(
        "What about in India?",
        jurisdiction="India",
        history=["Should our client claim this tax deduction?"],
    )

    user_payload = json.loads(observed["request"]["messages"][1]["content"])
    assert observed["client"]["base_url"] == "https://api.groq.com/openai/v1"
    assert user_payload["previous_user_queries"] == ["Should our client claim this tax deduction?"]
    assert result is not None and result.provider == "groq"
    assert result.resolved_query == payload["resolved_query"]
