"""
classify_query() — the resilient entry point for semantic query understanding.

    query text
        │
        ▼
   classify_query_llm()   (Groq, structured output)
        │
   succeeds ──────────────► deterministic overrides ──► QueryIntent(source="llm")
        │
   fails/unavailable
        │
        ▼
   _fallback_classify()   (existing regex classifiers, composed)
        │
        ▼
   deterministic overrides ──► QueryIntent(source="fallback")

"Deterministic overrides" applies AFTER either path: an explicit, literal
instruction in the query text (the user named a specific chart type in
words the existing parser recognizes) is enforced regardless of what the
LLM concluded — regex is trusted for literal control instructions, never
for open-ended semantic meaning, which is the opposite of what
classify_query_llm() is for.

Phase A/B of the semantic-classifier build: this function exists and is
independently testable/callable, but is NOT yet called from ask_kriton()'s
live routing. Wiring it in is a deliberately separate, later change — this
mirrors this codebase's own established pattern of every other structured-
evidence addition (see e.g. dbnomics.py's module docstring) landing only
after its own verification, not bundled into the change that introduces it.
"""
from __future__ import annotations

from app.orchestration.dbnomics import countries_in_query
from app.orchestration.intent_classifier import CORRELATION, FACT, RELATIONSHIP, classify_intent
from app.orchestration.query_intent import QueryEntity, QueryIntent
from app.orchestration.query_classifier_llm import classify_query_llm
from app.orchestration.response_planner import (
    detect_explicit_visual_request, detect_requested_chart_variant,
)
from app.orchestration.visualization.domain import classify_domain_context


def _fallback_classify(query: str) -> QueryIntent:
    """Compose a QueryIntent from the existing deterministic classifiers —
    never a rewrite of them. This is what keeps the application usable when
    Groq is down, rate-limited, or returns something that fails schema
    validation."""
    raw_intent = classify_intent(query)
    intent = None if raw_intent == FACT else raw_intent
    domain_context = classify_domain_context(query, intent)
    jurisdictions = countries_in_query(query)

    return QueryIntent(
        domain=domain_context.domain,  # type: ignore[arg-type]
        intent=intent,  # type: ignore[arg-type]
        jurisdictions=jurisdictions,
        entities=[QueryEntity(name=j, type="country") for j in jurisdictions],
        wants_visualization=detect_explicit_visual_request(query),
        explicitly_requested_chart_words=detect_requested_chart_variant(query),
        # The regex classifiers have no OUT_OF_SCOPE/ambiguity signal of
        # their own — that judgment call belongs to the domain guard/risk
        # pipeline elsewhere in ask_kriton(), not duplicated here.
        out_of_scope=False,
        ambiguous=False,
        confidence=0.5,
        source="fallback",
    )


def _apply_deterministic_overrides(query: str, intent: QueryIntent) -> QueryIntent:
    """A literal, named chart type in the query text is a control
    instruction, not something for the semantic layer to interpret —
    enforced regardless of which path produced `intent`, so a case the LLM
    missed (or a fallback response with wants_visualization=False for other
    reasons) never silently drops an explicit user request."""
    requested_variant = detect_requested_chart_variant(query)
    if requested_variant:
        intent.wants_visualization = True
        intent.explicitly_requested_chart_words = requested_variant
    elif detect_explicit_visual_request(query):
        intent.wants_visualization = True
    return intent


def _apply_semantic_invariants(intent: QueryIntent) -> QueryIntent:
    """Logical-consistency checks on the OTHER fields a given `intent` value
    claims to be backed by — catches the LLM (or, in principle, a bug in the
    fallback composer) asserting a chart-shaped intent its own extracted
    entities/measures don't actually support. Downgrades confidence /
    flags ambiguous rather than silently trusting an internally
    inconsistent result; never fabricates or deletes extracted data."""
    if intent.intent == CORRELATION and len(intent.measures) < 2 and len(intent.entities) < 2:
        # A correlation needs two things being compared — either two named
        # measures, or two named subjects sharing one measure (e.g. "compare
        # UK and India inflation": entities=[UK, India], measures=[inflation]).
        intent.ambiguous = True
        intent.confidence = min(intent.confidence, 0.5)
    if intent.intent == RELATIONSHIP and len(intent.entities) < 2:
        intent.ambiguous = True
        intent.confidence = min(intent.confidence, 0.5)
    return intent


async def classify_query(query: str) -> QueryIntent:
    """Semantic query understanding with a deterministic fallback. Never
    raises — a query always gets SOME QueryIntent back."""
    llm_result = await classify_query_llm(query)
    intent = llm_result if llm_result is not None else _fallback_classify(query)
    intent = _apply_semantic_invariants(intent)
    return _apply_deterministic_overrides(query, intent)
