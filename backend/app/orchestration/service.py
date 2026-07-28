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
import re
import time
import os
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.orchestration.identifiers import (
    generate_query_id, generate_correlation_id, generate_request_id,
    generate_audit_chain_id,
    check_idempotency, store_idempotency,
)
from app.orchestration.prescreen import run_prescreen, is_small_talk, check_off_topic_domain
from app.orchestration.navigation_answers import resolve_navigation_answer
from app.orchestration.retrieve import build_source_bundle, infer_category
from app.domains.source_library.service import list_sources, resolve_source_url
from app.domains.rag.planner import create_retrieval_plan
from app.domains.reference_data.service import (
    get_exchange_rate_bundle,
    match_currency_keyword,
    to_rag_chunk as treasury_to_rag_chunk,
    TREASURY_GOVERNED_SOURCE_ID,
    TREASURY_NODE_PREFIX,
    get_payroll_tax_bundle,
    match_work_state,
    extract_pay_date,
    to_payroll_tax_rag_chunk,
    PAYROLL_TAX_GOVERNED_SOURCE_ID,
    PAYROLL_TAX_NODE_PREFIX,
    get_census_income_poverty_bundle,
    match_state_fips,
    is_inflation_query,
    to_census_rag_chunk,
    CENSUS_GOVERNED_SOURCE_ID,
    CENSUS_NODE_PREFIX,
    get_cpi_bundle,
    to_cpi_rag_chunk,
    BLS_CPI_GOVERNED_SOURCE_ID,
    BLS_CPI_NODE_PREFIX,
    get_gdp_bundle,
    is_gdp_query,
    to_gdp_rag_chunk,
    BEA_GDP_GOVERNED_SOURCE_ID,
    BEA_GDP_NODE_PREFIX,
    get_interest_rates_bundle,
    to_fred_rag_chunk,
    FRED_INTEREST_RATES_GOVERNED_SOURCE_ID,
    FRED_NODE_PREFIX,
    get_cfr_section_bundle,
    extract_cfr_section,
    to_cfr_rag_chunk,
    CFR_TITLE26_GOVERNED_SOURCE_ID,
    CFR_NODE_PREFIX,
    get_ecfr_section_bundle,
    to_ecfr_rag_chunk,
    ECFR_TITLE26_GOVERNED_SOURCE_ID,
    ECFR_NODE_PREFIX,
    get_federal_register_document_bundle,
    extract_federal_register_document_number,
    to_federal_register_rag_chunk,
    FEDERAL_REGISTER_GOVERNED_SOURCE_ID,
    FEDERAL_REGISTER_NODE_PREFIX,
    get_congress_bill_bundle,
    extract_congress_bill_identifier,
    to_congress_rag_chunk,
    CONGRESS_GOVERNED_SOURCE_ID,
    CONGRESS_NODE_PREFIX,
    TAVILY_GOVERNED_SOURCE_ID,
    SERPAPI_GOVERNED_SOURCE_ID,
    get_professional_search_bundle,
    to_professional_search_chunks,
)
from app.domains.reference_data.bank_reconciliation import (
    BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
    BANK_RECONCILIATION_NODE_PREFIX,
    to_bank_reconciliation_rag_chunk,
)
from app.domains.reference_data.month_end_close import (
    MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
    MONTH_END_CLOSE_NODE_PREFIX,
    to_month_end_close_rag_chunk,
)
from app.domains.reference_data.accounting_fundamentals import (
    ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
    ACCOUNTING_FUNDAMENTALS_NODE_PREFIX,
    to_accounting_fundamentals_rag_chunk,
)
from app.domains.reference_data.user_provided_data import (
    USER_PROVIDED_DATA_GOVERNED_SOURCE_ID,
    USER_PROVIDED_DATA_NODE_PREFIX,
    to_user_provided_data_rag_chunk,
    compose_quarterly_results,
)
from app.orchestration.educational_answers import (
    compose_accounting_fundamentals,
    compose_bank_reconciliation,
    compose_month_end_close,
)
from app.domains.calculation.household_extraction import extract_household_params
from app.domains.calculation.arithmetic_extraction import extract_arithmetic_expression
from app.domains.calculation.formula_extraction import extract_named_formula, identify_missing_formula_inputs
from app.domains.calculation.router import (
    route as route_calculation,
    CalculationRequest,
    ENGINE_EXPRESSION_EVALUATOR,
    ENGINE_FORMULA_REGISTRY,
)
from app.domains.calculation.provenance import ProvenanceStore, from_expression_record, from_formula_result
from app.domains.calculation.widget import build_widget as build_calculation_widget
from app.domains.calculation.service import (
    get_calculation_bundle,
    to_calculation_rag_chunk,
    to_expression_rag_chunk,
    to_formula_rag_chunk,
    POLICYENGINE_GOVERNED_SOURCE_ID,
    POLICYENGINE_NODE_PREFIX,
    EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID,
    EXPRESSION_EVALUATOR_NODE_PREFIX,
    FORMULA_REGISTRY_GOVERNED_SOURCE_ID,
    FORMULA_REGISTRY_NODE_PREFIX,
)
from app.orchestration.routing_matrix import (
    map_safety_confidence,
    ROUTE_LLM, ROUTE_REFUSAL, ROUTE_CLARIFICATION,
    ROUTE_HUMAN_REVIEW, ROUTE_REFERRAL, ROUTE_SECURITY_INCIDENT, ROUTE_REJECTED,
    CONF_SUFFICIENT, CONF_INSUFFICIENT, CONF_LIMITED,
)
from app.orchestration.composition_validator import build_validated_disclaimer
from app.orchestration.professional_referral import referral_message
from app.orchestration.persisted_objects import create_review_case, create_security_incident_sync
from app.orchestration.schemas import (
    AskKritonRequest, AskKritonResponse,
    ComposedAnswer, SourceCitation, SourceSummary, SafetyState, NextAction, AuditReference,
)
from app.orchestration.presentation import build_answer_presentation
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
    audit_redaction_applied, audit_plan_created, audit_rerank_completed,
    audit_context_fit_completed, audit_route_reevaluated,
    audit_citation_assembly_completed, audit_coverage_assessed,
)
from app.domains.risk_safety.schemas import ClassifyRequest
from app.domains.model_gateway import service as model_gateway_service
from app.orchestration.compose import select_prompt
from app.domains.rag.retrieval import retrieve_documents
from app.domains.rag.reranker import Reranker
from app.domains.rag.context_fit import build_grounded_context
from app.domains.rag.citation_assembly import assemble_citations
from app.domains.rag.redaction import redact_for_external_exposure

# Massarius™ retrieval and evidence subsystem — Phase 1 control modules
# (ZL-ENG-03). These wrap/replace the inline licence filtering, bundle
# construction, and answer validation that used to happen ad hoc in this
# file; retrieve.py itself is unchanged — its output is now treated as
# preliminary retrieval-layer output that these modules gate and finalise.
from app.domains.massarius import bundle_builder, license_gate
from app.domains.massarius import risk_safety as massarius_risk_safety
from app.domains.massarius.answer_validator import (
    validate_answer,
    generalize_unsupported_numeric_claims,
    _PROHIBITED,
)
from app.domains.massarius.policy_matrix import resolve_policy
from app.domains.coverage import assess_us_professional_coverage

_reranker = Reranker(top_n=5)

_NUMERIC_RESULT_QUERY_PATTERN = re.compile(
    r"\b(how\s+much|rate|rates|amount|amounts|percentage|percent|threshold|"
    r"limit|deduction|credit|price|cost|fee|number|value|calculate|compute|chart|graph)\b|[$£€]\s*\d|\d\s*%",
    re.IGNORECASE,
)

# Any injected live-data chunk's node_id starts with one of these prefixes —
# checked by _reinstate_live_chunks below.
_LIVE_DATA_NODE_PREFIXES = (
    TREASURY_NODE_PREFIX, PAYROLL_TAX_NODE_PREFIX, CENSUS_NODE_PREFIX,
    BLS_CPI_NODE_PREFIX, BEA_GDP_NODE_PREFIX, FRED_NODE_PREFIX, CFR_NODE_PREFIX,
    FEDERAL_REGISTER_NODE_PREFIX, ECFR_NODE_PREFIX, POLICYENGINE_NODE_PREFIX,
    CONGRESS_NODE_PREFIX, EXPRESSION_EVALUATOR_NODE_PREFIX, FORMULA_REGISTRY_NODE_PREFIX,
    BANK_RECONCILIATION_NODE_PREFIX,
    MONTH_END_CLOSE_NODE_PREFIX,
    ACCOUNTING_FUNDAMENTALS_NODE_PREFIX,
    USER_PROVIDED_DATA_NODE_PREFIX,
)


def _reinstate_live_chunks(raw_chunks: list, reranked: list) -> list:
    """The cross-encoder reranker ranks on prose similarity alone and can
    drop an injected live-data chunk in favor of a document that merely
    discusses the same topic in prose (originally observed: FRS 105's
    currency-translation text outscoring Treasury's compact rate listing).
    infer_category() already deterministically established relevance for
    each live-data source before it was injected — the reranker's job is to
    rank uncertain candidates, not gatekeep something already known to be
    pertinent — so any such chunk must survive reranking regardless of its
    cross-encoder score."""
    result = reranked
    for prefix in _LIVE_DATA_NODE_PREFIXES:
        live_chunk = next((c for c in raw_chunks if c["node_id"].startswith(prefix)), None)
        if live_chunk and not any(c["node_id"] == live_chunk["node_id"] for c in result):
            result = [live_chunk] + result
    return result


def _is_mandatory_context_chunk(chunk: dict) -> bool:
    """Return whether dropping this chunk would remove required evidence."""
    metadata = chunk.get("metadata") or {}
    return bool(metadata.get("mandatory_source")) or str(chunk.get("node_id", "")).startswith(
        _LIVE_DATA_NODE_PREFIXES
    )


