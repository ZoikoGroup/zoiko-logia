"""Deterministic presentation planning for already-validated answer text.

This module never generates facts. It only inspects the user query and the
final Markdown answer that has already passed Checkpoint C. Numeric charts are
derived exclusively from complete numeric columns in GFM tables, keeping the
table as the accessible textual source of truth.
"""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from app.orchestration import presentation_graph, presentation_llm_classifier
from app.orchestration.presentation_dataprofile import (
    RANKING_VERSION,
    AnalyticalIntent,
    SINGLE_TOTAL_COMPOSITION_PREFERENCE,
    TEMPORAL_PREFERENCE,
    chart_family,
    chart_renderer,
    compute_correlation_matrix,
    compute_data_profile,
    detect_analytical_intent,
    explicitly_requested_chart_type,
    select_chart_type,
    select_chart_with_alternatives,
    select_family_alternatives,
)
from app.orchestration.visualization_preferences import VisualizationPreferences, preferred_chart_for_intent
from app.orchestration.visualization_personalization import PersonalizationHint, personalization_hint_for_chart
from app.orchestration.visualization_gaps import classify_data_shape, VisualizationGapType, FallbackOutputType
from app.orchestration.ranking_experiments import ExperimentContext, matches_targeting
from app.orchestration.schemas import (
    AnswerPresentation,
    PresentationChart,
    PresentationGraph,
    PresentationGuide,
    PresentationSeries,
    VisualizationGrammar,
    VisualizationLayer,
)

