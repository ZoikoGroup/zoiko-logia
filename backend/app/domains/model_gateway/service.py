import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway.models import ModelDefinition, ModelRun, PromptTemplate
from app.domains.model_gateway.policy import eligible_deployments
from app.domains.model_gateway.schemas import (
    GatewayAttempt, GatewayContext, GatewayResult,
    ModelDefinitionCreate, ModelDefinitionUpdate,
)
from app.domains.model_gateway.providers.mock_adapter import MockProviderAdapter
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.domains.model_gateway.providers.google_adapter import GeminiAdapter
from app.domains.model_gateway.providers.openai_adapter import OpenAIAdapter

logger = logging.getLogger(__name__)
_PROVIDER_TIMEOUT_SECONDS = 30
settings = get_settings()


class GatewayUnavailableError(RuntimeError):
    """No policy-eligible deployment could complete the request."""

    def __init__(self, reason_code: str, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.reason_code = reason_code
        self.retryable = retryable


def _adapter_for_provider(provider: str):
    key = provider.casefold()
    if key in {"google", "gemini"}:
        return GeminiAdapter()
    if key == "groq":
        return GroqAdapter()
    if key == "openai":
        return OpenAIAdapter()
    if key == "mock":
        return MockProviderAdapter()
    raise GatewayUnavailableError(
        "PROVIDER_ADAPTER_UNAVAILABLE", f"No adapter is registered for {provider!r}."
    )


def _provider_failure(output: str | None) -> GatewayUnavailableError | None:
    if output and not output.startswith("[Error"):
        return None
    lowered = (output or "").casefold()
    if "rate" in lowered or "429" in lowered or "quota" in lowered:
        return GatewayUnavailableError(
            "PROVIDER_RATE_LIMITED", "The provider rate-limited the request.", retryable=True
        )
    if "auth" in lowered or "api_key" in lowered or "configured" in lowered:
        return GatewayUnavailableError(
            "PROVIDER_AUTHENTICATION_FAILED", "The provider rejected its configured credentials."
        )
    return GatewayUnavailableError(
        "PROVIDER_INVALID_OUTPUT", "The provider returned no usable output.", retryable=True
    )


def _select_adapter():
    """Provider selection: real adapters first (in preference order), mock
    only as the last resort when no provider API key is configured at all.
    Not yet driven by ModelDefinition.provider per-model routing (§ZL-T0-08
    envisions Application -> Query Orchestrator -> Model Gateway -> Provider
    Adapter -> Approved Model Deployment, selecting per model_definitions
    row) — this is a flat "first configured provider wins" default until a
    real per-model routing decision is wired to run_test_prompt's caller.

    Gemini is preferred for answering when configured (far more reliable at
    emitting the ```chart / ```mermaid blocks than Llama), with Groq as the
    fallback — see _complete_with_fallback.
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return GeminiAdapter()
    if os.environ.get("GROQ_API_KEY"):
        return GroqAdapter()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIAdapter()
    return MockProviderAdapter()


async def _try_complete(adapter, prompt: str, model: str | None) -> str:
    """Call an adapter's complete(), passing an optional per-call model
    override. Adapters whose complete() takes no `model` argument (the mock)
    raise TypeError — fall back to the no-arg form for them."""
    if model:
        try:
            return await adapter.complete(prompt, model=model)
        except TypeError:
            return await adapter.complete(prompt)
    return await adapter.complete(prompt)


async def _complete_with_fallback(prompt: str, model: str | None = None) -> str:
    """Answer via the preferred provider, and if that provider is Gemini and it
    fails (network blip, quota, bad model id — adapters fail soft with an
    "[Error…]" string), transparently fall back to Groq so the user still gets
    an answer. The `model` override is a Groq-specific fast-model name, so it is
    only forwarded when Groq is the one actually answering."""
    adapter = _select_adapter()
    is_gemini = isinstance(adapter, GeminiAdapter)
    # A Gemini answer must not receive a Groq model id — only pass `model`
    # through when the answering adapter is Groq.
    async def bounded_complete(provider, selected_model: str | None) -> str:
        try:
            output = await asyncio.wait_for(
                _try_complete(provider, prompt, selected_model),
                timeout=_PROVIDER_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            logger.warning("%s answer generation timed out after %ss", type(provider).__name__, _PROVIDER_TIMEOUT_SECONDS)
            raise RuntimeError(f"{type(provider).__name__} timed out") from exc
        if not output or output.startswith("[Error"):
            raise RuntimeError(f"{type(provider).__name__} failed to generate an answer")
        return output

    try:
        return await bounded_complete(adapter, None if is_gemini else model)
    except RuntimeError:
        if not (is_gemini and os.environ.get("GROQ_API_KEY")):
            raise
        logger.warning("Gemini answer generation failed; trying Groq")
        return await bounded_complete(GroqAdapter(), model)


async def _record_model_run(
    db: AsyncSession,
    *,
    context: GatewayContext,
    prompt_id: str,
    prompt_version: str,
    attempts: list[GatewayAttempt],
    deployment: ModelDefinition | None,
    status_value: str,
    reason_code: str | None,
    output: str | None,
    error_detail: str | None,
    started_at: datetime,
) -> ModelRun:
    row = ModelRun(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        correlation_id=context.correlation_id,
        deployment_id=deployment.id if deployment else None,
        provider=deployment.provider if deployment else None,
        model_id=deployment.name if deployment else None,
        task_type=context.task_type,
        data_classification=context.data_classification,
        processing_region=context.processing_region,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        policy_version=settings.MODEL_GATEWAY_POLICY_VERSION,
        retrieval_version=context.retrieval_version,
        tool_versions=context.tool_versions,
        requested_tools=context.requested_tools,
        attempts=[item.model_dump() for item in attempts],
        status=status_value,
        reason_code=reason_code,
        output_hash=hashlib.sha256(output.encode("utf-8")).hexdigest() if output else None,
        error_detail=(error_detail or "")[:1000] or None,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def run_policy_completion(
    db: AsyncSession,
    input_text: str,
    context: GatewayContext,
    *,
    prompt_id: str = "inline",
    prompt_version: str = "inline",
) -> GatewayResult:
    """Select and execute only policy-eligible approved deployments.

    Every fallback is filtered by the same policy before any prompt content is
    sent. Raw prompts and outputs are never persisted; the durable run stores
    routing metadata, attempts and an output hash.
    """
    started_at = datetime.now(timezone.utc)
    rows = list((await db.execute(select(ModelDefinition))).scalars().all())
    candidates, decisions = eligible_deployments(rows, context)
    attempts: list[GatewayAttempt] = []
    max_calls = max(1, settings.MODEL_GATEWAY_MAX_PROVIDER_CALLS)

    if not candidates:
        detail = "; ".join(f"{key}:{value}" for key, value in sorted(decisions.items()))
        await _record_model_run(
            db, context=context, prompt_id=prompt_id, prompt_version=prompt_version,
            attempts=attempts, deployment=None, status_value="unavailable",
            reason_code="NO_ELIGIBLE_DEPLOYMENT", output=None,
            error_detail=detail or "No model deployments are registered.", started_at=started_at,
        )
        raise GatewayUnavailableError(
            "NO_ELIGIBLE_DEPLOYMENT", "No approved model deployment is eligible for this request."
        )

    async def execute_candidates() -> tuple[ModelDefinition, str]:
        last_error: GatewayUnavailableError | None = None
        for deployment in candidates[:max_calls]:
            adapter = _adapter_for_provider(deployment.provider)
            try:
                output = await asyncio.wait_for(
                    _try_complete(adapter, input_text, deployment.name),
                    timeout=settings.MODEL_GATEWAY_TIMEOUT_SECONDS,
                )
                failure = _provider_failure(output)
                if failure:
                    raise failure
                attempts.append(GatewayAttempt(
                    deployment_id=deployment.id, provider=deployment.provider,
                    model_id=deployment.name, outcome="completed",
                ))
                return deployment, output
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                last_error = GatewayUnavailableError(
                    "PROVIDER_TIMEOUT", "Provider execution exceeded its deadline.", retryable=True
                )
            except GatewayUnavailableError as exc:
                last_error = exc
            except Exception as exc:
                last_error = GatewayUnavailableError(
                    "PROVIDER_UNAVAILABLE", type(exc).__name__, retryable=True
                )
            attempts.append(GatewayAttempt(
                deployment_id=deployment.id, provider=deployment.provider,
                model_id=deployment.name, outcome="failed",
                reason_code=last_error.reason_code, retryable=last_error.retryable,
            ))
        assert last_error is not None
        raise last_error

    try:
        deployment, output = await asyncio.wait_for(
            execute_candidates(), timeout=settings.MODEL_GATEWAY_TOTAL_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        error = GatewayUnavailableError(
            "GATEWAY_DEADLINE_EXCEEDED", "The total model gateway deadline was exceeded.", retryable=True
        )
        await _record_model_run(
            db, context=context, prompt_id=prompt_id, prompt_version=prompt_version,
            attempts=attempts, deployment=None, status_value="failed",
            reason_code=error.reason_code, output=None, error_detail=error.reason_code,
            started_at=started_at,
        )
        raise error
    except GatewayUnavailableError as error:
        last = candidates[min(len(attempts), len(candidates)) - 1] if attempts else None
        await _record_model_run(
            db, context=context, prompt_id=prompt_id, prompt_version=prompt_version,
            attempts=attempts, deployment=last, status_value="failed",
            reason_code=error.reason_code, output=None, error_detail=error.reason_code,
            started_at=started_at,
        )
        raise

    run = await _record_model_run(
        db, context=context, prompt_id=prompt_id, prompt_version=prompt_version,
        attempts=attempts, deployment=deployment, status_value="completed",
        reason_code="COMPLETED", output=output, error_detail=None, started_at=started_at,
    )
    return GatewayResult(
        output_text=output, run_id=run.id, deployment_id=deployment.id,
        provider=deployment.provider, model_id=deployment.name,
        policy_version=settings.MODEL_GATEWAY_POLICY_VERSION, attempts=attempts,
    )


async def list_models(db: AsyncSession) -> list[ModelDefinition]:
    result = await db.execute(select(ModelDefinition))
    return list(result.scalars().all())


async def list_model_runs(
    db: AsyncSession, *, tenant_id: str, correlation_id: str | None = None,
) -> list[ModelRun]:
    statement = select(ModelRun).where(ModelRun.tenant_id == tenant_id)
    if correlation_id:
        statement = statement.where(ModelRun.correlation_id == correlation_id)
    result = await db.execute(statement.order_by(ModelRun.started_at.desc()).limit(100))
    return list(result.scalars().all())


async def register_model(
    db: AsyncSession, payload: ModelDefinitionCreate, submitter_id: str,
    tenant_id: str = "GLOBAL_CONTROL",
) -> ModelDefinition:
    row = ModelDefinition(
        **payload.model_dump(), status="PendingReview", enabled=False,
        submitted_by=submitter_id, policy_version=settings.MODEL_GATEWAY_POLICY_VERSION,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await record_event_async(
        db, tenant_id=tenant_id, event_name="model_deployment_registered",
        emitting_service="model_gateway", subject_type="model_deployment",
        subject_id=row.id, actor_id=submitter_id, classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={"provider": row.provider, "model_id": row.name, "status": row.status},
    )
    return row


async def update_model(
    db: AsyncSession, model_id: str, payload: ModelDefinitionUpdate, actor_id: str,
    tenant_id: str = "GLOBAL_CONTROL",
) -> ModelDefinition:
    row = (await db.execute(
        select(ModelDefinition).where(ModelDefinition.id == model_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    # Any policy-relevant edit invalidates the prior approval.
    row.status = "PendingReview"
    row.enabled = False
    row.submitted_by = actor_id
    row.approved_by = None
    row.approved_at = None
    row.policy_version = settings.MODEL_GATEWAY_POLICY_VERSION
    await db.commit()
    await db.refresh(row)
    await record_event_async(
        db, tenant_id=tenant_id, event_name="model_deployment_updated",
        emitting_service="model_gateway", subject_type="model_deployment",
        subject_id=row.id, actor_id=actor_id, classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={"status": row.status, "approval_invalidated": True},
    )
    return row


async def approve_model(
    db: AsyncSession, model_id: str, approver_id: str,
    tenant_id: str = "GLOBAL_CONTROL",
) -> ModelDefinition:
    row = (await db.execute(
        select(ModelDefinition).where(ModelDefinition.id == model_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    if row.submitted_by == approver_id:
        raise HTTPException(status_code=403, detail="Maker-checker violation")
    if not row.evaluation_manifest_id or not row.training_opt_out:
        raise HTTPException(
            status_code=409,
            detail="Evaluation manifest and verified training opt-out are required",
        )
    if row.retention_policy.casefold() in {"", "unreviewed"}:
        raise HTTPException(status_code=409, detail="A reviewed retention policy is required")
    row.status = "Approved"
    row.enabled = True
    row.approved_by = approver_id
    row.approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    await record_event_async(
        db, tenant_id=tenant_id, event_name="model_deployment_approved",
        emitting_service="model_gateway", subject_type="model_deployment",
        subject_id=row.id, actor_id=approver_id, classification="INTERNAL",
        replay_relevance="REQUIRED",
        payload={
            "provider": row.provider, "model_id": row.name,
            "evaluation_manifest_id": row.evaluation_manifest_id,
            "policy_version": row.policy_version,
        },
    )
    return row


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


async def run_grounded_completion(
    input_text: str,
    model: str | None = None,
    *,
    db: AsyncSession | None = None,
    gateway_context: GatewayContext | None = None,
) -> str:
    """Direct provider completion with no approved-prompt-template row —
    the fallback used by orchestration when no PromptTemplate is seeded yet,
    so web-grounded answering still works out of the box. Returns the model
    output text. Provider failures raise after the bounded Groq fallback,
    allowing orchestration to return its composition-failed outcome."""
    if settings.MODEL_GATEWAY_POLICY_ENABLED:
        if db is None or gateway_context is None:
            raise GatewayUnavailableError(
                "GATEWAY_CONTEXT_REQUIRED",
                "Policy-driven routing requires a database session and trusted gateway context.",
            )
        result = await run_policy_completion(db, input_text, gateway_context)
        return result.output_text
    return await _complete_with_fallback(input_text, model)


async def run_test_prompt(
    db: AsyncSession,
    prompt_id: str,
    input_text: str,
    actor_id: str | None = None,
    tenant_id: str = "GLOBAL_CONTROL",
    correlation_id: str | None = None,
    model: str | None = None,
    gateway_context: GatewayContext | None = None,
) -> tuple[PromptTemplate, str]:
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")

    # Model Gateway -> Provider Adapter -> Approved Model. _select_adapter()
    # picks the first configured real provider (Groq, then OpenAI), falling
    # back to MockProviderAdapter only when no provider API key is set at all.
    full_prompt = f"[{prompt.name} {prompt.version}]\n\n{input_text}"
    # Preferred provider (Gemini when configured) with Groq fallback. The
    # optional per-call `model` override (a Groq fast-model name for low-risk
    # questions) is only applied when Groq actually answers — see
    # _complete_with_fallback.
    if settings.MODEL_GATEWAY_POLICY_ENABLED:
        if gateway_context is None:
            raise GatewayUnavailableError(
                "GATEWAY_CONTEXT_REQUIRED", "Policy-driven routing requires trusted gateway context."
            )
        gateway_result = await run_policy_completion(
            db, full_prompt, gateway_context,
            prompt_id=prompt.id, prompt_version=prompt.version,
        )
        output = gateway_result.output_text
        provider_name = gateway_result.provider
        deployment_id = gateway_result.deployment_id
        model_id = gateway_result.model_id
        policy_version = gateway_result.policy_version
    else:
        adapter = _select_adapter()
        provider_name = type(adapter).__name__.replace("Adapter", "").lower()
        output = await _complete_with_fallback(full_prompt, model)
        deployment_id = None
        model_id = model
        policy_version = "legacy-key-precedence"

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
            "deployment_id": deployment_id,
            "model_id": model_id,
            "policy_version": policy_version,
            "input_length": len(input_text),
            "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        },
    )
    return prompt, output
