"""ZERO-risk questions must actually be answered.

orchestration/risk_llm.py classifies greetings, capability questions and plain
definitions as ZERO, but ZERO had no rows in the orchestration routing matrix,
so every such question missed the lookup and fell through to the conservative
CLARIFICATION fallback. FORCE_DIRECT_ANSWER=true was the only thing hiding it.

Fixing the matrix alone is not enough: those answers are typically grounded in
live retrieval (SearXNG + the exact-figure connectors) rather than in the
governed SourceBundle, and Checkpoint C's grounding check counted only bundle
sources — so a correctly-routed ZERO answer would still have been rejected and
degraded to HUMAN_REVIEW. Both halves are covered here.
"""
import os
import sys

# Ensure backend root is in search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.massarius.answer_validator import validate_answer
from app.domains.massarius.policy_matrix import resolve_policy
from app.orchestration.routing_matrix import (
    CONF_INSUFFICIENT,
    CONF_LIMITED,
    CONF_SUFFICIENT,
    RISK_ZERO,
    ROUTE_LLM,
    resolve_route,
)
from app.orchestration.schemas import SourceBundle, SourceSummary

_SUBSTANTIVE = (
    "Taxation in India is structured under a two-tier system comprising direct "
    "and indirect taxes, administered by the CBDT and CBIC respectively."
)


def test_zero_risk_answers_at_every_confidence_state():
    """A greeting or a plain definition has no regulated stakes, so missing
    governed sources is not a reason to withhold an answer."""
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT):
        decision = resolve_route(RISK_ZERO, confidence)
        assert decision.route == ROUTE_LLM, f"{confidence} -> {decision.route}"
    print("test_zero_risk_answers_at_every_confidence_state: PASSED")


def test_zero_risk_routes_the_same_through_resolve_policy():
    """service.py calls resolve_policy, not resolve_route directly — the fix
    has to be visible on the path actually used at request time."""
    for confidence in (CONF_SUFFICIENT, CONF_LIMITED, CONF_INSUFFICIENT):
        decision = resolve_policy(confidence_state=confidence, risk_level=RISK_ZERO)
        assert decision.route == ROUTE_LLM
    print("test_zero_risk_routes_the_same_through_resolve_policy: PASSED")


def test_zero_risk_does_not_force_a_disclaimer_on_its_own():
    """Disclaimers stay tied to MEDIUM risk or limited confidence; a definition
    answered from sufficient sources should not carry one."""
    assert resolve_policy(confidence_state=CONF_SUFFICIENT, risk_level=RISK_ZERO).disclaimer_required is False
    assert resolve_policy(confidence_state=CONF_LIMITED, risk_level=RISK_ZERO).disclaimer_required is True
    print("test_zero_risk_does_not_force_a_disclaimer_on_its_own: PASSED")


def test_live_sources_satisfy_the_grounding_check():
    """An answer composed against SearXNG / connector sources is grounded, even
    though those sources are not registered in the governed SourceBundle."""
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer(_SUBSTANTIVE, empty_bundle, external_source_count=5)
    assert result.passed, result.failures
    print("test_live_sources_satisfy_the_grounding_check: PASSED")


def test_no_sources_of_any_kind_still_fails_grounding():
    """The relaxation must not become a bypass — with neither governed nor live
    sources, a substantive answer is still unsupported."""
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer(_SUBSTANTIVE, empty_bundle, external_source_count=0)
    assert not result.passed
    assert any("Grounding" in f for f in result.failures)
    print("test_no_sources_of_any_kind_still_fails_grounding: PASSED")


def test_citation_binding_accepts_refs_into_live_sources():
    """[REF-N] is assigned positionally over the live citations, so a marker
    inside that range must bind even when the governed bundle is empty."""
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    assert validate_answer("Rates differ by state. [REF-3]", empty_bundle, external_source_count=5).passed
    print("test_citation_binding_accepts_refs_into_live_sources: PASSED")


def test_citation_binding_still_rejects_out_of_range_refs():
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer("See [REF-9].", empty_bundle, external_source_count=5)
    assert not result.passed
    assert any("Citation binding" in f for f in result.failures)
    print("test_citation_binding_still_rejects_out_of_range_refs: PASSED")


def test_governed_bundle_alone_still_grounds_an_answer():
    """The existing path must be untouched: bundle sources with no live sources
    remain sufficient grounding."""
    bundle = SourceBundle(
        source_bundle_id="sb-1",
        eligible_source_count=1,
        sources=[
            SourceSummary(
                id="s1", title="FRS 102", category="standards",
                jurisdiction_scope="UK", version_label="v1", status="ACTIVE",
            )
        ],
        authority_level="secondary",
        confidence_state="sufficient",
        source_display_states={"s1": "show"},
    )
    assert validate_answer(_SUBSTANTIVE, bundle).passed
    print("test_governed_bundle_alone_still_grounds_an_answer: PASSED")
