"""Fixes from the 24 Oct 2026 review of "what is tax" and its follow-up
"Explain this comparison with a grounded example".

The follow-up was strictly sourced because it contains the word "tax"; 14
statements were removed. That left a lead-in to a removed table, an
unexplained £40 per unit, an empty "Personal income tax" heading, and a
checklist, common mistakes and agent guidance nobody asked for.
No model, database or network.
"""
import inspect

import pytest

from app.orchestration import service
from app.orchestration.claim_verification import drop_empty_headings, remove_claims, without_dependent_figures
from app.orchestration.derived_output import derived_output_instructions, requested_kinds
from app.orchestration.verification_service import prune_rejected_claims, requires_authoritative_evidence

CHIP = "Explain this comparison with a grounded example. Context: what is tax"


# ── 1. Only the form asked for ───────────────────────────────────────────

@pytest.mark.parametrize("question, kinds", [
    (CHIP, ["example"]),
    ("Summarize this as a checklist. Context: VAT registration", ["checklist"]),
    ("What common mistakes should I avoid? Context: an example of VAT", ["mistakes"]),
    ("Give a checklist and an example. Context: VAT", ["example", "checklist"]),
])
def test_only_the_requested_forms_are_instructed(question, kinds):
    assert requested_kinds(question) == kinds


def test_an_example_request_rules_out_the_other_forms():
    text = derived_output_instructions(CHIP)
    assert "Illustrative example" in text and "work the same scenario through each item compared" in text
    assert "For a checklist" not in text and "For common mistakes" not in text and "For a role" not in text
    assert "do not add a checklist, common mistakes, a version for a role" in text


def test_the_example_must_cite_a_rate_the_evidence_gives():
    assert "when the evidence gives the rate you use (a VAT rate, say), cite it" in derived_output_instructions(CHIP)


def test_the_service_passes_the_question():
    assert "derived_output_instructions(request.query)" in inspect.getsource(service)


# ── 2. A follow-up chip is held to its subject's standard ───────────────

@pytest.mark.parametrize("question, strict", [
    ("what is tax", False),
    (CHIP, False),
    ("Explain this with a grounded example. Context: What is the UK VAT registration threshold?", True),
    ("Summarize this as a checklist. Context: What are the GST return due dates?", True),
    ("Give me an example of VAT at the current UK rate", True),
])
def test_follow_up_strictness_follows_the_subject(question, strict):
    assert requires_authoritative_evidence(question, question) is strict


# ── 3. Lead-ins, unexplained figures, empty headings ─────────────────────

TABLE = """The table is a summary of the definitions found in the OECD sources.

| Tax type | Base |
|---|---|
| Personal income tax | Net income |

Next paragraph."""


def test_a_lead_in_goes_with_its_removed_table():
    out = remove_claims(TABLE, ["| Personal income tax | Net income |"])
    assert "The table is a summary" not in out and "Next paragraph." in out


def test_a_lead_in_stays_while_its_table_does():
    text = TABLE.replace("| Personal income tax | Net income |",
                         "| Personal income tax | Net income |\n| Corporate income tax | Net profit |")
    assert "The table is a summary" in remove_claims(text, ["| Personal income tax | Net income |"])


def test_a_colon_lead_in_goes_with_its_removed_table():
    text = "The comparison is:\n\n| A | B |\n|---|---|\n| x | 1 |\n\nAfter."
    assert remove_claims(text, ["| x | 1 |"]).strip() == "After."


EXAMPLE = """**Entity:** GreenTech Ltd. sells 1,000 units at £200 each.
Gross sales = 1,000 × £200 = £200,000
If the UK VAT rate is 20 % (current rate for most goods), the VAT per unit = £200 × 20 % = £40.
Total VAT collected = 1,000 × £40 = £40,000.
Remitted to HMRC = £40,000 − £5,000 = £35,000."""
RATE = "If the UK VAT rate is 20 % (current rate for most goods), the VAT per unit = £200 × 20 % = £40."


def test_lines_calculated_from_a_removed_figure_go_too():
    out = without_dependent_figures(remove_claims(EXAMPLE, [RATE]), [RATE], facts=CHIP)
    assert "Total VAT collected" not in out
    assert "Remitted to HMRC" not in out                       # built on £40,000, itself only from the £40
    assert "Gross sales = 1,000 × £200 = £200,000" in out      # £200 is stated in the scenario


def test_a_figure_the_user_gave_is_never_treated_as_unexplained():
    out = without_dependent_figures(remove_claims(EXAMPLE, [RATE]), [RATE], facts="The VAT per unit is £40.")
    assert "Total VAT collected = 1,000 × £40 = £40,000." in out


