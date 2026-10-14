"""Exact citation spans (ZL-ENG-AGT-01 §06.4)."""
from app.orchestration.citation_spans import evidence_by_ref, exact_spans

PASSAGE = ("Overview. You must register for VAT if your total VAT taxable turnover for the last 12 months "
           "was over £90,000. You can also register voluntarily. The flat rate is 16.5% for limited cost traders.")


def test_a_cited_claim_resolves_to_the_exact_supporting_sentence():
    spans = exact_spans("The registration threshold is £90,000 of taxable turnover over 12 months [REF-1].",
                        {"REF-1": PASSAGE})
    [span] = spans["REF-1"]
    assert PASSAGE[span["start"]:span["end"]].strip().startswith("You must register for VAT")
    assert "£90,000" in PASSAGE[span["start"]:span["end"]]


def test_decimals_do_not_split_a_sentence():
    [span] = exact_spans("Limited cost traders use a flat rate of 16.5% [REF-1].", {"REF-1": PASSAGE})["REF-1"]
    assert "16.5%" in PASSAGE[span["start"]:span["end"]]


def test_an_unsupported_claim_gets_no_span_rather_than_a_wrong_one():
    assert exact_spans("Corporation tax is 25% on profits [REF-1].", {"REF-1": PASSAGE}) == {}


def test_evidence_lines_are_read_by_reference():
    assert evidence_by_ref(["[REF-2] Text two.", "[REF-2] duplicate", "no ref"]) == {"REF-2": "Text two."}


def test_steps_are_renumbered_after_unsupported_ones_are_removed():
    from app.orchestration.answer_formatting import renumber_ordered_lists
    pruned = "**Steps**\n\n2. Enter outward supplies.\n3. Enter ITC.\n\n5. Save.\n7. Submit by the 20th.\n\nNotes\n4. Check registration."
    assert renumber_ordered_lists(pruned) == (
        "**Steps**\n\n1. Enter outward supplies.\n2. Enter ITC.\n\n3. Save.\n4. Submit by the 20th.\n\nNotes\n1. Check registration."
    )
