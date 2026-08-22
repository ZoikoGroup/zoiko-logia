"""
Deterministic extraction of entities/relationships/stages from the USER'S OWN
query text — never from retrieved sources or LLM output. This is the only
data source EVIDENCE_GRAPH (visualization/orchestrator.py) and PROCESS_FLOW
back today: there is no independent entity/relationship-extraction pipeline
over arbitrary text in this codebase, so a graph/flow visual only appears
when the user states the structure themselves, matching the spec's own
example prompt: "visualize every SUPPLIED entity and relationship." Anything
not explicitly present in the query is never invented (ZL-T0-04 data-honesty).

Two independent signals, either of which can win:
  1. An arrow chain — "A -> B -> C" / "A --> B --> C" / "A → B → C" — the
     most syntactically unambiguous signal; also doubles as a stage sequence
     for PROCESS intent (data_shape.py picks DIRECTED_STAGES vs NODES_EDGES
     based on intent, not on how the text was structured).
  2. Relation clauses — "A owns B", "B invoices C" — a fixed, small verb
     vocabulary chosen to avoid false positives on ordinary prose; entities
     must start with a capital letter (a reasonable heuristic for named
     entities: companies, people, document titles).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.intent_classifier import COMPOSITION, DISTRIBUTION

_MAX_LABEL_LEN = 60
_MAX_NODES = 40  # sanity cap — a query listing more than this is almost
                  # certainly a parsing false-positive, not a real graph.


@dataclass
class ExtractedEdge:
    source: str
    target: str
    type: str = "related_to"


@dataclass
class ExtractedGraph:
    nodes: list[str] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)


_ARROW_SPLIT = re.compile(r"\s*(?:-->|->|→)\s*")
# Label character class includes "-" (real identifiers are routinely
# hyphenated: "Invoice-2024", "Sign-off", "Journal-Entry-88") — safe to
# include alongside the arrow tokens themselves (-->, ->) because Python's
# backtracking engine still resolves "Step-1 -> Step-2" correctly: the
# non-greedy label match only extends past "Step" to "Step-1" once trying to
# match the mandatory following arrow fails at the "-1" position (a bare
# hyphen followed by a digit is never a valid "->" start).
_LABEL_CHARS = r"[\w&/ -]"
# A chain needs at least one arrow between plausible short labels — this
# guards against splitting on a stray "->" inside unrelated text (e.g. code).
# The trailing lookahead accepts the same sentence-enders (.!?) the leading
# boundary already does — "...Onboard?" is as valid a chain terminator as
# "...Onboard." is; only the character class differed before, not the intent.
_ARROW_CHAIN = re.compile(
    r"(?:^|[:\n]|(?<=[.!?])\s)\s*([A-Za-z]%s{0,%d}?(?:\s*(?:-->|->|→)\s*[A-Za-z]%s{0,%d}?){1,%d})(?=[.!?\n]|$)"
    % (_LABEL_CHARS, _MAX_LABEL_LEN, _LABEL_CHARS, _MAX_LABEL_LEN, _MAX_NODES),
)


def extract_arrow_chain(query: str) -> ExtractedGraph | None:
    """Finds the first "A -> B -> C" style chain in the query. Returns None
    if none is present — never guesses at implicit ordering."""
    q = query or ""
    match = _ARROW_CHAIN.search(q)
    if not match:
        return None
    parts = [p.strip() for p in _ARROW_SPLIT.split(match.group(1)) if p.strip()]
    if len(parts) < 2:
        return None
    nodes: list[str] = []
    seen = set()
    for p in parts:
        if p not in seen:
            nodes.append(p)
            seen.add(p)
    edges = [ExtractedEdge(source=parts[i], target=parts[i + 1], type="next") for i in range(len(parts) - 1)]
    return ExtractedGraph(nodes=nodes, edges=edges)


def extract_arrow_statements(query: str) -> ExtractedGraph | None:
    """Merge semicolon/newline-separated arrow statements such as
    ``A -> B; B -> C`` without inferring any unstated edge."""
    nodes: list[str] = []
    seen: set[str] = set()
    edges: list[ExtractedEdge] = []
    for statement in re.split(r"[;\n]+", query or "")[:_MAX_NODES]:
        graph = extract_arrow_chain(statement.strip())
        if graph is None:
            continue
        for node in graph.nodes:
            if node not in seen:
                nodes.append(node)
                seen.add(node)
        edges.extend(graph.edges)
    return ExtractedGraph(nodes=nodes, edges=edges[:_MAX_NODES]) if len(nodes) >= 2 and edges else None


_STAGE_LIST_HINT = re.compile(
    r"\b(?:flowchart|flow diagram|process flow|process diagram|workflow|"
    r"mermaid (?:flowchart|flow|diagram)|x6 (?:workflow|flow|diagram))\b",
    re.I,
)


def extract_stage_list(query: str) -> ExtractedGraph | None:
    """Extract stages only from an explicit comma-separated flow request."""
    q = query or ""
    if not _STAGE_LIST_HINT.search(q) or ":" not in q:
        return None
    tail = q.rsplit(":", 1)[1].strip().rstrip(".!?")
    parts = [part.strip() for part in tail.split(",") if part.strip()]
    if not 2 <= len(parts) <= _MAX_NODES:
        return None
    if any(len(part) > _MAX_LABEL_LEN or not re.search(r"[A-Za-z0-9]", part) for part in parts):
        return None
    nodes = list(dict.fromkeys(parts))
    if len(nodes) < 2:
        return None
    edges = [ExtractedEdge(source=parts[i], target=parts[i + 1], type="next") for i in range(len(parts) - 1)]
    return ExtractedGraph(nodes=nodes, edges=edges)


# Fixed, small vocabulary — chosen to avoid firing on ordinary prose that
# happens to contain a common verb ("owns" also means something in casual
# text; requiring a capitalised entity on both sides keeps false positives
# low without needing real NLP). Longer phrases MUST come before shorter
# ones that are their own prefix ("is audited by" before "audits" would be
# fine either way here since neither prefixes the other, but "is owned by"
# vs "is a subsidiary of" etc. — kept in a readable, non-prefix-colliding
# order deliberately).
_RELATION_VERBS = (
    "owns", "controls", "invoices", "pays", "supplies", "audits", "manages",
    "employs", "guarantees", "borrows from", "lends to", "depends on",
    "reports to", "is a subsidiary of", "is owned by", "contracts with", "licenses to",
    "supports", "is audited by", "is supported by", "is controlled by",
    "reviews", "is reviewed by",
)
# Entity character class includes "-" — real identifiers are routinely
# hyphenated ("Invoice-2024", "Auditor-Team-A", "Journal-Entry-88"); see
# _LABEL_CHARS' docstring above for why this doesn't create arrow-matching
# ambiguity (not applicable here — this pattern has no arrow tokens — but
# the same backtracking safety applies to word-boundary matching against
# the verb alternation below).
_ENTITY_CHARS = r"[\w&-]"
_RELATION_CLAUSE = re.compile(
    r"\b([A-Z]%s{0,%d}(?:\s+[A-Z]%s{0,%d}){0,3})\s+(%s)\s+"
    r"([A-Z]%s{0,%d}(?:\s+[A-Z]%s{0,%d}){0,3})\b"
    % (
        _ENTITY_CHARS, _MAX_LABEL_LEN, _ENTITY_CHARS, _MAX_LABEL_LEN,
        "|".join(re.escape(v) for v in _RELATION_VERBS),
        _ENTITY_CHARS, _MAX_LABEL_LEN, _ENTITY_CHARS, _MAX_LABEL_LEN,
    ),
)


def extract_relation_clauses(query: str) -> ExtractedGraph | None:
    """Finds "A <relation-verb> B" clauses using a fixed verb vocabulary.
    Returns None if none matched — never infers a relationship type that
    wasn't stated."""
    q = query or ""
    matches = list(_RELATION_CLAUSE.finditer(q))
    if not matches:
        return None
    nodes: list[str] = []
    seen = set()
    edges: list[ExtractedEdge] = []
    for m in matches[:_MAX_NODES]:
        a, verb, b = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        for n in (a, b):
            if n not in seen:
                nodes.append(n)
                seen.add(n)
        edges.append(ExtractedEdge(source=a, target=b, type=verb.replace(" ", "_")))
    return ExtractedGraph(nodes=nodes, edges=edges)