def test_a_calculator_result_is_never_treated_as_unexplained():
    facts = CHIP + "\n200 * 0.2 = 40"
    assert "Total VAT collected" in without_dependent_figures(remove_claims(EXAMPLE, [RATE]), [RATE], facts=facts)


def test_without_facts_pruning_is_unchanged():
    assert "Total VAT collected" in prune_rejected_claims(EXAMPLE, [RATE])
    assert "Total VAT collected" not in prune_rejected_claims(EXAMPLE, [RATE], facts=CHIP)


@pytest.mark.parametrize("text, expected", [
    ("**Personal income tax**\n\n### Checklist\n- Register.", "### Checklist\n- Register."),
    ("### A\n\n### B\nText.", "### B\nText."),
    ("### A\nText.\n\n### B", "### A\nText."),
    ("## Report\n### Section\nText.", "## Report\n### Section\nText."),          # a parent above its child
    ("**Personal income tax**\nThe sources provided do not confirm this.\n### Next\nX.",
     "**Personal income tax**\nThe sources provided do not confirm this.\n### Next\nX."),
])
def test_only_empty_headings_are_dropped(text, expected):
    assert drop_empty_headings(text) == expected


def test_the_service_drops_empty_headings_and_passes_facts():
    source = inspect.getsource(service)
    assert "final_text = drop_empty_headings(final_text)" in source
    assert "facts=release_facts" in source


# ── Regression after the first fix (24 Oct 2026): every example figure was ──
#    removed, because the example instruction was only given in strict mode
#    and the example exemption ended at the first subheading.

from app.orchestration.derived_output import is_illustration_heading, without_scenarios
from app.orchestration.verification_service import normalize_citations

GROUNDED = """## Grounded example – a UK small business
GreenTech Ltd. sells 1,000 units at £200 each.
### Journal entries
Dr Cash £240,000; Cr Sales £200,000; Cr VAT payable £40,000.
**Corporate tax**
Profit £50,000 taxed at 19% = £9,500 [REF-2].
## Why the example illustrates tax
Revenue of £999,999 was earned."""


@pytest.mark.parametrize("heading, is_example", [
    ("Illustrative example (hypothetical figures)", True),
    ("Grounded example – a UK small business", True),
    ("What is “tax” – a grounded example", True),
    ("Worked example", True),
    ("Example", False),
    ("Examples of tax types", False),
])
def test_example_headings_are_recognised(heading, is_example):
    assert is_illustration_heading(heading) is is_example


def test_the_exemption_covers_the_examples_subsections():
    view = without_scenarios(GROUNDED)
    assert "GreenTech Ltd. sells" not in view and "Dr Cash £240,000" not in view   # hypothetical, not claims


def test_rule_and_rate_lines_in_the_example_are_still_checked():
    assert "taxed at 19% = £9,500 [REF-2]" in without_scenarios(GROUNDED)


def test_figures_after_the_example_are_checked_again():
    assert "Revenue of £999,999 was earned." in without_scenarios(GROUNDED)


def test_the_example_instruction_is_given_outside_strict_sourcing_too():
    source = inspect.getsource(service)
    assert "if not (authority_required and not self_contained_calculation) and is_derived_output_request(request.query):" \
        in source


@pytest.mark.parametrize("narrated, clean", [
    ("## What is “tax” – a grounded example (corrected)", "## What is “tax” – a grounded example"),
    ("### Corrected journal entries (simplified)", "### Journal entries (simplified)"),
    ("**Revised balancing check**", "**Balancing check**"),
])
def test_correction_words_are_removed_from_headings(narrated, clean):
    assert normalize_citations(narrated, set()) == clean


@pytest.mark.parametrize("prose", ["Updated figures show revenue rose.", "The corrected invoice was issued.",
                                   "A revised budget was approved (revised in March)."])
def test_prose_using_those_words_is_kept(prose):
    assert normalize_citations(prose, set()) == prose


# ── "Output tax (UK VAT)" listed as a type of tax ─────────────────────────

from app.orchestration.accounting_methods import accounting_method_guidance


@pytest.mark.parametrize("question", ["what is tax", "What are taxes?", "Explain the types of tax",
                                      "What kinds of taxes are there?", CHIP])
def test_a_tax_types_question_gets_the_note(question):
    note = accounting_method_guidance(question)
    assert "Output tax and input tax are not separate taxes" in note and "property taxes" in note


@pytest.mark.parametrize("question", ["What is the UK VAT rate?", "How is tax calculated on a $50,000 salary?",
                                      "What is a tax point for VAT?", "What is deferred tax?"])
def test_other_tax_questions_do_not(question):
    assert "Output tax and input tax are not separate taxes" not in accounting_method_guidance(question)
