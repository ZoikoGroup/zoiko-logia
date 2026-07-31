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


_ALLOWED_RISKS = {"ZERO", "LOW", "MEDIUM", "HIGH"}
_ALLOWED_RESPONSE_FORMATS = {
    "adaptive", "concise", "plain_language", "step_by_step", "comparison",
    "table", "calculation", "summary", "detailed",
}
_PROMPT_VERSION = "query-understanding-v1"
_cache: dict[tuple[str, str, str, str, str], tuple[float, "LLMClassification"]] = {}
_inflight: dict[tuple[str, str, str, str, str], threading.Event] = {}
_cache_lock = threading.Lock()
_SYSTEM_PROMPT = """You classify user queries for an accounting education and
professional-advice product. In the same response, identify the user's task,
produce a conservative retrieval query, and specify the requested answer style.
Return only the requested JSON.

Risk definitions:
- ZERO: small talk, navigation, or no substantive accounting/tax/legal content.
- LOW: factual, educational, definitional, comparison, or arithmetic content.
- MEDIUM: interpretive accounting/audit content that is not personalized advice.
- HIGH: regulated tax/legal advice or a recommendation for a named person's,
  client's, or business's real situation.

Never return RESTRICTED. Privacy, security, licence, academic-integrity, and
control-bypass restrictions are enforced by deterministic rules before this
classifier. Do not lower risk because context is missing; report missing
context and choose the conservative applicable tier. Confidence expresses
classification certainty, not how safe the query is.

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


def configured_mode() -> str:
    """Return off, fallback, or shadow; invalid values fail closed to off."""
    mode = os.getenv("RISK_LLM_CLASSIFIER_MODE", "off").strip().lower()
    return mode if mode in {"off", "fallback", "shadow"} else "off"


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


def classify(query: str, *, jurisdiction: str = "", mode: str = "Workflow") -> LLMClassification | None:
    """Classify with OpenAI Structured Outputs, returning ``None`` on failure.

    Provider/network failures are intentionally swallowed here. The caller owns
    the conservative MEDIUM/HIGH fallback and records the failure reason.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    cache_key: tuple[str, str, str, str, str] | None = None
    owns_request = False
    try:
        from openai import OpenAI

        model = os.getenv("RISK_LLM_CLASSIFIER_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        cache_key = (query.strip(), jurisdiction.strip(), mode, model, _PROMPT_VERSION)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        owns_request, completion = _claim_request(cache_key)
        if not owns_request:
            completion.wait(timeout=max(0.1, _env_float("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", 8.0) + 1.0))
            return _cache_get(cache_key)
        client = OpenAI(
            api_key=api_key,
            timeout=_env_float("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", 8.0),
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"query": query, "jurisdiction": jurisdiction or None, "product_mode": mode},
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
                            "intent": {"type": "string"},
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
                        },
                        "required": [
                            "risk_level", "confidence", "intent", "advice_signal",
                            "missing_context", "reason_codes", "domain",
                            "retrieval_query", "response_format", "requested_depth",
                            "requires_current_sources",
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
        )
        _cache_put(cache_key, result)
        return result
    except Exception:
        return None
    finally:
        if owns_request and cache_key is not None:
            _finish_request(cache_key)
