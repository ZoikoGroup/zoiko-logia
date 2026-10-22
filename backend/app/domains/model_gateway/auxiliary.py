"""The gateway path for Kriton's supporting model calls (ZL-ENG-AGT-01 §11).

Answer generation already goes through model_gateway.service. The smaller
calls around it (risk classification, query classification, claim
verification) used to create provider clients themselves. Every one of them
now goes through complete_auxiliary(), which before anything leaves the
service:

  1. checks the call's purpose is registered and the provider is approved
     for that purpose (unregistered purpose or unapproved provider → refused);
  2. redacts protected data from the user content (ZL-ENG-03 §5.8), unless
     the caller has already done so;
  3. bounds the call with a timeout;
and afterwards logs purpose, provider, model, latency and token counts, never
the content.

Provider SDKs are imported only here and in providers/. Callers that need to
react to provider errors use the aliases below (RateLimitError, …) rather
than importing the SDK. tests/test_model_gateway_single_path.py fails the
build if a provider SDK is imported anywhere else.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

import groq
from groq import AsyncGroq

logger = logging.getLogger("kriton.model_gateway.auxiliary")

Provider = Literal["groq", "gemini"]
Purpose = Literal["risk_classification", "query_classification", "claim_verification", "claim_extraction"]

# Which providers each purpose may use. A purpose missing here cannot call a
# model at all; a provider missing for a purpose is never used for it, even
# as a fallback.
PURPOSE_PROVIDERS: dict[str, frozenset[str]] = {
    "risk_classification": frozenset({"groq", "gemini"}),
    "query_classification": frozenset({"groq"}),
    "claim_verification": frozenset({"groq"}),
    # Pulls the checkable claims out of pasted text (review_mode.py).
    "claim_extraction": frozenset({"groq"}),
}

_API_KEYS = {"groq": ("GROQ_API_KEY",), "gemini": ("GEMINI_API_KEY",)}

# Provider error types, for callers that retry or classify failures.
ProviderError = groq.GroqError
RateLimitError = groq.RateLimitError
RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    groq.APITimeoutError, groq.RateLimitError, groq.InternalServerError, groq.APIConnectionError,
)


class GatewayRefused(RuntimeError):
    """The gateway would not send this call (purpose or provider not approved)."""


class GatewayNotConfigured(GatewayRefused):
    """The approved provider has no credentials configured."""


def approved_providers() -> frozenset[str]:
    """Providers this deployment has approved for data transfer. Set
    MODEL_GATEWAY_APPROVED_PROVIDERS (comma-separated) to narrow it; the
    default matches the providers the answer path already uses."""
    raw = os.environ.get("MODEL_GATEWAY_APPROVED_PROVIDERS", "groq,gemini")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def _api_key(provider: str) -> Optional[str]:
    for name in _API_KEYS.get(provider, ()):
        if os.environ.get(name):
            return os.environ[name]
    return None


def may_use(purpose: str, provider: str) -> bool:
    """Approved for this purpose and configured with credentials."""
    return (provider in PURPOSE_PROVIDERS.get(purpose, frozenset())
            and provider in approved_providers() and _api_key(provider) is not None)


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str
    latency_ms: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


def _authorize(purpose: str, provider: str) -> str:
    if purpose not in PURPOSE_PROVIDERS:
        raise GatewayRefused(f"Unregistered model-call purpose: {purpose}")
    if provider not in PURPOSE_PROVIDERS[purpose]:
        raise GatewayRefused(f"Provider {provider} is not approved for {purpose}")
    if provider not in approved_providers():
        raise GatewayRefused(f"Provider {provider} is not approved for this deployment")
    key = _api_key(provider)
    if key is None:
        raise GatewayNotConfigured(f"Provider {provider} is not configured")
    return key


async def complete_auxiliary(
    *,
    purpose: Purpose,
    model: str,
    system: str,
    user: str,
    provider: Provider = "groq",
    response_format: Optional[dict] = None,
    timeout: Optional[float] = None,
    redact: bool = True,
    extra: Optional[dict[str, Any]] = None,
) -> Completion:
    """Send one supporting call through the gateway. Raises GatewayRefused
    when the call is not allowed, and the provider's own exception types
    (see the aliases above) when the provider fails."""
    api_key = _authorize(purpose, provider)
    if redact:
        from app.orchestration.redaction import redact_for_external_exposure
        user = redact_for_external_exposure(user).redacted_text

    started = time.monotonic()
    if provider == "groq":
        from app.domains.model_gateway.execution import current_budget
        from app.domains.model_gateway.agent_budget import GenerationBudgetExceeded
        from app.domains.model_gateway.errors import RequestBudgetExhausted
        client = AsyncGroq(api_key=api_key, max_retries=0)
        kwargs = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            **({"response_format": response_format} if response_format else {}),
            **(extra or {}),
        )
        budget = current_budget()
        try:
            if budget is not None:
                response = await budget.create(client, seconds=timeout or 25.0, **kwargs)
            else:
                call = client.chat.completions.create(**kwargs)
                response = await (asyncio.wait_for(call, timeout=timeout) if timeout else call)
        except GenerationBudgetExceeded:
            raise RequestBudgetExhausted() from None
        usage = getattr(response, "usage", None)
        result = Completion(
            text=(response.choices[0].message.content or ""),
            provider=provider, model=model, latency_ms=(time.monotonic() - started) * 1000,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
        )
    else:
        text = await _gemini(api_key, model=model, system=system, user=user, timeout=timeout)
        result = Completion(text=text, provider=provider, model=model,
                            latency_ms=(time.monotonic() - started) * 1000)
    logger.info("model call purpose=%s provider=%s model=%s latency_ms=%.0f tokens=%s",
                purpose, provider, model, result.latency_ms, result.total_tokens)
    return result


async def _gemini(api_key: str, *, model: str, system: str, user: str, timeout: Optional[float]) -> str:
    from google import genai
    from google.genai import types

    def _call() -> str:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.0,
                # Gemini flash is a "thinking" model: internal reasoning is
                # billed against max_output_tokens, so a tiny cap returns
                # EMPTY text. 256 leaves room for the thinking plus a short answer.
                max_output_tokens=256,
            ),
        )
        return resp.text or ""

    # google-genai's call is synchronous: run it off the event loop.
    task = asyncio.to_thread(_call)
    return await (asyncio.wait_for(task, timeout=timeout) if timeout else task)
