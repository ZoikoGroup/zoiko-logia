"""Stage S2 (shadow): the contract records each part's topics and period, and
the strictness switch as the pipeline computes it. Recorded only. No model,
database or network.
"""
import pytest

from app.orchestration.task_contract import build_task_contract, period_of
from app.orchestration.verification_service import requires_authoritative_evidence


@pytest.mark.parametrize("text, kind, start, end", [
    ("What is the current UK VAT registration threshold?", "current", None, None),
    ("What was the UK VAT registration threshold in 2022?", "year", "2022", "2022"),
    ("What GST rate applies to hotel rooms after the September 2025 changes?", "after", "September 2025", None),
    ("What interest is charged for accounting periods starting on or after 1 January 2023?", "after", "1 January 2023", None),
    ("What interest did HMRC charge for periods that started on or before 31 December 2022?", "before", None, "31 December 2022"),
    ("What are the income tax slabs in India for FY 2025-26?", "year", "2025-26", "2025-26"),
    ("What was the VAT rate between 2008 and 2010?", "range", "2008", "2010"),
    ("What did the VAT rate used to be?", "historical", None, None),
])
def test_the_period_asked_about_is_recorded(text, kind, start, end):
    period = period_of(text, official=True)
    assert (period.kind, period.start, period.end) == (kind, start, end)


def test_an_official_figure_with_no_period_is_the_current_one():
    assert period_of("What is the standard GST rate in Singapore?", official=True).kind == "implied_current"
    assert period_of("Explain how VAT works.").kind == "unspecified"


def test_each_part_records_its_topics_and_period():
    requirement = build_task_contract("What was the UK VAT registration threshold in 2022?").retrieval[0]
    assert requirement.topics == ["tax"] and requirement.period.kind == "year"
    assert "accounting" in build_task_contract("What is deferred tax and why does it arise?").retrieval[0].topics


@pytest.mark.parametrize("query", [
    "What is the current UK VAT registration threshold?",
    "Explain IFRS 16 lease accounting.",
    "What is working capital?",
])
def test_the_strictness_switch_is_the_pipelines(query):
    assert build_task_contract(query).authority_required is requires_authoritative_evidence(query, context=f"\n\n{query}")


def test_a_calculation_on_the_users_figures_is_not_held_to_strict_sourcing():
    # As the pipeline decides it, with the scenario as context (the bare
    # question alone says otherwise: intent_planner and concept_fallback ask it bare).
    query = "A UK business sells goods for £10,000 excluding VAT at the standard rate of 20%. What output VAT does it charge?"
    assert build_task_contract(query).authority_required is False


def test_the_summary_records_the_new_fields():
    summary = build_task_contract("What was the UK VAT registration threshold in 2022?").summary()
    assert summary["retrieval"][0]["period"] == "year" and summary["retrieval"][0]["topics"] == ["tax"]
    assert "authority_required" in summary
