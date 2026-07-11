"""
Ask Kriton™ orchestration service — ZL-ENG-02 §3 canonical 8-step flow.

Canonical flow:
  1. Generate identifiers
  2. Validate request
  3. Pre-screen safety (BEFORE retrieval) — Release Gate RG-01
  4. Retrieve SourceBundle (Massarius™ keyword_mvp retrieval layer)
  5. Classify risk + resolve route from versioned policy matrix
  6. Execute deterministic route
  7. Post-composition validation — Release Gate RG-03
  8. Finalise response + audit (BEFORE response is returned) — Release Gate RG-04

Principles (§2):
  - Policy before model: route decision controls whether model gateway may run.
  - Audit before response: no answer returned without durable audit trail.
  - No unsupported answering: safe query with insufficient sources must not answer from model knowledge.
  - Deterministic frontend: frontend renders from route/outcome, not by parsing answer text.
"""
from __future__ import annotations

import hashlib
import time
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.orchestration.identifiers import (
    generate_query_id, generate_correlation_id,
    generate_audit_chain_id,
    check_idempotency, store_idempotency,
)
from app.orchestration.prescreen import run_prescreen
from app.orchestration.retrieve import build_source_bundle
from app.orchestration.routing_matrix import (
    map_safety_confidence,
    ROUTE_LLM, ROUTE_REFUSAL, ROUTE_CLARIFICATION,
    ROUTE_HUMAN_REVIEW, ROUTE_SECURITY_INCIDENT, ROUTE_REJECTED,
    CONF_INSUFFICIENT,
)
from app.orchestration.composition_validator import build_validated_disclaimer
from app.orchestration.persisted_objects import create_review_case, create_security_incident_sync
from app.orchestration.schemas import (
    AskKritonRequest, AskKritonResponse,
    ComposedAnswer, SourceCitation, SafetyState, NextAction, AuditReference,
)
from app.orchestration.audit_events import (
    audit_query_received, audit_request_validated, audit_request_rejected,
    audit_prescreen_completed, audit_retrieval_started, audit_retrieval_completed,
    audit_retrieval_failed, audit_risk_classified, audit_route_selected,
    audit_composition_started, audit_composition_completed, audit_composition_failed,
    audit_composition_rejected, audit_human_review_created, audit_refusal_returned,
    audit_clarification_returned, audit_security_incident_recorded,
    audit_response_finalised, audit_response_returned,
    audit_licence_prefilter_completed, audit_licence_denied,
    audit_bundle_built, audit_validation_completed,
)
from app.domains.risk_safety.schemas import ClassifyRequest
from app.domains.model_gateway import service as model_gateway_service
from app.orchestration.compose import select_prompt
from app.domains.rag.retrieval import retrieve_documents
from app.domains.rag.reranker import Reranker
from app.domains.rag.context_fit import build_grounded_context

# Massarius™ retrieval and evidence subsystem — Phase 1 control modules
# (ZL-ENG-03). These wrap/replace the inline licence filtering, bundle
# construction, and answer validation that used to happen ad hoc in this
# file; retrieve.py itself is unchanged — its output is now treated as
# preliminary retrieval-layer output that these modules gate and finalise.
from app.domains.massarius import bundle_builder, license_gate
from app.domains.massarius import risk_safety as massarius_risk_safety
from app.domains.massarius.answer_validator import validate_answer
from app.domains.massarius.policy_matrix import resolve_policy

_reranker = Reranker(top_n=5)


