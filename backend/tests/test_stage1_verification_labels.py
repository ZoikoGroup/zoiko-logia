"""Stage 1 (25 Oct 2026): verification labels, unanswered responses and
internal calculation tags.

- A withheld ASC 606 answer showed "Arithmetic: verified".
- Four US GAAP answers (ASC 350-40, 410-20, 815, 845) had correct sums and a
  wrong treatment, yet read as verified because the arithmetic was.
- "{[calc‑valuation_allowance]}" reached the reader.
"""
import pytest

from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.verification_service import (_TREATMENT_CONTENT, EvidenceFinding, UNSUPPORTED_FINDING_CODES,
                                                    normalize_citations, verification_breakdown)

VAT = calculate_from_query("A UK business sells goods for £1,000 plus VAT at 20%. How much VAT is charged?")
JOURNAL = "Dr Right-of-use asset $85,000; Cr Lease liability $85,000. Recognise the asset at commencement."
CITED = "Recognise the right-of-use asset at commencement [REF-1]. Dr Right-of-use asset $85,000; Cr Lease liability $85,000 [REF-1]."


def test_withheld_answer_reports_nothing_verified():
    status = verification_breakdown(completeness="none", citations=0, limitations=[], calculation=VAT, receipts=2,
                                    answer_text=JOURNAL)
    assert (status.arithmetic, status.treatment, status.overall) == ("not_applicable", "not_applicable", "not_verified")


def test_withheld_answer_still_reports_a_figure_mismatch():
    status = verification_breakdown(completeness="none", citations=0, limitations=[], mismatches=["x"])
    assert status.arithmetic == "mismatch"


def test_unsourced_treatment_is_not_verified_even_with_correct_arithmetic():
    status = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=VAT,
                                    answer_text=JOURNAL)
    assert (status.arithmetic, status.treatment) == ("verified", "not_verified")
    assert status.overall == "partially_verified"


def test_treatment_finding_is_an_issue():
    status = verification_breakdown(completeness="partial", citations=0, limitations=[], calculation=VAT,
                                    treatment=["finding"], answer_text=JOURNAL)
    assert status.treatment == "issue_found"
    assert status.overall != "fully_verified"


def test_cited_treatment_with_verified_sources_is_supported():
    status = verification_breakdown(completeness="complete", citations=2, limitations=[], answer_text=CITED)
    # Cited and checked is a citation status, not a verified treatment.
    assert (status.sources, status.treatment, status.overall) == ("verified", "cited_checks_passed",
                                                                  "partially_verified")


def test_citation_after_the_full_stop_counts_for_that_sentence():
    status = verification_breakdown(completeness="complete", citations=1, limitations=[],
                                    answer_text="Recognise revenue over time. [REF-1]")
    assert status.treatment == "cited_checks_passed"


@pytest.mark.parametrize("text", [
    JOURNAL,
    "Recognise revenue over time [REF-1]. Dr Receivables £6,000; Cr Revenue £6,000.",
    "Recognise revenue over time [REF-1].\n\nDr Receivables  6,000\nCr Revenue  6,000",
])
def test_an_uncited_treatment_claim_is_not_verified_beside_a_cited_one(text):
    # Verified sources for one sentence do not cover a claim nobody cited.
    status = verification_breakdown(completeness="complete", citations=1, limitations=[], answer_text=text)
    assert (status.sources, status.treatment, status.overall) == ("verified", "not_verified", "partially_verified")


@pytest.mark.parametrize("text", [
    "The reverse charge applies, so the customer accounts for the £200 VAT.",
    "Revenue recognition happens when control passes; VAT is £200.",
])
def test_a_missed_treatment_no_longer_reads_fully_verified(text):
    status = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=VAT,
                                    answer_text=text)
    assert (status.treatment, status.overall) == ("not_verified", "partially_verified")


def test_partial_sources_do_not_support_the_treatment():
    unsupported = EvidenceFinding(code=sorted(UNSUPPORTED_FINDING_CODES)[0], statement=JOURNAL, refs=("REF-1",),
                                  message="not in the cited source")
    status = verification_breakdown(completeness="complete", citations=2, limitations=[], evidence=[unsupported],
                                    answer_text=JOURNAL)
    assert (status.sources, status.treatment) == ("partial", "not_verified")
    assert status.overall == "partially_verified"


def test_pure_arithmetic_answer_keeps_its_full_verification():
    status = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=VAT,
                                    answer_text="VAT at 20% on £1,000 is £200, so the gross amount is £1,200.")
    assert (status.treatment, status.overall) == ("not_applicable", "fully_verified")


def test_no_state_says_the_treatment_is_verified():
    from typing import get_args
    from app.orchestration.schemas import VerificationBreakdown
    states = set(get_args(VerificationBreakdown.model_fields["treatment"].annotation))
    assert states == {"cited_checks_passed", "not_verified", "issue_found", "not_applicable"}


