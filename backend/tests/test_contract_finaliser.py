"""Stage F: requested outputs in the Task Contract, the finaliser's
deliverable check against them, and the contract-driven chart and report
section decisions (KRITON_CONTRACT_FINALISER / KRITON_CONTRACT_DECISIONS)."""
import pytest

from app.orchestration import service
from app.orchestration.finalisation import deliverable_findings
from app.orchestration.task_contract import build_task_contract

DEPRECIATION = ("Equipment costs £95,000, has a residual value of £11,000 and a useful life of seven years. "
                "Calculate annual straight-line depreciation and the carrying amount after three full years.")


def _outputs(query):
    return [(o.kind, o.name) for o in build_task_contract(query).outputs]


def test_two_requested_amounts_are_two_outputs():
    assert _outputs(DEPRECIATION) == [("amount", "annual straight-line depreciation"),
                                      ("amount", "carrying amount after three full years")]


@pytest.mark.parametrize("query, expected", [
    ("1. Calculate the VAT on £10,000 at 20%. 2. Pass the journal entry.",
     [("amount", "VAT on £10,000 at 20%"), ("journal_entry", "journal entry")]),
    ("Calculate gross profit and margin for the year.", [("amount", "gross profit"), ("amount", "margin for the year")]),
    ("Calculate profit and loss for the year", [("amount", "profit and loss for the year")]),
    ("Calculate the deferred tax liability and pass the journal entry.",
     [("amount", "deferred tax liability"), ("journal_entry", "journal entry")]),
    ("Compute the lease liability, the right-of-use asset and the interest expense for year 1, and prepare the "
     "amortisation schedule.", [("amount", "lease liability"), ("amount", "right-of-use asset"),
                                ("amount", "interest expense for year 1"), ("schedule", "schedule")]),
    ("What is the UK VAT registration threshold?", []),
    ("Explain the difference between IFRS 16 and ASC 842.", []),
])
def test_outputs(query, expected):
    assert _outputs(query) == expected


def _missing(query, answer, **kwargs):
    return [f.expression for f in deliverable_findings(build_task_contract(query).outputs, answer, **kwargs)]


def test_complete_answer_has_no_findings():
    answer = ("Annual depreciation = (£95,000 − £11,000) ÷ 7 = £12,000.\n"
              "Carrying amount after three years = £95,000 − (£12,000 × 3) = £59,000.")
    assert _missing(DEPRECIATION, answer) == []


def test_a_missing_second_output_is_found():
    assert _missing(DEPRECIATION, "Annual straight-line depreciation is £12,000 per year.") == [
        "carrying amount after three full years"]


def test_table_and_synonym_wording_count():
    answer = "| Item | Amount |\n|---|---|\n| Depreciation charge | £12,000 |\n| NBV at end of year 3 | £59,000 |"
    assert _missing(DEPRECIATION, answer) == []


def test_a_named_output_without_a_figure_is_missing():
    assert _missing(DEPRECIATION, "Depreciation is the cost less residual value spread over the life. "
                                  "The carrying amount falls each year.") == [
        "annual straight-line depreciation", "carrying amount after three full years"]


def test_journal_schedule_chart_and_citation():
    query = "Calculate the deferred tax liability and pass the journal entry."
    assert _missing(query, "Deferred tax liability: £5,000.") == ["journal entry"]
    assert _missing(query, "Deferred tax liability: £5,000.\nDr Tax expense £5,000\nCr Deferred tax liability £5,000") == []
    chart = "Calculate revenue growth for 2023 and 2024 and show a chart."
    assert "chart" in _missing(chart, "Revenue growth 2024: 10%.")
    assert "chart" not in _missing(chart, "Revenue growth 2024: 10%.", has_visual=True)
    cite = "Which section of the CGST Act requires registration, and calculate the turnover limit?"
    assert "citation" in _missing(cite, "Turnover limit: ₹40 lakh.")
    assert "citation" not in _missing(cite, "Section 22 requires registration. Turnover limit: ₹40 lakh.")


def test_gaps_are_logged_but_not_applied_by_default(monkeypatch):
    monkeypatch.delenv("KRITON_CONTRACT_FINALISER", raising=False)
    contract = build_task_contract(DEPRECIATION)
    assert service._contract_deliverable_gaps(contract, "Annual depreciation: £12,000.", query_id="q", has_visual=False) == []


