"""Task Contract, Stage D follow-up (29 Oct 2026 live re-test).

1. Brightwater (an IFRS company, asked about ISA (UK) 570 and 240) was
   withheld whole as "content from another accounting framework": its
   sources were ISA (UK) pages published by the FRC, and "FRC" counted as
   UK GAAP. Auditing standards are not an accounting framework.
2. One statement from another framework replaced the whole answer. Now that
   statement is removed and the rest stays (finalisation.py, P3); an answer
   with nothing else left is still withdrawn.
3. CloudLedger, fully and correctly answered, was "Partially answered —
   figures may be out of date": its figures were calculated from the user's
   own and are in no source. They no longer count as unconfirmed.
4. "Noted" cut the period off: "year ended 31 March 2026 it reported reve".
No model, database or network.
"""
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

from app.orchestration.claim_verification import VerificationResult
from app.orchestration.finalisation import ValidationFinding, remove_statements
from app.orchestration.framework_scope import (
    FRAMEWORK_GAP, FRAMEWORK_REMOVED_NOTE, foreign_framework_statements, framework_families,
)
from app.orchestration.message_intent import context_facts
from app.orchestration.verification_service import _mostly_unconfirmed_outside_question

BRIGHTWATER = ("Brightwater Hotels plc owns 12 hotels and reports under IFRS.\n\nRequired:\n"
               "1. Explain the auditor's responsibilities under ISA (UK) 570.")
ISA_SOURCE = N(ref_id="REF-1", title="ISA (UK) 570 (Revised September 2019) Going Concern - FRC",
               framework="", evidence_preview="")


# 1 ----------------------------------------------------------------------------

def test_an_auditing_standard_is_not_an_accounting_framework():
    assert framework_families("ISA (UK) 570 (Revised) Going Concern - FRC") == set()
    assert foreign_framework_statements(
        BRIGHTWATER, "Under ISA (UK) 570 the auditor evaluates management's going concern assessment [REF-1].",
        [ISA_SOURCE]) == []


def test_uk_gaap_is_still_another_framework_for_an_ifrs_question():
    assert framework_families("FRS 102 Section 20 Leases - FRC") == {"UK GAAP"}
    assert foreign_framework_statements(
        "Explain IFRS 16 lease accounting.", "Under FRS 102 Section 20 a lessee expenses operating lease payments.")


# 2 ----------------------------------------------------------------------------

def _finding(statement: str) -> ValidationFinding:
    return ValidationFinding(category="accounting_treatment", rule="framework_mismatch",
                             action="remove_statement", expression=statement)


def test_one_foreign_statement_is_removed_and_the_rest_stays():
    answer = ("Going concern indicators: falling occupancy and the covenant breach.\n\n"
              "Under FRS 102 Section 32 events after the reporting period are disclosed.")
    kept = remove_statements(answer, [_finding("Under FRS 102 Section 32 events after the reporting period are disclosed.")],
                             FRAMEWORK_REMOVED_NOTE)
    assert "falling occupancy" in kept and "FRS 102" not in kept


def test_an_answer_with_nothing_else_is_still_withdrawn():
    answer = "### Applicable conditions\nIAS 37 requires recognition when a present obligation exists."
    assert remove_statements(answer, [_finding("IAS 37 requires recognition when a present obligation exists.")],
                             FRAMEWORK_REMOVED_NOTE) == ""
    assert FRAMEWORK_GAP          # the caller shows this, as before


# 3 ----------------------------------------------------------------------------

QUESTION = ("UK company, standard-rated sales of £240,000 and standard-rated purchases of £90,000; all figures exclude "
            "VAT and VAT is 20%. Calculate the VAT payable.")


def test_figures_calculated_from_the_users_own_are_not_unconfirmed():
    claims = ["Output VAT = £240,000 × 20% = £48,000.", "Input VAT = £90,000 × 20% = £18,000.",
              "VAT payable = £48,000 − £18,000 = £30,000."]
    verdict = VerificationResult(checked=3, not_in_evidence=3, ran=True, rejected_ids=[1, 2, 3])
    assert verdict.mostly_unconfirmed
    assert not _mostly_unconfirmed_outside_question(claims, verdict, QUESTION)


def test_outside_figures_absent_from_the_sources_still_get_the_note():
    claims = ["The flat rate scheme percentage for software is 14.5%.", "The deregistration threshold is £88,000.",
              "VAT payable = £48,000 − £18,000 = £30,000."]
    verdict = VerificationResult(checked=3, not_in_evidence=2, ran=True, rejected_ids=[1, 2])
    assert _mostly_unconfirmed_outside_question(claims, verdict, QUESTION)


# 4 ----------------------------------------------------------------------------

def test_the_period_ends_at_its_date():
    text = "Northwind reports under FRS 102. For the year ended 31 March 2026 it reported revenue of £48 million."
    assert context_facts(text).period == ["year ended 31 March 2026"]
    assert context_facts("Period: FY2025.").period == ["FY2025"]
