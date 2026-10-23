"""Fixes from the 23 Oct 2026 manual review of ten accounting questions.

1. Routing: figures and terms the question supplies made three answers
   strictly sourced or looked up ("tax rate is 21%", "Income Tax Payable",
   "audit opinion" on the scenario's own misstatements).
2. A correct DuPont ROE (0.2667, 26.67%) was removed as unverified.
3. "[The sources provided do not state this]" was tagged onto arithmetic.
4. Method notes for four wrong methods and two incomplete entries.
5. Accepting a chart offer drew the question's numbers; the offer now
   carries the chart built from the answer's own table.
No model, database or network.
"""
import json
from pathlib import Path

import pytest

from app.orchestration.accounting_methods import accounting_method_guidance
from app.orchestration.agent_plan import plan_request
from app.orchestration.calculation_service import needs_lookup
from app.orchestration.chart_offer import offer_chart, offer_visualization
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.schemas import ChartOfferPublic
from app.orchestration.verification_service import normalize_citations, requires_authoritative_evidence

Q = json.loads((Path(__file__).parent / "fixtures" / "manual_review_questions_20261023.json").read_text())


# ── 1. Routing on supplied figures ───────────────────────────────────────

@pytest.mark.parametrize("name", sorted(Q))
def test_no_reviewed_question_is_strict_sourced_or_looked_up(name):
    assert not requires_authoritative_evidence(Q[name], Q[name])
    assert not needs_lookup(Q[name])
    assert "get_market_data" not in plan_request(Q[name]).tools


@pytest.mark.parametrize("text", [
    "Net income was $500,000. The corporate tax rate is 21%. Compute diluted EPS.",
    "Interest of $60,000 is deductible at a 25% tax rate. Compute the after-tax cost.",
    "The income tax rate was 30% on profit of $200,000. Compute the tax expense.",
])
def test_a_supplied_tax_rate_is_not_a_lookup(text):
    assert not needs_lookup(text)


@pytest.mark.parametrize("text", [
    "What is the corporate tax rate in the UK?",
    "What tax rate applies to dividends in India?",
    "Compute tax on income of $90,000 at the current tax rate.",
])
def test_a_tax_rate_the_question_does_not_give_is_still_looked_up(text):
    assert needs_lookup(text)


def test_tax_line_items_in_a_supplied_scenario_are_not_tax_rules():
    q = Q["cashflow"]
    assert not requires_authoritative_evidence(q, q)
    rule = "What are the income tax payable deadlines for companies in the UK?"
    assert requires_authoritative_evidence(rule, rule)


def test_a_tax_line_item_without_its_amount_still_needs_the_rate():
    q = ("Calculate taxable income for Year 1, determine the net deferred tax asset or liability movement, "
         "and write out the provision for income taxes.")
    assert requires_authoritative_evidence(q, "Pre-tax income $500,000; depreciation $120,000 versus $70,000.")


def test_an_audit_opinion_on_the_scenarios_own_misstatements_is_professional_application():
    assert not requires_authoritative_evidence(Q["materiality"], Q["materiality"])
    bare = "When must an auditor issue an adverse audit opinion?"
    assert requires_authoritative_evidence(bare, bare)


# ── 2. A verified result restated as a percentage ────────────────────────

CALCS = "\n".join(["400000 / 5000000 = 0.08", "(2800000 + 3200000) / 2 = 3000000", "5000000 / 3000000 = 1.666667",
                   "(1400000 + 1600000) / 2 = 1500000", "3000000 / 1500000 = 2"])
