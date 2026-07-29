import hashlib
import os
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.model_gateway import cost_latency_governance
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.model_gateway.providers.base import ProviderAdapter
from app.domains.model_gateway.providers.mock_adapter import MockProviderAdapter
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.domains.model_gateway.providers.openai_adapter import OpenAIAdapter
from app.domains.model_gateway.routing_fallback import complete_with_fallback

# §ZL-T0-08 envisions Application -> Query Orchestrator -> Model Gateway ->
# Provider Adapter -> Approved Model Deployment, selecting per
# model_definitions row. Both roles participate in ranking (not just
# "Primary reasoning model" alone) so a registry row explicitly labeled
# "Secondary / fallback model" (e.g. seeded Claude) actually functions as an
# in-registry fallback instead of being invisible to routing entirely.
_ANSWERING_ROLES = ("Primary reasoning model", "Secondary / fallback model")

# Only providers with a real, importable adapter class go here — anthropic/
# azure/google/self_hosted are one-line stubs with no class defined at all,
# so their absence from this dict *is* the "not implemented" signal; no
# separate enum needs to be kept in sync with providers/*.py's real state.
_IMPLEMENTED_ADAPTER_FACTORIES = {
    "groq": GroqAdapter,
    "openai": OpenAIAdapter,
    "mock": MockProviderAdapter,
}

# No priority/rank column on ModelDefinition — a fixed list gives identical
# ranking to a real column for a registry this size (a handful of rows),
# with zero migration risk. app/main.py's _migrate_*_columns() pattern is
# the escalation path if this ever needs to be admin-editable instead of
# code-editable.
_PROVIDER_PREFERENCE_ORDER = ("groq", "openai", "anthropic", "azure", "google", "self_hosted", "mock")


@dataclass(frozen=True)
class ModelSelection:
    # None only when the registry had no usable candidate at all and the
    # bottom-rung env-var fallback chain answered instead.
    model: Optional[ModelDefinition]
    adapter: ProviderAdapter
    selection_path: str  # "registry" | "fallback_chain"
    skip_trace: tuple = field(default_factory=tuple)


def _adapter_is_configured(adapter) -> bool:
    """GroqAdapter/OpenAIAdapter null out .client in __init__ when their API
    key env var is absent (see providers/groq_adapter.py, openai_adapter.py)
    — reused here instead of re-reading os.environ, so this stays correct if
    either adapter's key source ever changes (e.g. a secrets manager).
    MockProviderAdapter has no .client attribute and is always configured."""
    return getattr(adapter, "client", True) is not None


async def _select_model_and_adapter(db: AsyncSession) -> ModelSelection:
    """Real ModelDefinition-driven routing, replacing the old flat
    "first configured provider wins" _select_adapter(). Keyword match still
    wins in the sense that a real, Active, implemented-provider registry row
    is always preferred — the env-var chain below is strictly a bottom-rung
    fallback for when the registry can't resolve anything at all (empty,
    every row Testing/inactive, or every candidate provider unimplemented/
    unconfigured), so ask_kriton() is never left without a usable adapter.
    """
    result = await db.execute(select(ModelDefinition))
    all_rows = list(result.scalars().all())

    def _rank(row: ModelDefinition) -> tuple:
        role_rank = _ANSWERING_ROLES.index(row.role) if row.role in _ANSWERING_ROLES else len(_ANSWERING_ROLES)
        provider_rank = (
            _PROVIDER_PREFERENCE_ORDER.index(row.provider)
            if row.provider in _PROVIDER_PREFERENCE_ORDER
            else len(_PROVIDER_PREFERENCE_ORDER)
        )
        return (role_rank, provider_rank)

    candidates = sorted((r for r in all_rows if r.role in _ANSWERING_ROLES), key=_rank)

    skip_trace: list = []
    for row in candidates:
        if row.status != "Active":
            skip_trace.append(f"{row.id}({row.provider}): status={row.status!r}, not Active")
            continue
        factory = _IMPLEMENTED_ADAPTER_FACTORIES.get(row.provider)
        if factory is None:
            skip_trace.append(f"{row.id}({row.provider}): provider adapter not implemented")
            continue
        adapter = factory()
        if not _adapter_is_configured(adapter):
            skip_trace.append(f"{row.id}({row.provider}): adapter implemented but not configured (missing API key)")
            continue
        return ModelSelection(model=row, adapter=adapter, selection_path="registry", skip_trace=tuple(skip_trace))

    # Bottom-rung fallback — preserved exactly as the old _select_adapter()'s
    # logic, just reached only when the registry itself couldn't resolve.
    if os.environ.get("GROQ_API_KEY"):
        return ModelSelection(None, GroqAdapter(), "fallback_chain", tuple(skip_trace))
    if os.environ.get("OPENAI_API_KEY"):
        return ModelSelection(None, OpenAIAdapter(), "fallback_chain", tuple(skip_trace))
    return ModelSelection(None, MockProviderAdapter(), "fallback_chain", tuple(skip_trace))


