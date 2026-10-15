"""
Pre-screen safety gate — ZL-ENG-02 §6.

Runs BEFORE source retrieval and model work. This ordering is a Release Gate (RG-01).

Checks:
  1. Prompt injection — attempts to override system rules, reveal internals
  2. Data exfiltration — attempts to access unauthorised tenant data, credentials, logs
  3. Malicious instruction — commands to ignore governance, jailbreak, act unsafely
  4. Academic integrity — requests to solve exam/quiz/graded assessment questions

A FAILED pre-screen short-circuits the entire pipeline. No retrieval or model work runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ── Pattern registry ──────────────────────────────────────────────────────────

_PROMPT_INJECTION_PATTERNS = [
    # Qualifiers before "instruction(s)" and "prompt" are optional and
    # stack in real attacks ("ignore YOUR PREVIOUS instructions", "reveal
    # YOUR SYSTEM prompt") — each was previously a single fixed alternative,
    # so a real query naming two qualifiers together (as most natural
    # phrasing does) matched neither and slipped through. The two qualifier
    # groups below use distinct, non-overlapping literal words (no character
    # class shared between them), so — unlike the catastrophic-backtracking
    # regex fixed in calculation_service.py — there is exactly one way to
    # parse a run of them: no ambiguity, no exponential blowup.
    # A third qualifier group names WHICH instructions ("ignore previous
    # SECURITY instructions") — it was not matched and passed the screen
    # (ZL-ENG-AGT-01 §10 test). Distinct literal words, so still unambiguous.
    r"ignore\s+(?:the\s+|all\s+|your\s+|any\s+)*(?:previous\s+|prior\s+|above\s+)*"
    r"(?:security\s+|safety\s+|system\s+|access\s+|governance\s+|policy\s+)*instructions?\b",
    r"disregard\s+(?:(?:all|the)\s+)?(?:previous|prior|your)\s+instructions?\b",
    r"override\s+(?:the\s+|your\s+)?(system|safety|governance|policy)",
    r"forget\s+(?:the\s+|your\s+|all\s+)*(everything|rules|instructions)",
    r"you\s+are\s+now\s+(a\s+)?(?:different|unrestricted|jailbreak)",
    r"reveal\s+(?:the\s+|your\s+)*(system\s+prompt|internal|prompt|configuration)",
    r"print\s+(?:the\s+|your\s+)*(system\s+)?prompt",
    r"act\s+as\s+(if\s+you\s+have\s+no\s+|without\s+)?(restriction|limit|filter)",
    r"disregard\s+(?:the\s+|your\s+|all\s+|any\s+|previous\s+|prior\s+)*(safety|governance|rules?|instructions?)",
    r"hypothetically\s+(speaking\s+)?if\s+you\s+(had\s+no|were\s+not)",
    r"jailbreak",
    r"DAN\s+mode",
    # Quoted/source-text attacks often omit "previous" but still attempt to
    # turn untrusted content into higher-priority instructions.
    r"treat\s+(?:the\s+)?following\s+(?:source\s+)?text\s+as\s+instructions?",
    r"pretend\s+(?:that\s+)?you\s+are\s+unrestricted",
    r"answer\s+without\s+(?:recording|creating|writing)\s+(?:an?\s+)?audit(?:\s+event)?",
]

# Each pattern names a system target (other tenants' or users' data, logs,
# the hash chain, system files, credentials), not an accounting word on its
# own: "show audit procedures for inventory", "list client acceptance
# procedures", "export data to Excel" and a pasted review citing
# https://www.ifrs.org were all blocked as security incidents.
_DATA_EXFILTRATION_PATTERNS = [
    r"\b(?:show|list|dump|export|print|give|reveal|get|fetch|retrieve)\s+(?:me\s+)?(?:all\s+|every\s+|each\s+)?"
    r"(?:the\s+|other\s+|another\s+)?(?:tenants?|users?)(?:'s|s'|’s)?\s+"
    r"(?:data|records|details|emails?|passwords?|accounts?|documents?|files?|information)\b",
    r"\b(?:other|another|different|every|all)\s+tenants?(?:'s|s'|’s)?\s+(?:data|records|documents?|files?|information)\b",
    r"access\s+(another|other|different)\s+tenant",
    r"(retrieve|get|fetch)\s+(credentials|api\s+key|secret|password|token)",
    r"\b(?:show|print|dump|export|reveal|give)\s+(?:me\s+)?(?:the\s+|your\s+|all\s+)*"
    r"(?:system|server|internal|raw|application|audit|access|error|security|kriton(?:'s)?)\s+logs?\b",
    r"\b(?:show|print|dump|export|reveal)\s+(?:me\s+)?(?:the\s+|your\s+)*(?:audit\s+)?hash(?:es)?\s+chain\b",
    r"\b(?:read|access|open|cat)\s+(?:the\s+|your\s+)?(?:system|server|config(?:uration)?|env(?:ironment)?)\s+"
    r"(?:files?|director(?:y|ies))\b",
    r"\b(?:read|access|open|query|dump)\s+(?:the\s+|your\s+)?(?:kriton(?:'s)?|internal|backend|production|underlying|system)\s+database\b",
    # SQL, not prose: "select the method from the list" is an ordinary sentence.
    r"(?-i:\bSELECT\b)\s+[\w*.,\s]{1,80}?\s+(?-i:FROM)\s+\w+|\bselect\s+\*\s+from\b",
    # A command or an instruction to send data out — not a link being cited.
    r"\b(?:curl|wget)\s+(?:-{1,2}[\w-]+\s+)*['\"]?https?://",
    r"\b(?:send|post|upload|forward|transmit|exfiltrate)\s+(?:this|the|these|all|it|them|every)?[^.\n]{0,40}?\s+to\s+https?://",
    r"(?:disclose|reveal|provide|expose)\s+(?:the\s+)?(?:api\s+keys?|credentials?|secrets?|passwords?|tokens?)",
    r"(?:disclose|reveal|provide|expose)\s+(?:confidential|private)\s+(?:tenant\s+)?data",
]

_MALICIOUS_INSTRUCTION_PATTERNS = [
    r"make\s+(a|the)?\s*(bomb|weapon|malware|virus|exploit)",
    r"(synthesize|produce|create)\s+(illegal|harmful|dangerous)\s+substance",
    r"how\s+to\s+(harm|kill|hurt|attack)",
    r"bypass\s+(security|auth|authorization|firewall)",
    r"control\s+bypass",
    r"(stolen|hacked|leaked)\s+(credential|data|account)",
]

_ACADEMIC_INTEGRITY_PATTERNS = [
    r"\b(solve\s+(my|this)\s+(\w+\s+){0,2}exam|exam\s+answer|quiz\s+answer|"
    r"complete\s+(my|this)\s+(\w+\s+){0,2}assessment|do\s+my\s+homework|"
    r"answer\s+(my|this)\s+(\w+\s+){0,2}assignment)\b",
]


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]


_INJECTION = _compile(_PROMPT_INJECTION_PATTERNS)
_EXFILTRATION = _compile(_DATA_EXFILTRATION_PATTERNS)
_MALICIOUS = _compile(_MALICIOUS_INSTRUCTION_PATTERNS)
_ACADEMIC_INTEGRITY = _compile(_ACADEMIC_INTEGRITY_PATTERNS)


@dataclass
class PreScreenResult:
    passed: bool
    trigger: Optional[str] = None        # "prompt_injection" | "data_exfiltration" |
                                          # "malicious_instruction" | "academic_integrity"
    trigger_detail: Optional[str] = None  # matched pattern for evidence reference
    matched_text: Optional[str] = None    # the words that matched, shown to the user


def embedded_instructions(text: str) -> Optional[str]:
    """For content that is DATA, not a request: a retrieved document, an
    uploaded file or a tool result (ZL-ENG-AGT-01 §13 Demo C). Returns the
    trigger ("prompt_injection" / "data_exfiltration") when the text contains
    instruction-like wording, else None. The caller keeps the content but
    marks it untrusted and records the finding; it never blocks on it."""
    for trigger, patterns in (("prompt_injection", _INJECTION), ("data_exfiltration", _EXFILTRATION)):
        if any(pattern.search(text or "") for pattern in patterns):
            return trigger
    return None


def run_prescreen(query: str) -> PreScreenResult:
    """
    Evaluate the user query against all pre-screen safety patterns.
    Returns PreScreenResult(passed=False, trigger=...) on failure.
    Pipeline MUST short-circuit immediately on failure — no retrieval or model work.
    """
    for trigger, patterns in (
        ("prompt_injection", _INJECTION),
        ("data_exfiltration", _EXFILTRATION),
        ("malicious_instruction", _MALICIOUS),
        ("academic_integrity", _ACADEMIC_INTEGRITY),
    ):
        for pattern in patterns:
            match = pattern.search(query)
            if match:
                return PreScreenResult(
                    passed=False,
                    trigger=trigger,
                    trigger_detail=pattern.pattern,
                    matched_text=" ".join(match.group(0).split())[:80],
                )

    return PreScreenResult(passed=True)


_BLOCK_REASONS = {
    "prompt_injection": "it contains wording that tries to change Kriton's instructions",
    "data_exfiltration": "it asks for system data, another user's or tenant's data, credentials or logs, "
                         "or tells Kriton to send data to a web address",
    "malicious_instruction": "it asks for something harmful or for a way around security controls",
    "academic_integrity": "it asks Kriton to answer a graded exam, quiz or assignment",
}


def block_message(trigger: Optional[str], matched_text: Optional[str] = None) -> str:
    """Say which rule stopped the request and the words that tripped it, so a
    false block can be fixed by rewording instead of guessing ("what
    specifically blocked the query" was itself refused as off-topic)."""
    reason = _BLOCK_REASONS.get(trigger or "", "it matched a security policy")
    message = f"Kriton blocked this request because {reason}."
    if matched_text:
        message += f' The words that triggered it: "{matched_text}".'
    return message + " If that is a misreading, rephrase those words and ask again."