def test_fully_verified_only_without_a_treatment_claim():
    # The strongest treatment evidence available still leaves the answer partial.
    cited = verification_breakdown(completeness="complete", citations=2, limitations=[], calculation=VAT,
                                   answer_text=CITED)
    plain = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=VAT,
                                   answer_text="VAT at 20% on £1,000 is £200.")
    assert (cited.overall, plain.overall) == ("partially_verified", "fully_verified")


def test_a_detected_issue_stays_distinct_from_partial_verification():
    # Both are "partially_verified" overall; only the finding says something is wrong.
    unverified = verification_breakdown(completeness="complete", citations=0, limitations=[], calculation=VAT,
                                        answer_text=JOURNAL)
    flagged = verification_breakdown(completeness="partial", citations=0, limitations=[], calculation=VAT,
                                     treatment=["finding"], answer_text=JOURNAL)
    assert (unverified.overall, unverified.treatment) == ("partially_verified", "not_verified")
    assert (flagged.overall, flagged.treatment) == ("partially_verified", "issue_found")


def test_internal_calculation_tags_are_removed():
    assert normalize_citations("Allowance = $500,000 {[calc‑valuation_allowance]}", set()) == "Allowance = $500,000"
    assert normalize_citations("Total $14,000 [calc-3].", set()) == "Total $14,000."
    assert normalize_citations("Interest [calc_interest] is $900.", set()) == "Interest is $900."


def test_reader_visible_brackets_are_kept():
    assert normalize_citations("See [REF-1].", {"REF-1"}) == "See [REF-1]."
    assert normalize_citations("VAT [calculate result £6,486] is due.", set()) == "VAT £6,486 is due."
    assert normalize_citations("Total [calculated: £1,200].", set()) == "Total £1,200."
    assert normalize_citations("Total [Calculation = 1,200].", set()) == "Total 1,200."


@pytest.mark.parametrize("text", ["Use the [calculator] tab.", "Open [Calculations] in the menu.",
                                  "See [calculation basis].", "[Calculated using HMRC rates]"])
def test_reader_text_in_calculation_brackets_is_kept(text):
    # These were deleted by the earlier "[calculat…]" rule (found 25 Oct 2026).
    assert normalize_citations(text, set()) == text


# Reviewed 25 Oct 2026: the first list states only arithmetic or a plain
# meaning of the word; the second makes an accounting or tax claim.
NO_TREATMENT = [
    "The credit sale is £5,000 plus VAT of £1,000, so the customer owes £6,000.",
    "A 2% credit card fee on £3,000 is £60.",
    "On 30-day credit terms, the £1,200 is due by 30 November.",
    "The credit note for £500 plus VAT of £100 totals £600.",
    "GST of 18% on ₹10,000 is ₹1,800, so the input tax credit is ₹1,800.",
    "The R&D tax credit of 10% on £50,000 is £5,000.",
    "Revenue from the facial recognition software was £40,000; costs were £25,000, so profit is £15,000.",
    "The provision of services worth £2,000 plus VAT at 20% gives VAT of £400.",
    "With a deferred payment of £1,000 in 12 months at 5%, the present value is £952.38.",
    "Dr. Smith's invoice is £1,000 plus VAT of £200, and the credit terms are 30 days.",
    "Total credit of £600 against a debit balance of £1,000 leaves £400.",
    "The customer recognised the invoice total of £1,200 as correct.",
]
TREATMENT = [
    "You can claim input tax credit on this purchase because it is used for business.",
    "The business can recover the £200 input VAT because the goods are used for taxable supplies.",
    "ITC is blocked on motor vehicles under section 17(5).",
    "Dr Trade receivables £6,000; Cr Revenue £5,000; Cr VAT payable £1,000.",
    "Dr Trade receivables  6,000\nCr Revenue  5,000",
    "Debit the bank account and credit sales revenue.",
    "Post the following journal entry at 31 December.",
    "Recognise revenue over time as the service is delivered.",
    "Revenue recognition happens when control passes to the customer.",
    "The recognition of the lease liability starts at commencement.",
    "The development cost is recognised as an intangible asset.",
    "Make a provision of £10,000 for the warranty obligation.",
    "A provision for doubtful debts of £2,000 is required.",
    "The £6,000 is deferred revenue until January.",
    "Annual straight-line depreciation is (£50,000 − £5,000) / 5 = £9,000.",
    "Under IFRS 16 the lessee recognises a right-of-use asset.",
    "These supplies are exempt, so no VAT is charged.",
    "The reverse charge applies, so the customer accounts for the VAT.",
    "Children's clothing is zero-rated, so the VAT is £0.",
    "Record an accrual of £4,800 for the electricity.",
]


@pytest.mark.parametrize("text", NO_TREATMENT)
def test_arithmetic_wording_is_not_a_treatment_claim(text):
    assert _TREATMENT_CONTENT.search(text) is None


@pytest.mark.parametrize("text", TREATMENT)
def test_treatment_claims_are_detected(text):
    assert _TREATMENT_CONTENT.search(text) is not None
