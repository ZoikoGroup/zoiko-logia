"""Stage 4: strict-mode arithmetic exemption (27 Oct 2026).

Test definitions agreed before implementation:
~/kriton-backups/2026-10-27-remediation2/stage4-test-definitions.md

In strict mode (a question naming a standard, a rate or a rule), an uncited
statement was removed as "missing citation" even when it only did arithmetic
on the user's own figures: "Gross profit is £300,000." for revenue £800,000
and cost of sales £500,000 was removed, while "Gross profit = £800,000 −
£500,000 = £300,000." was kept. Such a statement is now kept only when every
figure is the user's or correct arithmetic from them, it asserts no rate,
rule, threshold, standard, obligation or accounting treatment, and no
figure comes from outside the user's text. Never exempted because some
figures came from the user. No model, database or network: every claim
here is uncited, so the model judge is never called.
"""
import asyncio

import pytest

from app.orchestration.calculation_service import validate_answer_calculations
from app.orchestration.verification_service import _verify_authoritative_answer

Q = "Under IFRS 15, revenue £800,000 and cost of sales £500,000. What is the gross profit and margin?"
EVIDENCE = ["[REF-1] IFRS 15 Revenue from Contracts with Customers: revenue is recognised when control transfers."]


@pytest.fixture(autouse=True)
def _claim_checks_on_without_a_model(monkeypatch):
    from app.orchestration import claim_verification

    async def no_model(*_args, **_kwargs):
        raise AssertionError("the model judge must not be called: every claim here is uncited")

    monkeypatch.setattr(claim_verification, "enabled", lambda: True)
    monkeypatch.setattr(claim_verification, "verify_claims", no_model)


def _verify(answer, question=Q, requires_authority=True):
    return asyncio.run(_verify_authoritative_answer(
        answer, question=question, evidence=EVIDENCE, requires_authority=requires_authority))


# --- P: arithmetic on the user's figures is kept ---

@pytest.mark.parametrize("answer, question", [
    pytest.param("Gross profit is £800,000 − £500,000 = £300,000.", Q, id="P1-is-equation"),
    pytest.param("Gross profit is £300,000.", Q, id="P2-result"),
    pytest.param("The gross margin is 37.5%.", Q, id="P3-margin"),
    pytest.param("| Item | Amount |\n|---|---|\n| Revenue | £800,000 |\n| Cost of sales | £500,000 |\n"
                 "| Gross profit | £300,000 |", Q, id="P4-table"),
    pytest.param("Revenue of £800,000 less cost of sales of £500,000 gives gross profit of £300,000.", Q,
                 id="P5-sentence"),
    # The step's operand is in the same sentence: the figure check traces a
    # step only from a figure the same statement shows.
    pytest.param("Gross profit is £300,000, so operating profit is £180,000.",
                 Q.replace("£500,000.", "£500,000, overheads £120,000."), id="P6-two-steps"),
    pytest.param("VAT at 20% on £300,000 is £60,000.", Q + " Apply VAT at 20% to the gross profit.",
                 id="P8-user-rate"),
])
def test_arithmetic_on_user_figures_is_kept(answer, question):
    result = _verify(answer, question)
    assert result.passed, result.failures
    assert result.rejected_claims == []


def test_P7_mixed_answer_prunes_only_the_rule():
    rule = "Under IFRS 15 the revenue must be recognised over time."
    result = _verify(f"Gross profit is £300,000. {rule}")
    assert not result.passed
    assert result.rejected_claims == [rule]
    assert result.prunable


# --- N: never exempted because some figures came from the user ---

@pytest.mark.parametrize("answer, question", [
    pytest.param("The UK corporation tax rate is 25%, so tax = £300,000 × 25% = £75,000.", Q, id="N1-rate"),
    pytest.param("The UK corporation tax rate is 25%, so tax = £300,000 × 25% = £75,000.",
                 Q + " Use tax at 25%.", id="N1b-rate-as-law"),
    pytest.param("Under IFRS 15 the revenue must be recognised over time.", Q, id="N2-standard"),
    pytest.param("The industry average gross margin is 42%.", Q, id="N3-external"),
    pytest.param("Gross profit is £310,000.", Q, id="N5-not-derived"),
    pytest.param("Recognise revenue of £800,000 in the year.", Q, id="N6-treatment"),
    pytest.param("Dr Receivables £800,000 and Cr Revenue £800,000 on delivery.", Q, id="N6-journal"),
    pytest.param("Gross profit is £300,000, which is above the VAT threshold of £90,000.", Q, id="N7-statutory"),
    pytest.param("The standard VAT rate is 20%.", Q + " Apply VAT at 20% to the gross profit.", id="N8-rule"),
    pytest.param("The company must pay £75,000 to HMRC.", Q + " Use tax at 25%.", id="N9-obligation"),
])
def test_rules_rates_and_outside_facts_are_still_rejected(answer, question):
    result = _verify(answer, question)
    assert not result.passed
    assert result.rejected_claims


# Found by the existing suite while implementing (27 Oct 2026): a first
# version released both of these.
@pytest.mark.parametrize("answer, question", [
    pytest.param("Yes, it is correct: the rate is 6.5%.", "Is the current repo rate at 6.5%?",
                 id="N11-confirms-outside-fact"),
    pytest.param("Ask the company's auditor how to treat the £120,000 before the year end.",
                 "A customer paid £120,000 for a 12-month service under IFRS 15. How is it recognised?",
                 id="N12-repeats-user-figure-only"),
    pytest.param("The £120,000 is recognised on day one.",
                 "A customer paid £120,000 for a 12-month service under IFRS 15. How is it recognised?",
                 id="N12b-repeats-user-figure-as-treatment"),
])
def test_repeating_or_confirming_user_figures_is_not_arithmetic(answer, question):
    result = _verify(answer, question)
    assert not result.passed and result.rejected_claims == [answer]


def test_N4_wrong_arithmetic_is_flagged_and_not_exempted():
    wrong = "Gross profit is £800,000 − £500,000 = £350,000."
    assert validate_answer_calculations(wrong)
    assert not _verify(wrong).passed


def test_N10_non_strict_mode_is_unchanged():
    for answer in ("Gross profit is £300,000.", "The industry average gross margin is 42%."):
        assert _verify(answer, requires_authority=False).passed
