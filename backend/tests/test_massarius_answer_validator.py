"""ZL-ENG-03 Acceptance Criterion 7 — answer_validator.py (Checkpoint C)
blocks invalid output end-to-end and returns a degraded route rather than
the invalid answer, including the internal_reasoning_only non-exposure case."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.massarius.answer_validator import validate_answer, validate_answer_or_raise
from app.domains.massarius.errors import ValidationFailed
from app.orchestration.schemas import SourceBundle, SourceSummary
from app.domains.calculation.provenance import ProvenanceStore, from_expression_record, from_formula_result
from app.domains.calculation.expression_evaluator import evaluate_expression
from app.domains.calculation.formula_registry import execute_formula

_BUNDLE = SourceBundle(
    source_bundle_id="sb-1",
    eligible_source_count=1,
    sources=[SourceSummary(id="s1", title="FRS 102", category="standards", jurisdiction_scope="UK", version_label="v1", status="ACTIVE")],
    authority_level="secondary",
    confidence_state="sufficient",
    source_display_states={"s1": "show"},
)


def test_clean_grounded_cited_answer_passes():
    result = validate_answer("Under FRS 102, this may generally apply. [REF-1]", _BUNDLE)
    assert result.passed
    print("test_clean_grounded_cited_answer_passes: PASSED")


def test_ungrounded_substantive_answer_fails():
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer(
        "This is a long, substantive answer with no sources backing it at all, over fifty characters.",
        empty_bundle,
    )
    assert not result.passed
    assert any("Grounding" in f for f in result.failures)
    print("test_ungrounded_substantive_answer_fails: PASSED")


def test_unbound_citation_fails():
    result = validate_answer("See [REF-9] for details.", _BUNDLE)
    assert not result.passed
    assert any("Citation binding" in f for f in result.failures)
    print("test_unbound_citation_fails: PASSED")


# Real GAAS-shaped scenario (2026-07-20): a single large document gets
# chunked into multiple embedded pieces at ingestion, several of which can
# each make the reranker's top-5 cut — so eligible_source_count (2 distinct
# governed sources here) is smaller than the number of real [REF-N] anchors
# actually shown to the model (5 chunks). Matches
# app/domains/rag/context_fit.py::build_grounded_context's exact
# "[REF-N] Source: ..." header format.
_GAAS_GROUNDING_CONTEXT = (
    "[REF-1] Source: US Generally Accepted Auditing Standards (GAAS) (v1) - Jurisdiction: US\n"
    "Content:\nThe auditor should consider...\n"
    "---\n"
    "[REF-2] Source: US Generally Accepted Auditing Standards (GAAS) (v1) - Jurisdiction: US\n"
    "Content:\nIndependence requires...\n"
    "---\n"
    "[REF-3] Source: US Generally Accepted Auditing Standards (GAAS) (v1) - Jurisdiction: US\n"
    "Content:\nA representation letter...\n"
    "---\n"
    "[REF-4] Source: US Generally Accepted Auditing Standards (GAAS) (v1) - Jurisdiction: US\n"
    "Content:\nManagement's refusal...\n"
    "---\n"
    "[REF-5] Source: US Generally Accepted Auditing Standards (GAAS) (v1) - Jurisdiction: US\n"
    "Content:\nA qualified opinion...\n"
)
_GAAS_BUNDLE = SourceBundle(
    source_bundle_id="sb-gaas",
    eligible_source_count=2,  # 2 distinct governed sources, but 5 real chunks shown (above)
    sources=[SourceSummary(id="s1", title="US Generally Accepted Auditing Standards (GAAS)", category="audit", jurisdiction_scope="US", version_label="v1", status="ACTIVE")],
    authority_level="primary",
    confidence_state="sufficient",
    source_display_states={"s1": "show"},
)


def test_citation_binding_uses_grounding_context_ref_headers_when_available():
    """The actual fix: [REF-4] is a real, legitimately-shown chunk (see
    _GAAS_GROUNDING_CONTEXT above) even though eligible_source_count=2 —
    must pass, not be flagged as an unbound/hallucinated citation."""
    result = validate_answer(
        "Management's refusal to provide a representation letter is a scope limitation. [REF-4]",
        _GAAS_BUNDLE,
        grounding_context=_GAAS_GROUNDING_CONTEXT,
    )
    assert result.passed, result.failures
    print("test_citation_binding_uses_grounding_context_ref_headers_when_available: PASSED")


def test_citation_not_in_grounding_context_still_fails():
    """A citation to a REF-N that genuinely never appeared in the grounding
    context (not just one beyond eligible_source_count) must still fail —
    the fix widens what counts as valid, it doesn't disable the check."""
    result = validate_answer(
        "See [REF-9] for details.",
        _GAAS_BUNDLE,
        grounding_context=_GAAS_GROUNDING_CONTEXT,
    )
    assert not result.passed
    assert any("Citation binding" in f for f in result.failures)
    print("test_citation_not_in_grounding_context_still_fails: PASSED")


