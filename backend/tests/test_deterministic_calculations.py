from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.calculations.engine import execute, quantize
from app.domains.calculations.models import CalculationRun
from app.domains.calculations.service import persist_run
from app.orchestration.calculation_service import build_calculation


def test_versioned_decimal_operations():
    assert execute("sum", [Decimal("0.1"), Decimal("0.2")]) == Decimal("0.3")
    assert execute("difference", [Decimal("12.50"), Decimal("2.25")]) == Decimal("10.25")
    assert execute("percentage", [Decimal("25"), Decimal("100")]) == Decimal("25")
    assert execute("percentage_change", [Decimal("100"), Decimal("125")]) == Decimal("25")
    assert quantize(Decimal("2.345")) == Decimal("2.35")


def test_invalid_division_is_rejected():
    with pytest.raises(ValueError, match="divide by zero"):
        execute("percentage_change", [Decimal("0"), Decimal("10")])


def test_percentage_change_and_variance_are_extracted_deterministically():
    change = build_calculation("Calculate the percentage change from 100 to 125")
    variance = build_calculation("Calculate variance where actual is 120 and budget is 100")
    assert change is not None and change.record.output_value == "25"
    assert change.record.operation == "percentage_change"
    assert variance is not None and variance.record.output_value == "20"
    assert variance.record.operation == "variance"


@pytest.mark.asyncio
async def test_calculation_run_is_persisted_with_verified_chart():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        calculation = build_calculation("Calculate the percentage change from 100 to 125")
        assert calculation is not None
        await persist_run(
            db, tenant_id="tenant-a", query_id="qry-1",
            result=calculation.record, chart=calculation.chart,
        )
        row = await db.get(CalculationRun, calculation.record.calculation_id)
        assert row.output_value == "25"
        assert row.rule_version == "percentage_change:v1"
        assert row.chart_spec["verified"] is True
    await engine.dispose()
