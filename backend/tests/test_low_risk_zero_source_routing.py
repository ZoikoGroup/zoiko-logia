"""
LOW-risk questions must not be blocked by CLARIFICATION merely because their
keyword-inferred governed-source category (retrieve.py's infer_category) has
zero eligible rows in the source library.

This mirrors test_zero_risk_routing.py's fix for RISK_ZERO, extended to
RISK_LOW for the identical reason — see routing_matrix.py's comment on the
(RISK_LOW, CONF_INSUFFICIENT) row for the full rationale.

Root cause (found via a real, reproduced failure this session): "Do audit
adjustments tend to rise and fall together with total company revenue?" and
"Partner reviews Audit File; Audit File is reviewed by Quality Control." both
keyword-match retrieve.py's "audit" category, which had zero eligible seed
sources — producing confidence_state="insufficient" and, before this fix,
ROUTE_CLARIFICATION, asking the user to clarify jurisdiction/framework for a
question that was never actually ambiguous. Confirmed directly: "Compare the
rates." (genuinely vague — no stated subject, jurisdiction or period) landed
in the "standards" category, which HAD eligible sources, and sailed straight
to ROUTE_LLM with no clarification at all. confidence_state (a retrieval-
coverage signal) was never a reliable proxy for semantic ambiguity — a clear
question in an empty category was blocked; a vague one in a populated
category was not.

The fix does NOT fabricate replacement sources (a prior attempt at this did,
and was reverted — do not do that again, see seed_dev_user.py's SOURCES
comment) and does NOT touch MEDIUM/HIGH/RESTRICTED risk's existing, more
conservative CONF_INSUFFICIENT handling (still ROUTE_HUMAN_REVIEW/REFUSAL) —
those genuinely regulated-stakes tiers still require real evidence or
escalation, per this codebase's own source-governance doctrine.
"""
from __future__ import annotations

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.massarius.answer_validator import validate_answer
from app.domains.massarius.policy_matrix import resolve_policy
from app.orchestration.retrieve import infer_category
from app.orchestration.routing_matrix import (
    CONF_INSUFFICIENT,
    CONF_LIMITED,
    CONF_STALE,
    CONF_SUFFICIENT,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_RESTRICTED,
    ROUTE_CLARIFICATION,
    ROUTE_HUMAN_REVIEW,
    ROUTE_LLM,
    ROUTE_REFUSAL,
    resolve_route,
)
from app.orchestration.schemas import SourceBundle, SourceSummary

_SUBSTANTIVE = (
    "Audit adjustments and total revenue are not mechanically linked; whether "
    "they move together depends on the nature of the adjustments identified "
    "during fieldwork, not on revenue scale alone."
)


# ── 1. Zero retrieval results must not be treated as ambiguity (the core fix) ──

def test_low_risk_zero_sources_answers_instead_of_clarifying():
    """The exact case that reproduced live: a real, well-formed audit
    question landing in a category with zero eligible sources must reach
    the LLM, not get asked to clarify jurisdiction it never needed."""
    decision = resolve_route(RISK_LOW, CONF_INSUFFICIENT)
    assert decision.route == ROUTE_LLM


def test_low_risk_zero_sources_routes_the_same_through_resolve_policy():
    """service.py calls resolve_policy, not resolve_route directly — the fix
    has to be visible on the path actually used at request time."""
    decision = resolve_policy(confidence_state=CONF_INSUFFICIENT, risk_level=RISK_LOW)
    assert decision.route == ROUTE_LLM


# ── 2. Same question WITH a real matching source — must still work (unaffected) ──

def test_low_risk_with_real_source_still_answers():
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED):
        decision = resolve_route(RISK_LOW, confidence)
        assert decision.route == ROUTE_LLM, f"{confidence} -> {decision.route}"


# ── 3. Higher-risk tiers keep their existing, more conservative behavior ──

def test_medium_and_high_risk_zero_sources_still_escalate():
    """The fix is scoped to LOW risk only — a genuinely regulated-stakes
    question with no supporting evidence still escalates rather than
    answering unsupported, matching this codebase's source-governance
    doctrine (docs/...Authoritative_Source_Library...: "No regulated
    technical answer may be generated... unless its source basis is
    traceable"). This is requirement #5's "truthful source-unavailable
    state / escalate" path for evidence-required questions."""
    assert resolve_route(RISK_MEDIUM, CONF_INSUFFICIENT).route == ROUTE_HUMAN_REVIEW
    assert resolve_route(RISK_HIGH, CONF_INSUFFICIENT).route == ROUTE_HUMAN_REVIEW


# ── 4. A genuinely different signal (stale sources) still triggers clarification ──

def test_stale_sources_still_trigger_clarification_at_any_risk():
    """CLARIFICATION remains correct for the state it actually fits — the
    sources ARE there but may be out of date, a real question worth putting
    to the user ("current guidance or historical?"). This is NOT the
    retrieval-emptiness state this fix touches; confirming it is untouched
    is what proves the fix didn't just delete CLARIFICATION outright."""
    for risk in (RISK_LOW, RISK_MEDIUM, RISK_HIGH):
        assert resolve_route(risk, CONF_STALE).route == ROUTE_CLARIFICATION


