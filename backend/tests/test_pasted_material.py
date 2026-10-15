"""Pasted material plus a short instruction: the instruction, not the words
inside the material, decides whether statutory sources are required."""
from app.orchestration.pasted_material import review_instruction
from app.orchestration.verification_service import requires_authoritative_evidence

REPORT = "\n".join([
    "## Payroll Register — Payroll Statement",
    "| Particulars | Amount |", "| --- | --- |",
    "| Gross Employee Pay | 86,850.00 |", "| PAYE Deducted | 17,370.00 |",
    "| Employee National Insurance | 6,948.00 |", "| Employer National Insurance | 11,985.30 |",
    "VAT should generally be recorded separately from revenue, subject to the applicable tax rules.",
    "PAYE, employee National Insurance, and employee pension deductions are generally amounts withheld "
    "from employees' gross pay and payable to the relevant parties.",
])


def _authority(query: str) -> bool:
    return requires_authoritative_evidence(review_instruction(query) or query)


def test_a_comment_on_a_pasted_report_does_not_need_statutory_sources():
    assert requires_authoritative_evidence(REPORT + "\ncomment on the above")      # the old reading
    for instruction in ("comment on the above", "summarise this in 5 points", "Please review the above",
                        "what do you think of this?", "explain the above in simple terms"):
        assert review_instruction(REPORT + "\n" + instruction) == instruction
        assert not _authority(REPORT + "\n" + instruction), instruction
    assert not _authority("Summarise the following:\n" + REPORT)                   # instruction first


def test_an_instruction_about_tax_still_needs_sources():
    assert _authority(REPORT + "\nCheck the VAT treatment above")
    assert _authority(REPORT + "\nreview the PAYE rules in this")


def test_ordinary_questions_are_unchanged():
    assert review_instruction("What is the VAT registration threshold in the UK?") is None
    assert _authority("What is the VAT registration threshold in the UK?")
    assert review_instruction("Summarise this\nshort\ntext") is None                # no real material
    assert review_instruction(REPORT + "\nWhat is the PAYE threshold for 2026?") is None
    assert _authority(REPORT + "\nWhat is the PAYE threshold for 2026?")
