"""Reliability spec phases 3 and 6 — arithmetic and accounting concepts are
checked separately (22 Oct 2026 transcript, tests/fixtures/reliability_20261022.json).

Correct derived figures must survive (a lease answer lost "$42,123.64" =
210,618.19 ÷ 5, and ASC 842's 75%/90% thresholds); wrong concepts must not
pass because their numbers are right (share options cited under IAS 12 /
ASC 740; monetary unit sampling sized with the attribute-sampling formula).
"""
import json
import random
from pathlib import Path

import pytest

from app.orchestration.accounting_concepts import (
    MUS_METHOD_NOTE, correct_standard_references, reference_percentages, remove_wrong_method, review_concepts,
)
from app.orchestration.figure_reconciliation import unreconciled_figures

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "reliability_20261022.json").read_text())
TEXT = {m["id"]: m["content"] for m in FIXTURE["conversation"] if m.get("id")}
LEASE = TEXT["meridian-scenario"] + "\n" + TEXT["meridian-followup"]
LEASE_CALCULATIONS = ("50000 * (1 - (1 + 0.06) ** -5) / 0.06 = 210618.189278\n"
                      "210618.189278 * 0.06 = 12637.091357")


# ── Arithmetic: correct derived figures survive, fabricated ones do not ─────

def test_a_correct_high_precision_figure_one_step_from_verified_figures_is_kept():
    answer = "Annual amortisation of the ROU asset is $42,123.64. Year 1 lease expense is $54,760.73."
    assert unreconciled_figures(answer, LEASE, LEASE_CALCULATIONS) == []


def test_a_correct_two_step_figure_is_kept_without_its_intermediate():
    # 210,618.19 + 12,637.09 − 50,000: the answer does not show the interest.
    assert unreconciled_figures("The lease liability at the end of Year 1 is $173,255.28.",
                                LEASE, LEASE_CALCULATIONS) == []
    assert unreconciled_figures("Year 1 expense is $54,760.73.", LEASE, LEASE_CALCULATIONS) == []


def test_a_share_of_two_like_quantities_is_kept_and_a_wrong_share_is_not():
    assert unreconciled_figures("The lease term is 83% of the economic life.", LEASE, LEASE_CALCULATIONS) == []
    assert unreconciled_figures("The lease term is 71% of the economic life.", LEASE, LEASE_CALCULATIONS) == ["71%"]
    assert unreconciled_figures("Growth was 83%.", LEASE, LEASE_CALCULATIONS) == ["83%"]


def test_a_threshold_value_stated_as_a_fact_still_needs_support():
    assert unreconciled_figures("The lease term is 75% of the economic life.", LEASE, LEASE_CALCULATIONS) == ["75%"]


def test_a_wrong_high_precision_figure_is_still_removed():
    assert unreconciled_figures("Annual amortisation is $42,987.11.", LEASE, LEASE_CALCULATIONS) == ["$42,987.11"]


def test_a_near_miss_of_a_real_amount_is_not_derived_by_adding_a_count():
    # 210,618 − 5 − 5: the "5" of "5-year" is not a financial operand.
    assert unreconciled_figures("The lease liability is $210,608.00.", LEASE, LEASE_CALCULATIONS) == ["$210,608.00"]


@pytest.mark.parametrize("real", [42123.64, 54760.73, 173255.28, 210618.19, 12637.09])
@pytest.mark.parametrize("offset", [1, 5, 6, 10, 100])
def test_near_misses_of_verified_figures_are_removed(real, offset):
    for figure in (real + offset, real - offset):
        assert unreconciled_figures(f"The amount is ${figure:,.2f}.", LEASE, LEASE_CALCULATIONS) != []


# ── Known pre-existing gaps (predate 22 Oct 2026; tracked, not in this change) ─
# strict: when the older rules are fixed these start passing and must be
# turned into ordinary tests.

@pytest.mark.xfail(strict=True, reason="pre-existing: small whole percentages match other question numbers")
@pytest.mark.parametrize("percent", [1, 2, 4, 5, 6, 7, 10, 11, 12, 20, 25, 30, 36, 80])
def test_known_gap_small_whole_percentages_are_accepted_without_support(percent):
    assert unreconciled_figures(f"The lease term is {percent}% of the economic life.", LEASE, LEASE_CALCULATIONS) != []


