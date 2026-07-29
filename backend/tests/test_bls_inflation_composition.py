from app.orchestration.service import _compose_cpi_inflation


def test_cpi_composition_preserves_rate_and_observation_period():
    context = (
        "- 12-month (year-over-year) inflation rate: 2.7% "
        "(from 315.664 in June 2025 to 324.123 in June 2026)"
    )
    answer = _compose_cpi_inflation(context, "REF-1")
    assert "2.7%" in answer
    assert "June 2025" in answer
    assert "June 2026" in answer
    assert "[REF-1]" in answer
