import time
from decimal import Decimal

import pytest

from app.orchestration.calculation_service import (
    build_calculation,
    validate_answer_calculations,
)
from app.orchestration.telemetry import StageMetrics


def test_explicit_arithmetic_is_computed_with_decimal() -> None:
    calculation = build_calculation("Calculate (125,000 - 25,000) / 5")

    assert calculation is not None
    assert calculation.result == Decimal("20000")
    assert calculation.widget.output_value == "20000"
    assert "Verified result: 20000" in calculation.prompt_context()


def test_straight_line_depreciation_uses_named_inputs() -> None:
    calculation = build_calculation(
        "Calculate straight-line depreciation: cost $120,000, residual value $20,000, useful life 5 years."
    )

    assert calculation is not None
    assert calculation.result == Decimal("20000")
    assert calculation.widget.formula_id == "straight_line_depreciation"
    assert [item.name for item in calculation.widget.inputs] == ["cost", "residual", "life"]


def test_ambiguous_word_problem_is_not_guessed() -> None:
    assert build_calculation("How much tax might my business owe this year?") is None


def test_incorrect_answer_equation_is_rejected() -> None:
    failures = validate_answer_calculations("The working is (120000 - 20000) / 5 = 25000.")

    assert failures == ["Calculation mismatch: (120000 - 20000) / 5 equals 20000, not 25000."]
    assert validate_answer_calculations("(120000 - 20000) / 5 = 20000") == []


def test_long_numeric_series_with_no_equals_does_not_hang() -> None:
    """_EQUATION previously had catastrophic (exponential) backtracking on any
    long digit/operator run with no trailing `= result` — exactly the shape of
    a chart's raw data array. A real, unmodified 20-point GDP growth series
    (which includes negative years, e.g. 2008/2009/2020 recessions) reproduced
    a multi-minute hang; this must now resolve in well under a second."""
    uk_gdp_growth_series = [
        2.18982132415704, 2.93091133582351, -0.0494116727402769, -4.58740819226323,
        2.26054460931586, 0.851437739020326, 1.52826034721852, 1.71846961308464,
        3.16017351468152, 2.14040560033371, 2.20652020635357, 3.02322219840339,
        1.55133095078786, 1.25629899760824, -10.047896637362, 8.5431118453255,
        5.14970388522993, 0.271650048355255, 1.08027716858781, 1.38844207858726,
    ]
    text = '"data": [' + ", ".join(str(v) for v in uk_gdp_growth_series) + "]"

    start = time.monotonic()
    failures = validate_answer_calculations(text)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"validate_answer_calculations took {elapsed:.2f}s — regex backtracking regression"
    assert failures == []


@pytest.mark.asyncio
async def test_stage_metrics_records_success_and_error_type() -> None:
    metrics = StageMetrics()

    async def success() -> int:
        return 7

    async def failure() -> None:
        raise RuntimeError("provider unavailable")

    assert await metrics.run("success", success()) == 7
    with pytest.raises(RuntimeError):
        await metrics.run("failure", failure())

    snapshot = metrics.snapshot()
    assert snapshot["success"]["status"] == "ok"
    assert snapshot["failure"]["status"] == "error"
    assert snapshot["failure"]["error_type"] == "RuntimeError"
    assert snapshot["success"]["duration_ms"] >= 0
