"""
Compose step: pick an approved prompt template and run it through the model
gateway, grounded in whatever the retrieve step found. Never falls back to an
unapproved prompt — if none is approved for this mode, composition is
unavailable rather than silently using an unreviewed template.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.model_gateway.models import PromptTemplate
from app.orchestration.schemas import SourceBundle


async def select_prompt(db: AsyncSession, mode: str) -> PromptTemplate | None:
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.status == "Approved", PromptTemplate.mode == mode)
    )
    prompt = result.scalars().first()
    if prompt is not None:
        return prompt

    result = await db.execute(select(PromptTemplate).where(PromptTemplate.status == "Approved"))
    return result.scalars().first()


def build_grounded_input(query: str, bundle: SourceBundle) -> str:
    if not bundle.sources:
        return query
    source_lines = "\n".join(
        f"- {s.title} ({s.version_label}, {s.jurisdiction_scope})" for s in bundle.sources
    )
    return f"{query}\n\nGrounded in:\n{source_lines}"
