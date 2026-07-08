from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.learning_cpd.schemas import SyllabusPathwayPublic, TopicMapNodePublic
from app.domains.learning_cpd.service import list_syllabus_pathways, list_topic_map_nodes

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
