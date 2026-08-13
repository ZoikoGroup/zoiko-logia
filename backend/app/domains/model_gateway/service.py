import hashlib
import os

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.model_gateway.providers.mock_adapter import MockProviderAdapter
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.domains.model_gateway.providers.google_adapter import GeminiAdapter
from app.domains.model_gateway.providers.openai_adapter import OpenAIAdapter


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
    raise TypeError — fall back to the no-arg form for them."""
    if model:
        try:
            return await adapter.complete(prompt, model=model)
        except TypeError:
            return await adapter.complete(prompt)
    return await adapter.complete(prompt)


_PROVIDER_FAILURE_MESSAGE = (
    "Kriton is temporarily unable to reach the language model provider. "
    "Please try again in a moment."
)


class ProviderUnavailable(RuntimeError):
    """Every configured provider failed (quota, network, bad model id).

    Raised rather than returned as text. Returning it made a provider outage
    indistinguishable from a composed answer: `composed_text` was non-empty, so
    orchestration's "did the model produce anything?" guard passed, Checkpoint C
    validated the failure notice as if it were prose, and the turn was reported
    as outcome="answered" — carrying a disclaimer, live citations and follow-up
    suggestions around a sentence that answered nothing. Raising routes it to
    orchestration's existing composition_failed handler instead, which audits
    the failure and returns a refusal with no answer body.

    str() is deliberately the clean, generic message and never the provider's
    own text: this propagates into audit records and user-facing copy, and
    provider errors carry account/org identifiers and rate-limit internals. The
    raw string is kept on `.detail` for server-side diagnosis only.
    """

    def __init__(self, detail: str = ""):
        super().__init__(_PROVIDER_FAILURE_MESSAGE)
        self.detail = detail


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
    catch that. It raises ProviderUnavailable rather than returning a message:
    a total provider outage is not an answer, and anything returned here is
    treated downstream as one."""
    adapter = _select_adapter()
    is_gemini = isinstance(adapter, GeminiAdapter)
    # A Gemini answer must not receive a Groq model id — only pass `model`
    # through when the answering adapter is Groq.
    output = await _try_complete(adapter, prompt, None if is_gemini else model)
    if output.startswith("[Error") and is_gemini and os.environ.get("GROQ_API_KEY"):
        output = await _try_complete(GroqAdapter(), prompt, model)
    if output.startswith("[Error"):
        raise ProviderUnavailable(output)
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
    output text, or raises ProviderUnavailable when every provider failed —
    individual adapters still fail soft, but a total outage is surfaced as an
    exception so callers cannot mistake it for an answer. Uses the preferred
    provider with Groq fallback."""
    return await _complete_with_fallback(input_text, model)


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
    output = await _complete_with_fallback(full_prompt, model)

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
