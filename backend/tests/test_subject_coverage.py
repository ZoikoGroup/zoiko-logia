"""Tests for subject-level evidence coverage.

The failure this prevents, from a real query: asked to compare accounts
payable with accrued expenses, retrieval returned an accounts-payable process
document and nothing on accrued expenses. The bundle reported "sufficient
confidence" — four eligible sources, all describing one half of the question —
and the answer was a confident accounts-payable process checklist. A different
question, answered well.
"""
from app.orchestration.coverage import (
    assess_coverage,
    coverage_instruction,
    coverage_limitation,
    extract_subjects,
)


def _chunk(text: str, title: str = "Doc", rank: int | None = None, source_id: str = "") -> dict:
    metadata: dict = {"title": title}
    if rank is not None:
        metadata["authority_rank"] = rank
    if source_id:
        metadata["source_id"] = source_id
    return {"text": text, "metadata": metadata}


AP = "The accounts payable process: receive the invoice, validate it, approve and post the payable."
ACCRUED = "An accrued expense is recognised when incurred but not yet invoiced at the reporting date."


# ── Subject extraction ───────────────────────────────────────────────────


def test_a_prefix_comparison_yields_both_subjects():
    assert extract_subjects("Compare accounts payable and accrued expenses in a table.") == (
        "accounts payable", "accrued expenses",
    )


def test_an_infix_comparison_yields_the_subject_on_each_side():
    """Treating "vs" as a prefix marker dropped the left-hand subject
    entirely, so "FRS 102 vs FRS 105" was never checked as a comparison."""
    assert extract_subjects("FRS 102 vs FRS 105") == ("FRS 102", "FRS 105")
    assert extract_subjects("Accounts payable compared to accrued expenses") == (
        "Accounts payable", "accrued expenses",
    )


def test_interrogative_scaffolding_is_stripped_from_the_left_side():
    # Otherwise the subject reads "is FRS 102" in a user-facing limitation.
    assert extract_subjects("What is FRS 102 versus FRS 105?") == ("FRS 102", "FRS 105")


def test_a_presentation_instruction_is_not_a_subject():
    assert extract_subjects("Compare IFRS 16 and ASC 842 in a table") == ("IFRS 16", "ASC 842")
    assert extract_subjects("Compare IFRS 16 and ASC 842 as a chart") == ("IFRS 16", "ASC 842")


def test_three_subjects_are_all_extracted():
    assert extract_subjects("Compare accounts payable, accrued expenses and provisions") == (
        "accounts payable", "accrued expenses", "provisions",
    )


def test_a_single_subject_query_is_not_treated_as_a_comparison():
    """A coverage report over one subject adds nothing bundle confidence does
    not already say, and inventing subjects from prose would create false
    gaps."""
    for query in (
        "Compare the treatment under IFRS 16",
        "What does FRS 102 require for revenue recognition?",
        "Explain accruals",
        "Show me a chart of revenue by segment",
        "What is the ECB deposit facility rate?",
    ):
        assert extract_subjects(query) == (), query


# ── Coverage assessment ──────────────────────────────────────────────────


def test_the_real_failure_is_reported_as_partial():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses in a table.",
        [_chunk(AP, "Kriton Accounting Fundamentals — Core Processes", rank=5)],
    )
    assert report.is_multi_subject
    assert report.is_partial
    assert not report.is_complete
    assert report.uncovered == ("accrued expenses",)


def test_evidence_for_both_subjects_is_complete():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk(AP, "Fundamentals"), _chunk(ACCRUED, "Fundamentals")],
    )
    assert report.is_complete
    assert report.uncovered == ()
    assert not report.is_partial


def test_neither_subject_covered_is_not_partial():
    # "Partial" specifically means some covered and some not — the case that
    # produces a confident answer to a different question.
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk("Lease classification under IFRS 16 depends on control.", "IFRS 16")],
    )
    assert report.uncovered == ("accounts payable", "accrued expenses")
    assert not report.is_partial
    assert not report.is_complete


def test_coverage_counts_the_merged_evidence_not_one_provider():
    """Evidence from a document, a live source and a web result all count
    toward the same subject — the union is what the answer is built from."""
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [
            _chunk(AP, "Internal procedure", rank=5),
            _chunk(ACCRUED, "Web discovery result", rank=6),
        ],
    )
    assert report.is_complete
    by_subject = {item.subject: item for item in report.subjects}
    # And the best rank per subject is retained, so an answer can distinguish
    # "supported by a standard" from "supported only by discovery".
    assert by_subject["accounts payable"].best_rank == 5
    assert by_subject["accrued expenses"].best_rank == 6


def test_a_rank_can_come_from_the_document_rank_map():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk(AP, "Doc", source_id="doc-1"), _chunk(ACCRUED, "Doc", source_id="doc-2")],
        ranks_by_source_id={"doc-1": 2, "doc-2": 6},
    )
    by_subject = {item.subject: item.best_rank for item in report.subjects}
    assert by_subject == {"accounts payable": 2, "accrued expenses": 6}


def test_the_supporting_title_is_recorded():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk(AP, "Kriton Accounting Fundamentals")],
    )
    covered = next(item for item in report.subjects if item.covered)
    assert covered.supporting_titles == ("Kriton Accounting Fundamentals",)


def test_a_title_match_alone_can_satisfy_a_subject():
    # The document title is evidence of what the chunk is about.
    report = assess_coverage(
        "Compare IFRS 16 and ASC 842",
        [_chunk("Leases are classified by control.", "IFRS 16 — Leases"),
         _chunk("Dual model applies.", "ASC 842 — Leases")],
    )
    assert report.is_complete


def test_a_single_subject_query_produces_an_empty_report():
    report = assess_coverage("What does FRS 102 require?", [_chunk("FRS 102 requires...")])
    assert report.subjects == ()
    assert not report.is_multi_subject
    assert not report.is_complete


# ── What reaches the model and the reader ────────────────────────────────


def test_a_partial_gap_instructs_the_model_not_to_substitute_knowledge():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk(AP, "Fundamentals")],
    )
    instruction = coverage_instruction(report)
    assert "accrued expenses" in instruction
    assert "accounts payable" in instruction
    # The whole point: the gap must not be filled from the model's own
    # knowledge, which is what makes it invisible.
    assert "general knowledge" in instruction


def test_a_total_gap_instructs_a_plain_refusal_of_the_comparison():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk("Unrelated lease guidance.", "IFRS 16")],
    )
    instruction = coverage_instruction(report)
    assert "cannot compare" in instruction
    assert "general knowledge" in instruction


def test_complete_coverage_adds_no_instruction_or_limitation():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk(AP), _chunk(ACCRUED)],
    )
    assert coverage_instruction(report) == ""
    assert coverage_limitation(report) is None


def test_a_single_subject_query_adds_no_instruction_or_limitation():
    report = assess_coverage("What does FRS 102 require?", [_chunk("FRS 102 requires...")])
    assert coverage_instruction(report) == ""
    assert coverage_limitation(report) is None


def test_the_gap_is_stated_to_the_reader_not_only_the_model():
    report = assess_coverage(
        "Compare accounts payable and accrued expenses",
        [_chunk(AP, "Fundamentals")],
    )
    limitation = coverage_limitation(report)
    assert limitation is not None
    assert "accrued expenses" in limitation


def test_coverage_needs_no_model_call():
    # Deterministic and local: a query naming two subjects is a syntactic
    # fact, and an LLM round trip to notice it would sit on the critical path
    # of every request.
    import app.orchestration.coverage as module
    source = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("llm_classifier", "get_query_embedding", "httpx", "openai"):
        assert forbidden not in source, forbidden
