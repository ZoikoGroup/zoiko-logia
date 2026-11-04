"""Task Contract, Stage D: validator findings and their resolution.

The Harbor lease answer (29 Oct 2026) lost its correct liability: the model
showed "50,000 × 3.465106 = 173,255.280635" (a six-place factor beside the
exact result), the arithmetic re-check computed 173,255.30 from the rounded
factor and removed the figure, though it was the lease calculator's own
verified result. Now the arithmetic validator reports findings, judges a
result within the rounding its displayed intermediates carry (P2), and a
figure the calculator verified is not disproved by a re-check (P1). A real
error is still caught. No model, database or network.
"""
from decimal import Decimal

import pytest

from app.domains.model_gateway.agent import AgentOutcome, ToolResult, _tool_verified_values
from app.orchestration.calculation_service import arithmetic_findings, validate_answer_calculations
from app.orchestration.calculations.lease import lease_calculation
from app.orchestration.finalisation import ValidationFinding, resolve, verified_values_from
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

HARBOR = ("Harbor Freight Logistics Inc. leases a warehouse under a 4-year lease starting January 1, 2026. Annual "
          "payments of $50,000 are due at the end of each year. The company's incremental borrowing rate is 6%. The "
          "lease is an operating lease under ASC 842.\n\nTask for the Bot:\n1. Calculate the initial lease liability "
          "and right-of-use asset.\n2. Prepare the journal entry at commencement.\n3. Explain how the single lease "
          "cost is presented in the income statement for an operating lease.")


# P2: the rounding a step's displayed intermediates carry ------------------

def test_a_result_within_its_rounded_factor_is_not_a_mismatch():
    assert validate_answer_calculations("Liability = 50,000 × 3.465106 = 173,255.280635") == []


@pytest.mark.parametrize("working, expected", [
    ("Liability = 50,000 × 3.465106 = 173,300.00", "equals 173255.3, not 173300."),   # a real error, same factor
    ("VAT = 2,400 × 0.2 = 490", "equals 480, not 490."),                               # an exact rate stays strict
    ("Interest = 70,919.01 × 0.05 = 3,600.00", "not 3600."),                          # two places: exact
])
def test_a_real_error_is_still_caught(working, expected):
    failures = validate_answer_calculations(working)
    assert len(failures) == 1 and expected in failures[0]


def test_the_failure_text_every_caller_reads_is_unchanged():
    assert validate_answer_calculations("Total = 1,200 + 300 = 1,600") == [
        "Calculation mismatch: 1,200 + 300 equals 1500, not 1600."]
    assert validate_answer_calculations("| Account | Debit | Credit |\n|---|---|---|\n| Cash | 1,000 | |\n| Revenue | | 900 |") \
        == ["Journal entry does not balance: debits total 1000, credits total 900."]


# P1: provenance before re-check -----------------------------------------

def test_a_figure_the_calculator_verified_is_not_disproved():
    # A factor shown to two places is taken as exact, so the re-check gives
    # 173,500 and, without provenance, calls the calculator's result wrong.
    working = "Liability = 50,000 × 3.47 = 173,255.28"
    assert validate_answer_calculations(working)
    verified = verified_values_from(lease_calculation(HARBOR))
    assert Decimal("173255.28") in [round(value, 2) for value in verified]
    assert validate_answer_calculations(working, verified) == []
    findings = arithmetic_findings(working)
    resolution = resolve(findings, verified_values=verified)
    assert resolution.standing == [] and "P1" in resolution.overridden[0][1]


def test_provenance_never_excuses_a_different_figure():
    verified = verified_values_from(lease_calculation(HARBOR))
    assert validate_answer_calculations("Liability = 50,000 × 3.47 = 173,900.00", verified)


def test_findings_are_structured():
    finding = arithmetic_findings("Total = 1,200 + 300 = 1,600")[0]
    assert isinstance(finding, ValidationFinding)
    assert (finding.category, finding.rule, finding.action) == ("numerical_correctness", "arithmetic_mismatch",
                                                                "remove_statement")
    assert finding.stated == Decimal("1600") and finding.expected == Decimal("1500")


def test_the_agents_calculate_results_are_its_verified_values():
    executed = {("calculate", "a"): ToolResult(ok=True, content="50000 * 3.46510561 = 173255.2806"),
                ("search_web", "b"): ToolResult(ok=True, content="Rate 9,999")}
    assert "173255.2806" in _tool_verified_values(executed) and "9999" not in _tool_verified_values(executed)


# Through the pipeline ---------------------------------------------------

async def test_the_lease_liability_survives_the_rounded_working(pipeline):
    pipeline.answers(AgentOutcome(text=(
        "1. Lease liability = 50,000 × 3.465106 = 173,255.280635, so the liability and right-of-use asset are "
        "$173,255.28.\n\n2. Dr Right-of-use asset $173,255.28, Cr Lease liability $173,255.28.\n\n"
        "3. An operating lease shows a single straight-line lease cost of $50,000 a year.")))
    response, _ = await pipeline.ask(HARBOR)
    text = response.answer.text
    notes = " ".join(response.answer.limitations)
    assert "173,255.28" in text
    assert "did not match its own calculation" not in notes


async def test_a_wrong_liability_is_still_removed(pipeline):
    pipeline.answers(AgentOutcome(text=(
        "1. Lease liability = 50,000 × 3.465106 = 183,255.28, so the liability is $183,255.28.\n\n"
        "3. An operating lease shows a single straight-line lease cost of $50,000 a year.")))
    response, _ = await pipeline.ask(HARBOR)
    assert "183,255.28" not in (response.answer.text if response.answer else "")
