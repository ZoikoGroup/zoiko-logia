"""
Risk Classifier — ML-based triage engine with L1 deterministic checks.

Implements the routing logic per ZL-T0-04 (Sections 3, 6, 8, 12).
L1 (< 5 ms): Deterministic regex pattern scan for strict blockers (Academic, Bypass).
L2 (~40-80 ms): Zero-Shot Machine Learning semantic classification using transformers.
"""
from __future__ import annotations

import re
import uuid
import os
from typing import Optional

from app.core.config import get_settings
from app.domains.calculation.formula_extraction import extract_named_formula, identify_missing_formula_inputs
from app.domains.reference_data.user_provided_data import extract_inline_dataset
from app.domains.risk_safety.models import RiskLevel, RestrictedSubClass, Route
from app.domains.risk_safety.routing_matrix import ROUTING_MATRIX_VERSION, resolve as resolve_route
from app.domains.risk_safety import llm_classifier
from app.domains.risk_safety.query_signals import analyze as analyze_query_signals

settings = get_settings()

# ─── ML Pipeline Initialization ─────────────────────────────────────────────
# We use a lightweight cross-encoder for fast zero-shot text classification.
# In a real deployed environment, this might run on a dedicated GPU instance.
classifier_pipeline = None
CLASSIFIER_VERSION = "lazy-nli-distilroberta-base-v1"


def _get_classifier_pipeline():
    global classifier_pipeline, CLASSIFIER_VERSION
    if classifier_pipeline is not None:
        return classifier_pipeline
    if os.getenv("ENABLE_ML_CLASSIFIER", "").lower() not in {"1", "true", "yes"}:
        CLASSIFIER_VERSION = "fallback-offline"
        return None
    try:
        from transformers import pipeline

        classifier_pipeline = pipeline(
            "zero-shot-classification",
            model="cross-encoder/nli-distilroberta-base",
        )
        CLASSIFIER_VERSION = "nli-distilroberta-base-v1"
    except Exception:
        classifier_pipeline = None
        CLASSIFIER_VERSION = "fallback-offline"
    return classifier_pipeline

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
        r"\b(solve\s+(my|this)\s+(\w+\s+){0,2}exam|exam\s+answers?|answers?\s+(?:to\s+)?(?:my|this)\s+(?:\w+\s+){0,2}exam|quiz\s+answers?|complete\s+(my|this)\s+(\w+\s+){0,2}assessment)\b",
        re.IGNORECASE,
    )
]

_BYPASS_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\b(?:ignore|disregard|override)\b.{0,40}\b(?:instructions?|rules?|polic(?:y|ies)|safety|controls?)\b"
        r"|\b(?:reveal|show|print|expose)\b.{0,30}\b(?:system\s+prompt|hidden\s+instructions?|developer\s+message)\b"
        r"|\b(?:jailbreak|bypass\s+safety|DAN\s+mode)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bignore\b.{0,60}\b(?:kriton(?:['’]s)?\s+)?safety\s+rules?\b", re.IGNORECASE),
]

# 2026-07-22 (product vision doc, item 2 — memory:
# product-vision-kriton-tutor-not-search): the vision doc's own canonical
# example, "My taxes are being investigated. What should I do?", did NOT
# match either pattern below before this — "taxes" wasn't in the first
# pattern's noun list, and "do" wasn't in the second's verb list. Broadened
# both so the exact example the vision doc gives actually triggers the
# advice-signal handling it's meant to demonstrate.
_ADVICE_SIGNALS: list[re.Pattern] = [
    re.compile(
        r"\b(my|our)\s+(company|client|firm|business|tax(?:es)?|return|audit|filing|situation|case)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bshould\s+(I|we)\s+(file|report|recognize|do)\b", re.IGNORECASE),
]