def _hash_query(query: str) -> str:
    """Hash query text — raw query text is not stored in plaintext per §13 RG-04."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:32]


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
    enabled = os.getenv("FORCE_DIRECT_ANSWER", "").lower() in {"1", "true", "yes"}
    explicit_dev_unlock = (
        os.getenv("APP_ENV", "").lower() in {"local", "development", "test"}
        and os.getenv("ALLOW_UNSAFE_DEV_OVERRIDES", "").lower() in {"1", "true", "yes"}
    )
    return enabled and explicit_dev_unlock


class KritonMediator:
    """Mediator coordinating the Ask Kriton request pipeline.

    Colleague domains never call each other directly for this request path;
    every cross-domain call happens through this class, matching the
    canonical 8-step Ask Kriton workflow described in the repository
    README ("Canonical Ask Kriton workflow", ZL-ENG-02/ZL-ENG-03):
    risk_safety (via massarius.risk_safety), rag, massarius, model_gateway,
    source_library, coverage, calculation, reference_data, and audit_ledger
    (via orchestration.audit_events).
    """

    async def handle(
        self,
        db: AsyncSession,
        sync_db: Session,
        *,
        actor_id: str,
        tenant_id: str,
        role: str,
        request: AskKritonRequest,
        idempotency_key: str,
        clarification_cycle: int = 0,
    ) -> AskKritonResponse:

        start_time = time.monotonic()
        clarification_cycle = max(clarification_cycle, request.clarification_cycle)

        # ── Idempotency check ─────────────────────────────────────────────────────
        cached = await check_idempotency(db, idempotency_key, tenant_id)
        if cached is not None:
            return AskKritonResponse(**cached)

        # ── Step 1: Generate identifiers (§5) ────────────────────────────────────
        query_id = generate_query_id()
        correlation_id = generate_correlation_id()
        request_id = generate_request_id()
        audit_chain_id = generate_audit_chain_id()
        query_hash = _hash_query(request.query)

        # Audit: query_received — first event, before any processing
        await audit_query_received(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, query_hash=query_hash, request_id=request_id,
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

        # ── Step 2.5: Small-talk gate — greetings/acknowledgements never reach
        # retrieval or the model at all (see prescreen.is_small_talk's docstring
        # for why this can't just be another run_prescreen() pattern bank).
        if is_small_talk(request.query):
            await audit_clarification_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, clarification_cycle=clarification_cycle,
            )
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="clarification_required", route=ROUTE_CLARIFICATION,
                safety=SafetyState(risk_level="LOW", policy_state="needs_more_context", disclaimer_required=False),
                confidence_state=CONF_INSUFFICIENT,
                source_bundle=None, answer=None,
                next_action=NextAction(
                    type="ask_clarifying_question",
                    message=(
                        "Hi! I'm Kriton™ — I can help with accounting, tax, and audit "
                        "questions grounded in your governed sources. What would you "
                        "like to ask?"
                    ),
                ),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
            await _finalise_and_return(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                outcome=response.outcome, route=ROUTE_CLARIFICATION, start_time=start_time,
            )
            if idempotency_key:
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        # ── Step 2.6: Domain restriction — 2026-07-22 product vision doc, item 1.
        # Kriton is scoped to accounting/finance/tax/audit/reporting/bookkeeping/
        # compliance; an unrelated subject (chemistry, physics, ...) is refused
        # before retrieval runs, same "never reach the model for this" posture
        # as the small-talk gate above — no wasted retrieval, no security
        # incident (this isn't an attack, just out of scope).
        off_topic_subject = check_off_topic_domain(request.query)
        if off_topic_subject:
            refusal_message = (
                f"This service is designed specifically for accounting and finance "
                f"topics. I'm unable to assist with {off_topic_subject}-related questions."
            )
            await audit_refusal_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, reason=f"Out of domain: {off_topic_subject}",
            )
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="refused", route=ROUTE_REFUSAL,
                safety=SafetyState(risk_level="LOW", policy_state="blocked", disclaimer_required=False),
                confidence_state=CONF_INSUFFICIENT,
                source_bundle=None, answer=None,
                next_action=NextAction(type="refused", message=refusal_message),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
            await _finalise_and_return(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                outcome=response.outcome, route=ROUTE_REFUSAL, start_time=start_time,
            )
            if idempotency_key:
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

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
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        # ── Step 3.5: Product-navigation fast path ────────────────────────────
        # The requested location is application-owned metadata. It neither
        # needs governed accounting sources nor benefits from model generation.
        # Keep this after the security pre-screen so injection/exfiltration
        # attempts cannot disguise themselves as navigation requests.
        navigation = resolve_navigation_answer(request.query)
        if navigation is not None:
            await audit_risk_classified(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, risk_level="ZERO", confidence_state=CONF_SUFFICIENT,
            )
            await audit_route_selected(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, route=ROUTE_LLM, risk_level="ZERO",
                confidence_state=CONF_SUFFICIENT,
            )
            response = AskKritonResponse(
                query_id=query_id,
                correlation_id=correlation_id,
                outcome="answered",
                # ROUTE_LLM remains the public contract's direct-answer route;
                # prompt metadata below makes the deterministic execution clear.
                route=ROUTE_LLM,
                safety=SafetyState(
                    risk_level="ZERO", policy_state="allowed", disclaimer_required=False,
                ),
                confidence_state=CONF_SUFFICIENT,
                source_bundle=None,
                answer=ComposedAnswer(
                    text=navigation.text,
                    citations=[],
                    limitations=[],
                    prompt_id="deterministic-product-navigation",
                    prompt_name="Product navigation",
                    output_text=navigation.text,
                ),
                next_action=None,
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
            await _finalise_and_return(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, outcome=response.outcome, route=ROUTE_LLM,
                start_time=start_time,
            )
            if idempotency_key:
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        # ── Step 4: Plan, prefilter, retrieve, rerank and build (§7) ───────
        embeddings_enabled = os.getenv("ENABLE_RAG_EMBEDDINGS", "").lower() in {"1", "true", "yes"}
        retrieval_category = infer_category(request.query)
        closed_evidence_categories = {
            "exchange-rate", "economic-data", "interest-rates", "tax-regulations",
            "federal-register", "us-legislation", "bank-reconciliation",
            "month-end-close", "accounting-fundamentals", "user-provided-data",
        }
        retrieval_plan = create_retrieval_plan(
            request.query, request.jurisdiction, embeddings_enabled=embeddings_enabled,
        )
        await audit_plan_created(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            retrieval_plan_id=retrieval_plan.retrieval_plan_id,
            strategy=retrieval_plan.strategy, methods=list(retrieval_plan.methods),
        )

        # Checkpoint A: establish the complete tenant-visible allow-list before
        # vector or live-source retrieval. Denied IDs never enter retrieval.
        # Closed evidence routes can only use sources registered to their exact
        # category. Fetching and licence-checking the tenant's entire catalogue
        # (dozens or hundreds of rows over a remote DB) cannot alter their result.
        catalog_rows = await list_sources(
            db,
            retrieval_category if retrieval_category in closed_evidence_categories else None,
            tenant_id=tenant_id,
        )
        catalog_summaries = [
            SourceSummary(
                id=row["id"], title=row["title"], category=row["category"],
                jurisdiction_scope=row["jurisdiction_scope"],
                version_label=row["latest_version"].version_label if row["latest_version"] else "unknown",
                status=row["latest_version"].status if row["latest_version"] else "MISSING",
            )
            for row in catalog_rows
        ]
        prefilter = await license_gate.check_eligibility(db, catalog_summaries, tenant_id=tenant_id)
        allowed_source_ids = {source.id for source in prefilter.eligible}
        await audit_licence_prefilter_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            eligible_count=len(prefilter.eligible), excluded_count=len(prefilter.excluded),
        )
        if prefilter.excluded:
            await audit_licence_denied(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
                checkpoint="A", source_ids=[source.id for source in prefilter.excluded],
                reason_code=";".join(sorted(set(prefilter.exclusion_reasons.values()))) or "unknown",
            )

        await audit_retrieval_started(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        )
        # Fetched once here (top_k=30) and reused both for SourceBundle governance
        # merging below and for the LLM's grounded context further down —
        # retrieve_documents() embeds the query and runs a real Postgres vector
        # search (profiled at ~20s on this setup), and was previously being
        # called a second time, redundantly, for the exact same query later in
        # this same function.
        raw_chunks: list = []
        # Populated by the governed calculation engines below (expression
        # evaluator today; formula registry/PolicyEngine follow the same
        # pattern once wired) — passed to Checkpoint C's validate_answer() so a
        # derived figure that will never appear literally in grounding_context
        # (e.g. "70000" from "250000 - 180000") isn't wrongly flagged as
        # unsupported. See docs/calculation_architecture.md.
        provenance_store = ProvenanceStore()
        # Set True below when the expression evaluator OR the formula registry
        # verifies a self-contained calculation from the query's own figures —
        # used to bypass the coverage gate further down (a verified calculation
        # doesn't need an authoritative topical source; it needs nothing but
        # the inputs the user already supplied).
        verified_calculation_bypasses_coverage_gate = False
        # Populated below when a formula-registry calculation (currently:
        # straight-line depreciation) is confidently extracted and verified —
        # attached to the final ComposedAnswer so the frontend can render an
        # interactive widget (sliders + chart) instead of only prose. None
        # means no such calculation ran for this query; the text answer is
        # unaffected either way.
        calculation_widget = None
        executed_formula_result = None
        missing_formula_inputs = None
        policyengine_result = None
        exact_live_categories = closed_evidence_categories
        authority_web_lookup = (
            retrieval_category in {"audit", "standards"}
            and bool(re.search(r"\b(?:pcaob|sec\s+form|as\s*\d{4})\b", request.query, re.I))
        )
        skip_vector_retrieval = retrieval_category in exact_live_categories or authority_web_lookup
        if embeddings_enabled and not skip_vector_retrieval:
            try:
                raw_chunks = await retrieve_documents(
                    query=request.query,
                    tenant_id=tenant_id,
                    jurisdiction=request.jurisdiction or None,
                    top_k=30,
                    allowed_source_ids=sorted(allowed_source_ids),
                )
            except Exception as exc:
                # Previously silent (raw_chunks = [] with the exception fully
                # discarded) — a real embedding-model/pgvector outage was
                # indistinguishable from "legitimately no relevant documents,"
                # so every query would quietly degrade to keyword_mvp-only
                # retrieval with zero record anywhere that it happened.
                # audit_retrieval_failed already exists for exactly this
                # (replay_relevance="REQUIRED" in audit_events.py) but was never
                # actually reached from here, since this except block ate the
                # exception before the outer retrieval try/except further below
                # ever saw it. Still degrades gracefully (raw_chunks stays [] —
                # a single query's vector-search hiccup must not break the
                # keyword_mvp/live-data retrieval that still runs after this),
                # it just no longer does so invisibly.
                raw_chunks = []
                await audit_retrieval_failed(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                    actor_id=actor_id, error=f"vector retrieval degraded: {exc}",
                )

        # Procedure categories are closed evidence sets: semantically nearby
        # audit/SEC documents must not contaminate an operational answer.
        procedure_source_id = {
            "bank-reconciliation": BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
            "month-end-close": MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
            "accounting-fundamentals": ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
            "user-provided-data": USER_PROVIDED_DATA_GOVERNED_SOURCE_ID,
        }.get(retrieval_category)
        if procedure_source_id:
            raw_chunks = [
                chunk for chunk in raw_chunks
                if (chunk.get("metadata") or {}).get("source_id") == procedure_source_id
            ]

        # Prefer the reviewed procedure over documents that merely contain the
        # same vocabulary in a different accounting or auditing context.
        if (
            retrieval_category == "bank-reconciliation"
            and BANK_RECONCILIATION_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            raw_chunks.insert(0, to_bank_reconciliation_rag_chunk())
        if (
            retrieval_category == "month-end-close"
            and MONTH_END_CLOSE_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            raw_chunks.insert(0, to_month_end_close_rag_chunk())
        if (
            retrieval_category == "accounting-fundamentals"
            and ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            raw_chunks.insert(0, to_accounting_fundamentals_rag_chunk())
        if (
            retrieval_category == "user-provided-data"
            and USER_PROVIDED_DATA_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            raw_chunks.insert(0, to_user_provided_data_rag_chunk(request.query))

        # Live Treasury exchange-rate data — independent of ENABLE_RAG_EMBEDDINGS
        # (this isn't a document-embeddings feature), so it runs regardless of
        # that flag. Injected into the same raw_chunks list reused below for
        # SourceBundle eligibility, reranking, grounded context, and citations —
        # a Treasury API failure here must never break the rest of the answer.
        if infer_category(request.query) == "exchange-rate" and TREASURY_GOVERNED_SOURCE_ID in allowed_source_ids:
            currency = match_currency_keyword(request.query)
            # Only inject when the query actually names a currency. When it
            # doesn't, match_currency_keyword's own contract says "fetch the
            # full list" — every country Treasury tracks, in one chunk — which
            # composition then has no way to disambiguate: for a query like
            # "What is the current Treasury exchange rate?" (no currency named),
            # the model was picking one arbitrary row (e.g. Panama) out of that
            # list and presenting it as *the* answer, sourced and confident, to
            # a question that's actually ambiguous about which currency is
            # meant. match_work_state below has the right precedent for this
            # exact shape of problem — a required identity param with no query
            # match skips the live fetch rather than guessing one — so mirror
            # that here instead of special-casing composition to detect
            # ambiguity after the fact. Skipping just means this specific live
            # chunk doesn't get injected; normal retrieval still runs, and if
            # nothing else is eligible either, the existing NO_ELIGIBLE_SOURCE
            # path already asks the user to clarify rather than guessing.
            if currency is not None:
                try:
                    treasury_bundle = await get_exchange_rate_bundle(
                        db, currency=currency, since="2020-01-01", tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(0, treasury_to_rag_chunk(treasury_bundle, source_id=TREASURY_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

        # Live PayrollTax API data — same isolation posture as Treasury above.
        # workState is a required identity param for the upstream API; unlike
        # currency, there's no "fetch everything" fallback, so a query naming no
        # US state skips the live fetch entirely rather than guessing one (the 2
        # seeded governed sources are still eligible via the normal keyword_mvp
        # path either way, so the query isn't dead-ended).
        if infer_category(request.query) == "payroll-compliance" and PAYROLL_TAX_GOVERNED_SOURCE_ID in allowed_source_ids:
            work_state = match_work_state(request.query)
            if work_state is not None:
                try:
                    pay_date = extract_pay_date(request.query)
                    payroll_bundle = await get_payroll_tax_bundle(
                        db, work_state=work_state, pay_date=pay_date, tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(0, to_payroll_tax_rag_chunk(payroll_bundle, source_id=PAYROLL_TAX_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

        # Live Census ACS data — same isolation posture and fail-closed state
        # requirement as PayrollTax above (no state named -> skip, never guess).
        if infer_category(request.query) == "economic-data":
            state_fips = match_state_fips(request.query)
            if state_fips is not None and CENSUS_GOVERNED_SOURCE_ID in allowed_source_ids:
                try:
                    census_bundle = await get_census_income_poverty_bundle(
                        db, state_fips=state_fips, tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(0, to_census_rag_chunk(census_bundle, source_id=CENSUS_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

            # Live BLS CPI data — same category as Census above, but gated on
            # inflation-specific keywords rather than a state name (CPI is
            # national data, no entity to extract). Isolated the same way: a
            # BLS hiccup must never break an otherwise-answerable question.
            if is_inflation_query(request.query) and BLS_CPI_GOVERNED_SOURCE_ID in allowed_source_ids:
                try:
                    cpi_bundle = await get_cpi_bundle(db, tenant_id=tenant_id, actor_id=actor_id)
                    raw_chunks.insert(0, to_cpi_rag_chunk(cpi_bundle, source_id=BLS_CPI_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

            # Live BEA GDP data — same category and national-data posture as BLS
            # CPI above, gated on its own keyword check so a plain income/CPI
            # question doesn't also get an irrelevant GDP chunk injected.
            if is_gdp_query(request.query) and BEA_GDP_GOVERNED_SOURCE_ID in allowed_source_ids:
                try:
                    gdp_bundle = await get_gdp_bundle(db, tenant_id=tenant_id, actor_id=actor_id)
                    raw_chunks.insert(0, to_gdp_rag_chunk(gdp_bundle, source_id=BEA_GDP_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

        # Live FRED interest-rate data — its own dedicated category (unlike
        # Census/BLS/GDP, "interest-rates" isn't shared with anything else), so
        # the category match alone is sufficient gating, same posture as
        # Treasury/PayrollTax above.
        if infer_category(request.query) == "interest-rates" and FRED_INTEREST_RATES_GOVERNED_SOURCE_ID in allowed_source_ids:
            try:
                fred_bundle = await get_interest_rates_bundle(db, tenant_id=tenant_id, actor_id=actor_id)
                raw_chunks.insert(0, to_fred_rag_chunk(fred_bundle, source_id=FRED_INTEREST_RATES_GOVERNED_SOURCE_ID))
            except Exception:
                pass

        # Live GovInfo 26 CFR section lookup — only when the query names a
        # specific section number; no free-text fallback (there is no honest
        # way to guess which of thousands of CFR sections was meant), same
        # fail-closed contract as PayrollTax/Census above. The 2 seeded
        # governed sources are still eligible via the normal keyword_mvp path
        # either way, so a CFR question with no section number isn't dead-ended.
        if infer_category(request.query) == "tax-regulations":
            section_number = extract_cfr_section(request.query)
            if section_number is not None:
                # Two independent live sources for the same section — eCFR
                # (current amended text) and GovInfo (annual-edition snapshot)
                # — kept side by side rather than one replacing the other, per
                # the comprehensive-data-collection goal for this project.
                # Isolated separately so one source's failure never blocks the
                # other's chunk from being injected.
                try:
                    if ECFR_TITLE26_GOVERNED_SOURCE_ID not in allowed_source_ids:
                        raise PermissionError("source not eligible")
                    ecfr_bundle = await get_ecfr_section_bundle(
                        db, section_number=section_number, tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(0, to_ecfr_rag_chunk(ecfr_bundle, source_id=ECFR_TITLE26_GOVERNED_SOURCE_ID))
                except Exception:
                    pass
                try:
                    if CFR_TITLE26_GOVERNED_SOURCE_ID not in allowed_source_ids:
                        raise PermissionError("source not eligible")
                    cfr_bundle = await get_cfr_section_bundle(
                        db, section_number=section_number, tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(0, to_cfr_rag_chunk(cfr_bundle, source_id=CFR_TITLE26_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

        # Live PolicyEngine-US household tax calculation — piggybacks on the
        # existing "tax" category rather than a new category key (the ingested
        # PolicyEngine parameter markdown is already category="tax", and a
        # separate category would just compete for the same query space). Not
        # a "real API" in the external sense — it's an in-process deterministic
        # calculation, gated behind ENABLE_TAX_CALCULATION_ENGINE since
        # policyengine-us is a heavy dependency (numpy/pandas + large parameter
        # tree). Fail-closed: only runs when income + filing status (the two
        # facts with no honest default) are confidently extractable from the
        # query; otherwise falls through unchanged to today's keyword_mvp/LLM
        # behavior. Isolated the same way as every other live source: a
        # calculation failure never breaks the rest of the answer.
        if (
            os.getenv("ENABLE_TAX_CALCULATION_ENGINE", "").lower() in {"1", "true", "yes"}
            and infer_category(request.query) == "tax"
            and POLICYENGINE_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            household = extract_household_params(request.query)
            if household is not None:
                try:
                    calc_bundle = await get_calculation_bundle(
                        db, household=household, tenant_id=tenant_id, actor_id=actor_id,
                    )
                    policyengine_result = calc_bundle
                    # Drop the raw PolicyEngine parameter-markdown chunks (title
                    # prefix "PolicyEngine-US Parameters —", per
                    # scripts/ingest_policyengine_topics.py's MANIFEST) once a
                    # real computed figure exists for this household — verified
                    # live (2026-07-20): with both present, the model discarded
                    # the correct computed CA state tax ($782.69, clearly
                    # labeled in the calc chunk) and instead reconstructed its
                    # own (wrong) bracket-rate arithmetic from the competing raw
                    # parameter chunks, landing on an admittedly-uncertain
                    # guess. Once a household resolves, the raw parameters are
                    # no longer the authoritative answer path — the computed
                    # chunk is, and it should not have to compete for the
                    # model's attention against 4 other same-topic chunks.
                    # IRS Direct File chunks are left alone — narrative/
                    # eligibility content, not a source of alternative numbers
                    # to redo arithmetic from.
                    raw_chunks[:] = [
                        c for c in raw_chunks
                        if not c.get("metadata", {}).get("title", "").startswith("PolicyEngine-US Parameters")
                    ]
                    raw_chunks.insert(0, to_calculation_rag_chunk(calc_bundle, source_id=POLICYENGINE_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

        # Sandboxed arithmetic expression evaluator — Phase 1 of the governed
        # calculation architecture (docs/calculation_architecture.md). Same
        # fail-closed, gated-injection posture as PolicyEngine above: only runs
        # when arithmetic_extraction.py can confidently resolve a single,
        # unambiguous expression from the query text; never guesses. Routed
        # through router.route() (not called directly) so a query naming a
        # professional-methodology calculation this codebase already has a
        # named formula for is never silently downgraded to raw arithmetic —
        # the router enforces that priority, this call site doesn't re-decide
        # it. On a verified result, the figure is injected as a governed RAG
        # chunk (same numeric-fidelity-matching text convention as
        # to_calculation_rag_chunk) AND registered in provenance_store, so
        # Checkpoint C accepts the derived figure even though — unlike every
        # other governed chunk — it was never true that a real document said
        # this number; a real calculation computed it.
        if (
            os.getenv("ENABLE_EXPRESSION_CALCULATION_ENGINE", "").lower() in {"1", "true", "yes"}
            and EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            expression = extract_arithmetic_expression(request.query)
            if expression is not None:
                try:
                    decision = route_calculation(CalculationRequest(calculation_type="arithmetic", expression=expression))
                    if decision.engine == ENGINE_EXPRESSION_EVALUATOR and decision.status == "executed":
                        record = decision.result
                        # 2026-07-23 real incident: with the calculation chunk
                        # present but dozens of unrelated real regulatory
                        # documents also still in context (a plain arithmetic
                        # query like "calculate the sales tax on..." routinely
                        # pulls in 20-29 real tax-content chunks), the model
                        # kept padding an otherwise-correct, already-verified
                        # answer with a broader explanation quoting that real
                        # content too closely — tripping the summarize-don't-
                        # copy check even after being told not to pad. A prompt
                        # instruction alone wasn't reliable enough. A pure
                        # arithmetic question needs nothing but the calculation
                        # itself, so — same posture as PolicyEngine's own
                        # competing-chunk removal above — drop every other
                        # chunk once a verified calculation exists; there is
                        # nothing else for the model to legitimately need here.
                        raw_chunks.clear()
                        raw_chunks.insert(0, to_expression_rag_chunk(record, source_id=EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID))
                        provenance_store.add(from_expression_record(record))
                        verified_calculation_bypasses_coverage_gate = True
                except Exception:
                    pass

        # Named formula registry — Phase 3 of the governed calculation
        # architecture, first real natural-language wiring: straight-line
        # depreciation. Same fail-closed extraction posture as the expression
        # evaluator above (formula_extraction.py never guesses a missing
        # input), routed through the same router.route() so the priority
        # ordering (never downgrade a named formula to raw arithmetic) is
        # enforced in one place. On a verified result: injects a governed RAG
        # chunk + provenance record (same as every other calculation engine)
        # AND builds an interactive CalculationWidget (sliders + a book-value
        # chart) attached to the final ComposedAnswer below — see
        # app/domains/calculation/widget.py.
        if (
            os.getenv("ENABLE_EXPRESSION_CALCULATION_ENGINE", "").lower() in {"1", "true", "yes"}
            and FORMULA_REGISTRY_GOVERNED_SOURCE_ID in allowed_source_ids
        ):
            formula_extraction = extract_named_formula(request.query)
            if formula_extraction is not None:
                formula_inputs = formula_extraction.inputs
                try:
                    decision = route_calculation(CalculationRequest(
                        calculation_type=formula_extraction.calculation_type, inputs=formula_inputs,
                    ))
                    if decision.engine == ENGINE_FORMULA_REGISTRY and decision.status == "executed":
                        formula_result = decision.result
                        executed_formula_result = formula_result
                        # Same fix, same reasoning as the expression evaluator
                        # block above — drop competing real content once a
                        # verified formula result exists.
                        raw_chunks.clear()
                        raw_chunks.insert(0, to_formula_rag_chunk(formula_result, source_id=FORMULA_REGISTRY_GOVERNED_SOURCE_ID))
                        provenance_store.add(from_formula_result(formula_result))
                        verified_calculation_bypasses_coverage_gate = True
                        calculation_widget = build_calculation_widget(formula_result, formula_inputs)
                except Exception:
                    pass
            else:
                missing_formula_inputs = identify_missing_formula_inputs(request.query)
                if missing_formula_inputs is not None:
                    raw_chunks.clear()
                    raw_chunks.insert(0, {
                        "text": (
                            f"The approved {missing_formula_inputs.calculation_type} formula cannot execute yet. "
                            f"Missing required inputs: {', '.join(missing_formula_inputs.missing_inputs)}. "
                            "No value may be guessed."
                        ),
                        "metadata": {
                            "source_id": FORMULA_REGISTRY_GOVERNED_SOURCE_ID,
                            "title": "Named Formula Registry — Missing Input Check",
                            "version": "1.0.0", "jurisdiction": "GLOBAL",
                        },
                        "score": 1.0,
                        "node_id": f"{FORMULA_REGISTRY_NODE_PREFIX}missing-input",
                    })

        # Live Federal Register single-document lookup — same fail-closed,
        # on-demand posture as the GovInfo CFR lookup above: only fetched when
        # the query names a specific document number.
        if infer_category(request.query) == "federal-register":
            document_number = extract_federal_register_document_number(request.query)
            if document_number is not None and FEDERAL_REGISTER_GOVERNED_SOURCE_ID in allowed_source_ids:
                try:
                    fr_bundle = await get_federal_register_document_bundle(
                        db, document_number=document_number, tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(0, to_federal_register_rag_chunk(fr_bundle, source_id=FEDERAL_REGISTER_GOVERNED_SOURCE_ID))
                except Exception:
                    pass

        # Congress.gov is identifier-driven rather than free-text search. Only a
        # complete bill number plus Congress number is safe to fetch; otherwise
        # normal retrieval/clarification handles the request without guessing.
        if infer_category(request.query) == "us-legislation" and CONGRESS_GOVERNED_SOURCE_ID in allowed_source_ids:
            bill_identifier = extract_congress_bill_identifier(request.query)
            if bill_identifier is not None:
                try:
                    congress, bill_type, bill_number = bill_identifier
                    congress_bundle = await get_congress_bill_bundle(
                        db, congress=congress, bill_type=bill_type, bill_number=bill_number,
                        tenant_id=tenant_id, actor_id=actor_id,
                    )
                    raw_chunks.insert(
                        0, to_congress_rag_chunk(congress_bundle, source_id=CONGRESS_GOVERNED_SOURCE_ID)
                    )
                except Exception:
                    pass

        # The Direct File fact dictionary describes the deduction workflow but
        # does not carry the enacted annual dollar table. For an exact annual
        # amount, enrich its governed chunk with the applicable IRS-published
        # figure before reranking and validation. Preserve the governed source id
        # so the normal eligibility and citation controls still apply.
        standard_deduction_fact = _standard_deduction_fact(request.query)
        if standard_deduction_fact is not None:
            governed_tax_chunk = next(
                (
                    chunk for chunk in raw_chunks
                    if "standard deduction" in chunk.get("metadata", {}).get("title", "").lower()
                    and chunk.get("metadata", {}).get("source_id")
                ),
                None,
            )
            if governed_tax_chunk is not None:
                raw_chunks.insert(0, _standard_deduction_chunk(governed_tax_chunk, standard_deduction_fact))

        # Domain-restricted public-authority discovery. Tavily is primary;
        # SerpAPI is invoked only when Tavily fails or yields no usable approved
        # page. Search content still needs an ACTIVE governed connector source,
        # survives the licence gate, and then passes normal reranking/citation/
        # answer validation like every other external source.
        professional_categories = {"standards", "tax", "audit", "payroll-compliance"}
        category = infer_category(request.query)
        search_source_ids = {TAVILY_GOVERNED_SOURCE_ID, SERPAPI_GOVERNED_SOURCE_ID}
        purpose_built_live_evidence = any(
            str(chunk.get("node_id", "")).startswith(_LIVE_DATA_NODE_PREFIXES)
            for chunk in raw_chunks
        )
        if (
            category in professional_categories
            and not purpose_built_live_evidence
            and allowed_source_ids.intersection(search_source_ids)
        ):
            try:
                search_bundle, provider = await get_professional_search_bundle(
                    db, query=request.query, tenant_id=tenant_id, actor_id=actor_id,
                )
                source_id = TAVILY_GOVERNED_SOURCE_ID if provider == "tavily" else SERPAPI_GOVERNED_SOURCE_ID
                if source_id in allowed_source_ids:
                    raw_chunks.extend(to_professional_search_chunks(search_bundle, source_id=source_id))
            except Exception:
                pass

        # Candidate ordering is finalised before bundle construction and risk
        # classification. This keeps the immutable bundle and the model context
        # aligned to the same evidence selection.
        ranked_chunks = raw_chunks
        # A single governed candidate cannot be reordered. Running the
        # cross-encoder here only loads a large model and adds several seconds to
        # deterministic user-data/procedure answers without changing selection.
        # Keep reranking for genuine multi-candidate retrieval only.
        if len(raw_chunks) > 1:
            try:
                ranked_chunks = await _reranker.rerank(request.query, raw_chunks)
                ranked_chunks = _reinstate_live_chunks(raw_chunks, ranked_chunks)
            except Exception:
                ranked_chunks = raw_chunks
        await audit_rerank_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            input_count=len(raw_chunks), output_count=len(ranked_chunks),
        )

        try:
            preliminary_bundle = await build_source_bundle(
                db, query=request.query, jurisdiction=request.jurisdiction, tenant_id=tenant_id,
                raw_chunks=ranked_chunks,
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
            # Checkpoint B re-verifies the selected candidates and resolves
            # display state at bundle assembly. Checkpoint A was recorded above.
            if licence_result.excluded:
                await audit_licence_denied(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
                    checkpoint="B", source_ids=[s.id for s in licence_result.excluded],
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

        # Coverage gate: a nearby source is not a substitute for the authority a
        # professional topic actually requires. For example, retrieving ASC 606
        # must never make an ASC 842 lease question appear answerable. This gate
        # runs after the immutable eligible bundle exists and before risk/model
        # routing, so its decision is evidence-based and no model is invoked.
        #
        # 2026-07-23 real incident: "Calculate the sales tax on a $1,200
        # purchase at a 7.25% rate." — the rate is right there in the query,
        # and the expression evaluator verified $87.00 from it — but this gate
        # fires on the literal phrase "sales tax" regardless, and unconditionally
        # short-circuited the response before the verified calculation was ever
        # used, discarding a fully self-contained, already-correct answer to ask
        # for an "approved state revenue authority source" the question never
        # needed. verified_calculation_bypasses_coverage_gate means the query's own figures
        # already produced a deterministic, verified result — no external
        # topical authority is missing for THAT number, whatever the coverage
        # rule's usual (correct, for a rate/rule LOOKUP question) concern is.
        coverage = assess_us_professional_coverage(request.query, source_bundle)
        await audit_coverage_assessed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            applies=coverage.applies, covered=coverage.covered,
            domain=coverage.domain, topic=coverage.topic,
            required_authority=coverage.required_authority,
        )
        if coverage.applies and not coverage.covered and not verified_calculation_bypasses_coverage_gate:
            await audit_clarification_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
                clarification_cycle=clarification_cycle,
            )
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="clarification_required", route=ROUTE_CLARIFICATION,
                safety=SafetyState(risk_level="MEDIUM", policy_state="needs_more_context"),
                confidence_state=CONF_INSUFFICIENT,
                source_bundle=source_bundle, answer=None,
                next_action=NextAction(
                    type=coverage.action,
                    message=coverage.message or coverage.reason,
                ),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
            await _finalise_and_return(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                outcome=response.outcome, route=response.route, start_time=start_time,
            )
            await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

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
        #
        # Run off the event loop thread: classify_after_bundle() is entirely
        # synchronous, and when ENABLE_ML_CLASSIFIER is on (the default), it can
        # run a real HuggingFace zero-shot inference call inside it — a blocking,
        # CPU-bound call that would otherwise stall every other concurrent
        # request being served by this worker for its duration. sync_db is only
        # touched sequentially within this awaited call, never concurrently from
        # another thread, so handing it to a worker thread here is safe.
        decision = await asyncio.to_thread(
            massarius_risk_safety.classify_after_bundle, True, classify_request, sync_db
        )
        risk_level = decision.risk_level
        # risk_classifier.classify() sets this to has_advice_signal — whether
        # the query names the reader's own situation ("my company", "should I
        # file") — not literally "a human review is required" despite the field
        # name; routing_matrix.py's HIGH+advice_signal override is what actually
        # decides that. See risk_classifier.py's comment on why it's exposed raw
        # here rather than pre-gated on risk_level == HIGH.
        advice_signal = bool(decision.requires_human_review)

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
            advice_signal=advice_signal,
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
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
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
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        if route == ROUTE_REFERRAL:
            # 2026-07-22 product vision doc, item 3 — replaces what used to be
            # the ROUTE_HUMAN_REVIEW branch below for this exact situation
            # (weak/conflicting confidence on a HIGH-risk query, or two
            # unresolved clarification cycles): no persisted review case, no
            # "waiting for a human" response. route_selected already recorded
            # risk_level/confidence_state/route above, which is the analytics
            # trail the vision doc says to keep — this just doesn't ALSO queue
            # it for manual follow-up.
            referral_category = infer_category(request.query)
            referral_text = referral_message(referral_category)
            referral_answer = build_validated_disclaimer(
                "Kriton can provide general educational information, but the available evidence is not sufficient "
                "to make a recommendation for your specific circumstances.",
                risk_level, True, effective_confidence,
            )
            referral_answer = referral_answer + "\n\n" + referral_text
            await audit_refusal_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, reason=f"Referral: risk={risk_level}, confidence={effective_confidence}",
            )
            response = AskKritonResponse(
                query_id=query_id,
                correlation_id=correlation_id,
                outcome="limited_response",
                route=ROUTE_REFERRAL,
                safety=safety_state,
                confidence_state=effective_confidence,
                source_bundle=source_bundle,
                answer=ComposedAnswer(text=referral_answer, citations=[], limitations=[]),
                next_action=None,
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
            await _finalise_and_return(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                outcome=response.outcome, route=route, start_time=start_time,
            )
            if idempotency_key:
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
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
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
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
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        # ── LLM Route ─────────────────────────────────────────────────────────────
        # Model gateway executes ONLY when route == LLM (§9)
        assert route == ROUTE_LLM

        # Reuses raw_chunks fetched once back in Step 4 — see the comment there.
        # Local dev should not block on Hugging Face model downloads just to serve
        # the API shell, login, and deterministic routing flows.
        context_text = ""
        rag_citations: list[SourceCitation] = []
        source_refs: list[dict] = []
        if ranked_chunks:
            try:
                eligible_ids = {source.id for source in source_bundle.sources} if source_bundle else set()
                context_chunks = [
                    chunk for chunk in ranked_chunks
                    if (chunk.get("metadata") or {}).get("source_id") in eligible_ids
                    and source_bundle.source_display_states.get(
                        (chunk.get("metadata") or {}).get("source_id"), "show"
                    ) != "internal_reasoning_only"
                ]
                context_text, source_refs = build_grounded_context(context_chunks)
                selected_chunks = context_chunks[:len(source_refs)]
                rag_citations = []
                for i, chunk in enumerate(selected_chunks):
                    # The chunk's real governed source_id (added to ingestion
                    # metadata earlier), not its own arbitrary vector node_id —
                    # citations should point at the actual catalog entry a
                    # user/reviewer could look up, not an internal chunk id.
                    # Falls back to node_id for chunks with no source_id
                    # (e.g. ingested outside the governance workflow) — that
                    # fallback has no real Source row, so it can never get a url
                    # (resolve_source_url would build a link nothing can serve).
                    governed_source_id = chunk["metadata"].get("source_id")
                    rag_citations.append(SourceCitation(
                        ref_id=f"REF-{i+1}",
                        source_id=governed_source_id or chunk.get("node_id", f"chunk-{i}"),
                        title=chunk["metadata"].get("title", "Uploaded Document"),
                        url=(
                            resolve_source_url(governed_source_id, chunk["metadata"].get("file_path"))
                            if governed_source_id else None
                        ),
                        evidence_preview=re.sub(r"\s+", " ", str(chunk.get("text", ""))).strip()[:1200],
                    ))
            except Exception:
                context_text = ""
                context_chunks = []
                selected_chunks = []

        dropped_chunks = context_chunks[len(source_refs):] if ranked_chunks else []
        dropped_count = len(dropped_chunks)
        await audit_context_fit_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            selected_count=len(source_refs), dropped_count=dropped_count,
        )
        # Context fitting deliberately discards low-ranked overflow.  That is not
        # a confidence failure by itself.  Re-route only if required/live evidence
        # was actually lost.
        mandatory_dropped = [chunk for chunk in dropped_chunks if _is_mandatory_context_chunk(chunk)]
        if mandatory_dropped:
            reevaluated = resolve_policy(
                confidence_state=CONF_LIMITED,
                risk_level=risk_level,
                jurisdiction=request.jurisdiction,
                clarification_cycle=clarification_cycle,
                advice_signal=advice_signal,
            )
            await audit_route_reevaluated(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
                previous_route=route, new_route=reevaluated.route,
                reason="context_fit_dropped_mandatory_sources",
            )
            effective_confidence = CONF_LIMITED
            route_decision = reevaluated
            route = reevaluated.route
            if route == ROUTE_REFERRAL:
                # Same handling as the main ROUTE_REFERRAL branch above — no
                # persisted review case, a real (limited) response with a
                # named professional. Duplicated rather than jumped-to because
                # this fires mid-composition, after source_refs/context_text
                # already exist; the main branch runs before any of that.
                referral_category = infer_category(request.query)
                referral_text = referral_message(referral_category)
                referral_answer = build_validated_disclaimer(
                    "Some of the evidence needed for a confident answer was not "
                    "available after fitting it to this response. " + referral_text,
                    risk_level, True, effective_confidence,
                )
                await audit_refusal_returned(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                    actor_id=actor_id, reason="Referral: context_fit_dropped_mandatory_sources",
                )
                response = AskKritonResponse(
                    query_id=query_id, correlation_id=correlation_id,
                    outcome="limited_response", route=ROUTE_REFERRAL,
                    safety=safety_state, confidence_state=effective_confidence,
                    source_bundle=source_bundle,
                    answer=ComposedAnswer(text=referral_answer, citations=[], limitations=[referral_text]),
                    next_action=None,
                    audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                )
                await _finalise_and_return(
                    db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                    audit_chain_id=audit_chain_id, actor_id=actor_id,
                    outcome=response.outcome, route=response.route, start_time=start_time,
                )
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
                return response
            if route == ROUTE_CLARIFICATION:
                await audit_clarification_returned(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                    actor_id=actor_id, clarification_cycle=clarification_cycle,
                )
                response = AskKritonResponse(
                    query_id=query_id, correlation_id=correlation_id,
                    outcome="clarification_required", route=ROUTE_CLARIFICATION,
                    safety=safety_state, confidence_state=effective_confidence,
                    source_bundle=source_bundle, answer=None,
                    next_action=NextAction(
                        type="ask_clarifying_question",
                        message=reevaluated.clarification_message or "Could you provide more context?",
                    ),
                    audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                )
                await _finalise_and_return(
                    db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                    audit_chain_id=audit_chain_id, actor_id=actor_id,
                    outcome=response.outcome, route=response.route, start_time=start_time,
                )
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
                return response
            if route == ROUTE_REFUSAL:
                await audit_refusal_returned(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                    actor_id=actor_id, reason="context_fit_dropped_mandatory_sources",
                )
                response = AskKritonResponse(
                    query_id=query_id, correlation_id=correlation_id,
                    outcome="refused", route=ROUTE_REFUSAL,
                    safety=safety_state, confidence_state=effective_confidence,
                    source_bundle=source_bundle, answer=None,
                    next_action=NextAction(type="refused", message="Kriton™ could not confirm this answer against reliable sources."),
                    audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                )
                await _finalise_and_return(
                    db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                    audit_chain_id=audit_chain_id, actor_id=actor_id,
                    outcome=response.outcome, route=response.route, start_time=start_time,
                )
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
                return response

        if not context_text:
            # §2: No unsupported answering — never let the model answer from its
            # own general knowledge when there's no retrieved context to ground
            # it. This is a separate guarantee from the risk-routing matrix, so
            # it applies even under FORCE_DIRECT_ANSWER (that flag only bypasses
            # the HIGH-risk escalation/refusal policy, not this one) — previously
            # this fell through to sending the bare query to the LLM instead.
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
            if idempotency_key:
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        await audit_composition_started(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        )

        # Build grounded prompt input
        reviewed_source_ids = {
            BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
            MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
            ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
            USER_PROVIDED_DATA_GOVERNED_SOURCE_ID,
        }
        # Reviewed educational/data routes compose deterministically below and
        # never invoke a prompt template or model provider. Avoid an unnecessary
        # remote prompt-table query on their critical path.
        has_reviewed_source = any(
            (chunk.get("metadata") or {}).get("source_id") in reviewed_source_ids
            for chunk in selected_chunks
        )
        prompt = None if has_reviewed_source else await select_prompt(db, request.mode)
        grounded_input = (
            f"You are Kriton, an experienced US accounting, tax, and audit professional "
            f"explaining this to a client or student face to face — not a search engine "
            f"reciting results. Interpret the retrieved context below and explain, in "
            f"your own plain-English words, what it actually means and why it matters "
            f"for the question asked. Restating a source's exact phrasing is not the "
            f"goal; understanding it and teaching it back clearly is.\n\n"
            f"This freedom has one hard boundary: every material fact, figure, date, or "
            f"rule you state must be grounded in the retrieved context below — cite it "
            f"with a [REF-N] marker. Explaining, connecting ideas, and adding "
            f"plain-language context around a cited fact is expected and encouraged; "
            f"inventing a new fact, number, or rule that is not in the context is not. "
            f"Do not use outside/general knowledge to introduce information the context "
            f"does not contain — only to help you explain what the context does contain "
            f"more clearly.\n\n"
            f"When asked for a rule's purpose or objective, lead with the primary objective "
            f"stated by the authority, rather than a supporting procedure or consequence. "
            f"Answer a definition question with a direct plain-language definition in the first sentence; "
            f"do not substitute internal calculation workflow for the definition. Cite every numbered "
            f"or bulleted substantive claim, not only the final item. "
            f"If the context does not address the query's exact wording but contains "
            f"closely related material, present that material directly as the answer "
            f"and state how it relates to what was asked — never open by saying no "
            f"relevant information exists and then go on to cite information that "
            f"contradicts that statement. But if NOTHING in the retrieved context "
            f"actually defines, discusses, or supports what was asked — not even "
            f"related material — say so plainly instead of answering from your own "
            f"general knowledge and attaching a citation to an unrelated passage. A "
            f"citation on a sentence means that passage backs the claim; citing a "
            f"passage that does not, just because the query needs an answer, is "
            f"worse than an uncited answer — it looks verified when it is not. "
            f"Write your answer in your own words: never copy "
            f"a source's raw internal formatting (key=value pairs, field names like "
            f"'category=' or 'rate_structure=', code identifiers) directly into the "
            f"answer text — restate what those fields mean in ordinary language "
            f"instead. If the query asks for a percentage and the source expresses "
            f"the same figure as a decimal fraction (e.g. a source value of 0.062 "
            f"for a query asking 'what percentage'), state it as a percentage (6.2%) "
            f"— that is a unit conversion of the real figure, not a different number, "
            f"so state it in the unit actually asked for.\n\n"
            f"Two more things a real professional would do that you must also do: "
            f"(1) If a concrete example would make the rule easier to understand, "
            f"include one — but build it only from figures, dates, and facts that "
            f"actually appear in the retrieved context (reuse a cited amount or "
            f"rate as the example), never an invented number. A fabricated "
            f"illustrative figure is indistinguishable from a fabricated real one "
            f"to the person reading it, so it is not permitted. If the retrieved "
            f"context contains no real figure to build a numeric example from, "
            f"illustrate with a qualitative, non-numeric example instead (describe "
            f"a situation and what happens, with no invented dollar amount or "
            f"rate) — do not reach for a plausible-looking number just because "
            f"an example without one feels incomplete; a qualitative example "
            f"that stays honest beats a numeric one that doesn't. "
            f"(2) If the retrieved context mentions any exceptions, conditions, "
            f"thresholds, or caveats that qualify the answer, state them explicitly "
            f"and cite them — do not present a rule as absolute or unconditional if "
            f"the source material shows it has limits.\n\n"
            f"Explain what a rule means and how it generally applies — do not phrase "
            f"it as a direct personal instruction to the reader. Write \"a single "
            f"filer's standard deduction is $X, which reduces taxable income by that "
            f"amount\" rather than \"you should file using...\" or \"you need to "
            f"declare...\" — describing what a rule does, and what someone in a "
            f"given situation would generally do under it, is teaching; telling this "
            f"specific reader what they personally must do is advice, and Kriton "
            f"never gives that. When citing, use only the bare [REF-N] marker inline "
            f"in your own sentence — never copy the \"[REF-N] Source: ... Jurisdiction: "
            f"...\" header line itself into your answer; that header is context "
            f"formatting, not something to quote.\n\n"
            f"Summarize, don't copy: even when a source's exact wording is available "
            f"and on-topic, do not reproduce a long passage verbatim just because it "
            f"is there. Extract the purpose and the key idea and state that in your "
            f"own words, at roughly the length a tutor would use out loud — a short "
            f"quoted phrase is fine when the precise wording matters (a defined term, "
            f"a statutory threshold), but the bulk of the answer should be your "
            f"compression of the source, not a transcription of it.\n\n"
            f"When the question asks you to explain a concept, rule, or standard "
            f"(rather than look up a single figure, date, or yes/no fact), teach it "
            f"the way a tutor would: use a short heading, then cover what it is, why "
            f"it exists, the basic rule, a simple grounded example, how it is "
            f"actually used in practice, and, only if the retrieved context supports "
            f"it, a brief note on where it came from. Skip this fuller structure for "
            f"narrow factual lookups where it would be padding rather than teaching — "
            f"answer those directly in a sentence or two instead.\n\n"
            f"Format the answer using real markdown, not description of formatting: "
            f"'## Heading' for section headings (use sparingly — only for a genuine "
            f"multi-part explanation, never for a one-line factual answer), '- ' for "
            f"bullet lists, and a GFM pipe table ('| Column | Column |' with a "
            f"'|---|---|' divider row) whenever the query asks to compare two or "
            f"more things, or the answer is naturally several items each with the "
            f"same few attributes (rates by jurisdiction, standards by framework, "
            f"pros/cons). Every fact placed in a table cell must still carry the "
            f"same grounding and citation requirements as a fact in prose — a table "
            f"is a layout choice, not an exemption from citing what backs it. Do not "
            f"force a table onto an answer that is naturally a single explanation. "
            f"When the user asks for steps, a process, a procedure, or a workflow, "
            f"use an actual numbered Markdown list ('1. ', '2. ', and so on), keep "
            f"the instructions operational, and do not add a conclusion that merely "
            f"repeats the introduction. Add an example only when the grounded context "
            f"contains a complete useful example; never emit placeholder amounts. "
            f"Never end the answer with your own 'References' or 'Sources' section — "
            f"the interface already renders one from your inline [REF-N] markers; "
            f"adding another one duplicates it and risks copying raw header text "
            f"into the answer, which is never allowed.\n\n"
            f"On material numbers — a governed calculation architecture, not you, "
            f"is the authority: you may propose a calculation (which figures to "
            f"combine and how), but you never compute or state a material "
            f"financial, tax, accounting, or audit result yourself. A material "
            f"number appearing in the retrieved context below already went "
            f"through a governed engine (PolicyEngine-US, a named accounting/tax/"
            f"audit formula, or the sandboxed expression evaluator) — quote that "
            f"exact figure, never recompute it, round it differently, or adjust "
            f"it. If a calculation the query needs was not already computed for "
            f"you in the retrieved context, say plainly that Kriton cannot verify "
            f"that specific calculation right now rather than performing it "
            f"yourself — an unverified number you compute in your own reasoning "
            f"is exactly the failure this rule exists to prevent. You may still "
            f"explain, compare, and contextualize any number that is already "
            f"present below.\n\n"
            f"Real incident this rule exists to prevent: asked 'If revenue is "
            f"$250,000 and expenses are $180,000, what is the net profit?', the "
            f"model ignored the query's own stated figures and instead computed "
            f"an answer from an unrelated retrieved document's revenue/expense "
            f"numbers, just because that document also used the words 'revenue' "
            f"and 'expenses' — producing a completely wrong, fabricated-looking "
            f"result. When the query itself states specific figures as the "
            f"premise of a question ('if revenue is $X and expenses are $Y, "
            f"what is...'), those user-supplied figures ARE the input — never "
            f"substitute a same-named figure from a retrieved document for them, "
            f"no matter how relevant that document otherwise looks. A retrieved "
            f"document's own revenue/expense/etc. figures only apply when the "
            f"query is actually asking about that specific document's real "
            f"entity, not when the query already gave you the numbers to use.\n\n"
            f"When the retrieved context below contains a verified calculation "
            f"chunk ('Deterministic arithmetic calculation' or a named-formula-"
            f"registry result), the query is a calculation question, not an "
            f"invitation to write a general essay on the topic — answer the way "
            f"a calculator would: state the calculation and the result directly "
            f"in 1-3 sentences, cited. Do not pad this with a full tutor-depth "
            f"explanation of the broader concept (what the tax/rule/method is, "
            f"why it exists, its history) pulled from other retrieved sources "
            f"unless the user's query separately, explicitly asked for that "
            f"explanation too — a 'calculate X' question wants X calculated, "
            f"not a lecture. This also keeps the answer from over-quoting "
            f"unrelated regulatory text it doesn't actually need.\n\n"
            f"=== Retrieved Context ===\n{context_text}\n\n"
            f"=== User Query ===\n{request.query}"
        )

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
        prompt_name = "Inline Context Prompt"

        try:
            standard_deduction_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if chunk.get("metadata", {}).get("fact_type") == "standard_deduction"
                ),
                None,
            )
            icfr_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if "pcaob as 2201" in chunk.get("metadata", {}).get("title", "").lower()
                ),
                None,
            ) if re.search(r"\b(?:purpose|objective)\b.*\b(?:icfr|as\s*2201)\b|\b(?:icfr|as\s*2201)\b.*\b(?:purpose|objective)\b", request.query, re.I) else None
            as2310_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if "as 2310" in chunk.get("metadata", {}).get("title", "").lower()
                    or "as2310" in str(chunk.get("metadata", {}).get("file_path", "")).lower()
                ),
                None,
            ) if re.search(r"\bas\s*2310\b", request.query, re.I) else None
            gdp_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if chunk.get("metadata", {}).get("source_id") == BEA_GDP_GOVERNED_SOURCE_ID
                ),
                None,
            )
            cpi_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if chunk.get("metadata", {}).get("source_id") == BLS_CPI_GOVERNED_SOURCE_ID
                ),
                None,
            )
            fred_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if chunk.get("metadata", {}).get("source_id") == FRED_INTEREST_RATES_GOVERNED_SOURCE_ID
                ),
                None,
            )
            congress_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if chunk.get("metadata", {}).get("source_id") == CONGRESS_GOVERNED_SOURCE_ID
                ),
                None,
            )
            reviewed_procedure_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if (chunk.get("metadata") or {}).get("source_id") in {
                        BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
                        MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
                        ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
                        USER_PROVIDED_DATA_GOVERNED_SOURCE_ID,
                    }
                ),
                None,
            )
            formula_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if str(chunk.get("node_id", "")).startswith(FORMULA_REGISTRY_NODE_PREFIX)
                ),
                None,
            )
            policyengine_chunk = next(
                (
                    (index, chunk) for index, chunk in enumerate(selected_chunks)
                    if str(chunk.get("node_id", "")).startswith(POLICYENGINE_NODE_PREFIX)
                ),
                None,
            )
            if policyengine_result is not None and policyengine_chunk is not None:
                index, _chunk = policyengine_chunk
                composed_text = _compose_policyengine_result(policyengine_result, request.query, f"REF-{index + 1}")
                prompt_id = "deterministic-policyengine-result"
                prompt_name = "Governed PolicyEngine Tax Response"
            elif missing_formula_inputs is not None and formula_chunk is not None:
                index, _chunk = formula_chunk
                names = ", ".join(name.replace("_", " ") for name in missing_formula_inputs.missing_inputs)
                composed_text = (
                    f"## Information needed\n\nTo run the governed "
                    f"**{missing_formula_inputs.calculation_type.replace('_', ' ')}** calculation, "
                    f"please provide: **{names}**. [REF-{index + 1}]\n\n"
                    "Kriton will not guess missing calculation inputs."
                )
                prompt_id = "deterministic-formula-missing-input"
                prompt_name = "Governed Formula Missing-Input Response"
            elif executed_formula_result is not None and formula_chunk is not None:
                index, _chunk = formula_chunk
                composed_text = _compose_formula_result(executed_formula_result, f"REF-{index + 1}", request.query)
                prompt_id = "deterministic-formula-result"
                prompt_name = "Governed Named Formula Response"
            elif reviewed_procedure_chunk is not None:
                index, chunk = reviewed_procedure_chunk
                ref = f"REF-{index + 1}"
                source_id = (chunk.get("metadata") or {}).get("source_id")
                if source_id == BANK_RECONCILIATION_GOVERNED_SOURCE_ID:
                    composed_text = compose_bank_reconciliation(request.query, ref)
                    prompt_name = "Deterministic Bank Reconciliation Response"
                elif source_id == MONTH_END_CLOSE_GOVERNED_SOURCE_ID:
                    composed_text = compose_month_end_close(request.query, ref)
                    prompt_name = "Deterministic Month-End Close Response"
                elif source_id == ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID:
                    composed_text = compose_accounting_fundamentals(request.query, ref)
                    prompt_name = "Deterministic Accounting Fundamentals Response"
                else:
                    composed_text = compose_quarterly_results(request.query, ref)
                    prompt_name = "Deterministic User-Provided Data Response"
                prompt_id = "deterministic-reviewed-education"
            elif standard_deduction_chunk is not None:
                index, chunk = standard_deduction_chunk
                verified_fact = _compose_standard_deduction(chunk, f"REF-{index + 1}")
                composed_text = await _explain_verified_fact(
                    db, prompt, verified_fact, request.query, actor_id, tenant_id, correlation_id,
                )
                prompt_id = "deterministic-standard-deduction"
                prompt_name = "IRS Annual Standard Deduction Response"
            elif as2310_chunk is not None:
                index, _chunk = as2310_chunk
                ref = f"REF-{index + 1}"
                verified_fact = (
                    "Under PCAOB AS 2310, the auditor designs and executes confirmations to obtain "
                    f"relevant and reliable evidence directly from knowledgeable external sources. [{ref}] "
                    "The auditor identifies the information and appropriate confirming parties, maintains "
                    f"control by sending requests and receiving responses directly, and evaluates response reliability and exceptions. [{ref}] "
                    "For nonresponses, incomplete responses, or unreliable responses, the auditor follows up "
                    f"and performs the alternative procedures required by the standard. [{ref}]"
                )
                composed_text = await _explain_verified_fact(
                    db, prompt, verified_fact, request.query, actor_id, tenant_id, correlation_id,
                )
                prompt_id = "deterministic-as2310"
                prompt_name = "PCAOB AS 2310 Requirements Response"
            elif icfr_chunk is not None:
                index, _chunk = icfr_chunk
                verified_fact = (
                    "Under PCAOB AS 2201, the auditor's objective in an audit of internal control "
                    "over financial reporting is to express an opinion on the effectiveness of the "
                    f"company's internal control over financial reporting. [REF-{index + 1}]"
                )
                composed_text = await _explain_verified_fact(
                    db, prompt, verified_fact, request.query, actor_id, tenant_id, correlation_id,
                )
                prompt_id = "deterministic-as2201-objective"
                prompt_name = "PCAOB AS 2201 Objective Response"
            elif cpi_chunk is not None and re.search(
                r"\b(current|latest|today|rate|number|cpi|consumer\s+price\s+index)\b",
                request.query,
                re.I,
            ):
                index, chunk = cpi_chunk
                composed_text = _compose_cpi_inflation(chunk.get("text", ""), f"REF-{index + 1}")
                prompt_id = "deterministic-bls-inflation"
                prompt_name = "BLS CPI Inflation Response"
            elif gdp_chunk is not None and re.search(r"\b(chart|graph|plot)\b.*\bgdp\b|\bgdp\b.*\b(chart|graph|plot|last\s+\d+\s+years?)\b", request.query, re.I):
                index, chunk = gdp_chunk
                composed_text = _compose_gdp_history(chunk.get("text", ""), f"REF-{index + 1}")
                prompt_id = "deterministic-gdp-history"
                prompt_name = "BEA GDP History Response"
            elif gdp_chunk is not None and re.search(r"\breal\s+gdp\b.*\b(?:percent|percentage|change)\b|\b(?:percent|percentage|change)\b.*\breal\s+gdp\b", request.query, re.I):
                index, chunk = gdp_chunk
                verified_fact = _compose_real_gdp_change(chunk.get("text", ""), f"REF-{index + 1}")
                composed_text = await _explain_verified_fact(
                    db, prompt, verified_fact, request.query, actor_id, tenant_id, correlation_id,
                )
                prompt_id = "deterministic-real-gdp"
                prompt_name = "BEA Real GDP Change Response"
            elif fred_chunk is not None:
                index, chunk = fred_chunk
                verified_fact = _compose_fred_rate(request.query, chunk.get("text", ""), f"REF-{index + 1}")
                composed_text = await _explain_verified_fact(
                    db, prompt, verified_fact, request.query, actor_id, tenant_id, correlation_id,
                )
                prompt_id = "deterministic-fred-rate"
                prompt_name = "FRED Latest Rate Response"
            elif congress_chunk is not None:
                # Congress.gov returns structured official facts — the record
                # itself is still extracted verbatim (never generated) so no
                # fact/date/latest-action can be dropped or altered, but the
                # user-facing text is now a real explanation wrapped around
                # that verbatim record rather than the raw record itself; see
                # _explain_verified_fact's docstring for why this is safe
                # (Checkpoint C validates the wrapped output exactly like any
                # other composed answer).
                index, chunk = congress_chunk
                verified_fact = _compose_congress_record(chunk.get("text", ""), f"REF-{index + 1}")
                composed_text = await _explain_verified_fact(
                    db, prompt, verified_fact, request.query, actor_id, tenant_id, correlation_id,
                )
                prompt_id = "deterministic-congress"
                prompt_name = "Congress.gov Structured Bill Response"
            elif prompt:
                prompt_row, composed_text = await model_gateway_service.run_test_prompt(
                    db, prompt.id, grounded_input, actor_id, tenant_id, correlation_id=correlation_id
                )
                composed_text = _strip_meta_preamble(composed_text) if composed_text else composed_text
                composed_text = _strip_trailing_raw_references(composed_text) if composed_text else composed_text
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
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        # Provider output occasionally copies the context envelope instead of
        # using only its bare citation marker. Remove envelopes everywhere, not
        # just inside a trailing Sources section, before citation assembly.
        if composed_text:
            composed_text = _strip_raw_source_headers(composed_text)

        # Some providers occasionally omit citation markers even though the
        # draft was composed from grounded context. Give composition one tightly
        # constrained repair pass before Checkpoint C: preserve the draft's
        # claims and wording, adding only valid markers from the supplied
        # context. The repaired output still passes the full validator; failure
        # to bind citations after this pass remains a human-review outcome.
        if composed_text and prompt and not re.search(r"\[REF-\d+\]", composed_text):
            repair_input = (
                "Add source citations to the draft below. Preserve every factual claim and do not "
                "introduce, remove, or alter facts. Add only [REF-N] markers that exist in the "
                "retrieved context, placing a marker after each supported substantive sentence. "
                "Return ONLY the repaired draft itself — no preamble, no introduction like "
                "\"Here's the repaired draft...\", start directly with the first word of the answer.\n\n"
                f"=== Retrieved Context ===\n{context_text}\n\n"
                f"=== Draft ===\n{composed_text}"
            )
            try:
                _repair_prompt, repaired_text = await model_gateway_service.run_test_prompt(
                    db, prompt.id, repair_input, actor_id, tenant_id, correlation_id=correlation_id,
                )
                repaired_text = _strip_meta_preamble(repaired_text) if repaired_text else repaired_text
                repaired_text = _strip_trailing_raw_references(repaired_text) if repaired_text else repaired_text
                repaired_text = _strip_raw_source_headers(repaired_text) if repaired_text else repaired_text
                if repaired_text and re.search(r"\[REF-\d+\]", repaired_text):
                    composed_text = repaired_text
                    prompt_name = f"{prompt_name} + citation repair"
            except Exception:
                pass

        # A request for a numeric worked example cannot be satisfied by replacing
        # every absent value with a placeholder. Treat that as missing evidence so
        # the user receives an honest clarification instead of a broken table.
        if (
            composed_text
            and _NUMERIC_RESULT_QUERY_PATTERN.search(request.query)
            and re.search(r"\bthe applicable (?:amount|rate)\b", composed_text, re.I)
        ):
            composed_text = ""

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

        # For non-numeric requests (for example, a numbered bank-reconciliation
        # procedure), models sometimes add invented dollar/percentage examples
        # even though the steps themselves are fully grounded. Generalize only
        # unsupported illustrative figures before the immutable output hash and
        # Checkpoint C. Exact-number/rate/calculation queries are never repaired
        # this way: an unsupported requested figure must still fail validation.
        if context_text and not _NUMERIC_RESULT_QUERY_PATTERN.search(request.query):
            generalized_text = generalize_unsupported_numeric_claims(
                composed_text,
                grounding_context=context_text,
                query_text=request.query,
                provenance=provenance_store,
            )
            if generalized_text != composed_text:
                composed_text = generalized_text
                prompt_name = f"{prompt_name} + numeric-example generalization"

        output_hash = hashlib.sha256(composed_text.encode()).hexdigest()[:32]
        await audit_composition_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, prompt_id=prompt_id, output_hash=output_hash,
        )

        rag_citations = assemble_citations(composed_text, rag_citations, source_bundle)
        await audit_citation_assembly_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            citation_count=len(rag_citations),
        )

        # ── Step 7: Post-composition validation — Massarius™ Checkpoint C
        # (§10, RG-03; ZL-ENG-03 §5.7) ────────────────────────────────────────────
        # Validated against composed_text (the model's own output), not the
        # disclaimer-appended text: the mandatory disclaimer is fixed boilerplate
        # we fully control, not model output, so content-safety checks (grounding,
        # citation binding, prohibited-claim, authority ceiling, confidence
        # support) shouldn't run against it — and in practice can't safely: the
        # disclaimer's own required wording ("does not constitute professional
        # ... tax, audit or legal advice") trips the prohibited-claim scanner,
        # which matches "legal advice" regardless of a preceding negation. Passing
        # disclaimer_required=False here skips checkpoint 6 (disclaimer presence)
        # for the same reason — build_validated_disclaimer below appends it
        # deterministically, so that check would only ever fail if this function
        # itself were broken, not the model's answer.
        # grounding_context=context_text feeds checkpoint 8 (numeric fidelity) —
        # every $/% figure the model claims must actually appear somewhere in
        # what it was given to read, catching invented numbers even when the
        # citation they're attached to is technically real.
        # provenance=provenance_store (governed calculation architecture, see
        # docs/calculation_architecture.md): a figure computed by the
        # expression evaluator/formula registry/PolicyEngine wrapper during
        # this request is accepted by checkpoint 8 even though it never
        # appears literally in a retrieved document's text — it was derived,
        # not retrieved, and the provenance record is how it's still verified
        # rather than exempted from verification.
        validation = (
            validate_answer(
                composed_text, source_bundle, disclaimer_required=False,
                grounding_context=context_text, query_text=request.query,
                provenance=provenance_store,
            )
            if source_bundle else None
        )
        final_text = build_validated_disclaimer(
            composed_text, risk_level,
            route_decision.disclaimer_required,
            effective_confidence,
        )
        if route_decision.professional_referral_required:
            # HIGH-risk hedged answer (advice signal, or weak-but-real
            # confidence) — per the 2026-07-22 product vision doc item 4, name
            # the specific kind of professional for this topic rather than a
            # generic "consult a professional." Appended after the disclaimer,
            # not before Checkpoint C validation above — this is presentation,
            # not a claim the validator needs to check for grounding/citations.
            final_text = final_text + "\n\n" + referral_message(infer_category(request.query))
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
                    next_action=NextAction(
                        type="escalate",
                        message=(
                            f"Kriton™ withheld the generated answer because {_validation_failure_summary(validation.failures)}. "
                            "It has been escalated for review."
                        ),
                    ),
                    audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                )
            elif validation.degraded_route == ROUTE_CLARIFICATION:
                await audit_clarification_returned(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
                    clarification_cycle=clarification_cycle,
                )
                response = AskKritonResponse(
                    query_id=query_id, correlation_id=correlation_id,
                    outcome="clarification_required", route=ROUTE_CLARIFICATION,
                    safety=SafetyState(
                        risk_level=risk_level, policy_state="needs_more_context",
                        disclaimer_required=route_decision.disclaimer_required,
                    ),
                    confidence_state=CONF_INSUFFICIENT,
                    source_bundle=source_bundle, answer=None,
                    next_action=NextAction(
                        type="insufficient_exact_evidence",
                        message=(
                            "Kriton™ found related sources, but they do not contain the exact fact requested. "
                            "Please provide the entity, applicable period, requested figures, or an authoritative "
                            "source containing that data. For a chart, you can also upload or paste the table to visualize."
                        ),
                    ),
                    audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                )
            else:
                await audit_refusal_returned(
                    db, query_id=query_id, correlation_id=correlation_id,
                    tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                    actor_id=actor_id, reason="Composition rejected: prohibited claim detected",
                )
                # 2026-07-23 real incident: "The IRS sent me an audit notice —
                # what should I do?" and similarly advice-signal-shaped queries
                # got a bare "Response validation failed. Please rephrase your
                # query." — the model's hedged attempt still slipped into
                # "you should file/submit..." personalized phrasing, tripping
                # the prohibited-claim scan, and this branch's generic message
                # dropped the disclaimer + professional referral the 2026-07-22
                # product vision doc's item 3 requires even on a refusal path
                # ("Refuse or limit the response. Show an appropriate
                # disclaimer. Direct the user to the right professional.") —
                # not just for the limited/hedged-answer path. The failed
                # composed_text itself is never surfaced (it's exactly what
                # tripped the scan); this is boilerplate, matching how
                # ROUTE_REFERRAL constructs its own message elsewhere.
                if route_decision.professional_referral_required:
                    refusal_message_text = (
                        "Kriton™ can't give a direct answer to this because it would cross "
                        "into personalized professional advice, which Kriton doesn't provide. "
                        f"{referral_message(infer_category(request.query))}\n\n"
                        f"{build_validated_disclaimer('', risk_level, True, effective_confidence).strip()}"
                    )
                else:
                    refusal_message_text = "Response validation failed. Please rephrase your query."
                response = AskKritonResponse(
                    query_id=query_id, correlation_id=correlation_id,
                    outcome="refused", route=ROUTE_REFUSAL,
                    safety=safety_state, confidence_state=effective_confidence,
                    source_bundle=source_bundle, answer=None,
                    next_action=NextAction(type="refusal", message=refusal_message_text),
                    audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                )
            await _finalise_and_return(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                outcome=response.outcome, route=response.route, start_time=start_time,
            )
            if idempotency_key:
                await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())
            return response

        # ── Step 8: Finalise response ─────────────────────────────────────────────
        # final_text already has the mandatory disclaimer (§10) applied above, and
        # has passed Checkpoint C validation against that same text.

        # final_text already contains the validated disclaimer. Limitations are
        # for distinct constraints; adding another disclaimer duplicated the UI.
        limitations: list[str] = list(decision.limitations or [])

        answer = ComposedAnswer(
            text=final_text,
            citations=rag_citations,
            limitations=limitations,
            calculation_widget=calculation_widget,
            presentation=build_answer_presentation(request.query, final_text),
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
            await store_idempotency(db, idempotency_key, tenant_id, response.model_dump())

        return response


async def ask_kriton(
    db: AsyncSession,
    sync_db: Session,
    *,
    actor_id: str,
    tenant_id: str,
    role: str,
    request: AskKritonRequest,
    idempotency_key: str,
    clarification_cycle: int = 0,
) -> AskKritonResponse:
    return await KritonMediator().handle(
        db,
        sync_db,
        actor_id=actor_id,
        tenant_id=tenant_id,
        role=role,
        request=request,
        idempotency_key=idempotency_key,
        clarification_cycle=clarification_cycle,
    )


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


def _validation_failure_summary(failures: list[str]) -> str:
    """Return a safe user-facing category without leaking validator internals."""
    categories = []
    mapping = (
        ("Citation binding", "its citations did not map cleanly to the retrieved evidence"),
        ("Numeric fidelity", "a numerical claim was not present in the retrieved evidence"),
        ("Prohibited-claim", "it crossed the professional-advice boundary"),
        ("Grounding check", "the available evidence did not support a substantive answer"),
        ("Repetition", "the generated response was incomplete or repetitive"),
        ("Authority ceiling", "the answer claimed more authority than its sources support"),
        ("Confidence support", "the answer was too certain for the available evidence"),
        ("Licence exposure", "a source could not be exposed under its licence controls"),
        ("Summarize-don't-copy", "it reproduced a source passage instead of explaining it"),
        ("Tutor-depth structure", "it did not cover the topic in enough depth for a teaching-style answer"),
    )
    joined = " ".join(failures)
    for marker, description in mapping:
        if marker.lower() in joined.lower() and description not in categories:
            categories.append(description)
    return "; and ".join(categories[:2]) or "it did not pass grounded-answer validation"


_META_PREAMBLE_PATTERN = re.compile(
    r"^\s*here'?s?\s+(?:is\s+)?the\s+(?:repaired|revised|updated|final)\s+"
    r"(?:draft|answer|response|text)[^\n]*:\s*\n+",
    re.IGNORECASE,
)


def _strip_meta_preamble(text: str) -> str:
    """Strips a leading "Here's the repaired draft with added source
    citations...:" style line some models prepend despite an explicit
    "return only the repaired draft" instruction — real incident
    (2026-07-22): the citation-repair pass below asked for exactly that,
    and the model's literal preamble sentence leaked into the answer the
    user saw, ahead of the real content. Defensive post-processing rather
    than trusting the instruction alone, same posture as
    _explain_verified_fact's prohibited-claims pre-check — an instruction
    is a strong nudge, not a guarantee, for a model this size."""
    return _META_PREAMBLE_PATTERN.sub("", text, count=1)


# 2026-07-22 real incident: a "Compare IFRS vs GAA" answer ended with a
# self-appended "References:" section quoting raw "[REF-N] Source: ..."
# header text verbatim — exactly the header-copying the composition prompt
# already says never to do (see grounded_input's "never copy the [REF-N]
# Source: ... header line itself" rule above), plus a garbled, truncated
# second entry ("IASB) has also issued..."). The frontend already renders
# a proper Sources panel from answer.citations, so a raw duplicate list in
# the answer body is redundant even when well-formed. Same defensive
# posture as _strip_meta_preamble: the prompt instruction is a nudge, this
# is the backstop. Only strips a TRAILING block anchored at end of string,
# so a legitimate sentence mentioning "references" mid-answer is untouched.
_TRAILING_RAW_REFERENCES_PATTERN = re.compile(
    r"\n{1,3}#{0,3}\s*(?:references|sources)\s*:?\s*\n"
    r"(?:\[REF-\d+\][^\n]*\n?)+\s*\Z",
    re.IGNORECASE,
)


def _strip_trailing_raw_references(text: str) -> str:
    return _TRAILING_RAW_REFERENCES_PATTERN.sub("", text).rstrip()


_RAW_SOURCE_HEADER_PATTERN = re.compile(
    r"(\[REF-\d+\])\s+Source:\s*.*?(?=\s+\[REF-\d+\]\s+Source:|\n|\Z)",
    re.IGNORECASE,
)


def _strip_raw_source_headers(text: str) -> str:
    """Keep citation markers while removing leaked internal context headers."""
    return _RAW_SOURCE_HEADER_PATTERN.sub(r"\1", text)


def _compose_formula_result(result, ref: str, query: str = "") -> str:
    """Render an executed FormulaResult without asking an LLM to redo it."""
    citation = f"[{ref}]"
    title = result.formula_id.split(".")[-2].replace("_", " ").title()
    detailed = bool(re.search(r"\b(explain|detailed|detail|show\s+(?:the\s+)?steps|breakdown|methodology|assumptions?)\b", query, re.I))

    def display_value(value: str, unit: str) -> str:
        try:
            number = Decimal(value)
            rendered = f"{number:,.2f}"
        except Exception:
            rendered = value
        if unit in {"USD", "annual_amount", "monthly_amount"}:
            suffix = " per year" if unit == "annual_amount" else " per month" if unit == "monthly_amount" else ""
            return f"${rendered}{suffix}"
        if unit == "percent":
            return f"{rendered}%"
        if unit == "ratio":
            return f"{rendered}×"
        return f"{rendered} {unit}".strip()

    result_display = display_value(result.output_value, result.output_unit)
    if not detailed:
        step_lines = "\n".join(f"- {step} {citation}" for step in result.steps)
        assumption_lines = "\n".join(f"- {assumption} {citation}" for assumption in result.assumptions)
        boundary = f"\n\n### Important assumptions\n\n{assumption_lines}" if assumption_lines else ""
        return (
            f"## {title}\n\n"
            f"### Result\n\n**{result_display}** {citation}\n\n"
            f"### Calculation\n\n{step_lines}"
            + boundary
            + f"\n\n*Verified with `{result.formula_id}` v{result.formula_version}; "
            f"calculation ID `{result.calculation_id}`.*"
        )

    input_rows = []
    for name, raw in result.inputs.items():
        value = raw.get("value", "") if isinstance(raw, dict) else raw
        unit = raw.get("unit", "") if isinstance(raw, dict) else ""
        input_rows.append(f"| {name.replace('_', ' ').title()} | {value} | {unit} |")
    step_lines = "\n".join(f"{index}. {step} {citation}" for index, step in enumerate(result.steps, 1))
    assumption_lines = "\n".join(f"- {assumption} {citation}" for assumption in result.assumptions)
    assumptions = f"\n\n### Assumptions and judgment boundaries\n\n{assumption_lines}" if assumption_lines else ""
    return (
        f"## {title}\n\n"
        f"### Verified result\n\n"
        f"**{result_display}** {citation}\n\n"
        f"### Inputs\n\n| Input | Value | Unit |\n|---|---:|---|\n"
        + "\n".join(input_rows)
        + f"\n\n### Calculation steps\n\n{step_lines}"
        + assumptions
        + f"\n\n### Methodology and audit trail\n\n{result.methodology_reference} {citation}\n\n"
        f"Calculation ID: `{result.calculation_id}` · Formula: `{result.formula_id}` · "
        f"Version: `{result.formula_version}` · Rounding: `{result.rounding_policy}`"
    )


def _compose_policyengine_result(result, query: str, ref: str) -> str:
    citation = f"[{ref}]"
    q = query.lower()
    if "eitc" in q or "earned income" in q:
        variable, label = "eitc", "Earned Income Tax Credit"
    elif "child tax credit" in q or re.search(r"\bctc\b", q):
        variable, label = "ctc", "Child Tax Credit"
    elif "standard deduction" in q:
        variable, label = "standard_deduction", "Standard Deduction"
    else:
        variable, label = "income_tax", "Federal Income Tax"
    value = result.values.get(variable)
    if value is None:
        return f"## Information needed\n\nKriton could not verify the requested tax output from the supplied inputs. {citation}"
    household = result.household
    filing = household.filing_status.replace("_", " ").title()
    dependents = f"{household.num_dependents} dependent{'s' if household.num_dependents != 1 else ''}"
    return (
        f"## {label}\n\n### Calculated result\n\n"
        f"**${value:,.2f}** {citation}\n\n"
        f"This PolicyEngine-US calculation used tax year **{household.tax_year}**, "
        f"filing status **{filing}**, employment income **${household.annual_income:,.2f}**, "
        f"and **{dependents}**. {citation}\n\n"
        "The figure is a deterministic model result based on the supplied household inputs. "
        "Eligibility, filing positions, and facts not included in the request may change the real-world result."
    )


def _compose_congress_record(context_text: str, ref_id: str) -> str:
    """Render an official structured bill lookup with an unavoidable citation."""
    lines = [line.strip() for line in context_text.splitlines() if line.strip()]
    if not lines:
        return ""
    concise_lines = [
        line for line in lines
        if not line.startswith("- Latest CRS summary:")
    ]
    concise_record = "\n".join(concise_lines)
    return (
        "According to the current Congress.gov bill record:\n\n"
        f"{concise_record}\n\n[{ref_id}]"
    )


_STANDARD_DEDUCTION_AMOUNTS = {
    2023: {"single": 13_850, "married filing separately": 13_850, "head of household": 20_800, "married filing jointly": 27_700},
    2024: {"single": 14_600, "married filing separately": 14_600, "head of household": 21_900, "married filing jointly": 29_200},
    2025: {"single": 15_750, "married filing separately": 15_750, "head of household": 23_625, "married filing jointly": 31_500},
    2026: {"single": 16_100, "married filing separately": 16_100, "head of household": 24_150, "married filing jointly": 32_200},
}


def _standard_deduction_fact(query: str) -> dict | None:
    if not re.search(r"\bstandard deduction\b", query, re.I):
        return None
    year_match = re.search(r"\b(202[3-6])\b", query)
    if not year_match:
        return None
    lowered = query.lower()
    filing_status = next(
        (status for status in ("married filing separately", "married filing jointly", "head of household", "single") if status in lowered),
        None,
    )
    if filing_status is None:
        return None
    year = int(year_match.group(1))
    urls = {
        2023: "https://www.irs.gov/pub/irs-prior/p501--2023.pdf",
        2024: "https://www.irs.gov/publications/p17/ar01.html",
        2025: "https://www.irs.gov/irb/2025-45_IRB",
        2026: "https://www.irs.gov/newsroom/irs-releases-tax-inflation-adjustments-for-tax-year-2026-including-amendments-from-the-one-big-beautiful-bill",
    }
    return {"year": year, "filing_status": filing_status, "amount": _STANDARD_DEDUCTION_AMOUNTS[year][filing_status], "url": urls[year]}


def _standard_deduction_chunk(governed_chunk: dict, fact: dict) -> dict:
    metadata = dict(governed_chunk.get("metadata", {}))
    metadata.update({
        "title": f"IRS — {fact['year']} Standard Deduction",
        "jurisdiction": "US",
        "file_path": fact["url"],
        "fact_type": "standard_deduction",
        "year": fact["year"],
        "filing_status": fact["filing_status"],
        "amount": fact["amount"],
    })
    return {
        **governed_chunk,
        "text": (
            f"IRS annual standard deduction for tax year {fact['year']}: "
            f"{fact['filing_status']} — ${fact['amount']:,}."
        ),
        "metadata": metadata,
        "score": 1.0,
    }


def _compose_standard_deduction(chunk: dict, ref_id: str) -> str:
    metadata = chunk["metadata"]
    status = metadata["filing_status"]
    return (
        f"For tax year {metadata['year']}, the basic standard deduction for a "
        f"{status} filer is ${metadata['amount']:,}. [{ref_id}]"
    )


def _compose_real_gdp_change(context_text: str, ref_id: str) -> str:
    match = re.search(
        r"Real GDP percent change from the preceding quarter at an annual rate \(([^)]+)\):\s*([-\d.]+)%",
        context_text,
        re.I,
    )
    if not match:
        return ""
    period, value = match.groups()
    return (
        f"In {period}, US real GDP changed at an annual rate of {value}% from the "
        f"preceding quarter, according to the latest BEA observation in the retrieved evidence. [{ref_id}]"
    )


def _compose_cpi_inflation(context_text: str, ref_id: str) -> str:
    match = re.search(
        r"12-month \(year-over-year\) inflation rate:\s*([-\d.]+)%\s*"
        r"\(from ([\d.]+) in (.+?) to ([\d.]+) in ([^)]+)\)",
        context_text,
        re.I,
    )
    if not match:
        return "The latest BLS CPI evidence did not contain a complete same-month year-over-year comparison."
    rate, prior_value, prior_period, latest_value, latest_period = match.groups()
    return (
        "## US inflation\n\n"
        f"The latest available 12-month CPI-U inflation rate is **{rate}%**, measured from "
        f"{prior_value} in {prior_period} to {latest_value} in {latest_period}. [{ref_id}]\n\n"
        "This is a dated BLS observation, not a real-time estimate."
    )


def _compose_gdp_history(context_text: str, ref_id: str) -> str:
    rows = re.findall(r"^- (\d{4}):\s*([-\d.]+)%$", context_text, re.MULTILINE)
    if not rows:
        return "The retrieved BEA evidence did not contain a complete annual GDP-growth series."
    table = "\n".join(f"| {year} | {value}% |" for year, value in rows[-5:])
    return (
        "## US real GDP growth\n\n"
        "The table shows the latest five annual real GDP growth observations available in the retrieved BEA evidence. "
        f"[{ref_id}]\n\n| Year | Real GDP growth |\n|---|---:|\n{table}\n\n"
        "The chart is generated from this validated table."
    )
def _compose_fred_rate(query: str, context_text: str, ref_id: str) -> str:
    lowered = query.lower()
    if "10-year" in lowered or "10 year" in lowered:
        label = "10-Year Treasury Constant Maturity Rate"
    elif "30-year treasury" in lowered or "30 year treasury" in lowered:
        label = "30-Year Treasury Constant Maturity Rate"
    elif "federal funds" in lowered or "fed funds" in lowered:
        label = "Federal Funds Effective Rate"
    elif "prime" in lowered:
        label = "Bank Prime Loan Rate"
    elif "mortgage" in lowered:
        label = "30-Year Fixed Rate Mortgage Average"
    else:
        return ""
    match = re.search(
        rf"- {re.escape(label)} \([A-Z0-9]+\):\s*([-\d.]+)% \(as of ([^)]+)\)",
        context_text,
    )
    if not match:
        return ""
    value, date = match.groups()
    trend_match = re.search(
        rf"- {re.escape(label)} \([A-Z0-9]+\):.*?\n\s*One-year window: "
        r"([-\d.]+)% on ([\d-]+) to ([-\d.]+)% on ([\d-]+) "
        r"\(([+-][\d.]+) percentage points\)",
        context_text,
    )
    if re.search(r"\b(past|last|over)\s+(?:the\s+)?year\b", lowered) and trend_match:
        start_value, start_date, end_value, end_date, change = trend_match.groups()
        direction = "increased" if float(change) > 0 else "decreased" if float(change) < 0 else "was unchanged"
        return (
            f"Over the available one-year window, the {label.lower()} {direction} from "
            f"{start_value}% on {start_date} to {end_value}% on {end_date}, a change of "
            f"{abs(float(change)):.2f} percentage points. [{ref_id}]"
        )
    return f"The latest {label.lower()} is {value}% as of {date}. [{ref_id}]"


async def _explain_verified_fact(
    db: AsyncSession,
    prompt,
    verified_fact: str,
    query: str,
    actor_id: str | None,
    tenant_id: str,
    correlation_id: str | None,
) -> str:
    """Wraps an already-verified, precisely-worded fact (with its [REF-N]
    citation) in a real explanation instead of returning that raw sentence
    as the whole answer — the deterministic _compose_*() functions above
    exist to GUARANTEE the number/date itself is correct (regex-extracted
    from the actual chunk text, never generated), not to decide what the
    user sees verbatim. Kriton should read like a professional explaining
    the fact, not a search result pasting it.

    The fact's number, date, and citation marker are treated as fixed
    ground truth the model must restate exactly, not something it composes
    freely — but this isn't blind trust: the SAME Checkpoint C validator
    (answer_validator.py's numeric-fidelity and citation-binding checks)
    that runs on every other composed answer also runs on this one further
    down in ask_kriton(), so a model that quietly alters the pinned number
    gets caught and escalated to human review downstream, exactly like any
    other composition drift would be — this isn't a special trusted path.

    Falls back to the raw verified_fact sentence (today's behavior, before
    this existed) if no prompt is configured or the explanation call fails
    for any reason — the reliability floor this replaces is preserved
    unconditionally, explanation is only ever additive on top of it.

    Some callers' _compose_*() functions (GDP, FRED, Congress) return ""
    when their own regex extraction found nothing to verify — that empty
    string must keep meaning "no content" downstream (the same
    `if not composed_text` insufficient-sources handling every other empty
    composition hits), not get sent to the model as an empty fact to
    explain, which would just invite it to fabricate one."""
    if prompt is None or not verified_fact:
        return verified_fact
    explain_input = (
        "The sentence below is an already-verified fact with its citation marker — "
        "treat every number, date, and the citation marker itself as fixed ground "
        "truth. Do not alter, round, add to, or restate it with a different figure. "
        "Explain what it means in plain, accessible language, the way a knowledgeable "
        "accounting/tax/audit professional would explain it to the person who asked — "
        "two to four sentences, and include the verified sentence's exact citation "
        "marker inline in your own sentence (never copy a full \"[REF-N] Source: "
        "... Jurisdiction: ...\" header line, only the bare marker). Explain what "
        "the fact means and how it generally applies — do not phrase it as a "
        "direct personal instruction to this specific reader (avoid \"you should "
        "file/pay/submit/declare...\"); describing what the rule is and does is "
        "teaching, telling this reader what they personally must do is advice, "
        "and that is not permitted here.\n\n"
        f"=== Verified Fact ===\n{verified_fact}\n\n"
        f"=== User Query ===\n{query}"
    )
    try:
        _explain_prompt, explained = await model_gateway_service.run_test_prompt(
            db, prompt.id, explain_input, actor_id, tenant_id, correlation_id=correlation_id,
        )
        explained = _strip_meta_preamble(explained) if explained else explained
        # Pre-check against the same prohibited-claim patterns Checkpoint C
        # enforces downstream (answer_validator.py) — real incident
        # (2026-07-22): the instruction above wasn't enough on its own, the
        # model explained the standard-deduction fact with "you should file
        # using..." phrasing, which is exactly what that check exists to
        # block, and the whole query surfaced as "Response validation
        # failed" (REFUSAL) instead of falling back to the safe raw fact.
        # Checking here means a prompt-following slip degrades quietly to
        # today's plain sentence instead of failing the user's query outright.
        if (
            explained
            and re.search(r"\[REF-\d+\]", explained)
            and not any(pattern.search(explained) for pattern in _PROHIBITED)
        ):
            return explained
    except Exception:
        pass
    return verified_fact


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
