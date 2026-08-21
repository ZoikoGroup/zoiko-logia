"""
Semantic query classification via Groq structured outputs.

Same fail-soft contract as risk_llm.py's classify_risk(): returns None on
any error (missing key, network failure, malformed/non-schema response) so
the caller (query_classifier.py) can fall back to the existing deterministic
classifiers. This module's ONLY job is "query text in, QueryIntent or None
out" — it does not decide routing, does not touch the database, does not
know about ask_kriton().

Uses Groq's JSON-schema structured-output mode (response_format={"type":
"json_schema", ...}) so the model is constrained to the QueryIntent schema
rather than merely prompted to produce it — this is the single most
important reliability lever here, since a bare "return JSON" prompt on a
small fast model routinely drifts (extra fields, wrong enum casing, prose
before the JSON).

Retry policy mirrors app/domains/market_data/http.py's established
convention (that module's own docstring explains the rationale): timeout,
rate limit and 5xx/connection errors are transient and worth one retry with
backoff; auth/request-shape errors are not (retrying a rejected API key or a
malformed request just repeats the same failure).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import groq
from groq import AsyncGroq
from pydantic import ValidationError

from app.orchestration.query_intent import QueryIntent

logger = logging.getLogger("kriton.query_classifier")

_RETRYABLE_ERRORS = (
    groq.APITimeoutError, groq.RateLimitError, groq.InternalServerError,
    groq.APIConnectionError,
)
_MAX_RETRIES = 1
_BACKOFF_SECONDS = 0.4


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def _parse_groq_duration(raw: str) -> Optional[float]:
    """Groq's x-ratelimit-reset-* headers use Go-style duration strings
    ("577ms", "2.5s", "54m43.2s"), not a plain float — a bare float() parse
    silently raises on every real value this header actually sends."""
    matches = _DURATION_PART.findall(raw)
    if not matches:
        return None
    unit_seconds = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(value) * unit_seconds[unit] for value, unit in matches)


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    """Groq's 429 carries how long the caller actually needs to wait —
    x-ratelimit-reset-tokens (a token-bucket reset, typically sub-second to
    a few seconds) or the standard Retry-After header. A blind fixed
    backoff is too short under sustained token-budget pressure (measured:
    this classifier's prompt is large enough that ~30 back-to-back calls
    can exhaust an 8000-token/minute budget) and too long for the common
    case where the bucket is nearly full again already — same rationale as
    market_data/http.py's _retry_after_seconds."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    for header in ("x-ratelimit-reset-tokens", "retry-after"):
        raw = response.headers.get(header)
        if not raw:
            continue
        parsed = _parse_groq_duration(raw)
        if parsed is not None:
            return parsed
    return None

