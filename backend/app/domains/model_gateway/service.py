import asyncio
import hashlib
import logging
import os

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway.agent import AgentLimits, AgentOutcome, ToolDoneHook, ToolStartHook, run_agent
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.model_gateway.providers.mock_adapter import MockProviderAdapter
from app.domains.model_gateway.providers.groq_adapter import (
    _DEFAULT_MODEL as GROQ_DEFAULT_MODEL,
    KRITON_SYSTEM_PROMPT,
    GroqAdapter,
)
from app.domains.model_gateway.tool_registry import ToolRegistry, build_default_registry
from app.domains.model_gateway.providers.google_adapter import GeminiAdapter
from app.domains.model_gateway.providers.openai_adapter import OpenAIAdapter
from app.core.config import get_settings


_provider_slots = asyncio.Semaphore(max(1, get_settings().MODEL_PROVIDER_CONCURRENCY))

logger = logging.getLogger(__name__)
# A chart request now costs two Groq round trips instead of one (propose the
# render_chart call, then get the final prose once the backend has validated
# it — see GroqAdapter._resolve_chart_tool_calls), and a heavier prompt (more
# countries/data) pushes that past 30s in practice: a live 5-country GDP
# comparison measured 37.4s end to end. 60s keeps comfortable headroom under
# router.py's overall ASK_KRITON_TIMEOUT_SECONDS request deadline (105s).
_PROVIDER_TIMEOUT_SECONDS = 60


def _select_adapter():
    """Provider selection: real adapters first (in preference order), mock
    only as the last resort when no provider API key is configured at all.
    Not yet driven by ModelDefinition.provider per-model routing (§ZL-T0-08
    envisions Application -> Query Orchestrator -> Model Gateway -> Provider
    Adapter -> Approved Model Deployment, selecting per model_definitions
    row) — this is a flat "first configured provider wins" default until a
    real per-model routing decision is wired to run_test_prompt's caller.

    Gemini is preferred for answering when configured (generally higher
    answer quality than Llama), with Groq as the fallback — see
    _complete_with_fallback.
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
    raise TypeError — fall back to the no-arg form for them. The call is left
    unbounded here; _complete_with_fallback wraps it in _PROVIDER_TIMEOUT_SECONDS."""
    async with _provider_slots:
        if model:
            try:
                return await adapter.complete(prompt, model=model)
            except TypeError:
                return await adapter.complete(prompt)
        return await adapter.complete(prompt)


def _invalid_output(output: str | None) -> bool:
    return not output or not output.strip() or output.lstrip().startswith("[Error")


_PROVIDER_FAILURE_MESSAGE = (
    "Kriton is temporarily unable to reach the language model provider. "
    "Please try again in a moment."
)


async def _complete_with_fallback(prompt: str, model: str | None = None) -> str:
    """Answer via the preferred provider, and if that provider is Gemini and it
    fails (network blip, quota, bad model id — adapters fail soft with an
    "[Error…]" string), transparently fall back to Groq so the user still gets
    an answer. The `model` override is a Groq-specific fast-model name, so it is
    only forwarded when Groq is the one actually answering.

    If every attempted provider still failed (e.g. Groq itself hit a rate
    limit with no further fallback configured), the raw "[Error…]" string —
    which can include internal account/org identifiers and provider-internal
    rate-limit detail — must never reach the composed answer. This is the one
    choke point every caller goes through, so it's the one place that can
    catch that and swap in a clean, generic message instead."""
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
        except TimeoutError:
            logger.warning(
                "%s answer generation timed out after %ss",
                type(provider).__name__,
                _PROVIDER_TIMEOUT_SECONDS,
            )
            return ""
        if _invalid_output(output):
            logger.warning("%s failed to generate an answer", type(provider).__name__)
            return ""
        return output

    output = await bounded_complete(adapter, None if is_gemini else model)
    if _invalid_output(output) and not is_gemini and model:
        # The fast model intermittently returns an empty answer on long
        # prompts; the user saw "could not compose a response". The main
        # model answers the same prompt, so try it once before failing.
        logger.warning("Fast answer model %s failed; retrying with the main model", model)
        output = await bounded_complete(adapter, None)
    if _invalid_output(output) and is_gemini and os.environ.get("GROQ_API_KEY"):
        logger.warning("Gemini answer generation failed; trying Groq")
        output = await bounded_complete(GroqAdapter(), model)
    if _invalid_output(output):
        # Every provider available has failed (a provider that only returned a
        # timeout or an "[Error…]" string). Raise rather than return text: a
        # return value here is contractually an ANSWER, and a failure sentinel
        # written as text can slip into a composed answer downstream. Callers
        # that surface text to users (run_test_prompt, run_grounded_completion)
        # translate this into the clean user-safe message themselves.
        raise RuntimeError(
            "Repeated provider failures: failed to generate an answer "
            f"(last provider: {type(adapter).__name__})"
        )
    return output


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


