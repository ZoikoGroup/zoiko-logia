"""
Ask Kriton™ orchestration service — ZL-ENG-02 §3 canonical 8-step flow.

Canonical flow:
  1. Generate identifiers
  2. Validate request
  3. Pre-screen safety (BEFORE retrieval) — Release Gate RG-01
  4. Retrieve a rights-filtered passage bundle and persist its replay manifest
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
import logging
import time
import os
from datetime import date
import re
import json
from contextvars import ContextVar
from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import HTTPException
from app.domains.model_gateway.errors import ProviderRequestRejected, ProviderResponseIncomplete
from app.orchestration.fx_profit import latest_fx_requested, fresh_fx_sources, grounded_fx_profit
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.orchestration.identifiers import (
    generate_query_id, generate_correlation_id,
    generate_audit_chain_id,
    check_idempotency, claim_idempotency, store_idempotency,
)
from app.orchestration.prescreen import run_prescreen
from app.orchestration import claim_verification
from app.orchestration.evidence_narrative import ground_causal_claims
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.agent_plan import WRITE_REQUEST_NOTICE, plan_request
from app.orchestration.answer_formatting import renumber_ordered_lists, separate_headings
from app.orchestration.citation_spans import evidence_by_ref, exact_spans
from app.orchestration import workflow_state
from app.orchestration.professional_boundary import CERTIFICATION_REFUSAL, requests_tax_certification
from app.orchestration.series_summary import ground_series_summary
from app.orchestration.retrieve import build_source_bundle
from app.orchestration.routing_matrix import (
    map_safety_confidence,
    ROUTE_LLM, ROUTE_REFUSAL, ROUTE_CLARIFICATION,
    ROUTE_HUMAN_REVIEW, ROUTE_SECURITY_INCIDENT, ROUTE_REJECTED,
    CONF_INSUFFICIENT, CONF_LIMITED, CONF_SUFFICIENT,
)
from app.orchestration.persisted_objects import create_review_case, create_security_incident_sync
from app.orchestration.schemas import (
    AskKritonRequest, AskKritonResponse,
    ComposedAnswer, SourceCitation, SafetyState, NextAction, AuditReference,
    GeneratedArtifactPublic,
)
from app.orchestration.audit_events import (
    audit_agent_tool_called, audit_agent_completed, audit_calculation_receipt, audit_agent_plan,
    audit_query_received, audit_request_validated, audit_request_rejected,
    audit_prescreen_completed, audit_retrieval_started, audit_retrieval_completed,
    audit_retrieval_failed, audit_risk_classified, audit_route_selected,
    audit_composition_started, audit_composition_completed, audit_composition_failed,
    audit_composition_rejected, audit_human_review_created, audit_refusal_returned,
    audit_release_check_degraded, audit_release_check_completed,
    audit_clarification_returned, audit_security_incident_recorded,
    audit_response_finalised, audit_response_returned, audit_answer_statements_removed,
    audit_answer_figure_provenance,
    audit_licence_prefilter_completed, audit_licence_denied,
    audit_bundle_built, audit_validation_completed,
    audit_redaction_applied,
    audit_document_retrieval,
    audit_artifact_generation_failed,
    audit_calculation_completed,
    audit_context_resolved,
)
from app.domains.risk_safety.schemas import ClassifyRequest, SafetyDecision
from app.domains.model_gateway import service as model_gateway_service
from app.orchestration import answer_cache
from app.domains.model_gateway.agent import chart_requested, is_agent_clarification, with_agent_instructions
from app.domains.identity.permissions import permissions_for_role
from app.orchestration.conversation import bare_chart_hint, conversation_prompt, screened_history
from app.domains.risk_safety.refusal_templates import get_template as get_refusal_template
from app.orchestration.compose import select_prompt
from app.orchestration.redaction import redact_for_external_exposure
from app.orchestration.websearch import (
    search_focus,
    sub_questions,
    web_search_each,
    build_web_grounded_prompt,
    web_search,
)
from app.orchestration.dbnomics import countries_in_query
from app.domains.market_data.registry import detect_intent as detect_market_data_intent
from app.orchestration.market_data import _OWNERSHIP_HINTS, _OWNERSHIP_STRUCTURE_CHART_HINT
from app.orchestration.document_evidence import build_document_evidence
from app.orchestration.evidence import EvidenceModel, Entity, Relationship
from app.orchestration.extraction import extract_graph, extract_user_visual_evidence
from app.orchestration.intent_classifier import (
    classify_intent, GRAPH_INTENTS, PROCESS, DISTRIBUTION, TREND,
    CURRENT_METRIC, PRECISE_DATA, COMPOSITION,
)
from app.orchestration.data_shape import classify_data_shape
from app.orchestration.response_planner import (
    plan_response, detect_explicit_visual_request, detect_requested_chart_variant,
)
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization import telemetry as viz_telemetry
from app.orchestration.query_classifier_shadow import log_shadow_comparison
from app.orchestration.risk_llm import calibrate_calculation_risk, classify_risk, classify_risk_gemini
from app.domains.kriton_workspace.documents import (
    expired_attachment_names, retrieve_document_sources, resolve_conversation_document_ids,
)
from app.domains.kriton_workspace.artifacts import create_generated_artifact
from app.orchestration.document_pipeline import (
    analyse_spreadsheet_sources,
    build_document_generation_prompt,
    plan_document_task,
)
from app.orchestration.calculations import calculate_from_query
from app.orchestration.calculations.engine import calculation_markdown
from app.domains.source_library.service import record_source_usages
from app.orchestration.frankfurter import _find_currencies
from app.orchestration.live_data import build_forced_chart, fetch_live_data, LiveDataResult
from app.orchestration.calculation_service import (
    build_calculation, is_self_contained_calculation, needs_lookup, validate_answer_calculations,
)
from app.domains.calculations.service import persist_run as persist_calculation_run
from app.orchestration.telemetry import StageMetrics, current_stage_metrics
from app.orchestration.task_context import (
    ResolutionInput,
    prompt_context as build_task_prompt_context,
    resolve_task_context,
)
from app.orchestration.workflow_planner import apply_plan, plan_workflow
from app.orchestration.derived_output import derived_output_instructions, is_derived_output_request
from app.core.config import get_settings
from app.orchestration.review_mode import is_review_request, review_pasted_text
from app.orchestration import planner_shadow
from app.orchestration.supplied_context import missing_in_supplied_context
from app.orchestration.calculations.engine import change_followup
from app.orchestration.answer_relevance import off_topic, recompose_instruction, topics_in
from app.domains.identity.authorization import (
    ASK, DOCUMENT_READ, MODEL_TRANSMIT, authorize, list_authorized_engagements,
)

# Massarius™ retrieval and evidence subsystem — Phase 1 control modules
# (ZL-ENG-03). These wrap/replace the inline licence filtering, bundle
# construction, and answer validation that used to happen ad hoc in this
# file; retrieve.py itself is unchanged — its output is now treated as
# preliminary retrieval-layer output that these modules gate and finalise.
from app.domains.massarius import bundle_builder, license_gate
from app.domains.massarius import risk_safety as massarius_risk_safety
from app.domains.massarius.answer_validator import is_directive_failure, validate_answer
from app.domains.massarius.policy_matrix import resolve_policy


logger = logging.getLogger("kriton.orchestration")


_TOOL_PROGRESS = {
    "get_exchange_rate": "Fetching live exchange rates",
    "get_economic_indicator": "Fetching official economic statistics",
    "get_market_data": "Fetching market data",
    "calculate": "Calculating",
    "render_chart": "Building chart",
    "search_knowledge_base": "Searching the knowledge base",
}


def _hash_query(query: str) -> str:
    """Hash query text — raw query text is not stored in plaintext per §13 RG-04."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:32]


_SAME_DATA_REFERENCE = re.compile(
    r"\b(?:same|previous|above|that)\s+(?:data|series|figures?|values?|chart|graph|table)\b|"
    r"\b(?:show|render|display|plot)\s+(?:it|them)\s+as\b|"
    r"\b(?:change|convert|make|turn)\s+(?:that|this|it|them)\s+(?:to|into|as)\b|"
    r"\bthe\s+(?:underlying|raw|source)\s+(?:data|table|figures?|values?|numbers?)\b|"
    r"\bshow\s+(?:me\s+)?the\s+table\b",
    re.I,
)


_ELLIPTICAL_FOLLOW_UP = re.compile(
    r"^\s*(?:what|how)\s+about\b|"
    r"^\s*(?:and|also|instead|then)\b|"
    r"\bdo\s+the\s+same\b|"
    r"\buse\s+(?:it|them|that)\b|"
    r"\b(?:show|render|display|plot)\s+(?:this|that)\s+as\b|"
    # A hypothetical change to the figures already on the table: "Suppose our
    # supplier cuts prices so cost of sales drops 10% — where does that leave
    # the margin?" was planned as web research and answered "the sources do
    # not contain the figures" (int-followup-cost-down-paraphrase).
    r"^\s*(?:suppose|assume|imagine|what\s+if)\b|\bwhere\s+does\s+(?:that|this)\s+leave\b|"
    r"\bon\s+top\s+of\s+that\b",
    re.I,
)


_UNDER_SPECIFIED_METRIC_FORMAT = re.compile(
    r"\b(?:CPI|inflation|GDP|unemployment|interest rate|exchange rate)\b"
    r".{0,80}\b(?:as|using)\s+(?:an?\s+)?(?:line|bar|area|step|spline|horizontal|vertical|"
    r"grouped|stacked|scatter|table|chart|graph)",
    re.I,
)


def _looks_like_contextual_follow_up(query: str) -> bool:
    """Return True only for high-confidence references to an earlier turn.

    A named country makes a metric/chart request self-contained. A bare
    metric plus a presentation change (for example, "Show CPI as a bar
    chart") remains contextual so an earlier jurisdiction is preserved.
    """
    text = query or ""
    from app.orchestration.calculations.inventory_statement import _inventory_revision
    if _inventory_revision(text) is not None:
        return True
    if re.match(r'^\s*(?:(?:correct|change|set|increase|decrease)\s+only\s+(?:depreciation|rent|utilities|salaries|marketing|purchase returns|sales returns|outstanding cheques|variable cost)\b|(?:the )?actual invoice arrives\b|change the chart to\b|customers receive refunds\b|show only a table\b)',text,re.I):
        return True
    if _SAME_DATA_REFERENCE.search(text) or _ELLIPTICAL_FOLLOW_UP.search(text):
        return True
    return bool(_UNDER_SPECIFIED_METRIC_FORMAT.search(text) and not countries_in_query(text))


def _with_previous_context(
    query: str,
    previous_query: str | None,
    *,
    clarification_cycle: int = 0,
) -> str:
    """Add the preceding request only when the current turn depends on it.

    Current wording stays first so its requested output form wins. Relevant
    combined text remains subject to the existing pre-screen before retrieval.
    Clarification replies always retain context because short answers such as
    a jurisdiction or year are intentionally incomplete on their own.
    """
    current = (query or "").strip()
    previous = (previous_query or "").strip()
    if not previous:
        return current
    if clarification_cycle <= 0 and not _looks_like_contextual_follow_up(current):
        return current
    return f"{current}\n\nPrevious user request for context: {previous}"


def _should_reuse_previous_evidence(query: str) -> bool:
    """Only explicit formatting follow-ups inherit the previous evidence.

    A question that names its own countries ("Compare inflation in India, the
    US and the UK ... show it as a chart") has a subject of its own, so a
    failed live lookup must not swap in the previous turn's series."""
    if countries_in_query(query or ""):
        return False
    return bool(_SAME_DATA_REFERENCE.search(query or ""))


_MODEL_DOMAIN_REFUSAL = "designed to answer questions related to Accounting"
# The model sometimes declines an off-topic question in its own words ("I'm
# sorry, but I can't help with that.") instead of the fixed domain message,
# and it was then shown as an answer with disclaimers attached.
_GENERIC_REFUSAL = re.compile(
    r"^\W*(i'?m|i am)?\s*(sorry|afraid)?[,.]?\s*(but\s+)?i\s+(can'?t|cannot|am unable to|won'?t)\s+"
    r"(help|assist|answer)", re.I,
)
_MODEL_DOMAIN_REFUSAL_TEXT = (
    "I'm designed to answer questions related to Accounting, Taxation, Payroll, "
    "Finance, Auditing, Bookkeeping, Commerce, and Accounting Education across "
    "global countries.\n\nPlease ask a question related to these topics."
)
_MODEL_PROVIDER_FAILURE = "Kriton is temporarily unable to reach the language model provider."
# Prefix of the gateway's spend-limit message (_PROVIDER_SPEND_LIMIT_MESSAGE in
# model_gateway/service.py). A substring check, so the gateway's longer,
# user-facing sentence is recognised here.
_MODEL_PROVIDER_SPEND_LIMIT = (
    "Kriton is temporarily unavailable because the AI provider has reached its configured spending limit."
)
_MODEL_PROVIDER_SPEND_LIMIT_MESSAGE = (
    "Kriton is temporarily unavailable because the AI provider has reached its "
    "configured spending limit. Please try again later."
)

# High-confidence, consumer/general-knowledge requests that are plainly
# outside Kriton's governed accounting and finance scope. Keeping this gate
# deliberately narrow makes the refusal deterministic (and independent of an
# LLM outage) without trying to replace the richer model domain classifier.
_DETERMINISTIC_OUT_OF_SCOPE = re.compile(
    r"(?:\b(?:recommend|suggest|pick)\b.{0,40}\b(?:movie|film|tv show)\b|"
    r"\b(?:give|show|suggest|provide|write)\b.{0,35}\brecipe\b|"
    r"\b(?:tell|give)\s+(?:me\s+)?(?:a\s+)?joke\b|"
    r"\b(?:plan|recommend|suggest)\b.{0,50}\b(?:holiday|vacation|tourist trip|travel itinerary)\b|"
    r"\b(?:who won|what (?:was|is) the score|match result)\b.{0,50}"
    r"\b(?:football|soccer|cricket|basketball|tennis|match|game)\b)",
    re.I | re.DOTALL,
)
_DETERMINISTIC_DOMAIN_HINT = re.compile(
    r"\b(?:account(?:ing|ant|s)?|audit(?:ing|or)?|tax(?:ation|able)?|payroll|"
    r"bookkeep(?:ing|er)?|finance|financial|invoice|ledger|reconciliation|"
    r"expenses?|revenues?|profits?|costs?|costing|margin|pricing|budget|cash flow|balance sheet|holiday pay)\b",
    re.I,
)


def _is_deterministically_out_of_scope(query: str) -> bool:
    text = query or ""
    return bool(
        _DETERMINISTIC_OUT_OF_SCOPE.search(text)
        and not _DETERMINISTIC_DOMAIN_HINT.search(text)
    )
