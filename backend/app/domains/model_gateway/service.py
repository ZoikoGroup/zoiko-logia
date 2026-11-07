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
    KRITON_AGENT_SYSTEM_PROMPT,
    GroqAdapter,
)
from app.domains.model_gateway.auxiliary import approved_providers
from app.domains.model_gateway.errors import ProviderAccessBlocked, ProviderRequestRejected
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


_ANSWER_PROVIDERS = ("groq", "gemini", "openai")
_PROVIDER_KEYS = {"groq": ("GROQ_API_KEY",), "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
                  "openai": ("OPENAI_API_KEY",)}


def _answer_order() -> list[str]:
    """Answering providers in preference order: MODEL_GATEWAY_PRIMARY_PROVIDER
    (Groq by default) first, the others as fallbacks only. Having a key is not
    a reason to answer first: a Gemini key used to make Gemini the answering
    provider and switch the agent loop off."""
    primary = (get_settings().MODEL_GATEWAY_PRIMARY_PROVIDER or "").strip().lower()
    head = [primary] if primary in _ANSWER_PROVIDERS else []
    return head + [name for name in _ANSWER_PROVIDERS if name not in head]


def _configured_names() -> list[str]:
    """Providers this deployment approved (ZL-ENG-AGT-01 §11.5,
    auxiliary.approved_providers) AND has credentials for, in answer order."""
    approved = approved_providers()
    return [name for name in _answer_order()
            if name in approved and any(os.environ.get(key) for key in _PROVIDER_KEYS[name])]


def _adapter(name: str):
    return {"groq": GroqAdapter, "gemini": GeminiAdapter, "openai": OpenAIAdapter}[name]()


def _provider_name(adapter) -> str:
    return type(adapter).__name__.replace("Adapter", "").lower()


def answering_provider() -> str:
    """The provider that answers first ("mock" when none is configured)."""
    names = _configured_names()
    return names[0] if names else "mock"


def _select_adapter():
    """Provider selection: the first configured provider in answer order,
    mock only as the last resort when no provider is configured at all.
    Not yet driven by ModelDefinition.provider per-model routing (§ZL-T0-08
    envisions Application -> Query Orchestrator -> Model Gateway -> Provider
    Adapter -> Approved Model Deployment, selecting per model_definitions
    row) — this is a flat "first configured provider wins" default until a
    real per-model routing decision is wired to run_test_prompt's caller.
    The others are fallbacks — see _complete_with_fallback.
    """
    names = _configured_names()
    return _adapter(names[0]) if names else MockProviderAdapter()


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

def _configured_adapters() -> list:
    """Every real provider this deployment approves AND has credentials for, in
    answer order. A provider missing here is never selected, even as a
    fallback (§11.5, auxiliary.approved_providers)."""
    return [_adapter(name) for name in _configured_names()]


def _note_provider(adapter, *, answered: bool) -> None:
    # Imported here: the gateway records into the request's run, if any.
    from app.orchestration.workflow_state import note_model_provider
    note_model_provider(_provider_name(adapter), answered=answered)


def _provider_candidates(primary) -> list:
    """The primary adapter first, then every other configured provider once, so
    a blocked or failing provider is skipped for a working one."""
    candidates = [primary]
    for adapter in _configured_adapters():
        if any(
            isinstance(adapter, type(existing)) or isinstance(existing, type(adapter))
            for existing in candidates
        ):
            continue
        candidates.append(adapter)
    return candidates


async def _complete_with_fallback(prompt: str, model: str | None = None) -> str:
    output, _ = await _complete_with_provider(prompt, model)
    return output


