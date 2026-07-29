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


def classify(query: str, *, jurisdiction: str = "", mode: str = "Workflow") -> LLMClassification | None:
    """Classify with OpenAI Structured Outputs, returning ``None`` on failure.

    Provider/network failures are intentionally swallowed here. The caller owns
    the conservative MEDIUM/HIGH fallback and records the failure reason.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

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
        return None
