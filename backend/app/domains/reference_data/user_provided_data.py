"""Governed evidence and deterministic presentation for values in a query."""
from __future__ import annotations

import re
import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

USER_PROVIDED_DATA_GOVERNED_SOURCE_ID = "src-kriton-user-provided-data"
USER_PROVIDED_DATA_NODE_PREFIX = "user-provided-data-"
# Real gap (2026-08-04): "Alpha Corp $4.2B" silently answered with "$4.20"
# — nine orders of magnitude wrong — because the old pattern stopped at the
# digits and simply discarded the trailing "B", producing a confidently
# WRONG figure rather than a rejection. The abbreviated-magnitude suffix
# (K/M/B, optionally "n" as in "Bn", or the spelled-out word) is folded
# into this SAME capture group (not a new one) so every one of the ~15
# patterns that embed _NUMBER keeps its existing group count/positions —
# _decimal() below is what actually applies the multiplier. The trailing
# \b keeps a bare number followed by an unrelated word ("40 Boxes", "12
# Miles") from having its first letter mistaken for a magnitude suffix —
# \b only matches immediately after "K"/"M"/"B" when what follows isn't
# itself a word character, so "Boxes"/"Miles" never qualify.
_NUMBER = r"[$£€]?\s*(\d(?:\d|,(?=\d))*(?:\.\d+)?\s?(?:[KkMmBb]n?|thousand|million|billion)?\b)"
# Real gap (2026-08-03): "February ($7,500)" (accounting parenthesis
# notation) and "South -$18,000" (leading minus sign) both failed to match
# _NUMBER at all — the "(" or "-" sits exactly where _NUMBER's own optional
# currency symbol is checked, so the digit group never even starts. Adds
# an optional wrapping "(...)" and an optional leading "+"/"-" AROUND
# _NUMBER, in two extra (non-inner) groups a caller checks explicitly (see
# _signed_decimal) — deliberately only used by _PERIOD_VALUE and
# _CATEGORY_VALUE below, not swapped in everywhere _NUMBER already
# appears, so every other pattern's existing group-count/positions (and
# their tests) are completely unaffected.
_SIGNED_NUMBER = rf"(\()?\s*[+]?(-)?\s*{_NUMBER}\s*(\))?"
_PERIOD = r"(Q[1-4]|January|February|March|April|May|June|July|August|September|October|November|December)"
_PERIOD_RESULTS = re.compile(rf"\b{_PERIOD}\b[^.;]*?revenue\s*{_NUMBER}[^.;]*?expenses?\s*{_NUMBER}", re.I)
_PERIOD_VALUE = re.compile(rf"\b{_PERIOD}\b\s*{_SIGNED_NUMBER}", re.I)
# Live bug: this required the revenue figure to sit immediately after the
# period marker with only whitespace between them, so natural phrasing like
# "Q1 revenue $500,000 and gross margin 40%" (the word "revenue" in between)
# never matched — it fell through all the way to the generic _CATEGORY_VALUE
# fallback, which misread "Gross Margin"/"Margin" as a category name and
# silently dropped the revenue figures entirely. The gaps now tolerate
# filler words the same way _PERIOD_RESULTS above already does, while still
# excluding sentence/quarter-boundary punctuation (,;.  before the number,
# ;. after it — a comma is kept there since "revenue X, margin Y%" is
# common) so one quarter's match can't bleed into the next.
_PERIOD_REVENUE_MARGIN = re.compile(rf"\b{_PERIOD}\b[^,;.]*?{_NUMBER}[^;.%]*?(\d+(?:\.\d+)?)\s*%", re.I)
# Real gap (2026-08-04): "Our current ratio IS 1.8 against AN INDUSTRY
# benchmark of 2.0" matched nothing — the old pattern only accepted "of"
# (not "is"/"was") before the first number, and only a bare "a benchmark"
# (not "an industry benchmark"/"a peer group benchmark") before the
# second. Broadened to accept 0-2 filler words between "against" and
# "benchmark", and "is"/"was"/"of" (or nothing) before either number. The
# leading "our"/"my"/"the" strip keeps the extracted label as just the
# ratio name ("current ratio"), not "Our current ratio".
_RATIO_BENCHMARK = re.compile(
    r"\b(?:compare\s+(?:a\s+)?|our\s+|my\s+|the\s+)*([A-Za-z][A-Za-z -]*?ratio)\s+(?:is|was|of)?\s*(\d+(?:\.\d+)?)\s+against\s+"
    r"(?:(?:a|an|the)\s+)?(?:[A-Za-z]+\s+){0,2}benchmark\s+(?:of|is|was)?\s*(\d+(?:\.\d+)?)",
    re.I,
)
_AGING_BUCKET = re.compile(r"\b(current|1[–-]30\s+days?|31[–-]60\s+days?|61[–-]90\s+days?|over\s+90\s+days?)\s*" + _NUMBER, re.I)
_BUDGET_ACTUAL = re.compile(rf"\b([A-Za-z][A-Za-z &/-]*?)\s+budget\s*{_NUMBER}\s*(?:and|,)?\s*actual\s*{_NUMBER}", re.I)
# Real gap (2026-08-04): "Fieldwork 120 versus 145, Review 40 versus 38,
# Reporting 20 versus 27" only matched its FIRST row — the anchor only
# recognized ":"/";" as a row boundary, not the plain comma this natural
# phrasing actually uses between rows, so every row after the first was
# silently dropped.
_VERSUS_PAIR = re.compile(rf"(?:^|[:;,])\s*([A-Za-z][A-Za-z &/-]{{0,40}}?)\s+{_NUMBER}\s+(?:versus|vs\.?)\s+{_NUMBER}", re.I)
# Real gap (2026-08-04): "Show planned versus actual hours for the audit:
# Fieldwork 120 versus 145, ..." has genuine two-measure "N versus M" rows
# but neither "budget" nor "actual" — wait, "actual" IS present here, but
# "budget" is not, and the budget_rows fallback below required BOTH
# literal words, so it never even tried _VERSUS_PAIR and instead fell
# through to the generic single-measure fallback, which silently dropped
# every row's second ("versus") figure. This label pair, pulled from the
# query's own intro clause (the first "<word> versus <word>" — the later
# per-row matches are number-versus-number, not word-versus-word, so they
# never compete with this), gives the two measure columns real names
# instead of a vocabulary-specific "Budget"/"Actual" guess.
_VERSUS_HEADER_HINT = re.compile(r"\b([A-Za-z]+)\s+(?:versus|vs\.?)\s+([A-Za-z]+)\b", re.I)
_BALANCE = re.compile(rf"\b(cash|(?:accounts?\s+)?receivables?|inventory)\s*(?:balance\s*)?{_NUMBER}", re.I)
_CATEGORY_VALUE = re.compile(
    rf"(?:^|[:,;]|\band\b)\s*([A-Za-z][A-Za-z &/-]{{0,40}}?)\s+{_SIGNED_NUMBER}", re.I
)
# Real gap (2026-08-03): "We had 12,000 visitors, 3,400 signups, and 890
# customers this month" — a funnel/count convention that puts the NUMBER
# first — matched none of the above patterns (all require the label before
# the number) and fell through to general LLM composition with no
# supplied-dataset grounding at all, producing an answer that wandered into
# unrelated retrieved content. The anchor also needs a negative lookbehind
# on the comma/semicolon branch — without it, the thousands-separator comma
# INSIDE "12,000" itself is mistaken for a row boundary, truncating the
# value to "000" — and a small lead-verb group ("had", "recorded", ...) so
# the very first figure in a sentence (which has no preceding delimiter,
# only a verb) is still captured. Engaged as a fallback (see
# extract_user_data_table) only when it captures MORE rows than the
# label-first form above, so it never overrides that far more common
# "Label Number" phrasing except to recover figures that pattern missed.
_VALUE_FIRST_LEAD_VERB = (
    r"\b(?:had|has|saw|recorded|reported|received|generated|achieved|"
    r"totaled|totalled|counted|logged|produced|were|was)\b"
)
# Real gap (2026-08-04): "fifteen thousand ON ads, eight thousand ON
# events, and twelve thousand ON content. Chart it." (after spelled-out
# numbers are normalized to digits) exposed two more gaps in this same
# pattern: (1) the filler preposition ("on"/"for"/"toward(s)") between the
# number and its label was being swallowed INTO the label itself
# ("on ads" instead of "ads"), and (2) the very last item's terminator —
# "content. Chart it." — has a period followed by a NEW sentence, not the
# absolute end of the whole query string, so the old "[.!?]?$" (which only
# matched a period immediately before end-of-string) rejected it outright
# and silently dropped the final row.
_VALUE_FIRST_CATEGORY = re.compile(
    rf"(?:^|(?<!\d)[:,;]|\band\b|{_VALUE_FIRST_LEAD_VERB})\s*{_NUMBER}\s+"
    rf"(?:on\s+|for\s+|toward(?:s)?\s+)?([A-Za-z][A-Za-z &/-]{{0,40}}?)"
    rf"(?=,|\band\b|[.!?](?:\s|$)|$|\s+(?:this|that|last|next|per|for)\b)",
    re.I,
)
# Real gap (2026-08-04): "Our current ratio is 1.8 against an industry
# benchmark of 2.0" was misread as an external-evidence request ("current
# ... benchmark") purely because both words appeared anywhere in the same
# sentence — the unbounded ".*" let "current" (describing the user's own
# supplied ratio) and "benchmark" (the user's own supplied comparison
# figure) collide across six unrelated words in between. Bounded to a
# 0-2-word gap so it still catches "the current tax rate" (0 words
# between) but not a whole independent clause. "benchmark" is dropped from
# this branch entirely — a user-supplied numeric benchmark is exactly what
# _RATIO_BENCHMARK above already extracts safely; an authoritative
# external benchmark lookup would need much more specific phrasing than
# the word "benchmark" alone to justify rejecting supplied data.
_EXTERNAL_EVIDENCE_REQUEST = re.compile(
    r"\b(?:verify|validate|confirm|check)\b.*\b(?:official|record|source|correct|accurate)\b|"
    r"\b(?:current|latest)\b(?:\s+\w+){0,2}\s+\b(?:tax|rate|law|standard|policy)\b|"
    r"\b(?:tax|legal|law|regulation|policy)\b.*\b(?:current|latest|applicable|requirement)\b",
    re.I,
)
_DATA_OPERATION = re.compile(
    r"\b(?:calculat(?:e|ion)|summari[sz]e|compar(?:e|ison)|visuali[sz]e|chart|graph|plot|"
    r"break\s*down|distribution|histogram|box\s*plot|radar|table|analy[sz]e|show|display|"
    r"rank(?:ing)?|aging|ageing|review|explain|identify)\b",
    re.I,
)
_DISTRIBUTION_PREFIX = re.compile(
    r"\b(?:transaction|observation|sample|data)\s+values?\s*(?:are|:|=)\s*(.+?)(?:[.;]|$)", re.I,
)
# Real gap (2026-08-04): "Plot our weekly active users over the last 6
# weeks: 1200, 1350, ..." and "Show a histogram of order sizes: 45, 52,
# ..." used a fixed, narrow vocabulary above ("transaction/observation/
# sample/data value(s)") that doesn't cover arbitrary plural nouns
# ("visitors", "order sizes", "response times") introducing an unlabeled
# number list. This fallback instead looks at SHAPE, not vocabulary: if
# everything after the query's last colon is nothing but a comma-separated
# list of plain numbers (each optionally carrying a currency symbol or a
# trailing %) through to the end of the sentence, that's an unlabeled
# distribution regardless of what noun phrase introduced it. Because it
# requires the ENTIRE tail to be numbers-only, it never mismatches a
# labeled shape like "Salaries 45%, Rent 15%, ..." (those still have
# letters mixed into the tail, so this pattern simply doesn't match).
_GENERIC_COLON_NUMBER_LIST = re.compile(
    r":\s*((?:[$£€]?\s*-?\d[\d,]*(?:\.\d+)?%?\s*,\s*)+[$£€]?\s*-?\d[\d,]*(?:\.\d+)?%?)\s*[.!?]?\s*$"
)
# Real gap (2026-08-03): row separation between entities used to require a
# literal semicolon ("North: ...; South: ...; West: ..."). Natural rephrasing
# with commas instead ("North: headcount 45, revenue 900000, margin 12,
# South: headcount 30, ...") silently dropped every measure but the first
# for each entity — the generic single-measure fallback matched isolated
# "<word> <number>" pairs with no idea the query was ever multi-measure.
# A comma is only treated as a row boundary when what follows it looks like
# a real entity label — at most two words — immediately followed by a
# colon. Two constraints, not one, are load-bearing here:
#   1. Requiring a colon at all excludes a comma that's just separating two
#      measures within a row (never followed by ":").
#   2. Capping the label at two words additionally excludes a comma inside
#      an instruction/intro clause that happens to end in its own colon
#      (e.g. "...comparing headcount, revenue, and margin across regions:
#      North: ..." — "and margin across regions" is 4 words and correctly
#      never mistaken for a row boundary, while "North"/"West Region" are).
_ROW_BOUNDARY = re.compile(r"[;,]\s*(?=(?:[A-Za-z][A-Za-z0-9&'-]*\s+){0,1}[A-Za-z][A-Za-z0-9&'-]*\s*:)")
_ROW_SEGMENT = re.compile(r"([A-Za-z0-9][A-Za-z0-9 &/'-]{0,40})\s*:\s*([^;]+)")
_NAMED_MEASURE = re.compile(
    rf"\b((?:[A-Za-z][A-Za-z0-9 /()-]{{0,30}}?|20\d{{2}}))\s*([+-]?)\s*{_NUMBER}\s*(%)?\s*(?=,|\band\b|[.!?]?$)", re.I
)
# Real gap (2026-08-04): "Q1 labor $40,000 materials $25,000 overhead
# $10,000, Q2 labor $42,000 ..." chains several "<measure> <value>" pairs
# back-to-back with only a space between them — no comma, "and", or
# sentence end separates one measure from the next the way _NAMED_MEASURE
# above requires. Used only inside _extract_period_multi_measure_rows,
# scoped to the text between one period token and the next, so it can
# never run past a row boundary the way an unscoped "word number" pair
# search would.
_PERIOD_TOKEN = re.compile(rf"\b{_PERIOD}\b", re.I)
_MEASURE_VALUE_PAIR = re.compile(rf"\b([A-Za-z][A-Za-z]{{0,20}})\s+{_NUMBER}", re.I)
_SIGNED_MEASURE_VALUE_PAIR = re.compile(
    rf"\b([A-Za-z][A-Za-z]{{0,20}})\s+([+-]?)\s*{_NUMBER}\s*(%)?", re.I
)