# Clear, non-personal requests should not be made ambiguous merely because an
# optional zero-shot model is unavailable or has a low-confidence day.  These
# patterns determine *intent*, not the answer, so they do not weaken source or
# citation requirements later in the pipeline.
_EDUCATIONAL_PATTERNS: list[re.Pattern] = [
    # "was/were", "percentage/how much/how many", and "how does/do X impact/
    # affect Y" added after live testing (2026-07-21): "What was the US GDP
    # last quarter?", "What percentage is withheld for Medicare in Texas?",
    # and "How does recording depreciation... impact all three financial
    # statements?" all missed the original is/are-only bank entirely and
    # fell through to the ML zero-shot pipeline, which then
    # non-deterministically returned CLASSIFICATION_UNCERTAIN for perfectly
    # ordinary factual/educational questions.
    re.compile(
        r"^\s*(what\s+(?:is|are|was|were|does|do)|what\s+percentage|how\s+(?:much|many)|"
        r"how\s+(?:does|do)\b.*\b(?:impact|affect)|"
        r"define|explain|describe|compare|summari[sz]e)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(difference\s+between|learning\s+note|educational\s+summary)\b", re.IGNORECASE),
    re.compile(
        r"^\s*under\s+(?:pcaob\s+)?(?:as|asc|au-c)\s*\d+[A-Za-z-]*,?\s+what\s+(?:is|are|does|do)\b",
        re.IGNORECASE,
    ),
    # Real incident (2026-07-23): "Calculate straight-line depreciation for
    # a $50,000 asset..." and "If revenue is $250,000 and expenses are
    # $180,000, what is the net profit?" both missed every pattern above
    # (neither starts with "what/how/define/..."), fell through to the ML
    # zero-shot pipeline, and landed in CLASSIFICATION_UNCERTAIN — a plain
    # arithmetic accounting calculation asked for clarification instead of
    # an answer. A "calculate X" request and a "given these figures, what
    # is Y" conditional-arithmetic setup are exactly as safe/non-personal
    # as the "what is" patterns above; the "if" variant requires a digit or
    # $ between "if" and "what is" so it only catches the numeric-setup
    # shape, not a vague "if my situation happens, what is..." query.
    re.compile(r"^\s*calculate\b", re.IGNORECASE),
    re.compile(r"^\s*if\b.*[\$\d].*,?\s*what\s+(?:is|are|would\s+be)\b", re.IGNORECASE),
    # Presentation requests are ordinary data/educational intent. Whether
    # the requested figures actually exist is decided later by retrieval and
    # answer validation, not by probabilistic safety classification.
    re.compile(
        r"^[\s\"'“”‘’]*(?:visuali[sz]e\b|(?:show|present|create|build)\b.*\b(?:table|chart|graph|waterfall|visuali[sz]ation)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:show|create|present)\b.*\b(?:timeline|flow\s*chart|decision\s*flow|sequence\s+diagram|swimlane|scoring\s+matrix)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:give|create|list|outline|describe|show|walk\s+me\s+through)\b.*\b(?:steps?|process|procedure|workflow)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:give|show|create|provide)\b.*\bcheck\s?list\b", re.IGNORECASE),
    re.compile(r"^\s*give\s+me\s+(?:a\s+)?(?:detailed\s+)?explanation\b", re.IGNORECASE),
    re.compile(r"^\s*compare\b", re.IGNORECASE),
    re.compile(r"^\s*how\s+(?:do|can)\s+i\b", re.IGNORECASE),
    re.compile(
        r"^\s*(?:how\s+should\s+i|what\s+should\s+i)\s+"
        r"(?:investigate|examine|check|review|assess|evaluate|determine)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:what\s+do\s+i\s+need\s+to|how\s+should\s+(?:a|the)\s+reviewer)\s+"
        r"(?:investigate|examine|check|review|assess|evaluate|determine)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*what\s+should\s+happen\s+when\b", re.IGNORECASE),
    re.compile(r"^\s*what\s+steps\s+help\b", re.IGNORECASE),
    re.compile(r"\bevidence\b.*\bdoes\s+not\b.*\bwhat\s+happens\s+next\b", re.IGNORECASE),
    re.compile(r"\bidentify\s+the\s+error\b.*\bcorrecting\s+journal\s+entry\b", re.IGNORECASE),
    re.compile(
        r"\b(?:customer\s+)?payment\b.*\bcredited\s+to\s+revenue\b.*\baccounts?\s+receivable\b",
        re.IGNORECASE,
    ),
    re.compile(r"\baccounts?\s+receivable\b.*\brevenue\b.*\b(?:audit\s+procedures?|possible\s+causes?)\b", re.IGNORECASE),
    re.compile(r"^\s*show\s+quarterly\s+revenue\s+and\s+gross\s+margin\b", re.IGNORECASE),
    re.compile(r"^\s*create\s+an?\s+accounts?[\s-]+receivable\s+aging\s+analysis\b", re.IGNORECASE),
    re.compile(
        r"\b(?:accounts?\s+receivable|receivables)\b.*\b(?:sales|revenue)\b.*\b(?:audit|procedures?|causes?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsupplier\b.*\b(?:paid\s+twice|duplicate\s+payment)\b.*\b(?:checklist|investigat|correct)",
        re.IGNORECASE,
    ),
]

