"""
Kroki diagrams — kroki_diagrams.py, their five capabilities, and the render
endpoint's Kroki call in diagram_router.py.

Swimlane, BPMN, sequence and Gantt are PROCESS_FLOWs with one labelled node
per step, message or task; the ER diagram is an EVIDENCE_GRAPH of entities
and typed relationships. These tests pin the promises they share: the data
comes only from the user's text, the source sent to Kroki is generated from
validated labels only, and a structure that does not fit the diagram — or a
missing Kroki — degrades to the ordinary flow or graph instead of failing.
"""
import httpx
import pytest

from app.orchestration.data_shape import DIRECTED_STAGES, NODES_EDGES, classify_data_shape
from app.orchestration.diagram_router import render_svg
from app.orchestration.evidence import Entity, EvidenceModel, Relationship
from app.orchestration.extraction import extract_graph
from app.orchestration.intent_classifier import PROCESS, RELATIONSHIP, classify_intent
from app.orchestration.kroki_diagrams import build_source, extract_kroki_graph, split_lane_label
from app.orchestration.response_planner import detect_requested_chart_variant, plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator

P2P = ("Show the purchase-to-pay process as a swimlane: "
       "Clerk: Raise PO -> Manager: Approve PO -> Finance: Pay supplier")
BPMN_LANES = ("Show the purchase-to-pay process as a BPMN diagram: "
              "Clerk: Raise PO -> Manager: Approve PO -> Finance: Pay supplier")
BPMN_PLAIN = "Show the audit process as a BPMN diagram: Plan audit -> Perform fieldwork -> Sign off report"
SEQUENCE = ("Show the payment approval as a sequence diagram: Clerk -> Manager: Request approval; "
            "Manager -> Finance: Approve payment; Bank --> Finance: Confirm payment")
GANTT = ("Show the audit timeline as a Gantt chart: Planning: 2026-01-01 to 2026-01-05; "
         "Fieldwork: 6 Jan 2026 to 20 Jan 2026")
ERD = ("Show the billing data model as an ERD: Customer has many Invoice; "
       "Invoice has many Invoice Line; Customer has one Credit Account")


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

def test_each_diagram_reads_its_own_payload():
    assert extract_kroki_graph(P2P)[0] == ["Clerk: Raise PO", "Manager: Approve PO", "Finance: Pay supplier"]
    assert extract_kroki_graph(BPMN_PLAIN)[0] == ["Plan audit", "Perform fieldwork", "Sign off report"]
    assert extract_kroki_graph(SEQUENCE)[0] == [
        "1. Clerk -> Manager: Request approval",
        "2. Manager -> Finance: Approve payment",
        "3. Bank --> Finance: Confirm payment",
    ]
    # Written dates are normalised, so the Gantt source only ever sees ISO dates.
    assert extract_kroki_graph(GANTT)[0] == [
        "Planning: 2026-01-01 to 2026-01-05", "Fieldwork: 2026-01-06 to 2026-01-20",
    ]
    nodes, edges = extract_kroki_graph(ERD)
    assert nodes == ["Customer", "Invoice", "Invoice Line", "Credit Account"]
    assert edges == [("Customer", "Invoice", "has_many"), ("Invoice", "Invoice Line", "has_many"),
                     ("Customer", "Credit Account", "has_one")]


@pytest.mark.parametrize(
    "query, intent, variant",
    [
        ("Show as a swimlane: Clerk: Raise PO -> Manager: Approve PO", PROCESS, "SWIMLANE_DIAGRAM"),
        (BPMN_PLAIN, PROCESS, "BPMN_DIAGRAM"),
        (SEQUENCE, PROCESS, "SEQUENCE_DIAGRAM"),
        (GANTT, PROCESS, "GANTT_CHART"),
        (ERD, RELATIONSHIP, "ER_DIAGRAM"),
    ],
)
def test_diagram_names_are_recognised(query, intent, variant):
    assert classify_intent(query) == intent
    assert detect_requested_chart_variant(query) == variant


