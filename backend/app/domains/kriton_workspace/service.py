import json
import logging

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.kriton_workspace.models import Draft, SavedAnswer, SavedVisualization
from app.domains.kriton_workspace.schemas import (
    DraftCreateRequest,
    DraftUpdateRequest,
    SavedAnswerCreateRequest,
    SavedVisualizationCreateRequest,
)
from app.orchestration import presentation_graph
from app.orchestration.schemas import CalculationWidget, PresentationChart, PresentationGraph, PresentationGuide

_logger = logging.getLogger(__name__)

# Maps the client-facing visualization_type to the specific AnswerPresentation
# sub-schema whose renderer supports export/save (see
# frontend/components/AnswerVisualizations.tsx's applicability rule).
# Round-tripping the incoming payload through this model's own validation is
# what guarantees only fields those schemas define are ever stored — an
# LLM-only field like reasoning_summary was never part of any of these
# schemas, so there is no field for it to leak through.
_PAYLOAD_MODEL_BY_TYPE = {
    "chart": CalculationWidget,
    "graph": PresentationGraph,
    "diagram": PresentationGuide,
    "presentation_chart": PresentationChart,
}

# The live renderers only ever produce payloads within these bounds
# (presentation_graph.MAX_NODES/MAX_EDGES for graphs; the compose/formula
# pipeline never emits more than a handful of chart points or guide steps;
# _chart_from_table caps rows at 12 and series at 4). This endpoint accepts
# arbitrary client JSON though, not just payloads the backend itself
# generated, so those limits have to be re-enforced here — otherwise a
# client could post a graph with thousands of nodes straight to storage
# regardless of what the live renderer would ever have allowed.
_MAX_CHART_POINTS = 60
_MAX_CHART_INPUTS = 20
_MAX_GUIDE_ITEMS = 20
_MAX_PRESENTATION_CHART_CATEGORIES = 60
_MAX_PRESENTATION_CHART_SERIES = 20
_MAX_PAYLOAD_BYTES = 200_000


def _enforce_payload_limits(visualization_type: str, payload: dict) -> None:
    if visualization_type == "graph":
        if len(payload.get("nodes", [])) > presentation_graph.MAX_NODES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many nodes")
        if len(payload.get("edges", [])) > presentation_graph.MAX_EDGES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many edges")
    elif visualization_type == "chart":
        if len(payload.get("chart_points", [])) > _MAX_CHART_POINTS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many chart points")
        if len(payload.get("inputs", [])) > _MAX_CHART_INPUTS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many chart inputs")
    elif visualization_type == "diagram":
        if len(payload.get("items", [])) > _MAX_GUIDE_ITEMS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many diagram steps")
        if len(payload.get("flow_nodes", [])) > _MAX_GUIDE_ITEMS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many workflow nodes")
        if len(payload.get("flow_edges", [])) > presentation_graph.MAX_EDGES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many workflow edges")
    elif visualization_type == "presentation_chart":
        if len(payload.get("categories", [])) > _MAX_PRESENTATION_CHART_CATEGORIES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many chart categories")
        if len(payload.get("series", [])) > _MAX_PRESENTATION_CHART_SERIES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many chart series")


async def list_saved_answers(db: AsyncSession, user_id: str) -> list[SavedAnswer]:
    result = await db.execute(
        select(SavedAnswer).where(SavedAnswer.user_id == user_id).order_by(SavedAnswer.created_at.desc())
    )
    return list(result.scalars().all())


async def create_saved_answer(
    db: AsyncSession, tenant_id: str, user_id: str, payload: SavedAnswerCreateRequest
) -> SavedAnswer:
    row = SavedAnswer(
        tenant_id=tenant_id,
        user_id=user_id,
        query_id=payload.query_id,
        query_text=payload.query_text,
        answer_text=payload.answer_text,
        risk_level=payload.risk_level,
        tags=payload.tags,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_saved_answer(db: AsyncSession, user_id: str, answer_id: str) -> bool:
    result = await db.execute(
        select(SavedAnswer).where(SavedAnswer.id == answer_id, SavedAnswer.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_saved_visualizations(db: AsyncSession, user_id: str, query_id: str | None = None) -> list[SavedVisualization]:
    stmt = select(SavedVisualization).where(SavedVisualization.user_id == user_id)
    if query_id:
        stmt = stmt.where(SavedVisualization.query_id == query_id)
    result = await db.execute(stmt.order_by(SavedVisualization.created_at.desc()))
    return list(result.scalars().all())


async def create_saved_visualization(
    db: AsyncSession, tenant_id: str, user_id: str, payload: SavedVisualizationCreateRequest
) -> SavedVisualization:
    model = _PAYLOAD_MODEL_BY_TYPE.get(payload.visualization_type)
    if model is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported visualization_type")
    try:
        clean_payload = model.model_validate(payload.payload).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid visualization payload") from exc

    stripped_fields = set(payload.payload.keys()) - set(model.model_fields.keys())
    if stripped_fields:
        # Field NAMES only, never their values — this is exactly the
        # boundary meant to keep something like an LLM reasoning_summary out
        # of storage, so the log can't become a backdoor for the same data.
        _logger.info(
            "saved_visualization_fields_stripped",
            extra={"visualization_type": payload.visualization_type, "stripped_fields": sorted(stripped_fields)},
        )

    _enforce_payload_limits(payload.visualization_type, clean_payload)
    if len(json.dumps(clean_payload)) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Visualization payload too large")

    row = SavedVisualization(
        tenant_id=tenant_id,
        user_id=user_id,
        query_id=payload.query_id,
        visualization_type=payload.visualization_type,
        schema_version=payload.schema_version,
        title=payload.title[:200],
        summary=payload.summary[:2000],
        payload=clean_payload,
        source_references=payload.source_references[:50],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_saved_visualization(db: AsyncSession, user_id: str, visualization_id: str) -> bool:
    result = await db.execute(
        select(SavedVisualization).where(SavedVisualization.id == visualization_id, SavedVisualization.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_drafts(db: AsyncSession, user_id: str) -> list[Draft]:
    result = await db.execute(select(Draft).where(Draft.user_id == user_id).order_by(Draft.updated_at.desc()))
    return list(result.scalars().all())


async def create_draft(db: AsyncSession, tenant_id: str, user_id: str, payload: DraftCreateRequest) -> Draft:
    row = Draft(
        tenant_id=tenant_id,
        user_id=user_id,
        title=payload.title,
        content=payload.content,
        saved_answer_id=payload.saved_answer_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_draft(db: AsyncSession, user_id: str, draft_id: str, payload: DraftUpdateRequest) -> Draft:
    result = await db.execute(select(Draft).where(Draft.id == draft_id, Draft.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    if payload.title is not None:
        row.title = payload.title
    if payload.content is not None:
        row.content = payload.content
    if payload.status is not None:
        row.status = payload.status

    await db.commit()
    await db.refresh(row)
    return row