def test_prohibited_claim_degrades_to_refusal():
    result = validate_answer("I certify that this is correct. [REF-1]", _BUNDLE)
    assert not result.passed
    assert result.degraded_route == "REFUSAL"
    print("test_prohibited_claim_degrades_to_refusal: PASSED")


def test_generic_audit_opinion_discussion_does_not_trigger_prohibited_claim():
    """2026-07-22 real incident: "Compare a qualified opinion vs an
    unqualified audit opinion" was refused end-to-end because the bare term
    "audit opinion" tripped a pattern meant to catch personalized claims —
    a purely educational sentence using "the company" as an illustrative
    example, and the bare term "audit opinion" as a subject, must pass."""
    result = validate_answer(
        "An unqualified opinion means the company's audit opinion is clean, with no exceptions noted. "
        "A qualified opinion is issued when the auditor concludes that, except for a specific matter, "
        "the financial statements are fairly presented. [REF-1]",
        _BUNDLE,
    )
    assert result.passed, result.failures
    print("test_generic_audit_opinion_discussion_does_not_trigger_prohibited_claim: PASSED")


def test_personalized_audit_opinion_claim_still_blocked():
    """The fix narrows the pattern, it doesn't disable it — a genuine
    second-person claim about the reader's own audit opinion must still
    be caught."""
    result = validate_answer("Your audit opinion will need to be qualified given these findings. [REF-1]", _BUNDLE)
    assert not result.passed
    assert any("Prohibited-claim" in f for f in result.failures)
    print("test_personalized_audit_opinion_claim_still_blocked: PASSED")


def test_bare_this_is_advice_phrase_no_longer_blocks_educational_use():
    result = validate_answer(
        "Financial advice from a qualified professional differs from general educational information. [REF-1]",
        _BUNDLE,
    )
    assert result.passed, result.failures
    print("test_bare_this_is_advice_phrase_no_longer_blocks_educational_use: PASSED")


def test_this_is_my_advice_claim_still_blocked():
    result = validate_answer("This is my legal advice for your situation. [REF-1]", _BUNDLE)
    assert not result.passed
    assert any("Prohibited-claim" in f for f in result.failures)
    print("test_this_is_my_advice_claim_still_blocked: PASSED")


def test_authority_ceiling_blocks_overreach_on_non_primary_source():
    result = validate_answer("This is the only correct treatment. [REF-1]", _BUNDLE)
    assert not result.passed
    assert any("Authority ceiling" in f for f in result.failures)
    print("test_authority_ceiling_blocks_overreach_on_non_primary_source: PASSED")


def test_confidence_support_blocks_unhedged_certainty_on_limited_confidence():
    limited_bundle = _BUNDLE.model_copy(update={"confidence_state": "limited"})
    result = validate_answer("This is definitely correct. [REF-1]", limited_bundle)
    assert not result.passed
    assert any("Confidence support" in f for f in result.failures)
    print("test_confidence_support_blocks_unhedged_certainty_on_limited_confidence: PASSED")


def test_disclaimer_presence_required_when_flagged():
    result = validate_answer(
        "A reasonably long answer with enough content to pass grounding checks. [REF-1]",
        _BUNDLE,
        disclaimer_required=True,
    )
    assert not result.passed
    assert any("Disclaimer presence" in f for f in result.failures)
    print("test_disclaimer_presence_required_when_flagged: PASSED")


def test_internal_reasoning_only_source_never_exposed():
    """The licence exposure check — a source marked internal_reasoning_only
    must never leak into the answer text, even by title."""
    private_bundle = SourceBundle(
        source_bundle_id="sb-private",
        eligible_source_count=1,
        sources=[SourceSummary(id="s1", title="Confidential Internal Memo", category="internal", jurisdiction_scope="UK", version_label="v1", status="ACTIVE")],
        source_display_states={"s1": "internal_reasoning_only"},
    )
    result = validate_answer("Per the Confidential Internal Memo, proceed as follows. [REF-1]", private_bundle)
    assert not result.passed
    assert any("Licence exposure" in f for f in result.failures)
    assert result.degraded_route == "REFUSAL"
    print("test_internal_reasoning_only_source_never_exposed: PASSED")


def test_fabricated_figure_fails_numeric_fidelity():
    """The exact real incident this check was added for: a model cites a
    real, eligible source but invents a dollar figure nowhere in the text
    it was actually given to read."""
    result = validate_answer(
        "The maximum credit is $56,844. [REF-1]",
        _BUNDLE,
        grounding_context="The earned income amount which provides the max EITC with 2 or more qualifying children.",
    )
    assert not result.passed
    assert any("Numeric fidelity" in f for f in result.failures)
    assert result.degraded_route == "CLARIFICATION"
    print("test_fabricated_figure_fails_numeric_fidelity: PASSED")


