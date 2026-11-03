"""The request part of a pasted case study.

A case study pastes a background ("Apex Motors … registered under GST …
deferred tax asset/liability …") and then the questions under a heading
("Questions to Answer:"). Checks written for one short question read the
background's words as the request: "GST" and "liability" asked a VAT
question nobody asked, "Apex Motors" and "net profit" fetched an unrelated
US company's SEC filing, "auditing the financial statements" added draft-
statement notes and the countries named added "tax rates not verified"
(29 Oct 2026). Those checks read the questions only; the whole text is
still what the answer is composed from.
"""
from __future__ import annotations

import re

_QUESTION_HEADING = re.compile(
    r"(?im)^[ \t#*>•\-]*(?:questions?(?:\s+to\s+(?:answer|address|consider))?|tasks?(?:\s+for\s+(?:the\s+)?(?:bot|kriton|model))?"
    r"|required|requirements?|your\s+tasks?|what\s+(?:you\s+)?(?:need|have)\s+to\s+do)[ \t*]*:?[ \t*]*$"
)


def request_part(text: str) -> str:
    """The text after the last question heading, or the whole text when it
    has none (an ordinary question is unchanged)."""
    text = text or ""
    headings = list(_QUESTION_HEADING.finditer(text))
    if not headings:
        return text
    questions = text[headings[-1].end():].strip()
    return questions or text