DUPONT = """| Ratio | Formula | Calculation | Result |
|---|---|---|---|
| Net Profit Margin | Net Income ÷ Total Sales | 400 000 ÷ 5 000 000 | 0.08 (8 %) |
| Asset Turnover | Total Sales ÷ Average Total Assets | 5 000 000 ÷ 3 000 000 | 1.67 times |
| Equity Multiplier | Average Total Assets ÷ Average Total Equity | 3 000 000 ÷ 1 500 000 | 2.00 times |
| **Return on Equity (ROE) – DuPont** | Net Profit Margin × Asset Turnover × Equity Multiplier | 0.08 × 1.6667 × 2.00 | **0.2667 (26.67 %)** |
| **Return on Equity (ROE) – Direct** | Net Income ÷ Average Total Equity | 400 000 ÷ 1 500 000 | **0.2667  (26.67 %)** |

**Efficiency (Asset Turnover)** – Each dollar of average assets generates $1.67 of sales.

ROE = 0.08 × 1.6667 × 2.00 = 0.2667   (or  26.67%)

- **Return on Equity (DuPont):** 26.67 % (verified by the direct ROE calculation)."""


def test_the_reviewed_dupont_answer_keeps_its_roe():
    assert unreconciled_figures(DUPONT, Q["dupont"], CALCS, stated=Q["dupont"]) == []


def test_a_wrong_percentage_is_still_removed():
    wrong = DUPONT.replace("26.67 % (verified", "31.50 % (verified")
    assert unreconciled_figures(wrong, Q["dupont"], CALCS, stated=Q["dupont"]) == ["31.50 %"]


def test_a_percentage_of_an_equation_with_an_unverified_operand_is_still_removed():
    text = "ROE = 0.08 × 1.70 × 2.00 = 0.272 (or 27.2%)\n- ROE: 27.2%"
    assert "27.2%" in unreconciled_figures(text, Q["dupont"], CALCS, stated=Q["dupont"])


def test_an_amount_is_never_a_hundred_times_a_ratio():
    text = "ROE = 0.08 × 1.6667 × 2.00 = 0.2667\nProfit = $26.67"
    assert "$26.67" in unreconciled_figures(text, Q["dupont"], CALCS, stated=Q["dupont"])


# ── 3. Gap tags on the answer's own arithmetic ───────────────────────────

@pytest.mark.parametrize("tagged, clean", [
    ("Aggregate = 180,000 + 140,000 + 210,000 = 530,000 [The sources provided do not state this]",
     "Aggregate = 180,000 + 140,000 + 210,000 = 530,000"),
    ("| Understatement of accrued liabilities | 140,000 [The sources provided do not state this] |",
     "| Understatement of accrued liabilities | 140,000 |"),
    ("It also exceeds performance materiality of $375,000 [The sources provided do not state this.].",
     "It also exceeds performance materiality of $375,000."),
])
def test_a_bracketed_gap_tag_is_removed(tagged, clean):
    assert normalize_citations(tagged, set()) == clean


def test_a_gap_sentence_on_its_own_stays():
    text = "### Communication strategy\nThe sources provided do not state this."
    assert normalize_citations(text, set()) == text


# ── 4. Method notes ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name, must_say", [
    ("lease", "total lease payments ÷ lease term"),
    ("dvlifo", "index of the year that layer was added"),
    ("eps", "if-converted method"),
    ("pps", "expansion factor multiplies only an expected misstatement"),
    ("combination", "debit the subsidiary's equity accounts"),
    ("revenue", "is not revenue on the earlier date"),
])
def test_each_wrong_method_gets_its_note(name, must_say):
    assert must_say in accounting_method_guidance(Q[name])


@pytest.mark.parametrize("name", ["npv", "cashflow", "dupont", "materiality"])
def test_questions_answered_correctly_get_no_note(name):
    assert accounting_method_guidance(Q[name]) == ""


@pytest.mark.parametrize("question", [
    "What is a finance lease?",
    "Explain LIFO and FIFO.",
    "What is basic EPS?",
    "How do I calculate NPV?",
])
def test_unrelated_questions_get_no_note(question):
    assert accounting_method_guidance(question) == ""


def test_notes_state_methods_not_answers():
    for name in ("lease", "dvlifo", "eps", "pps"):
        guidance = accounting_method_guidance(Q[name])
        for answer in ("50,000", "350,500", "2.11", "60 items", "20,000"):
            assert answer not in guidance


