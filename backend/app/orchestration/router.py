"""
Ask Kriton™ REST API — ZL-ENG-02 §4.

POST /api/v1/orchestration/ask
Required header: Idempotency-Key: <client-generated-key>

Controls:
  - Authentication context (tenant_id, user_id) resolved from auth; never trusted from body.
  - Idempotency: duplicate Idempotency-Key returns original result without re-execution.
  - Rate limiting: enforced before retrieval or model work.
"""
from __future__ import annotations
import asyncio
import json
from contextlib import suppress

from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.core.rate_limit import limiter
from app.core.supabase_auth import verify_token
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse, TaskSpec
from app.orchestration.service import ask_kriton
from app.orchestration.task_context import TASK_SPECS
from app.core.config import get_settings
from app.domains.audit_ledger.event_envelope import (
    begin_audit_batch,
    commit_audit_batch,
    discard_audit_batch,
)
from app.orchestration.identifiers import abandon_idempotency, scope_idempotency_key, store_idempotency

router = APIRouter(prefix="/orchestration", tags=["Ask Kriton™ Orchestration"])
settings = get_settings()


@router.get("/task-specs", response_model=list[TaskSpec])
async def list_task_specs(
    current_user: User = Depends(get_current_user),
) -> list[TaskSpec]:
    """Publish the versioned F0 workflow contracts available to this client."""
    del current_user  # Authentication is the access boundary; specs are shared.
    return list(TASK_SPECS.values())


async def _run_with_deadline(**kwargs) -> AskKritonResponse:
    if kwargs.get("idempotency_key"):
        request = kwargs.get("request")
        selection = request.task_context if request is not None else None
        engagement_id = selection.engagement_id if selection else None
        kwargs["idempotency_key"] = scope_idempotency_key(kwargs["idempotency_key"], engagement_id)
    token = begin_audit_batch()
    try:
        async with asyncio.timeout(settings.ASK_KRITON_TIMEOUT_SECONDS):
            result = await ask_kriton(**kwargs)
            if kwargs.get("idempotency_key"):
                await store_idempotency(
                    kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"],
                    result.model_dump(mode="json"),
                )
            # Audit events and the terminal idempotency response are committed
            # together before the response can leave the service.
            await commit_audit_batch(kwargs["db"], token)
            return result
    except TimeoutError as exc:
        with suppress(ValueError, RuntimeError):
            discard_audit_batch(token)
        if kwargs.get("idempotency_key"):
            await abandon_idempotency(
                kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"]
            )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Kriton could not complete the response within the processing deadline.",
        ) from exc
    except HTTPException as exc:
        with suppress(ValueError, RuntimeError):
            discard_audit_batch(token)
        # 409 means another worker owns the durable reservation. Never delete
        # that worker's row while it is still processing.
        if exc.status_code != status.HTTP_409_CONFLICT and kwargs.get("idempotency_key"):
            await abandon_idempotency(
                kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"]
            )
        raise
    except Exception:
        with suppress(ValueError, RuntimeError):
            discard_audit_batch(token)
        if kwargs.get("idempotency_key"):
            await abandon_idempotency(
                kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"]
            )
        raise


def _user_key(request: Request) -> str:
    """Rate-limit key: the authenticated user's id, not IP — this is an
    authenticated API and a shared NAT/office IP must not share one bucket."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    claims = verify_token(token) if token else None
    return claims.sub if claims else "anonymous"


@router.post("/ask", response_model=AskKritonResponse)
@limiter.limit("30/minute", key_func=_user_key)
async def post_ask(
    request: Request,
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> AskKritonResponse:
    """
    Submit a query to Kriton™. Returns a deterministic route-driven response contract.

    The response outcome/route drives frontend rendering — do not infer state from answer text.
    Internal hashes, policy internals and audit chain material are not exposed (§12).
    """
    return await _run_with_deadline(
        db=db,
        sync_db=sync_db,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        request=payload,
        idempotency_key=idempotency_key,
        clarification_cycle=payload.clarification_cycle,
        conversation_id=payload.conversation_id,
    )


@router.post("/ask/stream")
@limiter.limit("30/minute", key_func=_user_key)
async def post_ask_stream(
    request: Request,
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> StreamingResponse:
    """Stream progress as newline-delimited JSON, followed by one result.

    The answer itself remains atomic: only a fully validated and audited result
    is exposed. Heartbeats keep buffering proxies and idle connections active.
    """
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress(stage: str, message: str) -> None:
        await queue.put({"type": "progress", "stage": stage, "message": message})

    async def execute() -> None:
        try:
            result = await _run_with_deadline(
                db=db,
                sync_db=sync_db,
                actor_id=current_user.id,
                tenant_id=current_user.tenant_id,
                role=current_user.role,
                request=payload,
                idempotency_key=idempotency_key,
                clarification_cycle=payload.clarification_cycle,
                conversation_id=payload.conversation_id,
                progress=progress,
            )
            await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except HTTPException as exc:
            await queue.put({"type": "error", "status": exc.status_code, "message": exc.detail})
        except asyncio.CancelledError:
            raise
        except Exception:
            await queue.put({"type": "error", "status": 500, "message": "Kriton could not complete this request."})

    task = asyncio.create_task(execute())

    async def events():
        try:
            yield json.dumps({"type": "progress", "stage": "accepted", "message": "Request accepted"}) + "\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                except TimeoutError:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
                    continue
                yield json.dumps(event) + "\n"
                if event["type"] in {"result", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
