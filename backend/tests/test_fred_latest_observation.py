from app.domains.reference_data.service import _FRED_SERIES, to_fred_rag_chunk
from app.domains.reference_data.models import ReferenceSourceBundle
from app.orchestration.service import _compose_fred_rate


def test_fred_uses_daily_effective_rate_series():
    assert "DFF" in _FRED_SERIES
    assert "FEDFUNDS" not in _FRED_SERIES
    assert "DGS10" in _FRED_SERIES
    assert "GS10" not in _FRED_SERIES


def test_fred_chunk_skips_missing_latest_observation():
    bundle = ReferenceSourceBundle(
        source_name="FRED",
        source_url="https://fred.stlouisfed.org/series/DFF",
        data=[
            {"series_id": "DFF", "title": "Federal Funds Effective Rate", "date": "2026-07-20", "value": "."},
            {"series_id": "DFF", "title": "Federal Funds Effective Rate", "date": "2026-07-17", "value": "3.63"},
        ],
    )
    chunk = to_fred_rag_chunk(bundle, source_id="src-fred")
    assert "3.63% (as of 2026-07-17)" in chunk["text"]


def test_fred_rate_composition_preserves_exact_value_and_date():
    context = "- 10-Year Treasury Constant Maturity Rate (DGS10): 4.58% (as of 2026-07-14)"
    answer = _compose_fred_rate("What is the latest 10-year Treasury constant maturity rate?", context, "REF-2")
    assert answer == "The latest 10-year treasury constant maturity rate is 4.58% as of 2026-07-14. [REF-2]"


def test_fred_chunk_formats_fred_api_raw_ten_decimal_values():
    bundle = ReferenceSourceBundle(
        source_name="FRED",
        source_url="https://fred.stlouisfed.org/series/DFF",
        data=[
            {"series_id": "DFF", "title": "Federal Funds Effective Rate", "date": "2026-07-17", "value": "3.6300000000"},
            {"series_id": "DFF", "title": "Federal Funds Effective Rate", "date": "2025-07-17", "value": "4.3300000000"},
        ],
    )
    chunk = to_fred_rag_chunk(bundle, source_id="src-fred")
    assert "3.6300000000" not in chunk["text"]
    assert "3.63% (as of 2026-07-17)" in chunk["text"]
    assert "4.33% on 2025-07-17" in chunk["text"]


def test_fed_funds_one_year_trend_composition():
    context = """Federal Reserve Economic Data (FRED) — key US interest rates:
- Federal Funds Effective Rate (DFF): 3.63% (as of 2026-07-17)
  One-year window: 4.33% on 2025-07-17 to 3.63% on 2026-07-17 (-0.70 percentage points)"""
    answer = _compose_fred_rate(
        "What has the Fed funds rate done over the past year", context, "REF-1"
    )
    assert "decreased from 4.33%" in answer
    assert "to 3.63%" in answer
    assert "0.70 percentage points" in answer
