from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.learning_cpd.schemas import (
    CPDEntryCreateRequest,
    CPDEntryPublic,
    CPDSummaryOut,
    SyllabusPathwayPublic,
    TopicMapNodePublic,
)
from app.domains.learning_cpd.service import (
    create_cpd_entry,
    get_cpd_summary,
    list_cpd_entries,
    list_syllabus_pathways,
    list_topic_map_nodes,
)

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/pathways", response_model=list[SyllabusPathwayPublic])
async def get_pathways(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SyllabusPathwayPublic]:
    pathways = await list_syllabus_pathways(db)
    return [SyllabusPathwayPublic.model_validate(p) for p in pathways]


@router.get("/topics", response_model=list[TopicMapNodePublic])
async def get_topics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TopicMapNodePublic]:
    topics = await list_topic_map_nodes(db)
    return [TopicMapNodePublic.model_validate(t) for t in topics]


@router.get("/cpd", response_model=list[CPDEntryPublic])
async def get_cpd_entries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CPDEntryPublic]:
    entries = await list_cpd_entries(db, current_user.id)
    return [CPDEntryPublic.model_validate(e) for e in entries]


@router.post("/cpd", response_model=CPDEntryPublic)
async def post_cpd_entry(
    payload: CPDEntryCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CPDEntryPublic:
    entry = await create_cpd_entry(db, current_user.tenant_id, current_user.id, payload)
    return CPDEntryPublic.model_validate(entry)


@router.get("/cpd/summary", response_model=CPDSummaryOut)
async def get_cpd_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CPDSummaryOut:
    summary = await get_cpd_summary(db, current_user.id)
    return CPDSummaryOut.model_validate(summary)


# Practice quizzes (see practice.py). A finished quiz is logged through the
# existing POST /learning/cpd, so it needs no endpoint of its own.
class PracticeAnswerRequest(BaseModel):
    question_id: str = Field(..., max_length=100)
    answer: str = Field("", max_length=4000)


@router.get("/practice/banks")
async def get_practice_banks(current_user: User = Depends(get_current_user)) -> list[dict]:
    from app.domains.learning_cpd.practice import list_banks

    return list_banks()


@router.get("/practice/{bank_id}/questions")
async def get_practice_questions(
    bank_id: str, count: int = 5, current_user: User = Depends(get_current_user),
) -> list[dict]:
    from app.domains.learning_cpd.practice import draw_questions

    return draw_questions(bank_id, count)


@router.post("/practice/{bank_id}/check")
async def post_practice_answer(
    bank_id: str, payload: PracticeAnswerRequest, current_user: User = Depends(get_current_user),
) -> dict:
    from app.domains.learning_cpd.practice import check_answer

    return check_answer(bank_id, payload.question_id, payload.answer)


@router.delete("/cpd/{entry_id}", status_code=204)
async def delete_cpd_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove one of the user's own CPD entries (a mistaken log). CPD is
    evidence of study, so the removal is recorded in the audit ledger."""
    from fastapi import HTTPException, Response
    from sqlalchemy import select

    from app.domains.audit_ledger.event_envelope import record_event_async
    from app.domains.learning_cpd.models import CPDEntry

    entry = (await db.execute(
        select(CPDEntry).where(CPDEntry.id == entry_id, CPDEntry.user_id == current_user.id,
                               CPDEntry.tenant_id == current_user.tenant_id)
    )).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="CPD entry not found")
    topic, minutes = entry.topic, entry.minutes
    await db.delete(entry)
    await db.commit()
    await record_event_async(
        db, tenant_id=current_user.tenant_id, event_name="learning.cpd_entry_deleted",
        emitting_service="learning_cpd", actor_id=current_user.id,
        subject_type="cpd_entry", subject_id=entry_id, payload={"topic": topic, "minutes": minutes},
    )
    return Response(status_code=204)