def test_gaps_become_incomplete_deliverables_when_on(monkeypatch):
    monkeypatch.setenv("KRITON_CONTRACT_FINALISER", "true")
    contract = build_task_contract(DEPRECIATION)
    [gap] = service._contract_deliverable_gaps(contract, "Annual depreciation: £12,000.", query_id="q", has_visual=False)
    assert gap.status == "incomplete" and gap.description == "requested carrying amount after three full years"
    assert service._contract_deliverable_gaps(object(), "x", query_id="q", has_visual=False) == []  # never raises


def test_contract_records_report_sections_and_chart_from_the_request_part():
    query = ("Last year's board pack had a bar chart of revenue.\n\nPrepare a management report with these sections:\n"
             "1. Executive summary\n2. Financial results and workings\n3. Key changes and interpretation\n"
             "4. Risks and limitations\n5. Management questions\n6. Recommended next steps")
    constraints = build_task_contract(query).output_constraints
    assert len(constraints.report_sections) == 6
    from app.orchestration.answer_coverage import report_section_names
    assert constraints.report_sections == report_section_names(query)


def test_decision_switches_default_off(monkeypatch):
    for name in ("KRITON_CONTRACT_DECISIONS", "KRITON_CONTRACT_FINALISER"):
        monkeypatch.delenv(name, raising=False)
    assert not service._contract_decisions_enabled() and not service._contract_finaliser_enabled()


# From the reviewed accounting conclusions (evals/accounting_review.json).
def test_a_date_comma_is_not_an_output_boundary():
    query = "Calculate revenue and the refund liability at December 31, 2026, and pass the journal entry."
    assert ("amount", "2026") not in _outputs(query)


def test_either_alternative_satisfies_an_or_output():
    query = "Calculate the discount or premium on the bonds."
    assert _missing(query, "Discount on the bonds $120,000.") == []


def test_unearned_profit_matches_unrealised_profit():
    query = "Calculate the intra-entity unearned profit to eliminate."
    assert _missing(query, "Unrealised profit in inventory is 30% of $40,000 = $12,000.") == []


# From the switches-on outcome comparison (3 Nov 2026): real calculator answers.
LEASE_ANSWER = ("### Calculation\n- Lease liability = present value of 5 payments of £30,000.00 in arrears (end of each "
                "period), discounted at 6% a year = £126,370.91\n- Right-of-use asset = lease liability = £126,370.91")


def test_facts_after_a_colon_are_not_outputs():
    query = "Calculate the IFRS 16 lease liability: annual payments of £30,000 in arrears, discount rate 6%, lease term 5 years."
    assert _outputs(query) == [("amount", "IFRS 16 lease liability")]
    assert _missing(query, LEASE_ANSWER) == []


def test_cgst_and_sgst_rows_count():
    query = "Calculate CGST and SGST on an intra-state sale of ₹40,000 at 12%"
    answer = "### Result\n| Item | Value |\n| --- | --- |\n| Cgst | ₹2,400.00 |\n| Sgst | ₹2,400.00 |"
    assert _missing(query, answer) == []


def test_a_tax_row_counts_for_a_named_tax():
    query = "Calculate income tax on £30,000 at 20% after a £12,570 allowance."
    assert _missing(query, "### Result\n| Item | Value |\n| --- | --- |\n| Tax | £3,486.00 |") == []


def test_an_explained_unavailable_chart_is_not_missing():
    query = "Calculate quarterly profit and draw a pie chart: Q1 £20,000, Q2 -£5,000, Q3 £12,000."
    answer = "Profit: £27,000. A pie chart requires non-negative parts with a positive total. Use a bar chart for signed values."
    assert "chart" not in _missing(query, answer)


def test_a_journal_request_answered_with_figures_only_is_incomplete():
    query = "Record the journal entry for a credit sale of £5,000 plus VAT at 20% by a UK VAT-registered business."
    answer = "### Result\n| Item | Value |\n| --- | --- |\n| VAT amount | £1,000.00 |\n| Total including VAT | £6,000.00 |"
    assert _missing(query, answer) == ["journal entry"]
