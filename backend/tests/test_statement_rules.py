"""Document 01 rules on financial-statement answers (statement_rules.py)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import learned_answers, review, service
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.statement_rules import (
    CASH_FLOW_NOTE, COMPARATIVES_NOTE, STATUS_NOTE, is_statement_request, open_items, remove_unsupported_claims,
)


def test_statement_requests_are_recognised():
    for question in ("Generate income statement", "Prepare the financial statements from this trial balance",
                     "Show the balance sheet", "Prepare a cash flow statement", "P&L for the year",
                     "Statement of changes in equity"):
        assert is_statement_request(question), question
    for question in ("What is income tax?", "Prepare the VAT summary", "Show total sales by month"):
        assert not is_statement_request(question), question


def test_unsupported_claims_are_removed_and_honest_ones_kept():
    text = ("Profit for the year is 590,250.\n"
            "These statements are fully compliant with FRS 102. They have been audited.\n"
            "The accounts are not audited and must be reviewed by an accountant.\n"
            "The tax of 196,750 remains unpaid.\n"
            "We cannot tell whether the tax is unpaid without the payment records.\n"
            "| Line | Amount |\n| Audited total | 1 |")
    kept, removed = remove_unsupported_claims(text)
    assert "fully compliant" not in kept and "have been audited" not in kept and "remains unpaid" not in kept
    assert "not audited and must be reviewed" in kept and "cannot tell whether the tax is unpaid" in kept
    assert "| Audited total | 1 |" in kept          # tables are left alone
    assert "Profit for the year is 590,250." in kept and len(removed) == 3


def test_open_items_name_the_draft_status_missing_comparatives_and_name_based_classifications():
    tb = "account_code\taccount_name\tdebit\tcredit\n6000\tUtilities\t18400\t\n6100\tBank charges\t2900\t"
    notes = open_items("Generate income statement", "Utilities 18,400", tb)
    assert notes[0] == STATUS_NOTE and COMPARATIVES_NOTE in notes
    assert any("Utilities" in n and "Bank charges" in n for n in notes)
    two_years = "account_name\t2026\t2025\nRevenue\t100\t90"
    assert COMPARATIVES_NOTE not in open_items("Generate income statement", "", two_years)
    assert CASH_FLOW_NOTE in open_items("Prepare a cash flow statement", "", tb)


ANSWER = ("**Income statement**\n\n| Line | 2026 |\n| Revenue | 4,182,000 |\n| Profit for the year | 590,250 |\n\n"
          "These financial statements are compliant with FRS 102.")
FIGURES = ("\n\n=== Verified figures computed by Kriton from the attached documents ===\n"
           "Trial balance 'tb.csv': total debits = 7,026,500; total credits = 7,026,500; difference = 0\n"
           "- Income statement: Revenue = 4,182,000; Profit for the year = 590,250")


@pytest.fixture
def pipeline(monkeypatch):
    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(learned_answers, "feedback_guidance", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=RuntimeError("no governed library in tests")))
    monkeypatch.setattr(service, "web_search_each", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "classify_risk", AsyncMock(return_value="LOW"))
    monkeypatch.setattr(service, "classify_risk_gemini", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=SimpleNamespace(
        id="prompt-test", mode="agent", template="{query}", version="1", model_hint=None)))
    monkeypatch.setattr(service, "_verified_document_figures_context", AsyncMock(return_value=FIGURES))
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: True)
    agent = AsyncMock(return_value=AgentOutcome(text=ANSWER))
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", agent)
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=""))
    return agent


async def test_an_income_statement_answer_is_labelled_a_draft_without_a_compliance_claim(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Generate income statement"))
    assert "590,250" in response.answer.text and "compliant with FRS 102" not in response.answer.text
    assert response.answer.limitations[0] == STATUS_NOTE and COMPARATIVES_NOTE in response.answer.limitations
    prompt = str(pipeline.await_args)
    assert "Financial statement rules (ZoikoLogia Document 01)" in prompt


async def test_other_questions_are_unchanged(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Summarise the revenue in this file"))
    assert STATUS_NOTE not in response.answer.limitations
    assert "Financial statement rules" not in str(pipeline.await_args)