async def run_grounded_completion(input_text: str, model: str | None = None) -> str:
    """Direct provider completion with no approved-prompt-template row —
    the fallback used by orchestration when no PromptTemplate is seeded yet,
    so web-grounded answering still works out of the box. Returns the model
    output text (adapters fail soft, returning an error string rather than
    raising). Uses the preferred provider with Groq fallback."""
    try:
        return await _complete_with_fallback(input_text, model)
    except RuntimeError:
        # The gateway raises once every provider has failed; its callers that
        # hand text to users translate that into the one clean, generic
        # message (never the raw provider "[Error…]" string).
        return _PROVIDER_FAILURE_MESSAGE


class AgentUnavailable(RuntimeError):
    """Agent mode can't run for this request; use the standard path."""


_default_registry: ToolRegistry | None = None


def _tool_registry() -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry


def agent_mode_active() -> bool:
    """Agent mode needs the flag AND Groq as the answering provider — the
    loop speaks the OpenAI-compatible tool-calling API, and when Gemini is
    configured it answers instead (see _select_adapter)."""
    gemini_active = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    return get_settings().KRITON_AGENT_MODE and bool(os.environ.get("GROQ_API_KEY")) and not gemini_active


async def run_agentic_completion(
    input_text: str,
    *,
    granted_permissions: frozenset[str],
    model: str | None = None,
    on_tool_start: ToolStartHook | None = None,
    on_tool_done: ToolDoneHook | None = None,
    chart_requested: bool = False,
    latest_fx_required: bool = False,
    source_ref_offset: int = 0,
) -> AgentOutcome:
    """Answer through the governed tool-calling loop. Raises on provider
    failure, AgentUnavailable when Groq isn't usable, and RuntimeError on an
    empty answer — the caller falls back to run_grounded_completion()."""
    adapter = GroqAdapter()
    if adapter.client is None:
        raise AgentUnavailable("GROQ_API_KEY is not configured")
    settings = get_settings()
    outcome = await run_agent(
        adapter.client,
        model=model or GROQ_DEFAULT_MODEL,
        system_prompt=KRITON_SYSTEM_PROMPT,
        user_prompt=input_text,
        registry=_tool_registry(),
        granted_permissions=granted_permissions,
        limits=AgentLimits(
            max_steps=settings.AGENT_MAX_STEPS,
            max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
            max_seconds=settings.AGENT_MAX_SECONDS,
        ),
        on_tool_start=on_tool_start,
        on_tool_done=on_tool_done,
        chart_requested=chart_requested,
        latest_fx_required=latest_fx_required,
        source_ref_offset=source_ref_offset,
    )
    if not outcome.text.strip():
        raise RuntimeError("Agent produced an empty answer")
    return outcome


async def run_test_prompt(
    db: AsyncSession,
    prompt_id: str,
    input_text: str,
    actor_id: str | None = None,
    tenant_id: str = "GLOBAL_CONTROL",
    correlation_id: str | None = None,
    model: str | None = None,
) -> tuple[PromptTemplate, str]:
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found")

    # Model Gateway -> Provider Adapter -> Approved Model. _select_adapter()
    # picks the first configured real provider (Groq, then OpenAI), falling
    # back to MockProviderAdapter only when no provider API key is set at all.
    adapter = _select_adapter()
    provider_name = type(adapter).__name__.replace("Adapter", "").lower()
    full_prompt = f"[{prompt.name} {prompt.version}]\n\n{input_text}"
    # Preferred provider (Gemini when configured) with Groq fallback. The
    # optional per-call `model` override (a Groq fast-model name for low-risk
    # questions) is only applied when Groq actually answers — see
    # _complete_with_fallback.
    try:
        output = await _complete_with_fallback(full_prompt, model)
    except RuntimeError:
        # Every provider failed — the prompt-studio test run surfaces the
        # clean user-safe message, not the raw provider error.
        output = _PROVIDER_FAILURE_MESSAGE

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
            "input_length": len(input_text),
            "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        },
    )
    return prompt, output
