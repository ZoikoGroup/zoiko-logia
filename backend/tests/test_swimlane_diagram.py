"""
Swimlane diagram — swimlane.py, the swimlane_diagram capability, and the
Kroki renderer in diagram_router.py.

A swimlane is a PROCESS_FLOW whose every stage names who performs it
("Clerk: Raise PO -> Manager: Approve PO"). These tests pin the three
promises it makes: the stages come only from the user's text, the PlantUML
sent to Kroki is generated from validated labels only, and a missing role
or a missing Kroki degrades to the ordinary flow instead of failing.
"""
import httpx
import pytest

from app.orchestration.data_shape import DIRECTED_STAGES, classify_data_shape
from app.orchestration.diagram_router import render_plantuml_svg
from app.orchestration.evidence import Entity, EvidenceModel, Relationship
from app.orchestration.extraction import extract_graph
from app.orchestration.intent_classifier import PROCESS, classify_intent
from app.orchestration.response_planner import detect_requested_chart_variant, plan_response
from app.orchestration.swimlane import build_plantuml, extract_swimlane_stages, split_lane_label
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator

P2P = ("Show the purchase-to-pay process as a swimlane: "
       "Clerk: Raise PO -> Manager: Approve PO -> Finance: Pay supplier")


def _decide(query: str):
    intent = classify_intent(query)
    graph = extract_graph(query)
    evidence = EvidenceModel()
    if graph:
        evidence.entities = [Entity(id=n, name=n) for n in graph.nodes]
        evidence.relationships = [
            Relationship(source_id=e.source, target_id=e.target, type=e.type) for e in graph.edges
        ]
        evidence.subject = query[:80]
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    return shape, VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query)


# ── parsing ──────────────────────────────────────────────────────────────

def test_role_and_step_are_read_from_each_stage():
    assert extract_swimlane_stages(P2P) == ["Clerk: Raise PO", "Manager: Approve PO", "Finance: Pay supplier"]


def test_swimlane_word_alone_is_a_process_request():
    query = "Show as a swimlane: Clerk: Raise PO -> Manager: Approve PO"
    assert classify_intent(query) == PROCESS
    assert detect_requested_chart_variant(query) == "SWIMLANE_DIAGRAM"


@pytest.mark.parametrize(
    "query",
    [
        # No swimlane request — role syntax alone is not enough.
        "Show the process: Clerk: Raise PO -> Manager: Approve PO",
        # One stage has no role — all or nothing, never a partial lane set.
        "Show as a swimlane: Clerk: Raise PO -> Approve PO",
        # A single stage is not a flow.
        "Show as a swimlane: Clerk: Raise PO",
    ],
)
def test_stages_are_only_read_from_a_complete_swimlane_request(query):
    assert extract_swimlane_stages(query) is None


def test_plantuml_syntax_characters_are_rejected():
    for label in ("Clerk: Raise PO;", "Clerk|Admin: Raise PO", "Clerk: Raise [PO]", "Raise PO"):
        assert split_lane_label(label) is None


# ── pipeline ─────────────────────────────────────────────────────────────

def test_swimlane_request_draws_the_swimlane_capability():
    shape, result = _decide(P2P)
    assert shape == DIRECTED_STAGES
    assert result.selected == "PROCESS_FLOW"
    assert result.capability_id == "swimlane_diagram"
    assert [n.label for n in result.spec.nodes] == [
        "Clerk: Raise PO", "Manager: Approve PO", "Finance: Pay supplier",
    ]
    assert VisualizationValidator().validate(result.spec).passed


def test_a_long_swimlane_is_not_replaced_by_the_interactive_workflow():
    # Six or more stages flips unnamed flows to the interactive workflow;
    # a swimlane the user asked for must survive that.
    query = ("Show as a swimlane: Clerk: Raise PO -> Manager: Approve PO -> Warehouse: Receive goods -> "
             "Finance: Match invoice -> Finance: Pay supplier -> Controller: Review ledger")
    _shape, result = _decide(query)
    assert result.capability_id == "swimlane_diagram"
    assert len(result.spec.nodes) == 6


def test_swimlane_without_roles_falls_back_to_a_flowchart_and_says_why():
    _shape, result = _decide("Show the purchase-to-pay process as a swimlane: Raise PO -> Approve PO -> Pay supplier")
    assert result.selected == "PROCESS_FLOW"
    assert result.capability_id == "flowchart_basic"
    assert "needs a role for each step" in result.spec.summary


def test_plain_flowchart_request_is_unchanged():
    _shape, result = _decide("Show the purchase-to-pay process as a flowchart: Raise PO -> Approve PO -> Pay supplier")
    assert result.capability_id == "flowchart_basic"
    assert not result.spec.summary


# ── PlantUML + Kroki ─────────────────────────────────────────────────────

def test_plantuml_has_one_lane_per_role_in_first_seen_order():
    source = build_plantuml(["Clerk: Raise PO", "Manager: Approve PO", "Clerk: File PO"])
    lines = source.splitlines()
    assert lines[0] == "@startuml" and lines[-1] == "@enduml"
    body = [line for line in lines if not line.startswith("skinparam")][1:-1]
    assert body == ["|Clerk|", "start", ":Raise PO;", "|Manager|", ":Approve PO;", "|Clerk|", ":File PO;", "stop"]


def test_plantuml_is_not_built_from_an_invalid_label():
    assert build_plantuml(["Clerk: Raise PO", "Manager: Approve PO;\n!include /etc/passwd"]) is None


async def test_kroki_svg_is_returned():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/plantuml/svg"
        assert request.content.startswith(b"@startuml")
        return httpx.Response(200, text='<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svg = await render_plantuml_svg(build_plantuml(["Clerk: Raise PO", "Manager: Approve PO"]), client=client)
    assert svg is not None and "<svg" in svg


async def test_unreachable_kroki_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await render_plantuml_svg("@startuml\n@enduml", client=client) is None


async def test_non_svg_kroki_answer_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Syntax Error?")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await render_plantuml_svg("@startuml\n@enduml", client=client) is None