def test_grounded_figure_passes_numeric_fidelity():
    """A figure that genuinely appears in the grounding context (even
    reformatted with $ and commas) must not be flagged."""
    result = validate_answer(
        "The rate is 3.5%. [REF-1]",
        _BUNDLE,
        grounding_context="12-month inflation rate: 3.5% (from 322.561 to 333.952).",
    )
    assert result.passed
    print("test_grounded_figure_passes_numeric_fidelity: PASSED")


def test_no_grounding_context_skips_numeric_fidelity_check():
    """Existing callers (e.g. these very tests above) that don't pass
    grounding_context must see no behavior change."""
    result = validate_answer("The maximum credit is $99,999,999. [REF-1]", _BUNDLE)
    assert result.passed
    print("test_no_grounding_context_skips_numeric_fidelity_check: PASSED")


def test_derived_total_of_inline_supplied_figures_passes_numeric_fidelity():
    """Real gap (2026-08-03): a query that supplies a complete itemized
    dataset inline routinely gets an answer with a computed "Displayed
    total" — simple arithmetic on numbers the user already supplied, not
    an invented claim. It used to fail whenever grounding_context happened
    to be non-empty (any source, however unrelated, being retrieved),
    while the identical answer shape passed when zero sources were
    retrieved and checkpoint 8 was skipped outright — an inconsistency
    depending on retrieval luck, not on whether the total was trustworthy."""
    query = "Rent 3000, Payroll 8000, Marketing 1500, Utilities 500."
    result = validate_answer(
        "**Displayed total:** $13,000. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated generic accounting guidance text.",
        query_text=query,
    )
    assert result.passed, result.failures
    print("test_derived_total_of_inline_supplied_figures_passes_numeric_fidelity: PASSED")


def test_derived_percentage_share_of_inline_supplied_figures_passes_numeric_fidelity():
    query = "Rent 3000, Payroll 8000, Marketing 1500, Utilities 500."
    # Payroll's share of the 13000 total: 8000 / 13000 * 100 = 61.5%.
    result = validate_answer(
        "Payroll is the largest item, representing 61.5% of the displayed total. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated generic accounting guidance text.",
        query_text=query,
    )
    assert result.passed, result.failures
    print("test_derived_percentage_share_of_inline_supplied_figures_passes_numeric_fidelity: PASSED")


def test_incorrect_derived_total_still_fails_numeric_fidelity():
    """The widened check only accepts the ACTUAL sum/share — it must not
    become a loophole that lets any dollar figure through just because the
    query happened to contain some numbers."""
    query = "Rent 3000, Payroll 8000, Marketing 1500, Utilities 500."
    result = validate_answer(
        "**Displayed total:** $999,999. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated generic accounting guidance text.",
        query_text=query,
    )
    assert not result.passed
    assert any("Numeric fidelity" in f for f in result.failures)
    print("test_incorrect_derived_total_still_fails_numeric_fidelity: PASSED")


def test_derived_total_requires_at_least_one_query_number():
    """No numbers in the query at all must not make an arbitrary total
    "supported" by accident (e.g. an empty-sum edge case)."""
    result = validate_answer(
        "**Displayed total:** $13,000. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated generic accounting guidance text.",
        query_text="Show a breakdown of monthly expenses by category.",
    )
    assert not result.passed
    assert any("Numeric fidelity" in f for f in result.failures)
    print("test_derived_total_requires_at_least_one_query_number: PASSED")


def test_derived_difference_of_inline_supplied_figures_passes_numeric_fidelity():
    """Real gap (2026-08-06): "Analyze these monthly expenses and identify
    the largest change: January $80,000, February $92,000, March $87,000
    and April $105,000." — the deterministic composition correctly
    computed the largest period-to-period CHANGE as $18,000 (April
    $105,000 minus March $87,000), both numbers the user supplied
    directly. The derived-total/percentage-share widening only covered a
    SUM and its SHARES, not a plain pairwise difference, so this correct,
    query-derived figure was rejected as unsupported and a working
    deterministic answer degraded to a needless clarification."""
    query = "January $80,000, February $92,000, March $87,000 and April $105,000."
    result = validate_answer(
        "**Key insight:** The largest period-to-period change is the $18,000 increase from March to April. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated generic accounting guidance text.",
        query_text=query,
    )
    assert result.passed, result.failures
    print("test_derived_difference_of_inline_supplied_figures_passes_numeric_fidelity: PASSED")


def test_incorrect_derived_difference_still_fails_numeric_fidelity():
    query = "January $80,000, February $92,000, March $87,000 and April $105,000."
    result = validate_answer(
        "**Key insight:** The largest period-to-period change is the $999,999 increase. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated generic accounting guidance text.",
        query_text=query,
    )
    assert not result.passed
    assert any("Numeric fidelity" in f for f in result.failures)
    print("test_incorrect_derived_difference_still_fails_numeric_fidelity: PASSED")


