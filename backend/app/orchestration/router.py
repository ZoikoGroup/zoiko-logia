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
import logging
from contextlib import suppress

from datetime import datetime
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.core.rate_limit import limiter
from app.core.supabase_auth import verify_token
from app.domains.identity.models import User
from app.domains.identity.permissions import REVIEW_READ, REVIEW_RESOLVE
from app.domains.identity.rbac import get_current_user, require_permission
from app.orchestration import learned_answers, review
from app.orchestration.audit_events import audit_answer_feedback, audit_review_resolved
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse, TaskSpec, VisualizationTelemetryEvent
from app.orchestration.service import ask_kriton
from app.orchestration.visualization.frontend_telemetry import log_frontend_interaction
from app.orchestration.task_context import TASK_SPECS
from app.orchestration.workflow_planner import plan_workflow
from app.domains.identity.authorization import ASK, list_authorized_engagements
from app.core.config import get_settings
from app.domains.audit_ledger.event_envelope import (
    begin_audit_batch,
    commit_audit_batch,
    discard_audit_batch,
)
from app.orchestration.identifiers import abandon_idempotency, scope_idempotency_key, store_idempotency

router = APIRouter(prefix="/orchestration", tags=["Ask Kriton™ Orchestration"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.get("/task-specs", response_model=list[TaskSpec])
async def list_task_specs(
    current_user: User = Depends(get_current_user),
) -> list[TaskSpec]:
    """Publish the versioned F0 workflow contracts available to this client."""
    del current_user  # Authentication is the access boundary; specs are shared.
    return list(TASK_SPECS.values())


async def _abandon_after_failure(db: AsyncSession, idempotency_key: str, tenant_id: str) -> None:
    """Release the idempotency reservation after a failed request. The failure
    (a timeout mid-query, a dropped connection) can leave the session in a
    failed transaction; querying it then raised PendingRollbackError, which
    turned a clean 504/"please try again" into an unhandled 500. Roll back
    first, and never let the clean-up itself mask the original failure."""
    with suppress(Exception):
        await db.rollback()
    try:
        await abandon_idempotency(db, idempotency_key, tenant_id)
    except Exception:
        logger.warning("Could not release idempotency key after a failed request", exc_info=True)


async def _run_with_deadline(**kwargs) -> AskKritonResponse:
    if kwargs.get("idempotency_key"):
        request = kwargs.get("request")
        selection = request.task_context if request is not None else None
        engagement_id = selection.engagement_id if selection else None
        if request is not None and engagement_id is None:
            plan = plan_workflow(request)
            if plan.task_type != "general_question":
                candidates = await list_authorized_engagements(
                    kwargs["db"], actor_id=kwargs["actor_id"],
                    tenant_id=kwargs["tenant_id"], operation=ASK,
                )
                if len(candidates) == 1:
                    engagement_id = candidates[0].id
        kwargs["idempotency_key"] = scope_idempotency_key(
            kwargs["idempotency_key"], engagement_id, kwargs.get("actor_id")
        )
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
            await _abandon_after_failure(kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"])
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
            await _abandon_after_failure(kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"])
        raise
    except Exception:
        with suppress(ValueError, RuntimeError):
            discard_audit_batch(token)
        if kwargs.get("idempotency_key"):
            await _abandon_after_failure(kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"])
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


@router.post("/telemetry", status_code=204)
@limiter.limit("120/minute", key_func=_user_key)
async def post_visualization_telemetry(
    request: Request,
    payload: VisualizationTelemetryEvent,
    current_user: User = Depends(get_current_user),
) -> None:
    """Fire-and-forget visualization-interaction telemetry (view switched,
    exported, saved, render failed, ...) — see frontend_telemetry.py's
    docstring for why this logs structurally rather than writing through the
    audit ledger. A dropped/rejected event is not an error the client needs
    to see: always 204, even when the event/category isn't recognized."""
    log_frontend_interaction(
        event=payload.event,
        category=payload.category,
        visualization_id=payload.visualization_id,
        visualization_type=payload.visualization_type,
        renderer=payload.renderer,
        detail=payload.detail,
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
            logger.exception("Unhandled Ask Kriton stream failure")
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


# ── Review loop: feedback, review queue, gold cases (app/orchestration/review.py) ──

class AnswerFeedbackIn(BaseModel):
    query_id: str = Field(min_length=1, max_length=100)
    rating: Literal["up", "down"]
    reasons: list[str] = Field(default_factory=list, max_length=9)
    comment: str = Field(default="", max_length=2000)
    # The question and the answer the user saw: answers are not stored
    # server-side, and the reviewer needs both to correct it.
    question: str = Field(default="", max_length=4000)
    answer_text: str = Field(default="", max_length=20000)


class AnswerFeedbackOut(BaseModel):
    id: str
    rating: str
    review_case_id: Optional[str] = None
    # Self-learning (learned_answers.py): a verified answer kept on thumbs-up,
    # a background re-answer started on thumbs-down.
    learned: bool = False
    self_correction_started: bool = False


class ReviewCaseOut(BaseModel):
    id: str
    query_id: str
    question: str
    draft_answer: str
    reason: str
    risk_level: str
    source: str
    status: str
    created_at: datetime
    reviewer_decision: Optional[str] = None
    review_note: str = ""
    resolved_at: Optional[datetime] = None


class ReviewQueueOut(BaseModel):
    cases: list[ReviewCaseOut]
    counts: dict[str, int]


class ReviewResolutionIn(BaseModel):
    decision: Literal["approved", "corrected", "rejected", "needs_evidence"]
    note: str = Field(default="", max_length=4000)
    corrected_answer: str = Field(default="", max_length=20000)
    # Facts a correct answer must state ("£90,000", "VAT65A"); they become the
    # evaluation checks for this question.
    key_facts: list[str] = Field(default_factory=list, max_length=10)
    category: Literal["retrieval", "citation", "calculation", "jurisdiction", "freshness", "reasoning", "safety", "off_domain", "missing_context", "visualization"] = "reasoning"


class ReviewResolutionOut(BaseModel):
    case: ReviewCaseOut
    gold_case_id: Optional[str] = None


def _case_out(case) -> ReviewCaseOut:
    return ReviewCaseOut(
        id=case.id, query_id=case.query_id, question=case.query_text, draft_answer=case.draft_answer,
        reason=case.reason, risk_level=case.risk_level, source=case.source, status=case.status,
        created_at=case.created_at, reviewer_decision=case.reviewer_decision,
        review_note=case.review_note, resolved_at=case.resolved_at,
    )


@router.post("/feedback", response_model=AnswerFeedbackOut, status_code=201)
@limiter.limit("60/minute", key_func=_user_key)
async def post_answer_feedback(
    request: Request,
    payload: AnswerFeedbackIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnswerFeedbackOut:
    """Rate an answer. Kriton learns from it with no reviewer needed: a
    thumbs-up keeps a fact-checked answer for the same question next time, a
    thumbs-down retires it and re-answers the question in the background (see
    learned_answers.py). A thumbs-down also opens an optional review case."""
    try:
        feedback = await review.record_feedback(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id, query_id=payload.query_id,
            rating=payload.rating, reasons=payload.reasons, comment=payload.comment.strip(),
            question=payload.question, answer_text=payload.answer_text,
        )
    except review.ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await audit_answer_feedback(
        db, query_id=payload.query_id, tenant_id=current_user.tenant_id, actor_id=current_user.id,
        rating=feedback.rating, reasons=feedback.reasons, review_case_id=feedback.review_case_id,
    )
    learned = started = False
    try:
        if feedback.rating == "up":
            learned = await learned_answers.learn_from_upvote(
                db, tenant_id=current_user.tenant_id, user_id=current_user.id, query_id=payload.query_id,
            )
        elif feedback.rating == "down":
            started = await learned_answers.correct_after_downvote(
                db, _run_with_deadline, tenant_id=current_user.tenant_id, user_id=current_user.id,
                role=current_user.role, query_id=payload.query_id, reasons=feedback.reasons,
                comment=feedback.comment or "",
            )
    except Exception:  # noqa: BLE001 — the rating itself is already stored
        logger.exception("Learning from feedback on %s failed", payload.query_id)
        await db.rollback()
    return AnswerFeedbackOut(id=feedback.id, rating=feedback.rating, review_case_id=feedback.review_case_id,
                             learned=learned, self_correction_started=started)


@router.get("/review-cases", response_model=ReviewQueueOut)
async def get_review_cases(
    status_filter: Literal["open", "needs_evidence", "resolved", "all"] = "open",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(REVIEW_READ)),
) -> ReviewQueueOut:
    cases = await review.list_review_cases(
        db, tenant_id=current_user.tenant_id, status=status_filter, limit=max(1, min(limit, 200)),
    )
    return ReviewQueueOut(
        cases=[_case_out(case) for case in cases],
        counts=await review.review_counts(db, tenant_id=current_user.tenant_id),
    )


@router.post("/review-cases/{case_id}/resolve", response_model=ReviewResolutionOut)
async def resolve_review_case(
    case_id: str,
    payload: ReviewResolutionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(REVIEW_RESOLVE)),
) -> ReviewResolutionOut:
    """Approve, correct or reject. Approved and corrected answers become gold
    evaluation cases."""
    try:
        case, gold = await review.resolve_review_case(
            db, tenant_id=current_user.tenant_id, case_id=case_id, reviewer_id=current_user.id,
            decision=payload.decision, note=payload.note, corrected_answer=payload.corrected_answer,
            key_facts=payload.key_facts, category=payload.category,
        )
    except review.ReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT if "already" in str(exc) else 422, detail=str(exc))
    await audit_review_resolved(
        db, query_id=case.query_id, correlation_id=case.correlation_id, tenant_id=current_user.tenant_id,
        actor_id=current_user.id, review_case_id=case.id, decision=payload.decision,
        gold_case_id=gold.id if gold else None,
    )
    return ReviewResolutionOut(case=_case_out(case), gold_case_id=gold.id if gold else None)


@router.get("/review-cases/{case_id}/evidence")
async def get_review_evidence(
    case_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(REVIEW_READ)),
) -> list[dict]:
    try:
        return await review.review_evidence(db, tenant_id=current_user.tenant_id, case_id=case_id)
    except review.ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
