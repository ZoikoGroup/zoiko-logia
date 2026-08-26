from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.kriton_workspace.artifacts import create_generated_artifact
from app.domains.kriton_workspace.documents import retrieve_document_sources
from app.domains.kriton_workspace.models import GeneratedArtifact
from app.domains.orchestration_state.tool_registry import (
    AgentTool, AgentToolError, ToolContext, ToolRegistry,
)
from app.orchestration.document_pipeline import analyse_spreadsheet_sources


class DocumentInput(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=10)


class InspectionOutput(BaseModel):
    document_ids: list[str]
    chunk_count: int
    locations: list[str]


class AnalysisOutput(BaseModel):
    analysis: dict[str, Any]


class ArtifactInput(BaseModel):
    document_ids: list[str]
    analysis: dict[str, Any]
    output_format: str = "xlsx"


class ArtifactOutput(BaseModel):
    artifact_id: str
    filename: str
    mime_type: str


async def _sources(context: ToolContext, document_ids: list[str]):
    return await retrieve_document_sources(
        context.db,
        query=context.goal,
        document_ids=document_ids,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        full_document=True,
    )


async def inspect_documents(context: ToolContext, arguments: DocumentInput) -> InspectionOutput:
    sources = await _sources(context, arguments.document_ids)
    if not sources:
        raise AgentToolError(
            "NO_READABLE_DOCUMENT_DATA",
            "No readable data was found in the selected document.",
        )
    return InspectionOutput(
        document_ids=arguments.document_ids,
        chunk_count=len(sources),
        locations=[source.title for source in sources],
    )


async def calculate_monthly_highest_sales(
    context: ToolContext, arguments: DocumentInput,
) -> AnalysisOutput:
    sources = await _sources(context, arguments.document_ids)
    analysis = analyse_spreadsheet_sources(sources)
    if not analysis.get("monthly_highest_sales"):
        raise AgentToolError(
            "MONTHLY_SALES_COLUMNS_NOT_FOUND",
            "Kriton could not find usable date and revenue columns in the selected document.",
        )
    return AnalysisOutput(analysis=analysis)


def _field(fields: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in fields:
            return fields[name]
        match = next((value for key, value in fields.items() if key.startswith(f"{name} ")), None)
        if match is not None:
            return match
    return ""


def _narrative(analysis: dict[str, Any]) -> str:
    rows = analysis.get("monthly_highest_sales", [])
    headers = ["Month", "Customer", "Product Category", "Deal Type", "Revenue", "Profit", "Status"]
    lines = [
        "## Executive Summary",
        "The workbook was analysed deterministically. The table lists the highest-revenue sale found for each month.",
        "",
        "## Highest-Revenue Sale by Month",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        fields = row.get("fields", {})
        values = [
            row.get("month", ""),
            _field(fields, "customer", "customer name"),
            _field(fields, "product category", "product"),
            _field(fields, "deal type", "service"),
            f"{row.get('revenue', 0):,.2f}",
            _field(fields, "profit", "gross profit"),
            _field(fields, "status"),
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    total = analysis.get("metrics", {}).get("monthly_highest_sales_total", 0)
    lines.extend([
        "",
        "## Verification",
        f"- Sum of the selected monthly highest sales: {total:,.2f}",
        f"- Months represented: {len(rows)}",
        "- Every result retains a source workbook location in the generated file.",
    ])
    return "\n".join(lines)


async def create_monthly_sales_artifact(
    context: ToolContext, arguments: ArtifactInput,
) -> ArtifactOutput:
    db: AsyncSession = context.db  # type: ignore[assignment]
    existing = await db.execute(select(GeneratedArtifact).where(
        GeneratedArtifact.query_id == context.run_id,
        GeneratedArtifact.tenant_id == context.tenant_id,
        GeneratedArtifact.user_id == context.user_id,
        GeneratedArtifact.status == "READY",
    ))
    artifact = existing.scalars().first()
    if artifact is None:
        artifact = await create_generated_artifact(
            db,
            title="Monthly Highest Sales Report",
            narrative=_narrative(arguments.analysis),
            analysis=arguments.analysis,
            format_name=arguments.output_format,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            query_id=context.run_id,
            source_document_ids=arguments.document_ids,
            request_text=context.goal,
        )
    return ArtifactOutput(
        artifact_id=artifact.id,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
    )


def build_agent_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(AgentTool(
        name="inspect_documents",
        description="Verify access and inspect all readable chunks in selected documents.",
        input_model=DocumentInput,
        output_model=InspectionOutput,
        handler=inspect_documents,
    ))
    registry.register(AgentTool(
        name="calculate_monthly_highest_sales",
        description="Deterministically group spreadsheet sales by month and select each maximum-revenue row.",
        input_model=DocumentInput,
        output_model=AnalysisOutput,
        handler=calculate_monthly_highest_sales,
    ))
    registry.register(AgentTool(
        name="create_monthly_sales_xlsx",
        description="Create and validate an XLSX artifact from verified monthly sales analysis.",
        input_model=ArtifactInput,
        output_model=ArtifactOutput,
        handler=create_monthly_sales_artifact,
        risk="DRAFT_WRITE",
        mutates_state=True,
    ))
    return registry