@pytest.mark.xfail(strict=True, reason="pre-existing: a stated amount plus a small count passes the older rules")
@pytest.mark.parametrize("figure", [50_001.0, 49_999.0, 50_005.0, 49_995.0, 50_006.0, 49_994.0])
def test_known_gap_a_stated_amount_plus_a_count_is_accepted(figure):
    assert unreconciled_figures(f"The amount is ${figure:,.2f}.", LEASE, LEASE_CALCULATIONS) != []


def test_a_short_figure_does_not_get_the_pair_search():
    # Pair search over many numbers matches most two-digit values by chance.
    assert unreconciled_figures("The ratio is 37%.", LEASE, LEASE_CALCULATIONS) == ["37%"]


def test_fabricated_two_decimal_figures_are_essentially_never_accepted():
    random.seed(20261022)
    answer = "Annual amortisation is $42,123.64. Year 1 lease expense is $54,760.73."
    accepted = sum(not unreconciled_figures(f"{answer} The balance is ${random.uniform(1_000, 300_000):,.2f}.",
                                            LEASE, LEASE_CALCULATIONS) for _ in range(500))
    assert accepted <= 2, f"{accepted}/500 fabricated figures passed"


def test_published_lease_classification_thresholds_are_reference_values():
    answer = ("Under ASC 842 a lease is a finance lease if the term is a major part (75% or more) of the "
              "economic life, or payments are substantially all (90% or more) of fair value.")
    assert unreconciled_figures(answer, LEASE, LEASE_CALCULATIONS) == []
    # Out of that statement's context the same figures still need support.
    assert unreconciled_figures("Gross margin was 75%.", "Revenue £100,000 and costs £40,000.", "") == ["75%"]
    assert unreconciled_figures("This is an operating lease under ASC 842. Rent rose 75% this year.",
                                "Rent was $10,000.", "") == ["75%"]


def test_conventional_confidence_levels_are_reference_values_only_for_sampling():
    assert 95.0 in reference_percentages("MUS at a 95% confidence level")
    assert reference_percentages("The company has 95% confidence in its forecast") == []


# ── Concepts: a standard cited for the wrong topic is corrected ─────────────

def test_share_based_payment_cited_under_the_income_tax_standards_is_corrected():
    text, notes = correct_standard_references(
        "IFRS IAS 12 / ASC 740 – The company records the total grant-date fair value (adjusted for expected "
        "forfeitures) as share-based-payment expense over the service period.")
    assert text.startswith("IFRS 2 / ASC 718 –")
    assert any("ASC 740 → ASC 718" in note for note in notes) and any("IAS 12 → IFRS 2" in note for note in notes)


# Correct sentences, including the ones a first version wrongly "corrected"
# (22 Oct 2026 review): cross-topic mentions, contrasts, superseded and
# non-registered standards, other frameworks. None may change.
CORRECT_REFERENCES = [
    "Deferred tax on share options is measured under ASC 740 when the award is deductible.",
    "Under ASC 740, the tax consequences of share-based payment awards are recognised when deductible.",
    "Under IAS 12, the tax effect of the lease is recognised separately.",
    "Lease payments under ASC 842 and deferred tax under ASC 740 are both relevant.",
    "Goodwill is not amortised under ASC 350 for public business entities.",
    "Private companies may elect to amortise goodwill under ASC 350.",
    "Goodwill acquired is tested annually for impairment under IAS 36.",
    "Goodwill acquired is tested annually under IAS 36.",
    "Goodwill is measured under ASC 805 as consideration plus NCI less net assets.",
    "Revenue is allocated by stand-alone selling price under ASC 606.",
    "Revenue from the lease component is recognised under ASC 842, not ASC 606.",
    "The contract with the customer is accounted for under IFRS 15 rather than IAS 18.",
    "Before 2019, leases were accounted for under ASC 840.",
    "Under Ind AS 116 the lessee recognises a right-of-use asset.",
    "Under Ind AS 12, deferred tax on the lease is recognised.",
    "Under FRS 102 Section 20 the lease is classified as a finance lease.",
    "The impairment loss on the machine is recognised under ASC 360 after the recoverability test fails.",
    "Expected credit losses on receivables are an impairment under IFRS 9.",
    "Inventory is written down under IAS 2 when net realisable value is lower.",
    "Under AU-C 705 a scope limitation that is material and pervasive leads to a disclaimer of opinion.",
    "For an issuer, PCAOB AS 3105 governs departures from an unqualified opinion.",
    "Sample size for monetary unit sampling follows the AICPA guide that supports AU-C 530.",
    "A material weakness is evaluated under AU-C 265 for a non-issuer.",
    "Cash paid for the lease is presented in financing activities under ASC 842 and ASC 230.",
    "Share-based payment awards are measured at grant-date fair value under IFRS 2.",
    "Stock options are expensed over the vesting period under ASC 718.",
    "The acquisition-date fair value of contingent consideration is measured under ASC 805.",
    "Taxable income differs from book income because of temporary differences under ASC 740.",
    "Interest paid may be classified in operating activities under IAS 7.",
    "See ASC 999 for the rule.",
    # Unregistered standards are never changed, even when they look misplaced.
    "Goodwill of $245,000 is recognised in the business combination under IAS 2.",
]


