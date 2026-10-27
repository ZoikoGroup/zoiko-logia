"""Pasted text is checked claim by claim: each claim searched and judged on
its own evidence, one verdict per claim, nothing free-written."""
import pytest

from app.orchestration import claim_verification, review_mode
from app.orchestration.review_mode import CORRECT, INCORRECT, UNVERIFIED, is_review_request, review_pasted_text
from app.orchestration.websearch import WebSource
from tests.test_long_input_and_block_reasons import PASTED_REVIEW

CLAIMS = [
    "IFRS 18 replaces IAS 1.",
    "IFRS 18 is effective for annual reporting periods beginning on or after 1 January 2025.",
    "IAS 1 requires comparative information for the preceding period.",
]
PAGES = {
    CLAIMS[0]: WebSource(title="IFRS 18", url="https://www.ifrs.org/ifrs-18", snippet="IFRS 18 replaces IAS 1."),
    CLAIMS[1]: WebSource(title="IFRS 18 effective date", url="https://www.ifrs.org/ifrs-18-effective",
                         snippet="IFRS 18 is effective for periods beginning on or after 1 January 2027."),
}


@pytest.fixture
def stubbed(monkeypatch):
    async def extract(material):
        return list(CLAIMS)

    async def search(claim, jurisdiction="", limit=5, read_pages=2):
        return [PAGES[claim]] if claim in PAGES else []

    async def judge(claims, evidence, question=""):
        claim = claims[0]
        if "2025" in claim:
            return claim_verification.VerificationResult(
                checked=1, ran=True, rejected_ids=[1],
                contradicted=[claim_verification.Contradiction(claim, "effective from 1 January 2027")])
        ref = evidence[0][1:evidence[0].index("]")]
        return claim_verification.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1: [ref]})

    async def no_official(claim):
        return []

    monkeypatch.setattr(review_mode, "_official_excerpts", no_official)
    monkeypatch.setattr(review_mode, "extract_review_claims", extract)
    monkeypatch.setattr(review_mode, "web_search", search)
    monkeypatch.setattr(claim_verification, "verify_claims", judge)


def test_a_pasted_text_with_a_check_instruction_is_a_review_request():
    assert is_review_request(PASTED_REVIEW)  # ends "comment on the above"
    assert is_review_request("check if this is correct:\n\n" + PASTED_REVIEW.replace("comment on the above", ""))
    assert not is_review_request("Check if IFRS 18 replaces IAS 1")       # a short question
    assert not is_review_request(PASTED_REVIEW.replace("comment on the above", "summarise this"))


async def test_each_claim_gets_its_own_verdict_and_source(stubbed):
    review = await review_pasted_text(PASTED_REVIEW)
    assert [v.verdict for v in review.verdicts] == [CORRECT, INCORRECT, UNVERIFIED]
    assert review.counts == {CORRECT: 1, review_mode.PARTLY: 0, INCORRECT: 1, UNVERIFIED: 1}
    # Named links: the answer view strips [REF-n] markers, which blanked the column.
    assert "| 1 | IFRS 18 replaces IAS 1. | **Correct** | [IFRS 18](https://www.ifrs.org/ifrs-18) |" in review.text
    assert "the source says: effective from 1 January 2027 ([IFRS 18 effective date](https://www.ifrs.org/ifrs-18-effective))" in review.text
    assert "[REF-" not in review.text
    assert "| 3 | IAS 1 requires comparative information for the preceding period. | **Could not verify** | — |" in review.text
    # Only sources a verdict rests on are cited, numbered as shown.
    assert [s.url for s in review.sources] == ["https://www.ifrs.org/ifrs-18", "https://www.ifrs.org/ifrs-18-effective"]


async def test_text_without_checkable_claims_falls_back_to_the_normal_pipeline(monkeypatch):
    async def none(material):
        return []
    monkeypatch.setattr(review_mode, "extract_review_claims", none)
    assert await review_pasted_text(PASTED_REVIEW) is None


async def test_a_verifier_outage_marks_claims_unverified_not_correct(monkeypatch, stubbed):
    async def down(claims, evidence, question=""):
        return claim_verification.VerificationResult()
    monkeypatch.setattr(claim_verification, "verify_claims", down)
    review = await review_pasted_text(PASTED_REVIEW)
    assert {v.verdict for v in review.verdicts} == {UNVERIFIED}
    assert review.sources == []


def test_table_cells_cannot_break_the_table():
    assert review_mode._cell("a | b\nc") == "a \\| b c"


