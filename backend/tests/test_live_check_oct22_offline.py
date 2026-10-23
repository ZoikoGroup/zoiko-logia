"""Offline regressions for the failures of the approved 22 Oct 2026 live check
(Nexus, EPS and LCNRV refused; DuPont figures removed and raw LaTeX shown;
WACC answered "inputs unavailable").

No model calls: saved answers, fixtures and the pipeline's own checks only.
These show the backend no longer causes those failures; they do not show what
the model will now answer, which needs a separately approved live test.
"""
import asyncio
import json
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.identity.permissions import ASSIGNABLE_ROLES
from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import figure_reconciliation as reconciliation
from app.orchestration import service
from app.orchestration.agent_plan import plan_request
from app.orchestration.answer_formatting import latex_to_plain
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.prescreen import run_prescreen
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)

QUESTIONS = json.loads((Path(__file__).parent / "fixtures" / "acceptance_questions_20261022.json").read_text())
DUPONT, WACC, NEXUS = QUESTIONS["dupont"], QUESTIONS["wacc"], QUESTIONS["nexus"]


# ── Out-of-scope refusals ──────────────────────────────────────────────────────
# The three refusals were the model's own text (a curly apostrophe; the
# backend's message has a straight one). The live-check harness ran as role
# "ACCOUNTANT", which no permission set names, so every tool call was refused
# and the model fell back to the out-of-scope message.

@pytest.mark.parametrize("name", list(QUESTIONS))
def test_accounting_scenarios_pass_every_backend_scope_check(name):
    question = QUESTIONS[name]
    assert run_prescreen(question).passed
    assert not service._is_deterministically_out_of_scope(question)
    assert service._structured_visual_query_is_in_domain(question) is not False
    plan = plan_request(question)
    assert plan.mode == "agent" and "calculate" in plan.tools


@pytest.mark.parametrize("question", ["Who won the 2022 football World Cup?", "Recommend a good movie for tonight"])
def test_genuine_off_domain_questions_are_still_refused(question):
    assert service._is_deterministically_out_of_scope(question)


def _authorizer(role):
    db = AsyncMock()
    result = MagicMock()
    result.first.return_value = SimpleNamespace(role=role, is_active=True, tenant_id="t")
    db.execute = AsyncMock(return_value=result)
    return service._tool_authorizer(db, lock=asyncio.Lock(), actor_id="a", tenant_id="t", role=role)


@pytest.mark.parametrize("role", sorted(ASSIGNABLE_ROLES))
def test_every_real_role_may_calculate_supplied_figures(role):
    assert asyncio.run(_authorizer(role)("calculate")).allowed


def test_an_unknown_role_is_refused_every_tool():
    # Fail closed, unchanged. The live-check harness used this role, which is
    # why its tool calls were refused; a live test must run as a real role.
    decision = asyncio.run(_authorizer("ACCOUNTANT")("calculate"))
    assert not decision.allowed and decision.reason_code == "role_not_allowed"


# ── WACC and EPS: no market-data lookup for supplied share figures ──────────────

@pytest.mark.parametrize("name", ["wacc", "eps", "vie"])
def test_share_capital_wording_does_not_plan_a_market_data_lookup(name):
    assert "get_market_data" not in plan_request(QUESTIONS[name]).tools


def test_fiscal_year_is_not_an_economic_indicator():
    assert "get_economic_indicator" not in plan_request(QUESTIONS["eps"]).tools
    assert "get_economic_indicator" in plan_request("Show India's fiscal deficit trend").tools


@pytest.mark.parametrize("question", [
    "What is Apple's share price today and its P/E if EPS is 6.1?",
    "Show Tesla stock performance over 5 years",
    "Microsoft market cap vs Google",
    "What dividend did Infosys pay last year?",
])
def test_real_market_lookups_still_plan_the_fetch(question):
    assert "get_market_data" in plan_request(question).tools


async def test_the_wacc_inputs_reach_the_agent_and_no_market_fetch_is_planned(pipeline):
    pipeline.answers(AgentOutcome(text="Scripted answer."))
    await pipeline.ask(WACC)
    prompt = pipeline.agent.call_args.args[0]
    for supplied in ("$950", "$1,000", "7% coupon", "15 years", "$45", "1.3", "4.5%", "6.0%", "$4.00", "$50", "21%"):
        assert supplied in prompt, supplied
    assert "get_market_data" not in pipeline.agent.call_args.kwargs["planned_tools"]
    assert pipeline.agent.call_args.kwargs["stated_facts"].startswith(WACC)


