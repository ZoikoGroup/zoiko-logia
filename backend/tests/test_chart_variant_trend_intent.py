"""
Regression suite for a bug found via live testing: naming a specific chart
rendering ("as a step line chart", "spline line chart", "area chart", "bar
chart") without also using trend wording ("over time", "last N years")
classified as FACT instead of TREND. Since _grounded_domain_fallback() in
service.py only corrects a false LLM off-domain refusal when intent is one
of {DISTRIBUTION, TREND, CURRENT_METRIC, PRECISE_DATA}, this meant genuinely
in-domain, source-grounded CPI/inflation chart requests kept showing the raw
"I'm designed to answer..." refusal even though real DBnomics observations
were found.
"""
from app.orchestration.intent_classifier import classify_intent, TREND
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.service import _grounded_domain_fallback


def _cpi_evidence() -> EvidenceModel:
    return EvidenceModel(
        subject="India CPI",
        observations=[Observation(dimension=f"202{i}", value=100.0 + i) for i in range(10)],
        sources=["https://dbnomics.example/series"],
    )


def test_step_line_chart_phrasing_classified_as_trend():
    assert classify_intent("Show India CPI as a step line chart") == TREND


def test_spline_line_chart_phrasing_classified_as_trend():
    assert classify_intent("Give me a spline line chart of UK inflation") == TREND


def test_area_chart_phrasing_classified_as_trend():
    assert classify_intent("Show India CPI as an area chart") == TREND


def test_bar_chart_phrasing_classified_as_trend():
    assert classify_intent("Show India's CPI as a bar chart") == TREND


def test_line_with_markers_phrasing_classified_as_trend():
    assert classify_intent("Show India CPI as a line with markers") == TREND


def test_bare_trend_phrasing_still_works():
    assert classify_intent("Show India CPI over the last 10 years") == TREND


def test_grounded_fallback_corrects_false_refusal_for_step_line_chart_request():
    text = _grounded_domain_fallback("Show India CPI as a step line chart", _cpi_evidence())
    assert text is not None
    assert "I'm designed to answer" not in text
    assert "India CPI" in text


def test_grounded_fallback_corrects_false_refusal_for_bar_chart_request():
    text = _grounded_domain_fallback("Show India's CPI as a bar chart", _cpi_evidence())
    assert text is not None
    assert "I'm designed to answer" not in text


def test_grounded_fallback_stays_none_without_real_evidence():
    empty = EvidenceModel(subject=None, observations=[], sources=[])
    assert _grounded_domain_fallback("Show India CPI as a step line chart", empty) is None