def test_unsupported_illustrative_figures_can_be_generalized_before_validation():
    from app.domains.massarius.answer_validator import generalize_unsupported_numeric_claims

    draft = (
        "1. Compare the bank statement with the ledger. [REF-1]\n"
        "2. If the statement shows $5,000 and the ledger shows $4,800, investigate the difference. [REF-1]\n"
        "3. Review any unsupported 12% adjustment. [REF-1]"
    )
    repaired = generalize_unsupported_numeric_claims(
        draft,
        grounding_context="Bank reconciliation compares the statement and ledger and investigates differences.",
        query_text="Give me the steps to reconcile a bank account.",
    )
    assert "$5,000" not in repaired
    assert "$4,800" not in repaired
    assert "12%" not in repaired
    assert repaired.count("the applicable amount") == 2
    assert "the applicable rate" in repaired
    result = validate_answer(
        repaired,
        _BUNDLE,
        grounding_context="Bank reconciliation compares the statement and ledger and investigates differences.",
        query_text="Give me the steps to reconcile a bank account.",
    )
    assert result.passed, result.failures


def test_supported_figures_are_not_generalized():
    from app.domains.massarius.answer_validator import generalize_unsupported_numeric_claims

    draft = "The source-supported rate is 3.5%. [REF-1]"
    repaired = generalize_unsupported_numeric_claims(
        draft,
        grounding_context="The applicable rate is 3.5%.",
        query_text="Explain how the rate works.",
    )
    assert repaired == draft


def test_unsupported_numeric_example_section_is_removed_instead_of_placeholderized():
    from app.domains.massarius.answer_validator import generalize_unsupported_numeric_claims

    draft = (
        "## Steps\n1. Compare the statement and ledger. [REF-1]\n\n"
        "**Example**\nThe statement is $5,000 and the ledger is $4,800.\n\n"
        "## Review\nConfirm the adjusted balances agree. [REF-1]"
    )
    repaired = generalize_unsupported_numeric_claims(
        draft,
        grounding_context="Compare the bank statement and ledger, then confirm adjusted balances agree.",
        query_text="Give me the steps to reconcile a bank account.",
    )
    assert "Example" not in repaired
    assert "applicable amount" not in repaired
    assert "## Steps" in repaired
    assert "## Review" in repaired


def test_bank_reconciliation_procedure_chunk_covers_required_operational_steps():
    from app.domains.reference_data.bank_reconciliation import to_bank_reconciliation_rag_chunk

    chunk = to_bank_reconciliation_rag_chunk()
    text = " ".join(chunk["text"].lower().split())
    for required in (
        "deposits in transit", "outstanding checks", "bank fees", "interest",
        "adjusted bank balance", "adjusted book balance", "journal entries",
    ):
        assert required in text
    assert chunk["metadata"]["source_id"] == "src-kriton-bank-reconciliation-procedure"
    assert "timing differences already recorded in the books normally do not require another journal entry" in text


def test_month_end_close_chunk_excludes_transaction_closing_content():
    from app.domains.reference_data.month_end_close import to_month_end_close_rag_chunk

    chunk = to_month_end_close_rag_chunk()
    text = " ".join(chunk["text"].lower().split())
    assert "reconcile bank accounts" in text
    assert "trial balance" in text
    assert "management review" in text
    assert "subscribed shares" not in text
    assert "purchase price" not in text


def test_user_provided_data_chunk_preserves_only_current_request_values():
    from app.domains.reference_data.user_provided_data import to_user_provided_data_rag_chunk

    query = "Show a table using this data: Q1 revenue $120,000 and expenses $90,000."
    chunk = to_user_provided_data_rag_chunk(query)
    assert query in chunk["text"]
    assert chunk["metadata"]["mandatory_source"] is True
    assert chunk["metadata"]["source_id"] == "src-kriton-user-provided-data"


def test_unsupported_deadline_is_rejected_by_numeric_fidelity():
    result = validate_answer(
        "The close must be completed by the 15th. [REF-1]",
        _BUNDLE,
        grounding_context=_GAAS_GROUNDING_CONTEXT,
        query_text="Explain the month-end close process.",
    )
    assert not result.passed
    assert any("Numeric fidelity" in failure for failure in result.failures)


def test_reviewed_mistakes_answer_does_not_trigger_tutor_depth_escalation():
    from app.orchestration.educational_answers import compose_bank_reconciliation

    result = validate_answer(
        compose_bank_reconciliation("What are the common mistakes?", "REF-1"),
        _BUNDLE,
        grounding_context=_GAAS_GROUNDING_CONTEXT,
        query_text="What are the most common bank-reconciliation mistakes, and how can they be avoided?",
    )
    assert result.passed, result.failures


