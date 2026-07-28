"""
Pure unit tests for the PayrollTax API integration's query-parsing and
chunk-formatting helpers — zero network calls (the free-tier API is metered
at 1,000 req/month, so real calls are reserved for test_payroll_tax_adapter.py's
single end-to-end check).

Run locally (from backend/, venv active):
    python3 tests/test_payroll_tax_helpers.py
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone

from app.domains.reference_data.models import ReferenceSourceBundle
from app.domains.reference_data.service import (
    match_work_state,
    extract_pay_date,
    to_payroll_tax_rag_chunk,
)


def test_match_work_state_full_name():
    assert match_work_state("What are the payroll tax rates for California?") == "CA"
    assert match_work_state("employment tax in new york state") == "NY"
    print("test_match_work_state_full_name: PASSED")


def test_match_work_state_two_letter_code():
    assert match_work_state("payroll tax rates for CA effective 2026-01-01") == "CA"
    assert match_work_state("What is the FICA rate in TX?") == "TX"
    print("test_match_work_state_two_letter_code: PASSED")


def test_match_work_state_no_false_positive_on_common_words():
    # "in", "or", "me", "hi", "ok" are common English words that are also
    # valid state codes — must not match unless capitalized as a real code.
    assert match_work_state("what is the payroll tax rate in this scenario") is None
    assert match_work_state("hi, what are the payroll tax rates") is None
    print("test_match_work_state_no_false_positive_on_common_words: PASSED")


def test_match_work_state_none_when_absent():
    assert match_work_state("What are the current payroll tax rates?") is None
    print("test_match_work_state_none_when_absent: PASSED")


def test_extract_pay_date_explicit_iso():
    assert extract_pay_date("payroll tax rates for CA effective 2026-03-15") == "2026-03-15"
    print("test_extract_pay_date_explicit_iso: PASSED")


def test_extract_pay_date_malformed_falls_back_to_today():
    today = datetime.now(timezone.utc).date().isoformat()
    assert extract_pay_date("rates for CA on 2026-13-40") == today
    print("test_extract_pay_date_malformed_falls_back_to_today: PASSED")


def test_extract_pay_date_none_falls_back_to_today():
    today = datetime.now(timezone.utc).date().isoformat()
    assert extract_pay_date("What are the payroll tax rates for California?") == today
    print("test_extract_pay_date_none_falls_back_to_today: PASSED")


def test_to_payroll_tax_rag_chunk_documented_shape():
    bundle = ReferenceSourceBundle(
        source_name="PayrollTax API",
        source_url="https://payrolltaxapi.com/v1/rates/lookup",
        data=[{
            "pay_date": "2026-01-01",
            "work_state": "CA",
            "taxes": [
                {"tax_type_code": "FED_FICA_SS_EE", "name": "Social Security", "rate": 0.062, "wage_base": 176100},
                {"tax_type_code": "CA_INCOME_EE", "name": "CA State Income Tax", "rate_structure": "graduated", "brackets": [{"min": 0, "max": 10000, "rate": 0.01}]},
            ],
        }],
        licence_status="licensed_api_key",
    )
    chunk = to_payroll_tax_rag_chunk(bundle, source_id="src-payroll-tax-api-rate-lookup")
    assert "Social Security" in chunk["text"]
    assert "rate=0.062" in chunk["text"]
    assert "CA State Income Tax" in chunk["text"]
    assert chunk["metadata"]["source_id"] == "src-payroll-tax-api-rate-lookup"
    assert chunk["metadata"]["jurisdiction"] == "CA"
    assert chunk["node_id"].startswith("payroll-tax-live-")
    print("test_to_payroll_tax_rag_chunk_documented_shape: PASSED")


def test_to_payroll_tax_rag_chunk_undocumented_shape_does_not_crash():
    # A hypothetical SUTA/SDI/local entry with fields never documented by
    # the vendor — must degrade to an uglier line, never crash or drop data.
    bundle = ReferenceSourceBundle(
        source_name="PayrollTax API",
        source_url="https://payrolltaxapi.com/v1/rates/lookup",
        data=[{
            "pay_date": "2026-01-01",
            "work_state": "NY",
            "taxes": [
                {"tax_type_code": "NY_SDI_EE", "new_employer_rate": 0.034, "effective_quarter": "Q1"},
                "not-even-a-dict",  # defensively skipped, not crashed on
            ],
        }],
        licence_status="licensed_api_key",
    )
    chunk = to_payroll_tax_rag_chunk(bundle, source_id="src-payroll-tax-api-rate-lookup")
    assert "NY_SDI_EE" in chunk["text"]
    assert "new_employer_rate=0.034" in chunk["text"]
    print("test_to_payroll_tax_rag_chunk_undocumented_shape_does_not_crash: PASSED")


def test_to_payroll_tax_rag_chunk_stays_under_context_budget():
    # Many tax entries — the formatter must cap total text well under
    # context_fit.py's 8000-char per-request budget, not just this chunk.
    many_taxes = [{"tax_type_code": f"TAX_{i}", "name": f"Tax {i}", "rate": 0.01} for i in range(500)]
    bundle = ReferenceSourceBundle(
        source_name="PayrollTax API",
        source_url="https://payrolltaxapi.com/v1/rates/lookup",
        data=[{"pay_date": "2026-01-01", "work_state": "TX", "taxes": many_taxes}],
        licence_status="licensed_api_key",
    )
    chunk = to_payroll_tax_rag_chunk(bundle, source_id="src-payroll-tax-api-rate-lookup")
    assert len(chunk["text"]) <= 3100  # _MAX_CONTEXT_CHARS=3000 + header slack
    print("test_to_payroll_tax_rag_chunk_stays_under_context_budget: PASSED")


if __name__ == "__main__":
    test_match_work_state_full_name()
    test_match_work_state_two_letter_code()
    test_match_work_state_no_false_positive_on_common_words()
    test_match_work_state_none_when_absent()
    test_extract_pay_date_explicit_iso()
    test_extract_pay_date_malformed_falls_back_to_today()
    test_extract_pay_date_none_falls_back_to_today()
    test_to_payroll_tax_rag_chunk_documented_shape()
    test_to_payroll_tax_rag_chunk_undocumented_shape_does_not_crash()
    test_to_payroll_tax_rag_chunk_stays_under_context_budget()
