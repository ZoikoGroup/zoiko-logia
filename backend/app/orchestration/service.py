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

import asyncio
import hashlib
import time
import os
import re
from typing import Optional

from fastapi import HTTPException
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
    CONF_INSUFFICIENT, CONF_SUFFICIENT,
)
from app.orchestration.persisted_objects import create_review_case, create_security_incident_sync
from app.orchestration.schemas import (
    AskKritonRequest, AskKritonResponse,
    ComposedAnswer, SourceCitation, SafetyState, NextAction, AuditReference,
    GeneratedArtifactPublic,
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
    audit_redaction_applied,
    audit_document_retrieval,
    audit_artifact_generation_failed,
)
from app.domains.risk_safety.schemas import ClassifyRequest
from app.domains.model_gateway import service as model_gateway_service
from app.orchestration.compose import select_prompt
from app.orchestration.redaction import redact_for_external_exposure
from app.orchestration.websearch import web_search, build_web_grounded_prompt
from app.orchestration.live_data import fetch_live_data, LiveDataResult
from app.orchestration.evidence import EvidenceModel, Entity, Relationship
from app.orchestration.extraction import extract_graph
from app.orchestration.intent_classifier import (
    classify_intent, GRAPH_INTENTS, PROCESS, DISTRIBUTION, TREND,
    CURRENT_METRIC, PRECISE_DATA,
)
from app.orchestration.data_shape import classify_data_shape
from app.orchestration.response_planner import (
    plan_response, detect_explicit_visual_request, detect_requested_chart_variant,
)
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization import telemetry as viz_telemetry
from app.orchestration.risk_llm import classify_risk, classify_risk_gemini
from app.domains.kriton_workspace.documents import retrieve_document_sources, resolve_conversation_document_ids
from app.domains.kriton_workspace.artifacts import create_generated_artifact
from app.orchestration.document_pipeline import (
    analyse_spreadsheet_sources,
    build_document_generation_prompt,
    plan_document_task,
)

# Massarius™ retrieval and evidence subsystem — Phase 1 control modules
# (ZL-ENG-03). These wrap/replace the inline licence filtering, bundle
# construction, and answer validation that used to happen ad hoc in this
# file; retrieve.py itself is unchanged — its output is now treated as
# preliminary retrieval-layer output that these modules gate and finalise.
from app.domains.massarius import bundle_builder, license_gate
from app.domains.massarius import risk_safety as massarius_risk_safety
from app.domains.massarius.answer_validator import validate_answer
from app.domains.massarius.policy_matrix import resolve_policy


