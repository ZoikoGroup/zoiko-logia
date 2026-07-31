from app.orchestration.service import (
    _compose_standard_deduction_table,
    _compose_standard_deduction,
    _standard_deduction_chunk,
    _standard_deduction_fact,
    _standard_deduction_request,
    _standard_deduction_year_chunk,
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


def test_standard_deduction_fact_understands_natural_joint_filer_wording():
    fact = _standard_deduction_fact(
        "Calculate the standard deduction for a married couple filing jointly in 2026."
    )

    assert fact is not None
    assert fact["filing_status"] == "married filing jointly"
    assert fact["amount"] == 32_200

    chunk = _standard_deduction_chunk(
        {"metadata": {"source_id": "src-irs-standard-deduction"}, "node_id": "existing"},
        fact,
    )
    answer = _compose_standard_deduction(chunk, "REF-1")
    assert "for a married couple filing jointly is $32,200" in answer


def test_standard_deduction_comparison_is_deterministic_and_cites_each_year():
    query = (
        "Create a table comparing the 2025 and 2026 standard deductions for "
        "single, married filing jointly, married filing separately, and head of household."
    )
    request = _standard_deduction_request(query)

    assert request == {
        "years": [2025, 2026],
        "filing_statuses": [
            "single",
            "married filing jointly",
            "married filing separately",
            "head of household",
        ],
    }

    governed = {
        "metadata": {
            "source_id": "src-irs-standard-deduction",
            "title": "IRS Standard Deduction",
        },
        "node_id": "existing",
    }
    chunks = [
        _standard_deduction_year_chunk(governed, request, year)
        for year in request["years"]
    ]
    answer = _compose_standard_deduction_table([(0, chunks[0]), (1, chunks[1])])

    assert "| Filing status | 2025 | 2026 |" in answer
    assert "| Single | $15,750 [REF-1] | $16,100 [REF-2] |" in answer
    assert "| Married Filing Jointly | $31,500 [REF-1] | $32,200 [REF-2] |" in answer
    assert "| Married Filing Separately | $15,750 [REF-1] | $16,100 [REF-2] |" in answer
    assert "| Head Of Household | $23,625 [REF-1] | $24,150 [REF-2] |" in answer
