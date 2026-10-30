"""Every material figure must come from verified data (ZL-ENG-AGT-01 §07.5,
gate G4; QA demonstration 3)."""
from tests.test_agent_loop import ScriptedClient, _reply

from app.domains.model_gateway.agent import run_agent
from app.domains.model_gateway.tool_registry import build_default_registry
from app.orchestration.figure_reconciliation import material_figures, unreconciled_figures

QUESTION = ("Company A: FY2024 operating profit 120,000 on revenue 1,000,000; "
            "FY2025 operating profit 150,000 on revenue 1,200,000. Compare operating margins.")


def test_only_material_figures_are_checked():
    text = ("Under Section 44AB, Form 3CD [REF-2] is due by 30 September 2025. Turnover above "
            "₹1 crore, a 12.5% margin, $1.2 million and 1,200,000 units. 1. First step.")
    shown = [figure for figure, _ in material_figures(text)]
    assert shown == ["₹1 crore", "12.5%", "$1.2 million", "1,200,000"]


def test_the_directive_golden_case_reconciles():
    """12.0% and 12.5% are ratios of the stated figures; +0.5 pp is their difference."""
    calculator = "Operating margin FY2024: 12.0%. Operating margin FY2025: 12.5%."
    answer = "The margin rose from 12.0% to 12.5%, up 0.5 pp, as profit grew to 150,000."
    assert unreconciled_figures(answer, QUESTION + "\n" + calculator) == []


def test_a_figure_the_model_made_up_is_caught():
    answer = "The margin rose from 12.0% to 13.4%, and revenue reached 987,654."
    assert unreconciled_figures(answer, QUESTION) == ["13.4%", "987,654"]


def test_rounding_units_and_conversions_are_accepted():
    evidence = "Revenue: $716,924,000,000. 1 GBP = 1.178 EUR. Convert 10,000 GBP."
    assert unreconciled_figures("Revenue was about $716.9 billion.", evidence) == []
    assert unreconciled_figures("10,000 GBP is 11,780 EUR.", evidence) == []


async def test_an_answer_with_unsupported_figures_gets_one_correction_then_is_withheld():
    client = ScriptedClient([
        _reply("The margin rose to 13.4%."),
        _reply("The margin rose to 13.9%."),   # still unsupported after the reminder
    ])
    outcome = await run_agent(client, model="m", system_prompt="sys", user_prompt=QUESTION,
                              registry=build_default_registry(), granted_permissions=frozenset())
    assert "do not match any number" in client.requests[1]["messages"][-1]["content"]
    assert outcome.unreconciled_figures == ["13.9%"]
    assert "withheld" in outcome.text and "13.9%" not in outcome.text


async def test_a_corrected_answer_is_released():
    client = ScriptedClient([_reply("The margin rose to 13.4%."), _reply("The margin rose from 12.0% to 12.5%.")])
    outcome = await run_agent(client, model="m", system_prompt="sys", user_prompt=QUESTION,
                              registry=build_default_registry(), granted_permissions=frozenset())
    assert outcome.unreconciled_figures == [] and outcome.text == "The margin rose from 12.0% to 12.5%."


async def test_a_zero_denominator_is_a_clear_controlled_error():
    for expression in ("120000 / 0", "0 / 0"):
        result = await build_default_registry().execute("calculate", {"expression": expression}, granted_permissions=frozenset())
        assert result.error_code == "invalid_arguments" and "Division by zero" in result.content
    other = await build_default_registry().execute("calculate", {"expression": "2 +* 3"}, granted_permissions=frozenset())
    assert "Division by zero" not in other.content


def test_an_amount_marked_k_in_a_thousands_source_is_the_stated_amount():
    # A waterfall's "Revenue | 10,000 k" was read as 10,000,000 and removed,
    # so the chart lost its first bar and was not drawn (QA case D03).
    evidence = "NORTHBRIDGE / INCOME STATEMENT; values USD thousands\nFY2025 Revenue\n10,000"
    answer = "| Step | Amount (USD k) |\n|---|---|\n| Revenue | 10,000 k |"
    assert unreconciled_figures(answer, evidence) == []
    # Without a thousands source, "10,000 k" is still ten million and unverified.
    assert unreconciled_figures(answer.replace("(USD k)", ""), "FY2025 Revenue 10,000") == ["10,000 k"]
    # And a thousands source does not make an unstated amount verified.
    assert unreconciled_figures("| Revenue | 12,000 k |", evidence) == ["12,000 k"]


def test_a_whole_shown_as_100_percent_of_itself_is_kept():
    # "| Revenue | 10 000 | 100.00 % |" removed a waterfall's starting row.
    evidence = "FY2025 Revenue\n10,000\nFY2025 Cost of goods sold\n(6,200)"
    assert unreconciled_figures("| Revenue | 10,000 | 100.00% |", evidence) == []
    # 100% beside an unverified amount, or on its own, is still not evidence.
    assert unreconciled_figures("| Revenue | 12,000 | 100.00% |", evidence) != []
    assert unreconciled_figures("Customer retention was 100.00%.", evidence) == ["100.00%"]


def test_a_waterfall_is_a_chart_request():
    from app.domains.model_gateway.agent import chart_requested
    assert chart_requested("Build a waterfall from FY2025 revenue to net income.")
