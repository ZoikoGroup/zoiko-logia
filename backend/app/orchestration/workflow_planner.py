"""Deterministic, capability-based workflow planning.

The planner understands intent without giving a model arbitrary execution
authority. It emits only registered capabilities; task contracts and F1
authorization remain the enforcement boundaries.
"""
from __future__ import annotations

import re

from app.orchestration.schemas import (
    AskKritonRequest,
    CapabilityStep,
    TaskContextSelection,
    WorkflowPlan,
)

_COMPARE = re.compile(r"\b(reconcil|compare|difference|variance|match|tie[ -]?out)\w*\b", re.I)
_EXTRACT = re.compile(r"\b(extract|find|locate|summari[sz]e|list|identify)\w*\b", re.I)
_POLICY = re.compile(
    r"\b(policy|standard|regulation|requirement|compliance|applicable|accounting treatment|"
    r"recognition criteria|disclosure requirement|ifrs|gaap|ias|frs)\w*\b",
    re.I,
)
_CALCULATE = re.compile(r"\b(calculate|compute|percentage|ratio|growth|margin|total)\w*\b", re.I)
_CHART = re.compile(r"\b(chart|graph|plot|visuali[sz]e|trend)\w*\b", re.I)
_EXECUTION = re.compile(r"\b(reconcile|compare|extract|calculate|compute|review|test)\w*\b", re.I)
_EDUCATIONAL = re.compile(r"^\s*(what is|what are|explain|define|how does|why does)\b", re.I)


def _step(capability: str, reason: str) -> CapabilityStep:
    return CapabilityStep(capability=capability, reason=reason)  # type: ignore[arg-type]


def plan_workflow(request: AskKritonRequest) -> WorkflowPlan:
    """Infer intent from query structure and attachments without reading content."""
    selection = request.task_context or TaskContextSelection()
    if selection.task_type is not None:
        task_type = selection.task_type
        detection = "explicit_override"
        confidence = 1.0
        reasons = ["CLIENT_TASK_OVERRIDE"]
    else:
        query = request.query.strip()
        document_count = len(set(request.document_ids))
        compare = bool(_COMPARE.search(query))
        policy = bool(_POLICY.search(query))
        extract = bool(_EXTRACT.search(query))
        execution = bool(_EXECUTION.search(query))
        educational = bool(_EDUCATIONAL.search(query))

        if document_count >= 2 and compare and execution:
            task_type, confidence = "reconciliation", 0.96
            reasons = ["MULTIPLE_DOCUMENTS", "COMPARISON_INTENT"]
        elif document_count and (extract or execution):
            task_type, confidence = "document_evidence_extraction", 0.94
            reasons = ["DOCUMENTS_ATTACHED", "EVIDENCE_INTENT"]
        elif policy and not (educational and not selection.engagement_id):
            task_type, confidence = "policy_research", 0.88
            reasons = ["POLICY_APPLICABILITY_INTENT"]
        else:


            
            task_type, confidence = "general_question", 0.92
            reasons = ["GENERAL_INFORMATION_INTENT"]
        detection = "automatic"

    steps: list[CapabilityStep] = []
    if request.document_ids:
        steps.extend([
            _step("document.retrieve", "Selected documents are required as evidence."),
            _step("document.extract", "Relevant facts must be extracted from authorized documents."),
        ])
    if task_type == "policy_research":
        steps.extend([
            _step("source.research", "Current authoritative sources are required."),
            _step("policy.lookup", "The request asks for applicable requirements."),
        ])
    if task_type == "reconciliation" or _COMPARE.search(request.query):
        steps.append(_step("numeric.compare", "The request asks for comparison or variance analysis."))
    if _CALCULATE.search(request.query):
        steps.append(_step("numeric.calculate", "The request contains an explicit calculation intent."))
    steps.append(_step("evidence.cite", "Material claims must retain evidence provenance."))
    if _CHART.search(request.query):
        steps.append(_step("chart.generate", "The user requested a visual representation."))
    steps.append(_step("response.compose", "A governed user-facing response is required."))

    return WorkflowPlan(
        task_type=task_type,
        detection=detection,
        confidence=confidence,
        reason_codes=reasons,
        steps=steps,
    )


def apply_plan(request: AskKritonRequest, plan: WorkflowPlan) -> AskKritonRequest:
    """Return a copy with the inferred broad task contract selected."""
    selection = request.task_context or TaskContextSelection()
    return request.model_copy(update={
        "task_context": selection.model_copy(update={"task_type": plan.task_type})
    })
