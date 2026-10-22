"""Explanation gaps are filled; figure, rate and rule gaps are not (gap_filler.py)."""
from unittest.mock import AsyncMock

from app.orchestration.gap_filler import LABEL, explanation_gaps, fill_explanation_gaps

FAILURE = "Kriton is temporarily unable to reach the language model provider."
ANSWER = (
    "The spreadsheet lists each asset with its cost and useful life.\n\n"
    "**Factors that determine depreciation expense** The sources provided do not state the factors that determine it.\n\n"
    "The sources provided do not state the depreciation method that should be applied.\n\n"
    "The sources provided do not state the total depreciation expense for the current year.\n\n"
    "The sources provided do not state the VAT registration threshold."
)


def test_only_explanation_gaps_are_selected():
    gaps = explanation_gaps(ANSWER)
    assert gaps == ["The sources provided do not state the factors that determine it.",
                    "The sources provided do not state the depreciation method that should be applied."]


async def test_gaps_are_filled_with_labelled_explanations_and_figure_gaps_stay():
    reply = ("1. Depreciation depends on the asset's cost, its useful life, any residual value and the method chosen.\n"
             "2. Common methods are straight-line, which spreads cost evenly, and reducing-balance, which charges more early.")
    text, filled = await fill_explanation_gaps(ANSWER, "depreciation journal", AsyncMock(return_value=reply), FAILURE)
    assert filled
    assert f"{LABEL} Depreciation depends on the asset's cost" in text
    assert f"{LABEL} Common methods are straight-line" in text
    assert "do not state the total depreciation expense" in text      # a figure: still a gap
    assert "do not state the VAT registration threshold" in text      # a threshold: still a gap


def test_a_gap_with_eg_or_etc_is_taken_whole():
    text = ("The sources provided do not state the applicable accounting standards (e.g., IAS 16) governing depreciation.\n"
            "The sources provided do not state the depreciation method (straight-line, reducing-balance, etc.) to apply.\n"
            "The sources provided do not state any residual-value assumptions.")
    assert explanation_gaps(text) == text.splitlines()


async def test_an_explanation_with_a_figure_or_a_failure_is_discarded():
    text, filled = await fill_explanation_gaps(ANSWER, "q", AsyncMock(return_value="1. Usually 20% a year.\n2. See [REF-1] for details."), FAILURE)
    assert not filled and text == ANSWER
    text, filled = await fill_explanation_gaps(ANSWER, "q", AsyncMock(return_value=FAILURE), FAILURE)
    assert not filled and text == ANSWER
    assert await fill_explanation_gaps("A complete answer.", "q", AsyncMock(), FAILURE) == ("A complete answer.", False)
