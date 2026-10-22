"""A VAT summary of the user's own attached file is arithmetic over their
figures: it is answered from the verified document figures, not withheld for
want of an HMRC source. A tax rule added without a source is still removed."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import learned_answers, review, service
from app.orchestration.schemas import AskKritonRequest

FIGURES = ("\n\n=== Verified figures computed by Kriton from the attached documents ===\n"
           "Table 'sales.csv' (invoice_no, net_amount, vat_amount, gross_amount): 40 data rows\n"
           "- Total net_amount = 310,350; average 7,758.75; highest 13,950; lowest 1,567.50\n"
           "- Total vat_amount = 62,070; average 1,551.75; highest 2,790; lowest 313.50\n"
           "- Total gross_amount = 372,420; average 9,310.50; highest 16,740; lowest 1,881")
ANSWER = ("**VAT summary for the period**\n\n- Net sales: 310,350\n- Output VAT: 62,070\n- Gross sales: 372,420")


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
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", AsyncMock(return_value=AgentOutcome(text=ANSWER)))
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=""))


async def test_a_vat_summary_of_the_attached_file_is_answered_from_its_figures(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Prepare the VAT summary for this period."))
    assert response.answer is not None
    assert "62,070" in response.answer.text and "372,420" in response.answer.text
    assert "do not establish an answer" not in response.answer.text


async def test_a_tax_rule_added_without_a_source_is_still_removed(pipeline, monkeypatch):
    rule = "VAT returns are due one month and seven days after the end of the period."
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion",
                        AsyncMock(return_value=AgentOutcome(text=ANSWER + "\n\n" + rule)))
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Prepare the VAT summary for this period."))
    assert "62,070" in response.answer.text
    assert "one month and seven days" not in response.answer.text
