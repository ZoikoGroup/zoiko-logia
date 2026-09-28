from app.orchestration.schemas import AskKritonRequest, TaskContextSelection
from app.orchestration.workflow_planner import apply_plan, plan_workflow


def test_general_question_needs_no_manual_workflow() -> None:
    plan = plan_workflow(AskKritonRequest(query="Explain what reconciliation means."))

    assert plan.task_type == "general_question"
    assert plan.detection == "automatic"
    assert plan.steps[-1].capability == "response.compose"


def test_two_document_comparison_builds_reconciliation_plan() -> None:
    request = AskKritonRequest(
        query="Compare revenue in these statements and calculate the difference.",
        document_ids=["doc-a", "doc-b"],
    )
    plan = plan_workflow(request)

    assert plan.task_type == "reconciliation"
    assert plan.confidence >= 0.9
    assert {step.capability for step in plan.steps} >= {
        "document.retrieve", "document.extract", "numeric.compare",
        "numeric.calculate", "evidence.cite", "response.compose",
    }


def test_document_extraction_is_detected_from_intent_and_attachment() -> None:
    request = AskKritonRequest(
        query="Extract the reported operating profit with a page reference.",
        document_ids=["doc-a"],
    )

    assert plan_workflow(request).task_type == "document_evidence_extraction"


def test_policy_research_is_general_across_jurisdictions() -> None:
    request = AskKritonRequest(
        query="Which accounting requirements apply to this transaction?",
        task_context=TaskContextSelection(
            engagement_id="eng-1", jurisdiction="JP", framework="J-GAAP"
        ),
    )

    assert plan_workflow(request).task_type == "policy_research"


def test_explicit_override_remains_available_for_compatibility() -> None:
    request = AskKritonRequest(
        query="Review these documents.",
        task_context=TaskContextSelection(task_type="document_evidence_extraction"),
    )
    plan = plan_workflow(request)

    assert plan.task_type == "document_evidence_extraction"
    assert plan.detection == "explicit_override"
    assert apply_plan(request, plan).task_context.task_type == plan.task_type


def test_chart_request_adds_only_registered_chart_capability() -> None:
    plan = plan_workflow(AskKritonRequest(query="Chart the inflation trend."))

    assert "chart.generate" in {step.capability for step in plan.steps}
