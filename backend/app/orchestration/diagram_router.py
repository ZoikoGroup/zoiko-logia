"""
Server-side diagram rendering through a self-hosted Kroki service.

Only the swimlane diagram uses this today. The browser sends the node labels
of a swimlane spec it already received; this endpoint re-validates them,
generates the PlantUML itself (swimlane.py) and returns Kroki's SVG. The
browser never sends diagram source, so the endpoint cannot be used to render
arbitrary PlantUML.

Kroki is optional. When it is not running, this returns 503 and the frontend
draws the ordinary process flow from the same labels instead.

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
from app.orchestration.router import _user_key
from app.orchestration.swimlane import build_plantuml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagrams", tags=["Diagram Rendering"])

_KROKI_TIMEOUT_SECONDS = 8.0
_MAX_SVG_BYTES = 2_000_000


def _kroki_url() -> str:
    return os.getenv("KROKI_URL", "http://localhost:8300").rstrip("/")


class SwimlaneRenderRequest(BaseModel):
    labels: list[str] = Field(min_length=2, max_length=40)
    theme: Literal["light", "dark"] = "light"


class SwimlaneRenderResponse(BaseModel):
    svg: str


async def _post_to_kroki(client: httpx.AsyncClient, source: str) -> httpx.Response:
    return await client.post(
        f"{_kroki_url()}/plantuml/svg",
        content=source.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )


async def render_plantuml_svg(source: str, client: httpx.AsyncClient | None = None) -> str | None:
    """SVG from Kroki, or None when Kroki is unreachable or answers with
    anything that is not an SVG document."""
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=_KROKI_TIMEOUT_SECONDS) as own_client:
                response = await _post_to_kroki(own_client, source)
        else:
            response = await _post_to_kroki(client, source)
    except httpx.HTTPError:
        logger.warning("Kroki unreachable at %s", _kroki_url())
        return None
    if response.status_code != 200 or len(response.content) > _MAX_SVG_BYTES:
        logger.warning("Kroki returned status=%s size=%s", response.status_code, len(response.content))
        return None
    svg = response.text
    return svg if "<svg" in svg[:2000] else None


@router.post("/swimlane", response_model=SwimlaneRenderResponse)
@limiter.limit("60/minute", key_func=_user_key)
async def post_swimlane(
    request: Request,
    payload: SwimlaneRenderRequest,
    current_user: User = Depends(get_current_user),
) -> SwimlaneRenderResponse:
    source = build_plantuml(payload.labels, payload.theme)
    if source is None:
        raise HTTPException(status_code=422, detail="Every step must be written as 'Role: Step'.")
    svg = await render_plantuml_svg(source)
    if svg is None:
        raise HTTPException(status_code=503, detail="Diagram renderer unavailable.")
    return SwimlaneRenderResponse(svg=svg)