_SYSTEM = (
    "You are the semantic query-understanding layer for Kriton, an "
    "accounting, tax, audit, payroll and finance assistant. Analyze MEANING, "
    "not keywords — a paraphrase with none of the obvious trigger words "
    "(e.g. \"has the burden on UK companies gotten heavier since 2020\" "
    "instead of \"UK corporation tax trend\", or \"the last ten years\" "
    "instead of \"the last 10 years\") must still classify correctly.\n"
    "Return only the fields in the supplied schema.\n\n"
    "domain: the closest single-topic area. GENERAL if it's in-domain but "
    "doesn't fit a narrower one; OUT_OF_SCOPE if the question is not about "
    "accounting, tax, audit, payroll, finance, bookkeeping or commerce at "
    "all (weather, sports, recipes, general programming, etc.) — a "
    "sentence merely SHAPED like an in-domain one (\"X depends on Y\" about "
    "software modules) is still OUT_OF_SCOPE; judge what the named entities "
    "actually are, never the sentence structure.\n"
    "intent: the single best-fitting label. Leave it unset (null) for a "
    "plain factual/definitional/explanatory question with none of the "
    "shapes below — most questions are this, not a chart-shaped one.\n"
    "  TREND: a single measure changing over time.\n"
    "  DISTRIBUTION: how spread out / how variable a set of values is "
    "(words like \"volatile\", \"spread out\", \"how varied\" all count, "
    "not only \"distribution\"/\"histogram\").\n"
    "  CORRELATION vs RELATIONSHIP — the most commonly confused pair, judge "
    "carefully: CORRELATION is a statistical association between two or "
    "more MEASURABLE NUMERIC SERIES (\"does taxable income move with tax "
    "paid?\", \"is inflation associated with interest rates?\") — the "
    "question is about whether two sets of NUMBERS move together. "
    "RELATIONSHIP is a structural/factual connection between named ENTITIES "
    "— ownership, a transaction/document flow, a dependency, an "
    "organizational link — stated or asked about directly (\"Company A owns "
    "Company B\", \"how do the PO, invoice and payment connect?\", \"which "
    "subsidiaries belong to this parent?\"). A giveaway: if answering "
    "requires two numeric series to compare, it's CORRELATION; if it "
    "requires naming entities and how they connect to each other, it's "
    "RELATIONSHIP, even with no \"connected\"/\"network\" wording — \"Company "
    "A owns Company B, and Company B invoices Company C\" is RELATIONSHIP "
    "purely from the owns/invoices structure. Never use RELATIONSHIP merely "
    "because a correlation question also happens to name entities (a "
    "country's inflation and interest rate are numeric series, not "
    "entities). Never use CORRELATION merely because two entities are "
    "linked with no numeric series in question.\n"
    "  COMPOSITION: asks for a real company's ACTUAL, FILED ownership/"
    "shareholding, fetched from a register — not something the user stated "
    "themselves. \"Who owns Barclays?\" and \"what percentage of Barclays is "
    "owned by each shareholder?\" are BOTH COMPOSITION — the user is asking "
    "to look up a real disclosure, not describing entities themselves. "
    "Contrast with RELATIONSHIP's \"Company A owns Company B\": there the "
    "user is STATING the ownership fact directly in their own sentence, not "
    "asking Kriton to go find out who owns a real, named company. The test "
    "is \"fetched real disclosure\" (COMPOSITION) vs \"the user supplied "
    "this structure themselves\" (RELATIONSHIP), never the word "
    "\"ownership\" itself.\n"
    "  CURRENT_METRIC: a single current/latest value, not a change over "
    "time or a comparison of two points.\n"
    "  PRECISE_DATA: an exact figure/conversion, not shaped like any of the "
    "above.\n"
    "  PROCESS: an ordered sequence of stages/steps the user names.\n"
    "  NETWORK/DEPENDENCY/LINEAGE: like RELATIONSHIP but specifically an "
    "ownership network, a dependency chain, or data/audit lineage the user "
    "supplies.\n"
    "jurisdictions: ONLY countries/regions actually named in the query — "
    "never infer one from context you don't have.\n"
    "entities: real, specific named things the query mentions (a country, "
    "company, person, metric, currency, or document) — never invent one.\n"
    "wants_visualization: true only if a chart/graph/table would materially "
    "help answer THIS question (e.g. it asks about a trend, a comparison "
    "across multiple items, or explicitly names a chart type) — not merely "
    "because the topic is numeric. explicitly_requested_chart_words carries "
    "the user's own words for a named chart type verbatim (e.g. \"bar "
    "chart\", \"pie chart\") if any, else null — you are NOT choosing the "
    "final chart type (a mismatched request like \"inflation as a pie "
    "chart\" still gets wants_visualization=true and the requested word "
    "recorded verbatim; whether pie is actually the right chart is decided "
    "later, by a different part of the system, from the real retrieved "
    "data — not something you judge).\n"
    "needs_live_data: true if answering requires a current/real-time figure "
    "(a live price, current exchange rate, today's rate).\n"
    "needs_retrieval: true if answering benefits from checking external/"
    "governed sources rather than general knowledge alone.\n"
    "needs_calculation: true only if arriving at the answer requires actual "
    "arithmetic on numbers the user (or a later step) supplies — not for a "
    "question that merely explains a formula or concept.\n"
    "ambiguous: true if material information (which jurisdiction, which "
    "period, which entity) is genuinely unresolved and answering well "
    "requires guessing. confidence: your genuine confidence in this whole "
    "classification, 0 to 1.\n"
    "Do not perform any tax/accounting calculation yourself. Do not invent "
    "jurisdictions, dates, entities or measures the query didn't name."
)