WACC_CALCULATIONS = "calculate: ytm(price=950, face=1000, coupon=70, years=15) = 0.075714"
WACC_WORKING = [
    "- Market value of debt = 40,000 × $950 = $38,000,000",
    "- Market value of common equity = 2,000,000 × $45 = $90,000,000",
    "- Market value of preferred stock = 100,000 × $50 = $5,000,000",
    "- Total capital = $38,000,000 + $90,000,000 + $5,000,000 = $133,000,000",
    "- Weight of debt = $38,000,000 ÷ $133,000,000 = 28.57%",
    "- Weight of equity = $90,000,000 ÷ $133,000,000 = 67.67%",
    "- Weight of preferred = $5,000,000 ÷ $133,000,000 = 3.76%",
    "- Cost of equity = 4.5% + 1.3 × 6.0% = 12.3%",
    "- Cost of preferred = $4.00 ÷ $50 = 8.00%",
    "- Pre-tax cost of debt (YTM) = 7.57%",
    "- After-tax cost of debt = 7.57% × (1 − 0.21) = 5.98%",
    "- WACC = 28.57% × 5.98% + 3.76% × 8.00% + 67.67% × 12.3% = 10.33%",
]


def test_a_correct_wacc_working_is_kept_whole():
    assert unreconciled_figures("\n".join(WACC_WORKING), WACC, WACC_CALCULATIONS, stated=WACC) == []


@pytest.mark.parametrize("wrong, figure", [
    # The equation holds, on an input the question does not give: a 25% tax
    # rate, a beta of 1.4. Two other figures of the line used to vouch for it.
    ("- After-tax cost of debt = 7.57% × (1 − 0.25) = 5.68%", "5.68%"),
    ("- Cost of equity = 4.5% + 1.4 × 6.0% = 12.9%", "12.9%"),
    ("- Pre-tax cost of debt (YTM) = 7.9%", "7.9%"),
])
def test_a_wacc_step_on_an_unsupported_input_is_withheld(wrong, figure):
    text = "\n".join(WACC_WORKING[:-1] + [wrong])
    assert figure in unreconciled_figures(text, WACC, WACC_CALCULATIONS, stated=WACC)


@pytest.mark.parametrize("wrong, figure", [
    ("- WACC = 28.57% × 5.98% + 3.76% × 8.00% + 67.67% × 12.3% = 11.33%", "11.33%"),
    ("- Weight of debt = $38,000,000 ÷ $133,000,000 = 29.57%", "29.57%"),
    ("- Cost of equity = 4.5% + 1.3 × 6.0% = 13.3%", "13.3%"),
    ("- WACC = 28.57% × 5.98% + 3.76% × 8.00% + 67.67% × 12.3% = **11.33 %**", "11.33 %"),
])
def test_a_miscalculated_step_is_the_arithmetic_checks_and_never_verified(wrong, figure):
    """An equation that does not hold is removed by the arithmetic check,
    which names the correct result. The figure check does not count it as
    verified: a figure built on it is withheld."""
    from app.orchestration.calculation_service import validate_answer_calculations
    assert validate_answer_calculations(wrong)
    built_on_it = f"- Hurdle rate set at {figure} plus 2.00 pp."
    text = "\n".join(WACC_WORKING[:-1] + [wrong, built_on_it])
    assert figure in unreconciled_figures(text, WACC, WACC_CALCULATIONS, stated=WACC)


# ── DuPont: correct derived figures were removed ───────────────────────────────

@pytest.mark.parametrize("statement", [
    "- Average Equity = $1,750,000",
    "- Average Total Assets = $3,100,000",
    "| Average Equity | ($1,600,000 + $1,900,000) ÷ 2 | **$1,750,000** |",
    "- Average Equity = (Equity FY 2025 + Equity FY 2026) ÷ 2 = ($1,600,000 + $1,900,000) ÷ 2 = **$1,750,000**",
    # The saved answer's ROE: bold, with a narrow no-break space before %.
    "ROE = $468,000 ÷ $1,750,000 = **26.74 %**",
    "| Equity Multiplier | $3,100,000 ÷ $1,750,000 | **1.77×** |",
    "| Total Asset Turnover | $5,200,000 ÷ $3,100,000 | **1.68×** |",
])
def test_dupont_averages_and_ratios_built_on_them_are_kept(statement):
    assert unreconciled_figures(statement, DUPONT, "", stated=DUPONT) == []


@pytest.mark.parametrize("statement, figure", [
    ("- Average Equity = $1,760,000", "$1,760,000"),
    ("- Average Equity = $1,850,000", "$1,850,000"),
    ("- Average Total Assets = $3,150,000", "$3,150,000"),
])
def test_dupont_wrong_averages_are_still_removed(statement, figure):
    assert figure in unreconciled_figures(statement, DUPONT, "", stated=DUPONT)


DUPONT_ANSWER = """**1. Return on Equity (ROE) – FY 2026**

- Average Equity = ($1,600,000 + $1,900,000) ÷ 2 = **$1,750,000**
- Average Total Assets = ($2,800,000 + $3,400,000) ÷ 2 = **$3,100,000**
- ROE = $468,000 ÷ $1,750,000 = **26.74\u202f%**

| Component | Calculation | Result |
| --- | --- | --- |
| Net Profit Margin | $468,000 ÷ $5,200,000 | **9.00 %** |
| Total Asset Turnover | $5,200,000 ÷ $3,100,000 | **1.68×** |
| Equity Multiplier | $3,100,000 ÷ $1,750,000 | **1.77×** |
"""


