"""Extra controls the implementation prompt requires besides the ten QA cases."""
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domains.source_library.licensing import SourceUseContext, _decide
from app.orchestration.calculations.engine import calculate_from_query


def test_unknown_rights_are_never_allowed():
    version = SimpleNamespace(revoked_at=None, superseded_by_version_id=None, status="APPROVED",
                              effective_from=None, effective_to=None)
    source = SimpleNamespace(is_tenant_private=False, tenant_id="GLOBAL_CONTROL", jurisdiction_scope="", framework_scope="")
    decision = _decide(version, source, None, SourceUseContext(tenant_id="t"), "model_transmission", datetime.now(timezone.utc))
    assert not decision.allowed and decision.reason_code == "RIGHT_UNKNOWN"


def test_classification_uncertain_is_never_low(monkeypatch):
    """A low-confidence classification routes to clarification at MEDIUM,
    never LOW (App. A: CLASSIFICATION_UNCERTAIN is not LOW)."""
    from app.domains.risk_safety import risk_classifier
    monkeypatch.setattr(risk_classifier, "_get_classifier_pipeline",
                        lambda: (lambda query, labels: {"labels": ["general accounting education"], "scores": [0.05]}))
    decision = risk_classifier.classify("tell me about that thing")
    assert "l2-classification-uncertain" in decision["rules_applied"]
    assert decision["risk_level"] != "LOW" and decision["route"] == "CLARIFICATION"


@pytest.mark.parametrize("query", [
    "Revenue ₹500,000 and expenses $4,000. Calculate profit margin.",
])
def test_mixed_currencies_ask_for_clarification(query):
    result = calculate_from_query(query)
    assert result.status == "clarification_required" and result.error_code == "CURRENCY_MISMATCH"


def test_a_missing_month_is_not_charted_from_invented_data():
    from app.domains.model_gateway.agent import unverified_chart_values
    import json
    evidence = "Monthly sales: Jan 120,000; Feb 135,000; Apr 150,000."  # March missing
    chart = {"type": "bar", "title": "Sales", "categories": ["Jan", "Feb", "Mar", "Apr"],
             "series": [{"name": "Sales", "data": [120000, 135000, 141000, 150000]}]}
    assert unverified_chart_values(json.dumps(chart), evidence) == [141000]


async def test_logs_hold_no_secrets_or_protected_prompt_content(monkeypatch, caplog):
    from app.domains.model_gateway import auxiliary as gateway

    class _Completions:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="LOW"))], usage=None)

    monkeypatch.setattr(gateway, "AsyncGroq", lambda api_key, **options: SimpleNamespace(chat=SimpleNamespace(completions=_Completions())))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_123")
    with caplog.at_level(logging.DEBUG):
        await gateway.complete_auxiliary(purpose="risk_classification", model="m", system="s",
                                         user="Client Jane Doe, NI number QQ123456C, email jane@example.com")
    assert "gsk_secret_value_123" not in caplog.text
    assert "jane@example.com" not in caplog.text and "QQ123456C" not in caplog.text