# Real gap (2026-08-03): "Compare Vendor A, Vendor B, and Vendor C on
# quality, delivery speed, reliability, and cost efficiency: Vendor A 82,
# 75, 91, 68; Vendor B 76, 88, 84, 73; Vendor C 90, 72, 86, 79." names each
# measure ONCE up front rather than repeating the measure name next to
# every number (the shape _NAMED_MEASURE/_extract_multi_measure_rows
# requires) — every number after "Vendor A" is purely positional. Falling
# through to the generic single-measure fallback captured only "Vendor A
# 82" and silently dropped 75/91/68. This is intentionally the LAST
# pattern tried (see extract_inline_dataset) — positional matching has no
# anchor tying a specific number to a specific measure beyond ORDER, so it
# only engages once every more specific, self-labeling pattern has failed.
_MEASURE_LIST_INTRO = re.compile(r"\bon\s+([A-Za-z][A-Za-z ,/&-]{0,120}?)\s*:", re.I)
_ENTITY_NUMBER_LIST = re.compile(
    r"\b([A-Za-z][A-Za-z0-9 &/'-]{0,30}?)\s+((?:\d[\d,]*(?:\.\d+)?%?\s*,\s*)*\d[\d,]*(?:\.\d+)?%?)\s*(?=;|\.|$)", re.I,
)

