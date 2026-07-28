from app.domains.reference_data.models import ReferenceSourceBundle
from app.domains.reference_data.service import to_gdp_rag_chunk
from app.orchestration.service import _compose_gdp_history, _compose_real_gdp_change


def test_gdp_chunk_distinguishes_real_quarterly_change_from_current_dollar_growth():
    bundle = ReferenceSourceBundle(
        source_name="BEA",
        source_url="https://apps.bea.gov/api/data",
        data=[
            {"_table": "T10105", "TimePeriod": "2025Q1", "LineDescription": "Gross domestic product", "DataValue": "30000000"},
            {"_table": "T10105", "TimePeriod": "2026Q1", "LineDescription": "Gross domestic product", "DataValue": "31800000"},
            {"_table": "T10101", "TimePeriod": "2026Q1", "LineDescription": "Gross domestic product", "DataValue": "2.1"},
            {"_table": "T10101", "_frequency": "A", "TimePeriod": "2022", "LineDescription": "Gross domestic product", "DataValue": "1.9"},
            {"_table": "T10101", "_frequency": "A", "TimePeriod": "2023", "LineDescription": "Gross domestic product", "DataValue": "2.5"},
            {"_table": "T10101", "_frequency": "A", "TimePeriod": "2024", "LineDescription": "Gross domestic product", "DataValue": "2.8"},
            {"_table": "T10101", "_frequency": "A", "TimePeriod": "2025", "LineDescription": "Gross domestic product", "DataValue": "2.0"},
            {"_table": "T10101", "_frequency": "A", "TimePeriod": "2026", "LineDescription": "Gross domestic product", "DataValue": "1.7"},
        ],
    )
    text = to_gdp_rag_chunk(bundle, source_id="src-bea")["text"]
    assert "Year-over-year GDP growth (current dollars" in text
    assert "6.0%" in text
    assert "Real GDP percent change from the preceding quarter" in text
    assert "2.1%" in text
    answer = _compose_real_gdp_change(text, "REF-1")
    assert "2.1%" in answer
    assert "[REF-1]" in answer
    history = _compose_gdp_history(text, "REF-2")
    assert "| Year | Real GDP growth |" in history
    assert "| 2022 | 1.9% |" in history
    assert "| 2026 | 1.7% |" in history
    assert "[REF-2]" in history
