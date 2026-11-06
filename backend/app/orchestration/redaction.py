"""
Massarius™ retrieval and evidence subsystem — query redaction before external
model exposure (ZL-ENG-03 §5.8; ZL-ENG-02 §9 "no partial leakage").

Runs at the external-provider exposure boundary — immediately before
orchestration/service.py hands grounded_input to model_gateway_service — not
at pipeline entry. Redacting at entry would break tenant-private retrieval
recall (entity names can be legitimate retrieval keys) and blind the
pre-screen injection/exfiltration checks in orchestration/prescreen.py,
which need the raw query. See ZL-ENG-03 §1's "Redaction too early" correction.

MVP scope, honestly bounded (same "keyword_mvp" labeling precedent as
orchestration/retrieve.py): regex-based structured-PII redaction only —
email addresses, IBAN, US SSN, UK NI numbers, UK sort codes, and
Luhn-valid card numbers. Deliberately does NOT attempt generic numeric ID
redaction (invoice numbers, tax references, standard section numbers like
"IFRS 16" are all short numeric strings an accounting assistant must be
able to see) or named-entity redaction (person/organisation names need real
NER — Presidio/spaCy — not implemented here). Both are flagged gaps, not
silently assumed solved; a query containing a client's name is NOT
currently redacted before reaching an external model provider.

Preserves accounting meaning per the source spec: only the matched PII
span is replaced with a category placeholder — jurisdiction, framework,
transaction type, and every other term survives unredacted.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

# Deliberately excludes generic account-number/phone-number patterns — see
# module docstring. Only patterns with a low accounting-domain false-positive
# rate are included.
_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "uk_ni_number": re.compile(r"\b[A-CEGHJ-PR-TW-Za-ceghj-pr-tw-z]{2}\d{6}[A-Da-d]\b"),
    "uk_sort_code": re.compile(r"\b\d{2}-\d{2}-\d{2}\b"),
    # Anchored digit-first/last so a trailing separator (e.g. the space
    # before the next word) is never pulled into the match.
    "card_number": re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
    # A pasted credential (QA K06, P0): the value after a key-like name, and
    # common provider key formats. Only the value is replaced.
    "secret": re.compile(r"(?<=[=:])[ \t]*[A-Za-z0-9_\-/+]{8,}"
                         r"|\b(?:sk|gsk|pk|rk)[-_][A-Za-z0-9_-]{16,}\b|\bAKIA[0-9A-Z]{16}\b"),
}
# The names whose "=" or ":" value is a secret ("fake_key=DEMO_…", "api key: …").
_SECRET_NAME = re.compile(
    r"\b(?:api[\s_-]?key|apikey|secret(?:[\s_-]?key)?|client[\s_-]?secret|access[\s_-]?(?:key|token)|"
    r"auth[\s_-]?token|bearer|token|password|passwd|private[\s_-]?key|\w*_key)\s*$", re.I)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class RedactionResult:
    redacted_text: str
    redaction_applied: bool
    redaction_categories: list[str] = field(default_factory=list)
    # placeholder -> original span. Access-controlled by the caller (never
    # persisted in plaintext audit fields) — ZL-ENG-03 §5.8's
    # "encrypted redaction_map reference only" requirement.
    redaction_map: dict[str, str] = field(default_factory=dict)


def redact_for_external_exposure(text: str) -> RedactionResult:
    """Redact structured PII from `text` before it is sent to an external
    model provider. Returns the redacted text plus a map of the
    placeholders it introduced, so a caller with legitimate need (e.g. a
    human reviewer with access controls) can reverse it — this function
    itself never logs or persists the original spans."""
    categories: set[str] = set()
    redaction_map: dict[str, str] = {}
    redacted = text

    for category, pattern in _PATTERNS.items():
        def _replace(match: re.Match, category: str = category) -> str:
            span = match.group(0)
            lead = ""
            if category == "card_number":
                digits = re.sub(r"[ -]", "", span)
                if not (13 <= len(digits) <= 19) or not _luhn_valid(digits):
                    return span  # not a real card number — leave untouched
            if category == "secret" and match.string[match.start() - 1:match.start()] in ("=", ":"):
                # "Total: 12400000" is a figure; only a key-like name's value is a secret.
                if not _SECRET_NAME.search(match.string[max(0, match.start() - 41):match.start() - 1]):
                    return span
                lead, span = re.match(r"([ \t]*)(.*)", span, re.S).groups()
            placeholder = f"[REDACTED_{category.upper()}_{uuid.uuid4().hex[:8]}]"
            redaction_map[placeholder] = span
            categories.add(category)
            return lead + placeholder

        redacted = pattern.sub(_replace, redacted)

    return RedactionResult(
        redacted_text=redacted,
        redaction_applied=bool(categories),
        redaction_categories=sorted(categories),
        redaction_map=redaction_map,
    )
