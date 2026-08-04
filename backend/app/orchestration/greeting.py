"""
Pure-greeting detector — "Hi", "Hello Kriton", "good morning", "what's up".

Without this, a plain greeting retrieves zero document context (nothing in
an accounting/tax source library matches "Hi"), which trips the §2 "no
unsupported answering" rule (orchestration/service.py) and returns the
confusing "Kriton could not find sufficient sources... clarify your
jurisdiction" message — a wrong response to something as simple as "hi".

Deliberately a whole-string match, not a substring/keyword-contains check:
"Hi, can you calculate my VAT?" must NOT match this — that's a real
question that happens to start with a greeting, not a pure greeting, and
still needs the full grounded/citation pipeline. Anchoring the pattern to
the entire (normalized) query is what keeps this safe from false positives.
"""
from __future__ import annotations

import re

_GREETING_PATTERN = re.compile(
    r"^\s*"
    r"(hi+|hey+|yo+|hello+|howdy|greetings|"
    r"good\s*morning|good\s*afternoon|good\s*evening|"
    r"what'?s?\s*up)"
    r"(\s*,?\s*kriton)?"
    r"\s*[!.?]*\s*$",
    re.IGNORECASE,
)


def is_pure_greeting(query: str) -> bool:
    return bool(_GREETING_PATTERN.match(query))
