"""Deciding whether a question is about the United Kingdom.

Retained as a named module because bank_of_england.py and govuk.py both import
it, and because the UK is the product's home market. The decision itself now
lives in country_scope.py, shared with the Bank of Canada, CSO Ireland, RBA,
ABS and US Treasury connectors — five connectors all needing the same "is this
question about MY country" answer, which is exactly the kind of rule that goes
out of step if each module keeps its own copy of the country list.

See country_scope.py for the rule and why it is asymmetric.
"""
from __future__ import annotations

from app.orchestration.country_scope import (
    display_name as _display_name,
    is_country_scoped as _is_country_scoped,
    names_another_country as _names_another_country,
    names_country as _names_country,
)

_UK = "GB"


def names_uk(query: str) -> bool:
    """Whether the question names the United Kingdom."""
    return _names_country(query, _UK)


def names_another_country(query: str) -> bool:
    """Whether the question names a country other than the UK."""
    return _names_another_country(query)


def is_uk_scoped(query: str) -> bool:
    """Whether a UK-only connector may answer this question.

    False means "do not answer": either the question names another country, or
    it names another country and the UK together. True means the question names
    the UK, or names no country at all — the caller's UK default.
    """
    return _is_country_scoped(query, _UK)


def uk_display_name() -> str:
    return _display_name(_UK)
