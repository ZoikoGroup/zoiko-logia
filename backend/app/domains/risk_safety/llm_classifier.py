"""Schema-constrained LLM fallback for ambiguous risk classifications.

This classifier is deliberately subordinate to ``pre_screen``. It can only
propose ZERO..HIGH; deterministic code remains the sole authority for the
RESTRICTED tier.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


_ALLOWED_RISKS = {"ZERO", "LOW", "MEDIUM", "HIGH"}
_SYSTEM_PROMPT = """You classify user queries for an accounting education and
professional-advice product. Return only the requested JSON.

Risk definitions:
- ZERO: small talk, navigation, or no substantive accounting/tax/legal content.
- LOW: factual, educational, definitional, comparison, or arithmetic content.
- MEDIUM: interpretive accounting/audit content that is not personalized advice.
- HIGH: regulated tax/legal advice or a recommendation for a named person's,
  client's, or business's real situation.

Never return RESTRICTED. Privacy, security, licence, academic-integrity, and
control-bypass restrictions are enforced by deterministic rules before this
classifier. Do not lower risk because context is missing; report missing
context and choose the conservative applicable tier. Confidence expresses
classification certainty, not how safe the query is.
"""


@dataclass(frozen=True)
class LLMClassification:
    risk_level: str
    confidence: float
    intent: str
    advice_signal: bool
    missing_context: tuple[str, ...]
    reason_codes: tuple[str, ...]
    model: str


def configured_mode() -> str:
    """Return off, fallback, or shadow; invalid values fail closed to off."""
    mode = os.getenv("RISK_LLM_CLASSIFIER_MODE", "off").strip().lower()
    return mode if mode in {"off", "fallback", "shadow"} else "off"


def _user_content(query: str, jurisdiction: str, mode: str) -> str:
    return json.dumps({"query": query, "jurisdiction": jurisdiction or None, "product_mode": mode}, ensure_ascii=False)


def _parse_classification(content: str | None, model: str) -> LLMClassification | None:
    """Lenient shared parser for the Groq/Gemini fallback paths below, which
    use plain JSON mode rather than OpenAI's strict json_schema (Groq/Gemini
    support for that strict mode is less certain) — missing optional fields
    degrade to safe defaults instead of failing the whole classification."""
    payload = json.loads(content or "")
    risk_level = str(payload["risk_level"]).upper()
    if risk_level not in _ALLOWED_RISKS:
        return None
    confidence = payload.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) and 0 <= confidence <= 1 else 0.75
    return LLMClassification(
        risk_level=risk_level,
        confidence=confidence,
        intent=str(payload.get("intent", ""))[:120],
        advice_signal=bool(payload.get("advice_signal", False)),
        missing_context=tuple(str(item)[:80] for item in (payload.get("missing_context") or [])[:10]),
        reason_codes=tuple(str(item)[:80] for item in (payload.get("reason_codes") or [])[:10]),
        model=model,
    )


def _classify_via_groq(query: str, jurisdiction: str, mode: str) -> LLMClassification | None:
    """Fallback provider (2026-08-05) tried when OpenAI isn't configured —
    same schema/prompt, plain JSON mode, sync client (this whole module is
    called synchronously from risk_classifier.classify(), same as the OpenAI
    path above)."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq

        model = os.getenv("GROQ_CLASSIFIER_MODEL", "llama-3.1-8b-instant").strip() or "llama-3.1-8b-instant"
        client = Groq(api_key=api_key, timeout=float(os.getenv("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", "8")))
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT + "\nRespond with a single JSON object matching: "
                 '{"risk_level": "ZERO|LOW|MEDIUM|HIGH", "confidence": 0-1, "intent": "...", '
                 '"advice_signal": true|false, "missing_context": [...], "reason_codes": [...]}'},
                {"role": "user", "content": _user_content(query, jurisdiction, mode)},
            ],
        )
        return _parse_classification(response.choices[0].message.content, model)
    except Exception:
        return None


def _classify_via_gemini(query: str, jurisdiction: str, mode: str) -> LLMClassification | None:
    """Second fallback provider, tried only when both OpenAI and Groq are
    unavailable — provider-level redundancy across three different LLMs."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        model = os.getenv("GEMINI_CLASSIFIER_MODEL") or os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=_user_content(query, jurisdiction, mode),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT + "\nRespond with a single JSON object matching: "
                '{"risk_level": "ZERO|LOW|MEDIUM|HIGH", "confidence": 0-1, "intent": "...", '
                '"advice_signal": true|false, "missing_context": [...], "reason_codes": [...]}',
                temperature=0,
                response_mime_type="application/json",
                max_output_tokens=512,
            ),
        )
        return _parse_classification(response.text, model)
    except Exception:
        return None


def classify(query: str, *, jurisdiction: str = "", mode: str = "Workflow") -> LLMClassification | None:
    """Classify with OpenAI Structured Outputs, returning ``None`` on failure.

    Provider/network failures are intentionally swallowed here. The caller owns
    the conservative MEDIUM/HIGH fallback and records the failure reason.

    Real gap (2026-08-05): this call site is the ONLY wired-in LLM risk
    fallback, but it required OPENAI_API_KEY specifically — an environment
    with GROQ_API_KEY/GEMINI_API_KEY configured (and no OpenAI key) got
    silent, permanent None here regardless of RISK_LLM_CLASSIFIER_MODE.
    Falls through to Groq then Gemini so provider availability, not which
    key happens to be set, decides whether this fallback ever engages.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _classify_via_groq(query, jurisdiction, mode) or _classify_via_gemini(query, jurisdiction, mode)

    try:
        from openai import OpenAI

        model = os.getenv("RISK_LLM_CLASSIFIER_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        client = OpenAI(
            api_key=api_key,
            timeout=float(os.getenv("RISK_LLM_CLASSIFIER_TIMEOUT_SECONDS", "8")),
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"query": query, "jurisdiction": jurisdiction or None, "product_mode": mode},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "risk_classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "risk_level": {"type": "string", "enum": sorted(_ALLOWED_RISKS)},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "intent": {"type": "string"},
                            "advice_signal": {"type": "boolean"},
                            "missing_context": {"type": "array", "items": {"type": "string"}},
                            "reason_codes": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "risk_level", "confidence", "intent", "advice_signal",
                            "missing_context", "reason_codes",
                        ],
                    },
                },
            },
        )
        content = response.choices[0].message.content
        payload = json.loads(content or "")
        risk_level = str(payload["risk_level"]).upper()
        confidence = float(payload["confidence"])
        if risk_level not in _ALLOWED_RISKS or not 0 <= confidence <= 1:
            return None
        return LLMClassification(
            risk_level=risk_level,
            confidence=confidence,
            intent=str(payload["intent"])[:120],
            advice_signal=bool(payload["advice_signal"]),
            missing_context=tuple(str(item)[:80] for item in payload["missing_context"][:10]),
            reason_codes=tuple(str(item)[:80] for item in payload["reason_codes"][:10]),
            model=model,
        )
    except Exception:
        # OpenAI is configured but the call itself failed (outage, rate
        # limit, bad response) — same redundancy goal as the no-key branch
        # above: don't let one provider's failure silently disable this
        # whole fallback when another configured provider could answer.
        return _classify_via_groq(query, jurisdiction, mode) or _classify_via_gemini(query, jurisdiction, mode)
