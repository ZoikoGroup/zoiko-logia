from fastapi import APIRouter, Depends
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
