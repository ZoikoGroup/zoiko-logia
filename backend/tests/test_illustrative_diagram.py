"""A diagram requested without its structure is drawn as a labelled general
illustration, through the same parsers and renderers (illustrative_diagram.py)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration import learned_answers, review, service
from app.orchestration.extraction import extract_graph
from app.orchestration.illustrative_diagram import NOTE, illustrated_query, needs_illustration
from app.orchestration.schemas import AskKritonRequest

FAILURE = "Kriton is temporarily unable to reach the language model provider."
SWIMLANE = "Clerk: Raise PO -> Manager: Approve PO -> Stores: Receive goods -> Finance: Pay supplier"


def test_only_a_diagram_without_its_structure_needs_an_illustration():
    assert needs_illustration("Show the purchase-to-pay process as a swimlane diagram")
    assert needs_illustration("Draw the purchase to pay process as a flowchart")
    assert needs_illustration("Create a class diagram for an accounting system")
    assert not needs_illustration(f"Show this as a swimlane diagram: {SWIMLANE}")      # structure given
    assert not needs_illustration("What is the VAT rate?")
    assert not needs_illustration("Show the audit plan as a Gantt chart")              # dates are the user's
    assert not needs_illustration("Show revenue as a bar chart")                       # charts need real data


async def test_the_structure_is_kept_only_when_the_parser_accepts_all_of_it():
    good = await illustrated_query("Show the purchase-to-pay process as a swimlane diagram",
                                   AsyncMock(return_value=SWIMLANE), FAILURE)
    assert good.endswith(SWIMLANE) and extract_graph(good) is not None
    for bad in ("Step 1 -> Step 2", "not a structure at all", FAILURE, ""):
        assert await illustrated_query("Draw the purchase to pay process as a flowchart", AsyncMock(return_value=bad), FAILURE) == ""


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
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=SimpleNamespace(
        id="prompt-test", mode="agent", template="{query}", version="1", model_hint=None)))
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: False)
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=SWIMLANE))


async def test_a_swimlane_without_steps_is_drawn_and_labelled(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Show the purchase-to-pay process as a swimlane diagram"))
    assert response.outcome == "answered"
    assert response.visualization is not None
    assert response.answer.limitations[0] == NOTE


async def test_extra_text_after_the_diagram_name_does_not_break_the_lanes():
    from app.orchestration.kroki_diagrams import extract_kroki_graph

    query = '"Show the purchase-to-pay process as a swimlane diagram"\tSwimlane: Clerk / Manager / Finance lanes'
    out = await illustrated_query(query, AsyncMock(return_value=SWIMLANE), FAILURE)
    assert out.endswith(SWIMLANE) and extract_kroki_graph(out) is not None   # a real swimlane, not a plain flow


def test_an_illustration_is_not_described_as_supplied():
    from app.orchestration.illustrative_diagram import illustration_wording

    text = ("Kriton mapped the 6 supplied accounting-workflow stages in order. "
            "The validated process visualization below does not add or remove stages.")
    reworded = illustration_wording(text)
    assert "supplied" not in reworded and "standard accounting-workflow stages" in reworded
    assert "general illustration" in reworded
