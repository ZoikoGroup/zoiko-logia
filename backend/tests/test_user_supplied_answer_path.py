"""Answers for questions that carry their own numbers.

A question like "revenue 8.2m against a target of 10m" needs no source: the
figures are the user's own. The RG-03 grounding check correctly found no
citation behind the model's prose and escalated the whole answer to human
review — for a question that never required one. The graph/flow case already
had a bypass (service.py's uses_user_supplied_structure); these are its
numeric twin.

The narration tested here matters as much as the bypass. Calling a user's own
figures "source-grounded observations" claims a provenance they do not have,
which is the same misstatement as presenting a guess as retrieved data — just
pointing the other way.
"""
from __future__ import annotations

import pytest

from app.orchestration.extraction import extract_user_visual_evidence
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.service import _grounded_domain_fallback


def _narrate(query: str) -> str:
    evidence = extract_user_visual_evidence(query, classify_intent(query))
    return _grounded_domain_fallback(query, evidence) or ""


@pytest.mark.parametrize(
    "query, fragments",
    [
        ("revenue 8.2m against a target of 10m",
         ["8,200,000", "10,000,000", "82.0% of target", "short of target"]),
        ("expenses 450k against a budget of 400k",
         ["450,000", "400,000", "112.5% of target", "above target"]),
        ("collections 78% against a target of 90%",
         ["78%", "90%", "86.7% of target"]),
    ],
)
def test_a_gauge_question_is_answered_deterministically(query, fragments):
    text = _narrate(query)
    assert text, "no deterministic answer was produced, so the model's prose would escalate"
    for fragment in fragments:
        assert fragment in text, f"{fragment!r} missing from: {text}"
    assert "supplied in the question" in text


def test_over_target_is_described_as_over_not_short():
    """112.5% of budget is an overspend; wording it as a shortfall would
    invert the finding for anyone skim-reading."""
    text = _narrate("expenses 450k against a budget of 400k")
    assert "above target" in text
    assert "short of target" not in text


def test_gauge_figures_are_never_called_source_grounded():
    text = _narrate("revenue 8.2m against a target of 10m")
    assert "source-grounded" not in text
    assert "not retrieved" in text


@pytest.mark.parametrize(
    "query",
    [
        "show the distribution of invoice processing times as a box plot: 4, 8, 15, 16",
        "create a histogram for these invoice times: 1,2,2,3,3,3,4,5,5,7,8,8,10,12",
    ],
)
def test_a_supplied_sample_is_summarised_honestly(query):
    text = _narrate(query)
    assert text
    assert "supplied in the question" in text
    assert "source-grounded" not in text, (
        "numbers typed into the question are not source-grounded observations"
    )
    # Dimensions are 1, 2, 3… — positions in a list, not periods. The trend
    # wording would read "increased from 4 in 1 to 16 in 4".
    assert "increased from" not in text
    assert "decreased from" not in text


def test_the_sample_subject_does_not_keep_the_chart_name():
    """"show the distribution of invoice times as a box plot" previously left
    a subject of "invoice times as box", which appeared verbatim in the
    answer."""
    text = _narrate(
        "show the distribution of invoice processing times as a box plot: 4, 8, 15, 16"
    )
    assert "invoice processing times" in text
    assert "as box" not in text


@pytest.mark.parametrize(
    "query",
    [
        "create a pie chart: payroll 45%, rent 30%, other 25%",
        "create a donut chart: payroll 45%, rent 30%, other 25%",
        "pie chart of operating expenses: payroll $180,000, rent $55,000, utilities $25,000",
    ],
)
def test_a_supplied_split_is_not_described_as_a_statutory_filing(query):
    """This branch was written for Companies House PSC data and said so in
    every case, so a user's own expense percentages came back as "named
    holders on file" and "filed ownership data" — naming a statutory register
    as the source of figures the reader had just typed."""
    text = _narrate(query)
    assert text
    assert "holders on file" not in text
    assert "filed ownership data" not in text
    assert "given as" in text and "in the question" in text
    assert "not retrieved" in text


def test_a_question_with_no_supplied_data_produces_nothing_here():
    """The bypass must not fire for ordinary questions, or a genuinely
    ungrounded answer would skip the check that exists to catch it."""
    assert _narrate("how is revenue recognised under IFRS 15") == ""
    assert _narrate("what is payroll") == ""
