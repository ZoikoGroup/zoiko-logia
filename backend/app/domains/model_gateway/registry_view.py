"""
Live view behind the Model & Prompt Registry page.

The model_definitions table is a hand-maintained catalogue; what Kriton
actually calls is decided by environment settings read in the answer path.
This module reports that runtime truth (which model fills which role, whether
its provider is approved and keyed), the system instructions in use, model-run
usage from the audit ledger, and the registry's change history — so the page
can show where the catalogue and the running system disagree.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent
from app.domains.model_gateway.auxiliary import approved_providers
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate

_PROVIDER_KEYS = {
    "groq": ("GROQ_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
}


@dataclass(frozen=True)
class _Role:
    role: str
    provider: str
    setting: str
    default: str
    used_by: str
    fallback_setting: str | None = None


# Defaults mirror the os.getenv(...) calls at each call site.
_ROLES = (
    _Role("Answer model (preferred)", "gemini", "GEMINI_MODEL", "gemini-flash-latest",
          "model_gateway/providers/google_adapter.py"),
    _Role("Answer and agent model (fallback)", "groq", "GROQ_MODEL", "openai/gpt-oss-120b",
          "model_gateway/providers/groq_adapter.py, model_gateway/service.py"),
    _Role("Fast answers for low-risk questions", "groq", "GROQ_FAST_ANSWER_MODEL", "openai/gpt-oss-20b",
          "orchestration/service.py"),
    _Role("Claim verifier", "groq", "GROQ_VERIFIER_MODEL", "openai/gpt-oss-120b",
          "orchestration/claim_verification.py", fallback_setting="GROQ_MODEL"),
    _Role("Risk classifier", "groq", "GROQ_CLASSIFIER_MODEL", "llama-3.1-8b-instant",
          "orchestration/risk_llm.py classify_risk"),
    _Role("Risk classifier (fallback)", "gemini", "GEMINI_CLASSIFIER_MODEL", "gemini-flash-lite-latest",
          "orchestration/risk_llm.py classify_risk_gemini", fallback_setting="GEMINI_MODEL"),
    _Role("Query classifier", "groq", "GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b",
          "orchestration/query_classifier_llm.py"),
)


def _resolve(role: _Role) -> tuple[str, str]:
    value = os.getenv(role.setting)
    if value:
        return value, role.setting
    if role.fallback_setting and os.getenv(role.fallback_setting):
        return os.environ[role.fallback_setting], role.fallback_setting
    return role.default, "default"


def runtime_models() -> list[dict]:
    approved = approved_providers()
    rows = []
    for role in _ROLES:
        model, source = _resolve(role)
        key_configured = any(os.getenv(name) for name in _PROVIDER_KEYS.get(role.provider, ()))
        rows.append({
            "role": role.role,
            "provider": role.provider,
            "model": model,
            "setting": role.setting,
            "source": source,
            "provider_approved": role.provider in approved,
            "key_configured": key_configured,
            "active": key_configured and role.provider in approved,
            "used_by": role.used_by,
        })

    from app.domains.source_library.embeddings import _DEFAULT_MODEL as EMBEDDING_DEFAULT
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()
    rows.append({
        "role": "Embeddings (semantic retrieval)",
        "provider": "self_hosted",
        "model": os.getenv("EMBEDDING_MODEL", EMBEDDING_DEFAULT) or EMBEDDING_DEFAULT,
        "setting": "EMBEDDING_MODEL",
        "source": "EMBEDDING_MODEL" if os.getenv("EMBEDDING_MODEL") else "default",
        "provider_approved": True,
        "key_configured": True,
        "active": embedding_provider == "local",
        "used_by": "source_library/embeddings.py",
    })
    return rows


def _instruction(name: str, used_by: str, text: str) -> dict:
    return {
        "name": name,
        "used_by": used_by,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "characters": len(text),
        "text": text,
    }


def system_instructions() -> list[dict]:
    from app.domains.model_gateway.agent import AGENT_TOOL_INSTRUCTIONS
    from app.domains.model_gateway.providers.groq_adapter import KRITON_SYSTEM_PROMPT
    from app.orchestration import claim_verification, query_classifier_llm, risk_llm

    return [
        _instruction("Kriton answer system prompt", "Gemini and Groq answer adapters", KRITON_SYSTEM_PROMPT),
        _instruction("Agent tool instructions", "Agent mode (appended to the grounded prompt)", AGENT_TOOL_INSTRUCTIONS),
        _instruction("Claim verifier", "orchestration/claim_verification.py", claim_verification._SYSTEM),
        _instruction("Risk classifier", "orchestration/risk_llm.py", risk_llm._SYSTEM),
        _instruction("Query classifier", "orchestration/query_classifier_llm.py", query_classifier_llm._SYSTEM),
    ]


def active_adapter() -> str:
    from app.domains.model_gateway.service import _select_adapter

    return type(_select_adapter()).__name__.replace("Adapter", "")


async def usage(db: AsyncSession, *, tenant_id: str) -> dict:
    provider = AuditEvent.payload["provider"].as_string()
    by_provider = (
        await db.execute(
            select(provider, func.count(), func.max(AuditEvent.event_time))
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.event_name == "model_run_completed")
            .group_by(provider)
        )
    ).all()
    by_prompt = (
        await db.execute(
            select(AuditEvent.subject_id, func.count(), func.max(AuditEvent.event_time))
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.event_name == "model_run_completed")
            .group_by(AuditEvent.subject_id)
        )
    ).all()
    return {
        "by_provider": sorted(
            ({"provider": name or "unknown", "runs": count, "last_run": last} for name, count, last in by_provider),
            key=lambda row: -row["runs"],
        ),
        "by_prompt": {prompt_id: {"runs": count, "last_run": last} for prompt_id, count, last in by_prompt},
    }


def match_registry(models: list[ModelDefinition], runtime: list[dict]) -> dict[str, list[str]]:
    """Registry row id → runtime roles it fills (matched on model id)."""
    by_model: dict[str, list[str]] = {}
    for row in runtime:
        if row["active"]:
            by_model.setdefault(row["model"].lower(), []).append(row["role"])
    matches = {}
    for model in models:
        roles = by_model.get((model.version or "").lower()) or by_model.get((model.name or "").lower()) or []
        matches[model.id] = roles
    return matches


async def change_history(db: AsyncSession, *, tenant_id: str, limit: int = 30) -> list[dict]:
    """Prompt approvals from the audit ledger, newest first. Evaluation runs
    and release decisions are listed in Evaluation Gates, not repeated here."""
    approvals = (
        await db.execute(
            select(AuditEvent.event_time, AuditEvent.actor_id, AuditEvent.payload)
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.event_name == "prompt_template_approved")
            .order_by(AuditEvent.event_time.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "time": time.isoformat() if time else None,
            "kind": "prompt_approved",
            "summary": f"Prompt {payload.get('prompt_name', '')} {payload.get('version', '')} approved".strip(),
            "actor": payload.get("approved_by") or actor,
        }
        for time, actor, payload in approvals
    ]


async def registry_overview(db: AsyncSession, *, tenant_id: str) -> dict:
    models = list((await db.execute(select(ModelDefinition))).scalars().all())
    prompts = list((await db.execute(select(PromptTemplate))).scalars().all())
    runtime = runtime_models()
    matches = match_registry(models, runtime)
    return {
        "active_adapter": active_adapter(),
        "approved_providers": sorted(approved_providers()),
        "runtime_models": runtime,
        "registry_matches": matches,
        "unused_registry_models": [model.id for model in models if not matches.get(model.id)],
        "prompt_count": len(prompts),
        "usage": await usage(db, tenant_id=tenant_id),
    }