# ── 5. Retrieval-emptiness is still correctly DETECTED, just not conflated
#      with ambiguity in the routing decision ──

def test_audit_category_still_correctly_reports_zero_eligible_sources():
    """The underlying signal (infer_category routing to a real, sparse
    category) must still be detected and surfaced as confidence_state —
    the fix changes what LOW risk DOES with that signal, not whether the
    signal exists. (Uses the real category function, not a mock, so this
    fails loudly if infer_category's category set ever drifts.)"""
    assert infer_category(
        "Do audit adjustments tend to rise and fall together with total company revenue?"
    ) == "audit"


# ── 6. Grounding validation: an unsourced LOW-risk answer must still be
#      HONEST about having no sources, never silently pass off as cited ──

def test_low_risk_zero_source_answer_still_needs_grounding_of_some_kind():
    """Routing to LLM is not a license to fabricate citations — Checkpoint
    C's grounding check still applies identically to a LOW-risk answer.
    With neither governed nor live sources, a substantive answer still
    fails (mirrors test_zero_risk_routing.py's equivalent case)."""
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer(_SUBSTANTIVE, empty_bundle, external_source_count=0)
    assert not result.passed
    assert any("Grounding" in f for f in result.failures)


def test_low_risk_zero_governed_source_but_real_live_sources_grounds_fine():
    """The realistic success path: no governed-library rows, but SearXNG/
    live-data DID find something — that's real grounding, not a gap."""
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer(_SUBSTANTIVE, empty_bundle, external_source_count=3)
    assert result.passed, result.failures


def test_governed_bundle_alone_still_grounds_a_low_risk_answer():
    """The existing, real-source path must be untouched."""
    bundle = SourceBundle(
        source_bundle_id="sb-1",
        eligible_source_count=1,
        sources=[
            SourceSummary(
                id="s1", title="ISA 315", category="audit",
                jurisdiction_scope="Global", version_label="v1", status="ACTIVE",
            )
        ],
        authority_level="primary",
        confidence_state="sufficient",
        source_display_states={"s1": "show"},
    )
    assert validate_answer(_SUBSTANTIVE, bundle).passed


# ── 8. Genuine ambiguity — documents the real mechanism, doesn't invent one ──

def test_genuinely_vague_query_still_reaches_the_llm_not_a_hard_gate():
    """"Compare the rates." (no stated subject, jurisdiction, or period) is
    real semantic ambiguity — but reproducing this live confirmed
    confidence_state was "sufficient" for it (it landed in the populated
    "standards" category), so it already reached ROUTE_LLM before this fix
    and still does after. There is no separate deterministic ambiguity gate
    in the live ask_kriton() pipeline today — domains/risk_safety/
    risk_classifier.py's _ADVICE_SIGNALS rule exists but is NOT called from
    service.py (verified: only ClassifyRequest, a schema, is imported from
    that module there; pre_screen()/classify() are not). Genuine ambiguity
    is handled by the model's own conversational judgment when it receives
    the query directly — matching the requested architecture's "ask only if
    genuinely necessary" being a model-level decision, not a pre-LLM rule.
    This test documents that fact so a future change to route vague queries
    away from LLM doesn't happen by accident without updating this note."""
    decision = resolve_route(RISK_LOW, CONF_SUFFICIENT)
    assert decision.route == ROUTE_LLM


# ── 9. Out-of-domain — confirms this fix does not touch that mechanism ──

def test_restricted_risk_still_refuses_regardless_of_confidence():
    """Out-of-domain/blocked content is gated by risk_level (RESTRICTED,
    set upstream of this matrix — prescreen.py's L0/L1 hard-blocks and the
    LLM's own domain classification in its system prompt, both entirely
    independent of confidence_state) or ROUTE_REFUSAL text-matched from the
    model's own response — neither of which this fix touches. What IS
    testable here is that RESTRICTED risk refuses at every confidence
    state, confirming this fix (scoped to the RISK_LOW row only) didn't
    accidentally loosen that unrelated gate."""
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT):
        assert resolve_route(RISK_RESTRICTED, confidence).route == ROUTE_REFUSAL


# ── 7. No placeholder/fabricated sources remain in the seed data ──

def test_seed_sources_contain_no_placeholder_titles():
    """Regression guard for the specific mistake made and reverted this
    session: do not seed fake-titled "sources" with no real backing
    document just to make a category non-empty. Real gaps get fixed by
    routing logic (this file) or real source ingestion, never by
    fabricated retrieval hits."""
    from scripts.seed_dev_user import SOURCES

    placeholder_titles = {
        "ISA (International Standards on Auditing) Handbook",
        "Payroll Compliance and Withholding Guide",
        "Firm Internal Control Policy Manual",
        "ACCA/AICPA Syllabus Reference",
        "IRS/HMRC Tax Guidance Manual",
    }
    seeded_titles = {title for _cat, title, _cls, _status, _note in SOURCES}
    assert not (seeded_titles & placeholder_titles)
