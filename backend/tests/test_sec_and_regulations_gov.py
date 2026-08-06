"""Tests for the SEC EDGAR and Regulations.gov live-data integrations
(2026-08-06) — wired the same way as Congress.gov: identifier-driven,
never-guess extraction, a real seeded governed Source catalog row, and a
category-level deterministic rule so a query naming a real ticker or docket
ID is never misrouted into the semantic-classifier's "default" fallback
(which service.py's off-domain refusal fast path treats as confidently
off-topic).
"""
from decimal import Decimal

from app.domains.reference_data.models import ReferenceSourceBundle
from app.domains.reference_data.service import (
    extract_sec_lookup,
    to_sec_rag_chunk,
    SEC_GOVERNED_SOURCE_ID,
    extract_regulations_gov_docket_id,
    to_regulations_gov_rag_chunk,
    REGULATIONS_GOV_GOVERNED_SOURCE_ID,
)
from app.orchestration.retrieve import infer_category_rule


def test_sec_ticker_requires_cashtag_or_explicit_form_never_a_bare_word():
    # "$AAPL" and "ticker AAPL" are unambiguous; a bare "AAPL" is too easily
    # confused with an ordinary capitalized word/acronym to ever guess from.
    assert extract_sec_lookup("What is $AAPL revenue?") == ("AAPL", "revenue")
    assert extract_sec_lookup("What is ticker AAPL net income?") == ("AAPL", "net_income")
    assert extract_sec_lookup("NASDAQ: AAPL total assets") == ("AAPL", "total_assets")
    assert extract_sec_lookup("What is AAPL revenue?") is None


def test_sec_lookup_requires_a_known_financial_concept():
    assert extract_sec_lookup("What is $AAPL?") is None


def test_sec_chunk_formats_the_looked_up_concept():
    bundle = ReferenceSourceBundle(
        source_name="SEC EDGAR — Company Facts",
        source_url="https://www.sec.gov/Archives/edgar/data/320193/000032019325000079",
        data=[{
            "concept": "revenue", "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
            "label": "Revenue from Contract with Customer, Excluding Assessed Tax",
            "value": 416161000000, "unit": "USD", "fiscal_year": 2025,
            "period_start": "2024-09-29", "period_end": "2025-09-27", "filed": "2025-10-31",
            "accession_number": "0000320193-25-000079", "company_title": "Apple Inc.", "ticker": "AAPL",
        }],
    )
    chunk = to_sec_rag_chunk(bundle, source_id=SEC_GOVERNED_SOURCE_ID)
    assert "Apple Inc." in chunk["text"]
    assert "AAPL" in chunk["text"]
    assert "$416,161,000,000" in chunk["text"]
    assert "fiscal year 2025" in chunk["text"]
    assert chunk["metadata"]["source_id"] == SEC_GOVERNED_SOURCE_ID


def test_regulations_gov_docket_id_requires_the_full_agency_year_number_shape():
    assert extract_regulations_gov_docket_id("What does docket IRS-2014-0019 say?") == "IRS-2014-0019"
    assert extract_regulations_gov_docket_id("What does TREAS-DO-2024-0003 propose?") == "TREAS-DO-2024-0003"
    assert extract_regulations_gov_docket_id("What is the latest IRS regulation?") is None


def test_regulations_gov_chunk_formats_the_docket():
    bundle = ReferenceSourceBundle(
        source_name="Regulations.gov — Docket Lookup",
        source_url="https://www.regulations.gov/docket/IRS-2014-0019",
        data=[{
            "docket_id": "IRS-2014-0019", "title": "Participation in a Summons Interview",
            "agency_id": "IRS", "docket_type": "Rulemaking", "rin": "1545-BM24",
            "abstract": "The IRS is issuing temporary regulations...",
            "modify_date": "2016-04-18T13:30:31Z", "keywords": [],
        }],
    )
    chunk = to_regulations_gov_rag_chunk(bundle, source_id=REGULATIONS_GOV_GOVERNED_SOURCE_ID)
    assert "IRS-2014-0019" in chunk["text"]
    assert "Participation in a Summons Interview" in chunk["text"]
    assert chunk["metadata"]["source_id"] == REGULATIONS_GOV_GOVERNED_SOURCE_ID


def test_sec_and_regulations_gov_queries_get_a_deterministic_category_not_the_default_fallback():
    # Live bug this guards against: without a deterministic rule, these
    # queries had no keyword-list match, fell through to the semantic
    # classifier, and (having no close category-example embedding for "SEC
    # ticker" or "regulatory docket ID") landed on the "default" fallback —
    # which service.py's off-domain refusal fast path treats as confidently
    # off-topic, refusing a genuinely answerable query outright.
    assert infer_category_rule("What is $AAPL revenue?") == "sec-filings"
    assert infer_category_rule("What does docket IRS-2014-0019 say?") == "federal-register"
