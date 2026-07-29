from app.orchestration.service import (
    _compose_standard_deduction,
    _standard_deduction_chunk,
    _standard_deduction_fact,
)


def test_2025_single_standard_deduction_uses_current_enacted_amount():
    fact = _standard_deduction_fact("What is the standard deduction for a single filer in 2025?")
    assert fact == {
        "year": 2025,
        "filing_status": "single",
        "amount": 15_750,
        "url": "https://www.irs.gov/irb/2025-45_IRB",
    }

    chunk = _standard_deduction_chunk(
        {"metadata": {"source_id": "src-irs-standard-deduction"}, "node_id": "existing"},
        fact,
    )
    answer = _compose_standard_deduction(chunk, "REF-1")
    assert "$15,750" in answer
    assert "[REF-1]" in answer
    assert chunk["metadata"]["jurisdiction"] == "US"


def test_standard_deduction_fact_requires_year_and_status():
    assert _standard_deduction_fact("What is the standard deduction for a single filer?") is None
    assert _standard_deduction_fact("What is the standard deduction in 2025?") is None