def test_the_prompt_receives_the_notes():
    import inspect
    from app.orchestration import service
    assert "grounded_input += accounting_method_guidance(request.query)" in inspect.getsource(service)


# ── 5. The chart offer carries its chart ─────────────────────────────────

REVENUE = """| Performance obligation | Timing of revenue recognition | Amount recognised in 2026 |
|---|---|---|
| Software licence | Delivered immediately on Jan 1 2026 (point‑in‑time) | $120,000 |
| Implementation services | Completed on Mar 31 2026 (point‑in‑time) | $48,000 |
| Technical support | Over 24 months, straight‑line (12 months fall in 2026) | $36,000 |
| **Total revenue recognised in 2026** | | **$204,000** |"""
NPV = """| Year | Cash‑inflow | PV factor (10 %) | Present‑value (PV) |
|---|---|---|---|
| 1 | $300,000 | 0.9091 | $272,730 |
| 2 | $350,000 | 0.8264 | $289,240 |
| 3 | $280,000 | 0.7513 | $210,364 |
| 4 | $200,000 | 0.6830 | $136,600 |"""
LIFO = """| Item | Amount (base‑year $) | Amount (2026 current $) |
|---|---|---|
| Base‑year inventory (layer) | $300,000 | $375,000 |
| Layer added in 2025 | $30,000 | $37,500 |
| Layer added in 2026 | $14,000 | $17,500 |"""


def test_the_reviewed_pie_is_drawn_from_the_answer_not_the_question():
    spec = offer_visualization(offer_chart(REVENUE), REVENUE, "q-offer")
    assert spec.type == "DONUT" and spec.unit == "%"
    shares = {slice_.label: round(slice_.value, 2) for slice_ in spec.donut}
    assert shares == {"Software licence": 58.82, "Implementation services": 23.53, "Technical support": 17.65}
    assert all(not slice_.is_estimated for slice_ in spec.donut)


def test_a_series_over_years_is_a_line():
    spec = offer_visualization(offer_chart(NPV), NPV, "q-offer")
    assert spec.type == "LINE" and [p.y for p in spec.series[0].data] == [300000, 350000, 280000, 200000]


def test_two_measures_are_grouped_bars():
    spec = offer_visualization(offer_chart(LIFO), LIFO, "q-offer")
    assert spec.type == "GROUPED_BAR" and len(spec.series) == 2


def test_the_public_offer_carries_the_chart():
    offer = offer_chart(REVENUE)
    public = ChartOfferPublic(chart_type=offer.chart_type, title=offer.title, question=offer.question,
                              reason=offer.reason, chart=offer_visualization(offer, REVENUE, "q-offer"))
    assert public.model_dump(mode="json")["chart"]["type"] == "DONUT"


def test_the_same_table_always_gets_the_same_chart_id():
    from app.orchestration.chart_offer import offer_spec_id
    assert offer_spec_id(offer_chart(REVENUE)) == offer_spec_id(offer_chart(REVENUE))
    assert offer_spec_id(offer_chart(REVENUE)) != offer_spec_id(offer_chart(NPV))


def test_an_offer_without_a_drawable_chart_is_not_made():
    import inspect
    from app.orchestration import service
    source = inspect.getsource(service)
    assert "if offer is not None and chart is not None:" in source


# ── Second review (23 Oct 2026, later): EPS computed, payment upfront, ────
#    later services deferred, prose columns not charted

from decimal import Decimal

from app.orchestration.diluted_eps import eps_schedule, verified_eps_block
from app.orchestration.verification_service import received_consideration, unsupported_balances

EPS2 = """Net income for 2026 is $900,000, with 400,000 common shares outstanding all year. The company also has:
• 8,000 shares of 6%, $100 par cumulative convertible preferred stock, each convertible into 5 common shares.
• $500,000 of 5% convertible bonds, convertible into 20,000 common shares.
The tax rate is 25%.
Required: Calculate basic EPS, test each convertible for dilution, and calculate diluted EPS."""


def _eps(question):
    schedule = eps_schedule(question)
    return round(schedule.basic, 4), round(schedule.diluted, 4), [step[0] for step in schedule.steps if step[5]]


