"""Fixes from the 29 Oct 2026 twelve-question re-test.

A. Kestrel ("reports under IFRS") was marked partial: the lease calculator did
   not read "IFRS" as IFRS 16, added its IFRS-or-ASC-842 note, and the
   framework check cut the ASC 842 sentence. The calculator now reads the
   framework with the same families as the framework check.
B. Marlow was "may be out of date": "Revenue = £72,000 + £18,000 = £90,000"
   builds on the allocation the line before and, judged alone, looked like an
   outside figure. The user's own figures are now judged across the answer.
E. Harbourview gave the going concern indicators (as a labelled general
   explanation) and was still told "requested parts remain unanswered:
   going concern indicators". Completeness is judged on the final text.
No model, database or network.
"""
import pytest

from app.orchestration.calculations.lease import _lease_framework, lease_calculation
from app.orchestration.claim_verification import VerificationResult
from app.orchestration.finalisation import answered_as_general_explanation
from app.orchestration.verification_service import _mostly_unconfirmed_outside_question

KESTREL = ("Kestrel Logistics Ltd reports under IFRS. On 1 January 2026 it leased a depot for 5 years. Annual payments "
           "of £24,000 are paid at the end of each year, and the interest rate implicit in the lease is 7%. "
           "Calculate the initial lease liability.")


# A ----------------------------------------------------------------------------

@pytest.mark.parametrize("text, framework", [
    ("Kestrel reports under IFRS.", "IFRS 16"), ("We report under Ind AS.", "IFRS 16"),
    ("A US GAAP company (ASC 842).", "ASC 842"), ("Compare IFRS 16 and ASC 842.", None), ("No framework.", None),
    ("A UK company under FRS 102.", None),
])
def test_the_lease_model_follows_the_named_framework(text, framework):
    assert _lease_framework(text) == framework


def test_an_ifrs_lease_carries_no_other_frameworks_note():
    result = lease_calculation(KESTREL)
    assert result.outputs[0].display_value == "£98,404.74"
    assert not [note for note in result.notes if "ASC 842" in note or "was not stated" in note]


# B ----------------------------------------------------------------------------

QUESTION = ("Marlow Fitness plc reports under IFRS. It sold gym equipment with installation for a single price of "
            "£90,000. Marlow sells the equipment alone for £80,000 and installation alone for £20,000. "
            "Allocate the £90,000 under IFRS 15 and state the revenue recognised by 31 October 2026.")
ANSWER = ("Equipment £90,000 × (£80,000) ÷ (£80,000+£20,000)=£72,000\n"
          "Installation £90,000 × (£20,000) ÷ (£80,000+£20,000)=£18,000\n"
          "Revenue recognised by 31 October 2026 = £72,000 (equipment) + £18,000 (installation) = £90,000.")


def test_figures_built_on_the_answers_own_working_are_the_users():
    claims = ANSWER.splitlines()
    verdict = VerificationResult(checked=3, not_in_evidence=3, ran=True, rejected_ids=[1, 2, 3])
    assert not _mostly_unconfirmed_outside_question(claims, verdict, QUESTION, ANSWER)


def test_an_outside_figure_still_counts():
    claims = ["The IFRS 15 effective date was 1 January 2018 with a £5,000 threshold.",
              "Contract costs above £15,000 must be capitalised.", ANSWER.splitlines()[0]]
    verdict = VerificationResult(checked=3, not_in_evidence=2, ran=True, rejected_ids=[1, 2])
    assert _mostly_unconfirmed_outside_question(claims, verdict, QUESTION, "\n".join(claims))


# E ----------------------------------------------------------------------------

def test_a_part_given_as_a_general_explanation_is_answered():
    final = ("1. Going‑concern indicators General explanation: Indicators include a significant decline in revenue, "
             "the loss of a major customer and the expiry of a financing facility.\n\n2. Auditor's responsibilities …")
    assert answered_as_general_explanation("going concern indicators", final)


def test_a_part_not_in_the_answer_is_still_unanswered():
    final = "1. General explanation: Indicators include a decline in revenue.\n\n2. The auditor's responsibilities …"
    assert not answered_as_general_explanation("stay conditions for the first appeal", final)
    assert not answered_as_general_explanation("going concern indicators", "Going concern indicators: see the notes.")
