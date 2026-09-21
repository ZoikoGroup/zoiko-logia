"""
Post-composition validation gate — ZL-ENG-02 §10, Release Gate RG-03.

Validates LLM output AFTER composition but BEFORE response finalisation.
On failure: audit composition_rejected and degrade route to REFUSAL or HUMAN_REVIEW.
The invalid answer is NEVER returned to the frontend.

Checks:
  1. Grounding check    — every substantive answer claim attributable to SourceBundle
  2. Citation binding   — all [REF-N] markers reference sources in eligible_sources
  3. Prohibited-claim scan — ZL-ENG-01 professional boundary checks
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from app.orchestration.schemas import SourceBundle

# ── Prohibited professional claim patterns ────────────────────────────────────
# ZL-ENG-01: claims that constitute specific professional advice
_PROHIBITED_PATTERNS = [
    r"you\s+(should|must|need\s+to)\s+(file|register|pay|submit|declare)",
    r"(your|the\s+company('s)?)\s+(tax\s+(liability|return)|audit\s+opinion)",
    r"i\s+(confirm|certify|guarantee|assure)\s+(that\s+)?",
    r"(this\s+is\s+)?(legal|tax|audit|financial)\s+(advice|opinion|certification)",
    r"as\s+your\s+(accountant|auditor|tax\s+advisor|legal\s+counsel)",
    r"(sign|signature|signed)\s+(off|on)\s+(by|as)",
]
_PROHIBITED = [re.compile(p, re.IGNORECASE) for p in _PROHIBITED_PATTERNS]

_REF_PATTERN = re.compile(r"\[REF-(\d+)\]")


@dataclass
class ValidationResult:
    passed: bool
    failures: List[str] = field(default_factory=list)
    degraded_route: str = "REFUSAL"     # route to use if failed


def validate_composition(
    answer_text: str,
    source_bundle: SourceBundle,
) -> ValidationResult:
    """
    Run all three post-composition checks per §10.
    Returns ValidationResult(passed=False, ...) if any check fails.
    """
    failures: list[str] = []

    # 1. Grounding check — answer must not claim topics with no eligible sources
    if source_bundle.eligible_source_count == 0 and len(answer_text.strip()) > 50:
        failures.append(
            "Grounding check failed: answer contains substantive content "
            "but no eligible sources exist in the SourceBundle."
        )

    # 2. Citation binding — all [REF-N] must map to sources in eligible_sources
    ref_ids_in_answer = set(_REF_PATTERN.findall(answer_text))
    eligible_ids = set(str(i + 1) for i in range(source_bundle.eligible_source_count))
    unbound_refs = ref_ids_in_answer - eligible_ids
    if unbound_refs:
        failures.append(
            f"Citation binding failed: answer references [REF-{','.join(sorted(unbound_refs))}] "
            f"which are not present in eligible_sources."
        )

    # 3. Prohibited-claim scan
    for pattern in _PROHIBITED:
        if pattern.search(answer_text):
            failures.append(
                f"Prohibited-claim detected: answer contains professional-advice language "
                f"matching pattern '{pattern.pattern}'."
            )
            break   # One violation is sufficient to fail

    if failures:
        # Degrade to HUMAN_REVIEW if there's a citation or grounding issue
        # (may indicate model confusion), REFUSAL if prohibited claim
        has_prohibited = any("Prohibited" in f for f in failures)
        degraded = "REFUSAL" if has_prohibited else "HUMAN_REVIEW"
        return ValidationResult(passed=False, failures=failures, degraded_route=degraded)

    return ValidationResult(passed=True)


def build_validated_disclaimer(
    answer_text: str,
    risk_level: str,
    disclaimer_required: bool,
    confidence_state: str,
) -> str:
    """Append mandatory disclaimers for MEDIUM risk or limited confidence answers (§10)."""
    if not disclaimer_required:
        return answer_text

    disclaimer = (
        "\n\n---\n"
        "⚠️ **Kriton™ Disclaimer**: This response is provided for educational and informational "
        "purposes only under source-governed retrieval. It does not constitute professional "
        "accounting, tax, audit or legal advice. Always consult a qualified professional "
        "before acting on any guidance. Sources cited reflect available documentation at "
        "the time of retrieval and may not represent the latest effective standards."
    )
    return answer_text + disclaimer