def test_the_second_review_eps_is_computed():
    assert _eps(EPS2) == (Decimal("2.13"), Decimal("1.9973"), ["Convertible bonds", "Convertible preferred stock"])


def test_the_first_review_eps_is_computed():
    assert _eps(Q["eps"]) == (Decimal("2.3"), Decimal("2.1142"), ["Convertible bonds", "Convertible preferred stock"])


def test_the_year_is_never_net_income():
    assert eps_schedule(EPS2).net_income == Decimal("900000")


def test_an_antidilutive_convertible_is_excluded_and_diluted_never_exceeds_basic():
    q = ("Net income is $100,000 with 100,000 common shares outstanding. The company has $1,000,000 of 10% "
         "convertible bonds, convertible into 10,000 common shares. The tax rate is 20%. Calculate diluted EPS.")
    basic, diluted, included = _eps(q)
    assert included == [] and diluted == basic == Decimal("1")


@pytest.mark.parametrize("change", [
    lambda q: q + " Employees also hold 10,000 stock options.",            # treasury-stock method
    lambda q: q.replace("The tax rate is 25%.", ""),                      # bonds without a tax rate
    lambda q: q.replace("calculate diluted EPS", "calculate basic EPS").replace("test each convertible for dilution, and ", ""),
    lambda q: q.replace(", each convertible into 5 common shares", ""),   # preferred terms missing
])
def test_anything_not_read_with_certainty_is_left_to_the_model(change):
    assert eps_schedule(change(EPS2)) is None and verified_eps_block(change(EPS2)) == ""


def test_the_schedule_states_the_conclusions_for_the_model():
    block = verified_eps_block(EPS2)
    assert "do not recompute or contradict" in block and "DILUTIVE and included" in block
    assert "$918,750.00 ÷ 460,000 = $1.9973" in block and "Diluted EPS = $1.9973" in block


def test_the_prompt_receives_the_schedule():
    import inspect
    from app.orchestration import service
    assert "grounded_input += verified_eps_block(request.query)" in inspect.getsource(service)


REVENUE2 = ("On February 1, 2026, a company signs a $180,000 contract that includes equipment delivered February 1, "
            "2026, installation completed February 28, 2026, and two years of maintenance starting March 1, 2026. "
            "Give the journal entry on February 1 assuming full payment upfront, and compute revenue recognized in 2026.")


@pytest.mark.parametrize("question, received", [
    (REVENUE2, [180000.0]),
    ("A bundled contract has a total contract price of $240,000; the entire $240,000 was collected upfront.", [240000.0]),
    ("A $90,000 contract was paid in full on signing.", [90000.0]),
    ("A $180,000 contract includes equipment and installation. Allocate the price.", []),
    ("The implementation fee is £6,000. The customer paid £24,000 upfront.", [24000.0]),
])
def test_full_payment_upfront_is_the_contract_price_received(question, received):
    assert received_consideration(question) == received


def test_the_correct_contract_liability_is_kept():
    from app.orchestration.verification_service import VerifiedFigures
    answer = "Contract liability on February 1 = $180,000 − $108,000 = $72,000."
    calculated = VerifiedFigures(results={"108000.00", "72000.00"}, inputs=set())   # the calculator's results
    _text, flagged = unsupported_balances(answer, REVENUE2, calculated)
    assert flagged == []


def test_without_a_stated_payment_the_liability_is_still_not_established():
    from app.orchestration.verification_service import VerifiedFigures
    answer = "Contract liability on February 1 = $180,000 − $108,000 = $72,000."
    no_payment = REVENUE2.replace(" assuming full payment upfront", "")
    _text, flagged = unsupported_balances(answer, no_payment, VerifiedFigures(results={"108000.00"}, inputs=set()))
    assert "$72,000" in flagged


