"""Fourth 28 Oct 2026 live re-test: two leases in one message.

"Calculate the lease liability for payments of £10,000 a year at 5% for 3
years. … We lease a van: annual payments of £8,000 in arrears …", sent as one
message, was calculated as one lease with the van's "in arrears": a timing
never stated for the £10,000 lease. A message with a £12,000 lease in advance
and a ₹6,00,000 lease in arrears asked "advance or arrears?" instead of which
lease. Separate messages were already kept apart (round 5); within one
message they were mixed. No model, database or network.
"""
import pytest

from app.orchestration.calculations.lease import lease_calculation, leases_in_message
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

TEN = "Calculate the lease liability for payments of £10,000 a year at 5% for 3 years."
VAN = "We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years."
TWELVE = "Calculate the IFRS 16 lease liability: annual payments of £12,000 in advance, discount rate 6%, lease term 5 years."
OFFICE = "We lease office space: annual payments of ₹6,00,000 in arrears, discount rate 9%, lease term 3 years."


@pytest.mark.parametrize("message", [
    f"{TEN}\nWhen it asks advance or arrears, send {VAN}",
    f"{TWELVE}\nWe are an Indian company reporting under Ind AS for the year ending 31 March 2026.\n{OFFICE}\n"
    "Now calculate the lease liability for that lease.",
    f"{TWELVE} {OFFICE} Calculate both.",
])
def test_two_leases_in_one_message_are_asked_about_not_mixed(message):
    result = lease_calculation(message)
    assert result.status == "clarification_required" and result.error_code == "AMBIGUOUS_REFERENCE"
    assert result.message.startswith("Your message describes more than one lease")
    assert not result.outputs


@pytest.mark.parametrize("message, liability", [
    (f"{VAN}\nCorrection: the lease term is 4 years, not 3.\nNow calculate the lease liability for that lease.",
     "£28,367.60"),
    ("Calculate the lease liability: annual payments of £30,000 in arrears, discount rate 6%, lease term 5 years. "
     "Total payments of £150,000 will be made.", "£126,370.91"),
    ("Annual payments of £30,000 are made in arrears. Calculate the lease liability for payments of £30,000 at 6% "
     "for 5 years.", "£126,370.91"),
])
def test_one_lease_in_a_message_is_still_calculated(message, liability):
    result = lease_calculation(message)
    assert result.status == "success" and result.outputs[0].display_value == liability


def test_a_payment_without_terms_of_its_own_is_not_a_second_lease():
    assert len(leases_in_message("Annual payments of £30,000 in arrears at 6% for 5 years. "
                                 "Total payments of £150,000.")) == 1


async def test_the_question_reaches_the_user(pipeline):
    response, _ = await pipeline.ask(f"{TEN}\nWhen it asks advance or arrears, send {VAN}")
    assert response.outcome == "clarification_required"
    assert "more than one lease" in response.next_action.message
    assert response.calculation is None or not response.calculation.outputs
