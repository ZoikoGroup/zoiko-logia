"""Tax procedures a source or a question can be about.

Two pages on the same tax but different procedures read alike — to keyword
and to semantic search. "Who can sign off a VAT return?" retrieved the VAT
refund page (claimant signatures, power of attorney) from the web, and a
local embedding model ranked that refund passage above the Making Tax
Digital passage that answers the question. The procedure is therefore tagged
explicitly: on governed passages at ingestion, and detected in the question
at retrieval, so evidence about a different procedure is filtered out
rather than out-ranked.
"""
from __future__ import annotations

import re

PROCEDURE_PATTERNS: dict[str, str] = {
    "refund": r"\b(?:refunds?|repayments?|reclaim\w*|claim(?:ing)? (?:vat|tax|gst) back)\b",
    "registration": r"\b(?:register|registration|deregist\w*|cancel\w*)\b",
    "penalty": r"\b(?:penalt\w*|surcharges?)\b",
    "appeal": r"\b(?:appeals?|tribunals?|disputes?)\b",
    "exemption": r"\b(?:exempt\w*|zero[- ]rat\w*)\b",
}
_COMPILED = {name: re.compile(pattern, re.I) for name, pattern in PROCEDURE_PATTERNS.items()}


def procedures_named(text: str) -> set[str]:
    """The procedures a piece of text explicitly names."""
    return {name for name, pattern in _COMPILED.items() if pattern.search(text or "")}


# Who a procedure is for, as "procedure:claimant" (e.g. "refund:non_uk").
# Two refund schemes with different forms: VAT Notice 723A for businesses
# established outside the UK (VAT65A) and the VAT126 route for UK bodies not
# registered for VAT. Both are "refund", so a non-UK business was also handed
# the VAT126 page and the answer offered VAT126 as one of its routes.
CLAIMANT_PATTERNS: dict[str, str] = {
    "non_uk": r"\b(?:non[- ]uk|outside (?:the )?uk|overseas|foreign (?:business|company)|not established in the uk|eu business)\b",
    "unregistered_org": (
        r"\b(?:not (?:vat[- ])?registered|unregistered|local authorit\w*|charit\w*|academ\w*|"
        r"public bod\w*|non[- ]departmental)\b"
    ),
}
_CLAIMANTS = {name: re.compile(pattern, re.I) for name, pattern in CLAIMANT_PATTERNS.items()}


def is_other_procedure(source_procedure: str, query: str) -> bool:
    """True when evidence tagged with one procedure is offered for a question
    that does not name it, or for a different claimant than the question
    names. Untagged ("" or "general") evidence always passes."""
    if source_procedure in ("", "general"):
        return False
    procedure, _, claimant = source_procedure.partition(":")
    if procedure not in procedures_named(query):
        return True
    named = {name for name, pattern in _CLAIMANTS.items() if pattern.search(query or "")}
    # A question that names who is claiming excludes the other claimants'
    # schemes; one that names nobody keeps them all.
    return bool(claimant and named and claimant not in named)


def names_another_procedure(query: str, title: str) -> bool:
    """A title naming a procedure the question does not mention."""
    return bool(procedures_named(title) - procedures_named(query))
