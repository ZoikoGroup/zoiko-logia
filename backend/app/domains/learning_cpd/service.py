from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.learning_cpd.models import SyllabusPathway, TopicMapNode


async def list_syllabus_pathways(db: AsyncSession) -> list[SyllabusPathway]:
    result = await db.execute(select(SyllabusPathway))
    return list(result.scalars().all())


async def list_topic_map_nodes(db: AsyncSession) -> list[TopicMapNode]:
    result = await db.execute(select(TopicMapNode))
    return list(result.scalars().all())
