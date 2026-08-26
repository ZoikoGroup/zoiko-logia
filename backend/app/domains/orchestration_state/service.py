from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.kriton_workspace.models import GeneratedArtifact
from app.domains.orchestration_state.agent_tools import build_agent_tool_registry
from app.domains.orchestration_state.models import AgentRun, AgentStep
from app.domains.orchestration_state.schemas import (
    AgentArtifactPublic, AgentRunCreate, AgentRunPublic, AgentStepPublic,
)
from app.domains.orchestration_state.tool_registry import AgentToolError, ToolContext
from app.domains.learning_system.service import match_workflow


_MONTHLY_MAXIMUM = re.compile(
    r"(?=.*\b(month|monthly|each month|every month)\b)"
    r"(?=.*\b(highest|maximum|largest|top|best)\b)"
    r"(?=.*\b(sale|sales|revenue|deal)\b)",
    re.I,
)
_PROFESSIONAL_JUDGMENT = re.compile(
    r"\b(advise|recommend|certify|approve|audit opinion|tax treatment|"
    r"should (?:i|we)|file|submit|sign[ -]?off|compliance opinion)\b",
    re.I,
)
_PLAN = [
    "inspect_documents",
    "calculate_monthly_highest_sales",
    "create_monthly_sales_xlsx",
]
_REGISTRY = build_agent_tool_registry()


def classify_agent_goal(goal: str) -> tuple[str, str, list[str]]:
    if _PROFESSIONAL_JUDGMENT.search(goal):
        raise HTTPException(
            status_code=422,
            detail="This first agent release supports factual document analysis and draft generation, not professional advice or approval.",
        )
    if _MONTHLY_MAXIMUM.search(goal):
        return "MONTHLY_HIGHEST_SALES_REPORT", "LOW", list(_PLAN)
    raise HTTPException(
        status_code=422,
        detail="This agent release currently supports monthly highest-sales reports from uploaded spreadsheets.",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _arguments_for(run: AgentRun, tool_name: str) -> dict:
    document_ids = list(run.working_state.get("document_ids", []))
    if tool_name in {"inspect_documents", "calculate_monthly_highest_sales"}:
        return {"document_ids": document_ids}
    if tool_name == "create_monthly_sales_xlsx":
        return {
            "document_ids": document_ids,
            "analysis": run.working_state.get("analysis", {}),
            "output_format": run.working_state.get("output_format", "xlsx"),
        }
    raise AgentToolError("UNKNOWN_PLAN_STEP", f"Unsupported plan step: {tool_name}")


def _idempotency_key(run_id: str, sequence: int, tool_name: str, arguments: dict) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode()).hexdigest()[:24]
    return f"{run_id}:{sequence}:{tool_name}:{digest}"