_FACTUAL_LOOKUP_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(current|latest|today(?:'s)?)\b.*\b(rate|cpi|inflation|gdp|income|yield)\b", re.IGNORECASE),
    re.compile(r"\b(exchange|treasury|federal\s+funds|interest)\s+rate\b", re.IGNORECASE),
    re.compile(r"\bfed(?:eral)?\s+funds\s+rate\b", re.IGNORECASE),
    re.compile(r"\b(?:treasury\s+yield|\d+[\s-]*year\s+treasury)\b", re.IGNORECASE),
    re.compile(r"\b(?:convert|conversion)\b.*\b(?:usd|inr|currency|dollars?|rupees?)\b", re.IGNORECASE),
]

_REVIEWED_TAX_WORKFLOW_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bbusiness\s+tax\s+return\b.*\b(?:review|before\s+filing|workflow|checklist)\b", re.I),
    re.compile(r"\bcompany-specific\s+tax[\s-]+treatment\b", re.I),
]

_NAVIGATION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(?:hello|hi|hey|thanks?|thank\s+you)\b", re.IGNORECASE),
    re.compile(r"\b(?:where|how)\s+(?:can|do)\s+i\s+(?:find|open|access)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+can\s+(?:kriton|this\s+(?:app|assistant))\s+(?:do|help)\b", re.IGNORECASE),
]

# A request to chart/compare numbers the user already typed into the query
# isn't asking Kriton to look anything up or judge anything — it's a
# formatting request over data no more sensitive than the plain text it's
# already in. See the l2-deterministic-supplied-data-visualization rule below.
# Real gap (2026-08-03): "Starting cash was $500k. Operations added $180k,
# ... Show the movement to ending cash." scored low-confidence and fell into
# CLASSIFICATION_UNCERTAIN — the same live-bug shape as the 2026-08-01 fix
# below, just phrased with "movement"/"bridge" (a cash-flow-bridge/waterfall
# request) instead of "visualize"/"compare". Added the same trigger words
# presentation_dataprofile.py's FINANCIAL_MOVEMENT intent already recognizes
# for chart selection, so a query that will end up as a waterfall chart is
# never blocked one step earlier at risk classification.
# "show"/"display" added the same day: two more live queries — "Show
# monthly adjustments: ..." and "Show how profit changed from 2025 to
# 2026: ..." — each fully specify their own data but use neither a keyword
# above nor a recognized recommendation/personal-advice pattern, so they
# also fell into CLASSIFICATION_UNCERTAIN. "Show"/"display" alone would be
# too broad to trust generally, but paired with the existing
# _INLINE_NUMERIC_FIGURE requirement below (a literal $/£/€ figure must
# also be present) this only ever fires for a query that already supplies
# its own data to format — never a bare "show me how X works" concept
# question.
# Real gap (2026-08-04): the $/£/€ requirement above also rejected every
# non-currency dataset — "Display headcount by department: Engineering 42,
# Sales 28, ..." (plain counts) and "Plot our weekly active users: 1200,
# 1350, ..." (no labels or currency at all) both fell into
# CLASSIFICATION_UNCERTAIN despite fully specifying their own data. Rather
# than widen the regex heuristic further, this now falls back to the real
# extractor: if extract_inline_dataset() already proves the query is a
# complete, self-contained dataset request, that is strictly stronger
# evidence than "does a $ sign appear somewhere" and is trusted on its own.
_VISUALIZATION_KEYWORDS = re.compile(
    r"\b(visualiz\w*|chart|graph|plot|compare|comparison|composition|breakdown|variance|"
    r"distribution|movement|bridge|waterfall|walk\s+from|trend|show|display|rank(?:ing)?)\b",
    re.IGNORECASE,
)
_INLINE_NUMERIC_FIGURE = re.compile(r"[$£€]\s*\d[\d,]*(?:\.\d+)?")

_AMBIGUOUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*tell\s+me\s+about\s+(?:accounting|finance|tax(?:es)?)\s*[.?!]*\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*how\s+should\s+(this|that|it)(?:\s+(?:transaction|item|amount|entry))?\s+be\s+"
        r"(reported|treated|recorded|filed)\??\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*what\s+(?:accounting|tax)\s+treatment\s+should\s+(?:i|we)\s+use\??\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*how\s+should\s+(?:this|that|the)\s+transaction\s+be\s+treated\s+for\s+tax\s+purposes?\??\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*what\s+is\s+the\s+(?:correct|appropriate)\s+(?:accounting|tax)\s+treatment\s+for\s+"
        r"(?:this|that|the)\s+(?:transaction|item|amount|entry)\??\s*$",
        re.IGNORECASE,
    ),
]

def _new_query_id() -> str:
    return f"qry-{uuid.uuid4().hex[:12]}"


# A leading quote character defeats every ^\s* anchor below outright — \s*
# matches whitespace only, not punctuation, so a query typed or pasted with
# wrapping quotes (straight or curly) never matches at all, silently
# falling through to the ML pipeline instead. Confirmed live (2026-07-21):
# copy-pasting a suggested test question complete with its wrapping quotes
# turned an otherwise-matching "What are the exchange rates for major
# currencies?" into a CLASSIFICATION_UNCERTAIN clarification. Used only for
# the anchored pattern checks below (_EDUCATIONAL_PATTERNS, _AMBIGUOUS_PATTERNS)
# — never mutates the query used for the ML pipeline, retrieval, or audit
# logging, so nothing downstream sees a different query than the user typed.
_WRAPPING_QUOTES = "\"'“”‘’"