def test_gdp_factual_lookup_does_not_trigger_tutor_depth_escalation():
    # Live bug (2026-08-06): "What is US GDP?" was wrongly held to full
    # what/why/rule/example tutor-depth structure and escalated to human
    # review, even though it's a plain factual number lookup — the same
    # class of question "rate"/"amount"/"percentage" already exempt.
    result = validate_answer(
        "According to the U.S. Bureau of Economic Analysis, US GDP was "
        "$27.36 trillion (nominal, seasonally adjusted annual rate) as of "
        "Q1 2026, the most recently published estimate. [REF-1]",
        _BUNDLE,
        grounding_context=(
            "Bureau of Economic Analysis — Gross Domestic Product: $27.36 "
            "trillion (nominal, seasonally adjusted annual rate), Q1 2026."
        ),
        query_text="What is US GDP?",
    )
    assert result.passed, result.failures


def test_reviewed_accrual_answer_satisfies_tutor_depth_validation():
    from app.orchestration.educational_answers import compose_accounting_fundamentals

    result = validate_answer(
        compose_accounting_fundamentals("Explain accrual accounting.", "REF-1"),
        _BUNDLE,
        grounding_context=_GAAS_GROUNDING_CONTEXT,
        query_text="Explain accrual accounting, why it is used, and how it works in practice.",
    )
    assert result.passed, result.failures


# ── Provenance-aware numeric fidelity — 2026-07-23 governed calculation
# architecture (docs/calculation_architecture.md). Extends check 8 rather
# than replacing it: a claim unsupported by grounding_context now also
# checks query_text and a ProvenanceStore before failing.

def test_expression_derived_figure_is_supported_by_provenance():
    """The exact real-world false-positive risk this was built for: a
    genuinely correct derived number ('$70,000' from '250000 - 180000')
    would never appear literally in any retrieved document."""
    record = evaluate_expression("250000 - 180000")
    store = ProvenanceStore()
    store.add(from_expression_record(record))
    result = validate_answer(
        "Based on the figures provided, the estimated business profit is $70,000. [REF-1]",
        _BUNDLE,
        grounding_context="Some unrelated retrieved context with no numbers in it.",
        provenance=store,
    )
    assert result.passed, result.failures
    print("test_expression_derived_figure_is_supported_by_provenance: PASSED")


def test_same_claim_without_provenance_still_fails():
    """Confirms the provenance path is additive, not a general loosening —
    the identical claim with no provenance store supplied fails exactly as
    check 8 always has."""
    result = validate_answer(
        "Based on the figures provided, the estimated business profit is $70,000. [REF-1]",
        _BUNDLE,
        grounding_context="Some unrelated retrieved context with no numbers in it.",
    )
    assert not result.passed
    assert any("Numeric fidelity" in f for f in result.failures)
    print("test_same_claim_without_provenance_still_fails: PASSED")


def test_named_formula_result_is_supported_by_provenance():
    formula_result = execute_formula("accounting.gross_margin.v1", {
        "revenue": {"value": "250000", "unit": "USD"},
        "cost_of_goods_sold": {"value": "180000", "unit": "USD"},
    })
    store = ProvenanceStore()
    store.add(from_formula_result(formula_result))
    result = validate_answer(
        "The gross margin works out to 28.00%. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated context.",
        provenance=store,
    )
    assert result.passed, result.failures
    print("test_named_formula_result_is_supported_by_provenance: PASSED")


def test_fabricated_figure_still_fails_despite_unrelated_provenance_records():
    """A provenance store with real, verified records must not become a
    blanket exemption — a claimed figure that matches NONE of them still
    fails, exactly the correctness check 8 exists for."""
    record = evaluate_expression("250000 - 180000")
    store = ProvenanceStore()
    store.add(from_expression_record(record))
    result = validate_answer(
        "The estimated business profit is $99,999. [REF-1]",  # does not match the 70000 record
        _BUNDLE,
        grounding_context="Unrelated context.",
        provenance=store,
    )
    assert not result.passed
    assert any("Numeric fidelity" in f for f in result.failures)
    print("test_fabricated_figure_still_fails_despite_unrelated_provenance_records: PASSED")


def test_unverified_expression_record_does_not_support_any_claim():
    """An expression that was REJECTED (e.g. division by zero) must never
    quietly support a claim — only status='verified' records count."""
    record = evaluate_expression("1 / 0")
    store = ProvenanceStore()
    store.add(from_expression_record(record))
    result = validate_answer(
        "The result is $5. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated context.",
        provenance=store,
    )
    assert not result.passed
    print("test_unverified_expression_record_does_not_support_any_claim: PASSED")


def test_user_provided_figure_in_query_text_is_supported():
    """A figure the user themselves typed in their query — not retrieved,
    not calculated, but honestly restated back to them — must be accepted
    (provenance_type: user_provided_input)."""
    result = validate_answer(
        "You mentioned a purchase amount of $1,200. [REF-1]",
        _BUNDLE,
        grounding_context="Unrelated context.",
        query_text="What is the tax on my $1,200 purchase?",
    )
    assert result.passed, result.failures
    print("test_user_provided_figure_in_query_text_is_supported: PASSED")


