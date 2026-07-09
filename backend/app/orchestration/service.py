"""
Ask Kriton orchestration — retrieve -> classify -> compose -> audit.

Wires together the four domains built in Wave 2:
  retrieve  -> source_library  (real approved sources, not a mock bundle)
  classify  -> risk_safety     (the existing ML risk classifier + policy engine)
  compose   -> model_gateway   (approved prompt + provider adapter)
  audit     -> audit_ledger    (every step chained under one query_id)

Every event below shares correlation_id = the classifier's query_id, so the
whole flow is replayable from a single ID via GET /audit/replay/{query_id}.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway import service as model_gateway_service
from app.domains.risk_safety import service as risk_safety_service
from app.domains.risk_safety.schemas import ClassifyRequest
from app.orchestration.compose import build_grounded_input, select_prompt
from app.orchestration.retrieve import build_source_bundle
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse, ComposedAnswer


async def ask_kriton(
    db: AsyncSession,
    sync_db: Session,
    *,
    actor_id: str,
    tenant_id: str,
    role: str,
    request: AskKritonRequest,
) -> AskKritonResponse:
    # 1. Retrieve
    bundle = await build_source_bundle(db, query=request.query, jurisdiction=request.jurisdiction)

    # 2. Classify — the safety engine is the single source of truth on
    # whether generation may proceed at all.
    classify_request = ClassifyRequest(
        query=request.query,
        user_id=actor_id,
        role=role,
        tenant_id=tenant_id,
        jurisdiction=request.jurisdiction,
        mode=request.mode,
        source_confidence=request.source_confidence or bundle.confidence_state,
        pre_bundle_state=request.pre_bundle_state or "OK",
        privacy_class=request.privacy_class or "NONE",
    )
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

    # 3. Compose — only when the safety engine actually cleared it for
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
            answer = ComposedAnswer(prompt_id=prompt_row.id, prompt_name=prompt_row.name, output_text=output_text)
            outcome = "ANSWERED"
    else:
        outcome = "REFUSED"

    # 4. Audit — a single top-level event summarizing the whole flow, on top
    # of the per-step events each domain already recorded.
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