def extract_graph(query: str) -> ExtractedGraph | None:
    """Relation clauses take priority — they carry a real relationship type,
    which is strictly more informative than an arrow chain's generic "next"/
    "related_to". Falls back to an arrow chain when no typed clause is found."""
    return (
        extract_relation_clauses(query)
        or extract_arrow_statements(query)
        or extract_arrow_chain(query)
        or extract_stage_list(query)
    )


# User-authored chart data is trusted only as quoted input, never inferred
# from model prose. Requiring an explicit supported visual intent plus a
# colon-delimited payload keeps ordinary questions containing numbers from
# being silently reinterpreted as datasets.
_PERCENT_PAIR = re.compile(
    r"(?:^|[,;])\s*([A-Za-z][\w &/().'’-]{0,59}?)\s*(?::|=)?\s*"
    r"(-?\d+(?:\.\d+)?)\s*%",
)
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\w)")
_UNIT_HINT = re.compile(
    r"\b(days?|hours?|minutes?|seconds?|weeks?|months?|years?|percent(?:age)?|%)\b",
    re.I,
)
_MAX_USER_POINTS = 500


def _payload_after_colon(query: str) -> tuple[str, str] | None:
    prefix, separator, payload = (query or "").partition(":")
    if not separator or not payload.strip():
        return None
    return prefix.strip(), payload.strip()


