from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.learning_cpd.models import CPDEntry, SyllabusPathway, TopicMapNode
from app.domains.learning_cpd.schemas import CPDEntryCreateRequest


async def list_syllabus_pathways(db: AsyncSession) -> list[SyllabusPathway]:
    result = await db.execute(select(SyllabusPathway))
    return list(result.scalars().all())


async def list_topic_map_nodes(db: AsyncSession) -> list[TopicMapNode]:
    result = await db.execute(select(TopicMapNode))
    return list(result.scalars().all())


async def list_cpd_entries(db: AsyncSession, user_id: str) -> list[CPDEntry]:
    result = await db.execute(
        select(CPDEntry).where(CPDEntry.user_id == user_id).order_by(CPDEntry.logged_at.desc())
    )
    return list(result.scalars().all())


async def create_cpd_entry(
    db: AsyncSession, tenant_id: str, user_id: str, payload: CPDEntryCreateRequest
) -> CPDEntry:
    row = CPDEntry(
        tenant_id=tenant_id,
        user_id=user_id,
        topic=payload.topic,
        minutes=payload.minutes,
        note=payload.note,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_cpd_summary(db: AsyncSession, user_id: str) -> dict:
    entries = await list_cpd_entries(db, user_id)
    total_minutes = sum(e.minutes for e in entries)
    return {
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 1),
        "entries_count": len(entries),
    }