async def create_agent_run(
    db: AsyncSession, *, payload: AgentRunCreate, tenant_id: str, user_id: str,
) -> AgentRun:
    workflow = await match_workflow(db, tenant_id, payload.goal, payload.output_format)
    if workflow is not None:
        task_type, risk_level, plan = workflow.name, workflow.risk_level, list(workflow.plan)
    else:
        task_type, risk_level, plan = classify_agent_goal(payload.goal)
    run = AgentRun(
        id=f"agent-{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=payload.conversation_id,
        goal=payload.goal,
        task_type=task_type,
        status="QUEUED",
        risk_level=risk_level,
        current_step=0,
        maximum_steps=max(len(plan) + 2, 5),
        plan=plan,
        working_state={
            "document_ids": payload.document_ids,
            "output_format": payload.output_format,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="agent_run_created",
        emitting_service="agent_runtime",
        actor_id=user_id,
        subject_type="agent_run",
        subject_id=run.id,
        correlation_id=payload.conversation_id or run.id,
        payload={"task_type": task_type, "risk_level": risk_level, "step_count": len(plan)},
    )
    return run


async def execute_agent_run(db: AsyncSession, run: AgentRun) -> AgentRun:
    if run.status in {"COMPLETED", "CANCELLED"}:
        return run
    if run.status == "RUNNING":
        # A prior process may have stopped between checkpoints. The unique
        # step/idempotency records below make resuming safe.
        run.status = "QUEUED"
    run.status = "RUNNING"
    run.error_code = None
    await db.commit()

    try:
        while run.current_step < len(run.plan):
            if run.current_step >= run.maximum_steps:
                raise AgentToolError("AGENT_STEP_LIMIT", "The agent exceeded its maximum step count.")
            sequence = run.current_step + 1
            tool_name = run.plan[run.current_step]
            tool = _REGISTRY.get(tool_name)
            arguments = _arguments_for(run, tool_name)
            validated_arguments = tool.input_model.model_validate(arguments)
            key = _idempotency_key(run.id, sequence, tool_name, arguments)

            existing = await db.execute(select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.idempotency_key == key,
            ))
            step = existing.scalar_one_or_none()
            if step is not None and step.status == "COMPLETED":
                run.current_step = sequence
                await db.commit()
                continue
            if step is None:
                step = AgentStep(
                    id=f"agent-step-{uuid.uuid4().hex[:16]}",
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    user_id=run.user_id,
                    sequence=sequence,
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    idempotency_key=key,
                    status="RUNNING",
                )
                db.add(step)
            else:
                step.status = "RUNNING"
                step.error_code = None
                step.error_message = None
                step.started_at = _now()
            await db.commit()

            context = ToolContext(
                db=db,
                run_id=run.id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                conversation_id=run.conversation_id,
                goal=run.goal,
            )
            result = await asyncio.wait_for(
                tool.handler(context, validated_arguments),
                timeout=tool.timeout_seconds,
            )
            validated_result = tool.output_model.model_validate(result)
            summary = validated_result.model_dump(mode="json")
            state = dict(run.working_state)
            if tool_name == "inspect_documents":
                state["inspection"] = summary
            elif tool_name == "calculate_monthly_highest_sales":
                state["analysis"] = summary["analysis"]
            elif tool_name == "create_monthly_sales_xlsx":
                state["artifact"] = summary
                step.result_reference = summary["artifact_id"]
            run.working_state = state
            run.current_step = sequence
            run.updated_at = _now()
            step.result_summary = summary
            step.status = "COMPLETED"
            step.completed_at = _now()
            await db.commit()

        artifact = run.working_state.get("artifact", {})
        analysis = run.working_state.get("analysis", {})
        run.status = "COMPLETED"
        run.completed_at = _now()
        run.final_response = {
            "message": "The monthly highest-sales report was calculated, generated, and validated.",
            "months": len(analysis.get("monthly_highest_sales", [])),
            "selected_revenue_total": analysis.get("metrics", {}).get("monthly_highest_sales_total", 0),
            "artifact_id": artifact.get("artifact_id"),
        }
        await db.commit()
        await record_event_async(
            db,
            tenant_id=run.tenant_id,
            event_name="agent_run_completed",
            emitting_service="agent_runtime",
            actor_id=run.user_id,
            subject_type="agent_run",
            subject_id=run.id,
            correlation_id=run.conversation_id or run.id,
            payload={"task_type": run.task_type, "steps_completed": run.current_step},
        )
    except (AgentToolError, asyncio.TimeoutError, ValueError) as exc:
        code = exc.code if isinstance(exc, AgentToolError) else (
            "TOOL_TIMEOUT" if isinstance(exc, asyncio.TimeoutError) else "INVALID_TOOL_RESULT"
        )
        current = await db.execute(select(AgentStep).where(
            AgentStep.run_id == run.id,
            AgentStep.sequence == run.current_step + 1,
        ))
        failed_step = current.scalar_one_or_none()
        if failed_step is not None:
            failed_step.status = "FAILED"
            failed_step.error_code = code
            failed_step.error_message = str(exc)[:500]
            failed_step.completed_at = _now()
        run.status = "FAILED"
        run.error_code = code
        run.updated_at = _now()
        await db.commit()
    await db.refresh(run)
    return run


async def get_agent_run(
    db: AsyncSession, *, run_id: str, tenant_id: str, user_id: str,
) -> AgentRun | None:
    result = await db.execute(select(AgentRun).where(
        AgentRun.id == run_id,
        AgentRun.tenant_id == tenant_id,
        AgentRun.user_id == user_id,
    ))
    return result.scalar_one_or_none()


async def cancel_agent_run(db: AsyncSession, run: AgentRun, reason: str) -> AgentRun:
    if run.status == "COMPLETED":
        raise HTTPException(status_code=409, detail="A completed agent run cannot be cancelled")
    run.status = "CANCELLED"
    run.error_code = "USER_CANCELLED"
    state = dict(run.working_state)
    state["cancellation_reason"] = reason
    run.working_state = state
    run.updated_at = _now()
    await db.commit()
    await db.refresh(run)
    return run


async def serialize_agent_run(db: AsyncSession, run: AgentRun) -> AgentRunPublic:
    step_rows = await db.execute(select(AgentStep).where(
        AgentStep.run_id == run.id,
        AgentStep.tenant_id == run.tenant_id,
        AgentStep.user_id == run.user_id,
    ).order_by(AgentStep.sequence))
    artifact_rows = await db.execute(select(GeneratedArtifact).where(
        GeneratedArtifact.query_id == run.id,
        GeneratedArtifact.tenant_id == run.tenant_id,
        GeneratedArtifact.user_id == run.user_id,
        GeneratedArtifact.status == "READY",
    ))
    return AgentRunPublic(
        id=run.id,
        goal=run.goal,
        task_type=run.task_type,
        status=run.status,
        risk_level=run.risk_level,
        current_step=run.current_step,
        maximum_steps=run.maximum_steps,
        plan=list(run.plan),
        error_code=run.error_code,
        final_response=run.final_response,
        steps=[AgentStepPublic.model_validate(step) for step in step_rows.scalars().all()],
        artifacts=[
            AgentArtifactPublic(
                id=artifact.id,
                filename=artifact.filename,
                mime_type=artifact.mime_type,
                download_url=f"/kriton-workspace/artifacts/{artifact.id}/download",
            )
            for artifact in artifact_rows.scalars().all()
        ],
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )
