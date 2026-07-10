"""
Ask Kriton orchestration — validate -> pre-screen -> retrieve -> classify ->
compose -> validate output -> audit.

Wires together the four domains built in Wave 2:
  retrieve  -> source_library  (real approved sources, not a mock bundle)
  classify  -> risk_safety     (the existing ML risk classifier + policy engine)
  compose   -> model_gateway   (approved prompt + provider adapter)
  audit     -> audit_ledger    (every step chained under one query_id)

Every event below shares correlation_id = the classifier's query_id, so the
whole flow is replayable from a single ID via GET /audit/replay/{query_id}.

Pipeline order matters: pre_screen() (L0/L1 hard-blocks — privacy, license,
academic integrity, control bypass, jailbreak attempts) runs BEFORE
retrieval. A pre-screen hit skips retrieval and full classification
entirely — an attempted prompt injection never touches the source register.
Full classification (L2, which needs retrieval's source confidence) only
runs once pre-screen has passed.
"""
from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway import service as model_gateway_service
from app.domains.orchestration_state.models import IdempotencyRecord
from app.domains.risk_safety import service as risk_safety_service
from app.domains.risk_safety.schemas import ClassifyRequest, SafetyDecision
from app.orchestration.compose import build_grounded_input, select_prompt
from app.orchestration.retrieve import build_source_bundle
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse, ComposedAnswer


def _new_query_id() -> str:
    return f"qry-{uuid.uuid4().hex[:12]}"


def get_idempotent_response(sync_db: Session, *, tenant_id: str, idempotency_key: str) -> dict | None:
    """Look up a stored response for a prior request with the same key. Scoped
    by tenant so one tenant can never replay another tenant's cached answer."""
    record = (
        sync_db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    return record.response_json if record else None


def store_idempotent_response(sync_db: Session, *, tenant_id: str, idempotency_key: str, response: dict) -> None:
    sync_db.add(IdempotencyRecord(tenant_id=tenant_id, idempotency_key=idempotency_key, response_json=response))
    try:
        sync_db.commit()
    except IntegrityError:
        # Two concurrent requests raced on the same key — the other one won,
        # so this request's own response is simply not the cached one.
        sync_db.rollback()


def _route_to_outcome(route: str) -> str:
    if route == "HUMAN_REVIEW":
        return "HUMAN_REVIEW"
    if route == "CLARIFICATION":
        return "CLARIFICATION"
    return "REFUSED"


async def ask_kriton(
    db: AsyncSession,
    sync_db: Session,
    *,
    actor_id: str,
    tenant_id: str,
    role: str,
    request: AskKritonRequest,
) -> AskKritonResponse:
    # Phase 2 — schema validation. An empty query never reaches pre-screen,
    # retrieval, or classification at all.
    if not request.query or not request.query.strip():
        query_id = _new_query_id()
        await record_event_async(
            db,
            event_name="request_rejected",
            emitting_service="orchestration",
            subject_type="query",
            subject_id=query_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            correlation_id=query_id,
            classification="INTERNAL",
            replay_relevance="REQUIRED",
            payload={"reason": "empty_query"},
        )
        return AskKritonResponse(
            query_id=query_id,
            outcome="REJECTED",
            safety=SafetyDecision(allowed=False, risk_level="LOW", route="REJECTED", query_id=query_id),
            source_bundle=None,
            answer=None,
        )

    classify_request = ClassifyRequest(
        query=request.query,
        user_id=actor_id,
        role=role,
        tenant_id=tenant_id,
        jurisdiction=request.jurisdiction,
        mode=request.mode,
        source_confidence=request.source_confidence or "HIGH_CONFIDENCE",
        pre_bundle_state=request.pre_bundle_state or "OK",
        privacy_class=request.privacy_class or "NONE",
    )

    # Phase 2 — safety pre-screen. Hard stop: no retrieval, no full
    # classification, no model call if this hits.
    pre_screen_decision = risk_safety_service.pre_screen(classify_request, db=sync_db)
    if pre_screen_decision is not None:
        query_id = pre_screen_decision.query_id or "qry-unknown"
        await record_event_async(
            db,
            event_name="pre_screen_rejected",
            emitting_service="orchestration",
            subject_type="query",
            subject_id=query_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            correlation_id=query_id,
            classification="INTERNAL",
            replay_relevance="REQUIRED",
            payload={
                "route": pre_screen_decision.route,
                "risk_level": pre_screen_decision.risk_level,
                "restricted_sub_class": pre_screen_decision.restricted_sub_class,
                "rules_applied": pre_screen_decision.rules_applied,
            },
        )
        return AskKritonResponse(
            query_id=query_id,
            outcome=_route_to_outcome(pre_screen_decision.route),
            safety=pre_screen_decision,
            source_bundle=None,
            answer=None,
        )

    # Phase 3 — Retrieve (only reached once pre-screen has passed)
    bundle = await build_source_bundle(db, query=request.query, jurisdiction=request.jurisdiction)
    classify_request.source_confidence = request.source_confidence or bundle.confidence_state

    # Phase 4 — Classify (L2). The safety engine is the single source of
    # truth on whether generation may proceed at all.
    decision = risk_safety_service.evaluate(classify_request, db=sync_db)
    query_id = decision.query_id or "qry-unknown"

    await record_event_async(
        db,
        event_name="source_bundle_created",
        emitting_service="orchestration",
        subject_type="query",
        subject_id=query_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        correlation_id=query_id,
        classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={
            "bundle_id": bundle.bundle_id,
            "retrieval_run_id": bundle.retrieval_run_id,
            "category": bundle.category,
            "confidence_state": bundle.confidence_state,
            "source_ids": [s.id for s in bundle.sources],
        },
    )

    # Phase 5 — Compose — only when the safety engine actually cleared it for
    # generation. A refusal/human-review/clarification route never reaches
    # the model gateway.
    answer: ComposedAnswer | None = None
    if decision.route == "HUMAN_REVIEW":
        outcome = "HUMAN_REVIEW"
    elif decision.route == "CLARIFICATION":
        outcome = "CLARIFICATION"
    elif decision.allowed and decision.route == "LLM":
        prompt = await select_prompt(db, request.mode)
        if prompt is None:
            outcome = "COMPOSE_UNAVAILABLE"
        else:
            grounded_input = build_grounded_input(request.query, bundle)
            prompt_row, output_text = await model_gateway_service.run_test_prompt(
                db, prompt.id, grounded_input, actor_id, tenant_id, correlation_id=query_id
            )

            # Phase 6 — Post-composition validation. An answer that fails
            # this must never reach the user, no matter how it was routed.
            validation = risk_safety_service.validate_output(output_text, db=sync_db, answer_id=query_id)
            if not validation["is_safe"]:
                await record_event_async(
                    db,
                    event_name="composition_rejected",
                    emitting_service="orchestration",
                    subject_type="query",
                    subject_id=query_id,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    correlation_id=query_id,
                    classification="INTERNAL",
                    replay_relevance="REQUIRED",
                    payload={
                        "prompt_id": prompt_row.id,
                        "violations": validation["violations"],
                    },
                )
                outcome = "HUMAN_REVIEW"
            else:
                answer = ComposedAnswer(
                    prompt_id=prompt_row.id, prompt_name=prompt_row.name, output_text=validation["cleaned_text"]
                )
                outcome = "ANSWERED"
    else:
        outcome = "REFUSED"

    # Phase 9 — Audit — a single top-level event summarizing the whole flow,
    # on top of the per-step events each domain already recorded.
    await record_event_async(
        db,
        event_name="ask_kriton_flow_completed",
        emitting_service="orchestration",
        subject_type="query",
        subject_id=query_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        correlation_id=query_id,
        classification="INTERNAL",
        replay_relevance="SUPPORTING",
        payload={
            "outcome": outcome,
            "risk_level": decision.risk_level,
            "route": decision.route,
            "source_bundle_id": bundle.bundle_id,
            "model_run": answer is not None,
        },
    )

    return AskKritonResponse(
        query_id=query_id,
        outcome=outcome,
        safety=decision,
        source_bundle=bundle,
        answer=answer,
    )
