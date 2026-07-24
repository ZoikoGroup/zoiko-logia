"""
Format-intent gate — detects when the user explicitly asked for a specific
response format (chart, table, flowchart) rather than leaving Markdown
structure to the model's own "scale to content" judgment (see
orchestration/service.py's grounded_input).

Same exemplar-similarity technique validated throughout this session for
intent/context classification, reused here for a much lower-stakes
decision: a false positive just means an unrequested table appears, not a
safety gap — so this is a good fit for the technique's actual strengths
(paraphrase-robust, ~40ms, no external dependency) without the caveats
that apply to safety-relevant decisions (see risk_classifier.py's
_semantic_evasion_match, which is NOT built this way for exactly that
reason — it needs to be independently gated, not competing in an argmax).

Deliberately distinct from that evasion gate in one more way: this picks a
winner via argmax (there IS a legitimate "no explicit format request" case
to fall into), where the evasion gate is a standalone yes/no threshold
with no competing category — the right shape depends on whether "none of
the above" is itself a valid, common outcome (it is, here) or not.
"""
from __future__ import annotations

from typing import Literal, Optional

FormatIntent = Literal["CHART", "TABLE", "FLOWCHART"]

_FORMAT_EXEMPLARS: dict[FormatIntent, tuple[str, ...]] = {
    "CHART": (
        "show me a chart of this",
        "plot this data",
        "visualize this as a graph",
        "draw a trend line for this",
        "can you chart this trend",
    ),
    "TABLE": (
        "put this in a table",
        "show this side by side in a table",
        "compare these in a table",
        "give me this as a table",
    ),
    "FLOWCHART": (
        "show me a flowchart of this process",
        "draw a decision tree for this",
        "diagram the steps for this",
        "show me the decision process visually",
    ),
}
# A query must clear this floor against its own best-matching category
# AND beat "no explicit request" by a margin — otherwise content that's
# merely comparable (e.g. "Compare IFRS and GAAP") would misfire as a
# table request just for using the word "compare" (confirmed distinct in
# testing: that exact query scored higher on a NONE-style baseline than on
# TABLE once no explicit ask was present).
_MIN_SCORE = 0.45

_format_exemplar_embeddings: dict[FormatIntent, list[list[float]]] = {}


def _get_format_exemplar_embeddings() -> dict[FormatIntent, list[list[float]]]:
    global _format_exemplar_embeddings
    if not _format_exemplar_embeddings:
        from app.domains.rag.embeddings import get_query_embedding_cached
        _format_exemplar_embeddings = {
            fmt: [list(get_query_embedding_cached(ex)) for ex in exemplars]
            for fmt, exemplars in _FORMAT_EXEMPLARS.items()
        }
    return _format_exemplar_embeddings


def _cosine_similarity(v1, v2) -> float:
    import math
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(a * a for a in v2))
    return dot / (mag1 * mag2) if mag1 and mag2 else 0.0


def detect_format_intent(query: str) -> Optional[FormatIntent]:
    """None means no explicit format request was detected — the caller
    should fall back to the default 'use structure only if content
    warrants it' instruction, not force anything."""
    try:
        from app.domains.rag.embeddings import get_query_embedding_cached
        q_emb = get_query_embedding_cached(query)
        exemplar_embs = _get_format_exemplar_embeddings()
        scores = {
            fmt: max(_cosine_similarity(q_emb, e) for e in embs)
            for fmt, embs in exemplar_embs.items()
        }
        best_fmt, best_score = max(scores.items(), key=lambda kv: kv[1])
        return best_fmt if best_score >= _MIN_SCORE else None
    except Exception:
        # Same fail-safe convention as every other semantic check in this
        # codebase — an embedding-model outage degrades to "no explicit
        # format detected," never to forcing (or blocking) anything.
        return None


_FORMAT_DATA_REQUIREMENT: dict[FormatIntent, str] = {
    "CHART": "multi-point numeric data",
    "TABLE": "comparable items or values",
    "FLOWCHART": "decision logic or process steps",
}


# Regression guard: a real failure observed this session — a comparison
# table came back with cells containing the bare "[REF-4]" marker with no
# actual value, and "N/A" in cells where the retrieved context in fact had
# a real figure. A [REF-N] marker is a citation *for* a value, never a
# substitute for one — the model has to write the actual number/fact AND
# its marker together in the same cell, and only fall back to stating
# absence when the value genuinely isn't in the retrieved context.
_TABLE_CELL_CONTENT_RULE = (
    "Every table cell must contain the actual value or fact from the retrieved "
    "context, with its [REF-N] marker attached after it (e.g. '$632 [REF-4]') — "
    "never a bare [REF-N] marker alone as a stand-in for a value, and never "
    "'N/A' unless the retrieved context genuinely contains no figure for that "
    "cell after checking carefully."
)

