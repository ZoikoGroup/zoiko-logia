"""
Regression suite for the deterministic visualization pipeline (evidence.py,
intent_classifier.py, data_shape.py, response_planner.py,
visualization/{spec,registry,rules,orchestrator,validator}.py).

Scope matches what's actually implemented — see each module's docstring for
why the full 29-section design-doc taxonomy isn't all covered here yet.
"""
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.intent_classifier import classify_intent, TREND, CURRENT_METRIC, PROCESS, FACT
from app.orchestration.data_shape import classify_data_shape, NONE, SCALAR, TIME_SERIES
from app.orchestration.response_planner import plan_response, TEXT_ONLY, TEXT_KPI, TEXT_CHART
from app.orchestration.visualization.registry import renderer_for, VISUALIZATION_REGISTRY
from app.orchestration.visualization.rules import score_candidates
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator
from app.orchestration.visualization.spec import VisualizationSpec, VisualizationEncoding, EncodingField, VisualizationDataPoint


# ── Intent classification ────────────────────────────────────────────────────

def test_intent_definition_question_is_fact():
    assert classify_intent("What is accrual accounting?") == FACT


def test_intent_trend_question():
    assert classify_intent("Show CPI inflation over the last eight quarters.") == TREND


def test_intent_current_metric_question():
    assert classify_intent("What is the current exchange rate?") == CURRENT_METRIC


def test_intent_process_question():
    assert classify_intent("Explain the invoice approval process.") == PROCESS


# ── Data shape classification ────────────────────────────────────────────────

def test_data_shape_none_for_empty_evidence():
    assert classify_data_shape(EvidenceModel()) == NONE


def test_data_shape_scalar_for_single_observation():
    ev = EvidenceModel(observations=[Observation(dimension="2024-06-01", value=1.08)])
    assert classify_data_shape(ev) == SCALAR


def test_data_shape_time_series_for_three_plus_observations():
    ev = EvidenceModel(observations=[
        Observation(dimension="2024-Q1", value=1.0),
        Observation(dimension="2024-Q2", value=1.1),
        Observation(dimension="2024-Q3", value=1.3),
    ])
    assert classify_data_shape(ev) == TIME_SERIES


# ── ResponsePlanner ───────────────────────────────────────────────────────────

def test_plan_text_only_when_no_evidence():
    plan = plan_response("What is accrual accounting?", FACT, NONE)
    assert plan.response_mode == TEXT_ONLY
    assert plan.visual_required is False


def test_plan_text_chart_for_trend_with_time_series():
    plan = plan_response("Show CPI inflation over the last eight quarters.", TREND, TIME_SERIES)
    assert plan.response_mode == TEXT_CHART
    assert plan.visual_required is True
    assert plan.visual_family == "STATISTICAL"


def test_plan_text_kpi_for_current_metric_with_scalar():
    plan = plan_response("What is the current exchange rate?", CURRENT_METRIC, SCALAR)
    assert plan.response_mode == TEXT_KPI
    assert plan.visual_required is True


def test_plan_text_only_when_evidence_exists_but_not_requested():
    # Evidence exists (SCALAR) but intent doesn't ask to see/plot it —
    # should not force a visual onto an unrelated question (spec §20/§21).
    plan = plan_response("What is accrual accounting?", FACT, SCALAR)
    assert plan.response_mode == TEXT_ONLY
    assert plan.visual_required is False


def test_explicit_chart_request_detected():
    plan = plan_response("Make a chart of this", TREND, TIME_SERIES)
    assert plan.explicit_visual_request is True


def test_common_line_chart_and_plot_phrasings_are_explicit_visual_requests():
    for query in (
        "Show a line chart of US CPI.",
        "Create a chart for US GDP.",
        "Plot the US unemployment rate.",
    ):
        plan = plan_response(query, TREND, TIME_SERIES)
        assert plan.explicit_visual_request is True, query


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_maps_line_to_recharts():
    assert renderer_for("LINE") == "RECHARTS"


def test_registry_maps_evidence_graph_to_graph_adapter():
    assert renderer_for("EVIDENCE_GRAPH") == "GRAPH_ADAPTER"


def test_registry_maps_process_flow_to_flow_adapter():
    assert renderer_for("PROCESS_FLOW") == "FLOW_ADAPTER"


def test_registry_unknown_type_returns_none():
    assert renderer_for("KNOWLEDGE_GRAPH") is None  # not implemented yet — see orchestrator.py docstring


def test_registry_has_no_dangling_entries():
    for viz_type, entry in VISUALIZATION_REGISTRY.items():
        assert "renderer" in entry, viz_type


# ── Deterministic scoring ────────────────────────────────────────────────────

def test_score_time_series_favours_line():
    ranked = score_candidates(TIME_SERIES, observation_count=6, explicit_visual_request=False)
    assert ranked[0][0] == "LINE"


