"""Schema-constrained LLM fallback for ambiguous presentation-guide classification.

Deterministic regex rules in presentation.py remain the sole authority for
confident cases (ZL-ENG-02 §12 presentation contract) — this module only runs
when a query clearly wants some kind of process/workflow visual but no
specific-type rule fired. It NEVER generates diagram content: the numbered
steps it classifies are already extracted deterministically from validated,
Checkpoint-C-passed answer text (see presentation.py's module docstring), and
this classifier only chooses which of the pre-approved PresentationGuide
layouts (or none) best fits them. guide_type is constrained to a closed JSON
schema enum, so the model has no channel to inject markup, code, or new
facts — it can only pick a word from a fixed list.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


_ALLOWED_GUIDE_TYPES = {"process", "timeline", "checklist", "decision_flow", "sequence"}
_NO_GUIDE = "text_only"

_SYSTEM_PROMPT = """You classify how a validated accounting/audit/tax answer's
numbered steps should be visualised in a chat UI. Choose exactly one layout:

- process: a general sequential procedure with no strict timing, decision, or
  actor-to-actor messaging shape.
- timeline: steps anchored to dates, deadlines, or a chronological schedule.
- checklist: discrete review/verification items with no required order.
- decision_flow: steps that branch on a decision or condition.
- sequence: steps describing one actor/system sending a message or request to
  another (e.g. "the classifier forwards the query to the calculation engine").
- text_only: no diagram adds value; plain text is best.

Only choose from these six values. Never output HTML, Markdown, or code —
guide_type is a single enum word, and reasoning_summary is a short plain-English
sentence for an internal log, never shown to the end user verbatim. Set
requires_clarification to true when the query is genuinely ambiguous between
two layouts and you are not confident enough to pick one.
"""


@dataclass(frozen=True)
class GuideClassification:
    guide_type: str  # one of _ALLOWED_GUIDE_TYPES, or the _NO_GUIDE sentinel
    confidence: float
    reasoning_summary: str
    requires_clarification: bool
    model: str


def configured_mode() -> str:
    """Use fallback by default; it remains inert without an API key and all
    provider failures still fail safely to deterministic/text presentation."""
    mode = os.getenv("PRESENTATION_LLM_CLASSIFIER_MODE", "fallback").strip().lower()
    return mode if mode in {"off", "fallback"} else "off"


def _sanitize_reasoning(text: str) -> str:
    stripped = re.sub(r"```|[<>`]", "", text)
    return re.sub(r"\s+", " ", stripped).strip()[:200]


def classify(query: str, ordered_items: list[str]) -> GuideClassification | None:
    """Classify with OpenAI Structured Outputs, returning ``None`` on failure.

    Provider/network/timeout/parsing failures are intentionally swallowed
    here — the caller (presentation.py) owns the safe text-only or
    clarification-question fallback and records which path was taken.
    """
    if configured_mode() == "off":
        return None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI

        model = os.getenv("PRESENTATION_LLM_CLASSIFIER_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        client = OpenAI(
            api_key=api_key,
            timeout=float(os.getenv("PRESENTATION_LLM_CLASSIFIER_TIMEOUT_SECONDS", "6")),
            max_retries=1,
        )
        allowed = sorted(_ALLOWED_GUIDE_TYPES | {_NO_GUIDE})
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"query": query, "steps": ordered_items[:10]},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "presentation_guide_classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "guide_type": {"type": "string", "enum": allowed},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reasoning_summary": {"type": "string"},
                            "requires_clarification": {"type": "boolean"},
                        },
                        "required": [
                            "guide_type", "confidence", "reasoning_summary", "requires_clarification",
                        ],
                    },
                },
            },
        )
        content = response.choices[0].message.content
        payload = json.loads(content or "")
        guide_type = str(payload["guide_type"])
        confidence = float(payload["confidence"])
        if guide_type not in allowed or not 0 <= confidence <= 1:
            return None
        return GuideClassification(
            guide_type=guide_type,
            confidence=confidence,
            reasoning_summary=_sanitize_reasoning(str(payload["reasoning_summary"])),
            requires_clarification=bool(payload["requires_clarification"]),
            model=model,
        )
    except Exception:
        return None
