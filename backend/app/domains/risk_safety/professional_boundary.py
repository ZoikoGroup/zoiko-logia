"""
Professional boundary post-generation validator (ZL-T0-04 §7).

Scans LLM-generated text for prohibited professional assertions.
This is the LAST safety gate before an answer reaches the user.

Prohibited outputs (§7.1):
  • Professional identity claims ("I certify", "I advise as your accountant")
  • Definitive personalized treatment without sufficient context
  • Autonomous approval / sign-off / certification
  • Regulator / professional-body representation
  • Unsupported certainty or hidden assumptions on material answers

Permitted behavior (§7.2):
  Kriton™ may provide workflow guidance when all four sufficient-context
  conditions are met (source basis, context specificity, human review
  available, professional judgment acknowledged).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class BoundaryViolation:
    """Details of a detected professional boundary violation."""
    phrase_matched: str
    category: str
    severity: str  # "hard" (always block) or "soft" (add disclaimer)


# ─── Pattern Banks ──────────────────────────────────────────────────────────

_HARD_VIOLATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), category)
    for p, category in [
        (r"\bI\s+certify\s+that\b", "professional-identity"),
        (r"\bI\s+advise\s+you\s+to\b", "professional-identity"),
        (r"\bas\s+your\s+(accountant|auditor|tax\s+advisor|lawyer)\b", "professional-identity"),
        (r"\bI\s+verify\s+this\s+(filing|return|report)\s+is\s+correct\b", "autonomous-approval"),
        (r"\bI\s+approve\s+this\b", "autonomous-approval"),
        (r"\bI\s+sign\s+off\s+on\b", "autonomous-approval"),
        (r"\bthis\s+is\s+legally\s+compliant\b", "regulator-representation"),
        (r"\bI\s+am\s+a\s+licensed\b", "professional-identity"),
        (r"\bI\s+guarantee\b", "unsupported-certainty"),
        (r"\byou\s+must\s+file\b", "unsupported-certainty"),
        (r"\byou\s+are\s+required\s+to\b", "unsupported-certainty"),
        (r"\bthis\s+is\s+the\s+only\s+correct\s+treatment\b", "unsupported-certainty"),
    ]
]

_SOFT_VIOLATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), category)
    for p, category in [
        (r"\bthe\s+treatment\s+is\b", "certainty-language"),
        (r"\byou\s+should\s+definitely\b", "certainty-language"),
        (r"\bwithout\s+a\s+doubt\b", "certainty-language"),
        (r"\bthere\s+is\s+no\s+question\b", "certainty-language"),
    ]
]

# ─── Boundary notice text (appended when soft violations found) ─────────

BOUNDARY_NOTICE = (
    "Note: Kriton™ provides source-governed guidance to support your "
    "professional judgment. It does not act as a licensed accountant, "
    "auditor, tax advisor, or legal counsel. The above is based on the "
    "stated facts and the applicable standard — it is not a substitute "
    "for professional review."
)


def validate(text: str) -> tuple[bool, list[BoundaryViolation]]:
    """
    Validate generated text against professional boundary rules.

    Returns:
        (is_safe, violations)
        - is_safe: True if no hard violations found
        - violations: List of all detected violations (hard + soft)
    """
    violations: list[BoundaryViolation] = []

    for pattern, category in _HARD_VIOLATIONS:
        match = pattern.search(text)
        if match:
            violations.append(
                BoundaryViolation(
                    phrase_matched=match.group(0),
                    category=category,
                    severity="hard",
                )
            )

    for pattern, category in _SOFT_VIOLATIONS:
        match = pattern.search(text)
        if match:
            violations.append(
                BoundaryViolation(
                    phrase_matched=match.group(0),
                    category=category,
                    severity="soft",
                )
            )

    has_hard = any(v.severity == "hard" for v in violations)
    return (not has_hard, violations)


def append_boundary_notice(text: str) -> str:
    """Append the standard professional boundary disclaimer to an answer."""
    return f"{text}\n\n---\n{BOUNDARY_NOTICE}"