def _client() -> Optional[AsyncGroq]:
    api_key = os.environ.get("GROQ_API_KEY")
    return AsyncGroq(api_key=api_key) if api_key else None


def _to_strict_schema(schema: dict) -> dict:
    """Groq's `strict: true` structured-output mode requires every object to
    set `additionalProperties: false` and list EVERY property (including
    ones with a default) in `required` — Pydantic's own model_json_schema()
    does neither by default (a field with a default is normally omitted
    from `required`). Walks the whole schema, including $defs, applying
    both. Purely a generation-time constraint on the model's output; the
    response is still parsed back through the ordinary QueryIntent
    Pydantic model afterward, which is unaffected by this."""
    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(schema)
    return schema


# Categories a caller (production or eval tooling) needs to tell apart — a
# daily-quota exhaustion is a completely different signal from a genuine
# semantic miss or even a transient minute-level burst, and must never be
# scored as either "the LLM got this wrong" or silently merged into a flat
# "intent=None" with no explanation. See RATE_LIMIT_DAY vs RATE_LIMIT_MINUTE.
RATE_LIMIT_DAY = "rate_limit_day"
RATE_LIMIT_MINUTE = "rate_limit_minute"


def _classify_rate_limit(exc: groq.RateLimitError) -> str:
    """Groq's 429 body distinguishes "tokens/requests per DAY (TPD/RPD)"
    from "...per MINUTE (TPM/RPM)" in its error message — a daily-quota hit
    cannot be worked around by any amount of in-process backoff (unlike a
    minute-level burst), so this must be observable as a distinct category,
    not folded into a generic "rate_limit" bucket."""
    body = getattr(exc, "body", None) or {}
    message = str((body.get("error") or {}).get("message") or exc.message or "")
    if re.search(r"per day|TPD|RPD", message, re.I):
        return RATE_LIMIT_DAY
    return RATE_LIMIT_MINUTE


@dataclass
class ClassificationAttempt:
    """Full diagnostic result of one classify_query_llm() call — separate
    from that function's own Optional[QueryIntent] contract (which stays a
    simple None-on-any-failure, matching risk_llm.py's established
    convention) so production code doesn't need to branch on failure
    category, while eval tooling that DOES need to (to exclude quota/
    infra failures from semantic-accuracy scoring, not conflate them with a
    real miss) can call attempt_classify_query_llm() directly."""
    intent: Optional[QueryIntent]
    failure_category: Optional[str]
    latency_ms: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_tokens_remaining: Optional[int] = None
    estimated_requests_remaining: Optional[int] = None


def _log_failure(category: str, latency_ms: float) -> None:
    logger.warning(
        "query_classifier_llm_failed",
        extra={"failure_category": category, "latency_ms": latency_ms},
    )


def _log_success(attempt: ClassificationAttempt) -> None:
    logger.info(
        "query_classifier_llm_success",
        extra={
            "latency_ms": attempt.latency_ms,
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "total_tokens": attempt.total_tokens,
            "estimated_tokens_remaining": attempt.estimated_tokens_remaining,
            "estimated_requests_remaining": attempt.estimated_requests_remaining,
        },
    )


