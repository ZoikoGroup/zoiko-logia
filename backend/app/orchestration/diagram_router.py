"""
Server-side diagram rendering through a self-hosted Kroki service — swimlane,
sequence, Gantt, BPMN and ER diagrams (see kroki_diagrams.py).

The browser sends the node labels and edges of a spec it already received;
this endpoint re-validates them, generates the diagram source itself and
returns Kroki's SVG. The browser never sends diagram source, so the endpoint
cannot be used to render arbitrary PlantUML or BPMN.

Kroki is optional. When it is not running, this returns 503 and the frontend
draws the ordinary flow or graph from the same data instead.

KROKI_URL defaults to the port docker-compose.yml publishes (8300, not
Kroki's own 8000, which the local backend already uses).
"""
from __future__ import annotations

import logging
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.rate_limit import limiter
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.kroki_diagrams import KROKI_TYPES, build_source
from app.orchestration.router import _user_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagrams", tags=["Diagram Rendering"])

_KROKI_TIMEOUT_SECONDS = 15.0
_MAX_SVG_BYTES = 2_000_000


def _kroki_url() -> str:
    return os.getenv("KROKI_URL", "http://localhost:8300").rstrip("/")


class DiagramEdge(BaseModel):
    source: str = Field(max_length=80)
    target: str = Field(max_length=80)
    type: str = Field(max_length=30)


class DiagramRenderRequest(BaseModel):
    kind: Literal["swimlane", "sequence", "gantt", "bpmn", "erd"]
    labels: list[str] = Field(min_length=2, max_length=40)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=80)
    theme: Literal["light", "dark"] = "light"


class DiagramRenderResponse(BaseModel):
    svg: str


async def _post_to_kroki(client: httpx.AsyncClient, diagram_type: str, source: str) -> httpx.Response:
    return await client.post(
        f"{_kroki_url()}/{diagram_type}/svg",
        content=source.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )


async def render_svg(diagram_type: str, source: str, client: httpx.AsyncClient | None = None) -> str | None:
    """SVG from Kroki, or None when Kroki is unreachable or answers with
    anything that is not an SVG document."""
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=_KROKI_TIMEOUT_SECONDS) as own_client:
                response = await _post_to_kroki(own_client, diagram_type, source)
                # A freshly started Kroki answers its first request with a 500
                # while it warms up; one retry covers that.
                if response.status_code >= 500:
                    response = await _post_to_kroki(own_client, diagram_type, source)
        else:
            response = await _post_to_kroki(client, diagram_type, source)
            if response.status_code >= 500:
                response = await _post_to_kroki(client, diagram_type, source)
    except httpx.HTTPError:
        logger.warning("Kroki unreachable at %s", _kroki_url())
        return None
    if response.status_code != 200 or len(response.content) > _MAX_SVG_BYTES:
        logger.warning("Kroki returned status=%s size=%s for %s", response.status_code, len(response.content), diagram_type)
        return None
    svg = response.text
    return svg if "<svg" in svg[:2000] else None


@router.post("/render", response_model=DiagramRenderResponse)
@limiter.limit("60/minute", key_func=_user_key)
async def post_render(
    request: Request,
    payload: DiagramRenderRequest,
    current_user: User = Depends(get_current_user),
) -> DiagramRenderResponse:
    edges = [(e.source, e.target, e.type) for e in payload.edges]
    source = build_source(payload.kind, payload.labels, edges, payload.theme)
    if source is None:
        raise HTTPException(status_code=422, detail="The diagram data does not match the expected format.")
    svg = await render_svg(KROKI_TYPES[payload.kind], source)
    if svg is None:
        raise HTTPException(status_code=503, detail="Diagram renderer unavailable.")
    return DiagramRenderResponse(svg=svg)
