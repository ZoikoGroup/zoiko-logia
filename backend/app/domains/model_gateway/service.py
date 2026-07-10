import hashlib

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.model_gateway.providers.mock_adapter import MockProviderAdapter


async def list_models(db: AsyncSession) -> list[ModelDefinition]:
    result = await db.execute(select(ModelDefinition))
    return list(result.scalars().all())


async def list_prompts(db: AsyncSession) -> list[PromptTemplate]:
    result = await db.execute(select(PromptTemplate))
    return list(result.scalars().all())


async def approve_prompt(
    db: AsyncSession, approver_id: str, prompt_id: str, tenant_id: str = "GLOBAL_CONTROL"
) -> PromptTemplate:
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")

    if prompt.submitted_by == approver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Maker-checker violation: the editor of a prompt template cannot approve it.",
        )

    prompt.status = "Approved"
    prompt.approved_by = approver_id
    await db.commit()
    await db.refresh(prompt)

    await record_event_async(
        db,
        event_name="prompt_template_approved",
        emitting_service="model_gateway",
        subject_type="prompt",
        subject_id=prompt.id,
        actor_id=approver_id,
        tenant_id=tenant_id,
        classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={
            "prompt_name": prompt.name,
            "version": prompt.version,
            "submitted_by": prompt.submitted_by,
            "approved_by": approver_id,
        },
    )
    return prompt


from app.domains.model_gateway.providers.groq_adapter import GroqAdapter


async def run_test_prompt(
    db: AsyncSession,
    prompt_id: str,
    input_text: str,
    actor_id: str | None = None,
    tenant_id: str = "GLOBAL_CONTROL",
    correlation_id: str | None = None,
) -> tuple[PromptTemplate, str]:
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")

    # Model Gateway -> Provider Adapter -> Approved Model
    adapter = GroqAdapter()
    output = adapter.complete(f"[{prompt.name} {prompt.version}]\n\n{input_text}")

    # Store a hash of the output, not the raw text, per the privacy-by-design

    # doctrine (Section 9): raw prompt/output retention depends on risk class,
    # tenant, and provider privacy profile, which isn't decided yet.
    await record_event_async(
        db,
        event_name="model_run_completed",
        emitting_service="model_gateway",
        subject_type="prompt",
        subject_id=prompt.id,
        actor_id=actor_id,
        correlation_id=correlation_id or prompt.id,
        tenant_id=tenant_id,
        classification="INTERNAL",
        replay_relevance="SUPPORTING",
        payload={
            "prompt_name": prompt.name,
            "prompt_version": prompt.version,
            "provider": "mock",
            "input_length": len(input_text),
            "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        },
    )
    return prompt, output
