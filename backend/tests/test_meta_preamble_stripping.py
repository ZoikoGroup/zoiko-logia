"""
Pure unit test for app/orchestration/service.py::_strip_meta_preamble —
real incident (2026-07-22): the citation-repair pass asked the model to
"return only the repaired draft," but it sometimes prepended a literal
"Here's the repaired draft with added source citations..." sentence anyway,
which leaked into the answer the user actually saw ahead of the real
content.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.orchestration.service import (
    _has_only_presentation_failures,
    _strip_meta_preamble,
    _strip_raw_source_headers,
    _strip_trailing_raw_references,
    _validation_failure_summary,
)


def test_only_style_failures_are_eligible_for_automatic_repair():
    assert _has_only_presentation_failures([
        "Summarize-don't-copy check failed: copied passage",
        "Tutor-depth structure failed: missing purpose",
    ])
    assert not _has_only_presentation_failures([
        "Tutor-depth structure failed: missing purpose",
        "Numeric fidelity failed: unsupported amount",
    ])
    assert not _has_only_presentation_failures([
        "Prohibited-claim detected: professional advice",
    ])


def test_strips_real_incident_preamble():
    leaked = (
        "Here's the repaired draft with added source citations and [REF-N] markers:\n\n"
        "Our corporate structure and associated transfer pricing policies also "
        "contemplate future growth in international markets [REF-1]."
    )
    result = _strip_meta_preamble(leaked)
    assert result.startswith("Our corporate structure"), result
    print("test_strips_real_incident_preamble: PASSED")


def test_strips_phrasing_variants():
    for preamble in (
        "Here's the final answer:\n\n",
        "Here is the revised draft:\n\n",
        "Here's the updated response:\n\n",
    ):
        text = preamble + "The audit objective is X. [REF-1]"
        result = _strip_meta_preamble(text)
        assert result.startswith("The audit objective"), (preamble, result)
    print("test_strips_phrasing_variants: PASSED")


def test_leaves_clean_text_unaffected():
    clean = "A single filer's standard deduction is $16,100. [REF-1]"
    assert _strip_meta_preamble(clean) == clean
    print("test_leaves_clean_text_unaffected: PASSED")


def test_does_not_touch_legitimate_content_mentioning_drafts():
    # Must not strip content that just happens to discuss drafts/repairs as
    # its actual subject matter, only the specific leading-preamble shape.
    text = "The auditor's draft report should be reviewed before issuance. [REF-1]"
    assert _strip_meta_preamble(text) == text
    print("test_does_not_touch_legitimate_content_mentioning_drafts: PASSED")


def test_strips_real_incident_trailing_references_section():
    """2026-07-22 real incident: a "Compare IFRS vs GAA" answer self-appended
    a raw 'References:' section quoting [REF-N] header text verbatim,
    including a garbled second entry — exactly the header-copying the
    composition prompt already forbids, now with a defensive backstop."""
    leaked = (
        "In summary, while IFRS and GAA share similar principles, there are "
        "differences in their application. [REF-1]\n\n"
        "References:\n"
        "[REF-1] ASC 606 — Revenue from Contracts with Customers (FASB) (v1) - Jurisdiction: US\n"
        "[REF-1] IASB) has also issued IFRS 15, Revenue from Contracts with Customers (IFRS 15).\n"
    )
    result = _strip_trailing_raw_references(leaked)
    assert result.endswith("there are differences in their application. [REF-1]"), result
    assert "ASC 606" not in result
    print("test_strips_real_incident_trailing_references_section: PASSED")


def test_strips_markdown_heading_references_section():
    text = "The rule works as described. [REF-1]\n\n## Sources\n[REF-1] IRS Publication 501 (v1) - Jurisdiction: US\n"
    result = _strip_trailing_raw_references(text)
    assert result == "The rule works as described. [REF-1]", result
    print("test_strips_markdown_heading_references_section: PASSED")


def test_leaves_clean_text_without_reference_section_unaffected():
    clean = "A single filer's standard deduction is $16,100. [REF-1]"
    assert _strip_trailing_raw_references(clean) == clean
    print("test_leaves_clean_text_without_reference_section_unaffected: PASSED")


def test_does_not_touch_midtext_mention_of_references():
    # Must not strip a legitimate sentence that discusses "references" as a
    # real subject, only a genuine trailing raw-header block.
    text = "Auditors should retain references to supporting workpapers. [REF-1]"
    assert _strip_trailing_raw_references(text) == text
    print("test_does_not_touch_midtext_mention_of_references: PASSED")


def test_raw_context_headers_are_removed_but_markers_and_prose_remain():
    leaked = (
        "Compare the records. [REF-1] Source: Reviewed Procedure (v1) - Jurisdiction: Global\n"
        "Continue with the next step. [REF-1]\n"
        "[REF-2] Source: Other Source (v2) - Jurisdiction: US "
        "[REF-3] Source: Third Source (v1) - Jurisdiction: US"
    )
    cleaned = _strip_raw_source_headers(leaked)
    assert "Source:" not in cleaned
    assert "Jurisdiction:" not in cleaned
    assert "Compare the records. [REF-1]" in cleaned
    assert "Continue with the next step. [REF-1]" in cleaned
    assert cleaned.endswith("[REF-2] [REF-3]")


def test_failure_summary_covers_summarize_dont_copy_and_tutor_depth():
    """2026-07-22 real incident: "What are the VAT rates in the UAE vs
    India?" failed Checkpoint C but the user only ever saw the generic
    "did not pass grounded-answer validation" fallback — the new checks'
    failure strings weren't in the mapping table, so they fell through."""
    summary = _validation_failure_summary([
        "Summarize-don't-copy check failed: answer reproduces a 20+ word verbatim passage."
    ])
    assert summary != "it did not pass grounded-answer validation", summary
    assert "reproduced" in summary

    summary2 = _validation_failure_summary([
        "Tutor-depth structure failed: concept-explanation query answered without covering the what/why/rule/example structure."
    ])
    assert summary2 != "it did not pass grounded-answer validation", summary2
    assert "depth" in summary2
    print("test_failure_summary_covers_summarize_dont_copy_and_tutor_depth: PASSED")


if __name__ == "__main__":
    test_strips_real_incident_preamble()
    test_strips_phrasing_variants()
    test_leaves_clean_text_unaffected()
    test_does_not_touch_legitimate_content_mentioning_drafts()
    test_strips_real_incident_trailing_references_section()
    test_strips_markdown_heading_references_section()
    test_leaves_clean_text_without_reference_section_unaffected()
    test_does_not_touch_midtext_mention_of_references()
    test_failure_summary_covers_summarize_dont_copy_and_tutor_depth()
    print("All tests passed successfully!")
