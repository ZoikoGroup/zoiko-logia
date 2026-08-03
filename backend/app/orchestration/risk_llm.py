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

import asyncio
import os
from typing import Optional

from groq import AsyncGroq

_VALID = {"ZERO", "LOW", "MEDIUM", "HIGH"}

_SYSTEM = (
    "You classify the RISK LEVEL of a user's question for an accounting, tax, "
    "audit and payroll advisory assistant. Reply with EXACTLY ONE word — "
    "ZERO, LOW, MEDIUM, or HIGH — and nothing else.\n\n"
    "Judge by the FORM of the question and GENERALISE to any similar question, "
    "not just the listed examples:\n"
    "- ZERO: a greeting or small talk, help about using the assistant, OR a "
    "simple 'what is X' / 'define X' / plain 'explain X' question answerable as "
    "a short fact or plain definition/explanation, with NO specific structured "
    "format requested. e.g. 'hi', 'what can you do?', 'What is IFRS?', 'Define "
    "tax', 'Explain tax rules'.\n"
    "- LOW: an educational question that explicitly asks for a STRUCTURED or "
    "FORMATTED breakdown — phrased 'in N points', 'in N lines', 'as a list', "
    "'in bullet points', 'give me a summary in points', 'list the …' — with no "
    "personal or regulated stakes. The trigger is the requested format, not the "
    "topic. e.g. 'Explain tax in 10 points', 'Summarise IFRS in 5 lines', "
    "'List the types of GST'.\n"
    "- MEDIUM: an applied 'HOW DO I / HOW IS X DONE' question about a general "
    "method, procedure or calculation, NOT about the asker's own specific "
    "case. e.g. 'How is a finance lease recorded?', 'How do I calculate VAT on "
    "a mixed supply?', 'Steps to prepare a bank reconciliation'.\n"
    "- HIGH: a request to DECIDE or ADVISE on the asker's or a client's OWN "
    "specific situation, or a tax/audit/legal opinion or decision with real "
    "consequences — usually signalled by 'I', 'my', 'my company', 'my client', "
    "'should I', 'can I', 'am I required'. e.g. 'Should my company claim R&D "
    "credits this year?', 'How should I file my client's return?', 'Am I "
    "required to register for VAT with turnover of X?'"
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


async def classify_risk_gemini(query: str) -> Optional[str]:
    """Fallback classifier: same ZERO/LOW/MEDIUM/HIGH rubric, but via Google
    Gemini instead of Groq. Used only when the primary Groq classifier above
    returns None (Groq down / no key / rate-limited), giving provider-level
    redundancy across two different LLMs. Also fails soft — returns None on any
    error / missing key, so the caller can fall back to the ML result."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    # Reuse the configured Gemini model (a small/fast one is ideal for this
    # one-word task); GEMINI_CLASSIFIER_MODEL can override it independently.
    model = os.getenv("GEMINI_CLASSIFIER_MODEL") or os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    try:
        from google import genai
        from google.genai import types

        def _call() -> str:
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=model,
                contents=query,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    temperature=0.0,
                    # Gemini flash is a "thinking" model: internal reasoning is
                    # billed against max_output_tokens, so a tiny cap (e.g. 16)
                    # gets fully consumed by thinking and returns EMPTY text
                    # (finish_reason=MAX_TOKENS). 256 leaves ample room for the
                    # thinking plus the one-word answer. thinking_budget=0 is
                    # rejected by this model, so headroom is the reliable fix.
                    max_output_tokens=256,
                ),
            )
            return (resp.text or "").strip().upper()

        # google-genai's call is synchronous — run it off the event loop so it
        # doesn't block other concurrent requests while awaiting the model.
        raw = await asyncio.to_thread(_call)
    except Exception:
        return None

    for level in _VALID:
        if level in raw:
            return level
    return None