def _hash_query(query: str) -> str:
    """Hash query text — raw query text is not stored in plaintext per §13 RG-04."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:32]


async def ask_kriton(
    db: AsyncSession,
    sync_db: Session,
    *,
    actor_id: str,
    tenant_id: str,
    role: str,
    request: AskKritonRequest,
    idempotency_key: Optional[str] = None,
    clarification_cycle: int = 0,
) -> AskKritonResponse:

    start_time = time.monotonic()

    # ── Idempotency check ─────────────────────────────────────────────────────
    if idempotency_key:
        cached = check_idempotency(idempotency_key, tenant_id)
        if cached is not None:
            return AskKritonResponse(**cached)

    # ── Step 1: Generate identifiers (§5) ────────────────────────────────────
    query_id = generate_query_id()
    correlation_id = generate_correlation_id()
    audit_chain_id = generate_audit_chain_id()
    query_hash = _hash_query(request.query)

    # Audit: query_received — first event, before any processing
    await audit_query_received(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, query_hash=query_hash,
    )

    # ── Step 2: Request validation (§6) ──────────────────────────────────────
    if not request.query or not request.query.strip():
        await audit_request_rejected(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, reason="Empty query text",
        )
        return _make_rejected_response(query_id, correlation_id, audit_chain_id, "Empty query text")

    await audit_request_validated(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
    )

    # ── Step 3: Pre-screen safety BEFORE retrieval (§6, RG-01) ───────────────
    prescreen = run_prescreen(request.query)
    await audit_prescreen_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, passed=prescreen.passed,
        trigger=prescreen.trigger,
    )

    if not prescreen.passed:
        # Create persisted incident object (§11.2) before returning
        incident = create_security_incident_sync(
            sync_db,
            query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id,
            trigger=prescreen.trigger or "unknown",
            trigger_detail=prescreen.trigger_detail or "",
        )
        await audit_security_incident_recorded(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, incident_id=incident["incident_id"],
            trigger=incident["trigger"], evidence_reference=incident["evidence_reference"],
        )
        response = _make_security_incident_response(
            query_id, correlation_id, audit_chain_id, prescreen.trigger or "security_policy"
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=response.route, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    # ── Step 4: Retrieve SourceBundle (Massarius™ keyword_mvp layer) (§7) ────
    await audit_retrieval_started(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
    )
    try:
        preliminary_bundle = await build_source_bundle(
            db, query=request.query, jurisdiction=request.jurisdiction, tenant_id=tenant_id
        )
        await audit_retrieval_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            source_bundle_id=preliminary_bundle.source_bundle_id,
            confidence_state=preliminary_bundle.confidence_state,
            eligible_count=preliminary_bundle.eligible_source_count,
        )

        # ── Massarius™ Checkpoint A/B + bundle_builder (ZL-ENG-03 §5) ────────
        # retrieve.py's own bundle is treated as preliminary/keyword_mvp
        # output; license_gate.py re-verifies eligibility of what it
        # returned and resolves per-source display states, and
        # bundle_builder.py is the sole producer of the final, frozen
        # SourceBundle everything downstream actually uses.
        licence_result = await license_gate.check_eligibility(
            db, preliminary_bundle.sources, tenant_id=tenant_id,
        )
        await audit_licence_prefilter_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            eligible_count=len(licence_result.eligible),
            excluded_count=len(licence_result.excluded),
        )
        if licence_result.excluded:
            await audit_licence_denied(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
                checkpoint="A", source_ids=[s.id for s in licence_result.excluded],
                reason_code=";".join(sorted(set(licence_result.exclusion_reasons.values()))) or "unknown",
            )

        source_bundle = bundle_builder.build_bundle(preliminary_bundle, licence_result)
        await audit_bundle_built(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            source_bundle_id=source_bundle.source_bundle_id,
            confidence_state=source_bundle.confidence_state,
            index_version=source_bundle.index_version,
        )
    except Exception as exc:
        await audit_retrieval_failed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, error=str(exc),
        )
        source_bundle = None

    # ── Step 5: Classify risk (after bundle_builder.py, ZL-ENG-03 §5.6) +
    # resolve route from versioned policy matrix (§8) ────────────────────────
    # Override confidence state with playground param if provided
    effective_confidence = (
        map_safety_confidence(request.source_confidence)
        if request.source_confidence
        else (source_bundle.confidence_state if source_bundle else CONF_INSUFFICIENT)
    )

    classify_request = ClassifyRequest(
        query=request.query,
        user_id=actor_id,
        role=role,
        tenant_id=tenant_id,
        jurisdiction=request.jurisdiction,
        mode=request.mode,
        source_confidence=request.source_confidence or effective_confidence,
        pre_bundle_state=request.pre_bundle_state or "OK",
        privacy_class=request.privacy_class or "NONE",
    )
    # massarius_risk_safety.classify_after_bundle enforces the ZL-ENG-03 §5.6
    # ordering guarantee: risk classification cannot run without
    # bundle_builder.py's step having been attempted above (bundle_attempted
    # is True here regardless of whether it succeeded — the try/except above
    # already ran either way; source_bundle itself may still be None if
    # retrieval failed).
    decision = massarius_risk_safety.classify_after_bundle(True, classify_request, sync_db)
    risk_level = decision.risk_level

    await audit_risk_classified(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, risk_level=risk_level, confidence_state=effective_confidence,
    )

    # Resolve route from versioned policy matrix
    route_decision = resolve_policy(
        confidence_state=effective_confidence,
        risk_level=risk_level,
        jurisdiction=request.jurisdiction,
        clarification_cycle=clarification_cycle,
    )
    route = route_decision.route

    await audit_route_selected(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, route=route, risk_level=risk_level,
        confidence_state=effective_confidence,
    )

    safety_state = SafetyState(
        risk_level=risk_level,
        policy_state="allowed" if decision.allowed else "blocked",
        disclaimer_required=route_decision.disclaimer_required,
    )

    # ── Step 6: Execute deterministic route (§8, §9) ──────────────────────────

    if not decision.allowed and decision.route == ROUTE_CLARIFICATION:
        # The classifier's own signal was "needs clarification" (e.g. ambiguous/
        # low-confidence query), not a hard block — it still sets allowed=False,
        # but collapsing that into REFUSAL would show a refusal outcome next to
        # clarification-worded text. Surface it as clarification instead.
        clarification_msg = decision.refusal_text or (
            "Could you provide more context about your jurisdiction and reporting framework?"
        )
        await audit_clarification_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, clarification_cycle=clarification_cycle,
        )
        response = AskKritonResponse(
            query_id=query_id,
            correlation_id=correlation_id,
            outcome="clarification_required",
            route=ROUTE_CLARIFICATION,
            safety=safety_state,
            confidence_state=effective_confidence,
            source_bundle=source_bundle,
            answer=None,
            next_action=NextAction(type="ask_clarifying_question", message=clarification_msg),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=ROUTE_CLARIFICATION, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    if not decision.allowed or route == ROUTE_REFUSAL:
        # REFUSAL path
        refusal_reason = decision.refusal_text or "Query blocked by risk classification policy."
        await audit_refusal_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, reason=refusal_reason,
        )
        response = AskKritonResponse(
            query_id=query_id,
            correlation_id=correlation_id,
            outcome="refused",
            route=ROUTE_REFUSAL,
            safety=safety_state,
            confidence_state=effective_confidence,
            source_bundle=source_bundle,
            answer=None,
            next_action=NextAction(type="refusal", message=refusal_reason),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=route, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    if route == ROUTE_HUMAN_REVIEW:
        # Persist review case (§11.1) — returning label without persisted object is non-compliant
        review_case = await create_review_case(
            db,
            query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, risk_level=risk_level,
            confidence_state=effective_confidence,
            reason=f"Risk: {risk_level} | Confidence: {effective_confidence} | Mode: {request.mode}",
        )
        await audit_human_review_created(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, review_case_id=review_case.id,
        )
        response = AskKritonResponse(
            query_id=query_id,
            correlation_id=correlation_id,
            outcome="escalated",
            route=ROUTE_HUMAN_REVIEW,
            safety=safety_state,
            confidence_state=effective_confidence,
            source_bundle=source_bundle,
            answer=None,
            next_action=NextAction(
                type="escalate",
                message=(
                    f"This query has been escalated to a qualified reviewer "
                    f"(Review Case {review_case.id}). You will be notified when the review is complete."
                ),
            ),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=route, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    if route == ROUTE_CLARIFICATION:
        await audit_clarification_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, clarification_cycle=clarification_cycle,
        )
        clarification_msg = route_decision.clarification_message or (
            "Could you provide more context about your jurisdiction and reporting framework?"
        )
        response = AskKritonResponse(
            query_id=query_id,
            correlation_id=correlation_id,
            outcome="clarification_required",
            route=ROUTE_CLARIFICATION,
            safety=safety_state,
            confidence_state=effective_confidence,
            source_bundle=source_bundle,
            answer=None,
            next_action=NextAction(type="ask_clarifying_question", message=clarification_msg),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=route, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    # ── LLM Route ─────────────────────────────────────────────────────────────
    # Model gateway executes ONLY when route == LLM (§9)
    assert route == ROUTE_LLM

    await audit_composition_started(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
    )

    # Attempt semantic retrieval via RAG layer if explicitly enabled.
    # Local dev should not block on Hugging Face model downloads just to serve
    # the API shell, login, and deterministic routing flows.
    context_text = ""
    rag_citations: list[SourceCitation] = []
    if os.getenv("ENABLE_RAG_EMBEDDINGS", "").lower() in {"1", "true", "yes"}:
        try:
            raw_chunks = await retrieve_documents(
                query=request.query,
                tenant_id=tenant_id,
                jurisdiction=request.jurisdiction or None,
                top_k=30,
            )
            if raw_chunks:
                reranked = await _reranker.rerank(request.query, raw_chunks)
                context_text, source_refs = build_grounded_context(reranked)
                rag_citations = [
                    SourceCitation(
                        ref_id=f"REF-{i+1}",
                        source_id=chunk.get("node_id", f"chunk-{i}"),
                        title=chunk["metadata"].get("title", "Uploaded Document"),
                    )
                    for i, chunk in enumerate(reranked)
                ]
        except Exception:
            context_text = ""

    # Build grounded prompt input
    prompt = await select_prompt(db, request.mode)
    if context_text:
        grounded_input = (
            f"Use ONLY the following retrieved context to answer the query. "
            f"Cite sources using [REF-N] markers. Do not use general knowledge.\n\n"
            f"=== Retrieved Context ===\n{context_text}\n\n"
            f"=== User Query ===\n{request.query}"
        )
    else:
        # §2: No unsupported answering — must not answer from model knowledge when sources insufficient
        grounded_input = request.query

    composed_text: Optional[str] = None
    prompt_id = "inline"
    prompt_name = "Inline Context Prompt"

    try:
        if prompt:
            prompt_row, composed_text = await model_gateway_service.run_test_prompt(
                db, prompt.id, grounded_input, actor_id, tenant_id, correlation_id=query_id
            )
            prompt_id = prompt_row.id
            prompt_name = prompt_row.name
        else:
            # No prompt template — use grounded context directly as fallback
            if context_text:
                composed_text = (
                    f"Based on the retrieved sources:\n\n{context_text}\n\n"
                    f"Please note: This is an educational summary only. "
                    f"Consult a qualified professional for specific advice."
                )
            else:
                # No context, no prompt — cannot answer safely
                composed_text = None

    except Exception as exc:
        await audit_composition_failed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, error=str(exc),
        )
        # Degrade to clarification since composition failed
        response = AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id,
            outcome="refused", route=ROUTE_REFUSAL,
            safety=safety_state, confidence_state=effective_confidence,
            source_bundle=source_bundle, answer=None,
            next_action=NextAction(
                type="composition_failed",
                message="Kriton™ could not compose a response at this time. Please try again shortly.",
            ),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=ROUTE_REFUSAL, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    if not composed_text:
        # No content — insufficient sources and no fallback
        await audit_refusal_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, reason="Insufficient sources; cannot answer without grounded content",
        )
        response = AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id,
            outcome="clarification_required", route=ROUTE_CLARIFICATION,
            safety=safety_state, confidence_state=effective_confidence,
            source_bundle=source_bundle, answer=None,
            next_action=NextAction(
                type="ask_clarifying_question",
                message=(
                    "Kriton™ could not find sufficient sources to answer your query. "
                    "Could you clarify your jurisdiction, reporting framework, or topic scope?"
                ),
            ),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=ROUTE_CLARIFICATION, start_time=start_time,
        )
        return response

    output_hash = hashlib.sha256(composed_text.encode()).hexdigest()[:32]
    await audit_composition_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, prompt_id=prompt_id, output_hash=output_hash,
    )

    # ── Step 7: Post-composition validation — Massarius™ Checkpoint C
    # (§10, RG-03; ZL-ENG-03 §5.7) ────────────────────────────────────────────
    validation = (
        validate_answer(composed_text, source_bundle, disclaimer_required=route_decision.disclaimer_required)
        if source_bundle else None
    )
    await audit_validation_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        passed=validation.passed if validation else False,
    )

    if validation and not validation.passed:
        await audit_composition_rejected(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, failures=validation.failures,
            degraded_route=validation.degraded_route,
        )
        # Invalid answer is NEVER returned; degrade route
        if validation.degraded_route == ROUTE_HUMAN_REVIEW:
            review_case = await create_review_case(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, risk_level=risk_level,
                confidence_state=effective_confidence,
                reason=f"Composition rejected: {'; '.join(validation.failures[:2])}",
            )
            await audit_human_review_created(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, review_case_id=review_case.id,
            )
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="escalated", route=ROUTE_HUMAN_REVIEW,
                safety=safety_state, confidence_state=effective_confidence,
                source_bundle=source_bundle, answer=None,
                next_action=NextAction(type="escalate", message="Response validation failed; escalated for review."),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
        else:
            await audit_refusal_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, reason="Composition rejected: prohibited claim detected",
            )
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="refused", route=ROUTE_REFUSAL,
                safety=safety_state, confidence_state=effective_confidence,
                source_bundle=source_bundle, answer=None,
                next_action=NextAction(type="refusal", message="Response validation failed. Please rephrase your query."),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=response.route, start_time=start_time,
        )
        if idempotency_key:
            store_idempotency(idempotency_key, tenant_id, response.model_dump())
        return response

    # ── Step 8: Finalise response ─────────────────────────────────────────────
    # Apply mandatory disclaimers (§10)
    final_text = build_validated_disclaimer(
        composed_text, risk_level,
        route_decision.disclaimer_required,
        effective_confidence,
    )

    # Build limitations list
    limitations: list[str] = list(decision.limitations or [])
    if route_decision.disclaimer_required:
        limitations.append(
            "This response is for educational purposes only. Consult a qualified professional."
        )

    answer = ComposedAnswer(
        text=final_text,
        citations=rag_citations,
        limitations=limitations,
        prompt_id=prompt_id,
        prompt_name=prompt_name,
        output_text=final_text,
    )

    response = AskKritonResponse(
        query_id=query_id,
        correlation_id=correlation_id,
        outcome="answered",
        route=ROUTE_LLM,
        safety=safety_state,
        confidence_state=effective_confidence,
        source_bundle=source_bundle,
        answer=answer,
        next_action=None,
        audit_reference=AuditReference(audit_chain_id=audit_chain_id),
    )

    # Audit BEFORE response is returned (§13, RG-04)
    await _finalise_and_return(
        db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
        audit_chain_id=audit_chain_id, actor_id=actor_id,
        outcome=response.outcome, route=route, start_time=start_time,
    )

    if idempotency_key:
        store_idempotency(idempotency_key, tenant_id, response.model_dump())

    return response


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _finalise_and_return(
    db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
    outcome, route, start_time: float
) -> None:
    latency_ms = (time.monotonic() - start_time) * 1000
    await audit_response_finalised(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, outcome=outcome, route=route,
    )
    await audit_response_returned(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, latency_ms=latency_ms,
    )


def _make_rejected_response(query_id, correlation_id, audit_chain_id, reason) -> AskKritonResponse:
    return AskKritonResponse(
        query_id=query_id,
        correlation_id=correlation_id,
        outcome="rejected",
        route=ROUTE_REJECTED,
        safety=SafetyState(risk_level="RESTRICTED", policy_state="blocked"),
        confidence_state="insufficient",
        source_bundle=None,
        answer=None,
        next_action=NextAction(type="rejected", message=reason),
        audit_reference=AuditReference(audit_chain_id=audit_chain_id),
    )


def _make_security_incident_response(query_id, correlation_id, audit_chain_id, trigger) -> AskKritonResponse:
    return AskKritonResponse(
        query_id=query_id,
        correlation_id=correlation_id,
        outcome="rejected",
        route=ROUTE_SECURITY_INCIDENT,
        safety=SafetyState(risk_level="RESTRICTED", policy_state="blocked"),
        confidence_state="restricted_sources",
        source_bundle=None,
        answer=None,
        next_action=NextAction(
            type="security_incident",
            message="Your request could not be processed due to a security policy violation.",
        ),
        audit_reference=AuditReference(audit_chain_id=audit_chain_id),
    )