def extract_user_visual_evidence(query: str, intent: str) -> EvidenceModel:
    """Extract explicitly supplied chart values from the user's query.

    Supported general shapes are labelled percentages for composition charts
    and an unlabelled numeric sample for distributions. Invalid/ambiguous
    input returns empty evidence so the established text fallback remains in
    control.
    """
    split = _payload_after_colon(query)
    if split is None:
        return EvidenceModel()
    prefix, payload = split

    if intent == COMPOSITION:
        pairs = [
            (re.sub(r"^and\s+", "", m.group(1).strip(), flags=re.I), float(m.group(2)))
            for m in _PERCENT_PAIR.finditer(payload)
        ]
        if not 2 <= len(pairs) <= _MAX_USER_POINTS:
            return EvidenceModel()
        labels = [label.casefold() for label, _ in pairs]
        values = [value for _, value in pairs]
        if len(labels) != len(set(labels)) or any(value < 0 for value in values):
            return EvidenceModel()
        if sum(values) > 100.5:
            return EvidenceModel()
        return EvidenceModel(
            subject="Ownership composition" if "ownership" in prefix.casefold() else "Composition",
            composition_subject="Ownership composition" if "ownership" in prefix.casefold() else "Composition",
            composition=[
                Observation(dimension=label, value=value, measure="percent")
                for label, value in pairs
            ],
            composition_caveat="Percentages supplied directly by the user.",
            composition_is_estimated=False,
            dimensions=["category"],
            measures=["percent"],
            units=["%"],
        )

    if intent == DISTRIBUTION:
        # Percent-pair input belongs to composition, not a numeric sample.
        if "%" in payload:
            return EvidenceModel()
        values = [float(match.group(0)) for match in _NUMBER.finditer(payload)]
        if not 8 <= len(values) <= _MAX_USER_POINTS:
            return EvidenceModel()
        unit_match = _UNIT_HINT.search(prefix)
        unit = unit_match.group(1).lower() if unit_match else None
        subject = re.sub(
            r"\b(create|make|show|plot|draw|a|an|the|histogram|distribution|for|of|these|this)\b",
            " ", prefix, flags=re.I,
        )
        subject = re.sub(r"\s+", " ", subject).strip(" -") or "supplied values"
        return EvidenceModel(
            subject=subject,
            observations=[
                Observation(dimension=str(index), value=value, measure=subject)
                for index, value in enumerate(values, start=1)
            ],
            dimensions=["observation"],
            measures=[subject],
            units=[unit] if unit else [],
        )

    return EvidenceModel()
