import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.evaluation.models import BenchmarkCase, EvaluationDataset
from app.domains.learning_system.models import (
    FeedbackItem, LearningCandidate, MemoryItem, SourceUpdateReview, WorkflowDefinition,
)
from app.domains.learning_system.schemas import FeedbackCreate
from app.domains.source_library.models import SourceVersion


def _now():
    return datetime.now(timezone.utc)


async def submit_feedback(db: AsyncSession, payload: FeedbackCreate, user) -> tuple[FeedbackItem, str | None, str | None]:
    feedback = FeedbackItem(tenant_id=user.tenant_id, user_id=user.id, **payload.model_dump(exclude={"remember_correction"}))
    db.add(feedback)
    await db.flush()
    candidate_id = None
    memory_id = None
    if payload.feedback_type == "NOT_HELPFUL":
        candidate = LearningCandidate(
            tenant_id=user.tenant_id, feedback_id=feedback.id, query_text=payload.query_text,
            expected_answer=payload.correction, reason_code=payload.reason_code,
        )
        db.add(candidate)
        await db.flush()
        candidate_id = candidate.id
    if payload.remember_correction and payload.correction.strip():
        key = f"feedback:{payload.query_id}"
        found = await db.execute(select(MemoryItem).where(
            MemoryItem.tenant_id == user.tenant_id, MemoryItem.user_id == user.id, MemoryItem.key == key,
        ))
        memory = found.scalar_one_or_none() or MemoryItem(tenant_id=user.tenant_id, user_id=user.id, key=key)
        memory.value = payload.correction.strip()
        memory.confirmed = True
        memory.source_feedback_id = feedback.id
        db.add(memory)
        await db.flush()
        memory_id = memory.id
    await db.commit()
    await db.refresh(feedback)
    return feedback, candidate_id, memory_id


async def review_candidate(db: AsyncSession, candidate: LearningCandidate, decision: str, note: str, reviewer_id: str, promote: bool):
    candidate.status = decision
    candidate.review_note = note
    candidate.reviewer_id = reviewer_id
    candidate.reviewed_at = _now()
    if decision == "APPROVED" and promote and candidate.query_text and candidate.expected_answer:
        result = await db.execute(select(EvaluationDataset).where(EvaluationDataset.id == "feedback-learning-v1"))
        dataset = result.scalar_one_or_none()
        if dataset is None:
            dataset = EvaluationDataset(id="feedback-learning-v1", version="1", status="ACTIVE", domain="kriton_feedback")
            db.add(dataset)
        case = BenchmarkCase(
            id=f"feedback-{uuid.uuid4().hex[:16]}", dataset_id=dataset.id,
            query_text=candidate.query_text, gold_answer=candidate.expected_answer,
            source_refs=[], risk_scope="LOW",
        )
        db.add(case)
        candidate.benchmark_case_id = case.id
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def review_source_update(db: AsyncSession, item: SourceUpdateReview, decision: str, note: str, reviewer_id: str):
    if item.submitted_by == reviewer_id:
        raise HTTPException(403, "Maker-checker violation: submitter cannot approve this source update.")
    item.status = decision
    item.review_note = note
    item.reviewer_id = reviewer_id
    item.reviewed_at = _now()
    if decision == "APPROVED":
        result = await db.execute(select(SourceVersion).where(SourceVersion.id == item.proposed_version_id))
        version = result.scalar_one_or_none()
        if version is None or version.source_id != item.source_id:
            raise HTTPException(404, "Proposed source version not found")
        version.status = "APPROVED"
        version.approved_by = reviewer_id
    await db.commit()
    await db.refresh(item)
    return item


async def match_workflow(db: AsyncSession, tenant_id: str, goal: str, output_format: str):
    result = await db.execute(select(WorkflowDefinition).where(
        WorkflowDefinition.active.is_(True),
        WorkflowDefinition.tenant_id.in_([tenant_id, "GLOBAL_CONTROL"]),
    ).order_by(WorkflowDefinition.version.desc()))
    normalized = goal.lower()
    for workflow in result.scalars():
        terms = [str(term).lower() for term in workflow.match_terms]
        if terms and all(term in normalized for term in terms) and output_format.lower() in workflow.allowed_formats:
            return workflow
    return None