# Deliberately NOT every verb in extraction.py's _RELATION_VERBS: verbs that
# read as generic/technical regardless of the named entities ("depends_on",
# "manages", "contracts_with", "licenses_to") must NOT prove domain by
# themselves — "Module A depends on Module B" has to stay off-domain by
# entity content alone (see _structured_visual_query_is_in_domain's
# _TECHNICAL_ENTITY_HINTS check and the system prompt's own "judge what the
# named entities actually ARE, not the sentence structure" rule). Only verbs
# that are themselves unambiguously accounting/audit-specific belong here.
# A hand-copied list here has twice drifted out of sync with a verb ADDED to
# _RELATION_VERBS ("supports", then "reviews") — when adding a new verb
# there, add it here too ONLY if it's unambiguous like the ones below, never
# by blindly mirroring the whole tuple.
_ACCOUNTING_RELATIONS = {
    "owns", "controls", "invoices", "pays", "supplies", "audits", "reviews",
    "guarantees", "borrows_from", "lends_to", "reports_to", "supports",
    "is_a_subsidiary_of", "is_owned_by", "is_audited_by", "is_reviewed_by",
    "is_supported_by", "is_controlled_by",
}
_ACCOUNTING_ENTITY_HINTS = re.compile(
    r"\b(account|accounting|audit|auditor|evidence|working[- ]?paper|finding|"
    r"invoice|payment|expense|journal|ledger|purchase order|supplier|customer|"
    r"company|companies|corp|corporation|holdings?|subsidiar(y|ies)|parent|"
    r"consolidation|tax|payroll|financial|finance|control|ownership|"
    r"partner|sign[- ]?off|delivery note|goods receipt|requisition|"
    r"bank|statement|reconcil(e|ed|ing|iation)|record|balance|transaction|"
    r"deposit|withdrawal|cash|cheque|check|discrepanc(y|ies)|bookkeeping|"
    # VAT/GST decisions and finance-team org charts. Not plain "manager":
    # "Draft -> Manager Review -> Published" is a publishing flow.
    r"vat|gst|cfo|chief financial officer|accountants?|tax (?:manager|analyst|team))\b",
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

    from app.orchestration.chart_tables import is_chart_table, build_chart_table_spec
    if is_chart_table(evidence) and evidence.dimensions[1] == "budget_actual":
        spec = build_chart_table_spec(evidence, "narrative")
        rows = spec.rows
        total = sum(float(row["Variance"]) for row in rows)
        table = "| Category | Budget | Actual | Actual minus budget |\n| --- | ---: | ---: | ---: |\n"
        table += "\n".join(f"| {row['Category']} | {row['Budget']} | {row['Actual']} | {row['Variance']} |" for row in rows)
        return table + f"\n\nTotal actual minus budget: {total:,.2f}. Positive variance is overspend; negative variance is underspend."

    # A figure and the target it is measured against, both stated in the
    # question ("revenue 8.2m against a target of 10m"). Checked before the
    # series branch below, which would otherwise read the single observation
    # as a one-point trend and narrate it as having "increased from X to X".
    #
    # Narrated deterministically for the same reason the graph/flow case is:
    # the answer is a transcription of the user's own two numbers, and a model
    # paraphrase risks the prose disagreeing with the dial beneath it.
    if evidence.target is not None and evidence.observations:
        actual = evidence.observations[-1].value
        target = evidence.target
        subject = evidence.subject or "the measure"
        unit = evidence.units[0] if evidence.units else ""
        suffix = unit if unit == "%" else ((" " + unit) if unit else "")
        shortfall = target - actual

        def _fmt(value: float) -> str:
            return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:g}"

        standing = (
            f"{_fmt(abs(shortfall))}{suffix} short of target" if shortfall > 0
            else f"{_fmt(abs(shortfall))}{suffix} above target" if shortfall < 0
            else "exactly on target"
        )
        return (
            f"{subject} is {_fmt(actual)}{suffix} against a target of "
            f"{_fmt(target)}{suffix} — {actual / target * 100:.1f}% of target, "
            f"{standing}. Both figures were supplied in the question; Kriton has "
            "not retrieved, adjusted or benchmarked either of them, and the "
            "visualization shows those same two values."
        )

    # A numeric sample typed into the question. Narrated separately from the
    # retrieved-series branch below for two reasons, both about saying only
    # what is true: those figures are not "source-grounded observations", and
    # they are not a time series — their dimensions are 1, 2, 3…, so the trend
    # wording would read "increased from 4 in 1 to 16 in 4", describing a
    # movement over positions in a list as though it were movement over time.
    if evidence.user_supplied and evidence.observations and not evidence.composition:
        values = sorted(item.value for item in evidence.observations)
        count = len(values)
        middle = (
            values[count // 2] if count % 2
            else (values[count // 2 - 1] + values[count // 2]) / 2
        )
        subject = evidence.subject or "the supplied values"
        unit = evidence.units[0] if evidence.units else ""
        suffix = unit if unit == "%" else ((" " + unit) if unit else "")
        return (
            f"{count} values for {subject} were supplied in the question, ranging "
            f"from {values[0]:g}{suffix} to {values[-1]:g}{suffix}, with a median of "
            f"{middle:g}{suffix}. Kriton has not retrieved or adjusted these figures; "
            "the visualization summarises exactly the values as given."
        )

    # Rows read out of a document are CATEGORIES — balance-sheet line items,
    # expense headings — not periods. The series wording below would describe
    # them as a movement over time: "decreased from 418,000 in Inventory to
    # 87,000 in Deferred tax liability", with Inventory as "first" and a tax
    # liability as "latest". Nothing decreased, nothing came first, and the
    # two are not even the same kind of figure. Read quickly, that sentence
    # states something about the business that the document does not.
    if (
        "category" in evidence.dimensions
        and evidence.observations
        and not evidence.user_supplied
    ):
        rows = evidence.observations
        largest = max(rows, key=lambda item: item.value)
        smallest = min(rows, key=lambda item: item.value)
        subject = evidence.subject or "the figures"
        total_note = ""
        total = sum(item.value for item in rows)
        if all(item.value >= 0 for item in rows) and total > 0:
            total_note = (
                f" Together the rows shown come to {total:,.0f}, with "
                f"{largest.dimension} making up {largest.value / total * 100:.1f}% "
                "of that. This is the sum of those lines only — any total stated "
                "in the document was excluded so it is not charted beside its own "
                "parts."
            )
        return (
            f"{len(rows)} figures were read from the document for {subject}. "
            f"The largest is {largest.dimension} at {largest.value:,.0f} and the "
            f"smallest is {smallest.dimension} at {smallest.value:,.0f}.{total_note} "
            "These are separate line items, not a series over time, and the "
            "visualization shows the same values as read."
        )

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
        intent in {DISTRIBUTION, TREND, CURRENT_METRIC, PRECISE_DATA}
        or is_named_chart_request or evidence.provider is not None
    ):
        subject = evidence.subject or "financial series"
        if evidence.secondary_observations:
            secondary = evidence.secondary_subject or "comparison series"
            first_a, last_a = evidence.observations[0], evidence.observations[-1]
            first_b, last_b = evidence.secondary_observations[0], evidence.secondary_observations[-1]
            return (
                f"Kriton compared {len(evidence.observations)} period-aligned observations for "
                f"{subject} and {secondary}. In the latest shared period ({last_a.dimension}), "
                f"the values were {last_a.value:g} and {last_b.value:g}, respectively. "
                f"The comparison starts at {first_a.value:g} and {first_b.value:g} in "
                f"{first_a.dimension}; every value in the table and visualization comes from "
                "the same retrieved series."
            )
        first, latest = evidence.observations[0], evidence.observations[-1]
        minimum = min(evidence.observations, key=lambda item: item.value)
        maximum = max(evidence.observations, key=lambda item: item.value)
        # A first-vs-last comparison alone can call a series "unchanged" or
        # "increased" even when it swung wildly in between (e.g. GDP growth
        # cratering in 2020 and rebounding back near its starting value) —
        # technically true about the endpoints, materially misleading about
        # the series. When the net endpoint move is small next to the full
        # min/max swing, say so plainly instead of implying stability/a
        # steady trend the data doesn't show.
        value_range = maximum.value - minimum.value
        net_change = latest.value - first.value
        if value_range > 0 and abs(net_change) < 0.5 * value_range:
            direction = "fluctuated"
        else:
            direction = (
                "increased" if latest.value > first.value
                else "decreased" if latest.value < first.value
                else "was unchanged"
            )
        series_note = f" FRED series: {evidence.series_id}." if evidence.series_id else ""
        coverage_note = ""
        if not evidence.coverage_complete and evidence.warnings:
            coverage_note = f" Coverage is partial: {evidence.warnings[0]}"
        return (
            f"Across {len(evidence.observations)} source-grounded observations, {subject} {direction} "
            f"from {first.value:g} in {first.dimension} to {latest.value:g} in {latest.dimension}. "
            f"The minimum was {minimum.value:g} in {minimum.dimension}, and the maximum was "
            f"{maximum.value:g} in {maximum.dimension}. The visualization uses these same "
            "source-grounded values without adding model-generated figures."
            f"{series_note}{coverage_note}"
        )

    # Real, named PSC/shareholder holdings from Companies House
    # (market_data.py's _find_ownership) — a real company's filed ownership
    # is itself proof of scope regardless of which chart type the user named
    # alongside it (a treemap/radar-chart request is no less in-domain than
    # a donut-chart one; only the requested display format differs).
    if evidence.composition and intent == COMPOSITION:
        subject = evidence.composition_subject or "the company"
        # Split by provenance. This branch was written for Companies House
        # filings and said so in every case, so a user's own typed expense
        # percentages came back described as "named holders on file" and
        # "filed ownership data" — naming a statutory register as the source
        # of figures the reader had just typed. The wording has to follow
        # where the numbers actually came from.
        if evidence.user_supplied:
            parts = ", ".join(
                f"{item.dimension} {item.value:.4g}%" for item in evidence.composition[:6]
            )
            more = "" if len(evidence.composition) <= 6 else f", and {len(evidence.composition) - 6} more"
            caveat = f" {evidence.composition_caveat}" if evidence.composition_caveat else ""
            return (
                f"{subject} was given as {len(evidence.composition)} parts in the question: "
                f"{parts}{more}. Kriton has not retrieved or verified these figures; the "
                f"visualization shows exactly the split as supplied.{caveat}"
            )
        return (
            f"Kriton found {len(evidence.composition)} real, named holders on file for {subject}. "
            "The validated visualization below presents that filed ownership data without adding model-generated figures."
        )
    if intent == COMPOSITION and evidence.composition_subject and evidence.sources:
        return (
            f"Kriton checked the Companies House PSC register for {evidence.composition_subject}. "
            "No reportable ownership-of-shares PSC entries were found for that exact entity. "
            "PSC records cover statutory control (generally over 25%) and are not a complete "
            "shareholder register, particularly for widely held listed companies."
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
        if any(edge.type == "exception" for edge in graph.edges):
            return ("Kriton mapped the invoice workflow and the requested exception branches. "
                    "The resolve-and-retry loops are illustrative; check them against your actual dispute and approval procedures.")
        return (
            f"Kriton mapped the {len(graph.nodes)} supplied accounting-workflow stages in order. "
            "The validated process visualization below does not add or remove stages."
        )
    return None


def _document_failure_message(expired: list[str]) -> str:
    """What to tell a user whose attached documents produced no evidence.

    An expired document and an unreadable one both arrive here as zero
    sources, but only one of them is the user's to fix, and only by doing
    something the old wording never mentioned. Naming the expiry — and the
    filename — turns a dead end into a single clear action.
    """
    if not expired:
        return (
            "Kriton™ could not retrieve readable evidence from the attached "
            "document. Confirm that the attachment is ready, then attach it again "
            "or choose another document."
        )
    names = ", ".join(sorted(set(expired)))
    plural = "These documents have" if len(set(expired)) > 1 else "This document has"
    return (
        f"{plural} passed the retention period and can no longer be read: {names}. "
        "Upload the file again to continue — re-selecting it from saved documents "
        "links the same expired copy."
    )


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


def _classification_allowed(decision: SafetyDecision, provider_risk: Optional[str]) -> bool:
    """Use a provider risk result to resolve only ML classification uncertainty."""
    return decision.allowed or bool(
        provider_risk and "l2-classification-uncertain" in decision.rules_applied
    )


async def _classify_after_bundle_nonblocking(classify_request, sync_db):
    """Run the synchronous local classifier without occupying the event loop."""
    return await asyncio.to_thread(
        massarius_risk_safety.classify_after_bundle,
        True,
        classify_request,
        sync_db,
    )


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


def _query_classifier_shadow_mode_enabled() -> bool:
    """Off by default — see the call site's comment. Enable with
    QUERY_CLASSIFIER_SHADOW_MODE=1 only while actively evaluating
    classify_query() against real traffic (migration Phase 4)."""
    return os.getenv("QUERY_CLASSIFIER_SHADOW_MODE", "").lower() in {"1", "true", "yes"}



def _general_guidance_request(answer: str) -> str:
    """One rewrite for a user-specific question whose answer gave the reader
    instructions ("you must register…"): same facts, stated as the general
    rule, with no decision made for the reader."""
    return (
        "\n\n=== Your previous answer ===\n" + answer
        + "\n\nThis question concerns the asker's own or a client's matter. Rewrite the complete answer "
        "as general guidance: state each rule in general terms (for example 'a business must register "
        "when…' or 'HMRC requires…'), never as an instruction to the reader ('you must…', 'you should…'), "
        "and do not decide what the reader should do. Keep every fact, figure and source the same."
    )


_DANGLING_REFERENCE = re.compile(
    r"\b(?:those|these|the above|the same|the previous|the earlier|that|this)\s+"
    r"(?:expenses?|costs?|figures?|numbers?|amounts?|values?|revenues?|sales|totals?|"
    r"calculations?|results?|data|invoices?|entries|budget|chart|table|ratios?)\b"
    r"|\b(?:using|based on|from)\b[^.!?]{0,60}\b(?:my|the|these|those)\s+(?:supplied|provided|earlier)\s+figures\b",
    re.I,
)


def conversation_jurisdiction(query: str, history) -> str:
    """The country the conversation is about when this message names none.

    "I'm setting up a UK limited company…" then "What corporation tax rate
    applies?" was searched with no country and answered with the OECD
    average (21.2%). Only the user's own recent messages count, newest
    first, and only when exactly one country is named there."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if detect_jurisdictions(query):
        return ""
    for message in reversed(list(history or [])[-6:]):
        if getattr(message, "role", "") != "user":
            continue
        named = detect_jurisdictions(getattr(message, "content", "") or "")
        if len(named) == 1:
            return named[0]
        if named:
            return ""
    return ""


_FIGURELESS_CALCULATION = re.compile(
    r"^\W*(?:please\s+|can you\s+|could you\s+)?(?:calculate|compute|work out|estimate|figure out)\s+"
    r"(?:my|our|the|a)\s+(?:\w+\s+){0,2}?(?:tax(?:es)?|vat|gst|liability|salary|payroll|profit|bill)\W*$",
    re.I,
)


def figureless_calculation_request(query: str) -> bool:
    """A bare request to calculate something with nothing to calculate from."""
    return bool(_FIGURELESS_CALCULATION.match(query or "")) and not re.search(r"\d", query or "")


_REFERS_BACK = re.compile(
    r"\b(?:previous|earlier|above|same|those|these|that|it|them|again|instead|also|now|then|original|last)\b", re.I)
_OWN_MONEY = re.compile(r"[£$€₹]\s?\d|\b\d[\d,]*(?:\.\d+)?\s*(?:GBP|USD|EUR|INR|AED)\b", re.I)


def _standalone_with_figures(query: str) -> bool:
    """A request that carries its own figures and does not refer back: earlier
    turns add nothing it needs, and their figures can only contaminate it.
    Follow-ups ("what if revenue rises 15%?", "use the same figures") keep
    their history."""
    text = query or ""
    if (re.search(r'\b(?:keep|unchanged|overstated|understated)\b', text, re.I)
            or re.match(r'^\s*(?:increase|decrease|correct|recalculate|now|then|and)\b', text, re.I)):
        return False
    labelled_baseline = (re.search(r'\brevenue\b\s*(?:is|was|of|:|=)?\s*[£$€₹]\s*\d', text, re.I)
                         and re.search(r'\b(?:cost of (?:goods sold|sales)|COGS)\b\s*(?:is|was|of|:|=)?\s*[£$€₹]\s*\d', text, re.I))
    if (labelled_baseline and not re.search(r'\b(?:previous|earlier|original|same figures|last answer)\b', text, re.I)
            and not re.match(r'^\s*(?:now|then|and|what if|keep|using (?:the )?(?:same|previous))\b', text, re.I)):
        return True
    return (len(_OWN_MONEY.findall(text)) >= 2 and not _REFERS_BACK.search(text)
            and not _looks_like_contextual_follow_up(text))


_CLAUSE_SPLIT = re.compile(r"[.;?!]\s+|,?\s+\b(?:and|also|then|plus)\b\s+(?=(?:also\s+)?(?:tell|give|explain|show|list|state|"
                           r"cite|compare|what|which|how|why|is|are|does|do)\b)", re.I)
_EXTERNAL_FACT = re.compile(
    r"\b(?:published|official|benchmark|industry|sector|typical|statistics?|according to|national|government|"
    r"ONS|HMRC|IRS|OECD|average\s+(?:\w+\s+){0,3}(?:for|of|in|across)\s+(?:UK|US|the|\w+\s+(?:companies|firms|businesses|cafés|cafes|retailers))|"
    r"regulation|rule|standard|law|legislation|explain|why|unsupported|commentary|evidence|"
    # Deadlines and filing: "…and tell me when the quarterly VAT return is due".
    r"due|deadline|filing|file|submit|payable\s+by)\b", re.I)
_ASKS = re.compile(r"\b(?:tell|give|explain|state|cite|list|compare|what|which|how|why|when|is|are|does|do)\b", re.I)
_LIVE_CALCULATION_PART = re.compile(
    r'\b(?:(?:exchange|fx|reference)\s+rates?|(?:share|stock)\s+prices?|market\s+data|economic\s+(?:indicator|statistics))\b', re.I,
)
_LIVE_CALCULATION_ASK = re.compile(r'\b(?:retrieve|fetch|find|get|look\s+up|latest|current|today)\b', re.I)
_DERIVED_COMPARISON_ASK = re.compile(
    r'^\s*(?:highlight|explain|summari[sz]e|outline|identify|compare)\b[^.!?]{0,160}'
    r'\b(?:differences?|comparison)\b', re.I,
)
# A standard or rule reference is not a figure: "explain what IAS 16 says".
_RULE_REFERENCE = re.compile(r"\b(?:IAS|IFRS|IFRIC|SIC|FRS|ASC|Ind\s?AS|section|s\.?)\s?\d+[A-Z]?\b", re.I)


_DEADLINE_PART = re.compile(r"\b(?:due|deadline|file|filing|submit|payable\s+by|when)\b", re.I)
_STANDARD_PART = re.compile(r"\b(?:IAS|IFRS|IFRIC|FRS|US GAAP|ASC|Ind\s?AS|standard)\b", re.I)
_STATISTIC_PART = re.compile(r"\b(?:published|average|statistics?|ONS|benchmark|industry|sector|typical)\b", re.I)
_TAX_PART = re.compile(r"\b(?:vat|gst|tax|rate|threshold|rule|hmrc|irs)\b", re.I)


_DELIVERABLE = re.compile(r"\b(?:calculate|compute|compare|explain|identify|reconcile|recommend\w*|provide|"
                          r"prepare|chart|table|forecast|model)\b", re.I)


def deliverable_step_allowance(query: str) -> int:
    """Extra agent steps for a long request with many deliverables. The
    financial performance analysis (qry-f7c7ad8f72ff: net sales, margins,
    operating and pre-tax profit, prior year, changes, recommendations,
    table, chart) ran out of its 8 steps after 7 calculations and its whole
    answer was withheld. Bounded; the time budget is unchanged."""
    q = query or ""
    deliverables = len(_DELIVERABLE.findall(q))
    if len(q) <= 800 or deliverables < 4:
        return 0
    # Nine deliverables over twelve supplied amounts (current and prior year,
    # changes, margins) still ran out of 12 steps with £155,000 uncomputed.
    amounts = {token.replace(",", "") for token in re.findall(r"[£$€₹]\s?(\d[\d,]*(?:\.\d+)?)", q)}
    return 8 if deliverables >= 8 and len(amounts) >= 8 else 4


def request_parts(query: str, calculated: bool) -> list[dict]:
    """Each separately answerable part of a mixed request, with what it
    needs: the calculation (verified when the calculator ran) and every part
    that must come from evidence. "Calculate the VAT on £2,400 … and tell me
    when the quarterly VAT return is due" is two parts, and the deadline part
    lacking a source must not take the calculated £480 with it."""
    parts = []
    for clause in _CLAUSE_SPLIT.split(query or ""):
        clause = clause.strip()
        if re.fullmatch(r"(?:do not|don't) claim to have verified (?:the )?(?:law|legal eligibility)[.!]?", clause, re.I):
            continue
        if not clause:
            continue
        figures = _RULE_REFERENCE.sub("", re.sub(r"\b(?:19|20)\d{2}\b", "", clause))
        if re.search(r"\d", figures):
            kind = "tax_calculation" if re.search(r"\b(?:vat|gst|tax)\b", clause, re.I) else "calculation"
            parts.append({"kind": kind, "text": clause, "needs_evidence": False, "tools": ["calculate"],
                          "status": "calculated_and_verified" if calculated else "to_calculate"})
            continue
        if not (_ASKS.search(clause) and _EXTERNAL_FACT.search(clause)):
            continue
        kind = ("research_standard" if _STANDARD_PART.search(clause)
                else "research_tax" if _DEADLINE_PART.search(clause) or _TAX_PART.search(clause)
                else "live_data" if _STATISTIC_PART.search(clause) else "explanation")
        parts.append({"kind": kind, "text": clause, "needs_evidence": kind != "explanation",
                      "tools": ["search_knowledge_base", "search_web"] if kind != "explanation" else [],
                      "status": "needs_evidence"})
    return parts


def parts_instruction(parts: list[dict]) -> str:
    """The checklist the composer answers part by part."""
    lines = [f"\n\nThis request has {len(parts)} separate parts. Answer each one under its own short heading, in order:"]
    for number, part in enumerate(parts, start=1):
        if part["status"] == "calculated_and_verified":
            lines.append(f"{number}. {part['text']} — already calculated and verified above: show that result exactly; "
                         "it needs no citation.")
        elif not part.get('needs_evidence', True):
            lines.append(f"{number}. {part['text']} — explain using the supplied facts and general reasoning. "
                         "Label possible causes as questions to investigate, never as established facts. "
                         "An ordinary explanation does not require an external citation.")
        else:
            lines.append(f"{number}. {part['text']} — answer only from the evidence, citing it. If the evidence does not "
                         "establish this part, say so for this part only.")
    lines.append("A part the evidence cannot answer never removes the answer to another part.")
    return "\n".join(lines)


def uncalculated_part(query: str) -> str:
    """A clause of a calculation request that the calculator cannot answer:
    it carries no figures of its own and asks for an outside fact or an
    explanation. "" when every clause is arithmetic on the given figures."""
    if re.search(r'\b(?:report|answer)\b[\s\S]{0,120}\b(?:sections|headings)\b', query or '', re.I):
        return 'Complete the explicitly requested report sections.'
    if _DERIVED_COMPARISON_ASK.search(query or ''):
        return re.split(r'\s+Context:\s+', query, maxsplit=1)[0].strip()
    for clause in _CLAUSE_SPLIT.split(query or ""):
        clause = clause.strip()
        if re.fullmatch(r"(?:do not|don't) claim to have verified (?:the )?(?:law|legal eligibility)[.!]?", clause, re.I):
            continue
        # A ticker, an amount or an observation year in a lookup clause does
        # not make that clause answerable by the accounting calculator.
        if _LIVE_CALCULATION_PART.search(clause) and _LIVE_CALCULATION_ASK.search(clause):
            return clause
        # A year ("in 2025") is not a figure to calculate with.
        figures = _RULE_REFERENCE.sub("", re.sub(r"\b(?:19|20)\d{2}\b", "", clause))
        if (clause and not re.search(r"\d", figures) and _ASKS.search(clause) and _EXTERNAL_FACT.search(clause)
                and not re.search(r"\b(?:calculate|compute|work out)\b", clause, re.I)):
            return clause
    return ""


_PART_NOT_FOUND = re.compile(
    r"\b(?:no|not)\b[^.\n]{0,200}?\b(?:could be|can be|was|were)\s+(?:found|retrieved|located|identified)\b"
    r"|\bcould not (?:be )?(?:find|found|retrieve|retrieved|locate|located|verify|verified|confirm|confirmed)\b",
    re.I)


# Reason codes in answer_statements_removed (version 1). Only the first says
# the statement is wrong; the others say it could not be verified as written.
REMOVAL_REASONS = frozenset({
    "contradicted_by_cited_source",   # the cited evidence says otherwise
    "not_in_cited_evidence",          # the cited evidence does not address it
    "missing_citation",               # a factual statement with no valid reference
    "citation_not_bound",             # supported, but not by the reference it cites
    "calculation_error",              # a derived figure that does not compute
    "figure_unreconciled",            # a figure matching no evidence, tool result or calculation
    "unsupported_premise",            # a balance resting on consideration the question never established
    "figure_misattributed",           # a verified figure shown for the wrong period or scenario
    "jurisdiction_mismatch",          # a source for another jurisdiction cited for this one
    "effective_date_mismatch",        # today's position given for a question about a past period
    "policy_rule:composition_threshold_label", "policy_rule:state_service_threshold",
    "policy_rule:ring_fence_rate", "policy_rule:export_igst_refund", "policy_rule:interstate_exemptions",
    "unspecified",
})
_MAX_REMOVED_PER_STAGE = 20
_EXCERPT_CHARS = 120


def removal_stage(stage: str, before: str, after: str, removed: list[tuple[str, str, dict]],
                  citations: list) -> dict:
    """One stage of removals for the audit trail. A statement is kept as a
    hash and a redacted excerpt (no full answer text), with the references it
    cited and their source ids."""
    from app.orchestration.redaction import redact_for_external_exposure
    source_of = {citation.ref_id: citation.source_id for citation in citations or []}
    entries = []
    for statement, reason, extra in removed[:_MAX_REMOVED_PER_STAGE]:
        refs = list(dict.fromkeys(f"REF-{n}" for n in re.findall(r"\[REF-(\d+)\]", statement)))
        excerpt = redact_for_external_exposure(re.sub(r"\s*\[REF-\d+\]", "", statement)).redacted_text
        entries.append({
            "statement_hash": _hash_query(statement),
            "excerpt": excerpt[:_EXCERPT_CHARS] + ("…" if len(excerpt) > _EXCERPT_CHARS else ""),
            "reason_code": reason if reason in REMOVAL_REASONS else "unspecified",
            "cited_refs": refs,
            "source_ids": [source_of[ref] for ref in refs if ref in source_of],
            **extra,
        })
    return {
        "stage": stage,
        "answer_hash_before": _hash_query(before) if before else None,
        "answer_hash_after": _hash_query(after or ""),
        "removed_count": len(removed),
        "removed": entries,
    }


# The question supplies its own scenario and names the framework to apply.
# Told only to cite, the model answered "the sources provided do not state
# this" for VIE, subsequent-event and internal-control scenarios (22 Oct 2026).
PROFESSIONAL_APPLICATION_INSTRUCTION = (
    "\n\nThis question supplies its own facts and names the framework to apply. Answer every part in "
    "full from professional knowledge of that framework: classifications, the reasoning for each, journal "
    "entries, calculations, presentation and disclosure. Cite a source where the evidence has one; where "
    "it has none, still answer the part and do not say the sources do not state it. Use only the figures, "
    "rates and dates the question gives; do not add a statutory rate, threshold or deadline it does not "
    "give. State any assumption you make. Search at most once, only for a specific rule you will cite, and "
    "never repeat a search that found nothing. Make all the calculations you need in as few calculator "
    "calls as possible."
)
# An answer citing some sources and explaining the rest from professional
# knowledge: the label used to depend on the whole answer citing nothing, so
# a mixed answer's uncited parts were not marked (review R2, 22 Oct 2026).
MIXED_SOURCES_NOTE = ("Partly source-verified. Statements with a source reference are supported by that source; "
                      "statements without one are general explanation from professional knowledge, not "
                      "source-verified. Calculations on the figures you gave are checked separately.")
GENERAL_EXPLANATION_NOTE = ("General explanation — not source-verified. This is general practice guidance, not a "
                            "statement of what a rule, standard or tax law requires.")


def jurisdiction_limitation(question: str, removed: list[dict]) -> str:
    """When a statement was removed because its source belongs to another
    jurisdiction, say so instead of leaving only a generic gap: "The sources
    found cover the UK, not the Isle of Man; the Isle of Man rule could not
    be confirmed from them." """
    mismatched = [item for stage in removed for item in stage.get("removed", [])
                  if item.get("reason_code") == "jurisdiction_mismatch"]
    if not mismatched:
        return ""
    from app.orchestration.source_taxonomy import detect_jurisdictions, jurisdiction_label, source_jurisdiction
    asked = detect_jurisdictions(question)
    # The removal record keeps each statement's sources (web source ids are
    # their URLs), so this works even when the whole answer was withheld.
    found = list(dict.fromkeys(j for item in mismatched for source in item.get("source_ids", [])
                               if (j := source_jurisdiction(source)) and j not in asked))
    if not asked or not found:
        return ""
    asked_text = " and ".join(jurisdiction_label(j) for j in asked)
    found_text = " and ".join(jurisdiction_label(j) for j in found)
    return (f"Incomplete answer: the sources found cover {found_text} rules, not {asked_text}. {asked_text} "
            f"legislates separately, so the {asked_text} rule could not be confirmed from these sources.")


_LIVE_DATA_FRESHNESS = {"realtime", "delayed", "daily", "historical", "filing"}


GENERAL_BACKGROUND_NOTE = ("Parts of this answer are general explanation, not verified against a source. Figures, "
                           "rates, deadlines and rules in it are sourced or calculated.")


def strip_citations_from(text: str, statements: list[str]) -> str:
    """Remove [REF-n] markers from the given statements only."""
    for statement in statements:
        bare = re.sub(r"\s*\[REF-\d+\]", "", statement)
        if bare != statement:
            text = text.replace(statement, bare)
    return text


def cited_only(text: str, citations: list) -> list:
    """The sources the released answer actually cites. An IAS 2 answer citing
    [REF-1] and [REF-2] listed seven sources, among them a carbon-offset paper
    and an ethics code it never used. Only the displayed list changes: the
    source bundle, retrieval audit and answer receipt keep every source that
    was considered. Ref ids are kept, so [REF-n] in the text still points at
    its source. An answer without markers cites no web hit (a gross-margin
    answer listed ten unrelated OECD papers); it keeps only live data
    observations (an exchange rate, a price, a statistic), whose figures an
    answer can show without a marker. A prefetched rule text it never cited
    is not shown (a mixed VAT answer citing nothing listed eight)."""
    used = {f"REF-{number}" for number in re.findall(r"\[REF-(\d+)\]", text or "")}
    if not used:
        return [citation for citation in citations if getattr(citation, "freshness", None) in _LIVE_DATA_FRESHNESS]
    return [citation for citation in citations if citation.ref_id in used]


def dangling_reference(query: str) -> bool:
    """The message points at figures from earlier ("those expenses") but
    carries none itself. Only meaningful when there is no earlier turn or
    attached document for it to point at."""
    # "by 10%" is an instruction about the figures, not the figures.
    figures = re.sub(r"\d+(?:\.\d+)?\s*(?:%|percent\b|per cent\b)", "", query or "", flags=re.I)
    return bool(_DANGLING_REFERENCE.search(query or "")) and not re.search(r"\d", figures)


from app.orchestration.verification_service import (
    _CLAIM_REMOVED_NOTE, _CLAIMS_UNCONFIRMED_NOTE, _verify_answer_claims, verify_for_release, requires_authoritative_evidence,
    normalize_citations, prune_rejected_claims, _UNSUPPORTED_REMOVED_NOTE, unbind_arithmetic_citations, calculated_figures,
    decide_release_failure, release_claims, uncited_explanations,
)


# The user permits a currency conversion: "find an exchange rate if needed",
# "convert at today's rate", "use the latest rate".
_MAY_FETCH_FX = re.compile(
    r"\b(?:find|fetch|get|use|look\s+up|retrieve|apply)\b[^.?]*\b(?:exchange|fx|conversion|currency)\s+rates?\b"
    r"|\bconvert(?:ing|ed)?\b|\b(?:latest|current|today'?s|live)\s+(?:exchange\s+|fx\s+)?rates?\b",
    re.I,
)


def figure_evidence_text(request, web_sources, governed_passages, document_sources, calculation_result,
                         remembered_calculation=None) -> str:
    """What a figure in the answer may be verified against, apart from tool
    results: the question, the whole conversation (earlier answers were
    released after verification), documents, retrieved and governed passages,
    and a deterministic calculation. Never the prompt's own instructions and
    examples: an exact match with one of their numbers is not provenance."""
    parts = [request.query, *(message.content for message in request.conversation_history)]
    parts += [getattr(source, "snippet", "") or "" for source in [*(web_sources or []), *(document_sources or [])]]
    parts += [content for _, _, content in governed_passages or []]
    if calculation_result is not None and getattr(calculation_result, "status", "") == "success":
        parts += [f"{item.name} {item.value}" for item in [*(calculation_result.inputs or []),
                                                           *(calculation_result.outputs or [])]]
    if remembered_calculation is not None:
        parts += [f'{item.name} {item.value}' for item in remembered_calculation.outputs if item.value is not None]
    return "\n".join(part for part in parts if part)


def _agent_tool_evidence(agent_outcome, ref_offset: int) -> str:
    """The agent's tool results (exchange rates, indicators) under the REF ids
    the answer cites them by. A rewrite given only the pre-agent prompt never
    saw them, and answered "the sources provided do not state this"."""
    if not agent_outcome or not agent_outcome.sources:
        return ""
    start = ref_offset - len(agent_outcome.sources)
    return "\n\n=== Tool results (cite by these REF ids) ===\n" + "\n\n".join(
        f"[REF-{start + i + 1}] {source.title}\n{source.snippet}" for i, source in enumerate(agent_outcome.sources)
    )


_partial_answer_active: ContextVar[bool] = ContextVar("partial_answer_active", default=False)
_TAMPERING_SENTENCE = re.compile(
    r"\b(?:delete|erase|wipe|purge|remove|disable|turn\s+off|alter|modify|edit|backdate|truncate|drop)\b"
    r"[^.?!]*\b(?:audit|ledger|log|logs|records?|trail|history)\b"
    r"|\b(?:audit|ledger|log|logs|records?|trail)\b[^.?!]*\b(?:delete|erase|wipe|purge|disable|backdate)\b"
    r"|\b(?:backdate|falsify|fabricate|forge)\b",
    re.I,
)


def _split_tampering_request(query: str) -> tuple[str, str]:
    """(the rest of the question, the record-tampering sentence) when a
    message mixes the two; ("", "") otherwise. Only an instruction to act on
    records is split off: a message that is only that, or whose other
    sentences also ask for it, is refused whole as before."""
    # Sentences, and clauses joined by "and also" / ", also" / ";": "Get the
    # rate, and also delete the audit ledger" is two requests in one sentence.
    sentences = [part.strip(" ,;") for part in re.split(
        r"(?<=[.?!])\s+|,?\s+(?:and\s+)?also,?\s+|;\s*", query or "", flags=re.I) if part.strip(" ,;")]
    declined = [part for part in sentences if _TAMPERING_SENTENCE.search(part)]
    allowed = [part for part in sentences if part not in declined]
    if not declined or not allowed:
        return "", ""
    allowed_text = re.sub(r"^\s*(?:also|and|then)[,:]?\s+", "", " ".join(allowed), flags=re.I)
    return allowed_text, " ".join(declined)


def _dated_fx_question(query: str) -> bool:
    """A conversion at a named past date. In agent mode nothing is
    pre-fetched, and for "the USD/INR reference rate for 31 December 2024"
    the agent took 85.55 from a company filing in the web results instead of
    the ECB rate for that date; that rate is fetched up front instead."""
    from app.orchestration.frankfurter import _find_currencies, requested_rate_date

    return len(_find_currencies(query)) >= 2 and requested_rate_date(query) is not None


# Official rates the agent has no tool for: the Bank of England, Bank of
# Canada, RBA, Federal Reserve and US Treasury connectors run only in the
# pre-fetch (live_data.py), which agent mode skips. "Show the Bank of England
# base rate over the last 3 years as a line chart" was answered "I'm unable to
# retrieve the Bank of England base rate" while the connector had the series.
_OFFICIAL_RATE_QUESTION = re.compile(
    r"\b(?:base|bank|policy|cash|overnight|official|repo)\s+rates?\b|\bfed(?:eral)?\s+funds\b|"
    r"\btreasury\s+(?:yields?|rates?|bills?|notes?|bonds?)\b|\bgilt\s+yields?\b|\binterest\s+rate\s+decisions?\b",
    re.I)


def _official_rate_question(query: str) -> bool:
    return bool(_OFFICIAL_RATE_QUESTION.search(query or ""))


async def _record_calculation_receipts(db, *, receipts: list[dict], query_id: str, correlation_id: str,
                                       tenant_id: str, audit_chain_id: str, actor_id: str) -> None:
    """Save each agent calculation as a calculation run (the immutable
    receipt, §07.3) and audit it. Committed with the request's audit batch."""
    from app.domains.calculations.models import CalculationRun
    for receipt in receipts:
        db.add(CalculationRun(
            id=receipt["calculation_id"], tenant_id=tenant_id, query_id=query_id,
            operation="expression", rule_version=receipt["formula_version"],
            inputs=[{key: receipt.get(key) for key in ("label", "expression", "input_hash", "tool", "tool_version", "warnings")}],
            output_value=receipt["result"], output_unit=receipt.get("units") or "",
            rounding_mode="ROUND_HALF_UP", scale=2, status="completed",
        ))
        await audit_calculation_receipt(db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                                        audit_chain_id=audit_chain_id, actor_id=actor_id, receipt=receipt)
        workflow_state.note_calculation(receipt["calculation_id"])


def final_text_needs_notice(text: str | None) -> bool:
    """A real answer that does not already say Kriton won't act for the user."""
    return bool((text or "").strip()) and WRITE_REQUEST_NOTICE.split(".")[0] not in text


_FIGURE = re.compile(r"\d")
_ASKS_FOR_EXAMPLE = re.compile(r"\b(?:example|illustrat\w*|numerical|worked|hypothetical|scenario|sample)\b", re.I)


def supplies_figures(query: str, history) -> bool:
    """Whether the user gave any figures to calculate with, here or in an
    earlier user turn, or asked for a worked example. "Can we switch from
    straight-line to reducing-balance depreciation…?" has none, yet the agent
    made four calculate calls on an invented £100,000 asset, and the answer
    was then withheld as unverifiable (ps-std-depreciation-method-change)."""
    texts = [query or ""] + [getattr(m, "content", "") or "" for m in (history or [])
                             if getattr(m, "role", "user") == "user"]
    if any(_ASKS_FOR_EXAMPLE.search(text) for text in texts):
        return True
    for text in texts:
        stripped = _RULE_REFERENCE.sub("", re.sub(r"\b(?:19|20)\d{2}\b", "", text))
        if _FIGURE.search(stripped):
            return True
    return False


def _tool_authorizer(db, *, lock, actor_id: str, tenant_id: str, role: str, figures_supplied: bool = True):
    """Per-step tool policy (ZL-ENG-AGT-01 §05, §10). Each proposed call is
    decided from the user's CURRENT stored state, not from what the run
    started with: a user deactivated, moved to another tenant or given a
    different role during the run is refused at the next tool call. The
    model's output never decides anything here."""
    from sqlalchemy import select

    from app.domains.identity.models import User
    from app.domains.model_gateway.service import tool_registry
    from app.domains.model_gateway.tool_registry import decide

    # Figures can also come from a data tool earlier in the run (an exchange
    # rate, an indicator, a price): calculate is then allowed.
    fetched_data = False

    async def authorize(tool: str):
        nonlocal fetched_data
        async with lock:  # shares the request session with the knowledge-base tool
            current = (await db.execute(
                select(User.role, User.is_active, User.tenant_id).where(User.id == actor_id)
            )).first()
        current_role = current.role if current else ""
        decision = decide(
            tool_registry().get(tool), tool, role=current_role,
            active=bool(current and current.is_active), same_tenant=bool(current and current.tenant_id == tenant_id),
            role_unchanged=current_role == role, permissions=permissions_for_role(current_role),
        )
        if decision.allowed and tool in ("get_exchange_rate", "get_economic_indicator", "get_market_data"):
            fetched_data = True
        if decision.allowed and tool == "calculate" and not figures_supplied and not fetched_data:
            # Only narrows: a call the policy allowed is refused, never the
            # reverse, and the refusal is audited with its own reason.
            from dataclasses import replace
            decision = replace(decision, allowed=False, reason_code="no_user_figures")
        return decision

    return authorize


from app.domains.model_gateway.execution import request_execution_scope


@request_execution_scope
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
    progress: Optional[Callable[[str, str], Awaitable[None]]] = None,
    deadline_seconds: Optional[float] = None,
) -> AskKritonResponse:

    start_time = time.monotonic()
    if conversation_id and request.conversation_id and conversation_id != request.conversation_id:
        raise HTTPException(status_code=400, detail='Conversation identifiers do not match.')
    conversation_id = conversation_id or request.conversation_id
    effective_query = _with_previous_context(
        request.query,
        request.previous_query,
        clarification_cycle=clarification_cycle,
    )
    # One decision for which earlier turns this message depends on, used by
    # retrieval, planning and composition alike (conversation_resolver.py).
    from app.orchestration.conversation_resolver import resolve_conversation

    def resolve_turns(history):
        return resolve_conversation(request.query, screened_history(history),
                                    legacy_follow_up=_looks_like_contextual_follow_up,
                                    standalone=_standalone_with_figures)

    resolution = resolve_turns(request.conversation_history)
    if resolution.follows_up and not resolution.legacy_follow_up:
        # Retrieval and classification see the scenario the question is about.
        scenario = resolution.scenario_text()
        if scenario and scenario not in effective_query:
            effective_query = f"{effective_query}\n\nEarlier in this conversation the user wrote: {scenario}"
    metrics = StageMetrics()

    async def report(stage: str, message: str) -> None:
        if progress is not None:
            await progress(stage, message)

    workflow_plan = metrics.run_sync("workflow.plan", lambda: plan_workflow(request))
    request = apply_plan(request, workflow_plan)
    await report("workflow_planned", f"Detected {workflow_plan.task_type.replace('_', ' ')}")

    requested_engagement_id = request.task_context.engagement_id if request.task_context else None
    no_engagement_general_guidance = False
    # A sole authorized engagement is unambiguous and can be selected without
    # a workflow form. Multiple engagements are never guessed; the task
    # contract will request the missing engagement instead.
    if workflow_plan.task_type != "general_question" and not requested_engagement_id:
        candidates = await metrics.run(
            "authorization.engagement_candidates",
            list_authorized_engagements(
                db, actor_id=actor_id, tenant_id=tenant_id, operation=ASK,
            ),
        )
        if len(candidates) == 1:
            requested_engagement_id = candidates[0].id
            request = request.model_copy(update={
                "task_context": request.task_context.model_copy(
                    update={"engagement_id": requested_engagement_id}
                )
            })
        elif not candidates and workflow_plan.detection == "automatic":
            # With no engagement to choose, the task contract could only ever
            # ask for one the user cannot supply — every "our company / our
            # client" question stopped at a clarification with no way on.
            # Answer as general guidance instead, labelled as such; truly
            # advisory questions are still routed to human review by risk.
            no_engagement_general_guidance = True
            workflow_plan = workflow_plan.model_copy(update={
                "task_type": "general_question",
                "reason_codes": [*workflow_plan.reason_codes, "NO_ENGAGEMENT_GENERAL_GUIDANCE"],
            })
            request = apply_plan(request, workflow_plan)
    authorized_engagement_id: str | None = None
    if requested_engagement_id:
        required_operations = [ASK, MODEL_TRANSMIT]
        if request.document_ids:
            required_operations.append(DOCUMENT_READ)
        for operation in required_operations:
            authz = await metrics.run(
                f"authorization.{operation}",
                authorize(
                    db, actor_id=actor_id, tenant_id=tenant_id,
                    engagement_id=requested_engagement_id, operation=operation,
                ),
            )
            if not authz.allowed:
                raise HTTPException(status_code=403, detail={
                    "code": authz.reason_code,
                    "operation": operation,
                    "engagement_id": requested_engagement_id,
                })
        authorized_engagement_id = requested_engagement_id

    # ── Idempotency check ─────────────────────────────────────────────────────
    request_hash = hashlib.sha256(json.dumps({**request.model_dump(mode="json"), "query":request.original_message}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if idempotency_key:
        try:
            cached = await metrics.run(
                "idempotency.lookup",
                check_idempotency(db, idempotency_key, tenant_id, request_hash),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if cached is not None:
            return AskKritonResponse(**cached)
        if not await metrics.run("idempotency.claim", claim_idempotency(db, idempotency_key, tenant_id)):
            raise HTTPException(status_code=409, detail="This request is already being processed.")

    # ── Step 1: Generate identifiers (§5) ────────────────────────────────────
    query_id = generate_query_id()
    correlation_id = generate_correlation_id()
    audit_chain_id = generate_audit_chain_id()
    query_hash = _hash_query(request.original_message)

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
    await report("validated", "Request validated")

    # ── F0: resolve a trusted, versioned task context before retrieval ──────
    context_decision = metrics.run_sync(
        "context.resolve",
        lambda: resolve_task_context(
            request,
            ResolutionInput(actor_id=actor_id, tenant_id=tenant_id, role=role),
            authorized_engagement_id=authorized_engagement_id,
        ),
    )
    effective_context = context_decision.resolved_context

    def contextualize(response: AskKritonResponse) -> AskKritonResponse:
        return response.model_copy(update={
            "effective_context": effective_context,
            "context_decision": context_decision,
            "workflow_plan": workflow_plan,
        })

    review_evidence_snapshot: list[dict] = []
    # What verification removed from the answer, by stage (removal_stage);
    # written as one audit event when the response is finalised.
    removed_statements: list[dict] = []
    # Figures whose statements the release figure gate removed (selective withholding).
    service_removed_figures: list[str] = []
    service_unsupported_balances: list[str] = []
    service_misattributed: list[str] = []
    charts_dropped: list[str] = []
    # The run's calculator receipts, for the answer's figure provenance.
    released_receipts: list[dict] = []
    # Intent planner, shadow mode only (planner_shadow.py): off by default,
    # never awaited, and it changes nothing the request does.
    planner_handle = None
    shadow_facts: dict = {}

    task_snapshot = None
    prior_calculation = None
    prior_calculation_state = None

    async def finish(
        response: AskKritonResponse, *, route: str | None = None, store: bool = True, json_dump: bool = False,
    ) -> AskKritonResponse:
        """Finalise the audit trail, keep the response for idempotent retries
        and return it in its request context. Every terminal response is
        retained for consistent idempotent retries."""
        nonlocal task_snapshot
        from app.orchestration.visualization.router import describe_visualization
        from app.orchestration.schemas import RequestIntegrity
        from app.orchestration.answer_coverage import check_requested_deliverables, report_section_names
        from app.orchestration.calculations.schemas import CalculationTaskState
        from app.orchestration.calculations.inventory_statement import _inventory_revision
        relation = ('correction' if _inventory_revision(request.query) is not None or re.match(r'^\s*(?:increase|decrease|correct|recalculate)\b', request.query, re.I)
                    else 'follow_up' if resolution.follows_up
                    else 'multi_part' if len(_DELIVERABLE.findall(request.query)) >= 3 else 'independent')
        result = response.calculation
        family = lambda ids: {name.removesuffix('_scenario').removesuffix('_comparison') for name in ids}
        compatible_previous = bool(result and prior_calculation and family(result.formula_ids) & family(prior_calculation.formula_ids))
        previous = {i.name:i for i in prior_calculation.inputs} if compatible_previous and relation in {'correction','follow_up'} else {}
        changed = [i.name for i in result.inputs if i.name in previous and (i.value, i.currency, i.kind) != (previous[i.name].value, previous[i.name].currency, previous[i.name].kind)] if result else []
        response.request_integrity = RequestIntegrity(conversation_id=conversation_id, turn_id=request.turn_id, request_id=request.request_id,
            current_message_sha256=hashlib.sha256(request.original_message.encode("utf-8")).hexdigest(), relation=relation, changed_inputs=changed)
        if result:
            response.calculation_state = CalculationTaskState(task_type=result.formula_ids, inputs=result.inputs,
                original_inputs=(prior_calculation_state.original_inputs if prior_calculation_state else prior_calculation.inputs) if previous else result.inputs, changed_inputs=changed,
                assumptions=result.notes, derived_results=result.outputs)
        response.visualization_intent = describe_visualization(request.query, response.visualization,
            calculation=result, limitations=response.answer.limitations if response.answer else [], legacy_text=response.answer.text if response.answer else "")
        preference = response.visualization_intent.user_requested_type
        if response.visualization is not None and preference in {'line','bar','column','pie','donut','waterfall','flowchart'} and detect_explicit_visual_request(request.query):
            response.visualization.user_requested_type = preference
        if response.answer is not None:
            response.requested_deliverables = check_requested_deliverables(request.query, response.answer.text or '',
                has_visual=bool(response.visualization or response.secondary_visualizations))
            missing = [d.description for d in response.requested_deliverables if d.status == 'incomplete']
            if missing:
                response.answer = response.answer.model_copy(update={'limitations':[*response.answer.limitations,
                    'Incomplete answer: ' + '; '.join(missing) + '.']})
                if response.visualization is None:
                    response.visualization_intent.fallback_reason = '; '.join(response.answer.limitations)
            # A refusal, rejection or escalation carries no substantive answer
            # even when it has an answer body (a refusal notice was recorded
            # as "complete" in the 78-case run).
            completeness = ("none" if response.outcome in ("refused", "rejected", "escalated")
                            else answer_completeness(response.answer.limitations))
            if completeness == 'complete' and response.answer.completeness in {'partial','none'}:
                completeness = response.answer.completeness
            response = response.model_copy(update={"answer": response.answer.model_copy(
                update={"completeness": completeness})})
        sections = report_section_names(request.query)
        if len(sections) >= 6 and response.outcome not in {'refused', 'rejected', 'escalated', 'clarification_required'}:
            if response.answer is None:
                response.requested_deliverables = check_requested_deliverables(request.query, '')
            unfinished = [d.description for d in response.requested_deliverables
                          if d.description in sections and d.status != 'complete']
            if unfinished or response.answer is None or response.answer.completeness != 'complete':
                message = 'Kriton cannot complete the requested report.'
                if unfinished:
                    message += ' Incomplete sections: ' + '; '.join(unfinished) + '.'
                message += ' This request has not passed report-completion validation.'
                response.outcome = 'unavailable'
                response.next_action = NextAction(type='report_incomplete', message=message)
                if response.answer is not None:
                    text = message + '\n\n' + response.answer.text
                    response.answer = response.answer.model_copy(update={
                        'text': text, 'output_text': text, 'completeness': 'partial',
                        'limitations': [*response.answer.limitations, message]})
        if (response.outcome == 'answered' and response.answer is not None and response.visualization is None
                and not response.secondary_visualizations and '```chart' not in (response.answer.text or '')
                and not detect_explicit_visual_request(request.query)):
            # The answer's figures would read better as a chart the user did
            # not ask for: offer it, and draw it only if they say so. A request
            # for no chart, or for text or a table only, is respected.
            from app.orchestration.chart_offer import chart_declined, offer_chart, offer_spec_id, offer_visualization
            from app.orchestration.schemas import ChartOfferPublic
            offer = None if chart_declined(request.query) else offer_chart(response.answer.text or '')
            # Offered only with the chart itself, drawn under the answer when
            # accepted; an offer that would need a second question is not made.
            chart = offer_visualization(offer, response.answer.text or '', offer_spec_id(offer)) if offer else None
            if offer is not None and chart is not None:
                response.chart_offer = ChartOfferPublic(chart_type=offer.chart_type, title=offer.title,
                                                        question=offer.question, reason=offer.reason, chart=chart)
        if task_snapshot is None and response.visualization is not None:
            task_snapshot = {'version':1, 'task_state':{}}
        if task_snapshot is not None:
            if response.calculation_state is not None:
                task_snapshot['calculation_state'] = response.calculation_state.model_dump(mode='json')
            if response.visualization is not None:
                task_snapshot['visualization'] = response.visualization.model_dump(mode='json')
            task_snapshot['task_state'].update(
                relation=relation, changed_inputs=changed,
                response_completion=response.answer.completeness if response.answer else 'no_answer',
                outcome=response.outcome,
                remaining_limitations=list(response.answer.limitations) if response.answer else [],
                visualization_id=response.visualization.id if response.visualization else None,
            )
            await conversation_memory.save_snapshot(
                db, tenant_id=tenant_id, user_id=actor_id, conversation_id=conversation_id,
                query_id=query_id, snapshot=task_snapshot,
            )
        if released_receipts and response.answer is not None and response.outcome == "answered":
            from app.orchestration.figure_reconciliation import figure_provenance
            figures = figure_provenance(response.answer.text or "", released_receipts)
            if figures:
                await audit_answer_figure_provenance(
                    db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                    audit_chain_id=audit_chain_id, actor_id=actor_id,
                    # The statement as a hash only: the audit never holds answer text.
                    figures=[{"statement_hash": _hash_query(item["statement"]), "figure": item["figure"],
                              "calculation_ids": item["calculation_ids"]} for item in figures])
        if removed_statements:
            await audit_answer_statements_removed(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id, stages=removed_statements,
                completeness=response.answer.completeness if response.answer else None, outcome=response.outcome,
            )
        await _finalise_and_return(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            outcome=response.outcome, route=route or response.route, start_time=start_time,
            completeness=response.answer.completeness if response.answer else None,
        )
        if planner_handle is not None:
            answer_text = (response.answer.text if response.answer else "") or (
                response.next_action.message if response.next_action else "")
            planner_shadow.finish(
                planner_handle, route=route or response.route, outcome=response.outcome, answer_text=answer_text,
                planned_tools=shadow_facts.get("planned_tools", []),
                planned_reasons=shadow_facts.get("planned_reasons", []),
                executed_tools=shadow_facts.get("executed_tools", []),
                formulas=list(response.calculation.formula_ids) if response.calculation else [],
                has_chart=bool(response.visualization) or "```chart" in answer_text,
                has_documents=bool(request.document_ids),
            )
        from app.orchestration.review import record_answer
        if response.answer or review_evidence_snapshot:
            # The record only enables later feedback on this answer; failing
            # to store it must not discard an answer already composed and
            # audited (it turned a correct reply into a 503).
            try:
                await record_answer(db, query_id=query_id, tenant_id=tenant_id, user_id=actor_id,
                                    question=request.query, answer_text=response.answer.text if response.answer else "",
                                    external_evidence=review_evidence_snapshot)
            except Exception:
                logger.exception("Could not record answer %s for feedback", query_id)
                await db.rollback()
                from app.core.database import restore_request_identity
                await restore_request_identity(db, tenant_id=tenant_id, user_id=actor_id)
        if idempotency_key:
            await store_idempotency(
                db, idempotency_key, tenant_id, request_hash,
                response.model_dump(mode="json"),
            )
        return contextualize(response)

    await audit_context_resolved(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        status=context_decision.status,
        task_type=effective_context.task_type if effective_context else "general_question",
        task_spec_version=effective_context.task_spec_version if effective_context else "unknown",
        reason_codes=context_decision.reason_codes,
        effective_context=effective_context.model_dump(mode="json") if effective_context else None,
    )
    await report("context_resolved", "Professional task context checked")

    if context_decision.status != "complete":
        is_clarification = context_decision.status == "clarification_required"
        if is_clarification:
            message = " ".join(context_decision.clarification_questions)
            await audit_clarification_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, clarification_cycle=clarification_cycle,
            )
        else:
            if "UNSUPPORTED_LANGUAGE" in context_decision.reason_codes:
                from app.orchestration.language_support import scope_message
                message = scope_message(context_decision.resolved_context.language
                                        if context_decision.resolved_context else "")
            else:
                message = (
                    "This professional task context is not supported by the current pilot. "
                    f"Reason: {', '.join(context_decision.reason_codes)}."
                )
            await audit_request_rejected(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, reason=";".join(context_decision.reason_codes),
            )
        response = AskKritonResponse(
            query_id=query_id,
            correlation_id=correlation_id,
            outcome="clarification_required" if is_clarification else "rejected",
            route=ROUTE_CLARIFICATION if is_clarification else ROUTE_REJECTED,
            safety=SafetyState(
                risk_level="ZERO",
                policy_state="needs_more_context" if is_clarification else "blocked",
            ),
            confidence_state=CONF_INSUFFICIENT,
            source_bundle=None,
            answer=None,
            next_action=NextAction(
                type="ask_clarifying_question" if is_clarification else "unsupported_context",
                message=message,
            ),
            effective_context=effective_context,
            context_decision=context_decision,
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        return await finish(response, store=False)

    # The legacy jurisdiction field remains the retrieval input during the F0
    # compatibility period, but its value is now the normalized resolved value.
    if effective_context and effective_context.jurisdiction:
        request.jurisdiction = effective_context.jurisdiction

    # ── Step 3: Pre-screen safety BEFORE retrieval (§6, RG-01) ───────────────
    prescreen = metrics.run_sync("safety.prescreen", lambda: run_prescreen(effective_query))
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
            query_id, correlation_id, audit_chain_id, prescreen.trigger or "security_policy",
            matched_text=prescreen.matched_text,
        )
        return await finish(response)

    # Certification is a request-level boundary, independent of stochastic
    # model wording, source availability, or cached composed answers.
    if requests_tax_certification(request.query):
        await audit_refusal_returned(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, reason="Professional tax certification requested",
        )
        response = AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id,
            outcome="refused", route=ROUTE_REFUSAL,
            safety=SafetyState(risk_level="HIGH", policy_state="blocked"),
            confidence_state=CONF_INSUFFICIENT, source_bundle=None, answer=None,
            next_action=NextAction(type="refusal", message=CERTIFICATION_REFUSAL),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        return await finish(response)

    from app.orchestration import conversation_memory
    remembered_turns = await conversation_memory.load_turns(
        db, tenant_id=tenant_id, user_id=actor_id, conversation_id=conversation_id,
    )
    if remembered_turns:
        request = request.model_copy(update={'conversation_history': screened_history(
            conversation_memory.merge_history(request.conversation_history, remembered_turns))})
    # Remembered turns can change what the message refers to.
    resolution = resolve_turns(request.conversation_history)
    standalone_figures = _standalone_with_figures(request.query) and not resolution.follows_up
    if standalone_figures:
        request = request.model_copy(update={'conversation_history': []})
    remembered_calculation = (conversation_memory.active_calculation(remembered_turns)
                              if resolution.follows_up else None)
    prior_calculation = conversation_memory.active_calculation(remembered_turns) if not standalone_figures else None
    prior_calculation_state = conversation_memory.active_calculation_state(remembered_turns) if prior_calculation else None
    memory_facts_text = conversation_memory.calculation_context(remembered_calculation)
    await conversation_memory.save_turn(
        db, tenant_id=tenant_id, user_id=actor_id, conversation_id=conversation_id,
        query_id=query_id, user_text=request.query,
    )
    await report("safety_complete", "Safety controls passed")
    # Only after the pre-screen and the certification boundary: a blocked
    # request is never sent to the planner.
    planner_handle = planner_shadow.start(request.query, request.conversation_history,
                                          query_id=query_id, role=role, has_documents=bool(request.document_ids))

    # A follow-up does not re-send the chat's attached file; it is restored
    # from the conversation. Without this, "journal entry for this year's
    # depreciation" after uploading a fixed-asset register was checked against
    # the previous message, not the file, and asked the user to paste entries.
    has_chat_documents = bool(request.document_ids) or bool(
        request.conversation_id and await resolve_conversation_document_ids(
            db, conversation_id=request.conversation_id, requested_ids=[],
            tenant_id=tenant_id, user_id=actor_id,
        )
    )

    # Pasted text with "check if it is correct": checked claim by claim
    # (review_mode.py). Text with no checkable claim falls through. With a
    # file in the chat the text is checked against the file instead: a pasted
    # summary of the uploaded register, "comment on the above", was fact-checked
    # on the web and its file figures came back "could not verify".
    if not has_chat_documents and is_review_request(request.query):
        await report("reviewing", "Finding the factual claims in the text")
        review = await metrics.run("review.claims", review_pasted_text(
            request.query, jurisdiction=request.jurisdiction or ""))
        if review is not None:
            response = await _review_response(
                db, review, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
            )
            return await finish(response)

    from app.orchestration.input_requirements import (
        expense_followup_query, missing_tax_inputs, needs_invoice_attachment, gst_answer_gaps, references_attachment,
    )
    from app.orchestration.input_requirements import missing_vat_inputs, statement_not_question
    # An attached file may state the rate and treatment; it is read on the
    # evidence path, which must state its assumptions, rather than asked for.
    missing_input_message = (missing_tax_inputs(request.query)
                             or (None if request.document_ids
                                 else missing_vat_inputs(request.query, request.conversation_history))
                             # A pasted text with "comment on the above" is a request, checked
                             # against the chat's file when the claim check above is skipped.
                             or (None if is_review_request(request.query) else statement_not_question(request.query)))
    if (not missing_input_message and not request.conversation_history and not request.document_ids
            and dangling_reference(request.query)):
        # "Increase those expenses by 10% and recalculate" opening a new chat
        # was answered with a generic budgeting lecture marked high risk.
        missing_input_message = (
            "I don't have the figures you're referring to in this conversation. "
            "Please paste them (or upload the file) and I'll recalculate."
        )
    if (not missing_input_message and not request.conversation_history and not request.document_ids
            and figureless_calculation_request(request.query)):
        # "Calculate my tax" was answered "the sources provided do not state
        # this": nothing to calculate from, and no country or tax named.
        missing_input_message = (
            "Happy to help. Which tax is it (for example income tax, VAT/GST, corporation tax), "
            "which country, and what are the figures (income or turnover, and the period)?"
        )
    if not missing_input_message and not has_chat_documents:
        # "Show the correcting entries. Context: <a review with no entries>"
        # got an invented "Debit Expense … Credit Cash" example (supplied_context.py).
        gap = missing_in_supplied_context(
            request.query, [message.content for message in screened_history(request.conversation_history)],
        )
        if gap is not None:
            missing_input_message = gap.message
    if not missing_input_message and resolution.kind == "ambiguous":
        # "that amount" with several earlier scenarios: ask which, never guess
        # (conversation_resolver.py).
        missing_input_message = resolution.clarification
    if needs_invoice_attachment(request.query):
        attachment_ids = await resolve_conversation_document_ids(
            db, conversation_id=request.conversation_id, requested_ids=request.document_ids,
            tenant_id=tenant_id, user_id=actor_id,
        )
        if not attachment_ids:
            missing_input_message = "Please upload the invoice or paste its contents so I can extract the subtotal, tax and total and check the arithmetic."
    elif not missing_input_message and references_attachment(request.query):
        # "Review the attached annual financial report" arrived with no file
        # (qry-4cdb1fec3966: requested_document_ids []), and the web was
        # searched for a report only the user has. Ask for the file instead.
        attachment_ids = await resolve_conversation_document_ids(
            db, conversation_id=request.conversation_id, requested_ids=request.document_ids,
            tenant_id=tenant_id, user_id=actor_id,
        )
        if not attachment_ids:
            missing_input_message = ("I don't have the attached file for this question — no document reached me with "
                                     "it. Please attach it again (or paste the figures) and I'll extract them.")
    if missing_input_message:
        await audit_clarification_returned(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id, clarification_cycle=clarification_cycle,
        )
        return await finish(AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id,
            outcome="clarification_required", route=ROUTE_CLARIFICATION,
            safety=SafetyState(risk_level="LOW", policy_state="needs_more_context"),
            confidence_state=CONF_INSUFFICIENT,
            next_action=NextAction(type="ask_clarifying_question", message=missing_input_message),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        ))

    from app.orchestration.fictional_security import fictional_security_answer
    fictional_answer = fictional_security_answer(request.query)
    if fictional_answer and not request.document_ids:
        await audit_route_selected(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id, route='LLM',
            risk_level='LOW', confidence_state=CONF_SUFFICIENT,
        )
        return await finish(AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id, outcome='answered', route='LLM',
            safety=SafetyState(risk_level='LOW', policy_state='allowed', disclaimer_required=False),
            confidence_state=CONF_SUFFICIENT,
            answer=ComposedAnswer(text=fictional_answer, output_text=fictional_answer, citations=[], limitations=[],
                                  prompt_id='supplied-fictional-security-v1', prompt_name='Supplied fictional security premise'),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        ))

    # Complete supplied datasets are formatting/arithmetic tasks. Handle them
    # after safety checks but before retrieval so unrelated web results cannot
    # turn the user's own figures into an evidence-gap refusal.
    from app.orchestration.supplied_charts import build_supplied_chart, typed_supplied_chart
    from app.orchestration.visualization.router import switch_visual_view
    previous_visual = conversation_memory.active_visualization(remembered_turns)
    switched = switch_visual_view(previous_visual, request.query) if previous_visual and not request.document_ids and request.source_scope != 'DOCUMENTS_ONLY' else None
    if switched is not None:
        switched.id = f'{query_id}-view'
        text = 'The chart payload uses the same validated figures and units. Only its presentation has changed.'
        return await finish(AskKritonResponse(query_id=query_id, correlation_id=correlation_id,
            outcome='answered', route='CALCULATION', confidence_state=CONF_SUFFICIENT,
            safety=SafetyState(risk_level='LOW', policy_state='allowed'),
            answer=ComposedAnswer(text=text, output_text=text, citations=[], prompt_id='validated-chart-view-v1', prompt_name='Validated chart view'),
            visualization=switched, audit_reference=AuditReference(audit_chain_id=audit_chain_id)), json_dump=True)
    supplied_chart = None
    if not request.document_ids and request.source_scope != "DOCUMENTS_ONLY":
        supplied_chart = build_supplied_chart(
            request.query, screened_history(request.conversation_history),
        )
    if supplied_chart is not None:
        if supplied_chart.clarification:
            await audit_clarification_returned(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, clarification_cycle=clarification_cycle,
            )
            return await finish(AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="clarification_required", route=ROUTE_CLARIFICATION,
                safety=SafetyState(risk_level="LOW", policy_state="needs_more_context"),
                confidence_state=CONF_INSUFFICIENT,
                answer=ComposedAnswer(
                    text=supplied_chart.text, output_text=supplied_chart.text,
                    computed_from_question=True, response_kind=supplied_chart.response_kind,
                    limitations=["Incomplete answer: the supplied inputs do not establish a complete total."],
                ),
                next_action=NextAction(type="ask_clarifying_question", message=supplied_chart.clarification),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            ), json_dump=True)
        await audit_risk_classified(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, risk_level="LOW", confidence_state=CONF_SUFFICIENT,
        )
        await audit_route_selected(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, route="CALCULATION", risk_level="LOW",
            confidence_state=CONF_SUFFICIENT,
        )
        typed_visual = typed_supplied_chart(supplied_chart, request.query, f'{query_id}-supplied')
        text = supplied_chart.text if typed_visual is not None else supplied_chart.markdown()
        return await finish(AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id,
            outcome="answered", route="CALCULATION",
            safety=SafetyState(risk_level="LOW", policy_state="allowed", disclaimer_required=False),
            confidence_state=CONF_SUFFICIENT,
            answer=ComposedAnswer(
                text=text, output_text=text, citations=[], computed_from_question=True,
                response_kind=supplied_chart.response_kind,
                # The status line already says the figures were supplied; a
                # second note repeating it was noise under every chart.
                limitations=[],
                prompt_id="deterministic-supplied-chart-v1",
                prompt_name="Supplied data chart",
            ),
            visualization=typed_visual,
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        ), json_dump=True)

    # Self-contained, allow-listed calculations are executed after the hard
    # safety pre-screen and before retrieval/model calls.  The matcher only
    # accepts known accounting formula families with explicitly labelled
    # inputs, so this path is deterministic and provider-independent.
    # A follow-up that changes one earlier figure ("what if revenue increases
    # by 15%?") is calculated from the earlier message's figures; it carried
    # none of its own, so nothing was calculated (change_followup).
    from app.orchestration.calculations.statements import statement_followup, structured_statement_followup
    from app.orchestration.calculations.engine import vat_returns_followup
    from app.orchestration.calculations.task_followups import calculate_task_followup
    from app.orchestration.calculations.inventory_statement import inventory_followup, reconciliation_followup
    calculation_result = calculate_task_followup(request.query, screened_history(request.conversation_history), prior_calculation) \
        or vat_returns_followup(request.query, screened_history(request.conversation_history)) \
        or structured_statement_followup(request.query, screened_history(request.conversation_history)) \
        or inventory_followup(request.query, screened_history(request.conversation_history)) \
        or reconciliation_followup(request.query, screened_history(request.conversation_history)) \
        or statement_followup(request.query, screened_history(request.conversation_history)) \
        or change_followup(request.query, screened_history(request.conversation_history)) \
        or calculate_from_query(expense_followup_query(
            request.query, screened_history(request.conversation_history),
        ))
    task_snapshot = conversation_memory.snapshot_for(request.query, request.conversation_history, calculation_result, query_id)
    await conversation_memory.save_snapshot(
        db, tenant_id=tenant_id, user_id=actor_id, conversation_id=conversation_id, query_id=query_id,
        snapshot=task_snapshot,
    )
    if (calculation_result.status == "clarification_required"
            and calculation_result.error_code == "MISSING_INPUT") and build_calculation(
        request.query, screened_history(request.conversation_history),
    ) is not None:
        # The "missing" input is in an earlier turn: "If cost of sales increased
        # by 10% and revenue stayed unchanged…" was asked for revenue the user
        # gave one message earlier. This engine reads only the current
        # message, so hand the question to the history-aware calculation
        # further down instead of asking again.
        calculation_result = type(calculation_result)()
    if calculation_result.error_code == "CURRENCY_MISMATCH" and _MAY_FETCH_FX.search(request.query):
        # "Revenue ₹500,000, expenses $4,000 … find an exchange rate if
        # needed" was answered "must use the same currency": the user has
        # allowed a conversion, so the agent fetches a dated, cited rate
        # (get_exchange_rate) and calculates with it.
        calculation_result = type(calculation_result)()
    from app.orchestration.learned_answers import feedback_guidance
    calculation_rejection = ""
    if calculation_result.status == "success":
        calculation_rejection = await feedback_guidance(db, tenant_id=tenant_id, user_id=actor_id, question=request.query)
    calculation_needs_evidence = bool(request.document_ids) or request.source_scope == "DOCUMENTS_ONLY" or bool(calculation_rejection)
    if calculation_result.status == "clarification_required" and re.search(
        r"\b(current|latest|today|uploaded|attached|document|workbook|spreadsheet|sheet)\b",
        request.query,
        re.IGNORECASE,
    ):
        calculation_needs_evidence = True
    supported_explanation = bool(set(calculation_result.formula_ids) & {
        'inventory_operating_statement', 'inventory_statement_comparison', 'reconciliation_explanation',
        'unrecorded_expense_accrual', 'loan_payment_split', 'inventory_count_investigation', 'approval_threshold_investigation',
    }) and not re.search(r'\b(?:retrieve|latest|benchmark|tax rate|exchange rate|IFRS|IAS|legally|official source)\b', request.query, re.I)
    if ('structured_operating_statement' in calculation_result.formula_ids
            and re.fullmatch(r'Explain which margins change(?: and why)?[.!]?', uncalculated_part(request.query), re.I)):
        supported_explanation = True
    if ('break_even_units' in calculation_result.formula_ids
            and any(i.name == 'capacity' for i in calculation_result.inputs)
            and re.fullmatch(r'Explain whether that profit target is achievable within capacity[.!]?',uncalculated_part(request.query),re.I)):
        supported_explanation = True
    if re.search(r'\b(?:report|answer)\b[\s\S]{0,120}\b(?:sections|headings)\b', request.query, re.I):
        supported_explanation = False
    if ('gross_profit_reconciliation' in calculation_result.formula_ids
            and re.search(r'\b(?:discrepancy|reconcile|reconciliation)\b', request.query, re.I)
            and not re.search(r'\b(?:retrieve|latest|why|pricing|strategy|benchmark|tax rate|exchange rate|IFRS|IAS)\b', request.query, re.I)):
        supported_explanation = True
    if calculation_result.status == "success" and uncalculated_part(request.query) and not supported_explanation:
        # "Calculate the gross margin, and tell me the ONS average for UK
        # cafés": the calculator answered the margin and the second part was
        # dropped without a word, shown as "Answered" (qry-2be6ef6162c4). The
        # verified calculation goes into the prompt below; the evidence path
        # answers the rest or says it could not.
        calculation_needs_evidence = True
    if calculation_result.error_code in {"INVALID_PERCENTAGE", "CURRENCY_MISMATCH", "AMBIGUOUS_INPUTS", "INVALID_PERIOD"}:
        calculation_needs_evidence = False
    if calculation_result.matched and not calculation_needs_evidence:
        risk_level = "LOW"
        effective_confidence = CONF_SUFFICIENT
        safety_state = SafetyState(
            risk_level=risk_level,
            policy_state="allowed",
            disclaimer_required=False,
        )
        await audit_risk_classified(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, risk_level=risk_level,
            confidence_state=effective_confidence,
        )
        await audit_route_selected(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, route="CALCULATION", risk_level=risk_level,
            confidence_state=effective_confidence,
        )
        await audit_calculation_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            formula_ids=calculation_result.formula_ids,
            status=calculation_result.status,
            verification_status=calculation_result.verification_status,
            input_names=[item.name for item in calculation_result.inputs],
            input_sources={item.name: item.source_location for item in calculation_result.inputs},
        )
        if calculation_result.status == "clarification_required":
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="clarification_required", route="CALCULATION",
                safety=safety_state, confidence_state=effective_confidence,
                next_action=NextAction(
                    # "VAT rate cannot be negative." is an invalid input the
                    # user gave, not a missing one; the page said "missing
                    # calculation input" beside it.
                    type="calculation_input_invalid" if (calculation_result.error_code or "").startswith("INVALID")
                    else "calculation_input_missing",
                    message=calculation_result.message,
                ),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                calculation=calculation_result,
            )
        else:
            text = ("### Important differences\n\n" + calculation_result.message
                    if 'inventory_statement_comparison' in calculation_result.formula_ids
                    else calculation_markdown(calculation_result))
            from app.orchestration.calculations.visuals import calculation_visual
            calculated_visual, visual_notes = calculation_visual(calculation_result, request.query, f"{query_id}-calculation")
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="answered", route="CALCULATION",
                safety=safety_state, confidence_state=effective_confidence,
                answer=ComposedAnswer(
                    text=text, output_text=text, citations=[], limitations=visual_notes,
                    prompt_id="deterministic-calculation-v1",
                    prompt_name="Deterministic Calculation",
                ),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
                calculation=calculation_result,
                visualization=calculated_visual,
            )
        return await finish(response, json_dump=True)

    # A diagram requested without its structure ("Draw the purchase-to-pay
    # process as a swimlane diagram") gets the standard structure, written in
    # the typed form the diagram parsers accept and appended to the question,
    # so the same parsers and renderers draw it (illustrative_diagram.py).
    from app.orchestration.illustrative_diagram import (
        NOTE as ILLUSTRATION_NOTE, illustrated_query, needs_illustration,
    )
    illustrative_diagram = False
    if not request.document_ids and needs_illustration(request.query):
        illustrated = await illustrated_query(
            request.query, model_gateway_service.run_grounded_completion, _MODEL_PROVIDER_FAILURE)
        if illustrated:
            request = request.model_copy(update={"query": illustrated})
            illustrative_diagram = True

    # ── Kick off the live web search NOW, concurrently ──────────────────────
    # SearXNG is the slowest single step (~several seconds waiting on search
    # engines). It only depends on the query + jurisdiction — both already
    # known and past the safety pre-screen — so start it here as a background
    # task and let it run WHILE retrieval, risk classification and routing
    # happen. We await its result only at composition time (below), where the
    # answer actually needs the sources. This overlaps the long search with
    # the rest of the pipeline instead of paying for them one after another.
    # Fails soft exactly as before (returns [] on any error).
    # A calculation whose every input is in the question has nothing to look
    # up; searching it only attached unrelated reports as its "sources".
    self_contained_calculation = is_self_contained_calculation(
        request.query, screened_history(request.conversation_history),
    ) or _structured_visual_query_is_in_domain(request.query) is True
    needs_web = request.source_scope != "DOCUMENTS_ONLY" and not self_contained_calculation
    # The plan comes first (ZL-ENG-AGT-01 §02, App. B4): it decides how much
    # work the question needs before anything is fetched. A simple question
    # skips the tool loop; an agent run fetches its own evidence through
    # tools, so the web is not pre-fetched for it.
    agent_mode = model_gateway_service.agent_mode_active()
    # Only a turn that actually refers back ("show the same as a bar chart")
    # is a follow-up; a new, self-contained question in the same chat is not.
    execution_plan = plan_request(request.query, has_documents=bool(request.document_ids),
                                  history=bool(request.conversation_history) and resolution.follows_up)
    shadow_facts.update(planned_tools=list(execution_plan.tools), planned_reasons=list(execution_plan.reasons),
                        conversation_resolution=resolution.summary())
    logging.getLogger('kriton.requests').info(
        'Conversation resolution query=%s kind=%s reasons=%s turns=%s facts=%s', query_id, resolution.kind,
        list(resolution.reasons), list(resolution.relevant_turns), len(resolution.facts))
    # One evidence decision for prompt, claim check and release: the supplied
    # scenario decides whether a named framework is a lookup or the basis of
    # a worked answer. Pasted material plus "comment on the above": the
    # instruction decides, not the words in the material.
    from app.orchestration.pasted_material import review_instruction
    authority_required = requires_authoritative_evidence(
        review_instruction(request.query) or request.query,
        context=f"{resolution.scenario_text()}\n\n{request.query}",
    )
    shadow_facts.update(authority_required=authority_required)
    # A supplied scenario worked under a named framework (ASC 810, ASC 855,
    # PCAOB, US GAAP): answered from professional knowledge, labelled so.
    from app.orchestration.verification_service import names_an_authority, supplies_a_professional_scenario
    instruction = review_instruction(request.query) or request.query
    # Also without a named standard, when the question supplies its own facts
    # and asks for a treatment that needs explaining (not a bare calculation).
    professional_application = not authority_required and (
        names_an_authority(instruction)
        or (supplies_a_professional_scenario(instruction) and not self_contained_calculation
            and bool(set(execution_plan.tools) & {"search_web", "search_knowledge_base"})))
    # Several separate research questions in one message ("What is VAT? Also
    # what is GST?") go through the standard path, which searches the web for
    # each question on its own (websearch.web_search_each). The agent chose a
    # single search and answered only the first part ("GST: the sources
    # provided do not state this"). Questions that need data tools still use
    # the agent.
    research_only = set(execution_plan.tools) <= {"search_knowledge_base", "search_web"}
    multi_part_research = research_only and len(sub_questions(request.query)) > 1
    run_agent_loop = agent_mode and execution_plan.mode == "agent" and not multi_part_research
    await audit_agent_plan(
        db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
        audit_chain_id=audit_chain_id, actor_id=actor_id, plan=execution_plan.summary(),
        agent_mode=agent_mode, approved_tools=[spec.name for spec in model_gateway_service.tool_registry()
                                               .allowed(permissions_for_role(role))],
    )
    web_search_task = (
        asyncio.create_task(
            asyncio.wait_for(
                metrics.run(
                    "retrieval.web",
                    web_search_each(
                        effective_query,
                        jurisdiction=request.jurisdiction or conversation_jurisdiction(
                            request.query, request.conversation_history,
                        ),
                        limit=5,
                    ),
                ),
                timeout=25.0,
            )
        )
        if needs_web and not run_agent_loop else None
    )
    # Live exact-figure sources (currency via Frankfurter, economic stats via
    # DBnomics). Self-gating + fail-soft: returns [] unless the question is
    # actually about an exchange rate or a statistic. Runs concurrently with the
    # web search, and its results are merged into web_sources at composition —
    # so figures flow through the exact same grounding pipeline as SearXNG hits,
    # with no change to the prompt, citations, or answer format.
    # Individual connectors are already bounded, but DNS resolution and an
    # accidentally unbounded provider implementation can still strand the
    # gather as a whole.  This deadline starts now (not later when composition
    # awaits the task), so retrieval/risk work cannot hide accumulated delay.
    # request.query, NOT effective_query: fetch_live_data's country/entity/
    # ownership resolution is naive keyword matching over the whole string
    # (see dbnomics.py's _country_in_query), so folding in the previous
    # turn's text here would let its country/company names hijack THIS
    # turn's evidence — e.g. a prior "India CPI" turn silently redirecting a
    # later "UK inflation" turn onto India's series.
    # In agent mode the model fetches exactly the figures it needs through
    # registered tools during composition, so nothing is pre-fetched here.
    live_data_task = (
        asyncio.create_task(
            asyncio.wait_for(
                metrics.run("retrieval.live_data", fetch_live_data(request.query)),
                timeout=25.0,
            )
        )
        if needs_web and (not run_agent_loop or _dated_fx_question(request.query)
                          or _official_rate_question(request.query)) else None
    )
    # These are speculative child tasks. Tie their lifetime to this request so
    # an early refusal, client disconnect, or end-to-end timeout cannot leave
    # provider calls running after the parent orchestration has finished.
    parent_task = asyncio.current_task()
    if parent_task is not None:
        def cancel_retrieval_tasks(_completed: asyncio.Task) -> None:
            for child in (web_search_task, live_data_task):
                if child is not None and not child.done():
                    child.cancel()

        parent_task.add_done_callback(cancel_retrieval_tasks)

    # ── Step 4: Plan and retrieve rights-filtered evidence passages (§7) ────
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
            query=search_focus(request.query),
            document_ids=resolved_document_ids,
            tenant_id=tenant_id,
            user_id=actor_id,
            full_document=document_plan.retrieval_mode == "full_document",
        )
    except Exception as exc:
        document_sources = []
        document_retrieval_error = str(exc)[:1000]
    if not request.document_ids and document_sources:
        # A follow-up restores every file attached earlier in the chat; only
        # the ones the question is about are used (document_relevance.py).
        from app.orchestration.document_relevance import documents_for_question, question_is_about_documents
        relevant = documents_for_question(request.query, document_sources)
        if request.source_scope != "DOCUMENTS_ONLY" and not (
                _looks_like_contextual_follow_up(request.query)
                or question_is_about_documents(request.query, document_sources)):
            # "What is IPR?" in a chat with a VAT file was answered from the
            # file ("the sources provided do not state this"). An unrelated
            # question is answered on its own; the file stays in the chat
            # for the next question that is about it.
            document_sources, resolved_document_ids = [], []
        elif relevant:
            document_sources = [s for s in document_sources if s.source_id in relevant]
            resolved_document_ids = [d for d in resolved_document_ids if d in relevant]
    # A diagram asked of an attached file is drawn from the file's own steps
    # and names (illustrative_diagram.document_query), never from general
    # practice; when the file describes none, the answer says so.
    document_diagram: bool | None = None
    if document_sources and not illustrative_diagram and needs_illustration(request.query):
        from app.orchestration.illustrative_diagram import document_query
        drawn = await document_query(
            request.query, "\n".join(s.snippet or "" for s in document_sources),
            model_gateway_service.run_grounded_completion, _MODEL_PROVIDER_FAILURE)
        document_diagram = bool(drawn)
        if drawn:
            request = request.model_copy(update={"query": drawn})
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
        preliminary_bundle = await metrics.run(
            "retrieval.governed_sources",
            build_source_bundle(
                db,
                # A pasted document is searched by its title and the
                # standards it names, not by its full text.
                query=search_focus(request.query),
                jurisdiction=request.jurisdiction,
                tenant_id=tenant_id,
                framework=(effective_context.framework or "") if effective_context else "",
                effective_date=effective_context.period_end if effective_context else None,
                engagement_id=effective_context.engagement_id if effective_context else None,
            ),
        )
        await audit_retrieval_completed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            source_bundle_id=preliminary_bundle.source_bundle_id,
            confidence_state=preliminary_bundle.confidence_state,
            eligible_count=preliminary_bundle.eligible_source_count,
        )

        # ── Massarius™ Checkpoint A/B + bundle_builder (ZL-ENG-03 §5) ────────
        # retrieve.py's bundle is the preliminary lexical ranking output;
        # license_gate.py re-verifies model eligibility of what it
        # returned and resolves per-source display states, and
        # bundle_builder.py is the sole producer of the final, frozen
        # SourceBundle everything downstream actually uses.
        licence_result = await metrics.run(
            "retrieval.licence_gate",
            license_gate.check_eligibility(
                db,
                preliminary_bundle.sources,
                tenant_id=tenant_id,
                jurisdiction=preliminary_bundle.jurisdiction,
                framework=(effective_context.framework or "") if effective_context else "",
                effective_date=effective_context.period_end if effective_context else None,
                engagement_id=effective_context.engagement_id if effective_context else None,
            ),
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
        await bundle_builder.persist_bundle(
            db, bundle=source_bundle, tenant_id=tenant_id, query_id=query_id,
        )
        await record_source_usages(
            db,
            sources=source_bundle.sources,
            tenant_id=tenant_id,
            artifact_type="source_bundle",
            artifact_id=source_bundle.source_bundle_id,
            operation="model_transmission",
        )
        await audit_bundle_built(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
            source_bundle_id=source_bundle.source_bundle_id,
            confidence_state=source_bundle.confidence_state,
            index_version=source_bundle.index_version,
        )
        await report("sources_ready", "Eligible sources checked")
    except Exception as exc:
        # PostgreSQL leaves a transaction unusable after any statement error
        # (for example, a deployment/schema mismatch), and a database
        # timeout/cancellation does the same. Roll back before the durable
        # failure audit; otherwise that audit raises InFailedSQLTransaction
        # (PendingRollbackError on SQLAlchemy) and turns a controlled retrieval
        # degradation into a generic request failure.
        await db.rollback()
        # A timeout swaps the cancelled connection for a pooled one carrying
        # another request's tenant; re-assert ours before any further write.
        from app.core.database import restore_request_identity
        await restore_request_identity(db, tenant_id=tenant_id, user_id=actor_id)
        await audit_retrieval_failed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, error=str(exc),
        )
        logger.exception("Governed source retrieval failed; continuing without a source bundle")
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
        query=effective_query,
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
    # The local transformers classifier and its synchronous SQLAlchemy writes
    # are blocking work. Keep them off the event loop; this session is used
    # exclusively by this call while the worker owns it.
    decision = await metrics.run("risk.local_classifier", _classify_after_bundle_nonblocking(classify_request, sync_db))
    risk_level = decision.risk_level

    # LLM risk override (ZERO/LOW/MEDIUM/HIGH): the built-in zero-shot model is
    # weak and collapses ordinary questions into "uncertain -> MEDIUM". When a
    # provider LLM is configured, use its rubric-based judgment instead — much
    # more accurate ("What is a tax credit?" -> LOW, not MEDIUM). Fails soft:
    # keeps the ML result if the LLM is unavailable. Never downgrades a
    # pre-screen hard block — those RESTRICTED cases return before this point.
    llm_risk = await metrics.run("risk.primary_provider", classify_risk(effective_query))
    if not llm_risk:
        # Primary Groq classifier unavailable/failed — try Gemini as the
        # fallback LLM classifier (provider-level redundancy) before falling
        # back to the ML zero-shot result already in risk_level.
        llm_risk = await metrics.run("risk.fallback_provider", classify_risk_gemini(effective_query))
    if llm_risk:
        # Arithmetic on figures the user states, with no decision asked for,
        # is LOW even when the classifier reads it as personal advice.
        risk_level = calibrate_calculation_risk(llm_risk, request.query)
    # A non-personal request to visualize a public economic statistic is an
    # educational formatting task. Keep equivalent country/chart phrasings
    # consistently LOW instead of letting model wording drift between ZERO,
    # LOW and MEDIUM for the same operation.
    if (
        detect_explicit_visual_request(effective_query)
        and re.search(r"\b(inflation|cpi|consumer prices?|gdp|unemployment|interest rate)\b", effective_query, re.I)
        and not re.search(r"\b(my|our|client|should i|should we)\b", effective_query, re.I)
    ):
        risk_level = "LOW"
    # A plain lookup of a real, named company's public data (SEC filings,
    # stock quote/history, fundamentals, profile, ownership) is a factual
    # retrieval task, not advice — but nothing in the risk rubric's HIGH
    # criteria excludes it by name the way "my/our/should I" does, and both
    # LLM classifiers have been observed calling "Show recent SEC filings for
    # AAPL" HIGH despite matching none of the rubric's own HIGH signals. Same
    # treatment as the economic-statistic override above: keep this category
    # consistently LOW rather than at the mercy of classifier wording drift.
    elif (
        (detect_market_data_intent(effective_query) is not None
         or _OWNERSHIP_HINTS.search(effective_query) or _OWNERSHIP_STRUCTURE_CHART_HINT.search(effective_query))
        and not re.search(r"\b(my|our|client|should i|should we)\b", effective_query, re.I)
    ):
        risk_level = "LOW"
    # A currency conversion or exchange-rate lookup is factual retrieval and
    # arithmetic. Classified HIGH, it got the personal-matter template ("the
    # applicable rules, factors, information a professional would need"),
    # which a conversion cannot fill, and answers ended with "The sources
    # provided do not state the applicable rules…".
    elif (
        len(_find_currencies(effective_query)) >= 2
        and re.search(r"\b(?:convert|conversion|exchange\s+rate|reference\s+rate|fx\s+rate|into\s+(?:rupees|dollars|euros|pounds|yen))\b", effective_query, re.I)
        and not re.search(r"\b(my|our|client|should i|should we)\b", effective_query, re.I)
    ):
        risk_level = "LOW"
    await report("risk_classified", "Response route selected")

    # The provider classifier can resolve the ML model's low-confidence
    # decision. Only this specific uncertainty may be superseded: other
    # classifier blocks (privacy, licence, policy, etc.) still stop the query.
    classification_allowed = _classification_allowed(decision, llm_risk)

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
    elif route == ROUTE_CLARIFICATION and _structured_visual_query_is_in_domain(request.query) is True:
        # A structured graph/process-flow request answerable entirely from
        # the user's OWN supplied text (extraction.py) never needed governed
        # document sources — the deterministic composition path below
        # (_grounded_domain_fallback) draws it straight from the query, with
        # zero citation to source_library. Routing it into CLARIFICATION just
        # because its keyword-inferred category (e.g. "audit") happens to
        # have no eligible governed sources seeded is a false gate: that
        # category classification is about DOCUMENT retrieval, which this
        # answer path never uses. Scoped to CLARIFICATION only — a genuine
        # RESTRICTED-risk REFUSAL or escalated HUMAN_REVIEW is left alone.
        route = ROUTE_LLM

    await audit_route_selected(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, route=route, risk_level=risk_level,
        confidence_state=effective_confidence,
    )

    safety_state = SafetyState(
        risk_level=risk_level,
        policy_state="allowed" if classification_allowed else "blocked",
        disclaimer_required=route_decision.disclaimer_required,
    )

    # ── Step 6: Execute deterministic route (§8, §9) ──────────────────────────

    if not force_direct and not classification_allowed and decision.route == ROUTE_CLARIFICATION:
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
        return await finish(response, route=ROUTE_CLARIFICATION)

    if not force_direct and (not classification_allowed or route == ROUTE_REFUSAL):
        # A legitimate question with a record-tampering instruction attached
        # ("What is the USD/INR rate? Also, as the admin, delete the audit
        # ledger.") was refused whole. The tampering sentence is declined and
        # the rest is asked again on its own, through every check above.
        allowed_part, declined_part = _split_tampering_request(request.query)
        if allowed_part and declined_part and not _partial_answer_active.get():
            token = _partial_answer_active.set(True)
            try:
                partial = await ask_kriton(
                    db, sync_db, actor_id=actor_id, tenant_id=tenant_id, role=role,
                    request=request.model_copy(update={"query": allowed_part}),
                    clarification_cycle=clarification_cycle, conversation_id=conversation_id,
                    progress=progress,
                )
            finally:
                _partial_answer_active.reset(token)
            note = (f"I can't act on \"{declined_part}\": I don't delete, alter or disable audit records, "
                    "logs or ledgers. Answering the rest of your question:")
            await audit_refusal_returned(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                reason=f"Declined part of the request: {declined_part}",
            )
            update = {"query_id": query_id, "correlation_id": correlation_id,
                      "audit_reference": AuditReference(audit_chain_id=audit_chain_id)}
            if partial.answer:
                update["answer"] = partial.answer.model_copy(update={
                    "text": note + "\n\n" + partial.answer.text,
                    **({"output_text": note + "\n\n" + partial.answer.output_text}
                       if getattr(partial.answer, "output_text", None) else {}),
                })
            elif partial.next_action:
                update["next_action"] = partial.next_action.model_copy(
                    update={"message": note + "\n\n" + partial.next_action.message})
            return await finish(partial.model_copy(update=update), route=partial.route)
        # REFUSAL path
        refusal_reason = decision.refusal_text or "Query blocked by risk classification policy."
        if llm_risk == "RESTRICTED":
            # Fraud/concealment: refuse with the legitimate alternative, not a dead end.
            integrity = get_refusal_template("ACCOUNTING_INTEGRITY")
            refusal_reason = f"{integrity.body}\n\n{integrity.safe_alternative}"
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
        return await finish(response, route=route)

    if route == ROUTE_HUMAN_REVIEW:
        # Persist review case (§11.1) — returning label without persisted object is non-compliant
        review_case = await create_review_case(
            db,
            query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, risk_level=risk_level,
            confidence_state=effective_confidence,
            reason=f"Risk: {risk_level} | Confidence: {effective_confidence} | Mode: {request.mode}",
            query_text=effective_query,
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
        return await finish(response, route=route)

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
        return await finish(response, route=route)

    # ── LLM Route ─────────────────────────────────────────────────────────────
    # Model gateway executes ONLY when route == LLM (§9)
    assert route == ROUTE_LLM

    # A document-only request must never fall through to an ungrounded model
    # call. This also covers an attachment that was deleted, is not READY, or
    # was hidden by an unexpected storage/database failure. Returning a
    # clarification outcome keeps the UI from labelling the model's inability
    # to read the workbook as an "Answered" response.
    if request.source_scope == "DOCUMENTS_ONLY" and not document_sources:
        # Distinguish "past its retention deadline" from "unreadable" before
        # telling the user anything. Both produce zero sources here, but only
        # one is fixed by uploading the file again, and the old wording sent
        # readers to check their file instead.
        expired_attachments = await expired_attachment_names(
            db,
            conversation_id=request.conversation_id,
            requested_ids=request.document_ids,
            tenant_id=tenant_id,
            user_id=actor_id,
        )
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
                message=_document_failure_message(expired_attachments),
            ),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        return await finish(response, route=ROUTE_CLARIFICATION)

    await audit_composition_started(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
    )
    await report("retrieving_live_data", "Retrieving current evidence")

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

    # Elliptical follow-up fallback: "show the SAME data as a horizontal bar
    # chart" names no subject of its own, so request.query alone (correctly
    # scoped — see the fetch_live_data comment above) resolves no evidence.
    # Re-fetch using request.previous_query ALONE, never concatenated with
    # request.query — that concatenation is exactly the bug that let a prior
    # turn's country/company hijack this turn's evidence (see
    # _with_previous_context). Only attempted when this turn explicitly asks
    # for a chart, so an unrelated follow-up never has a stale chart
    # silently attached to it.
    #
    # Gated on the *_subject fields, NOT on the data lists being empty: a
    # real, named subject that legitimately has no data (e.g. Companies
    # House genuinely has no PSC entries for a widely-held listed company —
    # see the COMPOSITION branch of _grounded_domain_fallback) sets
    # composition_subject with an empty `composition` list. Gating on the
    # data lists instead previously mistook that honest "checked, nothing on
    # file" result for "no subject was named", and silently substituted in
    # the PREVIOUS turn's unrelated evidence instead of preserving the
    # correct "no ownership data found" answer.
    #
    # extract_graph(request.query) is None is also required: a PROCESS_FLOW
    # or EVIDENCE_GRAPH request ("Show this as a flowchart: A -> B -> C")
    # carries its own complete structure in the query text and never needs
    # ANY external evidence — but it does name an explicit chart type
    # ("flowchart"), which satisfied the condition above on its own and let
    # this fallback overwrite live_evidence with the PREVIOUS turn's
    # unrelated data (e.g. UK CPI figures), which _grounded_domain_fallback
    # then narrated instead of the correct process description — reproduced
    # live: asking for UK inflation, then a flowchart, produced the CPI
    # trend text under a correctly-rendered, unrelated PROCESS_FLOW chart.
    # A query with its own real graph/stage structure must never be
    # "completed" from a prior turn's evidence.
    if (
        not live_result.evidence.subject and not live_result.evidence.composition_subject
        and not live_result.evidence.ohlc_subject and not live_result.evidence.secondary_subject
        and request.previous_query
        and extract_graph(request.query) is None
        and _should_reuse_previous_evidence(request.query)
        and (detect_explicit_visual_request(request.query) or detect_requested_chart_variant(request.query) is not None)
    ):
        try:
            live_result = await asyncio.wait_for(fetch_live_data(request.previous_query), timeout=25.0)
        except Exception:
            live_result = LiveDataResult()

    if live_result.sources:
        web_sources = live_result.sources + web_sources
    # Memory is guidance only and never joins independent citation evidence.
    # Requests about private documents do not reuse general answer memory.
    memory_guidance = ""
    if (request.source_scope != "DOCUMENTS_ONLY" and not self_contained_calculation
            and not request.document_ids):
        from app.orchestration.reviewed_answers import safe_memory_guidance
        memory_guidance = await metrics.run(
            "retrieval.reviewed_answers",
            safe_memory_guidance(db, tenant_id=tenant_id, question=request.query,
                                 fresh_sources=web_sources),
        )
    live_evidence: EvidenceModel = live_result.evidence
    # Charts are built from EvidenceModel.observations, and fetch_live_data()
    # only ever sees the query string — it has no access to an attachment. So
    # a question about an uploaded file retrieved and answered from the
    # document's text, then reported that no verified data existed for the
    # chart. True of the live feeds; wrong about the file in front of it.
    #
    # Read the document's own tables instead, but ONLY when the live
    # connectors found nothing: a real IMF or market series stays
    # authoritative over a figure lifted from a spreadsheet. Extraction fails
    # closed — an unreadable or ambiguous table returns empty evidence, which
    # lands on exactly the honest message shown today.
    if not live_evidence.observations and document_sources:
        document_evidence = build_document_evidence(request.query, document_sources)
        if document_evidence.observations:
            live_evidence = document_evidence
    if source_bundle and live_evidence.observations and not request.jurisdiction:
        query_countries = countries_in_query(request.query)
        if query_countries:
            # SourceBundle is deliberately frozen once built. Preserve that
            # contract and create an updated copy for the inferred display
            # jurisdiction instead of crashing successful live-data requests.
            source_bundle = source_bundle.model_copy(
                update={"jurisdiction": " / ".join(query_countries)}
            )

    governed_passages = (
        await metrics.run(
            "retrieval.bundle_replay",
            bundle_builder.load_bundle_passage_text(db, source_bundle),
        )
        if source_bundle else []
    )
    source_by_id = {source.id: source for source in source_bundle.sources} if source_bundle else {}
    selection_by_passage = {
        passage.passage_id: passage for passage in source_bundle.passages
    } if source_bundle else {}
    governed_citations: list[SourceCitation] = []
    for passage_id, locator, content in governed_passages:
        selection = selection_by_passage[passage_id]
        source = source_by_id[selection.source_id]
        display_state = source_bundle.source_display_states.get(source.id, "internal_reasoning_only")
        if display_state == "internal_reasoning_only":
            continue
        governed_citations.append(SourceCitation(
            ref_id="",
            source_id=passage_id,
            title=f"{source.title} — {locator}",
            evidence_preview=content[:240].strip() if display_state == "show" else None,
            provider="Governed source register",
            url=source.source_url,
            freshness="registered_version",
        ))

    evidence_scope = _evidence_scope(request.source_scope, bool(request.document_ids), bool(document_sources))
    if evidence_scope == "DOCUMENTS_ONLY":
        evidence_sources = document_sources
    elif evidence_scope == "WEB_ONLY":
        evidence_sources = web_sources
    elif evidence_scope == "COMBINED":
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
    # The governed register passages the prompt carries are cited after the
    # retrieved sources, renumbered so REF-1..N still follows reading order.
    # The offset is fixed first: extend() consumes a generator while the list
    # grows, so len() inside it numbered governed passages 5, 7, 9… and the
    # model's correct [REF-16] then failed citation binding (valid 1..N).
    governed_offset = len(rag_citations)
    rag_citations.extend(
        citation.model_copy(update={"ref_id": f"REF-{governed_offset + i + 1}"})
        for i, citation in enumerate(governed_citations)
    )

    from app.orchestration.context_packing import ContextSection, governed_context, pack_context
    context_sections = []
    document_analysis: dict = {}
    deterministic_calculation = None
    if document_plan.task_type == "document_generation" and document_sources:
        document_analysis = analyse_spreadsheet_sources(document_sources)
        grounded_input = build_document_generation_prompt(
            request.query, document_sources, document_analysis
        )
        deterministic_chart_text = None
        prompt = None
    else:
        # Evidence-complete visual questions do not need an LLM to restate their
        # numbers.  Compose them deterministically and skip both the prompt-table
        # lookup and provider call; the same EvidenceModel later builds the chart.
        # Besides preventing prose/chart disagreement, this removes two remote
        # dependencies from the most common visualization path.
        # request.query here too — see the fetch_live_data comment above; these
        # deterministic evidence/intent checks must stay scoped to what THIS
        # turn actually asked, not the previous turn folded in for the LLM.
        explicit_visual_request = detect_explicit_visual_request(request.query)
        deterministic_chart_text = live_result.deterministic_answer
        if _is_deterministically_out_of_scope(request.query):
            deterministic_chart_text = _MODEL_DOMAIN_REFUSAL_TEXT
        elif (
            live_evidence.observations
            and (explicit_visual_request or live_evidence.provider)
            # Document evidence is excluded. This branch exists so a LIVE
            # series (FRED, DBnomics, market data) is narrated straight from
            # the retrieved numbers rather than re-described by the model,
            # which could drift from them. An uploaded document is different:
            # its full text is already in the grounded prompt, so the model
            # can answer it properly, and _grounded_domain_fallback's
            # time-series phrasing is wrong for it anyway — "decreased from
            # Inventory to Deferred tax liability" is not a sentence about
            # balance-sheet categories. The extracted figures still drive the
            # chart; only the prose comes from the model.
            and live_evidence.provider != "uploaded_document"
        ):
            deterministic_chart_text = _grounded_domain_fallback(request.query, live_evidence)
        elif live_evidence.composition_subject:
            # Real, named PSC/shareholder data (or a confirmed no-PSC-on-record
            # result) from Companies House is itself proof this is an in-domain,
            # answerable ownership question — never let the model free-narrate
            # invented holders/percentages over it. Not gated on
            # explicit_visual_request: _grounded_domain_fallback's own
            # COMPOSITION branch already fires unconditionally on
            # intent==COMPOSITION "regardless of which chart type the user
            # named" — this just gives it the chance to run before the model,
            # not after.
            deterministic_chart_text = _grounded_domain_fallback(request.query, live_evidence)
        elif _structured_visual_query_is_in_domain(request.query) is True:
            # Every node/edge/stage is already present in the user's query. Build
            # the deterministic description before composition so a temporary
            # model-provider outage cannot block G6/Cytoscape/Mermaid/X6 output.
            deterministic_chart_text = _grounded_domain_fallback(request.query, live_evidence)

        if deterministic_chart_text is None and not request.document_ids and not needs_lookup(request.query):
            supplied = extract_user_visual_evidence(request.query, classify_intent(request.query))
            if not supplied.is_empty() and explicit_visual_request:
                deterministic_chart_text = _grounded_domain_fallback(request.query, supplied)

        if calculation_rejection:
            deterministic_chart_text = None  # Rejection feedback must reach composition.

        # Build grounded prompt input from the sources. Prompt selection is
        # only needed when text will actually leave for the model provider.
        prompt = None
        if deterministic_chart_text is None:
            try:
                # Prompt selection is a database convenience lookup, not a reason
                # to strand the whole HTTP request when a session or connection is
                # unhealthy.  Keep its deadline shorter than the browser timeout.
                prompt = await asyncio.wait_for(select_prompt(db, request.mode), timeout=5.0)
            except (TimeoutError, asyncio.TimeoutError):
                # A cancelled asyncpg statement can leave the transaction unusable
                # until rollback.  Later audit writes need a clean session.
                await db.rollback()
                prompt = None

        if (
            explicit_visual_request and not live_evidence.observations and not run_agent_loop
            and deterministic_chart_text is None
        ):
            # Whether an approved prompt template happens to exist is an
            # unrelated operational detail — it must never decide whether a
            # numbers request with zero real evidence gets this honest message
            # or gets forwarded to the model. Forwarding it instead leaves the
            # model to freelance its own domain judgment on a data-less
            # statistics ask (e.g. "CPI" with no country named), which can
            # produce an off-domain refusal instead of plainly saying no live
            # series was retrieved.
            deterministic_chart_text = (
                "I couldn't retrieve verified data for this chart request, so I "
                "haven't invented values or produced a misleading visualization. "
                "Please try again shortly or specify a source and date range."
            )
        grounded_input = build_web_grounded_prompt(
            effective_query, evidence_sources, agent_mode=run_agent_loop, compact=True,
        )
        context_sections.append(ContextSection(
            0, len(grounded_input),
            lambda factor: build_web_grounded_prompt(
                effective_query, evidence_sources, agent_mode=run_agent_loop, compact=True,
                context_char_budget=int(6000 * factor),
            ),
        ))
        grounded_input += memory_guidance
        if governed_passages:
            refs_by_passage = {citation.source_id: citation.ref_id for citation in rag_citations}
            authority_context = "\n\n".join(
                f"[{refs_by_passage.get(passage_id, 'INTERNAL-GOV')}] {locator} (passage_id={passage_id})\n{content}"
                for passage_id, locator, content in governed_passages
            )
            registered_start = len(grounded_input)
            grounded_input += (
                "\n\n=== Governed registered evidence ===\n"
                "Use these approved passages for material professional claims, citing their exact [REF-N] IDs. "
                "Never cite INTERNAL-GOV text or present it as displayable evidence. "
                "If they conflict or do not support the requested conclusion, say so.\n"
                f"{authority_context}"
            )
            context_sections.append(ContextSection(
                registered_start, len(grounded_input),
                lambda factor: governed_context(
                    effective_query, governed_passages, refs_by_passage,
                    int(sum(len(content) for _, _, content in governed_passages) * factor),
                ),
            ))
        if risk_level == "HIGH":
            grounded_input += _high_risk_instruction(bool(document_sources))
        from app.orchestration.pasted_material import review_instruction
        if authority_required and not self_contained_calculation:
            # The release check (verify_for_release) holds back the whole
            # answer when any sentence lacks a supporting [REF-N]. "Cite
            # material claims" left uncited greetings, framing and closing
            # advice that escalated otherwise correct answers to review.
            grounded_input += (
                "\n\nCitation rule: every sentence and table row you write must end with the "
                "[REF-N] identifier of the evidence that states it. Do not add introductions, "
                "summaries, closing advice or any sentence the evidence does not state. If the "
                "evidence does not answer part of the question, say so in one short sentence "
                "rather than answering it from memory. Answer the question asked: state each "
                "point once, and leave out rules for situations the question does not raise "
                "(for example, rules for agents when the question is about a business itself). "
                "If the message asks several questions, answer each one under its own short "
                "heading. For a question or part the evidence does not answer, write only: "
                "\"The sources provided do not state this.\" Never add figures, rates or "
                "thresholds from memory, even with a caveat. A source's current figure does "
                f"answer a question about now or the current year ({date.today().year}); "
                "say it is the current figure. Calculations on figures the user supplied "
                "need no citation: write each as an equation with its result on the same line "
                "(for example \"Current ratio = 2,50,000 ÷ 1,00,000 = 2.50\")."
            )
            if is_derived_output_request(request.query):
                grounded_input += derived_output_instructions()
        elif professional_application:
            grounded_input += PROFESSIONAL_APPLICATION_INSTRUCTION
        if authority_required and not self_contained_calculation:
            from app.orchestration.input_requirements import uk_vat_rules_requested
            if uk_vat_rules_requested(request.query):
                grounded_input += (
                    "\n\nThe requested UK VAT registration rules need both the rolling-turnover "
                    "and expected-turnover triggers and each applicable registration deadline. "
                    "Find the threshold, period and deadlines in the evidence, not memory. "
                    "For headroom, state explicitly that the supplied turnover is assumed to cover "
                    "the same taxable-turnover period; headroom alone is not a registration exemption. "
                    "Use the current source threshold in the subtraction, show the equation, "
                    "and cite the source supplying that threshold. If any requested rule lacks "
                    "evidence, identify that missing rule explicitly."
                )
            if re.search(r"\b(?:india|indian)\b", request.query, re.I) and re.search(r"\bgst\b", request.query, re.I):
                grounded_input += (
                    "\nExplain who is liable, not merely how to fill in a form. For registration, "
                    "cover goods versus services, turnover thresholds and state-dependent conditions, "
                    "compulsory registration and exemptions. For input tax credit, explain how credit "
                    "reduces output tax, eligibility conditions and blocked credits in plain English. "
                    "Do not present a historic FAQ as current law without applicable amendments. "
                    "For every requested topic missing from the evidence, name that topic explicitly "
                    "and say the sources do not establish it. 'No change' is not a statement of a threshold. "
                    "Avoid portal upload specifications unless the user asks about the application process."
                )
        if effective_context:
            grounded_input += build_task_prompt_context(effective_context)
        if document_sources:
            # "The sources do not state the reporting period or currency" for
            # a balance sheet headed "As of December 31, 2026" in $ amounts.
            grounded_input += (
                "\n\nThe attached document's own text states its title, date line (for example \"As of …\") "
                "and currency (symbols or a column heading such as \"AMOUNT ($)\"); read them before saying the "
                "document does not state them. Cite each extracted figure with its page's [REF-N]."
                # A fixed-asset register summary wrote "$627 000" after saying the
                # sheet shows no currency, stated "straight-line, no residual value"
                # as the register's method, cited "see 'Verified figures'" and
                # ended "suitable for ongoing financial reporting".
                " When the document shows no currency, write amounts without a currency symbol. A method or basis "
                "the document does not state (for example straight-line depreciation) is your assumption: say so "
                "the first time it is used. Do not call the document ready or suitable for reporting, filing or "
                "audit while it states no reporting date or the verified figures list items to check; list those "
                "items instead. Never mention \"verified figures\" or other internal labels; cite the document."
            )
            if is_review_request(request.query):
                # "All quantitative totals … are accurate" was the verdict on a
                # summary that called a register with misfitting depreciation
                # "suitable for ongoing financial reporting", and explained June's
                # spike by "older assets" bought in June: figures were checked,
                # the explanations and the conclusion were waved through.
                grounded_input += (
                    "\n\nThe message pastes a text and asks you to check it. Check it against the attached document, "
                    "not general knowledge: confirm each figure that matches the document, and list each statement "
                    "that is wrong, unsupported by the document or an unstated assumption, with the correct figure "
                    "or wording. Check the explanations and the conclusion too, not only the numbers: an explanation "
                    "the document's rows contradict is wrong, not \"an interpretation\" (for example a month's assets "
                    "called older when the document dates them in that month), and a statement that the document is "
                    "ready or suitable for reporting is wrong while it states no reporting date or items to check "
                    "are listed below. Report every asset or row listed below as not fitting or to be checked, by "
                    "its ID, even when the text does not mention it — that the text missed them is itself a finding. "
                    "End with a one-line verdict that names the most serious problem; do not call the text accurate "
                    "or correct overall while any of these problems remains."
                )
        # Earlier turns supply figures a follow-up refers to ("cost of sales
        # increased by 10%, revenue unchanged"), screened like the live query.
        deterministic_calculation = metrics.run_sync(
            "calculation.extract",
            lambda: build_calculation(request.query, screened_history(request.conversation_history)),
        )
        if deterministic_calculation:
            await persist_calculation_run(
                db,
                tenant_id=tenant_id,
                query_id=query_id,
                result=deterministic_calculation.record,
                chart=deterministic_calculation.chart,
            )
            workflow_state.note_calculation(deterministic_calculation.record.calculation_id)
            grounded_input += deterministic_calculation.prompt_context()

    # Earlier turns (including answers with figures) for follow-ups such as
    # "add Thailand" or "make it a bar chart" — untrusted context, redacted
    # below with the rest of the prompt.
    if calculation_result.status == "success":
        grounded_input += "\n\nVerified application calculation (use these results and address every requested part):\n" + calculation_markdown(calculation_result)
        if uncalculated_part(request.query):
            parts = request_parts(request.query, calculated=True)
            if len(parts) > 1:
                grounded_input += parts_instruction(parts)
                shadow_facts["request_parts"] = parts
    # Provenance: earlier turns are context only for a request that refers
    # back. A standalone question that carries its own figures ("from a loss
    # of £12,000 to a profit of £3,000") was answered with drivers drawn from
    # an earlier break-even example in the same chat. Only the turns of the
    # scenario this message builds on are included, never an older one.
    relevant_history = resolution.history()
    history_block = conversation_prompt(relevant_history, max_chars=6000) if resolution.follows_up else ''
    history_start = len(grounded_input)
    grounded_input += history_block
    if history_block:
        def render_history(factor):
            nonlocal history_block
            history_block = conversation_prompt(relevant_history, max_chars=int(6000 * factor))
            return history_block
        context_sections.append(ContextSection(
            history_start, len(grounded_input),
            render_history,
        ))
    grounded_input += memory_facts_text
    grounded_input += bare_chart_hint(request.query, request.conversation_history)
    # The user's own thumbs-down on this question asks for a re-check
    # (structured reasons only, learned_answers.py). Also changes the
    # answer-cache key, so the rejected answer is never served back.
    from app.orchestration.learned_answers import feedback_guidance
    grounded_input += calculation_rejection or await feedback_guidance(
        db, tenant_id=tenant_id, user_id=actor_id, question=request.query,
    )
    document_figures_block = await _verified_document_figures_context(
        db, request.query, resolved_document_ids, document_sources, document_plan, tenant_id, actor_id,
    )
    grounded_input += document_figures_block
    # Financial statements are drafts until reviewed (statement_rules.py).
    from app.orchestration.statement_rules import INSTRUCTIONS as STATEMENT_RULES, is_statement_request
    statement_request = is_statement_request(request.query)
    if statement_request:
        grounded_input += STATEMENT_RULES
    # The method, not the answer, for calculations whose arithmetic was right
    # and method wrong in the 23 Oct 2026 review (accounting_methods.py).
    from app.orchestration.accounting_methods import accounting_method_guidance
    grounded_input += accounting_method_guidance(request.query)
    # Diluted EPS on convertibles is computed, not left to the model, which
    # misapplied the method even with the note (diluted_eps.py).
    from app.orchestration.diluted_eps import verified_eps_block
    grounded_input += verified_eps_block(request.query)

    if context_sections:
        from app.domains.model_gateway.agent_budget import request_prompt_estimate
        from app.domains.model_gateway.execution import current_budget
        from app.domains.model_gateway.providers.groq_adapter import KRITON_COMPOSITION_SYSTEM_PROMPT, KRITON_AGENT_SYSTEM_PROMPT, CHART_TOOL_SCHEMA
        execution_budget = current_budget()
        request_limit = execution_budget.max_request_tokens if execution_budget else get_settings().AGENT_MAX_REQUEST_TOKENS
        if request_limit > 0:
            context_tools = [CHART_TOOL_SCHEMA]
            context_system = KRITON_COMPOSITION_SYSTEM_PROMPT
            if run_agent_loop:
                names = set(execution_plan.tools) | {'calculate'}
                if chart_requested(request.query):
                    names.add('render_chart')
                context_tools = [tool for tool in model_gateway_service.tool_registry().function_schemas(permissions_for_role(role))
                                 if tool['function']['name'] in names]
                context_system = KRITON_AGENT_SYSTEM_PROMPT
            def estimate_composition(text):
                return request_prompt_estimate([
                    {'role': 'system', 'content': context_system},
                    {'role': 'user', 'content': with_agent_instructions(text) + execution_plan.as_prompt()
                     if run_agent_loop else text},
                ], context_tools)
            # Reserve useful output plus template/redaction protocol headroom.
            grounded_input, before_size, after_size = pack_context(
                grounded_input, context_sections, estimate_composition, request_limit - 1280,
            )
            logging.getLogger('kriton.requests').info(
                'Composition context query=%s estimated_input_before=%s estimated_input_after=%s request_limit=%s',
                query_id, before_size, after_size, request_limit,
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
    await report("generating", "Generating the governed answer")

    composed_text: Optional[str] = deterministic_chart_text
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
    # A pasted set of questions needs the full model: the fast one lost the
    # thread on long multi-question prompts (blank output, then truncation).
    multi_question = len(sub_questions(request.query)) > 1
    if risk_level in ("ZERO", "LOW") and os.getenv("GROQ_API_KEY") and not gemini_active and not multi_question:
        answer_model = os.getenv("GROQ_FAST_ANSWER_MODEL", "openai/gpt-oss-20b")

    # ── Agent mode: governed tool-calling loop ─────────────────────────────
    # The model fetches figures through registered tools (permission-checked,
    # validated, time-boxed) and every call is audited. Any failure falls
    # through to the standard composition below, so agent mode can only add
    # evidence to an answer — never lose one.
    agent_outcome = None
    provider_access_error = None
    if run_agent_loop and deterministic_chart_text is None:
        # The knowledge base was already searched for this question (it feeds
        # risk classification), so the agent's plan does not search it again:
        # each search is ~30 round trips to the database.
        agent_plan = execution_plan.without("search_knowledge_base") if governed_passages else execution_plan
        calculation_tools_only = self_contained_calculation and not (
            set(agent_plan.tools) & {"get_exchange_rate", "get_economic_indicator", "get_market_data"}
        )
        if calculation_tools_only:
            agent_plan = agent_plan.without("search_knowledge_base").without("search_web")
        if professional_application and source_bundle is not None and not governed_passages:
            # The governed library was searched for this question before the
            # agent ran and holds nothing for it: searching it again only spent
            # steps (hedge and TDR runs, 23 Oct 2026, ended at the step limit
            # after empty knowledge-base and web searches).
            agent_plan = agent_plan.without("search_knowledge_base")
        async def on_tool_start(tool: str) -> None:
            await report("tool_call", _TOOL_PROGRESS.get(tool, "Gathering evidence"))

        async def on_tool_done(record) -> None:
            await audit_agent_tool_called(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                step=record.step, tool=record.tool, arguments_hash=record.arguments_hash,
                ok=record.ok, error_code=record.error_code,
                duration_ms=record.duration_ms, source_count=record.source_count,
                policy_decision_id=record.policy_decision_id, policy_reason=record.policy_reason,
                untrusted_instructions=record.untrusted_instructions,
                idempotency_key=record.idempotency_key, calculation_id=record.calculation_id,
                calculation_ids=record.calculation_ids, items_total=record.items_total,
                items_failed=record.items_failed,
                planned=record.planned, resumed=record.resumed,
            )

        from app.orchestration.governed_retrieval import GovernedRetrievalContext, bind_context, reset_context
        retrieval_context = GovernedRetrievalContext(
            db=db, tenant_id=tenant_id, user_id=actor_id, query_id=query_id,
            jurisdiction=request.jurisdiction or conversation_jurisdiction(request.query, request.conversation_history),
            framework=(effective_context.framework or "") if effective_context else "",
            effective_date=effective_context.period_end if effective_context else None,
            engagement_id=effective_context.engagement_id if effective_context else None,
        )
        retrieval_token = bind_context(retrieval_context)
        authorize_tool = _tool_authorizer(db, lock=retrieval_context.lock, actor_id=actor_id,
                                          tenant_id=tenant_id, role=role,
                                          # An attached file carries its own figures: "Review the attached
                                          # P&L for arithmetic errors" has no digits in the question
                                          # (int-doc-inconsistent was escalated when calculate was refused).
                                          figures_supplied=bool(request.document_ids)
                                          or supplies_figures(request.query, request.conversation_history))
        try:
            agent_outcome = await metrics.run(
                "composition.agent",
                model_gateway_service.run_agentic_completion(
                    with_agent_instructions(grounded_input) + agent_plan.as_prompt()
                    + ("\n\nThe governed knowledge-base passages for this question are already included above; "
                       "do not search the knowledge base again for the same point." if governed_passages else ""),
                    granted_permissions=permissions_for_role(role),
                    # Always the full GROQ_MODEL, never the fast one: planning
                    # tool calls is where the small model failed — refusing
                    # in-scope questions after fetching data, skipping a
                    # requested chart, pricing a US stock in rupees — while
                    # the full model answered the same questions correctly.
                    model=None,
                    on_tool_start=on_tool_start,
                    on_tool_done=on_tool_done,
                    chart_requested=chart_requested(request.query),
                    latest_fx_required=latest_fx_requested(request.query),
                    max_seconds=agent_time_budget(time.monotonic() - start_time, deadline_seconds),
                    extra_steps=deliverable_step_allowance(request.query),
                    source_ref_offset=len(rag_citations),
                    authorize=authorize_tool,
                    request_id=query_id,
                    planned_tools=agent_plan.tools,
                    stated_facts="\n".join([request.query, *(m.content for m in request.conversation_history
                                                              if m.role == "user")]),
                    # With the totals computed from the attached files: a trial
                    # balance's own 7,026,500 total was removed as unverified.
                    figure_evidence=figure_evidence_text(request, web_sources, governed_passages, document_sources,
                                                         calculation_result, remembered_calculation)
                    + document_figures_block,
                    resume_key=idempotency_key or "",
                    # The plan searches, and nothing was retrieved beforehand:
                    # the agent must gather evidence before it answers.
                    # Not for a calculation on the question's own figures: forced
                    # to search first, the financial performance analysis spent
                    # the steps it needed for its last calculations.
                    # Nor when the policy lets professional knowledge answer
                    # (a supplied scenario under a named framework): told to
                    # "answer only from what they return", VIE, subsequent-event
                    # and internal-control scenarios came back as "the sources
                    # do not state this" with the knowledge base and web search
                    # empty (22 Oct 2026).
                    require_evidence=bool(set(agent_plan.tools) & {"search_web", "search_knowledge_base"})
                    and not professional_application
                    and not governed_passages and not document_sources and not self_contained_calculation,
                    # Pure calculations cannot need external lookup schemas.
                    # Keep the complete registry and per-call policy enforcement.
                    available_tools=(("calculate", "render_chart") if chart_requested(request.query) else ("calculate",))
                    if calculation_tools_only else None,
                ),
            )
            composed_text = agent_outcome.text
            if agent_outcome.incomplete_reason and calculation_result.status == "success":
                composed_text += "\n\nVerified application results\n\n" + calculation_markdown(calculation_result)
            released_receipts = list(agent_outcome.calculation_receipts)
            shadow_facts["executed_tools"] = [call.tool for call in agent_outcome.tool_calls]
            await _record_calculation_receipts(
                db, receipts=agent_outcome.calculation_receipts, query_id=query_id,
                correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
            )
            prompt_id, prompt_name = "agent", "Agent (governed tool calling)"
            await audit_agent_completed(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                steps=agent_outcome.steps, stop_reason=agent_outcome.stop_reason,
                tool_call_count=len(agent_outcome.tool_calls), fell_back=False,
                tokens_used=agent_outcome.tokens_used, cost_usd=agent_outcome.cost_usd,
                estimated_tokens=agent_outcome.estimated_tokens, model_calls=agent_outcome.model_calls,
                resumed_calls=agent_outcome.resumed_calls, validation=agent_outcome.validation,
            )
        except Exception as exc:
            if isinstance(exc, ProviderRequestRejected):
                provider_access_error = exc
            logger.warning(
                "Agent composition failed query=%s correlation=%s (%s: %s); %s",
                query_id, correlation_id, type(exc).__name__, str(exc)[:300],
                "provider request rejected; no composition retry" if provider_access_error else "using standard composition",
            )
            if getattr(exc, 'origin', None):
                logger.warning('Request-size diagnostic correlation=%s origin=%s input_estimate=%s request_limit=%s',
                               correlation_id, exc.origin, exc.input_estimate, exc.request_limit)
            agent_outcome = None
            await audit_agent_completed(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                steps=0, stop_reason="error", tool_call_count=0,
                fell_back=provider_access_error is None,
                error=provider_access_error.code if provider_access_error else type(exc).__name__,
            )
        finally:
            reset_context(retrieval_token)

    # A repeat of the same grounded question costs nothing when its answer is
    # already known. This matters for the token allowance rather than for
    # speed: the provider's per-minute ceiling is what turns a second question
    # into a composition failure, and a cached answer spends none of it. The
    # audit trail, validation, disclaimer and visualization all still run —
    # only the model call is skipped. See answer_cache.py.
    answer_cache_key: str | None = None
    if agent_outcome is None and deterministic_chart_text is None and answer_cache.is_cacheable(evidence_sources):
        answer_cache_key = answer_cache.cache_key(grounded_input, answer_model)
        cached_answer = await answer_cache.get_answer(answer_cache_key)
        if cached_answer:
            composed_text = cached_answer
            prompt_name = "Web-grounded Prompt (cached)"

    # The standard path's answer was cut off at the output limit and only its
    # finished part is shown (partial_output.py). Never cached; marked incomplete.
    truncated_partial = False
    try:
        if provider_access_error is not None and composed_text is None:
            raise provider_access_error
        if deterministic_chart_text is None and composed_text is None:
            try:
                if prompt:
                    prompt_row, composed_text = await metrics.run(
                        "composition.model",
                        model_gateway_service.run_test_prompt(
                            db, prompt.id, grounded_input, actor_id, tenant_id,
                            correlation_id=query_id, model=answer_model,
                        ),
                    )
                    prompt_id = prompt_row.id
                    prompt_name = prompt_row.name
                else:
                    # No approved prompt template seeded — fall back to a direct
                    # provider completion so web-grounded answering still works.
                    composed_text = await metrics.run(
                        "composition.model",
                        model_gateway_service.run_grounded_completion(grounded_input),
                    )
            except ProviderResponseIncomplete as incomplete:
                # Cut off at the output limit: keep the finished part when it
                # is worth showing; otherwise fail as before.
                from app.orchestration.partial_output import usable_partial
                partial = usable_partial(incomplete.partial_text)
                if not partial:
                    raise
                composed_text, truncated_partial = partial, True
            # The model gateway deliberately sanitizes provider exceptions as
            # user-safe text. At the orchestration boundary that text is still
            # a failed composition, never an "answered — source grounded"
            # result. Structured official-data paths above do not reach here.
            # An account spending-limit block is a distinct, non-transient
            # cause and is checked first so it gets its own message. Both are
            # raised rather than returned, so they cannot be cached or shown as
            # an answer.
            if composed_text and _MODEL_PROVIDER_SPEND_LIMIT in composed_text:
                raise RuntimeError("model_provider_spend_limit")
            if composed_text and _MODEL_PROVIDER_FAILURE in composed_text:
                raise RuntimeError("model_provider_unavailable")

            # Stored only AFTER that check. The gateway returns its failure as
            # ordinary text, so caching before this point would pin a
            # transient outage in place for the whole TTL and serve it as an
            # answer — the same trap websearch.py avoids by never caching an
            # empty result set.
            if answer_cache_key and composed_text and not truncated_partial:
                await answer_cache.put_answer(answer_cache_key, composed_text)

    except Exception as exc:
        await audit_composition_failed(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, error=exc.code if isinstance(exc, ProviderRequestRejected) else str(exc),
        )
        if calculation_result.status == "success":
            # A written explanation failing cannot erase independently
            # verified application work. Keep the full request marked partial.
            failure_note = (exc.user_message if isinstance(exc, ProviderRequestRejected)
                            else "The AI service could not complete the written response.")
            text = calculation_markdown(calculation_result)
            from app.orchestration.calculations.illustrations import verified_example, verified_comparison
            text += verified_example(request.query, calculation_result) or verified_comparison(request.query, calculation_result)
            response = AskKritonResponse(
                query_id=query_id, correlation_id=correlation_id,
                outcome="answered", route="CALCULATION", safety=safety_state,
                confidence_state=effective_confidence, source_bundle=source_bundle,
                answer=ComposedAnswer(
                    text=text, output_text=text, citations=[], completeness="partial",
                    limitations=["Incomplete answer: " + failure_note + " The verified calculations are shown; other requested parts remain incomplete."],
                    prompt_id="deterministic-calculation-v1", prompt_name="Verified calculation recovery",
                ), calculation=calculation_result,
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
            return await finish(response, route="CALCULATION")
        # Service unavailability is not a policy refusal or missing input. A typed
        # provider failure carries its own safe message; anything untyped gets
        # the generic one (or the spend-limit one if its text says so).
        provider_message = (
            _MODEL_PROVIDER_SPEND_LIMIT_MESSAGE
            if "spend_limit" in str(exc)
            else "Kriton™ could not compose a response at this time. Please try again shortly."
        )
        response = AskKritonResponse(
            query_id=query_id, correlation_id=correlation_id,
            outcome="unavailable", route="LLM",
            safety=safety_state, confidence_state=effective_confidence,
            source_bundle=source_bundle, answer=None,
            next_action=NextAction(
                type=exc.next_action_type if isinstance(exc, ProviderRequestRejected) else "composition_failed",
                message=exc.user_message if isinstance(exc, ProviderRequestRejected) else provider_message,
            ),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        return await finish(response, route="LLM")

    from app.orchestration.uk_vat_headroom import source_grounded_headroom
    sourced_headroom = source_grounded_headroom(request.query, evidence_sources, rag_citations)
    if sourced_headroom:
        composed_text = sourced_headroom

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
        return await finish(response, route=ROUTE_CLARIFICATION, store=False)

    if agent_outcome is not None and is_agent_clarification(composed_text, agent_outcome):
        # The agent asked for missing input ("which amount?") instead of
        # answering. Shown as an answer it read "Answered — model knowledge,
        # no sources retrieved"; it is a clarification, so it gets that status.
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
            next_action=NextAction(type="ask_clarifying_question", message=composed_text.strip()),
            audit_reference=AuditReference(audit_chain_id=audit_chain_id),
        )
        return await finish(response, route=ROUTE_CLARIFICATION, store=False)

    # The agent loop grounds its own prose against its tool results. A
    # standard composition (agent mode off, or the agent failed and fell back)
    # gets the same treatment against the series fetched for this question:
    # extrema and trend claims are restated from the numbers, and causes the
    # sources never state are removed.
    if agent_outcome is None and deterministic_chart_text is None:
        series_sources = [source for source in live_result.sources if source.series]
        if series_sources:
            composed_text = ground_series_summary(
                ground_causal_claims(composed_text, series_sources), series_sources,
            )

    if agent_outcome is not None:
        # Tool evidence joins the answer's citations after the retrieved
        # sources, and validated charts are attached as-is (built from checked
        # tool arguments, never retyped by the model).
        rag_citations = rag_citations + [
            SourceCitation(
                ref_id=f"REF-{len(rag_citations) + i + 1}",
                source_id=s.url,
                title=s.title,
                url=s.url or None,
                evidence_preview=(s.snippet[:240].strip() or None) if s.snippet and s.preview_allowed else None,
                provider=s.provider,
                fetched_at=s.fetched_at,
                freshness=s.freshness,
            )
            for i, s in enumerate(agent_outcome.sources)
        ]
        if agent_outcome.artifacts:
            composed_text = composed_text.rstrip() + "\n\n" + "\n\n".join(agent_outcome.artifacts)

    # Force a chart from the connector's own fetched numeric series when the
    # question wanted one and the model didn't already produce it (via prose
    # or the render_chart tool) — see live_data.build_forced_chart. Runs
    # before validation so the forced chart is checked like any other content.
    if agent_outcome is None and "```chart" not in composed_text:
        forced_chart = build_forced_chart(request.query, live_result.sources)
        if forced_chart:
            composed_text = composed_text.rstrip() + "\n\n" + forced_chart

    # Provider models occasionally ignore the shared domain instructions and
    # refuse clearly in-domain CPI/FX or corporate-relationship prompts. Use a
    # deliberately narrow deterministic correction only when governed
    # structured evidence independently proves the request is in scope. The
    # replacement then continues through the same audit, answer validation,
    # disclaimer and visualization gates as every other composed response.
    # request.query, not effective_query — see fetch_live_data's comment
    # above. This decides in-domain scope and narrates structured evidence;
    # both must reflect only what THIS turn supplied, or a prior turn's
    # relationships/entities can bleed into this answer's text.
    structured_scope = _structured_visual_query_is_in_domain(request.query)
    uses_user_supplied_structure = False
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
            uses_user_supplied_structure = True
    elif _MODEL_DOMAIN_REFUSAL in composed_text or _MODEL_PROVIDER_FAILURE in composed_text:
        grounded_fallback = _grounded_domain_fallback(request.query, live_evidence)
        if grounded_fallback:
            composed_text = grounded_fallback

    # A question carrying its own complete chart DATA ("revenue 8.2m against a
    # target of 10m", "distribution: 4, 8, 15, 16") is the numeric twin of the
    # graph/flow case above: nothing is retrieved, the figures are the user's
    # own, and the visualization shows those same figures back. It needs the
    # same treatment for the same reason — deterministic narration, and the
    # grounding bypass below.
    #
    # Without this the model composed prose with no citation behind it, the
    # RG-03 grounding check correctly found none, and the answer escalated to
    # human review — for a question that never needed a source at all. Gated
    # on live evidence being absent so a real retrieved series is never
    # displaced by a number that merely appears in the question text.
    if (
        not uses_user_supplied_structure
        and not live_evidence.observations
        and not live_evidence.composition
    ):
        supplied = extract_user_visual_evidence(request.query, classify_intent(request.query))
        if not supplied.is_empty():
            supplied_answer = _grounded_domain_fallback(request.query, supplied)
            if supplied_answer:
                composed_text = supplied_answer
                uses_user_supplied_structure = True

    # For structured statistical visuals, narrative and chart must come from
    # one normalized evidence object.  Model prose can misread a direction or
    # stop before the latest observation even when the plotted values are
    # correct; deterministic narration eliminates that split-brain result.
    uses_deterministic_summary = False
    from app.orchestration.gst_registration import source_grounded_registration
    registration_answer = source_grounded_registration(request.query, [*evidence_sources, *(agent_outcome.sources if agent_outcome else [])], rag_citations)
    if registration_answer:
        composed_text = registration_answer
        uses_deterministic_summary = True
    from app.orchestration.gst_export import source_grounded_export
    export_answer = source_grounded_export(
        request.query, [*evidence_sources, *(agent_outcome.sources if agent_outcome else [])], rag_citations,
    )
    if export_answer:
        composed_text = export_answer
        uses_deterministic_summary = True
    from app.orchestration.official_evidence import source_grounded_tax_replacement
    replacement_answer = source_grounded_tax_replacement(request.query, [*evidence_sources, *(agent_outcome.sources if agent_outcome else [])], rag_citations)
    if replacement_answer:
        composed_text = replacement_answer
        uses_deterministic_summary = True
    from app.orchestration.official_evidence import source_grounded_current_rate
    current_rate_answer = source_grounded_current_rate(
        request.query, [*evidence_sources, *(agent_outcome.sources if agent_outcome else [])], rag_citations,
    )
    if current_rate_answer:
        composed_text = current_rate_answer
        uses_deterministic_summary = True
    from app.orchestration.uk_vat_headroom import source_grounded_threshold_correction
    threshold_correction = source_grounded_threshold_correction(
        request.query, [*evidence_sources, *(agent_outcome.sources if agent_outcome else [])], rag_citations,
    )
    if threshold_correction:
        composed_text = threshold_correction
    fx_sources = [*evidence_sources, *(agent_outcome.sources if agent_outcome else [])]
    if latest_fx_requested(request.query):
        if not fresh_fx_sources(request.query, fx_sources):
            composed_text = (
                "The retrieved evidence does not establish a sufficiently recent, dated exchange rate "
                "for this currency pair. I have not substituted a historical rate. "
                "The requested currency calculations need a current rate before they can be completed."
            )
            uses_deterministic_summary = True
        else:
            fx_answer = grounded_fx_profit(request.query, fx_sources, rag_citations)
            if fx_answer:
                composed_text = fx_answer
                # Rate/date/provenance come directly from the typed connector
                # observation; arithmetic is checked below, not against web prose.
                uses_deterministic_summary = True
    if live_evidence.observations and detect_explicit_visual_request(request.query):
        grounded_summary = _grounded_domain_fallback(request.query, live_evidence)
        if grounded_summary:
            composed_text = grounded_summary
            uses_deterministic_summary = True

    if not uses_user_supplied_structure:
        from app.orchestration.answer_formatting import latex_to_plain, normalize_markdown_tables
        # Before validation, so the arithmetic check reads the same working
        # the user sees (the answer view does not render LaTeX).
        composed_text = separate_headings(normalize_markdown_tables(latex_to_plain(composed_text)))
        composed_text = normalize_citations(composed_text, {citation.ref_id for citation in rag_citations})

    from app.orchestration.review import external_evidence_snapshot
    review_evidence_snapshot = external_evidence_snapshot([
        *web_sources, *(agent_outcome.sources if agent_outcome else []),
    ], citations=rag_citations)
    verification_evidence = [
        *(f"[{citation.ref_id}] {source.snippet}" for citation, source in zip(rag_citations, evidence_sources)),
        # The figures computed from the attached files (document_figures.py)
        # are what an answer about them states — "Dr Depreciation 137,085"
        # is cost ÷ useful life, not a line in the file. Claim verification
        # read only the raw rows, judged such claims unsupported and pruned
        # them to "the sources do not state…". They are evidence for the
        # file they were computed from, under that file's reference.
        *_document_figures_evidence(document_figures_block, rag_citations, evidence_sources),
        *(f"[{citation.ref_id}] {content}" for citation in rag_citations
          for passage_id, _, content in governed_passages if citation.source_id == passage_id),
        *((f"[REF-{len(rag_citations) - len(agent_outcome.sources) + i + 1}] {source.snippet}" for i, source in enumerate(agent_outcome.sources))
          if agent_outcome else ()),
    ]
    claim_verification_note: str | None = None
    from app.orchestration.answer_formatting import restore_matching_tax_chart
    if (
        deterministic_chart_text is None and not uses_user_supplied_structure
        and not uses_deterministic_summary and _MODEL_DOMAIN_REFUSAL not in (composed_text or "")
        # Authoritative answers receive the complete citation-aware release
        # check below. A second, earlier judge could rewrite/prune correct
        # calculations before that stricter check ever saw them.
        and not authority_required
    ):
        contradicted_removed: list[dict] = []
        before_claim_check = composed_text
        composed_text, claim_verification_note = await _verify_answer_claims(
            composed_text,
            evidence=verification_evidence,
            question=request.query,
            grounded_input=grounded_input,
            report=report,
            metrics=metrics,
            removed=contradicted_removed,
        )
        if contradicted_removed:
            removed_statements.append(removal_stage(
                "contradiction_removal", before_claim_check, composed_text,
                [(item["statement"], item["reason_code"], {"confirmations": item["confirmations"]})
                 for item in contradicted_removed], rag_citations))
    if agent_outcome:
        composed_text = restore_matching_tax_chart(composed_text, agent_outcome.artifacts)

    if composed_text and document_sources:
        from app.orchestration.document_citations import cite_document_pages
        composed_text = cite_document_pages(composed_text, rag_citations)

    if composed_text and _MODEL_DOMAIN_REFUSAL not in composed_text and off_topic(request.query, composed_text):
        # A VAT question asked after an inventory question was answered with
        # the inventory comparison: cited and true, so every later check
        # passed it (answer_relevance.py). Re-answer once without the earlier
        # conversation; if still off-topic, say so rather than show it.
        logger.warning("Off-topic draft for %s: asked %s, answered %s", query_id,
                       sorted(topics_in(request.query)), sorted(topics_in(composed_text, min_mentions=3)))
        await report("correcting", "Re-answering: the draft addressed a different question")
        recomposed = await metrics.run(
            "composition.relevance_recompose",
            model_gateway_service.run_optional_completion(
                grounded_input.replace(history_block, "") + _agent_tool_evidence(agent_outcome, len(rag_citations))
                + recompose_instruction(request.query)),
        )
        from app.orchestration.answer_formatting import normalize_markdown_tables as _tables
        if (recomposed and recomposed.strip() and _MODEL_PROVIDER_FAILURE not in recomposed
                and not off_topic(request.query, recomposed)):
            composed_text = normalize_citations(_tables(recomposed), {citation.ref_id for citation in rag_citations})
        else:
            composed_text = "The sources found do not establish an answer to this question."

    output_hash = hashlib.sha256(composed_text.encode()).hexdigest()[:32]
    await audit_composition_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, prompt_id=prompt_id, output_hash=output_hash,
    )
    await report("validating", "Validating citations and safety controls")

    # ── Step 7: Post-composition validation — Massarius™ Checkpoint C
    # (§10, RG-03; ZL-ENG-03 §5.7) ────────────────────────────────────────────
    # Validate the provider's composed text directly. Generic disclaimer copy
    # is intentionally not appended to user-visible answers.
    # external_source_count carries the live retrieval sources (SearXNG + the
    # exact-figure connectors) the answer was actually composed against — they
    # are the [REF-N] citations the reader gets, but they are not registered in
    # the governed SourceBundle. Without it, every answer grounded purely in
    # live sources fails the grounding check and degrades to HUMAN_REVIEW.
    calculation_failures = metrics.run_sync(
        "calculation.validate", lambda: validate_answer_calculations(composed_text)
    )
    # Arithmetic the model got wrong is corrected before validation rather than
    # sending the whole answer to review: "4,07,600 * 180 = 733680000" (one
    # digit too many) escalated a five-part calculation answer. The model gets
    # the exact failing lines once; if its corrected answer still fails,
    # validation below escalates exactly as before. (The agent path corrects
    # inside its own loop.)
    if calculation_failures and agent_outcome is None and not uses_user_supplied_structure:
        await report("correcting", "Correcting a calculation")
        try:
            corrected = await metrics.run(
                "composition.calculation_correction",
                model_gateway_service.run_optional_completion(
                    grounded_input
                    + "\n\n=== Your previous answer ===\n" + composed_text
                    + "\n\n=== Arithmetic errors found in it ===\n" + "\n".join(calculation_failures)
                    + "\n\nRewrite the complete answer with these calculations corrected and every "
                    "figure that depends on them updated. Keep everything else the same."
                ),
            )
        except Exception:
            corrected = ""
        if corrected and corrected.strip() and _MODEL_PROVIDER_FAILURE not in corrected:
            composed_text = corrected
            calculation_failures = validate_answer_calculations(composed_text)
    # A calculation on the question's own figures ("revenue ₹50,00,000,
    # expenses ₹38,50,000 — net margin?") has nothing to cite, so failing it
    # for lacking sources escalated every such question. It is exempt from
    # the source-count check only when it was actually computed (a verified
    # calculation, or the agent's calculate/render_chart tools succeeded) AND
    # every calculation shown in the prose re-checks — the prohibited-claim
    # and citation checks still apply to it in full.
    computed_from_own_figures = not calculation_failures and (
        deterministic_calculation is not None
        or (self_contained_calculation and not rag_citations)
        or (agent_outcome is not None and any(
            call.tool in ("calculate", "render_chart") and call.ok for call in agent_outcome.tool_calls
        ))
    )
    from app.orchestration.limitation_reply import is_limitation_reply

    def validate(text: str):
        return (
            validate_answer(
                text,
                source_bundle,
                disclaimer_required=False,
                external_source_count=len(rag_citations),
                # An honest "I can't do this, because…" with no figure is not
                # an ungrounded claim (limitation_reply.py).
                ungrounded_answer_allowed=(effective_confidence == CONF_INSUFFICIENT or computed_from_own_figures
                                           or is_limitation_reply(text)),
                # What the answer was composed against: a phrase quoted from it
                # is the source speaking, not Kriton advising.
                evidence_text="\n".join([
                    *(content for _, _, content in governed_passages),
                    *(source.snippet for source in evidence_sources),
                    *((source.snippet for source in agent_outcome.sources) if agent_outcome else ()),
                ]),
                # HIGH risk = the asker's own or a client's specific matter
                # (pm_1.3): only then is "you must file/pay…" personal advice.
                user_specific=risk_level == "HIGH",
            )
            if source_bundle else None
        )

    if not uses_user_supplied_structure:
        # Claim and arithmetic corrections are fresh model output.
        composed_text = normalize_citations(composed_text, {citation.ref_id for citation in rag_citations})
    validation = validate(composed_text)
    # A user-specific question answered with directive wording ("you must
    # register…") is restated once as general guidance — the high-risk policy
    # (pm_1.3) — before anything is refused: "Can I register for VAT below the
    # threshold?" and "Who can sign off a VAT return?" were refused outright.
    # Any other prohibited claim, or directive wording that survives the
    # rewrite, is refused exactly as before.
    if (
        validation and not validation.passed and not force_direct and composed_text
        and all(is_directive_failure(failure) for failure in validation.failures)
    ):
        await report("correcting", "Restating the answer as general guidance")
        rewritten = await metrics.run(
            "composition.general_guidance_rewrite",
            model_gateway_service.run_optional_completion(
                grounded_input + _agent_tool_evidence(agent_outcome, len(rag_citations))
                + _general_guidance_request(composed_text)),
        )
        if rewritten and rewritten.strip() and _MODEL_PROVIDER_FAILURE not in rewritten:
            rewritten = normalize_citations(rewritten, {citation.ref_id for citation in rag_citations})
            revalidated = validate(rewritten)
            # Same guards as the release rewrite: restating the wording must
            # not lose the answer ("General guidance — The sources provided do
            # not state this." replaced a tool-backed currency conversion) or
            # add a chart the agent did not validate.
            verified_charts = {block.strip() for block in (agent_outcome.artifacts if agent_outcome else [])}
            keeps_answer = not (release_claims(composed_text) and not release_claims(rewritten))
            no_new_chart = all(block.strip() in verified_charts
                               for block in re.findall(r"```chart\n.*?```", rewritten, re.S))
            if revalidated and revalidated.passed and keeps_answer and no_new_chart:
                composed_text, validation = rewritten, revalidated
                calculation_failures = validate_answer_calculations(composed_text)
    if calculation_failures:
        if validation is None:
            from app.orchestration.schemas import ValidationResult
            validation = ValidationResult(
                passed=False, failures=calculation_failures, degraded_route=ROUTE_HUMAN_REVIEW
            )
        else:
            validation = validation.model_copy(update={
                "passed": False,
                "failures": [*validation.failures, *calculation_failures],
                "degraded_route": validation.degraded_route or ROUTE_HUMAN_REVIEW,
            })
    # Pasted material plus "comment on the above": the instruction decides
    # whether statutory sources are needed, not the words in the material.
    from app.orchestration.pasted_material import review_instruction
    # A summary of the user's own attached file, whose totals are the verified
    # document figures, is arithmetic over their figures like a self-contained
    # calculation: "Prepare the VAT summary for this period" of a sales file
    # was withheld for want of an HMRC source. A tax rule it states still needs
    # a source and is removed without one (unsourced_rule_statements below).
    document_calculation = bool(document_figures_block)
    requires_authority = authority_required and not (self_contained_calculation or document_calculation)
    release_review_required = False
    general_background_kept = False
    if (not uses_user_supplied_structure and not uses_deterministic_summary
            and deterministic_chart_text is None and _MODEL_DOMAIN_REFUSAL not in composed_text):
        release_evidence = verification_evidence
        # The jurisdiction each cited source's authority belongs to (gov.uk →
        # UK), so a source for one jurisdiction cannot substantiate a claim
        # about another (verification_service._jurisdiction_mismatch).
        from app.orchestration.source_taxonomy import source_jurisdiction
        release_jurisdictions = {citation.ref_id: found for citation in rag_citations
                                 if (found := source_jurisdiction(citation.url))}
        # The deterministic calculator's verified inputs and results: a line
        # restating them needs no research source (item 1, mixed requests).
        release_calculated = calculated_figures(
            calculation_result if calculation_result.status == "success" else None,
            # The user's own figures in earlier turns are stated facts too, and so
            # is sourced data a tool retrieved: "125000 / 1.3335308" uses the
            # ECB rate, which is an operand with provenance, not an assumption.
            question="\n".join([request.query, *(m.content for m in request.conversation_history if m.role == "user"),
                                *release_evidence]) + memory_facts_text + _agent_tool_evidence(agent_outcome, len(rag_citations)),
            receipts=agent_outcome.calculation_receipts if agent_outcome else None)
        if document_figures_block:
            # The totals computed from the attached files are verified results,
            # like calculator receipts: "Output VAT: 62,070" from a sales file
            # was removed as a tax statement with no source.
            release_calculated.results |= calculated_figures(None, question=document_figures_block).inputs
        # A research citation on arithmetic over the user's own figures is
        # not its source; the calculator is (unbind_arithmetic_citations).
        composed_text = unbind_arithmetic_citations(
            composed_text, "\n".join([request.query, grounded_input])
            + "".join(f"\n{r.get('expression')} = {r.get('result')}"
                      for r in (agent_outcome.calculation_receipts if agent_outcome else [])))
        from app.orchestration.verification_service import unbind_calculated_rows
        composed_text = unbind_calculated_rows(composed_text, release_calculated)
        # A liability balance must rest on consideration the user stated as
        # received or due, not on the model's assumption (IFRS 15 premise).
        from app.orchestration.verification_service import unsupported_balances
        user_facts = "\n".join([request.query, *(m.content for m in request.conversation_history if m.role == "user")])
        checked_text, unsupported_balance_figures = unsupported_balances(composed_text, user_facts, release_calculated)
        if unsupported_balance_figures:
            removed_statements.append(removal_stage(
                "premise_validation", composed_text, checked_text,
                [(figure, "unsupported_premise", {}) for figure in unsupported_balance_figures], rag_citations))
            composed_text = checked_text
            service_unsupported_balances = unsupported_balance_figures
        # A verified figure in the wrong period or scenario: the prior year's
        # cost of goods sold in the current-year column, the original fixed
        # costs in the revised scenario (figure_attribution).
        from app.orchestration.claim_verification import FIGURE_MISATTRIBUTED_NOTE
        from app.orchestration.figure_attribution import misattributed_figures
        misattributed = misattributed_figures(
            composed_text, request.query, [m.content for m in request.conversation_history if m.role == "user"],
            agent_outcome.calculation_receipts if agent_outcome else [],
            earlier_answers=[m.content for m in request.conversation_history if m.role == "assistant"],
            calculation=calculation_result)
        if misattributed:
            statements = list(dict.fromkeys(statement for statement, _, _ in misattributed))
            pruned = prune_rejected_claims(composed_text, statements, note=FIGURE_MISATTRIBUTED_NOTE)
            if pruned.strip():
                removed_statements.append(removal_stage(
                    "figure_attribution", composed_text, pruned,
                    [(statement, "figure_misattributed", {}) for statement in statements], rag_citations))
                composed_text = pruned
                service_misattributed = list(dict.fromkeys(why for _, _, why in misattributed))
        if (self_contained_calculation or document_calculation) and not requires_authority:
            # The arithmetic needs no source, but a tax or legal statement added
            # to it does, and this answer has none: removed, the rest kept.
            from app.orchestration.verification_service import unsourced_rule_statements
            added_rules = unsourced_rule_statements(composed_text, release_calculated)
            pruned = prune_rejected_claims(composed_text, added_rules) if added_rules else ""
            if pruned.strip():
                removed_statements.append(removal_stage(
                    "release_prune", composed_text, pruned,
                    [(statement, "missing_citation", {}) for statement in added_rules], rag_citations))
                composed_text, claim_verification_note = pruned, _UNSUPPORTED_REMOVED_NOTE
            elif added_rules:
                requires_authority = True  # nothing but the rule: the release check withholds it
        release_check = await metrics.run(
            "verification.release",
            verify_for_release(
                composed_text, question=request.query, evidence=release_evidence,
                requires_authority=requires_authority,
                chart_artifacts=agent_outcome.artifacts if agent_outcome else [],
                source_jurisdictions=release_jurisdictions, calculated=release_calculated,
            ),
        )
        # Correct citation/context mismatches once before pruning. A real
        # threshold cited to the prospective-registration paragraph must keep
        # that paragraph's timing condition, or cite the retrospective rule.
        from app.orchestration.input_requirements import registration_comparison_gaps, uk_vat_answer_gaps, tax_rate_comparison_gaps
        from app.orchestration.answer_coverage import requested_topic_gaps
        coverage_gaps = requested_topic_gaps(request.query, composed_text) + gst_answer_gaps(request.query, composed_text) + registration_comparison_gaps(request.query, composed_text) + uk_vat_answer_gaps(request.query, composed_text) + tax_rate_comparison_gaps(request.query, composed_text)
        # An answer built with tools (exchange rates, calculations, charts) is
        # never rewritten wholesale by a model without those tools: in the
        # audit ledger 42% of rewritten tool-backed answers came back as "the
        # sources do not state this" (3% when left alone). Its rejected
        # sentences are pruned below instead; a missing topic still rewrites.
        agent_used_tools = bool(agent_outcome and agent_outcome.tool_calls)
        if ((not release_check.passed and release_check.rejected_claims and not agent_used_tools)
                or coverage_gaps):
            corrected = await metrics.run(
                "verification.release_correction",
                model_gateway_service.run_optional_completion(
                    grounded_input + _agent_tool_evidence(agent_outcome, len(rag_citations))
                    + "\n\n=== Final verification rejected these statements ===\n"
                    + "\n".join(release_check.rejected_claims)
                    + "\nMissing requested topics: " + "; ".join(coverage_gaps)
                    + "\n\nPrevious answer:\n" + composed_text
                    + "\n\nRewrite the complete answer to the original question using only the supplied evidence. "
                    "Cite each factual statement with the exact supporting REF identifier. Preserve the "
                    "source's jurisdiction, time period, exceptions and conditions. Do not confuse an "
                    "expected future threshold crossing with turnover that has already exceeded it. "
                    "Do not omit the central answer merely to avoid a failed check.",
                ),
            )
            if corrected and corrected.strip() and _MODEL_PROVIDER_FAILURE not in corrected:
                corrected = normalize_markdown_tables(corrected)
                corrected = normalize_citations(corrected, {citation.ref_id for citation in rag_citations})
                if agent_outcome:
                    corrected = restore_matching_tax_chart(corrected, agent_outcome.artifacts)
                corrected_check = await metrics.run(
                    "verification.release_corrected",
                    verify_for_release(corrected, question=request.query, evidence=release_evidence,
                                       requires_authority=requires_authority,
                                       chart_artifacts=agent_outcome.artifacts if agent_outcome else [],
                                       source_jurisdictions=release_jurisdictions, calculated=release_calculated),
                )
                corrected_validation = validate(corrected)
                # A rewrite that drops every claim ("The sources provided do
                # not state this.") passes trivially; it replaced a correct,
                # tool-backed currency answer whose only rejected sentence was
                # "The chart below visualises the converted amounts."
                drops_the_answer = bool(release_claims(composed_text)) and not release_claims(corrected)
                # Chart fences are not claims, so a rewrite could add a chart
                # from its own reading of the evidence (an old 83.27 USD/INR
                # rate beside a 96.73 answer). Only the agent's validated charts
                # may appear in a rewrite.
                verified_charts = {block.strip() for block in (agent_outcome.artifacts if agent_outcome else [])}
                adds_unverified_chart = any(
                    block.strip() not in verified_charts
                    for block in re.findall(r"```chart\n.*?```", corrected, re.S)
                )
                if (corrected_check.passed and not drops_the_answer and not adds_unverified_chart and not gst_answer_gaps(request.query, corrected)
                        and not requested_topic_gaps(request.query, corrected)
                        and not registration_comparison_gaps(request.query, corrected)
                        and not uk_vat_answer_gaps(request.query, corrected)
                        and not tax_rate_comparison_gaps(request.query, corrected)
                        and not validate_answer_calculations(corrected)
                        and (corrected_validation is None or corrected_validation.passed)):
                    composed_text, release_check, validation = corrected, corrected_check, corrected_validation
            if gst_answer_gaps(request.query, composed_text):
                # A supported partial answer must explicitly identify the
                # missing central rule rather than imply complete coverage.
                composed_text += "\n\nThe retrieved evidence does not establish all requested GST topics: " + "; ".join(gst_answer_gaps(request.query, composed_text)) + "."
        remaining_markets = registration_comparison_gaps(request.query, composed_text)
        if remaining_markets:
            composed_text += "\n\nIncomplete comparison: the retrieved evidence does not establish " + "; ".join(remaining_markets) + "."
        # One uncited or unsupported sentence ("otherwise the standard 20%
        # rate applies") held back whole answers whose every other statement
        # the sources support. Those sentences are removed instead, and the
        # remainder released only if it re-verifies completely and still
        # passes Checkpoint C; anything else goes to review as before.
        # Two rounds: the verifier is not perfectly repeatable, and a re-check
        # of a pruned answer sometimes rejects a different sentence; one round
        # escalated a sound export answer whose first prune had succeeded.
        candidate, check = composed_text, release_check
        pruned_away: list[tuple[str, str, dict]] = []
        for _round in range(2):
            if check.passed or not check.prunable or not (validation is None or validation.passed):
                break
            pruned_away += [(claim, reason, {}) for claim, reason in
                            zip(check.rejected_claims, check.rejected_reasons or ["unspecified"] * len(check.rejected_claims))]
            # Only figure statements removed (worked by hand, no calculator
            # result, no rule asserted): say
            # so under an emptied heading, not "the sources do not confirm this".
            from app.orchestration.claim_verification import FIGURES_REMOVED_NOTE
            from app.orchestration.verification_service import is_figure_statement
            only_arithmetic = all(is_figure_statement(claim) for claim in check.rejected_claims)
            pruned = prune_rejected_claims(candidate, check.rejected_claims,
                                           note=FIGURES_REMOVED_NOTE if only_arithmetic else None)
            if not pruned or pruned == candidate:
                break
            check = await metrics.run(
                "verification.release_pruned",
                verify_for_release(
                    pruned, question=request.query, evidence=release_evidence,
                    requires_authority=requires_authority,
                    chart_artifacts=agent_outcome.artifacts if agent_outcome else [],
                    source_jurisdictions=release_jurisdictions, calculated=release_calculated,
                ),
            )
            candidate = pruned
            if check.passed:
                revalidated = validate(pruned)
                if revalidated is None or revalidated.passed:
                    removed_statements.append(removal_stage(
                        "release_prune", composed_text, renumber_ordered_lists(pruned), pruned_away, rag_citations))
                    composed_text, release_check, validation = renumber_ordered_lists(pruned), check, revalidated
                    claim_verification_note = _UNSUPPORTED_REMOVED_NOTE
                break
        # Pruning can create a new omission even when the original draft
        # covered every topic. Attempt one evidence-bound repair of that
        # newly incomplete remainder; never call it complete just because
        # all surviving claims passed verification.
        post_prune_gaps = (requested_topic_gaps(request.query, composed_text)
                           + gst_answer_gaps(request.query, composed_text)
                           + registration_comparison_gaps(request.query, composed_text)
                           + uk_vat_answer_gaps(request.query, composed_text)
                           + tax_rate_comparison_gaps(request.query, composed_text))
        if release_check.passed and post_prune_gaps and not coverage_gaps:
            repaired = await metrics.run(
                "verification.coverage_repair",
                model_gateway_service.run_optional_completion(
                    grounded_input + _agent_tool_evidence(agent_outcome, len(rag_citations))
                    + "\n\nVerified remainder:\n" + composed_text
                    + "\nMissing requested topics after verification: " + "; ".join(post_prune_gaps)
                    + "\nComplete the original request using only the supplied evidence. Cite each rule with its exact REF identifier. "
                    "Retain jurisdiction, scope, dates, exceptions and conditions. Do not recreate a rejected claim without supporting evidence."
                ),
            )
            if repaired and _MODEL_PROVIDER_FAILURE not in repaired:
                repaired = normalize_citations(normalize_markdown_tables(repaired), {c.ref_id for c in rag_citations})
                repaired_gaps = (requested_topic_gaps(request.query, repaired) + gst_answer_gaps(request.query, repaired)
                                 + registration_comparison_gaps(request.query, repaired) + uk_vat_answer_gaps(request.query, repaired)
                                 + tax_rate_comparison_gaps(request.query, repaired))
                verified_charts = {block.strip() for block in (agent_outcome.artifacts if agent_outcome else [])}
                invalid_chart = any(block.strip() not in verified_charts for block in re.findall(r"```chart\n.*?```", repaired, re.S))
                repaired_validation = validate(repaired)
                if (not repaired_gaps and not invalid_chart and release_claims(repaired)
                        and not validate_answer_calculations(repaired)
                        and (repaired_validation is None or repaired_validation.passed)):
                    repaired_check = await metrics.run("verification.coverage_repaired", verify_for_release(
                        repaired, question=request.query, evidence=release_evidence, requires_authority=requires_authority,
                        chart_artifacts=agent_outcome.artifacts if agent_outcome else [],
                        source_jurisdictions=release_jurisdictions, calculated=release_calculated))
                    if repaired_check.passed:
                        composed_text, release_check, validation = repaired, repaired_check, repaired_validation
                        claim_verification_note = None
        # The earlier, looser check flags "figures could not be confirmed"
        # from claims judged without their citations. Once the release check
        # has verified every statement against its cited evidence, that note
        # is wrong: a correct, fully cited £90,000 threshold answer carried it.
        if release_check.passed and requires_authority and claim_verification_note == _CLAIMS_UNCONFIRMED_NOTE:
            claim_verification_note = None
        # Gate G4 (§07.5): every material figure in the answer must match the
        # question, the retrieved evidence, a tool result or a verified
        # calculation. A figure with no source fails the release check like
        # any other unverified claim (degraded or sent to review below).
        # The agent's own calculator results carry no source, so they were
        # missing here and a verified "4.17%" change was withheld.
        calculator_results = "".join(f"\n{r.get('expression')} = {r.get('result')} (rounded {r.get('rounded')})"
                                     for r in (agent_outcome.calculation_receipts if agent_outcome else []))
        # With the totals computed from the attached files, cited or not: a VAT
        # summary's 62,070 from a sales file was withheld as unsourced.
        figure_evidence = "\n".join([figure_evidence_text(request, web_sources, governed_passages, document_sources,
                                                         calculation_result, remembered_calculation), *release_evidence,
                                     document_figures_block])
        unsupported_figures = unreconciled_figures(
            composed_text,
            figure_evidence + _agent_tool_evidence(agent_outcome, len(rag_citations)) + calculator_results,
            # A follow-up's evidence is too large for pairwise checks; the
            # comparison it asks for ("£98,400 more") is made from these.
            calculator_results,
            # What derived figures may be computed from: the user's figures,
            # never the prompt's instructions and examples.
            stated=user_facts,
        )
        if unsupported_figures and release_check.passed:
            # Selective withholding: remove the statements and rows that state
            # the figures; the whole answer is replaced only if nothing
            # substantive survives or the removal does not clear them.
            from app.domains.model_gateway.agent import _substantive
            from app.orchestration.claim_verification import FIGURES_REMOVED_NOTE
            from app.orchestration.figure_reconciliation import statements_with_figures
            figure_statements = statements_with_figures(composed_text, unsupported_figures)
            pruned = prune_rejected_claims(composed_text, figure_statements, note=FIGURES_REMOVED_NOTE) \
                if figure_statements else ""
            if _substantive(pruned) and not unreconciled_figures(
                    pruned, figure_evidence + _agent_tool_evidence(agent_outcome, len(rag_citations)) + calculator_results,
                    calculator_results, stated=user_facts):
                removed_statements.append(removal_stage(
                    "figure_reconciliation", composed_text, pruned,
                    [(statement, "figure_unreconciled", {}) for statement in figure_statements], rag_citations))
                composed_text = pruned
                service_removed_figures = list(dict.fromkeys(unsupported_figures))
                unsupported_figures = []
        if unsupported_figures and release_check.passed:
            from app.orchestration.verification_service import AnswerVerification
            release_check = AnswerVerification(
                passed=False,
                failures=[*release_check.failures, "unreconciled_figures: " + ", ".join(unsupported_figures[:8])],
                rejected_claims=release_check.rejected_claims,
                rejected_reasons=release_check.rejected_reasons,
            )
        # Not "decision": that name is the routing decision used below.
        if release_check.passed and release_check.general_explanations:
            # Decision C: explanatory background the sources did not cover is
            # kept and labelled, and any citation marker on it removed — the
            # cited source does not support it.
            composed_text = strip_citations_from(composed_text, release_check.general_explanations)
            general_background_kept = True
        release_decision = decide_release_failure(
            composed_text, release_check, risk_level=risk_level,
            validation_passed=validation is None or validation.passed,
        ) if not release_check.passed else None
        if release_decision is not None and not release_decision.escalate:
            # Arithmetic mismatches and prohibited claims fail validation
            # above and still escalate; see decide_release_failure.
            removed_statements.append(removal_stage(
                "release_withheld", composed_text, release_decision.text,
                [(claim, reason, {}) for claim, reason in zip(
                    release_check.rejected_claims,
                    release_check.rejected_reasons or ["unspecified"] * len(release_check.rejected_claims))]
                + [(figure, "figure_unreconciled", {}) for figure in unsupported_figures],
                rag_citations))
            composed_text, claim_verification_note = release_decision.text, release_decision.note
            await audit_release_check_degraded(
                db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
                audit_chain_id=audit_chain_id, actor_id=actor_id,
                failures=release_check.failures, removed=len(release_check.rejected_claims),
            )
        elif not release_check.passed:
            release_review_required = True
            from app.orchestration.schemas import ValidationResult
            validation = ValidationResult(
                passed=False, failures=[*(validation.failures if validation else []), *release_check.failures],
                degraded_route=ROUTE_HUMAN_REVIEW,
            )
        await audit_release_check_completed(
            db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
            audit_chain_id=audit_chain_id, actor_id=actor_id,
            passed=release_check.passed, requires_authority=requires_authority,
        )
    # Concept check, separate from arithmetic: a standard cited for the wrong
    # topic is corrected, a formula from another technique is removed
    # (accounting_concepts.py). Figures can all verify while the treatment
    # around them is wrong.
    from app.orchestration.accounting_concepts import review_concepts
    concept_review = review_concepts(request.query, composed_text or "")
    if concept_review.changed and _MODEL_DOMAIN_REFUSAL not in (composed_text or ""):
        composed_text = concept_review.text
        shadow_facts.update(concept_corrections=concept_review.corrections, concept_removals=concept_review.removed)
    if (execution_plan.write_request and final_text_needs_notice(composed_text)):
        # §10.5: explain the steps, never act; say so first.
        composed_text = WRITE_REQUEST_NOTICE + "\n\n" + composed_text
    if agent_outcome is not None and "```chart" in (composed_text or ""):
        # The chart shows only verified figures, the same ones the text does.
        from app.orchestration.figure_reconciliation import reconcile_charts, verified_values
        chart_receipts = "".join(f"\n{r.get('expression')} = {r.get('result')} (rounded {r.get('rounded')})"
                                 for r in agent_outcome.calculation_receipts)
        composed_text, charts_dropped = reconcile_charts(composed_text, verified_values(
            "\n".join([request.query, *(m.content for m in request.conversation_history if m.role == "user"),
                       *verification_evidence]) + _agent_tool_evidence(agent_outcome, len(rag_citations)),
            chart_receipts))
    final_text = composed_text
    # Exact citation spans for the answer receipt (§06.4): the supporting
    # sentence inside each cited reference's evidence.
    workflow_state.note_citation_spans(exact_spans(final_text or "", evidence_by_ref([
        *verification_evidence,
        *(line for line in _agent_tool_evidence(agent_outcome, len(rag_citations)).split("\n\n") if line.startswith("[REF-")),
    ])))
    await audit_validation_completed(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id,
        passed=validation.passed if validation else False,
    )

    # uses_user_supplied_structure answers are never LLM prose — they're a
    # mechanical transcription of relationships/stages the user typed
    # themselves (extraction.py), verified structurally before composition,
    # with the visualization showing that SAME data back to them. The
    # grounding check below exists to catch an LLM asserting substantive
    # content with no source behind it; it doesn't apply here, and without
    # this bypass a real, correctly-extracted structured request (e.g. one
    # whose keyword-inferred SourceBundle category — "audit" — has no
    # governed sources seeded) is wrongly escalated to human review for
    # lacking citations it was never supposed to need.
    released_with_review_warning = ""
    disproved_figure_notes: list[str] = []
    if validation and not validation.passed and (not force_direct or release_review_required) and not uses_user_supplied_structure:
        await audit_composition_rejected(
            db, query_id=query_id, correlation_id=correlation_id,
            tenant_id=tenant_id, audit_chain_id=audit_chain_id,
            actor_id=actor_id, failures=validation.failures,
            degraded_route=validation.degraded_route,
        )
        if validation.degraded_route == ROUTE_HUMAN_REVIEW:
            # Shown with a warning is for what could not be verified; a figure
            # the calculator disproved is removed first. If nothing of
            # substance is left, the answer goes to review as before.
            from app.orchestration.review_release import remove_disproved_figures
            composed_text, disproved_figure_notes = remove_disproved_figures(composed_text, validation.failures)
            final_text = composed_text
        # Product decision (2026-10-21): the reader always gets the answer.
        # An answer that fails a check is shown with a plain warning naming
        # what could not be verified, and still goes to Review Tasks for a
        # reviewer; "Response validation failed; escalated for review" with
        # no answer is no longer returned (review_release.py).
        if validation.degraded_route == ROUTE_HUMAN_REVIEW and (composed_text or "").strip():
            from app.orchestration.review_release import release_warning
            review_case = await create_review_case(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, risk_level=risk_level,
                confidence_state=effective_confidence,
                reason="Composition rejected (answer shown with a warning): " + "; ".join(dict.fromkeys(
                    validation.failures[:2] + [f for f in validation.failures if f.startswith("Rejected: ")][:1]
                )),
                query_text=request.query,
                draft_answer=composed_text,
            )
            await audit_human_review_created(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, audit_chain_id=audit_chain_id,
                actor_id=actor_id, review_case_id=review_case.id,
            )
            released_with_review_warning = release_warning(validation.failures,
                                                           disproved_removed=bool(disproved_figure_notes))
        # Invalid answer is NEVER returned; degrade route
        elif validation.degraded_route == ROUTE_HUMAN_REVIEW:
            review_case = await create_review_case(
                db, query_id=query_id, correlation_id=correlation_id,
                tenant_id=tenant_id, risk_level=risk_level,
                confidence_state=effective_confidence,
                reason="Composition rejected: " + "; ".join(dict.fromkeys(
                    validation.failures[:2] + [f for f in validation.failures if f.startswith("Rejected: ")][:1]
                )),
                query_text=request.query,
                draft_answer=composed_text,
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
                next_action=NextAction(type="refusal", message=(
                    "I can explain general requirements and help you prepare a review checklist, "
                    "but I cannot certify compliance or provide a professional sign-off. "
                    "Please have a qualified professional review your situation."
                    if any("Prohibited-claim" in failure for failure in validation.failures)
                    else "I couldn't provide a response that meets the source and safety requirements. "
                         "Please narrow your question or provide an approved source."
                )),
                audit_reference=AuditReference(audit_chain_id=audit_chain_id),
            )
        if not released_with_review_warning:
            return await finish(response)

    # ── Step 8: Finalise response ─────────────────────────────────────────────
    # final_text already has the mandatory disclaimer (§10) applied above, and
    # has passed Checkpoint C validation against that same text.

    # Build limitations list
    limitations: list[str] = list(decision.limitations or [])
    if released_with_review_warning:
        limitations.insert(0, released_with_review_warning)
    if truncated_partial:
        limitations.append("Incomplete answer: the AI response reached its output limit before it finished. "
                           "Only its finished part is shown; any unfinished calculation or conclusion was left out.")
    if concept_review.corrections:
        # The replacement is the standard for that topic within the framework
        # the answer used; it is not a ruling on which framework or period
        # applies to the entity.
        limitations.append("Corrected: a standard was cited for the wrong topic — "
                           + "; ".join(concept_review.corrections)
                           + ". The replacement is the standard for that topic in the same framework; confirm it "
                             "applies to the entity's reporting framework and period.")
    for note in concept_review.removed:
        limitations.append("Incomplete answer: " + note)
    if agent_outcome is not None and agent_outcome.disproved_notes:
        disproved_figure_notes = list(dict.fromkeys(agent_outcome.disproved_notes + disproved_figure_notes))
    if disproved_figure_notes:
        limitations.append("Incomplete answer: statements with a figure that did not match its own calculation "
                           "were removed: " + "; ".join(disproved_figure_notes) + ".")
    from app.orchestration.answer_coverage import requested_topic_gaps
    from app.orchestration.input_requirements import gst_answer_gaps
    remaining_topics = requested_topic_gaps(request.query, final_text) + gst_answer_gaps(request.query, final_text)
    if remaining_topics:
        limitations.append("Incomplete answer: requested topics could not all be verified: " + "; ".join(remaining_topics) + ".")
    from app.orchestration.input_requirements import uk_vat_answer_gaps
    if uk_vat_answer_gaps(request.query, final_text):
        limitations.append("Incomplete answer: registration rules or the headroom assumption could not all be verified from the retrieved evidence.")
    from app.orchestration.input_requirements import tax_rate_comparison_gaps
    rate_gaps = tax_rate_comparison_gaps(request.query, final_text)
    if rate_gaps:
        limitations.append('Incomplete answer: the requested standard tax rates could not all be verified: ' + '; '.join(rate_gaps) + '.')
    # When the LLM authoritatively re-classified risk, drop the weak ML
    # model's "uncertain / needs clarification" artifact — it's noise next to
    # a confidently-answered response.
    if llm_risk:
        limitations = [
            l for l in limitations
            if "CLASSIFICATION_UNCERTAIN" not in l and "clarification" not in l.lower()
        ]
    if no_engagement_general_guidance and risk_level != "HIGH":
        limitations.append(
            "General guidance only: no engagement is set up for you, so this is not advice on "
            "your or your client's specific matter. Set up an engagement for a governed, "
            "client-specific answer."
        )
    # Do not duplicate generic disclaimer copy in the limitations panel.

    # Off-domain refusal: when the domain gate declined the question (it is not
    # about accounting/tax/payroll/finance/audit/bookkeeping/commerce), the
    # web-search results are irrelevant to the reply — so return NO sources and
    # NO disclaimer. Sources are shown only for genuine in-domain answers.
    # Not when the agent fetched real figures for it: that question is
    # in-domain, and its short "I can't…" is about one part of it (India vs
    # Mars), not a reason to discard the whole answer as off-topic.
    agent_found_evidence = agent_outcome is not None and bool(agent_outcome.sources)
    if (
        composed_text and len(composed_text.strip()) < 160 and not agent_found_evidence
        and _GENERIC_REFUSAL.search(composed_text)
    ):
        composed_text = final_text = _MODEL_DOMAIN_REFUSAL_TEXT
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
    elif uses_user_supplied_structure:
        # The flow/graph is grounded solely in the user's supplied stages or
        # relationships. Unrelated web-search hits must not make this appear
        # externally source-grounded.
        rag_citations = []

    from app.orchestration.verification_service import is_evidence_gap_statement
    evidence_gap_only = not release_claims(final_text) and is_evidence_gap_statement(final_text)
    # A concept question the sources did not cover gets a labelled general
    # explanation instead of "Not answered" (concept_fallback.py).
    from app.orchestration.concept_fallback import GENERAL_NOTE, general_explanation, is_concept_question
    if evidence_gap_only and not is_offdomain_refusal and is_concept_question(
            request.query, has_documents=bool(document_sources), uses_live_data=bool(live_evidence.observations)):
        explanation = await general_explanation(
            request.query, model_gateway_service.run_grounded_completion, _MODEL_PROVIDER_FAILURE)
        if explanation:
            final_text = composed_text = explanation
            evidence_gap_only = False
            rag_citations = []
            limitations.insert(0, GENERAL_NOTE)
    # An explanation gap ("the sources do not state the factors that…") is
    # filled with a labelled general explanation; a missing figure, rate or
    # rule is left for "Partially answered" (gap_filler.py).
    if not evidence_gap_only and not is_offdomain_refusal and not uses_user_supplied_structure:
        from app.orchestration.gap_filler import NOTE as GAP_NOTE, fill_explanation_gaps
        final_text, gaps_filled = await fill_explanation_gaps(
            final_text, request.query, model_gateway_service.run_grounded_completion, _MODEL_PROVIDER_FAILURE)
        if gaps_filled:
            composed_text = final_text
            limitations.append(GAP_NOTE)
    if (re.search(r"(?:sources?|evidence)[^.\n]*(?:do not|does not|not establish|not state)", final_text, re.I)
            # "No ONS data … could be retrieved from the available sources":
            # one part answered, another not, shown as fully answered.
            or _PART_NOT_FOUND.search(final_text)) and not evidence_gap_only:
        limitations.append("Incomplete answer: some requested information could not be verified from the retrieved evidence.")
    if agent_outcome is not None and agent_outcome.unreconciled_figures:
        # The written answer was withheld and only the verified working is
        # shown; "Answered" beside "…so it was withheld" contradicted itself.
        # Name the figures, exactly as the answer wrote them (the reconciliation
        # result), so the reader knows what is unverified, not just that
        # something was.
        figures = list(dict.fromkeys(agent_outcome.unreconciled_figures))
        shown = ", ".join(figures[:5]) + (f" and {len(figures) - 5} more" if len(figures) > 5 else "")
        which = "this figure" if len(figures) == 1 else "these figures"
        if agent_outcome.removed_statements:
            # Selective withholding: only the statements and rows stating the
            # figures were removed; the audit records each one.
            removed_statements.append(removal_stage(
                "figure_reconciliation", "", final_text,
                [(statement, "figure_unreconciled", {}) for statement in agent_outcome.removed_statements],
                rag_citations))
            count = len(agent_outcome.removed_statements)
            limitations.append(f"Incomplete answer: {count} statement{'s' if count != 1 else ''} stating {which} "
                               f"could not be verified against the question, the conversation or the tool "
                               f"results and {'were' if count != 1 else 'was'} removed: {shown}. The rest of "
                               f"the answer is shown.")
        else:
            removed_statements.append(removal_stage(
                "figure_reconciliation", "", final_text, [(figure, "figure_unreconciled", {}) for figure in figures],
                rag_citations))
            limitations.append(f"Incomplete answer: the written explanation was withheld because "
                               f"{which} in it could not be verified "
                               f"against the question, the conversation or the tool results: {shown}. Only the "
                               f"calculator's verified working is shown.")
    if service_misattributed:
        reasons = "; ".join(service_misattributed[:3]) + (f"; and {len(service_misattributed) - 3} more"
                                                          if len(service_misattributed) > 3 else "")
        limitations.append(f"Incomplete answer: statements placing a figure in the wrong period or scenario were "
                           f"removed ({reasons}). The rest of the answer is shown.")
    if charts_dropped:
        limitations.append("Incomplete answer: the chart leaves out " + ", ".join(charts_dropped[:5])
                           + ("" if len(charts_dropped) <= 5 else f" and {len(charts_dropped) - 5} more")
                           + " because the figure could not be verified; the text does not state it either.")
    if service_unsupported_balances:
        figures = service_unsupported_balances
        shown = ", ".join(figures[:5]) + (f" and {len(figures) - 5} more" if len(figures) > 5 else "")
        limitations.append(f"Incomplete answer: a contract-liability balance ({shown}) is not shown because the "
                           "question does not establish the consideration received or due that it depends on. "
                           "Any further contract liability, and the recognition of fees not stated as received or "
                           "due, remain unresolved until those facts are known.")
    if service_removed_figures:
        figures = service_removed_figures
        shown = ", ".join(figures[:5]) + (f" and {len(figures) - 5} more" if len(figures) > 5 else "")
        limitations.append(f"Incomplete answer: statements stating {'this figure' if len(figures) == 1 else 'these figures'} "
                           f"could not be verified against the question, the evidence or the tool results and were "
                           f"removed: {shown}. The rest of the answer is shown.")
    if evidence_gap_only:
        rag_citations = []
        limitations = ["The retrieved evidence does not establish the requested answer. No factual answer was verified."]
    if general_background_kept and not evidence_gap_only:
        limitations.append(GENERAL_BACKGROUND_NOTE)
    if agent_outcome is not None and agent_outcome.incomplete_reason:
        # The run could not finish and its verified work is shown instead.
        limitations.append(f"Incomplete answer: {agent_outcome.incomplete_reason}, so only the verified "
                           "calculations and retrieved data are shown; explanations were not completed.")
    jurisdiction_note = jurisdiction_limitation(request.query, removed_statements)
    if jurisdiction_note:
        limitations.append(jurisdiction_note)
    if statement_request and not evidence_gap_only and not is_offdomain_refusal and (final_text or "").strip():
        # A statement answer is an unreviewed draft: no compliance, audit,
        # approval or filing claim, and its open items are named.
        from app.orchestration.statement_rules import open_items, remove_unsupported_claims, removed_claims_note
        final_text, removed_claims = remove_unsupported_claims(final_text)
        statement_notes = open_items(request.query, final_text, "\n".join(
            [document_figures_block, *(getattr(s, "snippet", "") or "" for s in document_sources)]))
        if removed_claims:
            statement_notes.append(removed_claims_note(removed_claims))
        limitations[:0] = [note for note in statement_notes if note not in limitations]
    if (not evidence_gap_only and not is_offdomain_refusal and not uses_user_supplied_structure
            and rag_citations and not re.search(r"\[REF-\d+\]", final_text or "")):
        # Sources found but none cited: their markers are added where a source
        # supports the text, so the reader sees them (citation_pass.py).
        from app.orchestration.citation_pass import cite_sources
        # Each REF's own text: retrieved sources, governed passages, then the
        # agent's tool sources, numbered as rag_citations was built.
        passage_text = {passage_id: content for passage_id, _, content in governed_passages}
        agent_sources = agent_outcome.sources if agent_outcome else []
        agent_start = len(rag_citations) - len(agent_sources)
        text_by_ref = {f"REF-{i + 1}": s.snippet or "" for i, s in enumerate(evidence_sources)}
        text_by_ref.update({f"REF-{agent_start + i + 1}": s.snippet or "" for i, s in enumerate(agent_sources)})
        snippets = {citation.ref_id: text_by_ref.get(citation.ref_id) or passage_text.get(citation.source_id, "")
                    for citation in rag_citations
                    if citation.freshness not in _LIVE_DATA_FRESHNESS and citation.provider != "uploaded_document"}
        snippets = {ref: text for ref, text in snippets.items() if text}
        final_text = await cite_sources(final_text, snippets, model_gateway_service.run_grounded_completion,
                                        _MODEL_PROVIDER_FAILURE)
    citations_composed_against = rag_citations
    rag_citations = cited_only(final_text, rag_citations)
    # An answer from an attached file always lists the file (source_guarantee.py).
    from app.orchestration.source_guarantee import keep_document_citations, official_sources_note
    if not evidence_gap_only and not is_offdomain_refusal and not uses_user_supplied_structure:
        rag_citations = keep_document_citations(rag_citations, citations_composed_against)
    from app.orchestration.agent_plan import GENERAL_GUIDANCE_REASON
    professional_answer = GENERAL_GUIDANCE_REASON in execution_plan.reasons or professional_application
    if professional_answer and not rag_citations and not evidence_gap_only and GENERAL_EXPLANATION_NOTE not in limitations:
        # Decision C: practical guidance answered without sources says so.
        limitations.append(GENERAL_EXPLANATION_NOTE)
    elif (professional_answer and rag_citations and not evidence_gap_only and MIXED_SOURCES_NOTE not in limitations
          and uncited_explanations(final_text)):
        # Cited and uncited parts together: the uncited ones are marked as
        # professional knowledge; cited ones are not called unverified.
        limitations.append(MIXED_SOURCES_NOTE)

    # A calculation on the question's own figures, or a chart redrawn from
    # figures already in the conversation, needs no source — calling it
    # "model knowledge" misdescribes it.
    computed_from_question = not evidence_gap_only and not rag_citations and not is_offdomain_refusal and (
        deterministic_calculation is not None
        or self_contained_calculation
        or (agent_outcome is not None and any(
            call.tool in ("calculate", "render_chart") and call.ok for call in agent_outcome.tool_calls
        ))
    )
    # Keep specific missing-work/evidence notices. Source provenance is
    # already shown in the status and citations, without generic footers.
    if not is_offdomain_refusal and not evidence_gap_only:
        from app.orchestration.websearch import MAX_SUB_QUESTIONS, question_count
        if (asked := question_count(request.query)) > MAX_SUB_QUESTIONS:
            # Twenty questions in one message were searched only for the
            # first eight, and the rest silently came back "not stated".
            limitations.append(
                f"This message asks {asked} questions; sources were searched for the first "
                f"{MAX_SUB_QUESTIONS} only. Ask the rest separately for sourced answers."
            )
        if claim_verification_note:
            limitations.append(claim_verification_note)
        # An answer with no sources at all gets no extra note: the status line
        # already reads "Answered — no cited sources" (removed at the user's
        # request — the note repeated it under every explanation).
    if (not rag_citations and not computed_from_question and not is_offdomain_refusal
            and not uses_user_supplied_structure and (final_text or "").strip()):
        # Which official publishers to check when nothing was cited — named,
        # never presented as citations (source_guarantee.py).
        limitations.append(official_sources_note(request.query))
    # Rewrites after the first normalisation can reintroduce LaTeX, which the
    # answer view shows raw ("\\(40{,}000 \\times 0.06 = 2{,}400\\)").
    from app.orchestration.answer_formatting import latex_to_plain
    from app.orchestration.answer_formatting import calculated_percentages, remove_visual_placeholders
    final_text = calculated_percentages(remove_visual_placeholders(latex_to_plain(final_text)))
    # A requested chart type that was not drawn is named, with the reason
    # (chart_substitution.py).
    from app.orchestration.chart_substitution import substitution_note
    chart_note = substitution_note(request.query, final_text, *(agent_outcome.artifacts if agent_outcome else []))
    if chart_note:
        limitations.append(chart_note)
    if illustrative_diagram:
        from app.orchestration.illustrative_diagram import illustration_wording
        final_text = illustration_wording(final_text)
        limitations.insert(0, ILLUSTRATION_NOTE)
    if document_diagram is not None:
        from app.orchestration.illustrative_diagram import DOCUMENT_NOTE, NOT_IN_DOCUMENT_NOTE
        limitations.insert(0, DOCUMENT_NOTE if document_diagram else NOT_IN_DOCUMENT_NOTE)
    if document_sources:
        from app.orchestration.document_figures import strip_internal_labels
        final_text = strip_internal_labels(final_text)
    answer = ComposedAnswer(
        text=final_text,
        citations=rag_citations,
        limitations=limitations,
        calculation_widget=deterministic_calculation.widget if deterministic_calculation else None,
        calculation_result=deterministic_calculation.record if deterministic_calculation else None,
        verified_charts=[deterministic_calculation.chart] if deterministic_calculation else [],
        computed_from_question=computed_from_question,
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
    # A check of a pasted text is not a request for a chart: "comment on the
    # above" got a "Distribution of 28 values" histogram of the register's costs.
    if not is_offdomain_refusal and not is_review_request(request.query):
        try:
            # request.query, NOT effective_query, throughout this block:
            # extract_graph() only promises to draw entities/relationships the
            # user "explicitly supplied in their OWN query text" (see its own
            # docstring) — effective_query also contains the PREVIOUS turn's
            # text (see _with_previous_context above), so using it here let a
            # prior turn's entities/relationships silently merge into (or
            # replace) this turn's graph, and could drop a current-turn
            # relationship whose verb wasn't recognized while keeping a
            # stale, recognized one from the previous turn instead.
            intent = classify_intent(request.query)

            # Entities/relationships the user explicitly supplied in their OWN
            # query text (extraction.py) — the only source EVIDENCE_GRAPH /
            # PROCESS_FLOW are backed by; merged into the same EvidenceModel
            # DBnomics/Frankfurter already populated, so a query can carry
            # both a numeric figure AND a supplied relationship structure.
            viz_evidence = live_evidence.model_copy(deep=True)
            supplied_evidence = extract_user_visual_evidence(request.query, intent)
            if supplied_evidence.observations and not viz_evidence.observations:
                viz_evidence.observations = supplied_evidence.observations
                viz_evidence.subject = supplied_evidence.subject
                viz_evidence.dimensions = supplied_evidence.dimensions
                viz_evidence.measures = supplied_evidence.measures
                viz_evidence.units = supplied_evidence.units
                # The target must travel with the figure it qualifies. Copying
                # the observation alone left target None, so classify_data_shape
                # read a lone SCALAR and the gauge capability — which exists
                # only for SCALAR_TARGET — was never a candidate. The chart
                # silently disappeared while the answer text still described a
                # comparison against a target.
                viz_evidence.target = supplied_evidence.target
                viz_evidence.target_label = supplied_evidence.target_label
                viz_evidence.user_supplied = supplied_evidence.user_supplied
            if supplied_evidence.composition and not viz_evidence.composition:
                viz_evidence.composition = supplied_evidence.composition
                viz_evidence.composition_subject = supplied_evidence.composition_subject
                viz_evidence.composition_caveat = supplied_evidence.composition_caveat
                viz_evidence.composition_is_estimated = supplied_evidence.composition_is_estimated
                viz_evidence.user_supplied = supplied_evidence.user_supplied
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
            logger.exception("Visualization pipeline failed for query_id=%s", query_id)
            visualization = None
            secondary_visualizations = []

        # Semantic-classifier shadow mode (migration Phase 4) — fire-and-
        # forget, never awaited, so this can never add latency or fail a
        # real request. Off by default: this makes one real Groq call per
        # request, which shouldn't be spent silently. Enable only while
        # actively comparing classify_query() against the existing
        # pipeline; it does not affect routing either way.
        if _query_classifier_shadow_mode_enabled():
            log_shadow_comparison(
                request.query, query_id=query_id, old_intent=intent,
                old_wants_visualization=visualization is not None,
            )

    if visualization is None and not evidence_gap_only and not is_offdomain_refusal:
        from app.orchestration.conceptual_diagrams import credit_sale_diagram
        visualization = credit_sale_diagram(request.query, final_text, spec_id=f"{query_id}-credit-sale",
                                             sources=[c.url for c in rag_citations if c.url])

    from app.orchestration.answer_formatting import has_retained_agent_chart, missing_visual_message
    retained_agent_chart = agent_outcome is not None and has_retained_agent_chart(final_text, agent_outcome.artifacts)
    if detect_explicit_visual_request(request.query) and visualization is None and not secondary_visualizations and not retained_agent_chart:
        visual_note = missing_visual_message(request.query)
        # Limitations are rendered beside the answer; don't also append the
        # identical warning to the text (which displayed it twice).
        answer.limitations.append(visual_note)

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

    # Retrieval is intentionally fail-soft so live/web-grounded answers can
    # still complete during a governed-source outage. In that degraded path
    # there is no governed bundle to dereference or record. The old unconditional
    # access raised AttributeError here and discarded an otherwise completed
    # response.
    await _record_answer_source_usages(
        db, source_bundle=source_bundle, tenant_id=tenant_id, query_id=query_id,
    )

    response = await finish(response)
    await report("complete", "Response ready")
    return response



# ── Helpers ────────────────────────────────────────────────────────────────────

def _terminal_response_state(is_offdomain_refusal: bool) -> tuple[str, str]:
    """Return the single terminal state used by artifacts and the response."""
    if is_offdomain_refusal:
        return "refused", ROUTE_REFUSAL
    return "answered", ROUTE_LLM


async def _record_answer_source_usages(
    db, *, source_bundle, tenant_id: str, query_id: str,
) -> None:
    if source_bundle is None:
        return
    await record_source_usages(
        db,
        sources=source_bundle.sources,
        tenant_id=tenant_id,
        artifact_type="answer",
        artifact_id=query_id,
        operation="model_transmission",
    )


def _high_risk_instruction(has_attached_file: bool) -> str:
    """What a HIGH-risk (the asker's own or a client's matter) answer is told.

    pm_1.3: such a question is answered as general guidance, never as the
    decision itself. Except about the user's attached file (product rule,
    2026-10-21): "Prepare the journal entry for this year's depreciation"
    with a fixed-asset register attached was told "general guidance only, do
    NOT make the decision", so the model ignored the verified 137,085, wrote
    about IAS 16 (which the file does not state) and that was pruned away.
    The "General guidance only" limitation is still shown to the reader.
    """
    if has_attached_file:
        return (
            "\n\nThis question is about the user's own attached records. Prepare exactly what is "
            "asked (the entry, statement, schedule or figures) from the attached file and the "
            "verified figures computed from it, citing the file's [REF-N]. State any assumption "
            "the file does not settle (for example: straight-line, no residual value, a full "
            "year) in one short line. Do not certify, sign off or give tax or legal advice."
        )
    return (
        "\n\nThis question concerns the asker's own or a client's specific matter. "
        "Give general guidance only: explain the applicable rules and standards, the "
        "factors that decide the outcome, worked illustrations where useful, and the "
        "information a qualified professional would need to conclude. Do NOT make the "
        "decision or give a definitive personal recommendation for their case."
    )


def _document_figures_evidence(figures_block: str, citations, sources) -> list[str]:
    """The verified-figures block as evidence, once per attached file, under
    the reference of that file's first cited excerpt."""
    block = (figures_block or "").strip()
    if not block:
        return []
    seen: set[str] = set()
    evidence = []
    for citation, source in zip(citations, sources):
        file_key = source.source_id or source.title
        if getattr(source, "provider", None) == "uploaded_document" and file_key not in seen:
            seen.add(file_key)
            evidence.append(f"[{citation.ref_id}] {block}")
    return evidence


def _evidence_scope(source_scope: str, sent_documents: bool, restored_documents_read: bool) -> str:
    """Which retrieved sources an answer is composed and checked against.

    A follow-up does not re-send the chat's file (the frontend sends only what
    is in the composer, as WEB_ONLY), but the file is restored from the
    conversation and read, and its verified figures reach the prompt. Checked
    as web-only, an answer built from that file had no source: "Dr
    Depreciation 137,085" from a fixed-asset register was escalated for
    "no eligible sources". When the chat's file was restored and read, it is
    evidence alongside the web.
    """
    if source_scope == "WEB_ONLY" and restored_documents_read and not sent_documents:
        return "COMBINED"
    return source_scope


async def _verified_document_figures_context(
    db, query: str, document_ids, document_sources, document_plan, tenant_id: str, user_id: str,
) -> str:
    """Totals, shares, rankings and margins computed from the attached
    documents' tables (document_figures.py), so the model states them instead
    of computing them in its head and gate G4 can confirm them. Always over
    the COMPLETE documents: a targeted retrieval holds only the relevant
    chunks, and a "total" over part of a sheet would be wrong. Fails soft."""
    if not document_ids:
        return ""
    from app.orchestration.document_figures import verified_document_figures

    try:
        sources = document_sources
        if document_plan.retrieval_mode != "full_document":
            # A savepoint, so a failed read cannot leave the request's session unusable.
            async with db.begin_nested():
                sources = await retrieve_document_sources(
                    db, query=query, document_ids=document_ids, tenant_id=tenant_id, user_id=user_id, full_document=True,
                )
        return verified_document_figures(sources, query)
    except Exception:  # noqa: BLE001 - extra figures must never fail the answer
        logger.exception("Could not compute verified document figures")
        return ""

NOT_VERIFIED_MARKER = "No factual answer was verified"
INCOMPLETE_MARKER = "Incomplete answer"
REVIEW_WARNING_MARKER = "Not fully verified:"


def answer_completeness(limitations: list[str]) -> str:
    """How much of the request the released answer covers, from the
    limitations the pipeline attached: every partial path adds an
    "Incomplete answer: …" limitation and an evidence gap adds "No factual
    answer was verified". The page showed "Partially answered" from these
    while the audit said only "answered"."""
    if any(NOT_VERIFIED_MARKER in item for item in limitations or []):
        return "none"
    # Statements removed by verification, or figures left unconfirmed, are
    # content the reader does not get as verified: the IFRS 15 answer that lost
    # a section to "Statements the cited sources do not support were removed"
    # was still called complete.
    # An answer released beside "Not fully verified" (review_release.py) failed
    # a check: it was marked complete next to that warning.
    withheld = (INCOMPLETE_MARKER, _UNSUPPORTED_REMOVED_NOTE, _CLAIM_REMOVED_NOTE, _CLAIMS_UNCONFIRMED_NOTE,
                REVIEW_WARNING_MARKER)
    if any(marker in item for item in limitations or [] for marker in withheld):
        return "partial"
    return "complete"


async def _finalise_and_return(
    db, *, query_id, correlation_id, tenant_id, audit_chain_id, actor_id,
    outcome, route, start_time: float, completeness: str | None = None,
) -> None:
    latency_ms = (time.monotonic() - start_time) * 1000
    metrics = current_stage_metrics()
    from app.domains.model_gateway.execution import current_budget
    budget = current_budget()
    await audit_response_finalised(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, outcome=outcome, route=route, completeness=completeness,
        model_execution=({'calls': budget.calls, 'tokens_used': budget.tokens_used,
                          'estimated_tokens': budget.estimated_tokens, 'max_calls': budget.max_calls,
                          'max_total_tokens': budget.max_total_tokens} if budget else None),
    )
    await audit_response_returned(
        db, query_id=query_id, correlation_id=correlation_id,
        tenant_id=tenant_id, audit_chain_id=audit_chain_id,
        actor_id=actor_id, latency_ms=latency_ms,
        stage_metrics=metrics.snapshot() if metrics else {},
    )


# Verification after the agent (claim checks, a correction, pruning) needs
# this much of the request deadline. A fixed 75 s agent budget started after
# ~26 s of retrieval on a long pasted review left ~4 s for it, and the request
# failed with "took too long" instead of returning an answer.
VERIFICATION_RESERVE_SECONDS = 25.0
MIN_AGENT_SECONDS = 20.0


def agent_time_budget(elapsed: float, deadline_seconds: Optional[float] = None) -> float:
    """The agent's time budget: what is left of the request deadline after
    the work already done and the reserve for verification."""
    deadline = deadline_seconds or get_settings().ASK_KRITON_TIMEOUT_SECONDS
    left = deadline - elapsed - VERIFICATION_RESERVE_SECONDS
    return max(MIN_AGENT_SECONDS, left)


async def _review_response(db, review, *, query_id, correlation_id, tenant_id, audit_chain_id,
                           actor_id) -> AskKritonResponse:
    """The claim-by-claim verdicts as an answer. Every row comes from the
    verifier's verdict on that claim's own evidence; nothing is free-written."""
    from app.orchestration.audit_events import audit_claim_review_completed
    from app.orchestration.review_mode import UNVERIFIED

    counts = review.counts
    await audit_composition_started(db, query_id=query_id, correlation_id=correlation_id,
                                    tenant_id=tenant_id, audit_chain_id=audit_chain_id, actor_id=actor_id)
    await audit_claim_review_completed(
        db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
        audit_chain_id=audit_chain_id, actor_id=actor_id, claim_count=len(review.verdicts),
        correct=counts["Correct"], incorrect=counts["Incorrect"], unverified=counts[UNVERIFIED],
        source_count=len(review.sources),
    )
    await audit_composition_completed(
        db, query_id=query_id, correlation_id=correlation_id, tenant_id=tenant_id,
        audit_chain_id=audit_chain_id, actor_id=actor_id, prompt_id="claim-review-v1",
        output_hash=hashlib.sha256(review.text.encode()).hexdigest(),
    )
    citations = [
        SourceCitation(
            ref_id=f"REF-{index}", source_id=source.source_id or source.url, title=source.title,
            url=source.url or None,
            evidence_preview=(source.snippet[:240].strip() or None) if source.snippet else None,
            provider=source.provider, fetched_at=source.fetched_at, freshness=source.freshness,
        )
        for index, source in enumerate(review.sources, start=1)
    ]
    limitations = []
    if counts[UNVERIFIED]:
        limitations.append(f"{counts[UNVERIFIED]} claim(s) could not be verified from the sources found.")
    return AskKritonResponse(
        query_id=query_id, correlation_id=correlation_id, outcome="answered", route=ROUTE_LLM,
        safety=SafetyState(risk_level="LOW", policy_state="allowed"),
        confidence_state=CONF_LIMITED if counts[UNVERIFIED] or not citations else CONF_SUFFICIENT,
        answer=ComposedAnswer(text=review.text, output_text=review.text, citations=citations,
                              limitations=limitations, prompt_id="claim-review-v1",
                              prompt_name="Claim-by-claim review"),
        audit_reference=AuditReference(audit_chain_id=audit_chain_id),
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


def _make_security_incident_response(query_id, correlation_id, audit_chain_id, trigger,
                                     *, matched_text: Optional[str] = None) -> AskKritonResponse:
    from app.orchestration.prescreen import block_message
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
            message=block_message(trigger, matched_text),
        ),
        audit_reference=AuditReference(audit_chain_id=audit_chain_id),
    )
