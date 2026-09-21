"""F0 task contracts and trusted context resolution."""
from __future__ import annotations

from dataclasses import dataclass

from app.orchestration.schemas import (
    AskKritonRequest, ContextDecision, TaskContext, TaskContextSelection, TaskSpec,
)

TASK_SPEC_VERSION = "f0.1"

TASK_SPECS: dict[str, TaskSpec] = {
    "general_question": TaskSpec(
        task_type="general_question", version=TASK_SPEC_VERSION, required_fields=[],
        allowed_outputs=["educational_answer", "source_summary"],
        prohibited_actions=["post_journal", "file_return", "move_funds", "issue_assurance_opinion"],
    ),
    "policy_research": TaskSpec(
        task_type="policy_research", version=TASK_SPEC_VERSION,
        required_fields=["engagement_id", "jurisdiction", "framework", "period_end"],
        allowed_outputs=["policy_research", "draft_conclusion", "source_comparison"],
        prohibited_actions=["issue_assurance_opinion", "file_return", "post_journal"],
        review_role="qualified_accounting_reviewer",
    ),
    "document_evidence_extraction": TaskSpec(
        task_type="document_evidence_extraction", version=TASK_SPEC_VERSION,
        required_fields=["engagement_id", "document_ids"],
        allowed_outputs=["extracted_facts", "evidence_locations", "missing_field_report"],
        prohibited_actions=["treat_customer_document_as_authority", "post_journal"],
        review_role="evidence_reviewer",
    ),
    "reconciliation": TaskSpec(
        task_type="reconciliation", version=TASK_SPEC_VERSION,
        required_fields=["engagement_id", "document_ids", "period_start", "period_end", "currency"],
        allowed_outputs=["matched_items", "unmatched_items", "variances", "draft_workpaper"],
        prohibited_actions=["post_journal", "move_funds", "approve_adjustment"],
        review_role="reconciliation_reviewer",
    ),
}

_JURISDICTIONS = {"UK": "GB", "GB": "GB", "UNITED KINGDOM": "GB"}
_FRAMEWORKS = {"IFRS": "IFRS", "UK GAAP": "UK_GAAP", "UK_GAAP": "UK_GAAP", "FRS 102": "UK_GAAP"}
_SUPPORTED_POLICY_CONTEXTS = {("GB", "IFRS"), ("GB", "UK_GAAP")}
_QUESTIONS = {
    "jurisdiction": "Which jurisdiction applies to this task?",
    "framework": "Which reporting framework applies (for example, IFRS or UK GAAP)?",
    "period_start": "What is the start date of the reconciliation period?",
    "period_end": "What reporting or transaction period end date should be used?",
    "currency": "Which currency should be used?",
    "document_ids": "Please attach the document or dataset required for this workflow.",
    "engagement_id": "Which authorized engagement should this professional task use?",
}


@dataclass(frozen=True)
class ResolutionInput:
    actor_id: str
    tenant_id: str
    role: str


def _normalise(value: str | None, aliases: dict[str, str]) -> str | None:
    if not value or not value.strip():
        return None
    normalised = value.strip().upper()
    return aliases.get(normalised, normalised)


def resolve_task_context(
    request: AskKritonRequest,
    identity: ResolutionInput,
    *,
    authorized_engagement_id: str | None = None,
) -> ContextDecision:
    selection = request.task_context or TaskContextSelection()
    spec = TASK_SPECS[selection.task_type]
    jurisdiction = _normalise(selection.jurisdiction or request.jurisdiction, _JURISDICTIONS)
    framework = _normalise(selection.framework, _FRAMEWORKS)
    language = (selection.language or "en").strip().lower()
    context = TaskContext(
        task_type=selection.task_type,
        task_spec_version=spec.version,
        actor_id=identity.actor_id,
        tenant_id=identity.tenant_id,
        actor_role=identity.role,
        # F1 will resolve authorized engagements. F0 must not echo a client id
        # into trusted context before that grant store exists.
        engagement_id=authorized_engagement_id,
        purpose=(selection.purpose or "answer_user_query").strip(),
        jurisdiction=jurisdiction,
        framework=framework,
        entity=selection.entity,
        period_start=selection.period_start,
        period_end=selection.period_end,
        currency=selection.currency.upper() if selection.currency else None,
        language=language,
        data_classification="CONFIDENTIAL" if request.document_ids else "INTERNAL",
        intended_use=selection.intended_use,
    )

    if selection.engagement_id and selection.engagement_id != authorized_engagement_id:
        return ContextDecision(
            status="unsupported", invalid_fields=["engagement_id"],
            reason_codes=["ENGAGEMENT_AUTHORIZATION_NOT_AVAILABLE"], resolved_context=context,
        )
    if language != "en":
        return ContextDecision(
            status="unsupported", invalid_fields=["language"],
            reason_codes=["UNSUPPORTED_LANGUAGE"], resolved_context=context,
        )

    missing: list[str] = []
    for field in spec.required_fields:
        value = request.document_ids if field == "document_ids" else getattr(context, field)
        if not value:
            missing.append(field)
    if missing:
        return ContextDecision(
            status="clarification_required", missing_fields=missing,
            reason_codes=[f"MISSING_{field.upper()}" for field in missing],
            clarification_questions=[_QUESTIONS[field] for field in missing],
            resolved_context=context,
        )

    if context.period_start and context.period_end and context.period_start > context.period_end:
        return ContextDecision(
            status="unsupported", invalid_fields=["period_start", "period_end"],
            reason_codes=["INVALID_PERIOD_RANGE"], resolved_context=context,
        )
    if selection.task_type == "policy_research" and (jurisdiction, framework) not in _SUPPORTED_POLICY_CONTEXTS:
        return ContextDecision(
            status="unsupported", invalid_fields=["jurisdiction", "framework"],
            reason_codes=["UNSUPPORTED_JURISDICTION_FRAMEWORK"], resolved_context=context,
        )
    return ContextDecision(status="complete", resolved_context=context)


def prompt_context(context: TaskContext) -> str:
    values = {
        "Workflow": context.task_type,
        "Jurisdiction": context.jurisdiction,
        "Framework": context.framework,
        "Entity": context.entity,
        "Period start": context.period_start,
        "Period end": context.period_end,
        "Currency": context.currency,
        "Language": context.language,
        "Intended use": context.intended_use,
    }
    lines = "\n".join(f"- {key}: {value}" for key, value in values.items() if value is not None)
    return f"\n\nSERVER-RESOLVED TASK CONTEXT (apply these boundaries):\n{lines}\n"
