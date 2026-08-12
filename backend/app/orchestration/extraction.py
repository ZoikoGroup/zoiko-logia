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
    return extract_relation_clauses(query) or extract_arrow_statements(query) or extract_arrow_chain(query)