def _fallback_chain_from_selection(selection: ModelSelection) -> list[tuple[str, object]]:
    """Bridges the registry-driven selection above with call-time fallback
    (routing_fallback.py's complete_with_fallback) — the two are
    complementary, not alternatives: _select_model_and_adapter() decides
    which model SHOULD be tried first (respecting Active status, role/
    provider preference, and the registry's own audit trail), but a single
    adapter.complete() call still has no protection against THAT specific
    provider failing at request time (a live Groq outage, a timeout). Every
    other configured, implemented provider not already the primary choice
    is appended in preference order — mock always last — so a call-time
    failure still falls through, the exact gap routing_fallback.py's own
    docstring was written to close (a Groq outage previously surfaced as a
    raw error string treated as the model's own answer, with nothing else
    ever attempted)."""
    primary_name = type(selection.adapter).__name__.replace("Adapter", "").lower()
    chain: list[tuple[str, object]] = [(primary_name, selection.adapter)]
    for provider_name in _PROVIDER_PREFERENCE_ORDER:
        if provider_name == primary_name:
            continue
        factory = _IMPLEMENTED_ADAPTER_FACTORIES.get(provider_name)
        if factory is None:
            continue
        adapter = factory()
        if provider_name != "mock" and not _adapter_is_configured(adapter):
            continue
        chain.append((provider_name, adapter))
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

    # Model Gateway -> Provider Adapter -> Approved Model, driven by the real
    # ModelDefinition registry (see _select_model_and_adapter's docstring)
    # for WHICH model to try first, then wrapped in call-time fallback (see
    # _fallback_chain_from_selection's docstring) so a live failure of that
    # specific provider still falls through to the next configured one
    # instead of surfacing as a raw error string treated as the answer.
    selection = await _select_model_and_adapter(db)
    full_prompt = f"[{prompt.name} {prompt.version}]\n\n{input_text}"
    fallback_result = await complete_with_fallback(full_prompt, _fallback_chain_from_selection(selection))
    output = fallback_result.output
    provider_name = fallback_result.provider_used
    cost_usd = cost_latency_governance.estimate_cost_usd(provider_name, full_prompt, output)
    cost_latency_governance.record_cost(cost_usd)

    # Store a hash of the output, not the raw text, per the privacy-by-design
    # doctrine (Section 9): raw prompt/output retention depends on risk class,
    # tenant, and provider privacy profile, which isn't decided yet.
    payload = {
        "prompt_name": prompt.name,
        "prompt_version": prompt.version,
        "provider": provider_name,
        # provider_attempts/fallback_occurred/succeeded/latency_ms/
        # estimated_cost_usd are the call-time fallback + cost governance
        # audit trail (routing_fallback.py/cost_latency_governance.py) —
        # complementary to model_definition_id/selection_path below, which
        # is the registry-selection audit trail. Together they answer both
        # "which model did the registry pick" and "what actually happened
        # when the gateway tried to reach it."
        "provider_attempts": fallback_result.attempts,
        "fallback_occurred": len(fallback_result.attempts) > 1,
        "succeeded": fallback_result.succeeded,
        "latency_ms": round(fallback_result.latency_ms, 1),
        "estimated_cost_usd": cost_usd,
        "input_length": len(input_text),
        "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        # model_definition_id/selection_path are the concrete, auditable
        # proof this is real per-model registry routing, not flat
        # first-configured-wins — model_definition_id is None only when the
        # bottom-rung fallback_chain path answered instead of the registry.
        "model_definition_id": selection.model.id if selection.model else None,
        "selection_path": selection.selection_path,
    }
    # Only logged on the fallback_chain path — on the healthy registry-driven
    # path this detail has no governance value and would bloat every single
    # event; it only matters when something's actually wrong (empty
    # registry, everything Testing/unimplemented/unconfigured).
    if selection.selection_path == "fallback_chain" and selection.skip_trace:
        payload["fallback_skip_reasons"] = list(selection.skip_trace)

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
        payload=payload,
    )
    return prompt, output