async def test_the_official_standard_text_is_checked_first(monkeypatch, stubbed):
    official = WebSource(title="IAS 1 — official text (IFRS Foundation)", url="https://www.ifrs.org/ias1.html",
                         snippet="An entity shall present comparative information in respect of the preceding period.")

    async def standard(claim):
        return [official] if "IAS 1" in claim else []
    monkeypatch.setattr(review_mode, "_official_excerpts", standard)
    review = await review_pasted_text(PASTED_REVIEW)
    assert review.verdicts[2].verdict == CORRECT
    assert "https://www.ifrs.org/ias1.html" in [s.url for s in review.sources]
    # Claims naming IAS 1 (1 and 3) rest on the official text, listed first in their evidence.
    assert review.verdicts[0].refs == review.verdicts[2].refs


async def test_a_contradiction_that_only_says_the_evidence_is_silent_is_unverified(monkeypatch, stubbed):
    async def silent(claims, evidence, question=""):
        return claim_verification.VerificationResult(checked=1, ran=True, rejected_ids=[1], contradicted=[
            claim_verification.Contradiction(claims[0], "The evidence does not mention IAS 8 or IFRS 7.")])
    monkeypatch.setattr(claim_verification, "verify_claims", silent)
    review = await review_pasted_text(PASTED_REVIEW)
    assert INCORRECT not in {v.verdict for v in review.verdicts}


async def test_a_source_stating_a_shorter_form_of_the_rule_is_partly_confirmed(monkeypatch, stubbed):
    from app.orchestration.review_mode import PARTLY

    says = {CLAIMS[0]: "IFRS 18 replaces IAS 1",                       # part of the claim, nothing new
            CLAIMS[1]: "IFRS 18 is effective from 1 January 2027"}     # a different date

    async def judge(claims, evidence, question=""):
        return claim_verification.VerificationResult(checked=1, ran=True, rejected_ids=[1], contradicted=[
            claim_verification.Contradiction(claims[0], says.get(claims[0], ""))])
    monkeypatch.setattr(claim_verification, "verify_claims", judge)
    review = await review_pasted_text(PASTED_REVIEW)
    assert review.verdicts[0].verdict == PARTLY
    assert review.verdicts[1].verdict == INCORRECT
    assert "### Partly confirmed" in review.text and "### Corrections" in review.text


PASTED_TABLES = "\n".join([
    "2. Cost-side totals",
    "| Category | Total cost | % of total cost |",
    "| --- | --- | --- |",
    "| Plant and machinery | 143,700 | 22.92 % |",
    "| Motor vehicles | 152,400 | 24.31 % |",
    "| **TOTAL** | **300,000** | **47.23 %** |",
    "Copy table",
    "Category\tNet book value",
    "Fixtures\t90,700",
    "IT equipment\t45,966.66",
    "TOTAL\t136,666.66",
    "",
    "comment on the above",
])


def test_the_totals_of_pasted_tables_are_added_up():
    checks = review_mode.figure_checks(PASTED_TABLES)
    assert checks == [
        "❌ **Total cost**: the 2 rows add up to 296,100, but the stated total is 300,000 (difference 3,900).",
        "✅ **% of total cost**: the 2 rows add up to 47.23, matching the stated total 47.23 %.",
        "✅ **Net book value**: the 2 rows add up to 136,666.66, matching the stated total 136,666.66.",
    ]


async def test_a_text_with_no_rule_claims_still_gets_its_totals_checked(monkeypatch):
    async def none(material):
        return []
    monkeypatch.setattr(review_mode, "extract_review_claims", none)
    review = await review_pasted_text(PASTED_TABLES)
    assert review.verdicts == [] and review.sources == []
    assert review.text.startswith("I added up the rows of each table with a total: 2 total(s) match, 1 do not.")
    assert "I checked 0 factual claims" not in review.text


def test_a_request_to_produce_an_analysis_is_not_a_claim_check():
    brief = ("Act as a senior management accountant analysing the following fictional company. Prepare a "
             "decision-ready financial performance review for the board.\n\n" + "Revenue rose. " * 200
             + "\n\nVALIDATION REQUIREMENTS\n- Check the arithmetic independently.")
    assert not is_review_request(brief)
    assert not is_review_request("Overall impression\n\n" + "Margins fell. " * 200 + "\n\nsummarise this in 5 points")
    assert is_review_request("Overall impression\n\n" + "Margins fell. " * 200 + "\n\ncheck if it is correct.")
