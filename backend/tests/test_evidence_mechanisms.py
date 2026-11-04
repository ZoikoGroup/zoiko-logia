"""System-wide evidence mechanisms (3 Nov 2026): a page's structured
question-and-answer data is read (GOV.UK publishes every part of a guide
there), and a figure the cited source states only for the opposite rule does
not support a statement (the joining limit cited for when a business must
leave the VAT Cash Accounting Scheme)."""
import pytest

from app.orchestration.verification_service import _figure_for_other_rule, evidence_findings
from app.orchestration.websearch import _html_to_text, structured_answers

GUIDE = '''<html><head><script type="application/ld+json">{"@type":"FAQPage","mainEntity":[
{"@type":"Question","name":"Join or leave the scheme","acceptedAnswer":{"@type":"Answer","text":
"<p>You can join if your VAT taxable turnover is &pound;1.35 million or less.</p><p>You must leave the scheme if your VAT taxable turnover is more than £1.6 million.</p>"}}]}</script>
<script type="application/ld+json">{"@type":"Organization","name":"GOV.UK publishing service"}</script></head>
<body><h1>VAT Cash Accounting Scheme</h1><p>To join the scheme your VAT taxable turnover must be £1.35 million or less.</p></body></html>'''


def test_a_guides_structured_answers_are_read():
    text = _html_to_text(GUIDE)
    assert "You must leave the scheme if your VAT taxable turnover is more than £1.6 million" in text
    assert "Organization" not in text and "publishing service" not in text


def test_broken_or_absent_structured_data_changes_nothing():
    assert structured_answers("<script type='application/ld+json'>{not json</script><p>x</p>") == []
    assert _html_to_text("<p>Plain page.</p>") == "Plain page."


SOURCE = ("To join the scheme your VAT taxable turnover must be £1.35 million or less. "
          "You must leave the scheme if your VAT taxable turnover is more than £1.6 million.")


@pytest.mark.parametrize("statement, figure, mismatch", [
    ("If turnover exceeded £1.35 million, the business must leave the scheme.", "£1.35 million", ("leaving", "joining")),
    ("A business must leave the scheme if its turnover is more than £1.6 million.", "£1.6 million", None),
    ("A business can join if turnover is £1.35 million or less.", "£1.35 million", None),
])
def test_a_figure_for_the_opposite_rule(statement, figure, mismatch):
    assert _figure_for_other_rule(statement, figure, SOURCE) == mismatch


def test_employer_and_employee_rates_are_not_interchangeable():
    source = "Employers pay secondary Class 1 contributions at 15%. Employees pay 8% on earnings above the threshold."
    assert _figure_for_other_rule("The employee rate is 15%.", "15%", source) == ("employees", "employers")
    assert _figure_for_other_rule("The employer rate is 15%.", "15%", source) is None


def test_the_finding_reaches_the_evidence_review():
    answer = "If VAT taxable turnover exceeded £1.35 million, the business must leave the scheme [REF-1]."
    findings = evidence_findings(answer, question="When must a business leave the VAT Cash Accounting Scheme?",
                                 evidence_by_ref={"REF-1": SOURCE}, citations=[])
    assert any(f.code == "figure_for_other_rule" for f in findings), findings