def test_a_later_service_is_not_contract_date_revenue_in_the_note():
    from app.orchestration.accounting_methods import accounting_method_guidance
    q = REVENUE2.replace("Give the journal entry", "Allocate the standalone selling prices (transaction price $180,000). "
                         "Give the journal entry")
    assert "completed later" in accounting_method_guidance(q)


LIFO2 = """| Year | Year‑end inventory (at year‑end prices) | Price index | Deflated inventory (base‑year cost) = Inventory ÷ Index | Layer activity* | Dollar‑Value LIFO ending inventory |
|---|---|---|---|---|---|
| 2023 (base) | – | 1.00 | $200,000 | – | – |
| 2024 | $242,000 | 1.10 | $220,000 | Add layer of $20,000 (base‑year cost) → valued at 1.10 → $20,000 × 1.10 = $22,000 | $200,000 × 1.00 + $22,000 = $222,000 |
| 2025 | $252,000 | 1.20 | $210,000 | Erode $10,000 of the most recent layer → valued at 1.10 → $10,000 × 1.10 = $11,000 | $200,000 × 1.00 + $11,000 = $211,000 |"""


def test_a_prose_column_is_not_charted():
    offer = offer_chart(LIFO2)
    names = [series["name"] for series in offer.chart["series"]]
    assert not any("Layer activity" in name for name in names)
    assert "Dollar‑Value LIFO ending inventory" in names


def test_a_series_name_drops_its_formula_and_the_title_stays_short():
    offer = offer_chart(LIFO2)
    assert "Deflated inventory (base‑year cost)" in [series["name"] for series in offer.chart["series"]]
    assert offer.title == "Year‑end inventory (at year‑end prices) and 2 other measures by year"


@pytest.mark.parametrize("cell, value", [("$200,000 × 1.00 + $22,000 = $222,000", "222000"), ("$120,000", "120000"),
                                         ("1.44 = 1.20 × 1.20", "1.44")])
def test_figure_cells_and_equations_still_read(cell, value):
    from app.orchestration.chart_offer import _value
    assert _value(cell) == Decimal(value)


def test_a_sentence_cell_is_not_a_figure():
    from app.orchestration.chart_offer import _value
    assert _value("Add layer of $20,000 (base‑year cost) → valued at 1.10 → $20,000 × 1.10 = $22,000") is None


# ── Third review (23 Oct 2026, evening): narration, unrequested entries, ──
#    mixed-unit and summary charts, malformed paragraph ranges

LEAK_EPS = """Re‑calculated figures (using the calculator tool)

| Item | Calculation (exact operands) | Calculator result |
|---|---|---|
| Net income + after‑tax interest | 600,000 + 42,000 = 642,000 | $642,000 |

Updated answer with calculator‑verified numbers (structure unchanged)
1. Basic earnings‑per‑share (basic EPS)

Basic EPS = 560,000 ÷ 300,000 = 1.866667

The calculator‑verified figures ($642,000 for net income + after‑tax interest) have been incorporated throughout, preserving the original structure and citations."""


def test_the_revision_preamble_and_closing_narration_are_removed():
    cleaned = normalize_citations(LEAK_EPS, set())
    assert cleaned.startswith("1. Basic earnings‑per‑share")
    assert "Basic EPS = 560,000 ÷ 300,000 = 1.866667" in cleaned
    for leak in ("Re‑calculated", "Updated answer", "structure", "incorporated throughout"):
        assert leak not in cleaned


@pytest.mark.parametrize("leaked, clean", [
    ("Monthly support revenue = $38,400 ÷ 12 = $3,200 (calculation 5).",
     "Monthly support revenue = $38,400 ÷ 12 = $3,200."),
    ("The allocation percentages are now shown as the exact results of the calculator calls (see calculations 1‑3). "
     "Licence $48,000.", "Licence $48,000."),
    ("3. Revenue recognised in 2026 (calculator‑derived amounts unchanged)", "3. Revenue recognised in 2026"),
    ("Identifiable assets: 500000 + 80000 + 120000 = 700000  [calc ID 1]", "Identifiable assets: 500000 + 80000 + 120000 = 700000"),
    ("All calculations now use the calculator‑generated results and retain the same structure and citations as before. "
     "Diluted EPS is $1.77.", "Diluted EPS is $1.77."),
])
def test_revision_narration_is_removed(leaked, clean):
    assert normalize_citations(leaked, set()).strip() == clean