async def test_the_dupont_answer_keeps_its_verified_figures(pipeline):
    pipeline.answers(AgentOutcome(text=DUPONT_ANSWER))
    response, _audited = await pipeline.ask(DUPONT)
    for figure in ("$1,750,000", "$3,100,000", "26.74", "9.00", "1.68", "1.77"):
        assert figure in response.answer.text, figure
    assert not any("could not be verified" in item for item in response.answer.limitations)


async def test_a_wrong_bold_dupont_result_is_removed_and_named(pipeline):
    wrong = DUPONT_ANSWER.replace("**26.74\u202f%**", "**27.74\u202f%**")
    pipeline.answers(AgentOutcome(text=wrong))
    response, _audited = await pipeline.ask(DUPONT)
    assert "27.74" not in response.answer.text
    assert response.answer.completeness == "partial"
    assert "did not match its own calculation" in " ".join(response.answer.limitations)


def test_a_year_followed_by_a_comma_is_not_an_operand():
    # "On January 1, 2026, Nexus Corp …": "2026," was read as an amount, so
    # $91,000 passed as the average of $180,000 and 2,026.
    assert "$91,000" in unreconciled_figures("- The figure is $91,000.", NEXUS, "", stated=NEXUS)


def test_the_average_rule_barely_changes_how_many_invented_amounts_pass():
    """Same samples with and without the rule; measured 44 → 45 of 12,352
    (the one extra a true average of a row's two prices)."""
    rng = random.Random(7)
    samples = []
    for name, question in QUESTIONS.items():
        amounts = [a for shown, v in reconciliation.material_figures(question)
                   if (a := reconciliation._amount(shown, v)) >= 100]
        low, high = min(amounts), max(amounts)
        for step in (1, 1000):
            for _ in range(150):
                value = round(rng.uniform(low, high) / step) * step
                if not any(abs(value - a) < step for a in amounts):
                    samples.append((question, value))

    def passed():
        return sum(not unreconciled_figures(f"- The figure is ${value:,.0f}.", q, "", stated=q) for q, value in samples)

    with_rule = passed()
    original = reconciliation._average_of_pair
    reconciliation._average_of_pair = lambda *args: False
    try:
        without_rule = passed()
    finally:
        reconciliation._average_of_pair = original
    assert with_rule - without_rule <= max(2, len(samples) // 1000)


# ── Raw LaTeX ─────────────────────────────────────────────────────────────────

def test_the_saved_dupont_formula_is_readable():
    saved = ("ROE= \\underbrace{(Net Income) ÷ (Sales)}_{Net Profit Margin}\n ×\n"
             " \\underbrace{(Sales) ÷ (Average Total Assets)}_{Total Asset Turnover}\n ×\n"
             " \\underbrace{(Average Total Assets) ÷ (Average Equity)}_{Equity Multiplier}")
    plain = latex_to_plain(saved)
    assert "\\" not in plain and "underbrace" not in plain and "{" not in plain
    assert "(Net Income) ÷ (Sales) [Net Profit Margin]" in plain
    assert "(Average Total Assets) ÷ (Average Equity) [Equity Multiplier]" in plain


@pytest.mark.parametrize("latex, plain", [
    ("ROE = \\underbrace{\\frac{\\text{Net Income}}{\\text{Sales}}}_{\\text{Net Profit Margin}} \\times 1.68",
     "ROE = (Net Income) ÷ (Sales) [Net Profit Margin] × 1.68"),
    ("\\overbrace{1.68 \\times 1.77}^{leverage}", "1.68 × 1.77 [leverage]"),
    # Never "[label](" — that would be a Markdown link.
    ("\\underbrace{a}_{L}(b)", "a [L] (b)"),
    ("\\( \\boxed{26.74\\%} \\)", " 26.74% "),
    ("| NPM | \\( \\frac{468{,}000}{5{,}200{,}000} \\) | 9.00% |", "| NPM |  (468,000) ÷ (5,200,000)  | 9.00% |"),
    # Cut off mid-formula: the command goes, the content stays.
    ("ROE = \\underbrace{(Net Income) ÷ (Sales", "ROE = (Net Income) ÷ (Sales"),
    # "&" outside an aligned row is text.
    ("R&D costs \\times 2 and Profit & Loss", "R&D costs × 2 and Profit & Loss"),
])
def test_latex_becomes_plain_text_with_the_same_meaning(latex, plain):
    assert latex_to_plain(latex) == plain


def test_an_aligned_multiline_formula_keeps_its_steps():
    latex = ("\\[ \\begin{aligned} WACC &= w_d K_d (1-t) + w_e K_e \\\\ "
             "&= 0.2857 \\times 7.57\\% \\times 0.79 \\end{aligned} \\]")
    lines = [line.strip() for line in latex_to_plain(latex).splitlines()]
    assert lines == ["WACC = w_d K_d (1-t) + w_e K_e", "= 0.2857 × 7.57% × 0.79"]


def test_a_formula_in_a_code_block_is_left_alone():
    text = "```\n\\underbrace{x}_{y}\n```"
    assert latex_to_plain(text) == text