_logger = logging.getLogger(__name__)
_LLM_CONFIDENCE_THRESHOLD = float(os.getenv("PRESENTATION_LLM_CONFIDENCE_THRESHOLD", "0.6"))
_MULTI_AXIS_CHART_TYPES = {"dual_axis", "scatter", "bubble", "heatmap", "correlation_matrix"}
_LAYERED_VISUAL_REQUEST = re.compile(r"\b(?:layered|combo|combined|overlay|bar\s+and\s+line|line\s+and\s+bar|dual[\s-]*axis)\b", re.I)
_FACET_VISUAL_REQUEST = re.compile(r"\b(?:facet(?:ed)?|small\s+multiples?|separate\s+panels?)\b", re.I)


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_CITATION = re.compile(r"\s*\[REF-\d+\]\s*")
_MARKDOWN = re.compile(r"[*_`]")
_ORDERED_STEP = re.compile(r"(?m)^\s*\d+[.)]\s+")
_HEADING = re.compile(r"(?m)^#{1,4}\s+")
_HEADING_LINE = re.compile(r"^#{1,4}\s+(.+?)\s*$")
_ORDERED_LINE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_COMPARE_QUERY = re.compile(r"\b(compare|comparison|difference|versus|vs\.?|pros?\s+and\s+cons?)\b", re.IGNORECASE)
_TIMELINE_QUERY = re.compile(r"\b(timeline|schedule|deadline|due date|chronolog(?:y|ical)?)\b", re.IGNORECASE)
_CHECKLIST_QUERY = re.compile(r"\b(checklist|check list|review|verify|validation)\b", re.IGNORECASE)
_DECISION_QUERY = re.compile(r"\b(decision|decide|whether|if .+ then|flowchart|decision flow)\b", re.IGNORECASE)
_SEQUENCE_QUERY = re.compile(
    r"\b(sequence diagram|message flow|call flow|request flow|communicat\w*|interact\w*|"
    r"talks?\s+to|connects?\s+to)\b",
    re.IGNORECASE,
)
_PROCESS_QUERY = re.compile(r"\b(process|procedure|workflow|steps?|how\s+do\s+i|visuali[sz]e\s+how|moves?\s+through)\b", re.IGNORECASE)
_RELATIONSHIP_QUERY = re.compile(
    r"\b(relationships?|connected records?|evidence chains?|transaction lineage|"
    r"invoice[\s-]to[\s-]payment|trac(?:e|es|ing)|source dependenc\w*|"
    r"knowledge graph|evidence graph)\b",
    re.IGNORECASE,
)
_EVIDENCE_CHAIN_QUERY = re.compile(
    r"\b(evidence chains?|transaction lineage|trac(?:e|es|ing)|invoice[\s-]to[\s-]payment)\b",
    re.IGNORECASE,
)
_GRAPH_REQUIRED_HEADERS = {"source", "source type", "relationship", "target", "target type"}
_MONTH_NAME = re.compile(r"^(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)$", re.I)
_ACCOUNTING_QUERY = re.compile(r"\b(account(?:ing|s?)|ledger|journal|reconcil|revenue|expenses?|profit|budget|balance sheet|retained earnings|cash flow)\b", re.I)
_AUDIT_QUERY = re.compile(r"\b(audit|control|assertion|materiality|evidence|finding|risk|sampling|substantive)\b", re.I)
_TAX_QUERY = re.compile(r"\b(tax|vat|gst|filing|deduction|taxable|deferred tax|effective tax rate)\b", re.I)
# The composed answer's actual heading/ID phrasing ("### Result", lowercase
# "calculation ID `calc-...`" with no colon) never matched the original
# stricter pattern here — confirmed live (2026-07-24): both the depreciation
# and current-ratio calculation answers fell through to layout="descriptive"
# instead of "calculation", showing the wrong follow-up questions even
# though the calculation itself (and, where registered, its widget) was
# correct. Anchored on the calc-<hex> ID pattern instead, which is generated
# by formula_registry._new_calculation_id() and unique enough not to appear
# in any non-calculation answer; case/colon/backtick-insensitive so future
# phrasing drift in the compose prompt doesn't silently break this again.
_CALCULATION_ANSWER = re.compile(
    r"(?m)^### (?:Verified|Calculated) result\s*$|calculation id:?\s*`?calc-[0-9a-f]{6,}",
    re.IGNORECASE,
)
_MISSING_INPUT_ANSWER = re.compile(r"(?m)^## Information needed\s*$")
# "movement"/"bridge"/"waterfall" added 2026-08-03: a cash-flow-bridge
# request ("Show the movement to ending cash") named no literal
# chart/graph/plot/visualize word, so allow_automatic_chart stayed False
# and no chart was ever attempted even once the query correctly parsed as
# a signed-steps dataset — see presentation_dataprofile.py's FINANCIAL_
# MOVEMENT intent pattern and risk_classifier.py's _VISUALIZATION_KEYWORDS
# for the sibling fixes the same live query needed at the other two layers.
# "show"/"display" added the same day, mirroring risk_classifier.py's
# _VISUALIZATION_KEYWORDS fix — "Show customer conversion: 12,000
# visitors, ..." parsed into a perfectly good chartable table but never
# got a chart because "show" wasn't recognized here. Safe to broaden:
# this only ever matters when the composed answer ALSO contains a real
# parseable numeric table (see _chart_from_table's own strict shape
# checks) — a "show" query with no such table still produces zero charts.
_VISUAL_REQUEST = re.compile(r"\b(chart|graph|visuali[sz]e|plot|movement|bridge|waterfall|show|display|compar(?:e|ison)|rank(?:ing)?|break\s*down|distribution)\b", re.IGNORECASE)
_BROAD_EXPLANATION_QUERY = re.compile(
    r"\b(complete picture|full picture|comprehensive|detailed|in depth|overview)\b",
    re.IGNORECASE,
)
_GUIDE_REQUEST = re.compile(
    r"\b(checklist|check list|decision|flow(?:chart)?|timeline|schedule|swimlane|"
    r"process|procedure|workflow|steps?|how\s+do\s+i|visuali[sz]e\s+how|moves?\s+through|sequence diagram|message flow|"
    r"call flow|request flow|communicat\w*|interact\w*|talks?\s+to|connects?\s+to)\b",
    re.IGNORECASE,
)
_EDITABLE_WORKFLOW_QUERY = re.compile(r"\b(editable|drag[\s-]*and[\s-]*drop|move nodes?|add or delete|workflow builder)\b", re.I)
_JOURNAL_ENTRY_QUERY = re.compile(r"\b(?:journal\s+entry|debit|credit)\b", re.IGNORECASE)
_EVIDENCE_MATRIX_QUERY = re.compile(r"\b(?:scoring\s+matrix|evidence\s+matrix)\b", re.IGNORECASE)
_SWIMLANE_QUERY = re.compile(r"\bswimlane\b", re.IGNORECASE)
_NUMBER = re.compile(
    # Real gap (2026-08-03): a minus sign can legitimately appear on either
    # side of the currency symbol depending on which formatter produced the
    # cell — user_provided_data.py's _money() writes "-$90,000" (sign
    # first), while some other formatting writes "$-90,000" (currency
    # first). Only one order used to be accepted, so a negative dollar
    # figure written the other way failed to parse at all — and since a
    # single unparseable cell drops its entire column from the chart (see
    # _chart_from_table), one negative value silently zeroed out an entire
    # otherwise-perfectly-chartable table (e.g. a cash-flow bridge with any
    # reduction, or a budget-vs-actual variance column with any underrun).
    r"^\s*(?P<open>\()?\s*(?P<sign_before>-)?\s*(?P<currency>[$£€])?\s*(?P<sign_after>-)?"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<percent>%?)\s*"
    r"(?P<code>USD|GBP|EUR)?\s*\)?\s*$",
    re.IGNORECASE,
)


def _cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _plain(cell: str) -> str:
    # _CITATION consumed the whitespace on both sides of the marker along
    # with it — replacing "significance and [REF-3] risk" with "" collapsed
    # to "significance andrisk", concatenating the two real words the
    # citation sat between. A single space instead of "" preserves the word
    # boundary; the following whitespace-collapse absorbs the resulting
    # double space when the citation had space on both sides already.
    return re.sub(r"\s+", " ", _MARKDOWN.sub("", _CITATION.sub(" ", cell))).strip()


