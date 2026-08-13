"""
Regression suite for X6-vs-Mermaid PROCESS_FLOW routing (spec §11): a simple/
read-only flow should route to Mermaid, an explicitly-interactive request or
a large stage count should route to X6. Both draw from the SAME
nodes/edges — evidence never differs between the two renderers.
"""
from app.orchestration.evidence import EvidenceModel, Entity, Relationship
from app.orchestration.intent_classifier import classify_intent, PROCESS
from app.orchestration.data_shape import classify_data_shape, DIRECTED_STAGES
from app.orchestration.response_planner import plan_response, detect_explicit_interactive_request
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator


def _stage_evidence(n: int) -> EvidenceModel:
    ids = [f"Stage{i}" for i in range(n)]
    return EvidenceModel(
        entities=[Entity(id=s, name=s) for s in ids],
        relationships=[Relationship(source_id=ids[i], target_id=ids[i + 1], type="next") for i in range(n - 1)],
    )


def test_detect_explicit_interactive_request():
    assert detect_explicit_interactive_request("Show an interactive workflow: A -> B.") is True
    assert detect_explicit_interactive_request(
        "Create an interactive accounts-payable workflow: Invoice -> Approval."
    ) is True
    assert detect_explicit_interactive_request(
        "Create an interactive AML compliance review process: Intake -> Decision."
    ) is True
    assert detect_explicit_interactive_request("Explain the invoice approval process: A -> B.") is False


def test_plan_carries_explicit_interactive_flag():
    q = "Show an interactive workflow: Invoice -> Review -> Approval."
    plan = plan_response(q, PROCESS, DIRECTED_STAGES)
    assert plan.explicit_interactive_request is True


def test_plain_process_request_routes_to_mermaid_not_x6():
    q = "Explain the invoice approval process: Invoice -> Review -> Approval -> Payment."
    intent = classify_intent(q)
    evidence = _stage_evidence(4)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="flow-simple")
    assert result.selected == "PROCESS_FLOW"
    assert result.spec.interactive is False


def test_explicit_interactive_request_routes_to_x6():
    q = "Show an interactive workflow: Invoice -> Review -> Approval -> Payment."
    intent = classify_intent(q)
    evidence = _stage_evidence(4)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="flow-interactive")
    assert result.spec.interactive is True


def test_qualified_interactive_workflow_routes_to_x6():
    q = "Create an interactive accounts-payable workflow: Invoice -> Review -> Approval -> Payment."
    intent = classify_intent(q)
    evidence = _stage_evidence(4)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="flow-qualified-interactive")
    assert plan.explicit_interactive_request is True
    assert result.spec.interactive is True


def test_large_stage_count_routes_to_x6_even_without_explicit_request():
    q = "Explain this process: " + " -> ".join(f"Stage{i}" for i in range(8))
    intent = classify_intent(q)
    evidence = _stage_evidence(8)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(q, intent, shape)
    assert plan.explicit_interactive_request is False
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="flow-large")
    assert result.spec.interactive is True


def test_same_evidence_backs_both_renderer_choices():
    # The nodes/edges themselves must be identical regardless of which
    # renderer is chosen — only `interactive` should differ.
    evidence = _stage_evidence(3)
    plan_simple = plan_response("Explain this process: A -> B -> C.", PROCESS, DIRECTED_STAGES)
    plan_interactive = plan_response("Show an interactive workflow: A -> B -> C.", PROCESS, DIRECTED_STAGES)
    r1 = VisualizationOrchestrator().decide(evidence, DIRECTED_STAGES, plan_simple, spec_id="a")
    r2 = VisualizationOrchestrator().decide(evidence, DIRECTED_STAGES, plan_interactive, spec_id="b")
    assert [n.label for n in r1.spec.nodes] == [n.label for n in r2.spec.nodes]
    assert r1.spec.interactive is False
    assert r2.spec.interactive is True
