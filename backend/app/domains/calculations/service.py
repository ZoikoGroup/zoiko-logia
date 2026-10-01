from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.calculations.models import CalculationRun
from app.domains.calculations.schemas import CalculationResult, VerifiedChartSpec


async def persist_run(
    db: AsyncSession, *, tenant_id: str, query_id: str,
    result: CalculationResult, chart: VerifiedChartSpec | None,
) -> None:
    db.add(CalculationRun(
        id=result.calculation_id,
        tenant_id=tenant_id,
        query_id=query_id,
        operation=result.operation,
        rule_version=result.rule_version,
        inputs=[item.model_dump(mode="json") for item in result.inputs],
        output_value=result.output_value,
        output_unit=result.output_unit,
        rounding_mode=result.rounding_mode,
        scale=result.scale,
        chart_spec=chart.model_dump(mode="json") if chart else None,
    ))
    await db.commit()
