"""
QueryIntent — the semantic query-understanding contract for Ask Kriton™.

Phase A of the semantic-classifier build (see conversation/design notes):
define the contract and a resilient classify_query() that can fail all the
way back to the existing deterministic classifiers. This module owns ONLY
the schema. It is NOT yet wired into ask_kriton()'s live routing — that is a
later, separate migration once classify_query() has been evaluated against
real traffic (shadow mode), matching every other structured-evidence change
in this codebase, which never lands ahead of its own verification.

Deliberately reuses the vocabulary that already exists and is already load-
bearing elsewhere, rather than inventing a second, parallel taxonomy that
would need to be kept in sync by hand:
  - `intent` values are exactly intent_classifier.py's existing constants
    (TREND, DISTRIBUTION, ...) — the visualization pipeline already branches
    on these strings; a semantic classifier that invented its own intent
    names would need a translation layer before any downstream code could
    use it.
  - `domain` values are exactly visualization/domain.py's existing
    (domain, subdomain) pairs, which already drive chart-variant
    specialization (e.g. TAX -> TAX_METRIC_TREND).

This schema is intentionally smaller than a maximal "capture everything"
design — every field maps to a real decision an existing part of this
pipeline already makes (needs_live_data -> fetch_live_data, needs_retrieval
-> build_source_bundle, wants_visualization -> detect_explicit_visual_request
et al). Fields with no current consumer are not included; add one only when
a concrete downstream use exists, per this codebase's own convention.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.orchestration.intent_classifier import (
    TREND, DISTRIBUTION, CORRELATION, COMPOSITION, CURRENT_METRIC,
    PRECISE_DATA, PROCESS, EVIDENCE_ANALYSIS, RELATIONSHIP, NETWORK,
    DEPENDENCY, LINEAGE,
)
from app.orchestration.visualization.domain import _RULES as _DOMAIN_RULES

# Exactly intent_classifier.py's constants MINUS FACT: FACT means "no
# chart-worthy shape identified", which this schema represents as
# `intent=None` instead (matching the LLM system prompt's instruction to
# leave the field unset for a plain factual question) — one meaning, not two
# spellings of it, across both the LLM and the regex-fallback paths.
QueryIntentLabel = Literal[
    "TREND", "DISTRIBUTION", "CORRELATION", "COMPOSITION", "CURRENT_METRIC",
    "PRECISE_DATA", "PROCESS", "EVIDENCE_ANALYSIS", "RELATIONSHIP", "NETWORK",
    "DEPENDENCY", "LINEAGE",
]

# Kept as one tuple so the Literal above and the fallback composer
# (query_classifier.py) can never drift against each other.
_INTENT_VALUES = (
    TREND, DISTRIBUTION, CORRELATION, COMPOSITION, CURRENT_METRIC,
    PRECISE_DATA, PROCESS, EVIDENCE_ANALYSIS, RELATIONSHIP, NETWORK,
    DEPENDENCY, LINEAGE,
)
assert set(QueryIntentLabel.__args__) == set(_INTENT_VALUES)  # nosec — dev-time contract check

# The (domain, subdomain) pairs visualization/domain.py already classifies
# queries into, plus GENERAL (its own no-match default) and OUT_OF_SCOPE (a
# query outside accounting/tax/audit/finance entirely — domain.py has no
# such state today since every VisualizationSpec belongs to *some* in-domain
# query by the time it reaches that module).
_DOMAIN_VALUES = tuple(sorted({d for d, _sub, _pat in _DOMAIN_RULES} | {"GENERAL", "OUT_OF_SCOPE"}))
QueryDomain = Literal[_DOMAIN_VALUES]  # type: ignore[valid-type]

EntityType = Literal["country", "company", "person", "metric", "currency", "document", "other"]

TimeGranularity = Literal["day", "month", "quarter", "year", "unknown"]


class QueryEntity(BaseModel):
    name: str
    type: EntityType = "other"


class TimeContext(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    granularity: TimeGranularity = "unknown"


class QueryIntent(BaseModel):
    """One semantic interpretation of a single user query.

    Deliberately does NOT select a chart renderer or a final chart type
    (e.g. "line" vs "bar") — that decision still belongs to
    data_shape.py + rules.py, which see the ACTUAL retrieved evidence, not
    just the sentence. `wants_visualization` says whether a visual would
    help; the existing deterministic pipeline still decides which one.
    """

    schema_version: str = "1.0"

    domain: QueryDomain = "GENERAL"
    intent: Optional[QueryIntentLabel] = None
    secondary_intents: list[QueryIntentLabel] = Field(default_factory=list)

    jurisdictions: list[str] = Field(default_factory=list)
    entities: list[QueryEntity] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    time_context: Optional[TimeContext] = None

    # Maps directly onto existing pipeline decisions — see fetch_live_data,
    # build_source_bundle, and the tax/calculation-tool gap noted in the
    # design discussion (no calculation engine exists yet; this field is
    # forward-looking, always False until one does).
    needs_live_data: bool = False
    needs_retrieval: bool = False
    needs_calculation: bool = False

    wants_visualization: bool = False
    explicitly_requested_chart_words: Optional[str] = None

    out_of_scope: bool = False
    ambiguous: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # Set by classify_query(), never by the LLM itself — which layer actually
    # produced this result, so callers/telemetry can distinguish "semantic"
    # from "regex fallback" without re-deriving it.
    source: Literal["llm", "fallback"] = "fallback"
