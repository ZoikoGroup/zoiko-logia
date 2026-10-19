"""An honest "I can't do this, because…" reply.

"I'm unable to prepare a balance sheet from the uploaded ledger because the
data does not classify the nominal codes…" makes no factual claim and states
no figure: it explains why the task cannot be done. The grounding check
(answer_validator.py, check 1) escalated it to human review because it is
longer than 50 characters and had no sources, so the reader got "Response
validation failed" instead of the explanation.

Deliberately narrow: an explicit inability statement, no digits at all (no
figure that could be wrong), no citation markers, and short. A reply that
says "I can't do X, but here is Y = 4,200" has digits and still goes through
every check.
"""
from __future__ import annotations

import re

MAX_CHARS = 900
_INABILITY = re.compile(
    r"\b(?:i\s*(?:am|['’]m)\s+(?:unable|not\s+able)\s+to|i\s+(?:cannot|can\s*not|can['’]t)\b|"
    r"(?:cannot|can\s*not|can['’]t)\s+be\s+(?:produced|prepared|determined|calculated|created|generated|retrieved)|"
    r"is\s+not\s+possible\s+(?:to|with)|not\s+enough\s+(?:data|information))",
    re.IGNORECASE,
)


def is_limitation_reply(text: str) -> bool:
    body = (text or "").strip()
    return (
        bool(body)
        and len(body) <= MAX_CHARS
        and not re.search(r"\d", body)
        and "[REF-" not in body
        and bool(_INABILITY.search(body[:300]))
    )