# Real gap (2026-08-03): "Starting cash was $500k. Operations added $180k,
# equipment purchases reduced it by $90k, ... Show the movement to ending
# cash." has no measure name repeated per row (unlike _NAMED_MEASURE's
# shape) and each figure uses a "k" shorthand none of the other patterns in
# this module parse — it fell all the way through to the generic
# _CATEGORY_VALUE fallback, which mangled whole clauses into category
# labels ("Equipment Purchases Reduced It By") and silently dropped
# "Operations added $180k" outright (not immediately preceded by one of
# _CATEGORY_VALUE's required anchors). A dedicated cash/balance-bridge
# extractor recognizes the "Starting X was N. Y added N, Z reduced it by
# N..." narrative shape directly, preserves the +/- sign of each movement,
# and computes the ending balance itself (start + every movement) rather
# than ever inventing or asking the model to compute it — this is exactly
# the signed_steps shape presentation_dataprofile.py's _reconciles_as_bridge
# validates before a waterfall chart is ever offered.
_BRIDGE_NUMBER = rf"{_NUMBER}\s*([kKmM])?\b"
_STARTING_BALANCE = re.compile(
    rf"\bstarting\s+([A-Za-z][A-Za-z /&-]{{0,30}}?)\s+(?:was|is|of|at)\s*{_BRIDGE_NUMBER}", re.I,
)
_POSITIVE_MOVEMENT = re.compile(
    rf"\b([A-Za-z][A-Za-z /&-]{{0,30}}?)\s+(?:added|increased|grew|contributed|generated)(?:\s+it)?\s*{_BRIDGE_NUMBER}", re.I,
)
_NEGATIVE_MOVEMENT = re.compile(
    rf"\b([A-Za-z][A-Za-z /&-]{{0,30}}?)\s+(?:reduced|decreased|lowered)\s+it\s+by\s*{_BRIDGE_NUMBER}", re.I,
)

_logger = logging.getLogger(__name__)

ProvenanceClass = Literal[
    "user_supplied_current_turn", "retrieved_authoritative_source",
    "retrieved_secondary_source", "connected_private_source",
    "prior_conversation_value", "model_inferred_value", "unsupported_value",
]


@dataclass(frozen=True)
class UserDataTable:
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str | Decimal, ...], ...]
    explanation: str = ""


@dataclass(frozen=True)
class InlineDataset:
    """Lossless, current-turn-only evidence handed to composition and charts."""

    dataset_id: str
    provenance: ProvenanceClass
    dimensions: tuple[str, ...]
    measures: tuple[str, ...]
    rows: tuple[tuple[str | Decimal, ...], ...]
    units: tuple[str, ...]
    currency: str | None
    temporal_granularity: str | None
    ordering: Literal["supplied", "not_applicable"]
    completeness_status: Literal["complete", "incomplete"]
    ambiguity_status: Literal["unambiguous", "ambiguous"]
    title: str
    explanation: str = ""

    def as_table(self) -> UserDataTable:
        return UserDataTable(
            self.title, self.dimensions + self.measures, self.rows, self.explanation
        )


def requires_external_evidence(query: str) -> bool:
    return bool(_EXTERNAL_EVIDENCE_REQUEST.search(query))


def _dataset_id(headers: tuple[str, ...], row_count: int) -> str:
    # Shape-derived only: no values or labels enter identifiers/telemetry.
    shape = f"{len(headers)}:{row_count}"
    return "inline-" + hashlib.sha256(shape.encode()).hexdigest()[:12]


