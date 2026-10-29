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


E01 = "Draw an accounts-payable three-way match flow from PO to payment."
FLOW_STEPS = "Raise PO -> Receive goods -> Match invoice to PO and receipt -> Approve invoice -> Pay supplier"


def test_a_flow_from_one_step_to_another_is_a_flowchart_request():
    # QA case E01 named no diagram type: nothing was drawn and the model
    # typed the flow as text art.
    assert needs_illustration(E01)
    assert needs_illustration("Draw the data flow from source trial balance to published financial statements.")
    assert not needs_illustration("Show the cash flow from operations to free cash flow.")
    assert not needs_illustration("Explain the flow from PO to payment.")   # nothing asked to be drawn


async def test_a_flow_from_po_to_payment_is_drawn_and_labelled(pipeline, monkeypatch):
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=FLOW_STEPS))
    out = await illustrated_query(E01, AsyncMock(return_value=FLOW_STEPS), FAILURE)
    assert extract_graph(out).nodes[0] == "Raise PO" and extract_graph(out).nodes[-1] == "Pay supplier"
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=E01))
    assert response.visualization is not None
    assert response.answer.limitations[0] == NOTE


async def test_extra_text_after_the_diagram_name_does_not_break_the_lanes():
    from app.orchestration.kroki_diagrams import extract_kroki_graph

    query = '"Show the purchase-to-pay process as a swimlane diagram"\tSwimlane: Clerk / Manager / Finance lanes'
    out = await illustrated_query(query, AsyncMock(return_value=SWIMLANE), FAILURE)
    assert out.endswith(SWIMLANE) and extract_kroki_graph(out) is not None   # a real swimlane, not a plain flow


MEMO = ("Purchasing procedure. The Clerk raises the purchase order. The Manager approves the purchase order. "
        "Stores receive the goods. Finance pays the supplier.")


async def test_a_diagram_of_an_attached_file_is_drawn_from_the_file_only():
    from app.orchestration.illustrative_diagram import document_query

    drawn = await document_query("Show the purchasing process in this file as a swimlane diagram", MEMO,
                                 AsyncMock(return_value=SWIMLANE), FAILURE)
    assert drawn.endswith(SWIMLANE) and extract_graph(drawn) is not None
    # The file describes no process, or the reply is a standard one the file does not contain.
    for reply in ("NONE", "Auditor: Plan audit -> Partner: Sign opinion -> Client: Receive report"):
        assert await document_query("Show the purchasing process in this file as a swimlane diagram", MEMO,
                                    AsyncMock(return_value=reply), FAILURE) == ""


async def test_a_file_diagram_is_drawn_and_labelled_and_a_file_without_steps_says_so(pipeline, monkeypatch):
    from app.orchestration.illustrative_diagram import DOCUMENT_NOTE, NOT_IN_DOCUMENT_NOTE
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(service, "resolve_conversation_document_ids", AsyncMock(return_value=["doc-1"]))
    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=[
        WebSource(title="procedure.docx — Section 1", url="", snippet=MEMO, source_id="doc-1")]))
    query = "Show the purchasing process in this file as a swimlane diagram"
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=query, document_ids=["doc-1"]))
    assert response.visualization is not None and response.answer.limitations[0] == DOCUMENT_NOTE

    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value="NONE"))
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=query, document_ids=["doc-1"]))
    assert response.visualization is None and NOT_IN_DOCUMENT_NOTE in response.answer.limitations


async def test_a_follow_up_unrelated_to_the_chat_file_is_not_answered_from_it(pipeline, monkeypatch):
    from app.orchestration.websearch import WebSource

    # No new upload: the chat's file is restored by the conversation.
    monkeypatch.setattr(service, "resolve_conversation_document_ids", AsyncMock(return_value=["doc-1"]))
    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=[
        WebSource(title="procedure.docx — Section 1", url="", snippet=MEMO, source_id="doc-1")]))
    from app.orchestration import conversation_memory
    monkeypatch.setattr(conversation_memory, "load_turns", AsyncMock(return_value=[]))
    monkeypatch.setattr(conversation_memory, "save_turn", AsyncMock())
    monkeypatch.setattr(conversation_memory, "save_snapshot", AsyncMock())
    db = AsyncMock()
    for query, used in (("What is IPR?", 0), ("Summarise the document", 1)):
        service.audit_document_retrieval.reset_mock()
        await service.ask_kriton(db, MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                 request=AskKritonRequest(query=query, conversation_id="c-1"))
        assert service.audit_document_retrieval.await_args.kwargs["hit_count"] == used, query


def test_an_illustration_is_not_described_as_supplied():
    from app.orchestration.illustrative_diagram import illustration_wording

    text = ("Kriton mapped the 6 supplied accounting-workflow stages in order. "
            "The validated process visualization below does not add or remove stages.")
    reworded = illustration_wording(text)
    assert "supplied" not in reworded and "standard accounting-workflow stages" in reworded
    assert "general illustration" in reworded