async def attempt_classify_query_llm(query: str) -> ClassificationAttempt:
    """Same call as classify_query_llm(), with the full diagnostic result
    (failure category, token usage, remaining-budget headers) — intended
    for eval/observability tooling, not production request handling."""
    client = _client()
    if client is None:
        return ClassificationAttempt(intent=None, failure_category="not_configured", latency_ms=0.0)

    # Same fast/classifier model already used for risk classification —
    # this is a structured-extraction task, not answer generation, so the
    # large GROQ_MODEL is unnecessary overhead here.
    model = os.getenv("GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b")
    schema = _to_strict_schema(QueryIntent.model_json_schema())
    started = time.monotonic()

    attempt = 0
    response = None
    while True:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "query_intent", "strict": True, "schema": schema},
                },
            )
            break
        except groq.RateLimitError as exc:
            category = _classify_rate_limit(exc)
            latency_ms = (time.monotonic() - started) * 1000
            # A daily-quota hit will not resolve within this call's lifetime
            # under any backoff — retrying just spends the retry budget on a
            # guaranteed-identical failure. Only a minute-level burst is
            # worth the single retry _RETRYABLE_ERRORS otherwise allows.
            if category == RATE_LIMIT_DAY or attempt >= _MAX_RETRIES:
                _log_failure(category, latency_ms)
                return ClassificationAttempt(intent=None, failure_category=category, latency_ms=latency_ms)
            retry_after = _retry_after_seconds(exc)
            delay = retry_after if retry_after is not None else _BACKOFF_SECONDS * (2 ** attempt)
            await asyncio.sleep(delay)
            attempt += 1
        except _RETRYABLE_ERRORS as exc:
            if attempt >= _MAX_RETRIES:
                latency_ms = (time.monotonic() - started) * 1000
                _log_failure(type(exc).__name__, latency_ms)
                return ClassificationAttempt(intent=None, failure_category=type(exc).__name__, latency_ms=latency_ms)
            retry_after = _retry_after_seconds(exc)
            delay = retry_after if retry_after is not None else _BACKOFF_SECONDS * (2 ** attempt)
            await asyncio.sleep(delay)
            attempt += 1
        except groq.GroqError as exc:
            # Auth/request-shape/other non-transient errors — retrying would
            # just fail identically, so don't.
            latency_ms = (time.monotonic() - started) * 1000
            _log_failure(type(exc).__name__, latency_ms)
            return ClassificationAttempt(intent=None, failure_category=type(exc).__name__, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.monotonic() - started) * 1000
            category = f"unexpected:{type(exc).__name__}"
            _log_failure(category, latency_ms)
            return ClassificationAttempt(intent=None, failure_category=category, latency_ms=latency_ms)

    latency_ms = (time.monotonic() - started) * 1000
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    output_tokens = getattr(usage, "completion_tokens", None) if usage else None
    total_tokens = getattr(usage, "total_tokens", None) if usage else None
    # Provider-returned headroom (x-ratelimit-remaining-tokens/-requests) is
    # deliberately NOT wired here: verified against this SDK version that
    # the plain client.chat.completions.create() response object (a parsed
    # ChatCompletion) exposes no raw HTTP headers — only the lower-level
    # client.chat.completions.with_raw_response.create() does, which returns
    # an unparsed response requiring an extra explicit .parse() step. Doing
    # that would mean restructuring this function's whole retry loop around
    # the raw-response call shape for a secondary observability feature; not
    # worth that risk to the core classification path. If this becomes
    # important, add it via with_raw_response rather than guessing at
    # attributes on the parsed object (an earlier version of this code did
    # exactly that and silently always returned None).
    remaining_tokens = None
    remaining_requests = None

    raw = response.choices[0].message.content
    if not raw:
        _log_failure("empty_response", latency_ms)
        return ClassificationAttempt(
            intent=None, failure_category="empty_response", latency_ms=latency_ms,
            input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        )
    try:
        intent = QueryIntent.model_validate_json(raw)
    except ValidationError:
        _log_failure("schema_validation", latency_ms)
        return ClassificationAttempt(
            intent=None, failure_category="schema_validation", latency_ms=latency_ms,
            input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        )
    intent.source = "llm"
    result = ClassificationAttempt(
        intent=intent, failure_category=None, latency_ms=latency_ms,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        estimated_tokens_remaining=remaining_tokens, estimated_requests_remaining=remaining_requests,
    )
    _log_success(result)
    return result


async def classify_query_llm(query: str) -> Optional[QueryIntent]:
    """Return a QueryIntent for `query`, or None if the LLM is unavailable,
    errors, or returns something that doesn't validate against the schema —
    the caller then falls back to the deterministic classifiers. This is
    the stable, simple contract production code (query_classifier.py) uses;
    see attempt_classify_query_llm() for the full diagnostic result."""
    return (await attempt_classify_query_llm(query)).intent