def _inline(table: UserDataTable, *, units: tuple[str, ...] = (), currency: str | None = None,
            temporal_granularity: str | None = None) -> InlineDataset:
    dimensions = (table.headers[0],)
    measures = tuple(table.headers[1:])
    dataset = InlineDataset(
        dataset_id=_dataset_id(table.headers, len(table.rows)),
        provenance="user_supplied_current_turn", dimensions=dimensions, measures=measures,
        rows=table.rows, units=units or tuple("" for _ in measures), currency=currency,
        temporal_granularity=temporal_granularity, ordering="supplied",
        completeness_status="complete", ambiguity_status="unambiguous",
        title=table.title, explanation=table.explanation,
    )
    _logger.info("inline_dataset_detected", extra={
        "inline_dataset_detected": True, "extracted_row_count": len(dataset.rows),
        "extracted_dimension_count": len(dataset.dimensions),
        "extracted_measure_count": len(dataset.measures), "provenance_class": dataset.provenance,
        "completeness_status": dataset.completeness_status,
        "ambiguity_status": dataset.ambiguity_status,
    })
    return dataset


# Real gap (2026-08-04): "Plot the relationship between marketing spend
# and new customers: ($5,000, 120), ($8,000, 210), ..." — paired (x, y)
# observations in parenthesized tuples — matched nothing at all; every
# existing pattern assumes one label per number, not two numbers per
# point. The intro's "between X and Y" phrasing supplies real axis names
# when present; a query using the tuple shape without that phrasing still
# extracts, just with generic "X"/"Y" headers.
_SCATTER_LABEL_INTRO = re.compile(r"\bbetween\s+([A-Za-z][A-Za-z /&-]{0,40}?)\s+and\s+([A-Za-z][A-Za-z /&-]{0,40}?)\s*:", re.I)
_PAIRED_TUPLE = re.compile(rf"\(\s*{_NUMBER}\s*,\s*{_NUMBER}\s*\)")


def _extract_scatter_pairs(query: str) -> UserDataTable | None:
    pairs = _PAIRED_TUPLE.findall(query)
    if len(pairs) < 2:
        return None
    label_match = _SCATTER_LABEL_INTRO.search(query)
    x_label = _label(label_match.group(1)) if label_match else "X"
    y_label = _label(label_match.group(2)) if label_match else "Y"
    rows = tuple((f"Point {index}", _decimal(x), _decimal(y)) for index, (x, y) in enumerate(pairs, 1))
    return UserDataTable(
        f"{x_label} versus {y_label}", ("Observation", x_label, y_label), rows,
        "Based on the paired figures supplied in your question.",
    )


def _extract_distribution(query: str) -> UserDataTable | None:
    match = _DISTRIBUTION_PREFIX.search(query) or _GENERIC_COLON_NUMBER_LIST.search(query)
    if not match:
        return None
    pieces = re.split(r"\s*,\s*|\s+and\s+", match.group(1).strip())
    values: list[Decimal] = []
    for piece in pieces:
        token = re.fullmatch(r"\s*[$£€]?\s*(-?\d+(?:\.\d+)?)\s*%?\s*", piece)
        if not token:
            return None
        values.append(_decimal(token.group(1)))
    if len(values) < 2:
        return None
    return UserDataTable(
        "Supplied observation distribution", ("Observation", "Value"),
        tuple((f"Observation {index}", value) for index, value in enumerate(values, 1)),
        "Based on the figures supplied in your question; the observation number preserves supplied order.",
    )


def _extract_multi_measure_rows(query: str) -> UserDataTable | None:
    segments: list[tuple[str, str]] = []
    for position, segment in enumerate(_ROW_BOUNDARY.split(query)):
        match = _ROW_SEGMENT.search(segment)
        if match is None:
            continue
        label = match.group(1)
        body = match.group(2)
        # The first clause often has an instruction prefix ("Compare regions:")
        # before the actual row label. Keep the label closest to the measures.
        if position == 0 and ":" in body:
            nested_label, body = body.rsplit(":", 1)
            label = nested_label.strip()
        segments.append((label, body))
    if len(segments) < 2:
        return None
    parsed: list[tuple[str, list[tuple[str, Decimal, str]]]] = []
    expected: tuple[str, ...] | None = None
    for label, body in segments:
        measures = [
            (_label(name), -_decimal(value) if sign == "-" else _decimal(value), "%" if percent else "")
            for name, sign, value, percent in _NAMED_MEASURE.findall(body)
        ]
        names = tuple(item[0] for item in measures)
        if len(measures) < 2 or (expected is not None and names != expected):
            return None
        expected = names
        parsed.append((_label(label), measures))
    assert expected is not None
    rows = tuple((label, *(value for _name, value, _unit in measures)) for label, measures in parsed)
    units = tuple(unit for _name, _value, unit in parsed[0][1])
    headers = ("Category",) + tuple(
        f"{name} (%)" if unit == "%" else name for name, (_old, _value, unit) in zip(expected, parsed[0][1])
    )
    return UserDataTable(
        "Multi-measure comparison", headers, rows,
        "Based on the figures supplied in your question; each supplied measure is preserved separately.",
    )


def _extract_semicolon_multi_measure_rows(query: str) -> UserDataTable | None:
    """Extract ``Entity measure n measure n; ...`` rows without requiring
    colons between each entity and its measures.

    The repeated, identical measure-name sequence is the structural guard:
    incomplete or inconsistent rows are rejected instead of being flattened
    into a misleading single-measure category table.
    """
    # Dedicated governed extractors add calculated variance/profit columns
    # for these shapes; never pre-empt those richer, validated results.
    if (
        re.search(r"\bbudget\b", query, re.I) and re.search(r"\bactual\b", query, re.I)
    ) or (
        _PERIOD_TOKEN.search(query) and re.search(r"\brevenue\b", query, re.I)
        and re.search(r"\bexpenses?\b", query, re.I)
    ):
        return None
    parsed: list[tuple[str, list[tuple[str, Decimal, str]]]] = []
    expected: tuple[str, ...] | None = None
    for raw_segment in query.split(";"):
        matches = list(_SIGNED_MEASURE_VALUE_PAIR.finditer(raw_segment))
        if len(matches) < 2:
            continue
        entity = raw_segment[:matches[0].start()].strip(" .,:")
        # The first segment may contain the instruction before its final
        # colon; only the text after that colon identifies the first entity.
        if ":" in entity:
            entity = entity.rsplit(":", 1)[1].strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 &/'-]{0,40}", entity):
            return None
        measures = [
            (
                _label(match.group(1)),
                -_decimal(match.group(3)) if match.group(2) == "-" else _decimal(match.group(3)),
                "%" if match.group(4) else "",
            )
            for match in matches
        ]
        names = tuple(item[0] for item in measures)
        if expected is not None and names != expected:
            return None
        expected = names
        parsed.append((_label(entity), measures))
    if len(parsed) < 2 or expected is None:
        return None
    units = tuple(unit for _name, _value, unit in parsed[0][1])
    if any(tuple(unit for _name, _value, unit in measures) != units for _entity, measures in parsed):
        return None
    headers = ("Category",) + tuple(
        f"{name} (%)" if unit == "%" else name for name, unit in zip(expected, units)
    )
    rows = tuple((entity, *(value for _name, value, _unit in measures)) for entity, measures in parsed)
    return UserDataTable(
        "Multi-measure comparison", headers, rows,
        "Based on the figures supplied in your question; each supplied measure is preserved separately.",
    )


