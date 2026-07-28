"""
Tests for infer_category()'s embedding-similarity fallback
(app/orchestration/retrieve.py) — the semantic path that kicks in only when
the keyword scan finds nothing, generalizing away from needing a hand-added
keyword for every future phrasing variant (already needed twice live: FICA/
Texas phrasing, then EITC/HoH phrasing).

Requires ENABLE_RAG_EMBEDDINGS=true and policyengine_us/sentence-transformers
installed (real model, no mocking — same posture as
test_policyengine_calculation_helpers.py's real-calculation sanity check).

Run locally (from backend/, venv active):
    python3 tests/test_category_semantic_classification.py
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["ENABLE_RAG_EMBEDDINGS"] = "true"

from app.orchestration.retrieve import infer_category, _infer_category_semantic


def _clear_cache():
    # infer_category is @lru_cache'd — tests toggling ENABLE_RAG_EMBEDDINGS
    # or asserting on the same query text across cases must clear it first,
    # or a cached result from an earlier assertion would silently mask this
    # test actually exercising the code path it claims to.
    infer_category.cache_clear()


# ── Regression: keyword-matched queries unaffected ───────────────────────

def test_keyword_match_wins_regardless_of_semantic_fallback():
    _clear_cache()
    assert infer_category("What is the current federal funds rate?") == "interest-rates"
    assert infer_category("What does 26 CFR 1.401(k)-1 say?") == "tax-regulations"
    assert infer_category("What is the standard deduction?") == "tax"
    assert infer_category("Give me the steps to reconcile a bank account.") == "bank-reconciliation"
    assert infer_category("Show the month-end financial closing process as a timeline.") == "month-end-close"
    assert infer_category("Show revenue in a chart using this data: Q1 $100, Q2 $120.") == "user-provided-data"
    assert infer_category("Compare cash $120,000, receivables $180,000, and inventory $150,000 in a bar chart.") == "user-provided-data"
    assert infer_category("Explain the process for preparing a trial balance.") == "accounting-fundamentals"
    print("test_keyword_match_wins_regardless_of_semantic_fallback: PASSED")


def test_keyword_match_wins_with_embeddings_disabled():
    _clear_cache()
    os.environ["ENABLE_RAG_EMBEDDINGS"] = "false"
    try:
        assert infer_category("What is the current federal funds rate?") == "interest-rates"
    finally:
        os.environ["ENABLE_RAG_EMBEDDINGS"] = "true"
        _clear_cache()
    print("test_keyword_match_wins_with_embeddings_disabled: PASSED")


def test_icfr_does_not_match_embedded_cfr_keyword():
    _clear_cache()
    assert infer_category("What is the purpose of an ICFR audit?") == "audit"


# ── Historical failure #1: payroll-compliance without FICA/SUTA/FUTA/etc ─

def test_historical_failure_payroll_resolves_via_semantic_path():
    _clear_cache()
    query = "What do I owe the government for a new hire's employer contributions in Texas?"
    # Sanity: this query must NOT contain any _CATEGORY_KEYWORDS["payroll-compliance"]
    # literal keyword, or this test would pass for the wrong reason (keyword
    # match, not semantic fallback).
    for keyword in ["payroll", "employment", "fica", "suta", "futa", "withholding tax", "unemployment"]:
        assert keyword not in query.lower(), f"test query accidentally contains keyword '{keyword}'"
    assert infer_category(query) == "payroll-compliance"
    print("test_historical_failure_payroll_resolves_via_semantic_path: PASSED")


def test_historical_failure_payroll_falls_to_standards_with_embeddings_disabled():
    _clear_cache()
    os.environ["ENABLE_RAG_EMBEDDINGS"] = "false"
    try:
        query = "What do I owe the government for a new hire's employer contributions in Texas?"
        assert infer_category(query) == "standards"
    finally:
        os.environ["ENABLE_RAG_EMBEDDINGS"] = "true"
        _clear_cache()
    print("test_historical_failure_payroll_falls_to_standards_with_embeddings_disabled: PASSED")


# ── Historical failure #2: tax/EITC without "tax"/"deduction"/"eitc"/etc ─

def test_historical_failure_tax_resolves_via_semantic_path():
    _clear_cache()
    query = "How much extra will I get back on my return this year for having two kids and a low income?"
    for keyword in ["tax", "deduction", "eitc", "earned income", "ctc", "child tax credit", "cdcc"]:
        assert keyword not in query.lower(), f"test query accidentally contains keyword '{keyword}'"
    assert infer_category(query) == "tax"
    print("test_historical_failure_tax_resolves_via_semantic_path: PASSED")


def test_historical_failure_tax_falls_to_standards_with_embeddings_disabled():
    _clear_cache()
    os.environ["ENABLE_RAG_EMBEDDINGS"] = "false"
    try:
        query = "How much extra will I get back on my return this year for having two kids and a low income?"
        assert infer_category(query) == "standards"
    finally:
        os.environ["ENABLE_RAG_EMBEDDINGS"] = "true"
        _clear_cache()
    print("test_historical_failure_tax_falls_to_standards_with_embeddings_disabled: PASSED")


# ── Out-of-scope query must not be pulled into a wrong category ─────────

def test_out_of_scope_query_does_not_match_tax():
    _clear_cache()
    result = infer_category("Under FRS 102, how should a lessee account for a finance lease?")
    assert result != "tax", f"expected NOT 'tax', got '{result}'"
    print("test_out_of_scope_query_does_not_match_tax: PASSED")


# ── Failure isolation ────────────────────────────────────────────────────

def test_semantic_fallback_isolated_from_embedding_failures():
    _clear_cache()
    import app.orchestration.retrieve as retrieve_module

    original = retrieve_module._get_category_example_embeddings
    retrieve_module._get_category_example_embeddings = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        query = "How much extra will I get back on my return this year for having two kids and a low income?"
        assert infer_category(query) == "standards"
    finally:
        retrieve_module._get_category_example_embeddings = original
        _clear_cache()
    print("test_semantic_fallback_isolated_from_embedding_failures: PASSED")


if __name__ == "__main__":
    test_keyword_match_wins_regardless_of_semantic_fallback()
    test_keyword_match_wins_with_embeddings_disabled()
    test_historical_failure_payroll_resolves_via_semantic_path()
    test_historical_failure_payroll_falls_to_standards_with_embeddings_disabled()
    test_historical_failure_tax_resolves_via_semantic_path()
    test_historical_failure_tax_falls_to_standards_with_embeddings_disabled()
    test_out_of_scope_query_does_not_match_tax()
    test_semantic_fallback_isolated_from_embedding_failures()
