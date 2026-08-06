"""Holds the authority-rank marker table against the corpus's REAL
`source_class` values.

This exists because the table was written against plausible strings rather
than checked against the data. The marker was "standard setter"; the corpus
says "Professional standard-setter". No match, so every FRS, ASC, PCAOB and
GAAS document fell through to the coarse authority_level fallback and ranked
5 — identical to a web-search result. The hierarchy was computing correctly
over values that all said the same thing, which is the worst kind of wrong:
it looked like it worked.

CORPUS_SOURCE_CLASSES below is the distinct set observed in the seeded and
ingested corpus. Adding a source_class without giving it a rank makes
test_no_corpus_source_class_silently_takes_the_fallback fail, which is the
guard that was missing.
"""
import pytest

from app.domains.live_sources.authority import (
    UNKNOWN_RANK,
    matches_a_class_marker,
    normalise_source_class,
    rank_for_document,
)

# (source_class, expected rank) — every distinct value in the corpus.
CORPUS_SOURCE_CLASSES: tuple[tuple[str, int], ...] = (
    # 1 — enacted legislation and official regulations
    ("Government legislation", 1),
    ("Official legislative information", 1),
    ("Official government regulatory text", 1),
    # 2 — regulators, tax authorities, standard setters, statistical authorities
    ("Tax authority", 2),
    ("Securities regulator", 2),
    ("Professional standard-setter", 2),
    ("Auditing standard-setter", 2),
    ("Government statistical agency", 2),
    ("Government statistical agency documentation", 2),
    ("Official government data source", 2),
    ("Official government documentation", 2),
    ("Official government publication", 2),
    # 5 — guidance, reviewed syntheses, in-process tools
    ("Reviewed internal educational procedure", 5),
    ("Reviewed synthesis of current IRS primary guidance", 5),
    ("Open-source tax-benefit microsimulation model (PolicyEngine-US)", 5),
    (
        "Versioned, pure-function formula registry (15 named accounting/finance/tax/audit "
        "formulas), executed in-process",
        5,
    ),
    (
        "Deterministic AST-based arithmetic evaluator (Python ast module, decimal.Decimal), "
        "executed in-process",
        5,
    ),
    # 6 — discovery, commercial, caller-supplied
    ("Restricted authoritative-domain web discovery", 6),
    ("Commercial data provider", 6),
    ("First-party request data", 6),
)


@pytest.mark.parametrize("source_class,expected", CORPUS_SOURCE_CLASSES)
def test_every_corpus_source_class_gets_its_intended_rank(source_class, expected):
    assert rank_for_document("secondary", source_class) == expected


def test_no_corpus_source_class_silently_takes_the_fallback():
    """The guard that was missing. A class nobody mapped inherits the coarse
    authority_level rank, which is how an accounting standard came to rank
    equal to a Google result."""
    unmatched = [cls for cls, _ in CORPUS_SOURCE_CLASSES if not matches_a_class_marker(cls)]
    assert not unmatched, f"unmapped source_class values would take the fallback: {unmatched}"


def test_punctuation_cannot_decide_authority():
    """A hyphen demoted every accounting standard in the corpus. Normalisation
    makes the separator irrelevant."""
    for variant in (
        "Professional standard-setter",
        "Professional standard setter",
        "PROFESSIONAL_STANDARD_SETTER",
        "professional  standard--setter",
    ):
        assert rank_for_document("secondary", variant) == 2, variant
    assert normalise_source_class("Professional standard-setter") == "professional standard setter"


def test_standards_outrank_web_discovery():
    """The property that actually matters: a standard-setter document must not
    tie with a search result. They were both 5."""
    standard = rank_for_document("secondary", "Professional standard-setter")
    discovery = rank_for_document("secondary", "Restricted authoritative-domain web discovery")
    assert standard < discovery


def test_legislation_outranks_a_standard_setter():
    assert rank_for_document("primary", "Government legislation") < rank_for_document(
        "secondary", "Professional standard-setter"
    )


def test_a_more_specific_marker_wins_over_a_generic_one():
    """Order in the table is by SPECIFICITY, not by rank. "formula registry"
    has to be tested before the generic "registry", or an in-process
    calculator is mistaken for an official filing system — it was, at 3."""
    assert rank_for_document("primary", "pure-function formula registry, executed in-process") == 5
    assert rank_for_document("secondary", "Companies House registry") == 3


def test_an_unrecognised_class_falls_back_to_the_authority_level():
    assert rank_for_document("primary", "Something Nobody Has Defined") == 2
    assert rank_for_document("secondary", "Something Nobody Has Defined") == 5
    assert rank_for_document("internal", "Something Nobody Has Defined") == 6
    assert rank_for_document("", "") == UNKNOWN_RANK


def test_the_default_class_still_defers_to_an_explicit_level():
    # "External Reference" is metadata_service's baseline default and carries
    # no information, so it must not override a level someone actually set.
    assert not matches_a_class_marker("External Reference")
    assert rank_for_document("primary", "External Reference") == 2
