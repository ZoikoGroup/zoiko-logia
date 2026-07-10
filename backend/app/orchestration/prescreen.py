"""
Pre-screen safety gate — ZL-ENG-02 §6.

Runs BEFORE source retrieval and model work. This ordering is a Release Gate (RG-01).

Checks:
  1. Prompt injection — attempts to override system rules, reveal internals
  2. Data exfiltration — attempts to access unauthorised tenant data, credentials, logs
  3. Malicious instruction — commands to ignore governance, jailbreak, act unsafely

A FAILED pre-screen short-circuits the entire pipeline. No retrieval or model work runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ── Pattern registry ──────────────────────────────────────────────────────────

_PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|your)\s+instruction",
    r"override\s+(system|safety|governance|policy)",
    r"forget\s+(everything|your\s+rules|instructions)",
    r"you\s+are\s+now\s+(a\s+)?(?:different|unrestricted|jailbreak)",
    r"reveal\s+(system\s+prompt|internal|your\s+prompt|configuration)",
    r"print\s+your\s+(system\s+)?prompt",
    r"act\s+as\s+(if\s+you\s+have\s+no\s+|without\s+)?(restriction|limit|filter)",
    r"disregard\s+(safety|governance|the\s+rule)",
    r"hypothetically\s+(speaking\s+)?if\s+you\s+(had\s+no|were\s+not)",
    r"jailbreak",
    r"DAN\s+mode",
]

_DATA_EXFILTRATION_PATTERNS = [
    r"(show|list|dump|export|print)\s+(all\s+)?(tenant|user|client|document|data|source)",
    r"access\s+(another|other|different)\s+tenant",
    r"(retrieve|get|fetch)\s+(credentials|api\s+key|secret|password|token)",
    r"(show|print|dump)\s+(log|audit|chain|hash|event)",
    r"(read|access|open)\s+(system\s+)?(file|directory|database)",
    r"SELECT\s+.+\s+FROM",
    r"curl\s+|wget\s+|http(s)?://",
]

_MALICIOUS_INSTRUCTION_PATTERNS = [
    r"make\s+(a|the)?\s*(bomb|weapon|malware|virus|exploit)",
    r"(synthesize|produce|create)\s+(illegal|harmful|dangerous)\s+substance",
    r"how\s+to\s+(harm|kill|hurt|attack)",
    r"bypass\s+(security|auth|authorization|firewall)",
    r"control\s+bypass",
    r"(stolen|hacked|leaked)\s+(credential|data|account)",
]


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]


_INJECTION = _compile(_PROMPT_INJECTION_PATTERNS)
_EXFILTRATION = _compile(_DATA_EXFILTRATION_PATTERNS)
_MALICIOUS = _compile(_MALICIOUS_INSTRUCTION_PATTERNS)


@dataclass
class PreScreenResult:
    passed: bool
    trigger: Optional[str] = None        # "prompt_injection" | "data_exfiltration" | "malicious_instruction"
    trigger_detail: Optional[str] = None  # matched pattern for evidence reference


def run_prescreen(query: str) -> PreScreenResult:
    """
    Evaluate the user query against all pre-screen safety patterns.
    Returns PreScreenResult(passed=False, trigger=...) on failure.
    Pipeline MUST short-circuit immediately on failure — no retrieval or model work.
    """
    for pattern in _INJECTION:
        if pattern.search(query):
            return PreScreenResult(
                passed=False,
                trigger="prompt_injection",
                trigger_detail=pattern.pattern,
            )

    for pattern in _EXFILTRATION:
        if pattern.search(query):
            return PreScreenResult(
                passed=False,
                trigger="data_exfiltration",
                trigger_detail=pattern.pattern,
            )

    for pattern in _MALICIOUS:
        if pattern.search(query):
            return PreScreenResult(
                passed=False,
                trigger="malicious_instruction",
                trigger_detail=pattern.pattern,
            )

    return PreScreenResult(passed=True)