@pytest.mark.parametrize(
    "query",
    [
        # Role syntax without a swimlane request is not enough.
        "Show the process: Clerk: Raise PO -> Manager: Approve PO",
        # One stage has no role — all or nothing, never a partial lane set.
        "Show as a swimlane: Clerk: Raise PO -> Approve PO",
        # BPMN roles on some steps only.
        "Show as a BPMN diagram: Clerk: Raise PO -> Approve PO",
        # A single stage is not a flow.
        "Show as a swimlane: Clerk: Raise PO",
        # A message without a receiver.
        "Show as a sequence diagram: Clerk: Request approval; Manager -> Finance: Approve",
        # A Gantt task ending before it starts.
        "Show as a Gantt chart: Planning: 2026-01-05 to 2026-01-01; Fieldwork: 2026-01-06 to 2026-01-20",
        # An ER statement that is not a supported relationship.
        "Show as an ERD: Customer owns Invoice; Invoice has many Invoice Line",
    ],
)
def test_payloads_are_only_read_when_they_parse_completely(query):
    assert extract_kroki_graph(query) is None


def test_syntax_characters_are_rejected():
    for label in ("Clerk: Raise PO;", "Clerk|Admin: Raise PO", "Clerk: Raise [PO]", "Raise PO"):
        assert split_lane_label(label) is None
    assert build_source("sequence", ["1. A -> B: hi;\n@enduml", "2. B -> A: ok"]) is None
    assert build_source("gantt", ["[Plan]: 2026-01-01 to 2026-01-02", "Work: 2026-01-03 to 2026-01-04"]) is None
    assert build_source("erd", ["Customer", 'Invoice" as X'], [("Customer", 'Invoice" as X', "has_many")]) is None
    assert build_source("bpmn", ["Raise <PO>", "Approve PO"]) is None


# ── pipeline ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query, capability, selected, shape",
    [
        (P2P, "swimlane_diagram", "PROCESS_FLOW", DIRECTED_STAGES),
        (BPMN_LANES, "bpmn_diagram", "PROCESS_FLOW", DIRECTED_STAGES),
        (BPMN_PLAIN, "bpmn_diagram", "PROCESS_FLOW", DIRECTED_STAGES),
        (SEQUENCE, "sequence_diagram", "PROCESS_FLOW", DIRECTED_STAGES),
        (GANTT, "gantt_chart", "PROCESS_FLOW", DIRECTED_STAGES),
        (ERD, "er_diagram", "EVIDENCE_GRAPH", NODES_EDGES),
    ],
)
def test_each_diagram_request_draws_its_capability(query, capability, selected, shape):
    actual_shape, result = _decide(query)
    assert actual_shape == shape
    assert result.selected == selected
    assert result.capability_id == capability
    assert not result.spec.summary
    assert VisualizationValidator().validate(result.spec).passed


def test_a_long_swimlane_is_not_replaced_by_the_interactive_workflow():
    # Six or more stages flips unnamed flows to the interactive workflow;
    # a diagram the user named must survive that.
    query = ("Show as a swimlane: Clerk: Raise PO -> Manager: Approve PO -> Warehouse: Receive goods -> "
             "Finance: Match invoice -> Finance: Pay supplier -> Controller: Review ledger")
    _shape, result = _decide(query)
    assert result.capability_id == "swimlane_diagram"
    assert len(result.spec.nodes) == 6


@pytest.mark.parametrize(
    "query, reason",
    [
        ("Show the purchase-to-pay process as a swimlane: Raise PO -> Approve PO -> Pay supplier",
         "needs a role for each step"),
        ("Show the payment process as a sequence diagram: Raise PO -> Approve PO -> Pay supplier",
         "needs each message written as"),
        ("Show the audit plan as a Gantt chart: Planning -> Fieldwork -> Reporting",
         "needs each task with its dates"),
    ],
)
def test_a_structure_that_does_not_fit_falls_back_to_a_flowchart_and_says_why(query, reason):
    _shape, result = _decide(query)
    assert result.selected == "PROCESS_FLOW"
    assert result.capability_id == "flowchart_basic"
    assert reason in result.spec.summary


