"""
Risk Classifier — ML-based triage engine with L1 deterministic checks.

Implements the routing logic per ZL-T0-04 (Sections 3, 6, 8, 12).
L1 (< 5 ms): Deterministic regex pattern scan for strict blockers (Academic, Bypass).
L2 (~40-80 ms): Zero-Shot Machine Learning semantic classification using transformers.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from transformers import pipeline

from app.domains.risk_safety.models import RiskLevel, RestrictedSubClass, Route
from app.domains.risk_safety.routing_matrix import ROUTING_MATRIX_VERSION, resolve as resolve_route

# ─── ML Pipeline Initialization ─────────────────────────────────────────────
# We use a lightweight cross-encoder for fast zero-shot text classification.
# In a real deployed environment, this might run on a dedicated GPU instance.
try:
    classifier_pipeline = pipeline(
        "zero-shot-classification",
        model="cross-encoder/nli-distilroberta-base"
    )
    CLASSIFIER_VERSION = "nli-distilroberta-base-v1"
except Exception as e:
    # Fallback if transformers isn't ready
    classifier_pipeline = None
    CLASSIFIER_VERSION = "fallback-offline"

# Semantic classes for the Zero-Shot model
CANDIDATE_LABELS = [
    "regulated tax or legal advice",
    "accounting or audit opinion",
    "general educational concept",
    "casual conversation or navigational help"
]

# ─── L1 Pattern Banks (Defense-in-Depth) ──────────────────────────────────

_ACADEMIC_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\b(solve\s+(my|this)\s+(\w+\s+){0,2}exam|exam\s+answer|quiz\s+answer|complete\s+(my|this)\s+(\w+\s+){0,2}assessment)\b",
        re.IGNORECASE,
    )
]

_BYPASS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(ignore\s+instructions|jailbreak|system\s+prompt|bypass\s+safety|DAN\s+mode)\b", re.IGNORECASE)
]

_ADVICE_SIGNALS: list[re.Pattern] = [
    re.compile(r"\b(my|our)\s+(company|client|firm|business)\b", re.IGNORECASE),
    re.compile(r"\bshould\s+(I|we)\s+(file|report|recognize)\b", re.IGNORECASE)
]

def _new_query_id() -> str:
    return f"qry-{uuid.uuid4().hex[:12]}"

# ─── Public API ─────────────────────────────────────────────────────────────

def pre_screen(
    query: str,
    jurisdiction: str = "",
    privacy_class: str = "NONE",
    pre_bundle_state: str = "OK",
    query_id: Optional[str] = None,
) -> Optional[dict]:
    """L0 (privacy/state) + L1 (regex hard-block) checks — everything that
    does NOT need retrieval's source_confidence to decide. Runs before
    retrieval so a manipulation attempt or privacy violation never reaches
    the source register at all. Returns None if the query passes and the
    full classify() (L2) should run next; returns a decision dict if it
    hard-blocks, in which case retrieval/L2 must be skipped entirely.
    """
    query_id = query_id or _new_query_id()
    rules_applied: list[str] = []

    # ── L0: Privacy & State Hard Checks (Sections 8 & 12) ────────────────

    if privacy_class in ["PII", "MINOR_DATA", "SECRETS"]:
        rules_applied.append("l0-privacy-block")
        return _decision(query_id, False, RiskLevel.RESTRICTED, Route.SECURITY_INCIDENT, 1.0, rules_applied, ["Privacy violation detected."], restricted_sub_class=RestrictedSubClass.CONTROL_BYPASS)

    if pre_bundle_state == "LICENSE_BLOCKED":
        rules_applied.append("l0-license-blocked")
        return _decision(query_id, False, RiskLevel.RESTRICTED, Route.LICENSE_PATH, 1.0, rules_applied, ["Source license restricted."], restricted_sub_class=RestrictedSubClass.SOURCE_PROHIBITED)

    if pre_bundle_state == "ONTOLOGY_UNRESOLVED":
        rules_applied.append("l0-ontology-unresolved")
        return _decision(query_id, False, RiskLevel.MEDIUM, Route.CLARIFICATION, 1.0, rules_applied, ["Ontology concept unresolved."])

    # ── L1: Regex Hard-Block (Section 4) ─────────────────────────────────

    for pat in _ACADEMIC_PATTERNS:
        if pat.search(query):
            rules_applied.append("l1-academic-integrity-block")
            return _decision(query_id, False, RiskLevel.RESTRICTED, Route.REFUSAL, 1.0, rules_applied, ["Academic integrity violation."], restricted_sub_class=RestrictedSubClass.ACADEMIC_INTEGRITY)

    for pat in _BYPASS_PATTERNS:
        if pat.search(query):
            rules_applied.append("l1-control-bypass-block")
            return _decision(query_id, False, RiskLevel.RESTRICTED, Route.SECURITY_INCIDENT, 1.0, rules_applied, ["Control bypass attempt."], restricted_sub_class=RestrictedSubClass.CONTROL_BYPASS)

    has_advice_signal = any(pat.search(query) for pat in _ADVICE_SIGNALS)
    if has_advice_signal and not jurisdiction:
        rules_applied.append("l1-advice-insufficient-context")
        return _decision(query_id, False, RiskLevel.RESTRICTED, Route.CLARIFICATION, 0.95, rules_applied, ["Missing jurisdiction for advice."], restricted_sub_class=RestrictedSubClass.ADVICE_INSUFFICIENT_CONTEXT)

    return None


def classify(
    query: str,
    jurisdiction: str = "",
    mode: str = "Workflow",
    tenant_id: str = "default",
    source_confidence: str = "HIGH_CONFIDENCE",
    pre_bundle_state: str = "OK",
    privacy_class: str = "NONE",
    tenant_policy_conflict: bool = False,
    tool_required: bool = False,
    query_id: Optional[str] = None,
) -> dict:
    """L2 ML semantic scoring + source-confidence routing. Assumes pre_screen()
    has already been called for this query and returned None (passed)."""
    query_id = query_id or _new_query_id()
    rules_applied: list[str] = []
    limitations: list[str] = []
    has_advice_signal = any(pat.search(query) for pat in _ADVICE_SIGNALS)

    # ── L2: ML Zero-Shot Semantic Scoring ───────────────────────────────

    confidence = 0.5
    top_label = "unknown"
    
    if classifier_pipeline:
        try:
            result = classifier_pipeline(query, CANDIDATE_LABELS)
            top_label = result["labels"][0]
            confidence = result["scores"][0]
        except Exception:
            rules_applied.append("l2-ml-pipeline-failed")
    else:
        rules_applied.append("l2-ml-fallback-mode")

    # Wireframe Rule: CLASSIFICATION_UNCERTAIN threshold
    if confidence < 0.65:
        rules_applied.append("l2-classification-uncertain")
        return _decision(
            query_id, False, RiskLevel.MEDIUM, Route.CLARIFICATION, confidence, rules_applied,
            ["Query ambiguous; CLASSIFICATION_UNCERTAIN entered. Needs clarification."]
        )

    # Route based on ML semantic intent
    if top_label in ["regulated tax or legal advice", "accounting or audit opinion"]:
        risk_level = RiskLevel.HIGH
        rules_applied.append("l2-semantic-high-risk")
    elif top_label == "general educational concept" or mode == "Learning":
        risk_level = RiskLevel.MEDIUM
        rules_applied.append("l2-semantic-medium-risk")
    else:
        risk_level = RiskLevel.LOW
        rules_applied.append("l2-semantic-low-risk")

    # ── Context & Source Overrides (Section 6 & 8) ──────────────────────
    # tenant_policy_conflict is a tenant-level override, not part of the
    # (risk_level, confidence_state) matrix itself — checked first, same as
    # before the matrix existed.
    if tenant_policy_conflict:
        rules_applied.append("l2-tenant-policy-conflict")
        return _decision(query_id, False, RiskLevel.HIGH, Route.HUMAN_REVIEW, confidence, rules_applied, ["Tenant policy conflict detected."])

    rule = resolve_route(risk_level.value, source_confidence)
    rules_applied.append(f"matrix-{risk_level.value.lower()}-{source_confidence.lower()}")

    if rule.limitation:
        limitations.append(rule.limitation)

    if not rule.allowed:
        return _decision(query_id, False, risk_level, rule.route, confidence, rules_applied, limitations, policy_version=ROUTING_MATRIX_VERSION)

    # has_advice_signal is a query-content signal, not part of the confidence
    # matrix — a HIGH-risk query that also names "my/our company" always
    # needs a human in the loop regardless of how strong the sources are.
    req_human = risk_level == RiskLevel.HIGH and has_advice_signal

    return _decision(
        query_id, True, risk_level, rule.route, confidence, rules_applied, limitations,
        requires_sources=rule.requires_sources, requires_human_review=req_human,
        requires_citation=rule.requires_citation, requires_professional_boundary=rule.requires_professional_boundary,
        policy_version=ROUTING_MATRIX_VERSION,
    )


def _decision(
    query_id: str,
    allowed: bool,
    risk_level: RiskLevel,
    route: Route,
    confidence: float,
    rules_applied: list[str],
    limitations: list[str],
    restricted_sub_class: Optional[RestrictedSubClass] = None,
    requires_sources: bool = False,
    requires_human_review: bool = False,
    requires_citation: bool = False,
    requires_professional_boundary: bool = False,
    policy_version: Optional[str] = None,
) -> dict:
    return {
        "query_id": query_id,
        "allowed": allowed,
        "risk_level": risk_level.value,
        "restricted_sub_class": restricted_sub_class.value if restricted_sub_class else None,
        "route": route.value,
        "confidence": confidence,
        "rules_applied": rules_applied,
        "limitations": limitations,
        "requires_sources": requires_sources,
        "requires_human_review": requires_human_review,
        "requires_citation": requires_citation,
        "requires_professional_boundary": requires_professional_boundary,
        "classifier_version": CLASSIFIER_VERSION,
        "policy_version": policy_version,
    }
