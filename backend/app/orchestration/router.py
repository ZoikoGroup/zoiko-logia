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
import time
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
from app.orchestration import review, workflow_state
from app.orchestration.audit_events import audit_answer_feedback, audit_review_resolved, audit_review_stage
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
    record_event_async,
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


CLEANUP_SECONDS = 5.0


async def _abandon_after_failure(db: AsyncSession, idempotency_key: str, tenant_id: str) -> None:
    """Release the idempotency reservation after a failed request. The failure
    (a timeout mid-query, a dropped connection) can leave the session in a
    failed transaction; querying it then raised PendingRollbackError, which
    turned a clean 504/"please try again" into an unhandled 500. Roll back
    first, and never let the clean-up itself mask the original failure."""
    async def clean_up() -> None:
        with suppress(Exception):
            await db.rollback()
        await abandon_idempotency(db, idempotency_key, tenant_id)

    # Bounded: after a deadline cancelled a query mid-flight the connection is
    # often broken, and reconnecting to release the key kept the user waiting
    # ~15 s past the deadline (504 at 120.5 s for a 105 s limit). The browser
    # uses a fresh key per attempt, so an unreleased reservation blocks nothing.
    try:
        await asyncio.wait_for(clean_up(), timeout=CLEANUP_SECONDS)
    except Exception:
        logger.warning("Could not release idempotency key after a failed request", exc_info=True)


def answer_receipt(result, run: "workflow_state.WorkflowRun") -> dict:
    """AnswerReceipt (ZL-ENG-AGT-01 App. B3) from the response and its run."""
    from app.orchestration.routing_matrix import POLICY_VERSION
    answer = getattr(result, "answer", None)
    safety = getattr(result, "safety", None)
    return {
        "request_id": result.query_id,
        "route": getattr(result, "route", None),
        "risk": getattr(safety, "risk_level", None),
        "outcome": getattr(result, "outcome", None),
        # complete | partial | none — the same value the page shows and
        # response_finalised records (service.answer_completeness).
        "completeness": getattr(answer, "completeness", None) if answer else None,
        "citation_ids": [c.ref_id for c in answer.citations] if answer else [],
        "calculation_ids": list(run.calculation_ids),
        "citation_spans": dict(run.citation_spans),
        "review_required": getattr(result, "outcome", None) == "escalated",
        "policy_version": POLICY_VERSION,
        "workflow_final_state": run.state.value,
    }