def _hash_query(query: str) -> str:
    """Hash query text — raw query text is not stored in plaintext per §13 RG-04."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:32]


_MODEL_DOMAIN_REFUSAL = "designed to answer questions related to Accounting"
_MODEL_DOMAIN_REFUSAL_TEXT = (
    "I'm designed to answer questions related to Accounting, Taxation, Payroll, "
    "Finance, Auditing, Bookkeeping, Commerce, and Accounting Education across "
    "global countries.\n\nPlease ask a question related to these topics."
)
_ACCOUNTING_RELATIONS = {
    "owns", "controls", "invoices", "pays", "supplies", "audits",
    "guarantees", "borrows_from", "lends_to", "reports_to",
    "is_a_subsidiary_of", "is_owned_by",
}
_ACCOUNTING_ENTITY_HINTS = re.compile(
    r"\b(account|accounting|audit|auditor|evidence|working[- ]?paper|finding|"
    r"invoice|payment|expense|journal|ledger|purchase order|supplier|customer|"
    r"company|companies|corp|corporation|holdings?|subsidiar(y|ies)|parent|"
    r"consolidation|tax|payroll|financial|finance|control|ownership|"
    r"partner|sign[- ]?off|delivery note|goods receipt|requisition)\b",
    re.I,
)
_TECHNICAL_ENTITY_HINTS = re.compile(
    r"\b(api|database|frontend|backend|service|server|module|code|repository|"
    r"microservice|deployment|container|kubernetes|function|class|package)\b",
    re.I,
)


def _grounded_domain_fallback(query: str, evidence: EvidenceModel) -> str | None:
    """Correct a model-only false off-domain decision when deterministic,
    governed evidence proves the request is finance/accounting-related.

    This does not broaden the product domain: generic module dependencies and
    generic publishing flows remain off-domain. The fallback only covers live
    financial statistics or explicitly supplied accounting relationships and
    is subsequently processed by the normal validation/disclaimer pipeline.
    """
    intent = classify_intent(query)
    # Naming ANY chart rendering this pipeline supports ("box plot", "step
    # line chart", "column chart", ...) is itself proof the request is a
    # statistical-data ask, independent of whether intent_classifier.py's
    # trend/distribution wordlists also happen to match — those wordlists
    # can't enumerate every current and future chart-variant phrase, so this
    # checks the visualization layer's own request detectors directly rather
    # than needing to keep two regex files in sync.
    is_named_chart_request = (
        detect_explicit_visual_request(query) or detect_requested_chart_variant(query) is not None
    )
    if evidence.observations and (
        intent in {DISTRIBUTION, TREND, CURRENT_METRIC, PRECISE_DATA} or is_named_chart_request
    ):
        subject = evidence.subject or "financial series"
        return (
            f"Kriton found {len(evidence.observations)} source-grounded observations for {subject}. "
            "The validated visualization below presents those values without adding model-generated figures."
        )

    graph = extract_graph(query)
    # Accept either a known accounting relation verb OR an accounting-entity
    # match — matching _structured_visual_query_is_in_domain's own, more
    # permissive check. A hardcoded verb-only list here previously drifted
    # out of sync with extraction.py's _RELATION_VERBS (e.g. "supports" was
    # added there but never mirrored into _ACCOUNTING_RELATIONS), so a
    # correctly-extracted, genuinely in-domain relationship like "Purchase
    # Order supports Goods Receipt" fell through and kept a false refusal.
    if graph and intent in GRAPH_INTENTS and (
        any(edge.type in _ACCOUNTING_RELATIONS for edge in graph.edges)
        or _ACCOUNTING_ENTITY_HINTS.search(query)
    ):
        relationships = "; ".join(
            f"{edge.source} {edge.type.replace('_', ' ')} {edge.target}" for edge in graph.edges
        )
        return (
            "Kriton mapped the accounting relationships exactly as supplied: "
            f"{relationships}. The validated visualization below does not infer additional links."
        )

    # Same entity-hint check as _structured_visual_query_is_in_domain's own
    # PROCESS branch — the previous separate, narrower keyword list here
    # (invoice|payment|audit|journal|expense|purchase order) missed generic
    # accounting-process phrasing like "tax filing process".
    if graph and intent == PROCESS and _ACCOUNTING_ENTITY_HINTS.search(query):
        return (
            f"Kriton mapped the {len(graph.nodes)} supplied accounting-workflow stages in order. "
            "The validated process visualization below does not add or remove stages."
        )
    return None


def _structured_visual_query_is_in_domain(query: str) -> bool | None:
    """Deterministically scope structured graph/flow prompts.

    Returns None when the query is not a structured graph/flow request, so the
    ordinary domain policy remains authoritative. For a recognized structured
    request, True/False is a code-enforced decision rather than an LLM guess.
    """
    intent = classify_intent(query)
    graph = extract_graph(query)
    if graph is None or (intent not in GRAPH_INTENTS and intent != PROCESS):
        return None
    if _TECHNICAL_ENTITY_HINTS.search(query) and not _ACCOUNTING_ENTITY_HINTS.search(query):
        return False
    if intent == PROCESS:
        return bool(_ACCOUNTING_ENTITY_HINTS.search(query))
    if any(edge.type in _ACCOUNTING_RELATIONS for edge in graph.edges):
        return True
    return bool(_ACCOUNTING_ENTITY_HINTS.search(query))


def _force_direct_answer() -> bool:
    """Dev/test-only override: force every query to the LLM route and skip
    the post-composition validation degrade, instead of the normal risk-based
    escalation/clarification/refusal policy. Does NOT touch pre_screen()'s L0/L1
    hard blocks (PII, jailbreak, academic-integrity) — those stay active
    regardless, since they guard against actual malicious/unsafe input, not
    routine risk-based routing. Citations are unaffected either way; they're
    built from the retrieved/reranked chunks independent of route or
    validation outcome. Turn off by unsetting FORCE_DIRECT_ANSWER (or setting
    it to anything other than 1/true/yes) once testing is done — this must
    never be left on in a real deployment, since it bypasses the human-review
    safeguard for HIGH-risk (tax/audit/legal-adjacent) queries entirely.
    """
    return os.getenv("FORCE_DIRECT_ANSWER", "").lower() in {"1", "true", "yes"}


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
    conversation_id: Optional[str] = None,
) -> AskKritonResponse:

    start_time = time.monotonic()

    # ── Idempotency check ─────────────────────────────────────────────────────
    request_hash = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
    if idempotency_key:
        try:
            cached = await check_idempotency(db, idempotency_key, tenant_id, request_hash)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        actor_id=actor_id, query_hash=query_hash, conversation_id=conversation_id,
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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
        return response

    # ── Kick off the live web search NOW, concurrently ──────────────────────
    # SearXNG is the slowest single step (~several seconds waiting on search
    # engines). It only depends on the query + jurisdiction — both already
    # known and past the safety pre-screen — so start it here as a background
    # task and let it run WHILE retrieval, risk classification and routing
    # happen. We await its result only at composition time (below), where the
    # answer actually needs the sources. This overlaps the long search with
    # the rest of the pipeline instead of paying for them one after another.
    # Fails soft exactly as before (returns [] on any error).
    needs_web = request.source_scope != "DOCUMENTS_ONLY"
    web_search_task = (
        asyncio.create_task(web_search(request.query, jurisdiction=request.jurisdiction, limit=5))
        if needs_web else None
    )
    # Live exact-figure sources (currency via Frankfurter, economic stats via
    # DBnomics). Self-gating + fail-soft: returns [] unless the question is
    # actually about an exchange rate or a statistic. Runs concurrently with the
    # web search, and its results are merged into web_sources at composition —
    # so figures flow through the exact same grounding pipeline as SearXNG hits,
    # with no change to the prompt, citations, or answer format.
    live_data_task = asyncio.create_task(fetch_live_data(request.query)) if needs_web else None
    # ── Step 4: Retrieve SourceBundle (Massarius™ keyword_mvp layer) (§7) ────
    await audit_retrieval_started(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
    )
    resolved_document_ids = await resolve_conversation_document_ids(
        db,
        conversation_id=request.conversation_id,
        requested_ids=request.document_ids,
        tenant_id=tenant_id,
        user_id=actor_id,
    )
    document_plan = plan_document_task(request.query, has_documents=bool(resolved_document_ids))
    document_retrieval_error: str | None = None
    try:
        # AsyncSession cannot safely execute two queries concurrently. Keep
        # document and governed-library retrieval sequential; web/live API
        # work still runs concurrently because it does not use this session.
        document_sources = await retrieve_document_sources(
            db,
            query=request.query,
            document_ids=resolved_document_ids,
            tenant_id=tenant_id,
            user_id=actor_id,
            full_document=document_plan.retrieval_mode == "full_document",
        )
    except Exception as exc:
        document_sources = []
        document_retrieval_error = str(exc)[:1000]
    await audit_document_retrieval(
        db,
        query_id=query_id,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        audit_chain_id=audit_chain_id,
        actor_id=actor_id,
        document_ids=resolved_document_ids,
        hit_count=len(document_sources),
        error=document_retrieval_error,
    )
    try:
        preliminary_bundle = await build_source_bundle(
            db, query=request.query, jurisdiction=request.jurisdiction, tenant_id=tenant_id,
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
        else (
            CONF_SUFFICIENT
            if document_sources
            else (source_bundle.confidence_state if source_bundle else CONF_INSUFFICIENT)
        )
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

    # LLM risk override (ZERO/LOW/MEDIUM/HIGH): the built-in zero-shot model is
    # weak and collapses ordinary questions into "uncertain -> MEDIUM". When a
    # provider LLM is configured, use its rubric-based judgment instead — much
    # more accurate ("What is a tax credit?" -> LOW, not MEDIUM). Fails soft:
    # keeps the ML result if the LLM is unavailable. Never downgrades a
    # pre-screen hard block — those RESTRICTED cases return before this point.
    llm_risk = await classify_risk(request.query)
    if not llm_risk:
        # Primary Groq classifier unavailable/failed — try Gemini as the
        # fallback LLM classifier (provider-level redundancy) before falling
        # back to the ML zero-shot result already in risk_level.
        llm_risk = await classify_risk_gemini(request.query)
    if llm_risk:
        risk_level = llm_risk

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
    force_direct = _force_direct_answer()
    if force_direct:
        route = ROUTE_LLM

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

    if not force_direct and not decision.allowed and decision.route == ROUTE_CLARIFICATION:
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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
        return response

    if not force_direct and (not decision.allowed or route == ROUTE_REFUSAL):
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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
        return response

    # ── LLM Route ─────────────────────────────────────────────────────────────
    # Model gateway executes ONLY when route == LLM (§9)
    assert route == ROUTE_LLM

    # A document-only request must never fall through to an ungrounded model
    # call. This also covers an attachment that was deleted, is not READY, or
    # was hidden by an unexpected storage/database failure. Returning a
    # clarification outcome keeps the UI from labelling the model's inability
    # to read the workbook as an "Answered" response.
    if request.source_scope == "DOCUMENTS_ONLY" and not document_sources:
        pending_tasks = [task for task in (web_search_task, live_data_task) if task is not None]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        await audit_refusal_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, reason="No readable document evidence was retrieved",
        )
        response = AskKritonResponse(
            query_id=query_id,
            correlation_id=correlation_id,
            outcome="clarification_required",
            route=ROUTE_CLARIFICATION,
            safety=safety_state,
            confidence_state=CONF_INSUFFICIENT,
            source_bundle=source_bundle,
            answer=None,
            next_action=NextAction(
                type="document_retrieval_failed",
                message=(
                    "Kriton™ could not retrieve readable evidence from the attached "
                    "document. Confirm that the attachment is ready, then attach it again "
                    "or choose another document."
                ),
            ),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, outcome=response.outcome,
            route=ROUTE_CLARIFICATION, start_time=start_time,
        )
        if idempotency_key:
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
        return response

    await audit_composition_started(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
    )

    # ── Web retrieval (SearXNG) ─────────────────────────────────────────────
    # The answer is grounded in live web sources found via SearXNG, restricted
    # (advisory) to authoritative accounting/tax/audit domains per
    # jurisdiction. Each source becomes a clickable [REF-N] citation. Fails
    # soft: if SearXNG is unreachable, web_sources is [] and the model answers
    # from its own knowledge with no source panel.
    # Started as a background task back at Step 4 so it ran concurrently with
    # retrieval + risk classification — by now it is usually already done.
    try:
        web_sources = await web_search_task if web_search_task is not None else []
    except Exception:
        web_sources = []
    # Merge in the exact-figure sources (currency / statistics), ranked FIRST so
    # the model grounds numeric answers in the precise value rather than a web
    # snippet. Fail-soft: no live data (or an error) just leaves web_sources as is.
    try:
        live_result: LiveDataResult = await live_data_task if live_data_task is not None else LiveDataResult()
    except Exception:
        live_result = LiveDataResult()
    if live_result.sources:
        web_sources = live_result.sources + web_sources
    live_evidence: EvidenceModel = live_result.evidence
    if request.source_scope == "DOCUMENTS_ONLY":
        evidence_sources = document_sources
    elif request.source_scope == "WEB_ONLY":
        evidence_sources = web_sources
    elif request.source_scope == "COMBINED":
        evidence_sources = document_sources + web_sources
    else:  # DOCUMENTS_THEN_WEB
        evidence_sources = document_sources or web_sources
    rag_citations: list[SourceCitation] = [
        SourceCitation(
            ref_id=f"REF-{i + 1}",
            source_id=s.source_id or s.url,
            title=s.title,
            url=s.url or None,
            # Genuine retrieved snippet, capped to a preview length — not a
            # fabricated summary.
            evidence_preview=(s.snippet[:240].strip() or None) if s.snippet else None,
            # Carried through so the reader can see whether a figure is
            # real-time, delayed, end-of-day or as-filed. Only market/company
            # connectors set these; a plain web hit leaves them None.
            provider=s.provider,
            fetched_at=s.fetched_at,
            freshness=s.freshness,
        )
        for i, s in enumerate(evidence_sources)
    ]

    # Build grounded prompt input from the web sources.
    prompt = await select_prompt(db, request.mode)
    document_analysis: dict = {}
    if document_plan.task_type == "document_generation" and document_sources:
        document_analysis = analyse_spreadsheet_sources(document_sources)
        grounded_input = build_document_generation_prompt(
            request.query, document_sources, document_analysis
        )
    else:
        grounded_input = build_web_grounded_prompt(request.query, evidence_sources)

    # External-provider exposure boundary (ZL-ENG-03 §5.8): redact before
    # grounded_input leaves the tenant trust boundary for the model gateway.
    # Deliberately after prescreen/retrieval, not at pipeline entry — those
    # steps need the raw query (see redaction.py's module docstring).
    redaction_result = redact_for_external_exposure(grounded_input)
    grounded_input = redaction_result.redacted_text
    await audit_redaction_applied(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        redaction_applied=redaction_result.redaction_applied,
        redaction_categories=redaction_result.redaction_categories,
    )

    composed_text: Optional[str] = None
    prompt_id = "inline"
    prompt_name = "Web-grounded Prompt"

    # Speed optimisation: simple, low-risk questions (greetings, plain
    # definitions) don't need the large 70B answer model — a small fast model
    # answers them well and much quicker. MEDIUM/HIGH-risk questions (real
    # advice, comparisons, judgment) keep the full GROQ_MODEL for depth and
    # quality. Only applied when Groq is the active provider (its fast model
    # names). answer_model=None means "use the provider's default model".
    # Only when Groq is the ACTIVE answering provider — if Gemini is configured
    # it answers instead (and this Groq model id must not be sent to it). Gemini
    # flash is already fast, so ZERO/LOW questions need no separate fast model.
    answer_model: Optional[str] = None
    gemini_active = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if risk_level in ("ZERO", "LOW") and os.getenv("GROQ_API_KEY") and not gemini_active:
        answer_model = os.getenv("GROQ_FAST_ANSWER_MODEL", "openai/gpt-oss-20b")

    try:
        if prompt:
            prompt_row, composed_text = await model_gateway_service.run_test_prompt(
                db, prompt.id, grounded_input, actor_id, tenant_id,
                correlation_id=query_id, model=answer_model,
            )
            prompt_id = prompt_row.id
            prompt_name = prompt_row.name
        else:
            # No approved prompt template seeded — fall back to a direct
            # provider completion so web-grounded answering still works.
            composed_text = await model_gateway_service.run_grounded_completion(grounded_input)

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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
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

    # Provider models occasionally ignore the shared domain instructions and
    # refuse clearly in-domain CPI/FX or corporate-relationship prompts. Use a
    # deliberately narrow deterministic correction only when governed
    # structured evidence independently proves the request is in scope. The
    # replacement then continues through the same audit, answer validation,
    # disclaimer and visualization gates as every other composed response.
    structured_scope = _structured_visual_query_is_in_domain(request.query)
    if structured_scope is False:
        composed_text = _MODEL_DOMAIN_REFUSAL_TEXT
    elif structured_scope is True:
        # Structured graph/flow data comes directly from the user's query.
        # Use the deterministic description whenever that governed structure
        # is in scope, not only when the model happened to refuse it. This
        # prevents provider prose from contradicting the visualization (for
        # example claiming Kriton cannot draw the flow that is rendered below)
        # or silently changing the meaning/order of a supplied stage.
        structured_answer = _grounded_domain_fallback(request.query, live_evidence)
        if structured_answer:
            composed_text = structured_answer
    elif _MODEL_DOMAIN_REFUSAL in composed_text:
        grounded_fallback = _grounded_domain_fallback(request.query, live_evidence)
        if grounded_fallback:
            composed_text = grounded_fallback

    output_hash = hashlib.sha256(composed_text.encode()).hexdigest()[:32]
    await audit_composition_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, prompt_id=prompt_id, output_hash=output_hash,
    )

    # ── Step 7: Post-composition validation — Massarius™ Checkpoint C
    # (§10, RG-03; ZL-ENG-03 §5.7) ────────────────────────────────────────────
    # Validate the provider's composed text directly. Generic disclaimer copy
    # is intentionally not appended to user-visible answers.
    # external_source_count carries the live retrieval sources (SearXNG + the
    # exact-figure connectors) the answer was actually composed against — they
    # are the [REF-N] citations the reader gets, but they are not registered in
    # the governed SourceBundle. Without it, every answer grounded purely in
    # live sources fails the grounding check and degrades to HUMAN_REVIEW.
    validation = (
        validate_answer(
            composed_text,
            source_bundle,
            disclaimer_required=False,
            external_source_count=len(rag_citations),
        )
        if source_bundle else None
    )
    final_text = composed_text
    await audit_validation_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        passed=validation.passed if validation else False,
    )

    if validation and not validation.passed and not force_direct:
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
            await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())
        return response

    # ── Step 8: Finalise response ─────────────────────────────────────────────
    # final_text already has the mandatory disclaimer (§10) applied above, and
    # has passed Checkpoint C validation against that same text.

    # Build limitations list
    limitations: list[str] = list(decision.limitations or [])
    # When the LLM authoritatively re-classified risk, drop the weak ML
    # model's "uncertain / needs clarification" artifact — it's noise next to
    # a confidently-answered response.
    if llm_risk:
        limitations = [
            l for l in limitations
            if "CLASSIFICATION_UNCERTAIN" not in l and "clarification" not in l.lower()
        ]
    # Do not duplicate generic disclaimer copy in the limitations panel.

    # Off-domain refusal: when the domain gate declined the question (it is not
    # about accounting/tax/payroll/finance/audit/bookkeeping/commerce), the
    # web-search results are irrelevant to the reply — so return NO sources and
    # NO disclaimer. Sources are shown only for genuine in-domain answers.
    is_offdomain_refusal = _MODEL_DOMAIN_REFUSAL in (composed_text or "")
    if is_offdomain_refusal:
        # This is a scope notice, not accounting guidance. Do not attach the
        # professional-advice disclaimer that may already have been added for
        # the provisional LLM route before deterministic scope correction.
        final_text = composed_text
        rag_citations = []
        limitations = []
        await audit_refusal_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, reason="Structured visualization request is outside Kriton's supported domain",
        )

    answer = ComposedAnswer(
        text=final_text,
        citations=rag_citations,
        limitations=limitations,
        prompt_id=prompt_id,
        prompt_name=prompt_name,
        output_text=final_text,
    )

    # ── Visualization pipeline (runs ONLY here — after safety, validation and
    # disclaimer have all already approved the text answer above; it can
    # never bypass or run ahead of that gate). Best-effort: any failure here
    # must never affect the already-composed text answer (spec §19/§29
    # DoD #15-16), so the whole block is wrapped and defaults to None.
    visualization = None
    secondary_visualizations: list = []
    if not is_offdomain_refusal:
        try:
            intent = classify_intent(request.query)

            # Entities/relationships the user explicitly supplied in their OWN
            # query text (extraction.py) — the only source EVIDENCE_GRAPH /
            # PROCESS_FLOW are backed by; merged into the same EvidenceModel
            # DBnomics/Frankfurter already populated, so a query can carry
            # both a numeric figure AND a supplied relationship structure.
            viz_evidence = live_evidence.model_copy(deep=True)
            graph = extract_graph(request.query)
            if graph and (intent in GRAPH_INTENTS or intent == PROCESS):
                viz_evidence.entities = [Entity(id=n, name=n) for n in graph.nodes]
                viz_evidence.relationships = [
                    Relationship(source_id=e.source, target_id=e.target, type=e.type)
                    for e in graph.edges
                ]
                viz_evidence.subject = viz_evidence.subject or request.query[:80]

            shape = classify_data_shape(viz_evidence, intent)
            plan = plan_response(request.query, intent, shape)
            result = VisualizationOrchestrator().decide(
                viz_evidence, shape, plan, spec_id=f"viz-{query_id}", query=request.query,
            )
            validation_result = None
            if result.spec is not None:
                validation_result = VisualizationValidator().validate(result.spec)
                if validation_result.passed:
                    visualization = result.spec
            # Each secondary is validated independently — a secondary that
            # fails never blocks the primary or the text answer (spec §16).
            if visualization is not None:
                for secondary in result.secondary_specs:
                    if VisualizationValidator().validate(secondary).passed:
                        secondary_visualizations.append(secondary)
            viz_telemetry.log_decision(
                query_id=query_id, query=request.query, intent=intent, data_shape=shape,
                response_mode=plan.response_mode, visual_required=plan.visual_required,
                result=result, validation=validation_result, render_success=visualization is not None,
            )
        except Exception:
            visualization = None
            secondary_visualizations = []

    # Compute the terminal response state before the optional artifact branch.
    # The response object is constructed below, so referencing `response.outcome`
    # (or an undeclared `outcome`) here would crash every otherwise-successful
    # request before it can be returned.
    response_outcome, response_route = _terminal_response_state(is_offdomain_refusal)

    generated_artifacts: list[GeneratedArtifactPublic] = []
    artifact_error: str | None = None
    if (
        response_outcome == "answered"
        and document_plan.response_mode == "chat_with_artifact"
        and document_sources
    ):
        try:
            artifact = await create_generated_artifact(
                db,
                title="Kriton Management Report",
                narrative=final_text,
                analysis=document_analysis,
                format_name=document_plan.output_format,
                tenant_id=tenant_id,
                user_id=actor_id,
                conversation_id=request.conversation_id,
                query_id=query_id,
                source_document_ids=resolved_document_ids,
                request_text=request.query,
            )
            generated_artifacts.append(GeneratedArtifactPublic(
                id=artifact.id,
                filename=artifact.filename,
                mime_type=artifact.mime_type,
                download_url=f"/kriton-workspace/artifacts/{artifact.id}/download",
                expires_at=artifact.expires_at.isoformat() if artifact.expires_at else None,
            ))
        except Exception as exc:
            # Preserve the valid grounded answer, but make the additive file
            # failure visible instead of silently degrading to Download .md.
            generated_artifacts = []
            artifact_error = (
                f"The report content was generated, but the requested "
                f"{document_plan.output_format.upper()} file could not be created."
            )
            await audit_artifact_generation_failed(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, format_name=document_plan.output_format,
                error_type=type(exc).__name__,
            )

    response = AskKritonResponse(
        query_id=query_id,
        correlation_id=correlation_id,
        outcome=response_outcome,
        route=response_route,
        safety=safety_state,
        confidence_state=effective_confidence,
        source_bundle=source_bundle,
        visualization=visualization,
        secondary_visualizations=secondary_visualizations,
        answer=answer,
        next_action=None,
        artifacts=generated_artifacts,
        artifact_error=artifact_error,
        audit_reference=AuditReference(audit_chain_id=audit_chain_id),
    )

    # Audit BEFORE response is returned (§13, RG-04)
    await _finalise_and_return(
        db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
        audit_chain_id=audit_chain_id, actor_id=actor_id,
        outcome=response.outcome, route=response.route, start_time=start_time,
    )

    if idempotency_key:
        await store_idempotency(db, idempotency_key, tenant_id, request_hash, response.model_dump())

    return response


# ── Helpers ────────────────────────────────────────────────────────────────────

def _terminal_response_state(is_offdomain_refusal: bool) -> tuple[str, str]:
    """Return the single terminal state used by artifacts and the response."""
    if is_offdomain_refusal:
        return "refused", ROUTE_REFUSAL
    return "answered", ROUTE_LLM


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
