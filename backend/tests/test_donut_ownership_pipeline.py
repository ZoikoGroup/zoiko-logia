"""
Regression suite for DONUT + COMPOSITION — backed by real, named UK
shareholders and their declared ownership BAND from Companies House
(persons-with-significant-control). Mirrors the style of
test_correlation_scatter_pipeline.py: every layer (band parsing, intent,
data shape, planning, orchestration, validation) is exercised with real,
honestly-banded synthetic evidence, never a fabricated exact percentage.
"""
from app.domains.market_data.providers.companies_house import _parse_share_band
from app.orchestration.market_data import _OWNERSHIP_HINTS
from app.orchestration.intent_classifier import classify_intent, COMPOSITION, RELATIONSHIP
from app.orchestration.data_shape import classify_data_shape, PART_TO_WHOLE, NONE
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.response_planner import plan_response, TEXT_CHART
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.registry import renderer_for, fallbacks_for
from app.orchestration.visualization.rules import score_candidates


def _ownership_evidence():
    return EvidenceModel(
        subject="Acme Corp",
        composition_subject="Acme Corp — shareholding",
        composition=[
            Observation(dimension="Jane Doe", value=37.5, measure="ownership_percent"),
            Observation(dimension="Acme Holdings Ltd", value=87.5, measure="ownership_percent"),
        ],
        composition_caveat="Ownership bands as filed with Companies House.",
        sources=["https://find-and-update.company-information.service.gov.uk/company/00000001/persons-with-significant-control"],
    )


# ── companies_house.py band parsing ──────────────────────────────────────

def test_parses_standard_band():
    assert _parse_share_band("ownership-of-shares-25-to-50-percent") == (25.0, 50.0)


def test_parses_high_band():
    assert _parse_share_band("ownership-of-shares-75-to-100-percent") == (75.0, 100.0)


def test_normalizes_open_ended_older_wording():
    assert _parse_share_band("ownership-of-shares-more-than-75-percent") == (75.0, 100.0)


def test_voting_rights_only_is_not_a_share_band():
    assert _parse_share_band("voting-rights-25-to-50-percent") is None


def test_appointment_right_is_not_a_share_band():
    assert _parse_share_band("right-to-appoint-and-remove-directors") is None


# ── self-gate ─────────────────────────────────────────────────────────────

def test_ownership_hints_match_shareholder_phrasing():
    assert _OWNERSHIP_HINTS.search("Who are the major shareholders of Acme Corp?")
    assert _OWNERSHIP_HINTS.search("Show the persons with significant control of Acme Corp")
    assert _OWNERSHIP_HINTS.search("What is the PSC register for Acme Corp?")


def test_ownership_hints_do_not_match_unrelated_query():
    assert not _OWNERSHIP_HINTS.search("What is the share price of Apple?")
    assert not _OWNERSHIP_HINTS.search("Explain how revenue is recognised under IFRS 15")


# ── intent classification: COMPOSITION vs RELATIONSHIP disjointness ──────

def test_shareholder_query_classified_as_composition():
    assert classify_intent("Who are the major shareholders of Acme Corp?") == COMPOSITION


def test_significant_control_query_classified_as_composition():
    assert classify_intent("Show persons with significant control for Acme Corp") == COMPOSITION


def test_cap_table_query_classified_as_composition():
    assert classify_intent("What does the cap table for Acme Corp look like?") == COMPOSITION


def test_user_supplied_ownership_structure_stays_relationship():
    # Deliberately NOT reusing "ownership structure" for COMPOSITION — that
    # phrase stays owned by a user-SUPPLIED entity graph.
    assert classify_intent("Show the ownership structure: Acme Corp owns Beta Ltd") == RELATIONSHIP


# ── data shape ────────────────────────────────────────────────────────────

def test_composition_evidence_classified_as_part_to_whole():
    assert classify_data_shape(_ownership_evidence(), COMPOSITION) == PART_TO_WHOLE


def test_composition_intent_without_composition_evidence_is_not_part_to_whole():
    empty = EvidenceModel(subject="Acme Corp")
    assert classify_data_shape(empty, COMPOSITION) != PART_TO_WHOLE


def test_single_slice_is_not_enough_for_part_to_whole():
    one_slice = EvidenceModel(composition=[Observation(dimension="Jane Doe", value=100.0)])
    assert classify_data_shape(one_slice, COMPOSITION) != PART_TO_WHOLE


def test_no_evidence_at_all_is_none_shape():
    assert classify_data_shape(EvidenceModel(), COMPOSITION) == NONE


# ── response planning ────────────────────────────────────────────────────