def test_score_time_series_below_minimum_points_has_no_line_candidate():
    # Below _MIN_LINE_POINTS, the deterministic LINE rule doesn't fire — but
    # ava_advisor's BAR disambiguation still applies to short series (real
    # data_shape.py never actually classifies 2 observations as TIME_SERIES;
    # this exercises score_candidates' own guard directly).
    ranked = score_candidates(TIME_SERIES, observation_count=2, explicit_visual_request=False)
    assert "LINE" not in dict(ranked)
    assert dict(ranked).get("BAR") == 0.55


def test_score_scalar_favours_kpi():
    ranked = score_candidates(SCALAR, observation_count=1, explicit_visual_request=False)
    assert ranked[0][0] == "KPI"


def test_explicit_request_bumps_but_does_not_invent_a_candidate():
    without = dict(score_candidates(TIME_SERIES, 6, explicit_visual_request=False))
    with_req = dict(score_candidates(TIME_SERIES, 6, explicit_visual_request=True))
    assert with_req["LINE"] > without["LINE"]
    assert "KPI" not in with_req  # explicit request can't fabricate a candidate the shape doesn't support


# ── VisualizationOrchestrator ────────────────────────────────────────────────

def _time_series_evidence() -> EvidenceModel:
    return EvidenceModel(
        subject="India · Consumer prices",
        observations=[
            Observation(dimension="2023-Q1", value=100.0, measure="cpi"),
            Observation(dimension="2023-Q2", value=101.5, measure="cpi"),
            Observation(dimension="2023-Q3", value=103.2, measure="cpi"),
            Observation(dimension="2023-Q4", value=104.8, measure="cpi"),
        ],
        measures=["cpi"],
        sources=["https://api.db.nomics.world/v22/series/x/y/z"],
    )


def test_orchestrator_builds_line_spec_from_time_series_evidence():
    evidence = _time_series_evidence()
    plan = plan_response("Show inflation over the last four quarters.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-test-1")

    assert result.visual_required is True
    assert result.selected == "LINE"
    assert result.renderer == "RECHARTS"
    assert result.spec is not None
    assert result.spec.type == "LINE"
    assert len(result.spec.data) == 4
    # Same numbers as the evidence — the whole point of building from
    # EvidenceModel instead of re-deriving from LLM text (spec §4).
    assert [p.y for p in result.spec.data] == [o.value for o in evidence.observations]


def test_orchestrator_builds_kpi_spec_from_scalar_evidence():
    evidence = EvidenceModel(
        subject="USD/INR exchange rate",
        observations=[Observation(dimension="2024-06-01", value=83.42, measure="rate")],
        units=["INR"],
        sources=["https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR"],
    )
    plan = plan_response("What is the current USD to INR rate?", CURRENT_METRIC, SCALAR)
    result = VisualizationOrchestrator().decide(evidence, SCALAR, plan, spec_id="viz-test-2")

    assert result.selected == "KPI"
    assert result.spec.value == 83.42
    assert result.spec.unit == "INR"


def test_orchestrator_returns_no_visual_when_plan_does_not_require_one():
    evidence = _time_series_evidence()
    plan = plan_response("What is accrual accounting?", FACT, TIME_SERIES)
    # Force the not-required case directly, since this exact plan/shape combo
    # wouldn't naturally occur — the orchestrator must still respect it.
    plan.visual_required = False
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-test-3")
    assert result.visual_required is False
    assert result.spec is None


