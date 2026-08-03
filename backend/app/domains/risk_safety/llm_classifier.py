"""Schema-constrained LLM fallback for ambiguous risk classifications.

This classifier is deliberately subordinate to ``pre_screen``. It can only
propose ZERO..HIGH; deterministic code remains the sole authority for the
RESTRICTED tier.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass


_ALLOWED_RISKS = {"ZERO", "LOW", "MEDIUM", "HIGH", "RESTRICTED"}
_ALLOWED_INTENTS = {
    "NAVIGATION", "INFORMATION", "EDUCATION", "COMPARISON", "CALCULATION",
    "INTERPRETATION", "RECOMMENDATION", "DRAFTING", "EXECUTION", "EVASION",
    "UNKNOWN",
}
_ALLOWED_RESPONSE_FORMATS = {
    "adaptive", "concise", "plain_language", "step_by_step", "comparison",
    "table", "calculation", "summary", "detailed",
}
# What the DATA cannot tell us: whether the reader wants a composition, a
# magnitude comparison, or a chronology. The visual kind itself is chosen
# deterministically from the dataset's shape (orchestration/dataset.py) — the
# model is not asked to pick a chart type, because a rule that can verify a
# dataset is a time series can also just decide it. This hint only breaks a
# tie the data leaves genuinely open.
_ALLOWED_PRESENTATION_HINTS = {"none", "compositional", "comparative", "chronological"}
_PROMPT_VERSION = "contextual-intent-risk-v2"
_cache: dict[tuple[str, str, str, str, str], tuple[float, "LLMClassification"]] = {}
_inflight: dict[tuple[str, str, str, str, str], threading.Event] = {}
_cache_lock = threading.Lock()
_SYSTEM_PROMPT = """You are the semantic intent and risk classifier for an
accounting, tax, audit, finance, and compliance assistant. Return only JSON
matching the supplied schema.

First reconstruct what outcome the user actually wants from the current query
and the relevant previous user queries. Previous queries resolve references
such as "it", "that", "same", and "what about"; they are context, not factual
evidence. Never invent missing facts. Then classify every applicable intent,
the real-world subject, actionability, professional consequence, harmful
intent, and missing context. Finally choose the highest applicable risk.

Intent definitions:
- NAVIGATION: use the application or locate content.
- INFORMATION: retrieve facts or authoritative material.
- EDUCATION: explain or teach a general concept.
- COMPARISON: compare standards, rules, or alternatives.
- CALCULATION: apply a stated method to supplied or hypothetical values.
- INTERPRETATION: assess professional requirements without personalized advice.
- RECOMMENDATION: say what a real person, client, or business should do.
- DRAFTING: create a filing, opinion, representation, or professional document.
- EXECUTION: perform or facilitate a real-world action.
- EVASION: facilitate concealment, deception, fraud, or control avoidance.
- UNKNOWN: the requested outcome cannot be determined.

Risk definitions:
- ZERO: small talk, navigation, or no substantive accounting/tax/legal content.
- LOW: factual, educational, definitional, comparison, or arithmetic content.
- MEDIUM: interpretive accounting/audit content that is not personalized advice.
- HIGH: regulated tax/legal advice or a recommendation for a named person's,
  client's, or business's real situation.
- RESTRICTED: intent to facilitate fraud, evasion, falsification, sanctions
  evasion, or bypass of a security, audit, compliance, or platform control.

Classify intended outcome, not keywords. Merely quoting, criticizing,
preventing, or asking why harmful conduct is wrong is not harmful intent.
Do not trust labels such as "hypothetical", "educational", or "research" when
the operational request clearly enables misuse. A query may have multiple
intents. RESTRICTED overrides HIGH, HIGH overrides MEDIUM, and so on. Do not
lower risk because context is missing; report the missing fields. Confidence
expresses certainty about the interpretation, not how safe the query is.