@pytest.mark.parametrize("sentence", CORRECT_REFERENCES)
def test_a_correct_or_ambiguous_reference_is_never_changed(sentence):
    assert correct_standard_references(sentence) == (sentence, [])


WRONG_REFERENCES = [
    ("IFRS IAS 12 / ASC 740 – The grant-date fair value is expensed over the vesting period.", "IFRS 2 / ASC 718"),
    ("The ROU asset is amortised over the lease term under ASC 606.", "ASC 842"),
    ("Goodwill of $245,000 is recognised in the business combination under IAS 7.", "IFRS 3"),
    ("Net cash from operating activities is presented under ASC 718.", "ASC 230"),
    ("Stock options are expensed over the vesting period under ASC 842.", "ASC 718"),
    ("Performance obligations are identified under ASC 805.", "ASC 606"),
]


@pytest.mark.parametrize("wrong, right", WRONG_REFERENCES)
def test_a_reference_to_an_unrelated_standard_is_corrected_within_its_framework(wrong, right):
    text, notes = correct_standard_references(wrong)
    assert right in text and notes


def test_the_correction_note_names_both_topics():
    _, notes = correct_standard_references(WRONG_REFERENCES[0][0])
    assert any("ASC 740 is the standard on income taxes; this statement is about share-based payment" in n
               for n in notes)


# ── Concepts: a formula from another technique is removed ───────────────────

MUS_QUESTION = TEXT["mus-followup"] + " " + TEXT["mus-scenario"]


def test_the_attribute_sampling_formula_is_removed_from_a_monetary_unit_sampling_answer():
    answer = ("Sample size\nn = (Z^2 p (1-p)) ÷ (d^2)\nwhere Z is the Z-value for the confidence level.\n"
              "Tainting = misstatement ÷ book value of the item.")
    text, notes = remove_wrong_method(MUS_QUESTION, answer)
    assert "Z^2" not in text and "Z-value" not in text and "Tainting = misstatement" in text
    assert notes == [MUS_METHOD_NOTE] and "expansion factor" in MUS_METHOD_NOTE


def test_a_line_contrasting_the_two_methods_is_kept():
    answer = "Unlike attribute sampling (n = Z^2 p(1-p)/d^2), MUS uses a confidence factor."
    assert remove_wrong_method(MUS_QUESTION, answer) == (answer, [])


def test_the_same_formula_in_an_attribute_sampling_question_is_left_alone():
    answer = "n = (Z^2 p (1-p)) ÷ (d^2)"
    assert remove_wrong_method("Determine the attribute sampling sample size for a deviation rate.", answer) == (answer, [])


def test_review_combines_corrections_and_removals():
    review = review_concepts(MUS_QUESTION, "n = Z² p(1−p) / d²\nThe confidence factor at 95% is 3.0.")
    assert review.changed and review.removed and "confidence factor" in review.text