def _compact(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", _plain(text)).strip()
    return value if len(value) <= limit else f"{value[:limit - 1].rstrip()}…"


def _visual_step_label(text: str) -> str:
    # Guide cards wrap naturally in the UI. Preserve a complete validated
    # procedure sentence instead of truncating it into an ambiguous ellipsis.
    value = _compact(text, 280)
    if ":" in value:
        label = value.split(":", 1)[0].strip()
        if 3 <= len(label) <= 70:
            return label
    return value


def _extract_sections(markdown: str) -> list[str]:
    sections = []
    for line in markdown.splitlines():
        match = _HEADING_LINE.match(line.strip())
        if match and (title := _compact(match.group(1), 80)) not in sections:
            sections.append(title)
    return sections[:6]


def _extract_ordered_items(markdown: str) -> list[str]:
    """Extract already-validated numbered content without inventing facts."""
    items: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        match = _ORDERED_LINE.match(line)
        if match:
            if current:
                items.append(_visual_step_label(" ".join(current)))
            current = [match.group(1)]
        elif current and line.strip() and not _HEADING_LINE.match(line.strip()):
            current.append(line.strip())
        elif current:
            items.append(_visual_step_label(" ".join(current)))
            current = []
    if current:
        items.append(_visual_step_label(" ".join(current)))
    return [item for item in items if item][:10]


_GUIDE_TITLES = {
    "process": "Process overview",
    "timeline": "Timeline",
    "checklist": "Review checklist",
    "decision_flow": "Decision path",
    "sequence": "Sequence flow",
}


def _classify_ambiguous_guide(query: str, ordered_items: list[str]) -> tuple[str | None, str]:
    """LLM fallback tier — only reached when no rule above produced a
    confident guide type. Returns (guide_type, classification_source);
    guide_type is None when the LLM is unavailable, its output fails
    validation, or its confidence is too low to act on — the caller degrades
    to text-only (or a clarification follow-up for the low-confidence case)
    rather than guessing.
    """
    try:
        result = presentation_llm_classifier.classify(query, ordered_items)
    except Exception:
        result = None

    if result is None:
        _logger.info(
            "presentation_guide_classification unavailable",
            extra={"classification_source": "llm_unavailable"},
        )
        return None, "llm_unavailable"

    if result.guide_type not in _GUIDE_TITLES:
        # Covers the "text_only" sentinel and, defensively, any value that
        # should have been impossible under the strict JSON-schema enum.
        source = "llm_text_only" if result.guide_type == "text_only" else "llm_invalid_response"
        _logger.info(
            "presentation_guide_classification %s",
            source,
            extra={"classification_source": source, "confidence": result.confidence},
        )
        return None, source

    if result.requires_clarification or result.confidence < _LLM_CONFIDENCE_THRESHOLD:
        _logger.info(
            "presentation_guide_classification low_confidence",
            extra={
                "classification_source": "llm_low_confidence",
                "guide_type": result.guide_type,
                "confidence": result.confidence,
            },
        )
        return None, "llm_low_confidence"

    _logger.info(
        "presentation_guide_classification llm",
        extra={"classification_source": "llm", "guide_type": result.guide_type, "confidence": result.confidence},
    )
    return result.guide_type, "llm"


def _follow_ups(layout: str, query: str) -> list[str]:
    if layout == "calculation":
        return [
            "Explain what this result means.",
            "Show the calculation assumptions and methodology.",
            "Calculate a different scenario.",
        ]
    if _SEQUENCE_QUERY.search(query):
        return [
            "Explain what happens if a step in this sequence fails.",
            "Show this sequence as a swimlane instead.",
            "Add the audit logging step to this sequence.",
        ]
    if _DECISION_QUERY.search(query):
        return [
            "Explain each decision branch.",
            "Add evidence and approval requirements.",
            "Show the escalation path for unresolved items.",
        ]
    if _JOURNAL_ENTRY_QUERY.search(query):
        return [
            "Show the original, incorrect, and correcting entries together.",
            "Explain how this error affects revenue and receivables.",
            "Give me another correcting-entry example.",
        ]
    if _EVIDENCE_MATRIX_QUERY.search(query):
        return [
            "Apply this matrix to a practical audit example.",
            "Turn the matrix into a reviewer checklist.",
            "Explain when a critical override applies.",
        ]
    if _SWIMLANE_QUERY.search(query):
        return [
            "Add evidence and sign-off requirements to each role.",
            "Adapt this swimlane for a smaller finance team.",
            "Show the escalation path for unresolved differences.",
        ]
    if _TIMELINE_QUERY.search(query):
        return [
            "Turn this timeline into an owner-and-deadline checklist.",
            "Explain the controls at each stage.",
            "Show the common close bottlenecks.",
        ]
    if _CHECKLIST_QUERY.search(query):
        return [
            "Explain why each checklist item matters.",
            "Show the common mistakes to avoid.",
            "Adapt this checklist for a reviewer.",
        ]
    if layout == "step_by_step":
        return [
            "Turn this answer into a practical checklist.",
            "Explain the common mistakes to avoid.",
            "Show a grounded worked example.",
        ]
    if layout == "comparison":
        return [
            "Highlight the most important differences.",
            "Turn this comparison into a decision checklist.",
            "Explain this comparison with a grounded example.",
        ]
    if layout == "data_visualization":
        return [
            "Explain the main trend shown in this data.",
            "Highlight the largest changes.",
            "Summarize the data for an executive audience.",
        ]
    if layout == "descriptive":
        return [
            "Summarize the key points as a checklist.",
            "Explain this with a grounded example.",
            "What common mistakes should I avoid?",
        ]
    return ["Explain this in more detail.", "Give me a grounded example."]


def _chart_follow_ups(charts: list[PresentationChart]) -> list[str] | None:
    if not charts:
        return None
    if charts[0].type == "donut":
        return [
            "Explain the largest share in this composition.",
            "Compare this composition with another scenario.",
            "Summarize the composition for an executive audience.",
        ]
    return None


def _numeric(cell: str) -> tuple[str, str] | None:
    match = _NUMBER.match(_plain(cell))
    if not match:
        return None
    raw = match.group("number").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if match.group("sign_before") or match.group("sign_after") or match.group("open"):
        value = -value
    currency = match.group("currency") or (match.group("code") or "").upper()
    unit = "%" if match.group("percent") else currency
    return format(value, "f"), unit


def _extract_tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = markdown.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not _TABLE_SEPARATOR.match(lines[index + 1]):
            index += 1
            continue
        headers = [_plain(cell) for cell in _cells(lines[index])]
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            row = [_plain(cell) for cell in _cells(lines[index])]
            if len(row) != len(headers):
                break
            rows.append(row)
            index += 1
        if len(headers) >= 2 and rows:
            tables.append((headers, rows))
    return tables


def _domain(query: str) -> str:
    if _AUDIT_QUERY.search(query):
        return "audit"
    if _TAX_QUERY.search(query):
        return "tax"
    if _ACCOUNTING_QUERY.search(query):
        return "accounting"
    return "general"


def _experiment_decision(
    experiment_context: ExperimentContext | None, intent_value: str, default_chart_type: str | None,
) -> tuple[dict[str, float] | None, str, str | None, str | None]:
    """v7 — returns (weights_override, ranking_version, experiment_id,
    experiment_group) for ONE chart. weights_override is None unless an
    active experiment's targeting matched this chart's own intent/family
    AND deterministic assignment placed this conversation in the variant
    arm — in every other case (no experiment, targeting didn't match,
    assigned to control) the caller scores with the live production
    weights exactly as it always has. Targeting is evaluated against the
    DEFAULT chart_type's own family — computed identically whether or not
    an experiment exists (see select_chart_type/the pre-v5 ternary in the
    caller), so an experiment can never influence which family a chart
    even belongs to, only how alternatives within that family are scored."""
    if experiment_context is None:
        return None, RANKING_VERSION, None, None
    if not matches_targeting(experiment_context.targeting_rules, intent_value, chart_family(default_chart_type)):
        return None, RANKING_VERSION, None, None
    if experiment_context.group == "variant":
        return (
            experiment_context.variant_weights, experiment_context.variant_ranking_version,
            experiment_context.experiment_id, "variant",
        )
    return None, experiment_context.control_ranking_version, experiment_context.experiment_id, "control"


def _chart_from_table(
    headers: list[str], rows: list[list[str]], position: int, query: str,
    recent_chart_types: tuple[str, ...] = (), experiment_context: ExperimentContext | None = None,
    preferences: VisualizationPreferences | None = None,
    gap_collector: list[dict] | None = None,
    personalization_hint: PersonalizationHint | None = None,
) -> PresentationChart | None:
    # Observation distributions commonly exceed the old 12-row display
    # heuristic. The renderer and accessible table remain bounded at a safe
    # 200 supplied rows; no values are sampled or dropped before profiling.
    if not 1 <= len(rows) <= 200 or len(headers) > 6 or (len(rows) == 1 and len(headers) < 3):
        return None
    categories = [row[0] for row in rows]
    category_header_is_year = bool(headers and re.search(r"\byear\b", headers[0], re.I))
    if any(
        not category
        or (
            _numeric(category)
            and not (category_header_is_year and re.fullmatch(r"\d{4}", category))
        )
        for category in categories
    ):
        return None

    series: list[PresentationSeries] = []
    units: set[str] = set()
    series_numeric_cells: dict[int, list[tuple[str, str] | None]] = {}
    chart_columns = list(range(1, len(headers)))
    # Variance is valuable in the accessible table, but plotting it beside
    # the much larger Budget and Actual series makes their comparison harder
    # to read. Keep variance textual when both primary series are present.
    lowered_headers = {header.lower() for header in headers}
    if {"budget", "actual", "variance"}.issubset(lowered_headers):
        chart_columns = [i for i in chart_columns if headers[i].lower() != "variance"]
    for column in chart_columns:
        parsed = [_numeric(row[column]) for row in rows]
        if any(value is None for value in parsed):
            continue
        values = [value[0] for value in parsed if value is not None]
        column_units = {value[1] for value in parsed if value is not None and value[1]}
        if len(column_units) > 1:
            continue
        units.update(column_units)
        series.append(PresentationSeries(name=headers[column], values=values, unit=next(iter(column_units), "")))
        series_numeric_cells[column] = parsed

    if not series:
        return None
    title = headers[0] if len(series) == 1 else f"{headers[0]} comparison"
    is_temporal = bool(re.search(r"\b(period|quarter|month|year|date)\b", headers[0], re.I)) or all(
        _MONTH_NAME.match(category) for category in categories
    )
    composition_requested = bool(re.search(r"\b(composition|breakdown|share|allocation|mix|proportion)\b", query, re.I))

    # Dynamic Visualization Selection v1/v2/v3 — a deterministic analytical-
    # intent match takes priority over the older heuristic below when it
    # produces a real chart type; anything it doesn't have a chart for
    # (text_only, or a compatibility check that fails with no fallback —
    # see presentation_dataprofile.py) falls through to the existing logic
    # unchanged.
    #
    # v5 — temporal (line/area) and single-measure composition (donut/
    # composition_bar) now get ranked alternatives too, but the DEFAULT pick
    # for both is still computed by mirroring this exact pre-v5 ternary
    # shape (with two narrow, test-verified-safe additions below) rather
    # than by the intent-based dynamic engine, so every already-tested query
    # and data shape keeps its bit-for-bit unchanged default — see
    # select_family_alternatives' docstring for why this can't reuse
    # generate_candidates/_INTENT_PREFERENCE_LISTS the way v1-v4 chart types
    # do.
    profile = compute_data_profile(headers, rows, series_numeric_cells)
    intent = detect_analytical_intent(query)
    preferences = preferences or VisualizationPreferences()
    preferred_chart_type = preferred_chart_for_intent(preferences, intent.value)
    # v4 — recent_chart_types only ever reaches the scoring layer's small,
    # capped recent_repetition_penalty weight (see presentation_dataprofile's
    # _WEIGHTS); it can't affect anything upstream of this call, including
    # is_temporal or which candidates are even compatible.
    # v7 — see _experiment_decision. Reset to the (non-experiment) baseline
    # for every branch below; only overwritten when an active experiment's
    # targeting actually matches this specific chart's intent/family.
    ranking_version_for_chart = RANKING_VERSION
    experiment_id_for_chart: str | None = None
    experiment_group_for_chart: str | None = None
    # v10 — same reset-per-branch posture as the experiment fields above;
    # only ever non-None when personalization_hint is eligible AND this
    # exact branch's own (intent, chart_family) signal clears its own
    # confidence bar (see personalization_hint_for_chart).
    personalization_confidence_band_for_chart: str | None = None

    if is_temporal:
        # v5 — bit-for-bit the pre-v5 default (requirement: preserve
        # existing defaults exactly). A non-additive, mixed-unit 3+-series
        # shape would in principle prefer "line" over "area" (no fill
        # implying a combined total across incompatible units) — but the
        # _MULTI_AXIS_CHART_TYPES guard a few lines below already refuses to
        # render ANY non-multi-axis chart_type when len(units) > 1 unless
        # exactly 2 series triggered dual_axis above, so that shape produces
        # no chart today and continues to produce no chart; there's no
        # reachable case where overriding the default here would change the
        # actual rendered output, only dead code pretending to.
        temporal_default = "dual_axis" if len(units) > 1 and len(series) == 2 else "area"
        weights_override, ranking_version_for_chart, experiment_id_for_chart, experiment_group_for_chart = (
            _experiment_decision(experiment_context, intent.value, temporal_default)
        )
        personalized_type, personalization_boosts, personalization_confidence_band_for_chart = personalization_hint_for_chart(
            personalization_hint, intent.value, chart_family(temporal_default),
        )
        selection = select_family_alternatives(
            temporal_default, TEMPORAL_PREFERENCE, intent, profile, query, recent_chart_types, weights_override, preferred_chart_type,
            personalized_type, personalization_boosts,
        )
    else:
        baseline_default = select_chart_type(intent, profile, query)
        weights_override, ranking_version_for_chart, experiment_id_for_chart, experiment_group_for_chart = (
            _experiment_decision(experiment_context, intent.value, baseline_default)
        )
        personalized_type, personalization_boosts, personalization_confidence_band_for_chart = personalization_hint_for_chart(
            personalization_hint, intent.value, chart_family(baseline_default),
        )
        selection = select_chart_with_alternatives(
            intent, profile, query, recent_chart_types, weights_override, preferred_chart_type,
            personalized_type, personalization_boosts,
        )
    dynamic_chart_type = selection.chart_type if selection else None
    alternatives: list[str] = []
    original_chart_type: str | None = None
    fallback_note: str | None = None
    selection_source: str | None = None
    # v5 — reached only in exactly the situations the pre-v5 ternary's donut
    # branch was reached: the intent-based dynamic engine above produced
    # nothing (dynamic_chart_type is None) AND this isn't a temporal answer.
    # contains_zero_total_group is the one narrow addition here (no existing
    # test covers a zero-total single-measure composition row).
    if (
        not dynamic_chart_type and not is_temporal and composition_requested
        and len(series) == 1 and profile.part_to_whole_valid and not profile.contains_zero_total_group
    ):
        weights_override, ranking_version_for_chart, experiment_id_for_chart, experiment_group_for_chart = (
            _experiment_decision(experiment_context, intent.value, "donut")
        )
        personalized_type, personalization_boosts, personalization_confidence_band_for_chart = personalization_hint_for_chart(
            personalization_hint, intent.value, chart_family("donut"),
        )
        selection = select_family_alternatives(
            "donut", SINGLE_TOTAL_COMPOSITION_PREFERENCE, intent, profile, query, recent_chart_types, weights_override, preferred_chart_type,
            personalized_type, personalization_boosts,
        )
        dynamic_chart_type = selection.chart_type
    preference_affected = bool(preferred_chart_type and dynamic_chart_type == preferred_chart_type and selection and selection.selection_source != SelectionSource.EXPLICIT_USER_REQUEST)
    personalization_affected = bool(selection and selection.personalization_affected_selection)
    if not personalization_affected:
        personalization_confidence_band_for_chart = None
    if selection and selection.explicit_request_invalid and selection.requested_chart_type and gap_collector is not None:
        gap_collector.append({
            "analytical_intent": intent.value, "requested_chart_type": selection.requested_chart_type,
            "gap_type": VisualizationGapType.INCOMPATIBLE_REQUEST_DATA if chart_renderer(selection.requested_chart_type) else VisualizationGapType.UNSUPPORTED_PRODUCT_CAPABILITY,
            "data_shape_class": classify_data_shape(profile), "fallback_chart_type": dynamic_chart_type or "bar",
            "fallback_output_type": FallbackOutputType.CHART,
            "registry_candidate_count": len(selection.candidates),
        })
    if dynamic_chart_type:
        _logger.info(
            "presentation_chart_classification dynamic_engine",
            extra={
                "classification_source": "dynamic_engine", "intent": intent.value, "chart_type": dynamic_chart_type,
                "alternatives": list(selection.alternatives) if selection else [],
            },
        )
        chart_type = dynamic_chart_type
        alternatives = list(selection.alternatives) if selection else []
        original_chart_type = dynamic_chart_type
        selection_source = selection.selection_source.value if selection and selection.selection_source else None
        if selection and selection.explicit_request_invalid and selection.requested_chart_type:
            requested_label = selection.requested_chart_type.replace("_", " ")
            fallback_note = (
                f"You asked for a {requested_label} chart, but this data doesn't support one — "
                f"showing {chart_type.replace('_', ' ')} instead."
            )
    else:
        chart_type = "bar"
        # No scoring ever ran for this pure fallback — an experiment's
        # weights were never consulted, so neither should its bookkeeping be.
        ranking_version_for_chart = RANKING_VERSION
        experiment_id_for_chart = None
        experiment_group_for_chart = None
    grammar: VisualizationGrammar | None = None
    grammar_series = series[:4]
    if len(grammar_series) >= 2 and _FACET_VISUAL_REQUEST.search(query):
        grammar = VisualizationGrammar(
            composition="facet", facet_columns=min(2, len(grammar_series)),
            layers=[VisualizationLayer(mark="bar", series_index=index) for index in range(len(grammar_series))],
            fallback_chart_type=chart_type,
        )
    elif len(grammar_series) >= 2 and _LAYERED_VISUAL_REQUEST.search(query):
        grammar = VisualizationGrammar(
            composition="layer",
            layers=[
                VisualizationLayer(mark="bar", series_index=0, axis="primary"),
                *[
                    VisualizationLayer(
                        mark="line", series_index=index,
                        axis="secondary" if grammar_series[index].unit != grammar_series[0].unit else "primary",
                    )
                    for index in range(1, len(grammar_series))
                ],
            ],
            fallback_chart_type=chart_type,
        )
    # Charts with genuinely separate per-measure axes (scatter's x/y,
    # bubble's x/y/size, a heatmap or correlation matrix's per-row values)
    # are misleading with mixed units on ONE shared axis (the original
    # reason for this guard) but not when each measure keeps its own axis —
    # same exemption dual_axis already has.
    if len(units) > 1 and chart_type not in _MULTI_AXIS_CHART_TYPES and grammar is None:
        return None
    summary_mode = "latest" if is_temporal else "total"
    if chart_type == "correlation_matrix":
        labels, matrix = compute_correlation_matrix(headers, series_numeric_cells)
        matrix_categories = labels
        matrix_series = [PresentationSeries(name=label, values=matrix[i], unit="") for i, label in enumerate(labels)]
    else:
        matrix_categories = categories
        matrix_series = series[:4]
    return PresentationChart(
        chart_id=f"answer-table-{position + 1}",
        type=chart_type,
        title=title,
        categories=matrix_categories,
        series=matrix_series,
        # A correlation coefficient is always unitless — never the original
        # measures' currency/percent unit, regardless of what was correlated.
        unit="" if chart_type == "correlation_matrix" else next(iter(units), ""),
        domain=_domain(query),
        summary_mode=summary_mode,
        alternatives=alternatives,
        original_chart_type=original_chart_type,
        fallback_note=fallback_note,
        analytical_intent=intent.value,
        selection_source=selection_source,
        experiment_id=experiment_id_for_chart,
        experiment_group=experiment_group_for_chart,
        ranking_version=ranking_version_for_chart,
        preference_affected_selection=preference_affected,
        personalization_enabled=personalization_hint is not None,
        personalization_affected_selection=personalization_affected,
        personalization_model_version=personalization_hint.model_version if personalization_hint else None,
        personalization_confidence_band=personalization_confidence_band_for_chart,
        preferred_output=preferences.preferred_output,
        visual_density=preferences.visual_density,
        contrast_preference=preferences.contrast_preference,
        reduced_motion=preferences.reduced_motion,
        table_alternative_default_open=preferences.table_alternative_default_open,
        label_orientation=preferences.label_orientation,
        grammar=grammar,
    )


def _collapse(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Table cells already passed through _plain() by the time they reach here,
# which strips underscores as markdown emphasis markers (_MARKDOWN) — so
# "issued_by" written in an answer's table arrives as "issuedby", not
# "issued_by". Matching on a fully collapsed (letters+digits only) form of
# both the cell text and the canonical enum values makes this robust to
# spaces, hyphens, underscores, or the markdown-stripped run-together form
# alike. Unknown values pass through the collapsed text unchanged so they
# still fail presentation_graph's enum validation (rejected, not silently
# dropped) rather than mapping to nothing.
_ENTITY_TYPE_BY_COLLAPSED = {_collapse(value): value for value in presentation_graph.ENTITY_TYPES}
_RELATIONSHIP_TYPE_BY_COLLAPSED = {_collapse(value): value for value in presentation_graph.RELATIONSHIP_TYPES}


def _canonical_entity_type(cell: str) -> str:
    collapsed = _collapse(cell)
    return _ENTITY_TYPE_BY_COLLAPSED.get(collapsed, collapsed)


def _canonical_relationship_type(cell: str) -> str:
    collapsed = _collapse(cell)
    return _RELATIONSHIP_TYPE_BY_COLLAPSED.get(collapsed, collapsed)


def _graph_table(headers: list[str], rows: list[list[str]]) -> tuple[list[dict], list[dict]] | None:
    """Parse an edge-list-shaped GFM table (Source | Source Type |
    Relationship | Target | Target Type [| Reference] [| Status]) into raw
    node/edge dicts, ready for presentation_graph.build_graph's strict
    validation. Returns None if the table isn't shaped this way — this is
    the only source of graph data; nothing here is invented."""
    lowered = [header.lower() for header in headers]
    if not _GRAPH_REQUIRED_HEADERS.issubset(lowered):
        return None
    index = {name: lowered.index(name) for name in _GRAPH_REQUIRED_HEADERS}
    reference_index = lowered.index("reference") if "reference" in lowered else None
    status_index = lowered.index("status") if "status" in lowered else None

    raw_nodes: dict[str, dict] = {}
    raw_edges: list[dict] = []
    for position, row in enumerate(rows):
        source_id = row[index["source"]].strip()
        target_id = row[index["target"]].strip()
        if not source_id or not target_id:
            continue
        reference = row[reference_index].strip() if reference_index is not None else ""
        status = row[status_index].strip() if status_index is not None else ""
        if source_id not in raw_nodes:
            raw_nodes[source_id] = {
                "id": source_id,
                "label": source_id,
                "entity_type": _canonical_entity_type(row[index["source type"]]),
            }
        if target_id not in raw_nodes:
            raw_nodes[target_id] = {
                "id": target_id,
                "label": target_id,
                "entity_type": _canonical_entity_type(row[index["target type"]]),
                "status": status,
                "source_reference": reference,
            }
        relationship = row[index["relationship"]].strip()
        raw_edges.append({
            "id": f"edge-{position + 1}",
            "source": source_id,
            "target": target_id,
            "relationship_type": _canonical_relationship_type(relationship),
            "label": relationship,
        })
    if not raw_nodes or not raw_edges:
        return None
    return list(raw_nodes.values()), raw_edges


def _is_hub_topology(raw_edges: list[dict]) -> bool:
    """True when every edge touches one common node — a single central
    entity, which reads best as a concentric layout rather than a chain
    (breadthfirst) or a general network (cose)."""
    if len(raw_edges) < 2:
        return False
    touched = Counter()
    for edge in raw_edges:
        touched[edge["source"]] += 1
        touched[edge["target"]] += 1
    _hub, hub_count = touched.most_common(1)[0]
    return hub_count >= len(raw_edges)


def _build_relationship_graph(query: str, tables: list[tuple[list[str], list[list[str]]]]) -> PresentationGraph | None:
    if not _RELATIONSHIP_QUERY.search(query):
        return None
    for position, (headers, rows) in enumerate(tables):
        extracted = _graph_table(headers, rows)
        if extracted is None:
            continue
        raw_nodes, raw_edges = extracted
        layout = (
            "breadthfirst" if _EVIDENCE_CHAIN_QUERY.search(query)
            else "concentric" if _is_hub_topology(raw_edges)
            else "cose"
        )
        node_count, edge_count = len(raw_nodes), len(raw_edges)
        graph, validation_result = presentation_graph.build_graph(
            graph_id=f"answer-graph-{position + 1}",
            title="Evidence chain" if _EVIDENCE_CHAIN_QUERY.search(query) else "Relationship graph",
            summary=(
                f"{node_count} record{'s' if node_count != 1 else ''} connected by "
                f"{edge_count} relationship{'s' if edge_count != 1 else ''}."
            ),
            raw_nodes=raw_nodes,
            raw_edges=raw_edges,
            layout=layout,
            confidence=1.0,
        )
        _logger.info(
            "presentation_graph_construction %s",
            validation_result,
            extra={"classification_source": "table_extraction", "validation_result": validation_result},
        )
        if graph is not None:
            return graph
    return None


def _graph_follow_ups(graphs: list[PresentationGraph]) -> list[str] | None:
    if not graphs:
        return None
    return [
        "Explain the weakest link in this chain.",
        "Show the supporting documents for each record.",
        "What would break this reconciliation?",
    ]


def build_answer_presentation(
    query: str, answer_text: str, recent_chart_types: tuple[str, ...] = (),
    experiment_context: ExperimentContext | None = None,
    preferences: VisualizationPreferences | None = None,
    gap_collector: list[dict] | None = None,
    personalization_hint: PersonalizationHint | None = None,
) -> AnswerPresentation:
    tables = _extract_tables(answer_text)
    is_calculation = bool(_CALCULATION_ANSWER.search(answer_text))
    is_missing_input = bool(_MISSING_INPUT_ANSWER.search(answer_text))
    temporal_table = any(
        headers and re.search(r"\b(period|quarter|month|year|date)\b", headers[0], re.I)
        for headers, _rows in tables
    )
    supplied_dataset = bool(re.search(r"\bq[1-4]\b.*[$£€]|accounts?[\s-]+receivable\s+aging.*[$£€]|ratio.*benchmark", query, re.I))
    analytical_intent = detect_analytical_intent(query)
    intent_requests_visual_analysis = analytical_intent in {
        AnalyticalIntent.CORRELATION,
        AnalyticalIntent.DISTRIBUTION,
        AnalyticalIntent.FINANCIAL_MOVEMENT,
        AnalyticalIntent.FLOW,
    }
    allow_automatic_chart = bool(_VISUAL_REQUEST.search(query)) or explicitly_requested_chart_type(query) is not None or intent_requests_visual_analysis or (temporal_table and not is_calculation) or supplied_dataset or (preferences is not None and preferences.preferred_output == "chart")
    charts = [
        chart
        for position, (headers, rows) in enumerate(tables)
        if allow_automatic_chart
        and (chart := _chart_from_table(headers, rows, position, query, recent_chart_types, experiment_context, preferences, gap_collector, personalization_hint)) is not None
    ]
    if gap_collector is not None and not gap_collector:
        requested = explicitly_requested_chart_type(query)
        if requested and not tables:
            gap_collector.append({
                "analytical_intent": detect_analytical_intent(query).value, "requested_chart_type": requested,
                "gap_type": VisualizationGapType.INSUFFICIENT_EXTRACTED_DATA,
                "data_shape_class": classify_data_shape(compute_data_profile([], [], {})),
                "fallback_chart_type": None, "fallback_output_type": FallbackOutputType.TEXT,
                "registry_candidate_count": 0,
            })
    relationship_graph = (
        _build_relationship_graph(query, tables)
        if not is_calculation and not is_missing_input
        else None
    )
    graphs = [relationship_graph] if relationship_graph is not None else []
    has_steps = bool(_ORDERED_STEP.search(answer_text))
    has_headings = bool(_HEADING.search(answer_text))
    if is_missing_input:
        layout = "concise"
    elif is_calculation:
        layout = "calculation"
    elif has_steps and _TIMELINE_QUERY.search(query):
        layout = "step_by_step"
    elif charts or graphs:
        layout = "data_visualization"
    elif tables or _COMPARE_QUERY.search(query):
        layout = "comparison"
    elif has_steps:
        layout = "step_by_step"
    elif has_headings:
        layout = "descriptive"
    else:
        layout = "concise"
    ordered_items = _extract_ordered_items(answer_text)
    if not ordered_items and _TIMELINE_QUERY.search(query) and tables:
        headers, rows = tables[0]
        ordered_items = [
            _compact(" — ".join(row[: min(3, len(headers))]), 280)
            for row in rows[:10]
        ]
    guides: list[PresentationGuide] = []
    clarification_follow_up: str | None = None
    if ordered_items and not is_calculation and not is_missing_input and _GUIDE_REQUEST.search(query):
        classification_source = "rules"
        if _SEQUENCE_QUERY.search(query):
            guide_type = "sequence"
        elif _DECISION_QUERY.search(query):
            guide_type = "decision_flow"
        elif _TIMELINE_QUERY.search(query):
            guide_type = "timeline"
        elif _CHECKLIST_QUERY.search(query):
            guide_type = "checklist"
        elif _PROCESS_QUERY.search(query):
            guide_type = "process"
        else:
            # No rule above produced a confident type even though the query
            # clearly wants some kind of process/workflow visual — hand off
            # to the schema-constrained LLM fallback tier.
            guide_type, classification_source = _classify_ambiguous_guide(query, ordered_items)
        if guide_type is not None:
            _logger.info(
                "presentation_guide_classification %s",
                classification_source,
                extra={"classification_source": classification_source, "guide_type": guide_type},
            )
            guides.append(PresentationGuide(
                guide_id="answer-guide-1",
                type=guide_type,
                title=_GUIDE_TITLES[guide_type],
                items=ordered_items,
                domain=_domain(query),
                renderer=(
                    "react_flow" if _EDITABLE_WORKFLOW_QUERY.search(query)
                    else "mermaid" if guide_type in {"timeline", "decision_flow", "sequence"} or (guide_type == "process" and _VISUAL_REQUEST.search(query))
                    else "html"
                ),
                editable=bool(_EDITABLE_WORKFLOW_QUERY.search(query)),
            ))
        elif classification_source == "llm_low_confidence":
            clarification_follow_up = "Would you like this shown as a flowchart, timeline, checklist, or process overview?"
    return AnswerPresentation(
        layout=layout,
        table_count=len(tables),
        has_steps=has_steps,
        charts=charts,
        guides=guides,
        graphs=graphs,
        sections=(
            _extract_sections(answer_text)
            if layout == "descriptive" and _BROAD_EXPLANATION_QUERY.search(query)
            else []
        ),
        follow_up_questions=(
            [] if is_missing_input
            else [clarification_follow_up] if clarification_follow_up
            else (_chart_follow_ups(charts) or _graph_follow_ups(graphs) or _follow_ups(layout, query))
        ),
    )