def test_provenance_defaults_to_none_and_does_not_change_existing_behavior():
    """Backward compatibility: every existing call site that never passes
    provenance= must see byte-identical behavior to before this parameter existed."""
    result = validate_answer(
        "The rate is 3.5%. [REF-1]",
        _BUNDLE,
        grounding_context="12-month inflation rate: 3.5% (from 322.561 to 333.952).",
    )
    assert result.passed
    print("test_provenance_defaults_to_none_and_does_not_change_existing_behavior: PASSED")


def test_degenerate_repetition_degrades_to_human_review():
    """Real incident (2026-07-20): asked for a credit the calculation
    engine can't compute without a user-supplied expense figure (CDCC), the
    model looped the same ~60-word paragraph 7 times instead of concluding.
    No other check (1-8) catches this — it never asserts a false claim, an
    unbound citation, or a fabricated number, it just never converges."""
    looping_answer = (
        "Since we do not have information about the Adjusted Care Benefits Amount, "
        "we will assume that the filer did not receive any dependent care benefits. "
        "In this case, the CDCC is calculated as the lesser of the Qualified Expenses "
        "and the Maximum Claimable Expense With One Qualifying Person. "
    ) * 3
    result = validate_answer(looping_answer, _BUNDLE)
    assert not result.passed
    assert any("Repetition" in f for f in result.failures)
    assert result.degraded_route == "HUMAN_REVIEW"
    print("test_degenerate_repetition_degrades_to_human_review: PASSED")


def test_normal_answer_does_not_trigger_repetition_check():
    """Short, legitimately repeated phrases (a disclaimer, "[REF-1]" appearing
    twice) must not false-positive — only long (40+ char) sentences repeated
    3+ times count."""
    result = validate_answer(
        "Under FRS 102, this may generally apply. [REF-1] "
        "A different point also applies here. [REF-1] "
        "This response is for educational purposes only. Consult a qualified professional.",
        _BUNDLE,
    )
    assert result.passed
    print("test_normal_answer_does_not_trigger_repetition_check: PASSED")


def test_missing_exact_requested_fact_routes_to_clarification():
    result = validate_answer(
        "The retrieved context does not provide the exact standard deduction amount. [REF-1]",
        _BUNDLE,
    )
    assert not result.passed
    assert result.degraded_route == "CLARIFICATION"
    assert any("Missing requested fact" in failure for failure in result.failures)


def test_missing_topic_information_routes_to_clarification():
    result = validate_answer(
        "Unfortunately, the provided context does not contain any information about the latest Federal Register document. [REF-1]",
        _BUNDLE,
    )
    assert not result.passed
    assert result.degraded_route == "CLARIFICATION"


def test_verbatim_copy_fails_summarize_dont_copy_check():
    """2026-07-22 product vision doc item 5 — a 35+ word run copied
    straight from the grounding context, not paraphrased, must fail.
    Threshold raised from 20 to 35 on 2026-07-23 (see _MIN_VERBATIM_RUN_WORDS'
    comment) — this passage is deliberately long enough to still clear it."""
    copied_passage = (
        "the auditor should obtain sufficient appropriate audit evidence "
        "regarding the assessed risks of material misstatement through "
        "designing and implementing appropriate responses to those risks "
        "identified and evaluated during the planning phase of the engagement "
        "before forming an opinion on the financial statements as a whole"
    )
    result = validate_answer(
        f"Per the standard, {copied_passage}. [REF-1]",
        _BUNDLE,
        grounding_context=f"Some preamble text. {copied_passage} Some trailing text.",
    )
    assert not result.passed
    assert any("Summarize-don't-copy" in f for f in result.failures)
    assert result.degraded_route == "HUMAN_REVIEW"
    print("test_verbatim_copy_fails_summarize_dont_copy_check: PASSED")


def test_short_grounded_phrase_does_not_trigger_copy_check():
    """A short reused phrase (well under 35 words) — a defined term or a
    restated figure — must not false-positive as block-copying."""
    result = validate_answer(
        "The standard deduction for a single filer is $16,100. [REF-1]",
        _BUNDLE,
        grounding_context="For 2026, the standard deduction for a single filer is $16,100 per the IRS schedule.",
    )
    assert result.passed, result.failures
    print("test_short_grounded_phrase_does_not_trigger_copy_check: PASSED")


