from app.orchestration.service import _compose_congress_record


def test_structured_congress_response_preserves_facts_and_citation():
    context = (
        "Congress.gov — HR 1, 119th Congress:\n"
        "- Title: Example Tax Act\n"
        "- Latest action (2025-02-01): Passed House"
    )

    answer = _compose_congress_record(context, "REF-2")

    assert "Example Tax Act" in answer
    assert "Passed House" in answer
    assert "[REF-2]" in answer


def test_structured_congress_response_omits_long_crs_summary():
    answer = _compose_congress_record(
        "Congress.gov — HR 1, 119th Congress:\n- Latest action (2025-07-04): Became law.\n- Latest CRS summary: Very long text",
        "REF-1",
    )
    assert "Became law" in answer
    assert "Very long text" not in answer
