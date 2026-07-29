"""
LLM-based risk classifier for Ask Kriton™.

The built-in zero-shot model (risk_classifier.py's distilroberta) is small and
often low-confidence, so it collapses many perfectly ordinary questions into
the "uncertain -> MEDIUM" fallback (e.g. "What is a tax credit?" comes back
MEDIUM). This uses the same Groq LLM already in the stack to classify a
question's risk on a clear ZERO/LOW/MEDIUM/HIGH rubric instead — much more
accurate for real questions.

Fails soft: returns None on any error / missing key, so the caller falls back
to the ML classifier's result rather than erroring.
"""
from __future__ import annotations

import os
from typing import Optional

from groq import AsyncGroq

_VALID = {"ZERO", "LOW", "MEDIUM", "HIGH"}

_SYSTEM = (
    "You classify the RISK LEVEL of a user's question for an accounting, tax, "
    "audit and payroll advisory assistant. Reply with EXACTLY ONE word — "
    "ZERO, LOW, MEDIUM, or HIGH — and nothing else.\n\n"
    "Rubric:\n"
    "- ZERO: greetings, small talk, or help about using the assistant; no "
    "accounting content. e.g. 'hi', 'what can you do?'\n"
    "- LOW: general definitional or educational questions with no personal or "
    "regulated stakes. e.g. 'What is a tax credit?', 'What is depreciation?'\n"
    "- MEDIUM: applied, procedural or how-to questions about accounting/tax/"
    "payroll methods in general. e.g. 'How is a finance lease recorded?', "
    "'How do I calculate VAT on a mixed supply?'\n"
    "- HIGH: requests for specific regulated advice about the asker's own "
    "situation, or tax/audit/legal opinions or decisions. e.g. 'Should my "
    "company claim R&D credits this year?', 'How should I file my client's "
    "return?'"
)


async def classify_risk(query: str) -> Optional[str]:
    """Return 'ZERO' | 'LOW' | 'MEDIUM' | 'HIGH' for the question, or None if
    the LLM is unavailable/errors (caller then keeps the ML classifier result)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    # Classification is a trivial one-word task — use a small, fast model
    # (llama-3.1-8b-instant) instead of the large answer model, so this extra
    # call is near-instant. Configurable via GROQ_CLASSIFIER_MODEL; the big
    # GROQ_MODEL stays reserved for actual answer generation.
    model = os.getenv("GROQ_CLASSIFIER_MODEL", "llama-3.1-8b-instant")
    try:
        client = AsyncGroq(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=4,
        )
        raw = (resp.choices[0].message.content or "").strip().upper()
    except Exception:
        return None

    # Model should return one bare word; be tolerant of stray punctuation.
    for level in _VALID:
        if level in raw:
            return level
    return None