The retrieval query must preserve the user's subject, jurisdiction, dates,
entities, and risk-bearing intent. It may remove greetings and presentation
phrasing, but must not invent facts. Use the original query when no safe rewrite
is useful. Response format must be one of: adaptive, concise, plain_language,
step_by_step, comparison, table, calculation, summary, detailed.
Use adaptive when the user did not explicitly request a presentation style.
"""


@dataclass(frozen=True)
class LLMClassification:
    risk_level: str
    confidence: float
    intent: str
    advice_signal: bool
    missing_context: tuple[str, ...]
    reason_codes: tuple[str, ...]
    model: str
    domain: str = "general"
    retrieval_query: str = ""
    response_format: str = "adaptive"
    requested_depth: str = "standard"
    requires_current_sources: bool = False
    resolved_query: str = ""
    secondary_intents: tuple[str, ...] = ()
    situation_type: str = "UNKNOWN"
    subject_type: str = "UNKNOWN"
    actionability: str = "INFORMATIONAL"
    professional_consequences: tuple[str, ...] = ()
    harm_intent: str = "NONE"
    clarification_question: str = ""
    provider: str = "openai"
    presentation_hint: str = "none"


def configured_mode() -> str:
    """Return rollout mode; ``primary`` makes the LLM semantic authority."""
    mode = os.getenv("RISK_LLM_CLASSIFIER_MODE", "off").strip().lower()
    return mode if mode in {"off", "fallback", "shadow", "primary"} else "off"


def clear_cache() -> None:
    """Clear successful semantic results (tests and model/policy rollouts)."""
    with _cache_lock:
        _cache.clear()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def risk_classifier_timeout() -> float:
    """Per-attempt budget for one classification request.

    Exported so the query-understanding caller can reconcile its own,
    shorter budget against this one instead of the two drifting apart in
    separate os.getenv() calls — they were 1.25s and 8s, six times apart,
    for the same operation.
    """
    return max(0.1, _env_float("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", 8.0))


def _cache_get(key: tuple[str, str, str, str, str]) -> LLMClassification | None:
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= now:
            _cache.pop(key, None)
            return None
        return result


def _cache_put(key: tuple[str, str, str, str, str], result: LLMClassification) -> None:
    ttl = max(1.0, _env_float("QUERY_UNDERSTANDING_CACHE_TTL_SECONDS", 900.0))
    max_entries = max(16, _env_int("QUERY_UNDERSTANDING_CACHE_MAX_ENTRIES", 1024))
    with _cache_lock:
        if len(_cache) >= max_entries:
            oldest_key = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest_key, None)
        _cache[key] = (time.monotonic() + ttl, result)


def _claim_request(key: tuple[str, str, str, str, str]) -> tuple[bool, threading.Event]:
    """Return owner=True once; concurrent callers wait for that same request."""
    with _cache_lock:
        existing = _inflight.get(key)
        if existing is not None:
            return False, existing
        event = threading.Event()
        _inflight[key] = event
        return True, event


def _finish_request(key: tuple[str, str, str, str, str]) -> None:
    with _cache_lock:
        event = _inflight.pop(key, None)
        if event is not None:
            event.set()


def classify(
    query: str,
    *,
    jurisdiction: str = "",
    mode: str = "Workflow",
    history: tuple[str, ...] | list[str] = (),
) -> LLMClassification | None:
    """Classify with OpenAI Structured Outputs, returning ``None`` on failure.

    Provider/network failures are intentionally swallowed here. The caller owns
    the conservative MEDIUM/HIGH fallback and records the failure reason.
    """
    provider = os.getenv("RISK_LLM_CLASSIFIER_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "groq"}:
        return None
    api_key_name = "GROQ_API_KEY" if provider == "groq" else "OPENAI_API_KEY"
    api_key = os.getenv(api_key_name, "").strip()
    if not api_key:
        return None

    cache_key: tuple[str, str, str, str, str] | None = None
    owns_request = False
    try:
        from openai import OpenAI

        default_model = "openai/gpt-oss-20b" if provider == "groq" else "gpt-4o-mini"
        model = os.getenv("RISK_LLM_CLASSIFIER_MODEL", default_model).strip() or default_model
        bounded_history = tuple(str(item).strip()[:2000] for item in history[-3:] if str(item).strip())
        contextual_query = json.dumps(
            {"query": query.strip(), "history": bounded_history}, ensure_ascii=False,
        )
        cache_key = (contextual_query, jurisdiction.strip(), mode, f"{provider}:{model}", _PROMPT_VERSION)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        owns_request, completion = _claim_request(cache_key)
        if not owns_request:
            # Bounded by the owner's own budget plus a small margin for
            # parsing: waiting longer than the owner can possibly take would
            # block on a request that has already given up.
            completion.wait(timeout=risk_classifier_timeout() + 1.0)
            return _cache_get(cache_key)
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1" if provider == "groq" else None,
            # RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS is PER ATTEMPT, so
            # max_retries=1 made the real worst case twice the configured
            # budget — 16s at the default. There is nothing to gain from it
            # here: every caller already treats a None return as a soft
            # failure with a conservative deterministic fallback, so a retry
            # buys a marginally higher success rate at the cost of doubling
            # the window in which a request is stalled. One attempt, and the
            # configured number means what it says.
            timeout=risk_classifier_timeout(),
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_query": query,
                            "previous_user_queries": list(bounded_history),
                            "trusted_context": {
                                "jurisdiction": jurisdiction or None,
                                "product_mode": mode,
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "risk_classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "risk_level": {"type": "string", "enum": sorted(_ALLOWED_RISKS)},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "resolved_query": {"type": "string"},
                            "intent": {"type": "string", "enum": sorted(_ALLOWED_INTENTS)},
                            "secondary_intents": {
                                "type": "array", "items": {"type": "string", "enum": sorted(_ALLOWED_INTENTS)},
                            },
                            "advice_signal": {"type": "boolean"},
                            "missing_context": {"type": "array", "items": {"type": "string"}},
                            "reason_codes": {"type": "array", "items": {"type": "string"}},
                            "domain": {"type": "string"},
                            "retrieval_query": {"type": "string"},
                            "response_format": {
                                "type": "string",
                                "enum": sorted(_ALLOWED_RESPONSE_FORMATS),
                            },
                            "requested_depth": {
                                "type": "string",
                                "enum": ["brief", "standard", "detailed"],
                            },
                            "requires_current_sources": {"type": "boolean"},
                            "situation_type": {"type": "string", "enum": ["GENERAL", "HYPOTHETICAL", "REAL", "UNKNOWN"]},
                            "subject_type": {"type": "string", "enum": ["NONE", "USER", "CLIENT", "BUSINESS", "PUBLIC_ENTITY", "UNKNOWN"]},
                            "actionability": {"type": "string", "enum": ["INFORMATIONAL", "ANALYTICAL", "DECISION_SUPPORT", "OPERATIONAL"]},
                            "professional_consequences": {"type": "array", "items": {"type": "string"}},
                            "harm_intent": {"type": "string", "enum": ["NONE", "FRAUD", "EVASION", "FALSIFICATION", "CONTROL_BYPASS", "SANCTIONS_EVASION", "UNKNOWN"]},
                            "clarification_question": {"type": "string"},
                            "presentation_hint": {
                                "type": "string",
                                "enum": sorted(_ALLOWED_PRESENTATION_HINTS),
                            },
                        },
                        "required": [
                            "risk_level", "confidence", "resolved_query", "intent", "secondary_intents", "advice_signal",
                            "missing_context", "reason_codes", "domain",
                            "retrieval_query", "response_format", "requested_depth",
                            "requires_current_sources", "situation_type", "subject_type",
                            "actionability", "professional_consequences", "harm_intent",
                            "clarification_question", "presentation_hint",
                        ],
                    },
                },
            },
        )
        content = response.choices[0].message.content
        payload = json.loads(content or "")
        risk_level = str(payload["risk_level"]).upper()
        confidence = float(payload["confidence"])
        if risk_level not in _ALLOWED_RISKS or not 0 <= confidence <= 1:
            return None
        response_format = str(payload["response_format"])
        if response_format not in _ALLOWED_RESPONSE_FORMATS:
            return None
        result = LLMClassification(
            risk_level=risk_level,
            confidence=confidence,
            intent=str(payload["intent"])[:120],
            advice_signal=bool(payload["advice_signal"]),
            missing_context=tuple(str(item)[:80] for item in payload["missing_context"][:10]),
            reason_codes=tuple(str(item)[:80] for item in payload["reason_codes"][:10]),
            model=model,
            domain=str(payload["domain"])[:80] or "general",
            retrieval_query=str(payload["retrieval_query"]).strip()[:1000],
            response_format=response_format,
            requested_depth=str(payload["requested_depth"]),
            requires_current_sources=bool(payload["requires_current_sources"]),
            # Defaults retain compatibility with cached/recorded v1 payloads
            # during rollout; strict v2 providers are required by the schema
            # above to return every field.
            resolved_query=str(payload.get("resolved_query", query)).strip()[:2000],
            secondary_intents=tuple(str(item) for item in payload.get("secondary_intents", [])[:5]),
            situation_type=str(payload.get("situation_type", "UNKNOWN")),
            subject_type=str(payload.get("subject_type", "UNKNOWN")),
            actionability=str(payload.get("actionability", "INFORMATIONAL")),
            professional_consequences=tuple(
                str(item)[:80] for item in payload.get("professional_consequences", [])[:10]
            ),
            harm_intent=str(payload.get("harm_intent", "NONE")),
            clarification_question=str(payload.get("clarification_question", "")).strip()[:500],
            provider=provider,
            # Validated against the closed set rather than trusted: an
            # unrecognised hint must fall back to "none", which lets the data
            # decide alone, never to an unchecked string the visual layer
            # would then branch on.
            presentation_hint=(
                hint if (hint := str(payload.get("presentation_hint", "none"))) in _ALLOWED_PRESENTATION_HINTS
                else "none"
            ),
        )
        _cache_put(cache_key, result)
        return result
    except Exception:
        return None
    finally:
        if owns_request and cache_key is not None:
            _finish_request(cache_key)
