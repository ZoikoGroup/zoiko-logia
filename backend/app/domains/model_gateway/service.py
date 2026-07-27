import hashlib
import os

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway import cost_latency_governance
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.model_gateway.providers.mock_adapter import MockProviderAdapter
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.domains.model_gateway.providers.openai_adapter import OpenAIAdapter
from app.domains.model_gateway.routing_fallback import complete_with_fallback


def _adapter_chain() -> list[tuple[str, object]]:
    """Provider fallback chain, in preference order — real adapters first,
    mock only as the last resort. Every configured provider is included
    (not just the first), so complete_with_fallback() can actually fall
    through to the next one if the first fails at call time — before this,
    _select_adapter() picked exactly one provider with no fallback, so a
    live Groq outage surfaced as a raw error string treated as the model's
    answer, and OpenAI (even if configured) was never tried.

    Not yet driven by ModelDefinition.provider per-model routing (§ZL-T0-08
    envisions Application -> Query Orchestrator -> Model Gateway -> Provider
    Adapter -> Approved Model Deployment, selecting per model_definitions
    row) — this is a flat, fixed preference order until a real per-model
    routing decision is wired to run_test_prompt's caller. Mock is always
    appended last so a request always resolves to something rather than
    an empty chain when no provider is configured.
    """
    chain: list[tuple[str, object]] = []
    if os.environ.get("GROQ_API_KEY"):
        chain.append(("groq", GroqAdapter()))
    if os.environ.get("OPENAI_API_KEY"):
        chain.append(("openai", OpenAIAdapter()))
    chain.append(("mock", MockProviderAdapter()))
    return chain


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

    # Model Gateway -> Provider Adapter -> Approved Model. Tries every
    # configured provider in preference order (Groq, then OpenAI, then
    # Mock as the last resort) — falls through to the next one only if the
    # current one actually fails at call time, not just "isn't configured."
    full_prompt = f"[{prompt.name} {prompt.version}]\n\n{input_text}"
    fallback_result = await complete_with_fallback(full_prompt, _adapter_chain())
    output = fallback_result.output
    provider_name = fallback_result.provider_used
    cost_usd = cost_latency_governance.estimate_cost_usd(provider_name, full_prompt, output)
    cost_latency_governance.record_cost(cost_usd)

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
            "provider": provider_name,
            "provider_attempts": fallback_result.attempts,
            "fallback_occurred": len(fallback_result.attempts) > 1,
            "succeeded": fallback_result.succeeded,
            "latency_ms": round(fallback_result.latency_ms, 1),
            "estimated_cost_usd": cost_usd,
            "input_length": len(input_text),
            "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        },
    )
    return prompt, output