def _extract_period_multi_measure_rows(query: str) -> UserDataTable | None:
    """"Q1 labor $40,000 materials $25,000 overhead $10,000, Q2 ..." — each
    period introduces several measures chained by spaces, not commas, so
    _extract_multi_measure_rows' colon-anchored row splitting never
    applies. Each period's segment is the text strictly between it and the
    next period token (or end of string), so a measure from one period can
    never bleed into another's row."""
    period_matches = list(_PERIOD_TOKEN.finditer(query))
    if len(period_matches) < 2:
        return None
    rows: list[tuple[str, ...]] = []
    expected: tuple[str, ...] | None = None
    for index, period_match in enumerate(period_matches):
        end = period_matches[index + 1].start() if index + 1 < len(period_matches) else len(query)
        segment = query[period_match.end():end]
        measures = _MEASURE_VALUE_PAIR.findall(segment)
        names = tuple(_label(name) for name, value in measures)
        if len(measures) < 2 or (expected is not None and names != expected):
            return None
        expected = names
        period_label = period_match.group(0).upper() if period_match.group(0).upper().startswith("Q") else period_match.group(0).title()
        rows.append((period_label, *(_decimal(value) for name, value in measures)))
    if len(rows) < 2 or expected is None:
        return None
    period_kind = "Quarterly" if all(str(row[0]).startswith("Q") for row in rows) else "Monthly"
    return UserDataTable(
        f"{period_kind} cost breakdown", ("Period",) + expected, tuple(rows),
        "Based on the figures supplied in your question; each supplied measure is preserved separately.",
    )


def _extract_positional_multi_measure(query: str) -> UserDataTable | None:
    """"...on <measure>, <measure>, and <measure>: <entity> n, n, n; ..." —
    see _MEASURE_LIST_INTRO/_ENTITY_NUMBER_LIST above. Every entity's
    number LIST must be exactly as long as the measure-name list, in the
    same order; any mismatch is treated as unparseable rather than
    guessed at, matching this module's "extract a complete dataset only"
    contract."""
    intro_match = _MEASURE_LIST_INTRO.search(query)
    if intro_match is None:
        return None
    measure_names = [
        _label(piece) for piece in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", intro_match.group(1).strip())
        if piece.strip()
    ]
    if len(measure_names) < 2:
        return None

    rows: list[tuple[str, ...]] = []
    percent_flags: list[bool] | None = None
    for segment in query[intro_match.end():].split(";"):
        entity_match = _ENTITY_NUMBER_LIST.search(segment)
        if entity_match is None:
            continue
        raw_values = [piece.strip() for piece in entity_match.group(2).split(",")]
        if len(raw_values) != len(measure_names):
            return None
        flags = [value.endswith("%") for value in raw_values]
        if percent_flags is None:
            percent_flags = flags
        elif flags != percent_flags:
            return None
        values = tuple(_decimal(value.rstrip("%")) for value in raw_values)
        rows.append((_label(entity_match.group(1)), *values))
    if len(rows) < 2:
        return None

    headers = ("Category",) + tuple(
        f"{name} (%)" if is_percent else name for name, is_percent in zip(measure_names, percent_flags or [])
    )
    return UserDataTable(
        "Multi-measure comparison", headers, tuple(rows),
        "Based on the figures supplied in your question; each supplied measure is preserved separately.",
    )


def _bridge_decimal(raw: str, suffix: str | None) -> Decimal:
    value = _decimal(raw)
    if suffix and suffix.lower() == "k":
        value *= 1000
    elif suffix and suffix.lower() == "m":
        value *= 1_000_000
    return value


def _extract_cash_bridge(query: str) -> UserDataTable | None:
    """Recognizes "Starting <balance> was N. <label> added N, <label>
    reduced it by N, ..." — a starting balance plus a narrative sequence
    of signed movements. The ending balance is always DERIVED as starting
    + every movement, never independently stated or invented — matching
    presentation_dataprofile.py's _reconciles_as_bridge requirement for a
    waterfall chart by construction, not by luck."""
    start_match = _STARTING_BALANCE.search(query)
    if start_match is None:
        return None
    start_label = _label(start_match.group(1))
    start_value = _bridge_decimal(start_match.group(2), start_match.group(3))

    movements: list[tuple[int, str, Decimal]] = []
    for match in _POSITIVE_MOVEMENT.finditer(query):
        if match.start() <= start_match.start():
            continue
        movements.append((match.start(), _label(match.group(1)), _bridge_decimal(match.group(2), match.group(3))))
    for match in _NEGATIVE_MOVEMENT.finditer(query):
        if match.start() <= start_match.start():
            continue
        movements.append((match.start(), _label(match.group(1)), -_bridge_decimal(match.group(2), match.group(3))))
    if len(movements) < 2:
        return None
    movements.sort(key=lambda item: item[0])

    ending_value = start_value + sum(value for _pos, _lbl, value in movements)
    rows = [(f"Starting {start_label}", start_value)]
    rows.extend((label, value) for _pos, label, value in movements)
    rows.append((f"Ending {start_label}", ending_value))
    return UserDataTable(
        f"{start_label} bridge", ("Step", "Amount"), tuple(rows),
        "The ending balance is calculated as the starting balance plus every movement supplied in the "
        "request — it is never independently stated or estimated.",
    )