def test_unnamed_flows_and_graphs_are_unchanged():
    _shape, flow = _decide("Show the purchase-to-pay process as a flowchart: Raise PO -> Approve PO -> Pay supplier")
    assert flow.capability_id == "flowchart_basic" and not flow.spec.summary
    _shape, graph = _decide("Show the relationship network: Control A mitigates Risk One; Control B mitigates Risk Two")
    assert graph.capability_id == "evidence_graph"


# ── diagram source ───────────────────────────────────────────────────────

def _body(source: str) -> list[str]:
    return [line for line in source.splitlines() if not line.startswith(("skinparam", "hide", "autonumber"))]


def test_swimlane_source_has_one_lane_per_role_in_first_seen_order():
    body = _body(build_source("swimlane", ["Clerk: Raise PO", "Manager: Approve PO", "Clerk: File PO"]))
    assert body == ["@startuml", "|Clerk|", "start", ":Raise PO;", "|Manager|", ":Approve PO;",
                    "|Clerk|", ":File PO;", "stop", "@enduml"]


def test_sequence_source_declares_participants_and_keeps_reply_arrows():
    body = _body(build_source("sequence", extract_kroki_graph(SEQUENCE)[0]))
    assert body == ["@startuml", 'participant "Clerk" as P0', 'participant "Manager" as P1',
                    'participant "Finance" as P2', 'participant "Bank" as P3',
                    "P0 -> P1 : Request approval", "P1 -> P2 : Approve payment",
                    "P3 --> P2 : Confirm payment", "@enduml"]


def test_gantt_source_starts_the_project_on_the_first_task():
    source = build_source("gantt", extract_kroki_graph(GANTT)[0])
    assert "Project starts 2026-01-01" in source
    assert "[Fieldwork] starts 2026-01-06 and ends 2026-01-20" in source
    assert source.startswith("@startgantt") and source.endswith("@endgantt")


def test_erd_source_uses_crowsfoot_links():
    nodes, edges = extract_kroki_graph(ERD)
    source = build_source("erd", nodes, edges)
    assert 'entity "Invoice Line" as E2' in source
    assert "E0 ||--o{ E1 : has many" in source
    assert "E0 ||--|| E3 : has one" in source


def test_bpmn_source_has_a_lane_per_role_and_layout_for_every_element():
    source = build_source("bpmn", extract_kroki_graph(BPMN_LANES)[0])
    assert source.count("<bpmn:lane ") == 3
    assert source.count("<bpmn:task ") == 3
    # bpmn.js draws nothing without a diagram layout for each element.
    for element in ("Start", "Task_0", "Task_1", "Task_2", "End", "Lane_0", "Pool"):
        assert f'bpmnElement="{element}"' in source
    assert source.count("<bpmndi:BPMNEdge ") == 4


def test_bpmn_without_roles_has_no_pool():
    source = build_source("bpmn", extract_kroki_graph(BPMN_PLAIN)[0])
    assert "<bpmn:lane " not in source and "collaboration" not in source
    assert 'bpmnElement="Process_1"' in source


# ── Kroki ────────────────────────────────────────────────────────────────

async def test_kroki_svg_is_returned_for_the_diagram_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bpmn/svg"
        assert request.content.startswith(b"<?xml")
        return httpx.Response(200, text='<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svg = await render_svg("bpmn", build_source("bpmn", ["Raise PO", "Approve PO"]), client=client)
    assert svg is not None and "<svg" in svg


async def test_a_warming_up_kroki_is_retried_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, text="warming up")
        return httpx.Response(200, text="<svg></svg>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await render_svg("plantuml", "@startuml\n@enduml", client=client) == "<svg></svg>"
    assert len(calls) == 2


async def test_unreachable_kroki_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await render_svg("plantuml", "@startuml\n@enduml", client=client) is None


async def test_non_svg_kroki_answer_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Syntax Error?")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await render_svg("plantuml", "@startuml\n@enduml", client=client) is None