def test_moderate_length_technical_overlap_no_longer_false_positives():
    """2026-07-23 real incident: dense-but-legitimate technical phrasing
    (e.g. GAAS/IRS language a correct paraphrase would still resemble
    closely) shared a ~20-24 word run with the source purely because
    precise regulatory language doesn't paraphrase much — this used to
    fail at the old 20-word threshold. A run under the new 35-word
    threshold must pass."""
    moderate_passage = (
        "the total cost you can deduct each year after applying the dollar "
        "limit is limited to the taxable income from the active conduct of "
        "any trade or business during the year"
    )
    result = validate_answer(
        f"Under Section 179, {moderate_passage}. [REF-1]",
        _BUNDLE,
        grounding_context=f"Some other context. {moderate_passage} Additional detail follows.",
    )
    assert result.passed, result.failures
    print("test_moderate_length_technical_overlap_no_longer_false_positives: PASSED")


def test_concept_question_missing_depth_fails_tutor_structure_check():
    """2026-07-22 product vision doc item 6 — a bare, short definition
    answering a genuine concept-explanation query must fail; it has no
    why/purpose signal and no illustrative example."""
    result = validate_answer(
        "Double-entry bookkeeping is an accounting method where every "
        "transaction affects at least two accounts, recorded as a debit "
        "and a credit of equal value. [REF-1]",
        _BUNDLE,
        query_text="Explain double-entry bookkeeping.",
    )
    assert not result.passed
    assert any("Tutor-depth structure" in f for f in result.failures)
    assert result.degraded_route == "HUMAN_REVIEW"
    print("test_concept_question_missing_depth_fails_tutor_structure_check: PASSED")


def test_reviewed_deterministic_answer_can_skip_llm_tutor_depth_heuristic():
    answer = (
        "Cash accounting records receipts and payments when cash moves, while "
        "accrual accounting records economic activity in the applicable period. [REF-1]"
    )
    result = validate_answer(
        answer,
        _BUNDLE,
        query_text="Explain the difference between cash basis and accrual basis accounting.",
        enforce_tutor_depth=False,
    )
    assert result.passed, result.failures


def test_concept_question_with_full_depth_passes_tutor_structure_check():
    """A genuinely tutor-depth answer to the same kind of question — covers
    what/why/example — must pass."""
    result = validate_answer(
        "Double-entry bookkeeping is an accounting method where every "
        "transaction affects at least two accounts, recorded as a debit "
        "and a credit of equal value. [REF-1] The purpose is to keep the "
        "accounting equation in balance and catch recording errors, "
        "because every debit must have a matching credit. For example, "
        "buying $500 of supplies with cash debits the supplies account "
        "and credits the cash account by the same amount. [REF-1] This is "
        "why professionals rely on it to detect mistakes before financial "
        "statements are prepared.",
        _BUNDLE,
        query_text="Explain double-entry bookkeeping.",
    )
    assert result.passed, result.failures
    print("test_concept_question_with_full_depth_passes_tutor_structure_check: PASSED")


def test_sparse_source_answer_with_only_why_signal_now_passes():
    """2026-07-23 real incident: "Explain the purpose of an audit trail."
    was escalated with only 3 eligible sources — sparse retrieval
    legitimately couldn't support a concrete grounded example, but the
    answer had genuine depth and a why-signal. Requiring BOTH why AND
    example punished an honestly concise, accurate answer the same as a
    lazy one; only one of the two is now required."""
    result = validate_answer(
        "An audit trail is the chronological record of documentation that "
        "traces a transaction from its origin through to the final "
        "financial statement entry. [REF-1] The purpose is to let an "
        "auditor verify that recorded transactions actually occurred and "
        "were processed correctly, because each step in the trail can be "
        "checked against supporting evidence. This is why maintaining a "
        "complete audit trail is considered essential to reliable "
        "financial reporting and internal control. [REF-1]",
        _BUNDLE,
        query_text="Explain the purpose of an audit trail.",
    )
    assert result.passed, result.failures
    print("test_sparse_source_answer_with_only_why_signal_now_passes: PASSED")


def test_arithmetic_question_does_not_trigger_tutor_structure_check():
    """2026-07-23 real incident: "What is $500 minus $200?" matched the
    "what is" concept-question trigger and, having no rate/amount/deduction
    word to exempt it, still engaged the check — then failed for lacking a
    why/example structure a two-term subtraction was never going to have.
    A bare arithmetic expression is a calculation question, not a
    concept-explanation one, regardless of starting with "what is"."""
    result = validate_answer(
        "$500 minus $200 is $300.",
        _BUNDLE,
        query_text="What is $500 minus $200?",
    )
    assert result.passed, result.failures
    print("test_arithmetic_question_does_not_trigger_tutor_structure_check: PASSED")


def test_percent_of_arithmetic_question_does_not_trigger_tutor_structure_check():
    result = validate_answer(
        "15% of 200 is 30.",
        _BUNDLE,
        query_text="What is 15% of 200?",
    )
    assert result.passed, result.failures
    print("test_percent_of_arithmetic_question_does_not_trigger_tutor_structure_check: PASSED")