# Real gap (2026-08-04): "fifteen thousand on ads, eight thousand on
# events, and twelve thousand on content" — spelled-out numbers — matched
# no pattern anywhere in this module; every extractor assumes digits.
# Rather than write a parallel spelled-out-number version of every
# extraction pattern, the query is normalized to digits ONCE, up front in
# extract_inline_dataset, and every existing digit-based pattern runs
# against that normalized copy unchanged. Only replaces a run of TWO OR
# MORE consecutive number-words ("fifteen thousand", "eighty-five") — a
# single bare word ("the one exception", "step six") is far too common in
# ordinary prose to safely treat as a figure, but two in a row essentially
# never occurs by coincidence.
_WORD_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_WORD_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_WORD_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_NUMBER_WORD = r"(?:" + "|".join(
    sorted(list(_WORD_ONES) + list(_WORD_TENS) + list(_WORD_SCALES), key=len, reverse=True)
) + r")"
_WORD_NUMBER_PHRASE = re.compile(rf"\b{_NUMBER_WORD}(?:[-\s]{_NUMBER_WORD})+\b", re.I)


def _words_to_decimal(phrase: str) -> Decimal:
    total = 0
    current = 0
    for token in re.split(r"[\s-]+", phrase.strip().lower()):
        if not token:
            continue
        if token in _WORD_ONES:
            current += _WORD_ONES[token]
        elif token in _WORD_TENS:
            current += _WORD_TENS[token]
        elif token == "hundred":
            current = (current or 1) * 100
        elif token in _WORD_SCALES:
            total += (current or 1) * _WORD_SCALES[token]
            current = 0
    return Decimal(total + current)


def _normalize_word_numbers(query: str) -> str:
    return _WORD_NUMBER_PHRASE.sub(lambda m: str(_words_to_decimal(m.group(0))), query)


def extract_inline_dataset(query: str) -> InlineDataset | None:
    """Extract a complete dataset only; never promote inferred or prior-turn data."""
    query = _normalize_word_numbers(query)
    if not _DATA_OPERATION.search(query) or requires_external_evidence(query):
        return None
    table = (
        _extract_scatter_pairs(query) or _extract_distribution(query) or _extract_multi_measure_rows(query)
        or _extract_semicolon_multi_measure_rows(query)
        or _extract_cash_bridge(query) or _extract_positional_multi_measure(query)
        # Tried only after extract_user_data_table's more specific shapes
        # (revenue/expenses/profit, budget/actual, ...) have already had a
        # chance — its generic "<word> <number>" pairing would otherwise
        # swallow "Q1 revenue $X and expenses $Y" itself and pre-empt the
        # dedicated profit-computing path below.
        or extract_user_data_table(query) or _extract_period_multi_measure_rows(query)
    )
    if table is None:
        return None
    temporal = None
    if table.headers and table.headers[0] == "Period":
        temporal = "quarter" if all(str(row[0]).startswith("Q") for row in table.rows) else "month"
    currency_match = re.search(r"[$£€]", query)
    currency = {"$": "USD", "£": "GBP", "€": "EUR"}.get(currency_match.group(0)) if currency_match else None
    units = tuple(
        "percent" if "%" in header
        # Real gap (2026-08-03): "Variance" (the 4th column of a budget-vs-
        # actual table) matched none of these words, so dataset.units for
        # it fell back to "" — compose_user_provided_results treats an
        # empty unit as "not a currency figure" and renders it as a bare
        # unformatted number ("8000") right next to Budget/Actual cells
        # correctly shown as "$150,000"/"$158,000". "labor"/"materials"/
        # "overhead" added 2026-08-04 for the same reason: a quarterly cost
        # breakdown's own measure names are cost categories, not one of
        # the words above, so their $-supplied figures rendered bare too.
        else (currency or "") if re.search(
            r"revenue|expense|amount|balance|budget|actual|profit|value|variance|"
            r"labor|materials|overhead|cost|price|salary|salaries|rent|payroll|spend|fee",
            header, re.I,
        )
        else ""
        for header in table.headers[1:]
    )
    return _inline(table, units=units, currency=currency, temporal_granularity=temporal)


_MAGNITUDE_SUFFIX = re.compile(r"^(-?\d[\d,]*(?:\.\d+)?)\s?([A-Za-z]+)?$")
_MAGNITUDE_MULTIPLIERS = {
    "k": Decimal("1e3"), "kn": Decimal("1e3"), "thousand": Decimal("1e3"),
    "m": Decimal("1e6"), "mn": Decimal("1e6"), "million": Decimal("1e6"),
    "b": Decimal("1e9"), "bn": Decimal("1e9"), "billion": Decimal("1e9"),
}


def _decimal(raw: str) -> Decimal:
    match = _MAGNITUDE_SUFFIX.fullmatch(raw.strip())
    if match and match.group(2):
        multiplier = _MAGNITUDE_MULTIPLIERS.get(match.group(2).lower())
        if multiplier is not None:
            return Decimal(match.group(1).replace(",", "")) * multiplier
    return Decimal(raw.replace(",", ""))


def _signed_decimal(open_paren: str, minus: str, digits: str, close_paren: str) -> Decimal:
    """Pairs with _SIGNED_NUMBER's four match groups. Negative when either
    a leading "-" was present, or the value was wrapped in accounting
    parentheses ("($X)") — open and close must both be present, not just
    one, so a stray unmatched paren elsewhere in the query can never flip
    the sign of an unrelated number."""
    value = _decimal(digits)
    if minus or (open_paren and close_paren):
        value = -value
    return value


def _label(raw: str) -> str:
    value = re.sub(r"^and\s+", "", raw.strip(), flags=re.I)
    return " ".join(value.split()).title()


