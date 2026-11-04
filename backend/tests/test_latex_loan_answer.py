r"""Maths notation in a model-composed loan answer (3 Nov 2026) was shown with
"\frac{…} {…}", "[4pt]" and "&≈" left in the text."""
from app.orchestration.answer_formatting import latex_to_plain

LIVE = (r"Monthly payment = \frac{200,000 \times 0.0041666667} {1-(1+0.0041666667)^{-300}} \\[4pt] "
        r"&= \frac{833.3333}{1-(1.0041666667)^{-300}} \\[4pt] &= \frac{833.3333}{1-0.2870} \\[4pt] &\approx £1,169.18")


def test_the_live_loan_formula_is_plain():
    text = latex_to_plain(LIVE)
    for leftover in ("\\frac", "[4pt]", "4pt]", "&", "\\approx", "{", "}"):
        assert leftover not in text, (leftover, text)
    assert "(200,000 × 0.0041666667) ÷ (1-(1+0.0041666667)^-300)" in text
    assert "≈ £1,169.18" in text


def test_a_single_backslash_spacing_command_goes_too():
    assert "pt]" not in latex_to_plain(r"a = 1 \[4pt] b = 2")


def test_ampersands_in_words_stay():
    assert latex_to_plain(r"R&D and Profit & Loss: \( a \times b \)").startswith("R&D and Profit & Loss")
