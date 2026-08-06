"""Tests for the UK/international live-data integrations (2026-08-06):
ONS (UK inflation/GDP), Bank of England (UK Bank Rate), EU VIES (VAT
validation), and UN+UK sanctions screening. Wired the same way as
Congress.gov/SEC/Regulations.gov: identifier-driven where applicable,
never-guess extraction, real seeded governed Source catalog rows, and
deterministic category rules where extraction success itself is the
category signal.
"""
from datetime import datetime

from app.domains.reference_data.models import ReferenceSourceBundle
from app.domains.reference_data.service import (
    is_uk_query,
    _year_over_year_change,
    to_ons_rag_chunk,
    ONS_INFLATION_GOVERNED_SOURCE_ID,
    to_bank_of_england_rag_chunk,
    BANK_OF_ENGLAND_GOVERNED_SOURCE_ID,
    extract_vat_number,
    to_vies_rag_chunk,
    VIES_GOVERNED_SOURCE_ID,
    extract_sanctions_screening_name,
    to_sanctions_rag_chunk,
    SANCTIONS_GOVERNED_SOURCE_ID,
)
from app.orchestration.retrieve import infer_category_rule


def test_is_uk_query_recognizes_common_uk_names_only():
    assert is_uk_query("What is the UK inflation rate?")
    assert is_uk_query("What is the United Kingdom's GDP?")
    assert not is_uk_query("What is the US inflation rate?")
    assert not is_uk_query("What is the inflation rate?")


def test_year_over_year_change_requires_a_full_year_of_history():
    series = [(datetime(2025, 1, 1), 135.1), (datetime(2026, 1, 1), 139.4)]
    change = _year_over_year_change(series)
    assert change is not None
    assert round(change["change_pct"], 2) == round((139.4 - 135.1) / 135.1 * 100, 2)
    # No same-month-prior-year observation at all -> None, never a guessed
    # comparison between two arbitrary points.
    assert _year_over_year_change([(datetime(2026, 1, 1), 139.4)]) is None


def test_ons_chunk_formats_a_real_year_over_year_change():
    bundle = ReferenceSourceBundle(
        source_name="ONS — CPIH (UK Inflation)", source_url="https://api.beta.ons.gov.uk/v1/datasets",
        data=[{
            "latest_month": "January 2026", "latest_value": 139.4,
            "prior_month": "January 2025", "prior_value": 135.1, "change_pct": 3.18,
        }],
    )
    chunk = to_ons_rag_chunk(bundle, source_id=ONS_INFLATION_GOVERNED_SOURCE_ID, title="ONS — CPIH (UK Inflation)", metric_label="UK CPIH inflation")
    assert "3.2%" in chunk["text"]
    assert "January 2026" in chunk["text"]
    assert chunk["metadata"]["jurisdiction"] == "UK"


def test_bank_of_england_chunk_formats_the_latest_rate():
    bundle = ReferenceSourceBundle(
        source_name="Bank of England — Bank Rate", source_url="https://www.bankofengland.co.uk/boeapps/database",
        data=[{"date": "01 Jan 2024", "value": "5.25"}, {"date": "05 Aug 2026", "value": "3.75"}],
    )
    chunk = to_bank_of_england_rag_chunk(bundle, source_id=BANK_OF_ENGLAND_GOVERNED_SOURCE_ID)
    assert "3.75%" in chunk["text"]
    assert "05 Aug 2026" in chunk["text"]


def test_vat_number_extraction_requires_explicit_vat_phrasing():
    # A bare 2-letter-plus-digits token is too easy to collide with an
    # unrelated identifier (invoice number, product code) to check without
    # the explicit "VAT number/registration" context.
    assert extract_vat_number("Is VAT number DE123456789 valid?") == ("DE", "123456789")
    assert extract_vat_number("What is DE123456789?") is None


def test_vies_chunk_formats_a_valid_result():
    bundle = ReferenceSourceBundle(
        source_name="EU VIES — VAT Validation", source_url="https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number",
        data=[{
            "country_code": "IE", "vat_number": "6388047V", "valid": True,
            "name": "GOOGLE IRELAND LIMITED", "address": "3RD FLOOR, GORDON HOUSE, DUBLIN 4",
            "request_date": "2026-08-06T12:55:57.587Z",
        }],
    )
    chunk = to_vies_rag_chunk(bundle, source_id=VIES_GOVERNED_SOURCE_ID)
    assert "VALID" in chunk["text"]
    assert "GOOGLE IRELAND LIMITED" in chunk["text"]


def test_sanctions_screening_name_requires_an_explicit_trigger_phrase():
    assert extract_sanctions_screening_name("Is John Smith on the sanctions list?") == "John Smith"
    assert extract_sanctions_screening_name("Check Acme Corp against the sanctions list.") == "Acme Corp"
    assert extract_sanctions_screening_name("What are sanctions?") is None


def test_sanctions_chunk_formats_matches_and_no_matches_distinctly():
    match_bundle = ReferenceSourceBundle(
        source_name="UN + UK Consolidated Sanctions Screening", source_url="https://scsanctions.un.org/",
        data=[{"list_source": "UN", "reference_id": "IRe.001", "name": "7TH OF TIR", "entry_type": "Entity"}],
    )
    match_chunk = to_sanctions_rag_chunk(match_bundle, source_id=SANCTIONS_GOVERNED_SOURCE_ID, screened_name="7TH OF TIR")
    assert "1 potential match" in match_chunk["text"]
    assert "not a confirmed identity match" in match_chunk["text"]

    no_match_bundle = ReferenceSourceBundle(
        source_name="UN + UK Consolidated Sanctions Screening", source_url="https://scsanctions.un.org/", data=[],
    )
    no_match_chunk = to_sanctions_rag_chunk(no_match_bundle, source_id=SANCTIONS_GOVERNED_SOURCE_ID, screened_name="Nobody Real")
    assert "no match found" in no_match_chunk["text"]


def test_vat_and_sanctions_queries_get_a_deterministic_category_not_the_default_fallback():
    # Same protective pattern as the SEC/Regulations.gov fix: extraction
    # success is itself the category signal, so these never fall through
    # to the semantic classifier's "default" bucket (which service.py's
    # off-domain refusal fast path treats as confidently off-topic).
    assert infer_category_rule("Is VAT number DE123456789 valid?") == "vat-validation"
    assert infer_category_rule("Is John Smith on the sanctions list?") == "sanctions-screening"