def extract_user_data_table(query: str) -> UserDataTable | None:
    """Recognise supported multi-value datasets without guessing any value."""
    ratio = _RATIO_BENCHMARK.search(query)
    if ratio:
        actual, benchmark = _decimal(ratio.group(2)), _decimal(ratio.group(3))
        return UserDataTable(
            f"{_label(ratio.group(1))} benchmark comparison",
            ("Measure", "Actual", "Benchmark", "Difference"),
            (("Ratio", actual, benchmark, actual - benchmark),),
            "Difference is actual minus benchmark; the benchmark is comparative context, not a universal pass/fail threshold.",
        )

    revenue_margin_rows = tuple(
        (period.upper() if period.upper().startswith("Q") else period.title(), _decimal(revenue), _decimal(margin))
        for period, revenue, margin in _PERIOD_REVENUE_MARGIN.findall(query)
    )
    if len(revenue_margin_rows) >= 2:
        return UserDataTable(
            "Quarterly revenue and gross margin", ("Period", "Revenue", "Gross margin (%)"),
            revenue_margin_rows, "Revenue and gross-margin percentages are the values supplied in the request.",
        )

    aging_rows = tuple((_label(bucket), _decimal(value)) for bucket, value in _AGING_BUCKET.findall(query))
    if len(aging_rows) >= 2:
        return UserDataTable(
            "Accounts-receivable aging", ("Aging bucket", "Receivable balance"), aging_rows,
            "These are the aging-bucket balances supplied in the request; they do not by themselves determine collectibility.",
        )
    period_rows = []
    for period, revenue, expenses in _PERIOD_RESULTS.findall(query):
        revenue_value, expense_value = _decimal(revenue), _decimal(expenses)
        period_rows.append((period.upper() if period.upper().startswith("Q") else period.title(), revenue_value, expense_value, revenue_value - expense_value))
    if period_rows:
        period_kind = "Quarterly" if all(str(row[0]).startswith("Q") for row in period_rows) else "Monthly"
        return UserDataTable(f"{period_kind} revenue, expenses, and profit", ("Period", "Revenue", "Expenses", "Profit"), tuple(period_rows), "Profit is calculated deterministically as revenue minus expenses for each period.")

    single_period_rows = tuple(
        (period.upper() if period.upper().startswith("Q") else period.title(), _signed_decimal(open_p, minus, value, close_p))
        for period, open_p, minus, value, close_p in _PERIOD_VALUE.findall(query)
    )
    if len(single_period_rows) >= 2:
        metric_match = re.search(r"\b(revenue|expenses?|accounts?[ -]receivable|cash|profit|sales|tax(?: expense)?)\b", query, re.I)
        metric = _label(metric_match.group(1)) if metric_match else "Amount"
        period_kind = "Quarterly" if all(str(row[0]).startswith("Q") for row in single_period_rows) else "Monthly"
        return UserDataTable(f"{period_kind} {metric.lower()} trend", ("Period", metric), single_period_rows, "These are the period amounts supplied in the request.")

    budget_rows = []
    for category, budget, actual in _BUDGET_ACTUAL.findall(query):
        budget_value, actual_value = _decimal(budget), _decimal(actual)
        budget_rows.append((_label(category), budget_value, actual_value, actual_value - budget_value))
    if not budget_rows and re.search(r"\bbudget\b", query, re.I) and re.search(r"\bactual\b", query, re.I):
        for category, budget, actual in _VERSUS_PAIR.findall(query):
            budget_value, actual_value = _decimal(budget), _decimal(actual)
            budget_rows.append((_label(category), budget_value, actual_value, actual_value - budget_value))
    if budget_rows:
        return UserDataTable("Budget versus actual expenses", ("Category", "Budget", "Actual", "Variance"), tuple(budget_rows), "Variance is actual minus budget; a positive value is over budget.")

    versus_rows = tuple(
        (_label(category), _decimal(first), _decimal(second))
        for category, first, second in _VERSUS_PAIR.findall(query)
    )
    if len(versus_rows) >= 2:
        header_hint = _VERSUS_HEADER_HINT.search(query)
        first_header = _label(header_hint.group(1)) if header_hint else "Value 1"
        second_header = _label(header_hint.group(2)) if header_hint else "Value 2"
        return UserDataTable(
            f"{first_header} versus {second_header} comparison",
            ("Category", first_header, second_header), versus_rows,
            "These are the figures supplied in the request.",
        )

    balance_rows = tuple((_label(name), _decimal(value)) for name, value in _BALANCE.findall(query))
    if len(balance_rows) >= 2:
        return UserDataTable("Balance comparison", ("Account", "Balance"), balance_rows, "These are the balances supplied in the request.")

    category_rows = tuple(
        (_label(name), _signed_decimal(open_p, minus, value, close_p))
        for name, open_p, minus, value, close_p in _CATEGORY_VALUE.findall(query)
    )
    value_first_rows = tuple((_label(name), _decimal(value)) for value, name in _VALUE_FIRST_CATEGORY.findall(query))
    # Prefer whichever shape captured more of the query's figures — a loose
    # "Label Number" match can pick up filler words ("We had", "and") as
    # spurious single-figure categories when the sentence is actually in the
    # number-first funnel/count convention, undercounting the real dataset.
    if len(value_first_rows) > len(category_rows) and len(value_first_rows) >= 2:
        return UserDataTable("Category comparison", ("Category", "Amount"), value_first_rows, "These are the amounts supplied in the request.")
    if len(category_rows) >= 2:
        return UserDataTable("Category comparison", ("Category", "Amount"), category_rows, "These are the amounts supplied in the request.")
    return None


def extract_quarterly_results(query: str) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    table = extract_user_data_table(query)
    if table is None or not table.title.startswith("Quarterly"):
        return []
    return [tuple(row) for row in table.rows]  # type: ignore[list-item]


def _money(value: Decimal) -> str:
    absolute = abs(value)
    formatted = f"${absolute:,.2f}" if absolute % 1 else f"${absolute:,.0f}"
    return f"-{formatted}" if value < 0 else formatted


def _plain_amount(value: Decimal) -> str:
    absolute = abs(value)
    formatted = f"{absolute:,.2f}" if absolute % 1 else f"{absolute:,.0f}"
    return f"-{formatted}" if value < 0 else formatted


def _amount(value: Decimal, is_currency: bool) -> str:
    """Real gap (2026-08-03): _professional_analysis always called _money()
    unconditionally, so a non-currency count dataset (e.g. "12,000
    visitors, 5,200 sign-ups...", with no $/£/€ anywhere in the query) got
    its "Key insight"/"Executive summary" narrative wrongly labeled with a
    dollar sign the table cells themselves never used — comma-grouped, but
    never claiming a currency the data never had."""
    return _money(value) if is_currency else _plain_amount(value)


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'))}%"