def test_plan_response_requires_visual_for_composition():
    plan = plan_response("Who are the major shareholders of Acme Corp?", COMPOSITION, PART_TO_WHOLE)
    assert plan.response_mode == TEXT_CHART
    assert plan.visual_required is True
    assert plan.visual_family == "COMPOSITION"


# ── rules.py scoring ──────────────────────────────────────────────────────

def test_donut_scored_for_part_to_whole_composition():
    ranked = dict(score_candidates(
        PART_TO_WHOLE, observation_count=0, explicit_visual_request=False,
        intent=COMPOSITION, composition_count=2,
    ))
    assert "DONUT" in ranked


def test_donut_not_scored_without_composition_intent():
    ranked = dict(score_candidates(
        PART_TO_WHOLE, observation_count=0, explicit_visual_request=False,
        intent=None, composition_count=2,
    ))
    assert "DONUT" not in ranked


def test_donut_not_scored_with_too_few_slices():
    ranked = dict(score_candidates(
        PART_TO_WHOLE, observation_count=0, explicit_visual_request=False,
        intent=COMPOSITION, composition_count=1,
    ))
    assert "DONUT" not in ranked


# ── registry ──────────────────────────────────────────────────────────────

def test_donut_renderer_is_echarts():
    assert renderer_for("DONUT") == "ECHARTS"


def test_donut_fallback_order():
    assert fallbacks_for("DONUT") == ["TABLE", "TEXT"]


# ── full orchestrator pipeline ───────────────────────────────────────────

def test_orchestrator_builds_donut_spec_end_to_end():
    query = "Who are the major shareholders of Acme Corp?"
    evidence = _ownership_evidence()
    intent = COMPOSITION
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)

    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-donut-1", query=query)

    assert result.visual_required is True
    assert result.selected == "DONUT"
    assert result.renderer == "ECHARTS"
    assert result.fallback_order == ["TABLE", "TEXT"]
    assert result.spec is not None
    assert result.spec.type == "DONUT"
    assert result.spec.family == "COMPOSITION"
    assert len(result.spec.donut) == 2
    assert all(s.is_estimated for s in result.spec.donut)
    labels = {s.label for s in result.spec.donut}
    assert labels == {"Jane Doe", "Acme Holdings Ltd"}
    assert result.spec.sources == evidence.sources


def test_orchestrator_no_visual_without_visual_required():
    evidence = EvidenceModel()
    plan = plan_response("What is depreciation?", "FACT", NONE)
    result = VisualizationOrchestrator().decide(evidence, NONE, plan, spec_id="viz-donut-2", query="What is depreciation?")
    assert result.visual_required is False
    assert result.spec is None


# ── validator ─────────────────────────────────────────────────────────────

def _build_donut_result(composition):
    evidence = EvidenceModel(
        subject="Acme Corp", composition_subject="Acme Corp — shareholding",
        composition=composition, sources=["https://example.com/psc"],
    )
    query = "Who are the major shareholders of Acme Corp?"
    shape = classify_data_shape(evidence, COMPOSITION)
    plan = plan_response(query, COMPOSITION, shape)
    return VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="viz-donut-3", query=query)


def test_valid_donut_passes_validation():
    result = _build_donut_result([
        Observation(dimension="Jane Doe", value=37.5),
        Observation(dimension="Acme Holdings Ltd", value=62.5),
    ])
    validation = VisualizationValidator().validate(result.spec)
    assert validation.passed
    assert validation.failures == []


def test_donut_slices_summing_over_100_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, DonutSlice

    spec = VisualizationSpec(
        id="viz-bad-1", type="DONUT", family="COMPOSITION", renderer="ECHARTS",
        donut=[DonutSlice(label="A", value=80.0), DonutSlice(label="B", value=80.0)],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("100%" in f for f in validation.failures)


def test_donut_with_fewer_than_two_slices_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, DonutSlice

    spec = VisualizationSpec(
        id="viz-bad-2", type="DONUT", family="COMPOSITION", renderer="ECHARTS",
        donut=[DonutSlice(label="A", value=100.0)],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("at least 2 slices" in f for f in validation.failures)


def test_donut_with_negative_slice_fails_validation():
    from app.orchestration.visualization.spec import VisualizationSpec, DonutSlice

    spec = VisualizationSpec(
        id="viz-bad-3", type="DONUT", family="COMPOSITION", renderer="ECHARTS",
        donut=[DonutSlice(label="A", value=-10.0), DonutSlice(label="B", value=50.0)],
    )
    validation = VisualizationValidator().validate(spec)
    assert not validation.passed
    assert any("non-negative" in f for f in validation.failures)