async def _complete_with_provider(prompt: str, model: str | None = None) -> tuple[str, str]:
    """(answer, name of the provider that gave it). Answer through the first
    configured provider that works, falling back to
    the others in preference order.

    Adapters fail soft by returning an "[Error…]" string, or raise a typed
    ProviderRequestRejected. A transient failure on one provider moves on to
    the next. An account spending-limit block (ProviderAccessBlocked), which no
    retry or model switch on that provider can clear, also moves on to the
    next provider at once; if every provider is blocked, that typed error is
    raised so the caller shows its specific message. Any other typed failure
    (request too large, authentication, rate limit) propagates unchanged.

    The `model` override is a Groq-specific fast-model name, so it is only
    forwarded to adapters that accept a Groq-style model id. The raw error
    detail — which can include account identifiers and provider-internal
    rate-limit text — never reaches a composed answer: this is the one choke
    point every caller goes through."""
    primary = _select_adapter()

    async def bounded_complete(provider, selected_model: str | None) -> str:
        # A Gemini answer must not receive a Groq model id.
        forward = None if isinstance(provider, GeminiAdapter) else selected_model
        try:
            output = await asyncio.wait_for(
                _try_complete(provider, prompt, forward),
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

    blocked: ProviderAccessBlocked | None = None
    last_provider = type(primary).__name__
    for adapter in _provider_candidates(primary):
        last_provider = type(adapter).__name__
        try:
            output = await bounded_complete(adapter, model)
            if _invalid_output(output) and not isinstance(adapter, GeminiAdapter) and model:
                # The fast model intermittently returns an empty answer on long
                # prompts; the user saw "could not compose a response". The main
                # model answers the same prompt, so try it once before moving on.
                logger.warning("Fast answer model %s failed; retrying with the main model", model)
                output = await bounded_complete(adapter, None)
        except ProviderAccessBlocked as failure:
            # Not transient and account-wide: do not retry this provider's
            # other model, just try the next provider.
            blocked = failure
            logger.warning("%s blocked: account spend limit reached", last_provider)
            _note_provider(adapter, answered=False)
            continue
        except Exception:
            _note_provider(adapter, answered=False)
            raise
        if not _invalid_output(output):
            _note_provider(adapter, answered=True)
            return output, _provider_name(adapter)
        _note_provider(adapter, answered=False)

    if blocked is not None:
        raise blocked
    # Every provider available has failed (a timeout or an "[Error…]" string).
    # Raise rather than return text: a return value here is contractually an
    # ANSWER, and a failure sentinel written as text can slip into a composed
    # answer downstream. Callers that surface text to users translate this into
    # the clean message themselves.
    raise RuntimeError(
        "Repeated provider failures: failed to generate an answer "
        f"(last provider: {last_provider})"
    )


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
    except ProviderRequestRejected:
        raise
    except RuntimeError:
        # The gateway raises once every provider has failed; its callers that
        # hand text to users translate that into the one clean, generic
        # message (never the raw provider "[Error…]" string).
        return _PROVIDER_FAILURE_MESSAGE


async def run_optional_completion(input_text: str, model: str | None = None) -> str:
    """A failed repair must leave the existing answer for verification."""
    try:
        return await run_grounded_completion(input_text, model)
    except ProviderRequestRejected:
        return ''


class AgentUnavailable(RuntimeError):
    """Agent mode can't run for this request; use the standard path."""


_default_registry: ToolRegistry | None = None


def _tool_registry() -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry(
            batch_calculations=bool(getattr(get_settings(), "AGENT_BATCH_CALCULATIONS", False)))
    return _default_registry


def tool_registry() -> ToolRegistry:
    """The production tool registry (shared with the per-step policy check)."""
    return _tool_registry()


def agent_mode_status() -> dict:
    """Whether the governed agent loop is on, and if not, exactly why, so it
    can never be switched off silently (ZL-ENG-AGT-01 §05)."""
    reasons = []
    if not get_settings().KRITON_AGENT_MODE:
        reasons.append("KRITON_AGENT_MODE is not true")
    if not os.environ.get("GROQ_API_KEY"):
        reasons.append("GROQ_API_KEY is not set")
    if "groq" not in approved_providers():
        reasons.append("groq is not in MODEL_GATEWAY_APPROVED_PROVIDERS")
    elif answering_provider() != "groq":
        reasons.append(f"{answering_provider()} answers first (MODEL_GATEWAY_PRIMARY_PROVIDER), so the tool loop is off")
    return {"active": not reasons, "reasons": reasons, "tools": tool_registry().names()}


def agent_mode_active() -> bool:
    """Agent mode needs the flag AND Groq as the answering provider — the
    loop speaks the OpenAI-compatible tool-calling API. A fallback provider's
    key (Gemini) does not switch it off; it answers only when Groq fails."""
    return (get_settings().KRITON_AGENT_MODE and bool(os.environ.get("GROQ_API_KEY"))
            and "groq" in approved_providers() and answering_provider() == "groq")


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
    authorize=None,
    request_id: str = "",
    planned_tools: tuple[str, ...] = (),
    stated_facts: str | None = None,
    figure_evidence: str | None = None,
    resume_key: str = "",
    require_evidence: bool = False,
    available_tools: tuple[str, ...] | None = None,
    max_seconds: float | None = None,
    extra_steps: int = 0,
) -> AgentOutcome:
    """Answer through the governed tool-calling loop. Raises on provider
    failure, AgentUnavailable when Groq isn't usable, and RuntimeError on an
    empty answer — the caller falls back to run_grounded_completion()."""
    if "groq" not in approved_providers():
        raise AgentUnavailable("Groq is not an approved provider for this deployment")
    adapter = GroqAdapter()
    if adapter.client is None:
        raise AgentUnavailable("GROQ_API_KEY is not configured")
    settings = get_settings()
    client = adapter.client
    if hasattr(client, "with_options"):
        # Agent retries are governed by its shared generation budget.
        client = client.with_options(max_retries=0)
    limits = AgentLimits(
        # A long request with many deliverables may use a few more steps;
        # the time budget (max_seconds) is unchanged, so latency stays capped.
        max_steps=settings.AGENT_MAX_STEPS + extra_steps,
        max_tool_calls=settings.AGENT_MAX_TOOL_CALLS + (extra_steps + 2 if extra_steps else 0),
        max_seconds=min(settings.AGENT_MAX_SECONDS, max_seconds) if max_seconds else settings.AGENT_MAX_SECONDS,
        max_total_tokens=settings.AGENT_MAX_TOKENS,
        max_completion_tokens=settings.AGENT_MAX_COMPLETION_TOKENS,
        max_request_tokens=settings.AGENT_MAX_REQUEST_TOKENS,
        max_cost_usd=settings.AGENT_MAX_COST_USD,
        price_per_million_tokens=settings.MODEL_PRICE_PER_MILLION_TOKENS,
    )
    outcome = await run_agent(
        client,
        model=model or GROQ_DEFAULT_MODEL,
        system_prompt=KRITON_AGENT_SYSTEM_PROMPT,
        user_prompt=input_text,
        registry=_tool_registry(),
        granted_permissions=granted_permissions,
        limits=limits,
        on_tool_start=on_tool_start,
        on_tool_done=on_tool_done,
        chart_requested=chart_requested,
        latest_fx_required=latest_fx_required,
        source_ref_offset=source_ref_offset,
        authorize=authorize,
        request_id=request_id,
        planned_tools=planned_tools,
        stated_facts=stated_facts,
        figure_evidence=figure_evidence,
        resume_key=resume_key,
        require_evidence=require_evidence,
        available_tools=available_tools,
    )
    if not outcome.text.strip():
        raise RuntimeError("Agent produced an empty answer")
    # A failed loop is not a provider failover: the caller retries on the
    # standard path, which records its own provider.
    _note_provider(adapter, answered=True)
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

    # Model Gateway -> Provider Adapter -> Approved Model: the primary provider
    # (Groq by default) with the other configured providers as fallbacks,
    # MockProviderAdapter only when no provider API key is set at all. The
    # optional per-call `model` override (a Groq fast-model name for low-risk
    # questions) is only applied when Groq actually answers — see
    # _complete_with_provider. The record names the provider that answered,
    # not the one tried first.
    provider_name = _provider_name(_select_adapter())
    full_prompt = f"[{prompt.name} {prompt.version}]\n\n{input_text}"
    try:
        output, provider_name = await _complete_with_provider(full_prompt, model)
    except ProviderRequestRejected:
        raise
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
