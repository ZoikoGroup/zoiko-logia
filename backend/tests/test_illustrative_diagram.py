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
    assert not response.answer.computed_from_question   # a standard process, not the question's figures
    # QA case E04: the same steps as an ordered list, in the drawing's order.
    assert "1. Raise PO\n2. Receive goods\n3. Match invoice to PO and receipt\n4. Approve invoice\n5. Pay supplier" \
        in response.answer.text


BRANCHED = ("Raise PO -> Receive goods -> Receive invoice -> Three way match passed? Yes -> Approve invoice -> "
            "Pay supplier; No -> Place invoice on hold -> Reviewer resolves exception -> Three way match passed")


async def test_e01_a_mismatch_routes_to_hold_in_the_drawing_and_the_list(pipeline, monkeypatch):
    # QA case E01 was drawn as one straight line, with no "mismatches route to hold".
    from app.orchestration.illustrative_diagram import FLOW, _FORMATS
    assert "? Yes ->" in _FORMATS[FLOW][1] and "? No ->" in _FORMATS[FLOW][1]
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=BRANCHED))
    edges = [(e.source, e.target, e.type) for e in extract_graph(
        await illustrated_query(E01, AsyncMock(return_value=BRANCHED), FAILURE)).edges]
    assert ("Three way match passed", "Place invoice on hold", "No") in edges
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=E01))
    assert response.visualization is not None
    assert "4. Three way match passed? Yes → Approve invoice; No → Place invoice on hold" in response.answer.text
    assert "8. Reviewer resolves exception → back to Three way match passed" in response.answer.text


def test_e04_each_decision_keeps_its_own_yes_and_no_paths():
    # Every Yes and No path hung off the first decision, and "Approve PO?" was a plain step.
    reply = ("Requisition submitted -> Approve requisition? Yes -> Create purchase order -> Approve PO? Yes -> "
             "Receive goods -> Match invoice? Yes -> Pay vendor; Approve requisition? No -> Reject requisition; "
             "Match invoice? No -> Resolve invoice issue -> Match invoice")
    from app.orchestration.illustrative_diagram import FLOW, _with_structure
    graph = extract_graph(_with_structure("Give the purchase-to-pay flow as a flowchart.", FLOW, reply, FAILURE))
    edges = {(e.source, e.type, e.target) for e in graph.edges}
    assert {("Approve requisition", "Yes", "Create purchase order"), ("Approve PO", "Yes", "Receive goods"),
            ("Match invoice", "Yes", "Pay vendor"), ("Approve requisition", "No", "Reject requisition"),
            ("Match invoice", "No", "Resolve invoice issue"), ("Resolve invoice issue", "next", "Match invoice")} <= edges
    assert not any(node.endswith("?") for node in graph.nodes)
    # A path written twice is one arrow ("Yes → Receive invoice" was listed twice).
    twice = extract_graph(_with_structure("Give the purchase-to-pay flow as a flowchart.", FLOW,
                                          "Order goods -> Goods received? Yes -> Receive invoice -> Pay; Goods received? "
                                          "No -> Follow up vendor -> Goods received? Yes -> Receive invoice", FAILURE))
    assert [(e.source, e.type, e.target) for e in twice.edges].count(("Goods received", "Yes", "Receive invoice")) == 1
    # The decisions are one diagram request, not separate questions.
    from app.orchestration.websearch import sub_questions
    query = _with_structure("Give the purchase-to-pay flow as a flowchart.", FLOW, reply, FAILURE)
    assert sub_questions(query) == [query]
    assert len(sub_questions("What is VAT? What is GST?")) == 2


@pytest.mark.parametrize("reply", [
    "Raise requisition -> Requisition approved? Yes -> Create purchase order -> Order approved? Yes -> "
    "Receive goods -> Pay supplier; Requisition approved? No -> Revise requisition; Order approved? No -> Hold order",
    # The 14-stage flow of the QA retest, as the model wrote it.
    "Start -> Requisition approved? Yes -> Create purchase order -> PO approved? Yes -> Receive goods -> Goods "
    "receipt matched? Yes -> Invoice received -> Invoice matched? Yes -> Payment processed -> End; Requisition "
    "approved? No -> Revise requisition -> Start; PO approved? No -> Hold purchase order -> Create purchase order; "
    "Goods receipt matched? No -> Return goods -> Receive goods; Invoice matched? No -> Resolve discrepancy -> "
    "Invoice received",
])
async def test_e04_a_branched_flow_is_drawn_not_reported_as_missing(pipeline, monkeypatch, reply):
    query = "Give the same purchase-to-pay flow as a flowchart and an ordered text list."
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=reply))
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=query))
    assert response.visualization is not None
    assert not any("could not be built" in note or "questions" in note for note in response.answer.limitations)


async def test_a_list_after_the_step_line_does_not_discard_the_steps():
    # QA case E04 asked for a flowchart and an ordered list; the reply had both.
    reply = ("Raise requisition -> Approve requisition -> Issue purchase order -> Receive goods -> Pay supplier"
             "\n\n1. Raise requisition\n2. Approve requisition\n3. Issue purchase order")
    out = await illustrated_query("Give the same purchase-to-pay flow as a flowchart and an ordered text list.",
                                  AsyncMock(return_value=reply), FAILURE)
    assert extract_graph(out).nodes == ["Raise requisition", "Approve requisition", "Issue purchase order",
                                        "Receive goods", "Pay supplier"]


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


async def test_e01_e04_a_file_of_records_gets_the_standard_flow_labelled_not_from_the_file(pipeline, monkeypatch):
    # Live run (11 Nov 2026): NB-3WAY.csv holds a PO, a receipt and an invoice,
    # not the steps; nothing was drawn and the model made a Sankey of invented flows.
    from app.orchestration.illustrative_diagram import NOT_FROM_FILE_NOTE, NOT_IN_DOCUMENT_NOTE
    from app.orchestration.websearch import WebSource

    records = ("record_type\treference\tquantity\tstate\nPURCHASE_ORDER\tPO-NB-001\t10\tAPPROVED_PO\n"
               "GOODS_RECEIPT\tGR-NB-001\t9\tRECEIVED_9\nSUPPLIER_INVOICE\tINV-NB-001\t10\tUNAPPROVED_EXCEPTION")
    monkeypatch.setattr(service, "resolve_conversation_document_ids", AsyncMock(return_value=["doc-1"]))
    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=[
        WebSource(title="NB-3WAY.csv — rows", url="", snippet=records, source_id="doc-1")]))
    # The file prompt finds nothing in the file; the standard prompt gives the steps.
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(
        side_effect=lambda prompt, *a, **k: "NONE" if "Using ONLY the document" in prompt else BRANCHED))
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query=E01, document_ids=["doc-1"]))
    assert response.visualization is not None
    assert response.answer.limitations[:2] == [NOT_FROM_FILE_NOTE, NOTE]
    assert NOT_IN_DOCUMENT_NOTE not in response.answer.limitations


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