# Regression guard: a second real failure observed this session, worse than
# the table one above — asked for a flowchart with no relevant context, the
# model correctly said the context didn't cover it, then explicitly OFFERED
# and delivered a second, fabricated flowchart "based on general knowledge"
# anyway. Saying the right thing first doesn't satisfy the no-fabrication
# rule if the model backslides into general knowledge one paragraph later —
# this has to close off the "offer an alternative anyway" escape hatch by
# name, not just repeat "don't invent data."
_NO_FABRICATION_FALLBACK_RULE = (
    "If the retrieved context does not cover the query, state that plainly and "
    "STOP — do not then offer, suggest, or provide a second version 'based on "
    "general knowledge' or a 'generic example' as a fallback. Saying the context "
    "doesn't cover it, and then answering from general knowledge anyway one "
    "paragraph later, is exactly the outcome this rule forbids."
)

# Mermaid syntax guard — three real failures observed this session:
# 1. The model used multi-word, space-containing text ("Step 1", "Step 2")
#    as bare node IDs instead of wrapping them in a label bracket, which
#    Mermaid's grammar rejects outright (a bare identifier cannot contain
#    a space).
# 2. The model wrote a labeled edge with no target node (e.g. 'A -->|End|'
#    ending the line right there) to mean "this is a terminal/end state" —
#    invalid grammar; confirmed by reproducing the exact same parse error
#    message the model's own output produced, character for character,
#    against the real mermaid parser (not guessed at). A '-->|Label|' edge
#    always requires a real target node id immediately after the closing
#    pipe, in the same statement.
# 3. On a query that never asked for a flowchart at all, the model wrote
#    bracket/node-style text ("Step1[User submits information]: ...") as
#    plain prose, never inside a ```mermaid``` fence — confirmed live: it
#    was literally copying the illustrative example string from THIS
#    instruction's own text into an unrelated answer about invoice
#    verification, because "a process with steps" was thematically close
#    enough to get parroted. Two fixes: an abstract, unparrotable example
#    (no real-sounding content), and an explicit rule that this syntax may
#    only appear inside a real fenced block, never as bare prose.
_MERMAID_SYNTAX_RULE = (
    "The bracket/arrow node syntax below (e.g. 'A[label]', '-->') may ONLY "
    "appear inside an actual ```mermaid``` fenced code block — never as plain "
    "prose text, even when describing a step-by-step process. If you are not "
    "including a ```mermaid``` block, describe steps as an ordinary numbered "
    "Markdown list ('1. Do X', '2. Do Y'), never with bracket/arrow syntax. "
    "Inside a real ```mermaid``` block: node IDs must be short single tokens "
    "with no spaces (e.g. A, B, N1) — never a multi-word phrase as a bare ID. "
    "Always put the human-readable text inside the label brackets instead, "
    "e.g. 'N1[<replace with this step's own description>]', never 'Step 1[...]' "
    "or a bare 'Step 1 --> Step 2'. Every edge arrow (even a labeled one like -->|Yes|) "
    "MUST end at a real target node with its own ID and label, e.g. "
    "'A -->|Yes| B[<this branch's actual outcome, from the context>]' — never end "
    "a line right after an edge label with no target (e.g. never write 'A -->|End|' "
    "with nothing after it). To represent an ending/terminal state, give it a real "
    "node with a label describing that actual ending, drawn from the context."
)


def build_format_instruction(query: str) -> str:
    """The instruction fragment to splice into grounded_input — forced
    when the user explicitly asked for a format, the existing default
    otherwise. Called once per request; safe to call even when the
    embedding model is unavailable (detect_format_intent fails closed)."""
    detected = detect_format_intent(query)
    if detected is None:
        return (
            "Use a Markdown table only for a genuine side-by-side comparison, a "
            "```kriton-chart``` block only for real multi-point numeric data in the "
            "context, and a ```mermaid``` block only for real decision logic or "
            "process steps in the context — omit all three otherwise. "
            f"{_TABLE_CELL_CONTENT_RULE} {_MERMAID_SYNTAX_RULE} {_NO_FABRICATION_FALLBACK_RULE}"
        )
    table_note = f" {_TABLE_CELL_CONTENT_RULE}" if detected == "TABLE" else ""
    mermaid_note = f" {_MERMAID_SYNTAX_RULE}" if detected == "FLOWCHART" else ""
    return (
        f"The user explicitly asked for a {detected.lower()}. If the retrieved "
        f"context contains genuine {_FORMAT_DATA_REQUIREMENT[detected]}, represent "
        f"it that way ({'a ```kriton-chart``` block' if detected == 'CHART' else 'a Markdown table' if detected == 'TABLE' else 'a ```mermaid``` block'}). "
        f"If it does not, say so directly — never invent data or structure to "
        f"satisfy the request.{table_note}{mermaid_note} {_NO_FABRICATION_FALLBACK_RULE}"
    )
