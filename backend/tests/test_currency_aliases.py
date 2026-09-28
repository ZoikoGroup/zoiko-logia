"""Currency spelling — orchestration/frankfurter.py.

The connector could always answer "convert 1100 USD to INR". It could not
answer "convert 1100 dollars to indian rupees", because recognition was
limited to three-letter ISO codes, so a question well within its reach fell
through to a plain web search that had no live rate.

These tests pin the two halves of the fix: the widened spellings, and the
refusal to guess where a name is genuinely ambiguous or the rate genuinely
unavailable.
"""
from __future__ import annotations

import pytest

from app.orchestration.frankfurter import (
    _CURRENCY_CODES,
    _UNSUPPORTED_ALIASES,
    _find_currencies,
    unsupported_currency_note,
)


@pytest.mark.parametrize(
    "query, expected",
    [
        ("convert 1100 dollars to indian rupees", ["USD", "INR"]),
        ("what is 1100 USD in Indian Rupees", ["USD", "INR"]),
        ("convert 500 euros to pounds", ["EUR", "GBP"]),
        ("500 japanese yen to swiss francs", ["JPY", "CHF"]),
        ("1000 mexican pesos in philippine pesos", ["MXN", "PHP"]),
        # Plurals come from the pattern's optional "s", not twin table entries.
        ("convert 100 shekels to euros", ["ILS", "EUR"]),
        # Symbols are how people actually type an amount.
        ("how much is $250 in rupees", ["USD", "INR"]),
        ("convert £100 to ₹", ["GBP", "INR"]),
        # The original code spelling must keep working unchanged.
        ("convert 1100 USD to INR", ["USD", "INR"]),
        ("1100 usd in inr", ["USD", "INR"]),
    ],
)
def test_currencies_are_recognised_however_they_are_spelled(query, expected):
    assert _find_currencies(query) == expected


def test_a_qualifier_beats_the_bare_name():
    """"canadian dollar" is CAD, not USD with a stray word in front.

    Alternation order is the disambiguation here, so this guards the sort that
    puts longer aliases first.
    """
    assert _find_currencies("convert 100 canadian dollars to australian dollars") == ["CAD", "AUD"]
    assert _find_currencies("convert 50 egyptian pounds to dollars") == ["USD"]


@pytest.mark.parametrize(
    "query, expected",
    [
        # "try" and "php" are ordinary words far more often than currencies.
        ("try converting 100 GBP to euros", ["GBP", "EUR"]),
        ("my php script converts 10 USD", ["USD"]),
        # Bare names that belong to several currencies must not be guessed.
        ("how much is 100 pesos", []),
        ("the krone fell today", []),
        ("this is a real problem for the won column", []),
    ],
)
def test_ambiguous_words_are_not_treated_as_currencies(query, expected):
    assert _find_currencies(query) == expected


def test_unserviceable_currencies_are_named_rather_than_silently_dropped():
    """The fabrication guard.

    With no source either way the model filled the gap from training data and
    the invented rate looked as grounded as a real one. An explicit "not
    published" source closes that off.
    """
    note = unsupported_currency_note("convert 500 dirhams to rupees")
    assert note is not None
    assert "AED" in note.snippet
    assert "do not include" in note.snippet


def test_the_note_stays_silent_when_the_question_is_not_a_conversion():
    assert unsupported_currency_note("the dirham is the currency of the UAE") is None
    assert unsupported_currency_note("convert 100 USD to INR") is None


def test_unsupported_table_never_overlaps_the_serviceable_codes():
    """A code in both tables would be recognised AND declared unavailable."""
    assert not (set(_UNSUPPORTED_ALIASES) & _CURRENCY_CODES)