def _strip_wrapping_quotes(query: str) -> str:
    return query.strip().strip(_WRAPPING_QUOTES).strip()

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

    stripped_query = _strip_wrapping_quotes(query)
    for pat in _BYPASS_PATTERNS:
        if pat.search(stripped_query):
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
    stripped_query = _strip_wrapping_quotes(query)
    is_ambiguous = any(pat.search(stripped_query) for pat in _AMBIGUOUS_PATTERNS)
    signals = analyze_query_signals(query, jurisdiction=jurisdiction, ambiguous=is_ambiguous)
    # The structured analyzer recognizes recommendation language beyond the
    # original narrow pattern bank. It can raise, never lower, the advice floor.
    has_advice_signal = has_advice_signal or signals.personalized_advice
    base_metadata: dict = {"signals": signals.to_dict()}

    if is_ambiguous:
        rules_applied.append("l2-ambiguous-context")
        return _decision(
            query_id, False, RiskLevel.MEDIUM, Route.CLARIFICATION, 1.0,
            rules_applied, ["The subject and reporting context are missing; clarification is required."],
            classification_metadata=base_metadata,
        )

    deterministic_label: Optional[str] = None
    if not has_advice_signal and any(pat.search(stripped_query) for pat in _NAVIGATION_PATTERNS):
        deterministic_label = "casual conversation or navigational help"
        rules_applied.append("l2-deterministic-navigation")
    elif not has_advice_signal and any(pat.search(query) for pat in _FACTUAL_LOOKUP_PATTERNS):
        deterministic_label = "factual lookup"
        rules_applied.append("l2-deterministic-factual-lookup")
    elif any(pat.search(stripped_query) for pat in _REVIEWED_TAX_WORKFLOW_PATTERNS):
        deterministic_label = "regulated tax or legal advice"
        rules_applied.append("l2-deterministic-reviewed-tax-workflow")
    # Live bug: "For a company with $400,000 in sales..., what is the gross
    # margin?" and "Overall materiality using a $1,000,000 benchmark
    # amount..." don't start with any of _EDUCATIONAL_PATTERNS' anchored
    # openers ("calculate", "what is", "if $X..."), so they fell through to
    # the ML zero-shot pipeline, which scored them just under the LOW
    # threshold (~0.30 vs 0.35) and asked for clarification instead of
    # answering — even though "current ratio for $150,000 assets..." (which
    # only differs by starting with "Calculate") sailed through. A query
    # that formula_extraction.py can already deterministically resolve into
    # a fully-specified, verified governed calculation is by construction
    # arithmetic, not personalized advice or ambiguous — no ML guess needed,
    # regardless of how the sentence happens to open.
    elif not has_advice_signal and (
        extract_named_formula(query) is not None or identify_missing_formula_inputs(query) is not None
    ):
        deterministic_label = "factual lookup"
        rules_applied.append("l2-deterministic-governed-calculation")
    # Live bug (2026-08-01): "Here is our department spending: Payroll budget
    # $150,000 actual $158,000...Visualize a comparison of budget and actual
    # by department." scored 0.2991 vs the 0.35 LOW-risk threshold and fell
    # into CLASSIFICATION_UNCERTAIN — even though it only asks Kriton to
    # chart figures the query itself already supplies, not to look anything
    # up or exercise judgment.
    elif not has_advice_signal and (
        (_VISUALIZATION_KEYWORDS.search(query) and _INLINE_NUMERIC_FIGURE.search(query))
        or extract_inline_dataset(query) is not None
    ):
        deterministic_label = "factual lookup"
        rules_applied.append("l2-deterministic-supplied-data-visualization")
    elif not has_advice_signal and any(pat.search(stripped_query) for pat in _EDUCATIONAL_PATTERNS):
        deterministic_label = "general educational concept"
        rules_applied.append("l2-deterministic-educational")

    # ── L2: ML Zero-Shot Semantic Scoring ───────────────────────────────

    confidence = 0.0
    top_label = "unknown"
    local_classifier_failed = False
    
    pipeline_instance = None if deterministic_label else _get_classifier_pipeline()
    if deterministic_label:
        top_label = deterministic_label
        confidence = 1.0
    elif pipeline_instance:
        try:
            result = pipeline_instance(query, CANDIDATE_LABELS)
            top_label = result["labels"][0]
            confidence = result["scores"][0]
        except Exception:
            rules_applied.append("l2-ml-pipeline-failed")
            local_classifier_failed = True
    else:
        rules_applied.append("l2-ml-fallback-mode")
        local_classifier_failed = True

    # ── L3: schema-constrained LLM fallback / shadow evaluation ─────────
    # An unavailable local model used to leave confidence=0.5 and
    # top_label="unknown". Since 0.5 exceeded the configured threshold, that
    # silently flowed to ZERO. Unknown and provider failure now always take
    # the conservative path unless a validated LLM fallback resolves them.
    llm_mode = llm_classifier.configured_mode()
    predicted_risk = _risk_for_label(top_label, mode)
    threshold = _confidence_threshold(predicted_risk)
    local_uncertain = local_classifier_failed or confidence < threshold
    llm_result = None
    external_llm_allowed = privacy_class == "NONE"
    if not deterministic_label and llm_mode in {"fallback", "shadow"} and (
        local_uncertain or llm_mode == "shadow"
    ) and external_llm_allowed:
        llm_result = llm_classifier.classify(query, jurisdiction=jurisdiction, mode=mode)
        rules_applied.append("l3-llm-classifier-applied" if llm_result else "l3-llm-classifier-unavailable")
    elif not deterministic_label and llm_mode in {"fallback", "shadow"} and not external_llm_allowed:
        rules_applied.append("l3-llm-classifier-skipped-sensitive")

    classification_metadata: dict = dict(base_metadata)
    classification_metadata["calibration"] = {
        "predicted_risk": predicted_risk.value,
        "threshold": threshold,
        "score": confidence,
    }
    if llm_result:
        classification_metadata["llm"] = {
            "risk_level": llm_result.risk_level,
            "confidence": llm_result.confidence,
            "intent": llm_result.intent,
            "advice_signal": llm_result.advice_signal,
            "missing_context": list(llm_result.missing_context),
            "reason_codes": list(llm_result.reason_codes),
            "model": llm_result.model,
            "shadow": llm_mode == "shadow" and not local_uncertain,
        }

    if llm_result and local_uncertain:
        top_label = {
            "HIGH": "regulated tax or legal advice",
            "MEDIUM": "accounting or audit opinion",
            "LOW": "general educational concept",
            "ZERO": "casual conversation or navigational help",
        }[llm_result.risk_level]
        confidence = llm_result.confidence
        has_advice_signal = has_advice_signal or llm_result.advice_signal
        rules_applied.append("l3-llm-fallback-adopted")
        predicted_risk = RiskLevel(llm_result.risk_level)
        threshold = _confidence_threshold(predicted_risk)
        local_uncertain = confidence < threshold
        classification_metadata["calibration"] = {
            "predicted_risk": predicted_risk.value,
            "threshold": threshold,
            "score": confidence,
        }

    # Wireframe Rule: CLASSIFICATION_UNCERTAIN threshold
    if local_uncertain:
        rules_applied.append("l2-classification-uncertain")
        # Real gap (2026-07-22): this early return used to fire regardless of
        # has_advice_signal, so a query naming the reader's own situation
        # ("my client is asking whether they should recognize this revenue")
        # got a generic "please clarify" instead of the mandatory human-review
        # escalation an advice-shaped query needs — the ML classifier being
        # uncertain about WHICH kind of question this is doesn't make it any
        # less an advice question. allowed=True here (not False) is
        # deliberate: orchestration/service.py's early-return branching only
        # treats allowed=False as "show clarification" when route is
        # literally CLARIFICATION — anything else with allowed=False falls
        # through to REFUSAL instead, which would wrongly refuse rather than
        # give a real answer. Setting allowed=True lets this flow through
        # the normal resolve_policy() call below, whose HIGH+advice_signal
        # override forces a hedged answer (still LLM) with a mandatory
        # disclaimer + professional referral — not a human-review case,
        # per the 2026-07-22 product vision doc's move away from a manual
        # review queue (memory: product-vision-kriton-tutor-not-search).
        # Reusing that override instead of duplicating its logic here.
        if has_advice_signal:
            rules_applied.append("l2-classification-uncertain-advice-signal")
            return _decision(
                query_id, True, RiskLevel.HIGH, Route.HUMAN_REVIEW, confidence, rules_applied,
                ["Query ambiguous and names the reader's own situation; a hedged answer with a professional referral will be provided."],
                requires_human_review=True,
                classification_metadata=classification_metadata,
            )
        return _decision(
            query_id, False, RiskLevel.MEDIUM, Route.CLARIFICATION, confidence, rules_applied,
            ["Query ambiguous or the classifier is unavailable; CLASSIFICATION_UNCERTAIN entered. Needs clarification."],
            classification_metadata=classification_metadata,
        )

    # Route based on ML semantic intent — four real tiers now (ZERO/LOW/
    # MEDIUM/HIGH; RESTRICTED is set only by pre_screen()'s dead L0/L1 path,
    # never here). "Regulated tax or legal advice" is the most advice-shaped
    # label and stays HIGH on its own; "accounting or audit opinion" moved
    # down to MEDIUM — it's interpretive professional content, not
    # necessarily personalized advice, and has_advice_signal (checked below,
    # before the matrix lookup) is what escalates it to HIGH when
    # the query does name the reader's own situation. Casual conversation
    # moved down from LOW to the new ZERO tier; educational/factual content
    # takes over LOW.
    if top_label == "regulated tax or legal advice":
        risk_level = RiskLevel.HIGH
        rules_applied.append("l2-semantic-high-risk")
    elif top_label == "accounting or audit opinion":
        risk_level = RiskLevel.MEDIUM
        rules_applied.append("l2-semantic-medium-risk")
    elif top_label in ["general educational concept", "factual lookup"] or mode == "Learning":
        risk_level = RiskLevel.LOW
        rules_applied.append("l2-semantic-low-risk")
    else:
        risk_level = RiskLevel.ZERO
        rules_applied.append("l2-semantic-zero-risk")

    # Personalized advice is a conservative floor, regardless of which
    # semantic label won. Apply it before the source-confidence matrix so
    # HIGH-risk source and citation requirements cannot be bypassed.
    if has_advice_signal and risk_level != RiskLevel.HIGH:
        risk_level = RiskLevel.HIGH
        rules_applied.append("l2-advice-signal-high-floor")

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
    # matrix — exposed here raw (not pre-gated on risk_level == HIGH) so the
    # live routing decision (app/orchestration/routing_matrix.py, via
    # orchestration/service.py reading this field) can apply the
    # HIGH+advice_signal-always-escalates rule itself. Gating it here too
    # would be redundant at best and silently wrong if that gate's risk
    # tiers ever drift from this module's — one place should own "does this
    # query name the reader's own situation," not two.
    return _decision(
        query_id, True, risk_level, rule.route, confidence, rules_applied, limitations,
        requires_sources=rule.requires_sources, requires_human_review=has_advice_signal,
        requires_citation=rule.requires_citation, requires_professional_boundary=rule.requires_professional_boundary,
        policy_version=ROUTING_MATRIX_VERSION,
        classification_metadata=classification_metadata,
    )


def _risk_for_label(label: str, mode: str) -> RiskLevel:
    if label == "regulated tax or legal advice":
        return RiskLevel.HIGH
    if label == "accounting or audit opinion":
        return RiskLevel.MEDIUM
    if label in {"general educational concept", "factual lookup"} or mode == "Learning":
        return RiskLevel.LOW
    return RiskLevel.ZERO


def _confidence_threshold(risk_level: RiskLevel) -> float:
    return {
        RiskLevel.ZERO: settings.CLASSIFIER_ZERO_CONFIDENCE_THRESHOLD,
        RiskLevel.LOW: settings.CLASSIFIER_LOW_CONFIDENCE_THRESHOLD,
        RiskLevel.MEDIUM: settings.CLASSIFIER_MEDIUM_CONFIDENCE_THRESHOLD,
        RiskLevel.HIGH: settings.CLASSIFIER_HIGH_CONFIDENCE_THRESHOLD,
    }[risk_level]


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
    classification_metadata: Optional[dict] = None,
) -> dict:
    result = {
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
    if classification_metadata:
        result["classification_metadata"] = classification_metadata
    return result
