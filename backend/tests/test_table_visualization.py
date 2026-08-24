"""
Regression suite for the TABLE visualization type: PRECISE_DATA intent over
a real multi-point TIME_SERIES produces every real value as a row, going
through the same orchestrator/registry/validator pipeline as every other
type — never LLM-authored markdown.
"""
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.intent_classifier import classify_intent, PRECISE_DATA, CURRENT_METRIC
from app.orchestration.data_shape import classify_data_shape, TIME_SERIES, SCALAR
from app.orchestration.response_planner import plan_response, TEXT_TABLE, TEXT_KPI
from app.orchestration.visualization.registry import renderer_for
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.spec import VisualizationSpec


def _series_evidence(n=6) -> EvidenceModel:
    return EvidenceModel(
        subject="India CPI",
        observations=[Observation(dimension=f"2020-{i:02d}", value=100.0 + i * 1.5) for i in range(n)],
        sources=["https://example.com/series"],
    )


def test_registry_maps_table_to_table_adapter():
    assert renderer_for("TABLE") == "TABLE_ADAPTER"


def test_plan_text_table_for_precise_data_over_time_series():
    plan = plan_response("Give me the exact CPI figures.", PRECISE_DATA, TIME_SERIES)
    assert plan.response_mode == TEXT_TABLE
    assert plan.visual_required is True


def test_plan_still_returns_kpi_for_precise_data_over_scalar():
    # A single value (e.g. one FX rate) can't be meaningfully tabled —
    # PRECISE_DATA + SCALAR must still route to KPI, not TABLE.
    plan = plan_response("Exactly how much is 250 GBP in USD?", PRECISE_DATA, SCALAR)
    assert plan.response_mode == TEXT_KPI


def test_plan_current_metric_over_time_series_still_returns_kpi():
    # Only PRECISE_DATA is redirected to TABLE — CURRENT_METRIC keeps its
    # existing KPI behaviour even over a TIME_SERIES.
    plan = plan_response("What is the current GDP rate?", CURRENT_METRIC, TIME_SERIES)
    assert plan.response_mode == TEXT_KPI


def test_orchestrator_builds_table_with_every_real_value():
    evidence = _series_evidence(6)
    q = "Give me the exact CPI figures for the last few quarters."
    intent = classify_intent(q)
    assert intent == PRECISE_DATA
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="table-test")

    assert result.selected == "TABLE"
    assert result.renderer == "TABLE_ADAPTER"
    assert len(result.spec.rows) == len(evidence.observations)
    # Every real value present, none summarized or dropped.
    row_values = {row["India CPI"] for row in result.spec.rows}
    assert row_values == {f"{o.value:g}" for o in evidence.observations}


def test_table_primary_does_not_get_repeated_kpi_secondary():
    evidence = _series_evidence(6)
    q = "Give me the exact CPI figures for the last few quarters."
    intent = classify_intent(q)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(q, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="table-secondary")
    assert result.secondary_specs == []


def test_validator_accepts_well_formed_table():
    spec = VisualizationSpec(
        id="t1", type="TABLE", family="STATISTICAL", renderer="TABLE_ADAPTER",
        columns=["Period", "Value"],
        rows=[{"Period": "2020-01", "Value": "100"}, {"Period": "2020-02", "Value": "101.5"}],
    )
    result = VisualizationValidator().validate(spec)
    assert result.passed


def test_validator_rejects_table_with_no_rows():
    spec = VisualizationSpec(id="t2", type="TABLE", family="STATISTICAL", renderer="TABLE_ADAPTER", columns=["Period"], rows=[])
    result = VisualizationValidator().validate(spec)
    assert not result.passed


def test_validator_rejects_table_row_missing_a_column():
    spec = VisualizationSpec(
        id="t3", type="TABLE", family="STATISTICAL", renderer="TABLE_ADAPTER",
        columns=["Period", "Value"],
        rows=[{"Period": "2020-01"}],  # missing "Value"
    )
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("missing column" in f for f in result.failures)