def _professional_analysis(table: UserDataTable, ref: str | None = None, is_currency: bool = True, query: str = "") -> list[str]:
    """Return accounting-focused insights calculated only from table values."""
    cite = f" [{ref}]" if ref else ""
    rows = table.rows
    if table.headers == ("Period", "Revenue", "Expenses", "Profit"):
        total_revenue = sum((row[1] for row in rows), Decimal(0))
        total_expenses = sum((row[2] for row in rows), Decimal(0))
        total_profit = sum((row[3] for row in rows), Decimal(0))
        overall_margin = total_profit / total_revenue * 100 if total_revenue else Decimal(0)
        first_profit, last_profit = rows[0][3], rows[-1][3]
        profit_change = (last_profit - first_profit) / abs(first_profit) * 100 if first_profit else None
        first_margin = first_profit / rows[0][1] * 100 if rows[0][1] else Decimal(0)
        last_margin = last_profit / rows[-1][1] * 100 if rows[-1][1] else Decimal(0)
        direction = "increased" if last_profit >= first_profit else "decreased"
        change_display = _percent(abs(profit_change)) if profit_change is not None else ""
        article = "an" if re.match(r"^(?:8|11|18)", change_display) else "a"
        headline = (
            f"**Key insight:** Profit {direction} from {_money(first_profit)} in {rows[0][0]} "
            f"to {_money(last_profit)} in {rows[-1][0]}"
            + (f", {article} {change_display} change" if profit_change is not None else "")
            + f".{cite}"
        )
        return [
            headline,
            f"- **Total revenue:** {_money(total_revenue)}{cite}",
            f"- **Total expenses:** {_money(total_expenses)}{cite}",
            f"- **Total profit:** {_money(total_profit)}{cite}",
            f"- **Overall profit margin:** {_percent(overall_margin)}{cite}",
            f"- **Margin movement:** {_percent(first_margin)} in {rows[0][0]} to {_percent(last_margin)} in {rows[-1][0]}.{cite}",
        ]
    if table.headers == ("Category", "Budget", "Actual", "Variance"):
        total_budget = sum((row[1] for row in rows), Decimal(0))
        total_actual = sum((row[2] for row in rows), Decimal(0))
        net_variance = total_actual - total_budget
        largest = max(rows, key=lambda row: abs(row[3]))
        status = "over" if net_variance > 0 else "under" if net_variance < 0 else "on"
        return [
            f"**Key insight:** Overall spending is {_money(abs(net_variance))} {status} budget.{cite}",
            f"- **Total budget:** {_money(total_budget)}{cite}",
            f"- **Total actual:** {_money(total_actual)}{cite}",
            f"- **Largest category variance:** {largest[0]} at {_money(largest[3])}.{cite}",
        ]
    if table.headers in {("Account", "Balance"), ("Category", "Amount")} or (table.headers and table.headers[0] == "Period" and len(table.headers) == 2):
        total = sum((row[1] for row in rows), Decimal(0))
        largest = max(rows, key=lambda row: abs(row[1]))
        if table.headers[0] == "Period" and re.search(r"\b(?:largest|biggest)\s+change\b", query, re.I) and len(rows) >= 2:
            previous, current = max(zip(rows, rows[1:]), key=lambda pair: abs(pair[1][1] - pair[0][1]))
            change = current[1] - previous[1]
            direction = "increase" if change >= 0 else "decrease"
            return [
                f"**Key insight:** The largest period-to-period change is the {_amount(abs(change), is_currency)} {direction} from {previous[0]} to {current[0]}.{cite}",
                f"- **Latest value:** {_amount(rows[-1][1], is_currency)} in {rows[-1][0]}{cite}",
            ]
        if any(row[1] < 0 for row in rows):
            return [
                f"**Key insight:** {largest[0]} has the largest absolute value at {_amount(largest[1], is_currency)}.{cite}",
                f"- **Displayed net total:** {_amount(total, is_currency)}{cite}",
            ]
        share = largest[1] / total * 100 if total else Decimal(0)
        return [
            f"**Key insight:** {largest[0]} is the largest item at {_amount(largest[1], is_currency)}, representing {_percent(share)} of the displayed total.{cite}",
            f"- **Displayed total:** {_amount(total, is_currency)}{cite}",
        ]
    return []


def compose_user_provided_results(query: str, ref: str) -> str | None:
    dataset = extract_inline_dataset(query)
    if dataset is None:
        return None
    table = dataset.as_table()
    analysis = _professional_analysis(table, ref, is_currency=dataset.currency is not None, query=query)
    lines = [f"## {table.title}", "", "Based on the figures supplied in your question. These figures have not been independently verified.", ""]
    if analysis:
        lines.extend([analysis[0], "", "### Executive summary", "", *analysis[1:], ""])
    lines.extend([table.explanation, "", "| " + " | ".join(table.headers) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(table.headers))) + "|"])
    for row in table.rows:
        cells = [str(row[0])]
        for column, value in enumerate(row[1:], 1):
            if not isinstance(value, Decimal):
                cells.append(str(value))
            elif "%" in table.headers[column]:
                cells.append(f"{_percent(value)} [{ref}]")
            elif table.title.endswith("benchmark comparison"):
                cells.append(f"{value.normalize()} [{ref}]")
            elif dataset.units[column - 1] == "":
                cells.append(f"{format(value, 'f')} [{ref}]")
            else:
                cells.append(f"{_money(value)} [{ref}]")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def compose_quarterly_results(query: str, ref: str) -> str | None:
    """Compatibility alias; now supports all reviewed user-data layouts."""
    return compose_user_provided_results(query, ref)


def to_user_provided_data_rag_chunk(query: str) -> dict:
    dataset = extract_inline_dataset(query)
    table = dataset.as_table() if dataset is not None else None
    verified = ""
    if table is not None:
        if table.headers == ("Period", "Revenue", "Expenses", "Profit"):
            verified = "\n".join(
                f"Verified arithmetic for {row[0]}: {_money(row[1])} - {_money(row[2])} = {_money(row[3])}."
                for row in table.rows
            )
        elif table.headers == ("Category", "Budget", "Actual", "Variance"):
            verified = "\n".join(
                f"Verified arithmetic for {row[0]}: {_money(row[2])} - {_money(row[1])} = {_money(row[3])}."
                for row in table.rows
            )
        else:
            is_currency = dataset.currency is not None if dataset is not None else True
            verified = "\n".join("Verified row: " + ", ".join(str(value) if not isinstance(value, Decimal) else _amount(value, is_currency) for value in row) for row in table.rows)
        analysis = _professional_analysis(table, is_currency=dataset.currency is not None if dataset is not None else True)
        if analysis:
            verified += "\n\nVerified derived summary:\n" + "\n".join(analysis)
    return {
        "text": "User-provided data for the current request. Treat only the values explicitly written below as inputs; do not add or infer missing values.\n\n" + query + "\n\n" + verified,
        "metadata": {"source_id": USER_PROVIDED_DATA_GOVERNED_SOURCE_ID, "title": "Data supplied by the user in this request", "version": "current-request", "jurisdiction": "GLOBAL", "mandatory_source": True, "provenance": "user_supplied_current_turn", "externally_verified": False},
        "score": 1.0,
        "node_id": f"{USER_PROVIDED_DATA_NODE_PREFIX}current",
    }