def test_orchestrator_returns_no_visual_for_empty_evidence():
    plan = plan_response("Show inflation trend.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(EvidenceModel(), TIME_SERIES, plan, spec_id="viz-test-4")
    assert result.visual_required is False
    assert result.spec is None


# ── VisualizationValidator ───────────────────────────────────────────────────

def _valid_line_spec() -> VisualizationSpec:
    return VisualizationSpec(
        id="viz-1", type="LINE", family="STATISTICAL", renderer="RECHARTS",
        encoding=VisualizationEncoding(
            x=EncodingField(field="period", type="temporal"),
            y=EncodingField(field="value", type="quantitative"),
        ),
        data=[
            VisualizationDataPoint(x="2023-Q1", y=1.0),
            VisualizationDataPoint(x="2023-Q2", y=1.1),
            VisualizationDataPoint(x="2023-Q3", y=1.3),
        ],
    )


def test_validator_accepts_well_formed_line_spec():
    result = VisualizationValidator().validate(_valid_line_spec())
    assert result.passed
    assert result.failures == []


def test_validator_rejects_line_spec_with_too_few_points():
    spec = _valid_line_spec()
    spec.data = spec.data[:2]
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("at least" in f for f in result.failures)


def test_validator_rejects_line_spec_missing_encoding():
    spec = _valid_line_spec()
    spec.encoding = None
    result = VisualizationValidator().validate(spec)
    assert not result.passed


def test_validator_rejects_unordered_line_spec():
    spec = _valid_line_spec()
    spec.data = [
        VisualizationDataPoint(x="2023-Q3", y=1.3),
        VisualizationDataPoint(x="2023-Q1", y=1.0),
        VisualizationDataPoint(x="2023-Q2", y=1.1),
    ]
    result = VisualizationValidator().validate(spec)
    assert not result.passed
    assert any("ordered" in f for f in result.failures)


def test_validator_accepts_well_formed_kpi_spec():
    spec = VisualizationSpec(id="viz-2", type="KPI", family="STATISTICAL", renderer="KPI_TILE", value=83.42)
    result = VisualizationValidator().validate(spec)
    assert result.passed


def test_validator_rejects_kpi_spec_without_value():
    spec = VisualizationSpec(id="viz-3", type="KPI", family="STATISTICAL", renderer="KPI_TILE")
    result = VisualizationValidator().validate(spec)
    assert not result.passed


# ── Auto-fallback cascade ─────────────────────────────────────────────────────
# fallbacks_for() has always computed a degrade chain (e.g. LINE -> [BAR,
# TABLE, TEXT]) but it was only ever surfaced as frontend "View alternatives"
# metadata — a spec that failed validation was silently dropped to no visual.
# decide() now retries the chain itself before giving up.

def _invalid_line_spec(spec_id: str) -> VisualizationSpec:
    # Empty data + no encoding fails validator._line on both counts.
    return VisualizationSpec(id=spec_id, type="LINE", family="STATISTICAL", renderer="RECHARTS", data=[])


def test_line_validation_failure_falls_back_to_bar(monkeypatch):
    import app.orchestration.visualization.orchestrator as orch

    monkeypatch.setattr(orch, "_build_line_spec", lambda evidence, spec_id: _invalid_line_spec(spec_id))

    evidence = _time_series_evidence()
    plan = plan_response("Show inflation over the last four quarters.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-fallback-1")

    assert result.requested_type == "LINE"
    assert result.selected == "BAR"
    assert result.spec is not None
    assert result.spec.type == "BAR"
    assert len(result.spec.data) == 4
    # A fallback substitution has no capability-routing decision behind it.
    assert result.capability_id is None
    assert result.canonical is None
    assert result.variant is None


def test_all_fallbacks_exhausted_degrades_to_no_visual(monkeypatch):
    import app.orchestration.visualization.orchestrator as orch

    def _invalid(spec_type):
        def _builder(evidence, spec_id):
            return VisualizationSpec(id=spec_id, type=spec_type, family="STATISTICAL", renderer=renderer_for(spec_type), data=[])
        return _builder

    monkeypatch.setattr(orch, "_build_line_spec", _invalid("LINE"))
    monkeypatch.setattr(orch, "_build_bar_spec", _invalid("BAR"))
    monkeypatch.setattr(orch, "_build_table_spec", lambda evidence, spec_id: VisualizationSpec(
        id=spec_id, type="TABLE", family="STATISTICAL", renderer="TABLE_ADAPTER", columns=[], rows=[],
    ))

    evidence = _time_series_evidence()
    plan = plan_response("Show inflation over the last four quarters.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-fallback-2")

    assert result.requested_type == "LINE"
    assert result.spec is None
    assert result.visual_required is False
    assert result.selected is None


def test_fallback_never_raises_into_caller(monkeypatch):
    import app.orchestration.visualization.orchestrator as orch

    def _boom(evidence, spec_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(orch, "_build_line_spec", _boom)

    evidence = _time_series_evidence()
    plan = plan_response("Show inflation over the last four quarters.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-fallback-3")

    # LINE's own build raised -> treated as invalid -> cascades to BAR, which
    # builds fine from the same real evidence.
    assert result.selected == "BAR"
    assert result.spec is not None


def test_fallback_spec_gets_recomputed_fallback_order(monkeypatch):
    import app.orchestration.visualization.orchestrator as orch

    monkeypatch.setattr(orch, "_build_line_spec", lambda evidence, spec_id: _invalid_line_spec(spec_id))

    evidence = _time_series_evidence()
    plan = plan_response("Show inflation over the last four quarters.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-fallback-4")

    assert result.selected == "BAR"
    from app.orchestration.visualization.registry import fallbacks_for
    assert result.fallback_order == fallbacks_for("BAR")
    assert result.spec.fallback_order == fallbacks_for("BAR")


def test_no_fallback_when_primary_succeeds_keeps_existing_stamping():
    evidence = _time_series_evidence()
    plan = plan_response("Show inflation over the last four quarters.", TREND, TIME_SERIES)
    result = VisualizationOrchestrator().decide(evidence, TIME_SERIES, plan, spec_id="viz-fallback-5")

    assert result.requested_type == "LINE"
    assert result.selected == "LINE"
    assert result.capability_id is not None
    assert result.canonical is not None
    assert result.spec.capability_id == result.capability_id
    assert result.spec.canonical == result.canonical