def test_comparison_lookup_query_does_not_trigger_tutor_structure_check():
    """2026-07-22 real incident: "What are the VAT rates in the UAE vs
    India?" matched the "what are" concept-question trigger, was long
    enough to engage the check (two jurisdictions), and failed for lacking
    a why/example signal a rate comparison was never going to have. The
    query names a concrete attribute ("rates"), so it must be exempted
    regardless of the leading "what are" phrasing."""
    result = validate_answer(
        "The UAE applies a standard VAT rate of 5%. [REF-1] India applies GST rates that "
        "vary by category, generally 5%, 12%, 18%, or 28%. [REF-1]",
        _BUNDLE,
        grounding_context="UAE standard VAT rate: 5%. India GST rates: 5%, 12%, 18%, 28% depending on category.",
        query_text="What are the VAT rates in the UAE vs India?",
    )
    assert result.passed, result.failures
    print("test_comparison_lookup_query_does_not_trigger_tutor_structure_check: PASSED")


def test_factual_lookup_query_skips_tutor_structure_check():
    """A narrow factual lookup ('What is the standard deduction amount?')
    is explicitly exempted per the vision doc — a short direct answer must
    not be forced into the fuller structure."""
    result = validate_answer(
        "The standard deduction for a single filer is $16,100. [REF-1]",
        _BUNDLE,
        query_text="What is the standard deduction amount for a single filer?",
    )
    assert result.passed, result.failures
    print("test_factual_lookup_query_skips_tutor_structure_check: PASSED")


def test_no_query_text_skips_tutor_structure_check():
    """Existing callers (e.g. earlier tests in this file) that don't pass
    query_text must see no behavior change."""
    result = validate_answer(
        "Double-entry bookkeeping is an accounting method where every "
        "transaction affects at least two accounts. [REF-1]",
        _BUNDLE,
    )
    assert result.passed, result.failures
    print("test_no_query_text_skips_tutor_structure_check: PASSED")


def test_validate_answer_or_raise_raises_typed_exception():
    """The literal spec shape — a direct call must raise ValidationFailed,
    not just return a falsy result, for callers that want to catch it."""
    try:
        validate_answer_or_raise("See [REF-9].", _BUNDLE)
        raise AssertionError("validate_answer_or_raise should have raised ValidationFailed")
    except ValidationFailed as e:
        assert e.failures
    print("test_validate_answer_or_raise_raises_typed_exception: PASSED")


if __name__ == "__main__":
    print("Running Massarius answer_validator tests (AC7)...")
    test_clean_grounded_cited_answer_passes()
    test_ungrounded_substantive_answer_fails()
    test_unbound_citation_fails()
    test_citation_binding_uses_grounding_context_ref_headers_when_available()
    test_citation_not_in_grounding_context_still_fails()
    test_prohibited_claim_degrades_to_refusal()
    test_authority_ceiling_blocks_overreach_on_non_primary_source()
    test_confidence_support_blocks_unhedged_certainty_on_limited_confidence()
    test_disclaimer_presence_required_when_flagged()
    test_internal_reasoning_only_source_never_exposed()
    test_fabricated_figure_fails_numeric_fidelity()
    test_grounded_figure_passes_numeric_fidelity()
    test_no_grounding_context_skips_numeric_fidelity_check()
    test_expression_derived_figure_is_supported_by_provenance()
    test_same_claim_without_provenance_still_fails()
    test_named_formula_result_is_supported_by_provenance()
    test_fabricated_figure_still_fails_despite_unrelated_provenance_records()
    test_unverified_expression_record_does_not_support_any_claim()
    test_user_provided_figure_in_query_text_is_supported()
    test_provenance_defaults_to_none_and_does_not_change_existing_behavior()
    test_degenerate_repetition_degrades_to_human_review()
    test_normal_answer_does_not_trigger_repetition_check()
    test_generic_audit_opinion_discussion_does_not_trigger_prohibited_claim()
    test_personalized_audit_opinion_claim_still_blocked()
    test_bare_this_is_advice_phrase_no_longer_blocks_educational_use()
    test_this_is_my_advice_claim_still_blocked()
    test_verbatim_copy_fails_summarize_dont_copy_check()
    test_short_grounded_phrase_does_not_trigger_copy_check()
    test_moderate_length_technical_overlap_no_longer_false_positives()
    test_concept_question_missing_depth_fails_tutor_structure_check()
    test_concept_question_with_full_depth_passes_tutor_structure_check()
    test_sparse_source_answer_with_only_why_signal_now_passes()
    test_arithmetic_question_does_not_trigger_tutor_structure_check()
    test_percent_of_arithmetic_question_does_not_trigger_tutor_structure_check()
    test_comparison_lookup_query_does_not_trigger_tutor_structure_check()
    test_factual_lookup_query_skips_tutor_structure_check()
    test_no_query_text_skips_tutor_structure_check()
    test_validate_answer_or_raise_raises_typed_exception()
    print("All tests passed successfully!")