@pytest.mark.parametrize("text", [
    "Revenue remains the same because prices are unchanged in 2026.",
    "The table keeps the same columns as last year.",
    "Depreciation = 100,000 ÷ 5 = 20,000 (straight-line).",
    "Calculation of goodwill: 850,000 − 670,000 = 180,000.",
    "The capital structure is unchanged after the issue.",
])
def test_ordinary_text_is_kept(text):
    assert normalize_citations(text, set()) == text


@pytest.mark.parametrize("cited, clean", [
    ("IAS 33 §13‑13 requires the deduction.", "IAS 33 requires the deduction."),
    ("See ASC 260 ¶36‑33 for this.", "See ASC 260 for this."),
    ("IAS 33 ¶41‑¶42 excludes antidilutive items.", "IAS 33 ¶41‑¶42 excludes antidilutive items."),
    ("IFRS 15 para 73-86 governs allocation.", "IFRS 15 para 73-86 governs allocation."),
])
def test_only_a_malformed_paragraph_range_is_dropped(cited, clean):
    assert normalize_citations(cited, set()) == clean


def test_the_correction_rounds_ask_for_the_answer_only():
    import inspect
    from app.domains.model_gateway import agent
    source = inspect.getsource(agent)
    assert source.count("+ FINAL_ANSWER_ONLY") == 3
    assert "do not mention this request, a revision" in agent.FINAL_ANSWER_ONLY


def test_unrequested_entries_are_ruled_out_only_when_none_are_asked_for():
    from app.orchestration.accounting_methods import NO_UNREQUESTED_ENTRIES
    assert NO_UNREQUESTED_ENTRIES in accounting_method_guidance(EPS2)
    assert "Do not add journal entries" in verified_eps_block(EPS2)
    assert NO_UNREQUESTED_ENTRIES not in accounting_method_guidance(Q["revenue"])     # asks for a journal entry


EPS_STEPS = """### 3. Diluted EPS
| Step | Calculation (calculator) | Result |
|---|---|---|
| Earnings after bonds | 852000 + 18750 | $870 750 |
| Shares after bonds | 400000 + 20000 | 420 000 |
| EPS after bonds | 870 750 ÷ 420 000 | $2.073214 (rounded $2.07) |
| Earnings after both | (852000 + 18750) + 48000 | $918 750 |"""
KEY_FIGURES = """Summary of key figures (USD)
| Item | Amount |
|---|---|
| Allocated licence revenue | $48,000 |
| Allocated training revenue | $9,600 |
| Revenue recognised in 2026 | $83,200 |
| Contract liability on 31‑Dec‑2026 | $12,800 |"""
EXPENSES = """Operating Expenses – 2026
| Expense | Amount (USD) | % of Total |
|---|---|---|
| Salaries | 250,000 | 50 % |
| Rent | 100,000 | 20 % |
| Marketing | 75,000 | 15 % |
| Utilities | 25,000 | 5 % |
| Other | 50,000 | 10 % |
| Total | 500,000 | 100 % |"""


def test_a_column_mixing_money_and_counts_is_not_offered():
    assert offer_chart(EPS_STEPS) is None


def test_a_summary_table_is_not_offered():
    assert offer_chart(KEY_FIGURES) is None


def test_a_real_breakdown_is_still_offered_as_a_pie():
    offer = offer_chart(EXPENSES)
    assert offer.chart_type == "pie" and offer.title == "% of Total by expense"


def test_the_dilution_rule_is_stated_against_the_running_eps_before_inclusion():
    from app.orchestration.accounting_methods import accounting_method_guidance as guidance
    block = verified_eps_block(EPS2)
    assert "below the running EPS before it is added" in block
    assert "below the running EPS before it is added" in guidance(EPS2)
    assert "after its inclusion" not in block