async def _record_cancellation(kwargs: dict, run: "workflow_state.WorkflowRun") -> None:
    """A durable record that a request was cancelled, on its own session (the
    request's session may be mid-query). Never raises."""
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            await record_event_async(
                session, tenant_id=kwargs["tenant_id"], event_name="request_cancelled",
                emitting_service="orchestration", actor_id=kwargs.get("actor_id"),
                subject_type="request", subject_id=kwargs.get("idempotency_key") or "unkeyed",
                payload=run.summary(), replay_relevance="SUPPORTING",
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — cancellation must still propagate
        logger.warning("Could not record a cancelled Ask Kriton request")


# One line per question, by the browser's request id (its Idempotency-Key):
# received → finished / failed (with a category) / cancelled. Written to
# backend/logs/kriton-requests.log and the terminal (app/main.py).
request_log = logging.getLogger("kriton.requests")


def failure_category(status: int | None, exc: BaseException | None = None) -> str:
    if status is not None:
        return {504: "deadline", 503: "database_or_network", 429: "rate_limit", 409: "duplicate_in_progress",
                422: "invalid_request", 401: "auth", 403: "auth"}.get(status, f"http_{status}")
    if exc is not None and (isinstance(exc, (TimeoutError, OSError))
                            or type(exc).__module__.startswith(("asyncpg", "sqlalchemy"))):
        return "database_or_network"
    return "unhandled_error"


def stream_deadline(query: str) -> float:
    """Pasted material gets the long deadline; a question keeps the normal one."""
    from app.orchestration.websearch import is_pasted_material
    settings = get_settings()
    if is_pasted_material(query):
        return settings.ASK_KRITON_LONG_INPUT_TIMEOUT_SECONDS
    return settings.ASK_KRITON_TIMEOUT_SECONDS


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
    run = workflow_state.WorkflowRun()
    run_token = workflow_state.current_run.set(run)
    try:
        async with asyncio.timeout(kwargs.get("deadline_seconds") or settings.ASK_KRITON_TIMEOUT_SECONDS):
            result = await ask_kriton(**kwargs)
            failed = bool(result.next_action and getattr(result.next_action, "type", "") == "composition_failed")
            run.finish(released=not failed)
            # The request's state path is committed with its other audit
            # events, before the response leaves (ZL-ENG-AGT-01 §05.2).
            await record_event_async(
                kwargs["db"], tenant_id=kwargs["tenant_id"], event_name="workflow_completed",
                emitting_service="orchestration", actor_id=kwargs.get("actor_id"),
                subject_type="query", subject_id=result.query_id, correlation_id=result.query_id,
                payload=run.summary(), replay_relevance="REQUIRED",
            )
            # The answer receipt (App. B3): what was released and on what basis,
            # committed with the audit batch before the response leaves.
            receipt = await record_event_async(
                kwargs["db"], tenant_id=kwargs["tenant_id"], event_name="answer_receipt",
                emitting_service="orchestration", actor_id=kwargs.get("actor_id"),
                subject_type="query", subject_id=result.query_id, correlation_id=result.query_id,
                payload=answer_receipt(result, run), replay_relevance="REQUIRED",
            )
            if receipt is not None and getattr(result, "audit_reference", None) is not None:
                result = result.model_copy(update={"audit_reference": result.audit_reference.model_copy(
                    update={"receipt_id": receipt.id})})
            if kwargs.get("idempotency_key"):
                await store_idempotency(
                    kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"],
                    result.model_dump(mode="json"),
                )
            # Audit events and the terminal idempotency response are committed
            # together before the response can leave the service.
            try:
                await commit_audit_batch(kwargs["db"], token)
            except Exception as exc:
                # No durable audit record, no answer (ZL-ENG-AGT-01 App. D):
                # withhold it, alert operations, and tell the user plainly.
                logger.critical(
                    "AUDIT_COMMIT_FAILED: answer withheld for request %s (%s)",
                    result.query_id, type(exc).__name__,
                )
                with suppress(Exception):
                    await kwargs["db"].rollback()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(f"Kriton could not record this answer, so it was withheld "
                            f"(request {result.query_id}). Please try again."),
                ) from exc
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
    except asyncio.CancelledError:
        # The user left (stream closed) or the server is stopping. The
        # unfinished batch is dropped, but the cancellation itself is kept.
        with suppress(ValueError, RuntimeError):
            discard_audit_batch(token)
        run.advance(workflow_state.WorkflowState.CANCELLED)
        await asyncio.shield(_record_cancellation(kwargs, run))
        raise
    except Exception:
        with suppress(ValueError, RuntimeError):
            discard_audit_batch(token)
        if kwargs.get("idempotency_key"):
            await _abandon_after_failure(kwargs["db"], kwargs["idempotency_key"], kwargs["tenant_id"])
        raise
    finally:
        workflow_state.current_run.reset(run_token)


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

    request_id = idempotency_key or "none"
    started = time.monotonic()
    request_log.info("ask received id=%s chars=%s history=%s", request_id, len(payload.query),
                     len(payload.conversation_history))

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
                deadline_seconds=stream_deadline(payload.query),
            )
            failed = bool(result.next_action and result.next_action.type == "composition_failed")
            request_log.info("ask %s id=%s query=%s outcome=%s route=%s seconds=%.1f",
                             "failed category=model_provider" if failed else "finished", request_id,
                             result.query_id, result.outcome, result.route, time.monotonic() - started)
            await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except HTTPException as exc:
            # A deadline (504) or a withheld answer (503) was not logged at
            # all; the user saw only "unavailable" and the cause was lost.
            request_log.warning("ask failed id=%s category=%s status=%s seconds=%.1f detail=%s", request_id,
                                failure_category(exc.status_code), exc.status_code,
                                time.monotonic() - started, exc.detail)
            await queue.put({"type": "error", "status": exc.status_code, "message": exc.detail})
        except asyncio.CancelledError:
            request_log.info("ask cancelled id=%s seconds=%.1f", request_id, time.monotonic() - started)
            raise
        except Exception as exc:
            category = failure_category(None, exc)
            logger.exception("Unhandled Ask Kriton stream failure (id=%s)", request_id)
            request_log.error("ask failed id=%s category=%s error=%s seconds=%.1f", request_id, category,
                              type(exc).__name__, time.monotonic() - started)
            await queue.put({"type": "error", "status": 503 if category == "database_or_network" else 500,
                             "message": "Kriton's database or network is temporarily unavailable."
                             if category == "database_or_network" else "Kriton could not complete this request."})

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
    # Always False. Kept so older clients still parse the response: feedback
    # no longer saves answers or starts automatic re-answers (ZL-ENG-AGT-01 §08).
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
    """Rate an answer. A rating is a signal, never knowledge (ZL-ENG-AGT-01
    §08): it is stored and audited, and a thumbs-down opens a review case for a
    reviewer. Nothing is learned, saved for reuse or re-answered automatically;
    only a reviewer's decision on the case can change a future answer."""
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
    return AnswerFeedbackOut(id=feedback.id, rating=feedback.rating, review_case_id=feedback.review_case_id)


@router.get("/review-cases", response_model=ReviewQueueOut)
async def get_review_cases(
    status_filter: Literal["open", "triaged", "needs_evidence", "resolved", "released", "all"] = "open",
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


class ReviewStageIn(BaseModel):
    note: str = Field(default="", max_length=4000)


@router.post("/review-cases/{case_id}/triage", response_model=ReviewCaseOut)
async def triage_review_case(
    case_id: str,
    payload: ReviewStageIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(REVIEW_RESOLVE)),
) -> ReviewCaseOut:
    """received → triaged (ZL-ENG-AGT-01 §08.3)."""
    try:
        case = await review.triage_review_case(db, tenant_id=current_user.tenant_id, case_id=case_id, note=payload.note)
    except review.ReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await audit_review_stage(db, case=case, tenant_id=current_user.tenant_id, actor_id=current_user.id,
                             stage="triaged", note=payload.note)
    return _case_out(case)


@router.post("/review-cases/{case_id}/release", response_model=ReviewResolutionOut)
async def release_reviewed_answer(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(REVIEW_RESOLVE)),
) -> ReviewResolutionOut:
    """Re-test an approved answer and release it for reuse; a different
    reviewer from the approver must do this (ZL-ENG-AGT-01 §08.3)."""
    try:
        case, gold = await review.release_reviewed_answer(
            db, tenant_id=current_user.tenant_id, case_id=case_id, releaser_id=current_user.id,
        )
    except review.ReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await audit_review_stage(db, case=case, tenant_id=current_user.tenant_id, actor_id=current_user.id,
                             stage="released", note="re-test passed", gold_case_id=gold.id)
    return ReviewResolutionOut(case=_case_out(case), gold_case_id=gold.id)


@router.get("/review-cases/{case_id}/evidence")
async def get_review_evidence(
    case_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(REVIEW_READ)),
) -> list[dict]:
    try:
        return await review.review_evidence(db, tenant_id=current_user.tenant_id, case_id=case_id)
    except review.ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
