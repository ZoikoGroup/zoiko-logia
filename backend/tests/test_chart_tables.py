"""
Charts over data typed into the question — chart_tables.py (Pareto, funnel,
streamgraph, bubble, parallel coordinates, Sankey, calendar heatmap), plus the
sunburst and bullet charts, which draw existing composition and actual-versus-
target data another way.

Pinned: every figure is read from the question and nothing else; a payload
that does not fully parse produces no chart rather than a partial one; the
figures reach the frontend as an exact TABLE; and the charts that already
existed are untouched.
"""
import pytest

from app.orchestration.chart_tables import extract_chart_table
from app.orchestration.data_shape import CHART_TABLE, PART_TO_WHOLE, SCALAR_TARGET, classify_data_shape
from app.orchestration.extraction import extract_user_visual_evidence
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.response_planner import plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.visualization.validator import VisualizationValidator

PARETO = "Show expenses as a pareto chart: Payroll $180,000, Rent $55,000, IT 25k, Travel 12000, Other 8000"
FUNNEL = ("Show the invoice collection pipeline as a funnel chart: "
          "Invoices issued 500, Reminders sent 320, Disputes resolved 150, Paid 120")
STREAM = ("Show costs over time as a streamgraph: Payroll: 2022 10, 2023 12, 2024 15; "
          "Rent: 2022 5, 2023 6, 2024 6")
BUBBLE = ("Show products as a bubble chart: Product A: revenue 100, margin 20, volume 50; "
          "Product B: revenue 80, margin 35, volume 20")
PARALLEL = ("Compare companies as parallel coordinates: Acme: margin 12, growth 8, debt 30; "
            "Beta: margin 9, growth 15, debt 45")
SANKEY = ("Show cash flows as a sankey chart: Revenue -> Operating Cash: 900; "
          "Operating Cash -> Payroll: 400; Operating Cash -> Tax: 150")
CALENDAR = "Show daily payments as a calendar heatmap: 2026-01-05 12, 2026-01-06 30, 2026-01-12 22"
SUNBURST = ("Show the cost breakdown as a sunburst chart: Payroll / Sales 20%, Payroll / Ops 25%, "
            "Rent / HQ 20%, IT 35%")
BULLET = "Show revenue 8.2m against a target of 10m as a bullet chart"


def _decide(query: str):
    intent = classify_intent(query)
    evidence = extract_user_visual_evidence(query, intent)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    return shape, VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query)


@pytest.mark.parametrize(
    "query, capability, selected, shape",
    [
        (PARETO, "spend_category_analysis", "TABLE", CHART_TABLE),
        (FUNNEL, "funnel_chart", "TABLE", CHART_TABLE),
        (STREAM, "stacked_area_chart", "TABLE", CHART_TABLE),
        (BUBBLE, "bubble_chart", "TABLE", CHART_TABLE),
        (PARALLEL, "scenario_comparison", "TABLE", CHART_TABLE),
        (SANKEY, "flow_of_funds", "TABLE", CHART_TABLE),
        (CALENDAR, "calendar_heatmap", "TABLE", CHART_TABLE),
        (SUNBURST, "sunburst_chart", "DONUT", PART_TO_WHOLE),
        (BULLET, "bullet_chart", "GAUGE", SCALAR_TARGET),
    ],
)
def test_each_named_chart_draws_its_capability(query, capability, selected, shape):
    actual_shape, result = _decide(query)
    assert actual_shape == shape
    assert result.selected == selected
    assert result.capability_id == capability
    assert "isn't available" not in (result.spec.summary or "")
    assert VisualizationValidator().validate(result.spec).passed


def test_pareto_rows_are_sorted_with_a_running_share():
    _shape, result = _decide(PARETO)
    assert result.spec.columns == ["Category", "Value", "Cumulative %"]
    assert [row["Category"] for row in result.spec.rows] == ["Payroll", "Rent", "IT", "Travel", "Other"]
    # Thousand separators, currency symbols and "k" are read as the user meant.
    assert [row["Value"] for row in result.spec.rows] == ["180000", "55000", "25000", "12000", "8000"]
    assert result.spec.rows[-1]["Cumulative %"] == "100.0"


def test_tables_keep_every_figure_in_its_row_and_column():
    _shape, stream = _decide(STREAM)
    assert stream.spec.columns == ["Period", "Payroll", "Rent"]
    assert stream.spec.rows[1] == {"Period": "2023", "Payroll": "12", "Rent": "6"}
    _shape, bubble = _decide(BUBBLE)
    assert bubble.spec.columns == ["Item", "revenue", "margin", "volume"]
    assert bubble.spec.rows[0] == {"Item": "Product A", "revenue": "100", "margin": "20", "volume": "50"}
    _shape, sankey = _decide(SANKEY)
    assert sankey.spec.columns == ["From", "To", "Amount"]
    assert sankey.spec.rows[0] == {"From": "Revenue", "To": "Operating Cash", "Amount": "900"}
    _shape, funnel = _decide(FUNNEL)
    assert [row["Stage"] for row in funnel.spec.rows][0] == "Invoices issued"   # order kept as given


def test_the_caption_says_the_figures_were_supplied():
    _shape, result = _decide(FUNNEL)
    assert result.spec.summary.startswith("Figures supplied directly by the user.")
    assert result.spec.title == "Invoice collection pipeline"


@pytest.mark.parametrize(
    "query",
    [
        "Show expenses as a pareto chart: Payroll lots, Rent some",
        "Show expenses as a pareto chart: Payroll 100",                               # one bar is not a Pareto
        "Show costs as a streamgraph: Payroll: 2022 10, 2023 12; Rent: 2022 5",       # ragged series
        "Show products as a bubble chart: A: x 1, y 2; B: x 3, y 4",                  # a bubble needs a size
        "Show flows as a sankey chart: A -> B: 10; B -> A: 5",                        # a cycle cannot be drawn
        "Show flows as a sankey chart: A -> B: 10; A -> A: 5",                        # nor a self-loop
        "Show payments as a calendar heatmap: 2026-01-05 12, 2026-01-05 30",          # the same day twice
        "Show payments as a calendar heatmap: 2025-01-01 1, 2026-06-01 2",            # more than a year
        "Show expenses as a pareto chart",                                            # no figures at all
    ],
)
def test_a_payload_that_does_not_fully_parse_gives_no_chart(query):
    assert extract_chart_table(query) is None


def test_charts_that_already_existed_are_unchanged():
    _shape, pie = _decide("Show the cost breakdown as a pie chart: Payroll 45%, Rent 30%, Marketing 15%, Other 10%")
    assert pie.capability_id == "pie_chart"
    _shape, gauge = _decide("revenue 8.2m against a target of 10m")
    assert gauge.capability_id == "gauge_speedometer"
    _shape, histogram = _decide(
        "Show the distribution of these invoice amounts as a histogram: 120, 95, 130, 150, 140, 170, 160, 180, 175, 190",
    )
    assert histogram.capability_id == "histogram"
    assert extract_chart_table("Show the cost breakdown as a pie chart: Payroll 45%, Rent 30%") is None
