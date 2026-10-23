"""An official-rate question gets its live data in agent mode too: the agent
has no tool for central bank or Treasury rates (service._official_rate_question)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import learned_answers, review, service
from app.orchestration.live_data import LiveDataResult
from app.orchestration.schemas import AskKritonRequest


def test_official_rate_questions_are_recognised():
    for question in ("Show the Bank of England base rate over the last 3 years as a line chart.",
                     "What is the Bank of Canada policy rate?", "RBA cash rate history", "Fed funds rate today",
                     "Plot US Treasury yields for 2025"):
        assert service._official_rate_question(question), question
    for question in ("What is income tax?", "Show UK inflation as a line chart", "What is the VAT rate?"):
        assert not service._official_rate_question(question), question


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
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: True)
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion",
                        AsyncMock(return_value=AgentOutcome(text="The UK Bank Rate is shown below.")))
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=""))
    live = AsyncMock(return_value=LiveDataResult())
    monkeypatch.setattr(service, "fetch_live_data", live)
    return live


async def test_an_official_rate_question_fetches_live_data_in_agent_mode(pipeline):
    await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                             request=AskKritonRequest(query="Show the Bank of England base rate over the last 3 years as a line chart."))
    pipeline.assert_awaited()
