"""A message that is pasted material plus a short instruction about it.

"<a long report>\\ncomment on the above" asks for commentary on the user's own
text. Whether the answer needs authoritative (statutory) sources depends on
the instruction, not on the words inside the material: a pasted payroll
summary mentions PAYE and VAT, but "summarise this in 5 points" is not a tax
question. Read on the whole message, those words required official sources
that a comment on pasted text never has, and the answer went to review.

The instruction still decides: "check the VAT treatment above" names VAT
and keeps requiring sources.
"""
from __future__ import annotations

import re

MIN_MATERIAL_CHARS = 400
MAX_INSTRUCTION_CHARS = 200
_INSTRUCTION = re.compile(
    r"^\W*(?:please\s+|can you\s+|could you\s+|now\s+)?"
    r"(?:comments?\s+on|review|summari[sz]e|explain|check|critique|proofread|rewrite|rephrase|"
    r"simplify|shorten|improve|tidy|format|evaluate|assess|analy[sz]e|"
    r"give\s+(?:me\s+)?(?:your\s+)?(?:feedback|comments?|thoughts|views?|opinion)|what\s+do\s+you\s+think)\b",
    re.IGNORECASE,
)
_REFERS_TO_MATERIAL = re.compile(
    r"\b(?:above|below|this|these|that|it|the following|the text|the answer|the report)\b", re.IGNORECASE,
)


def review_instruction(query: str) -> str | None:
    """The instruction line when the message is pasted material plus a short
    instruction about it (last line, or first line), else None."""
    text = (query or "").strip()
    head, separator, material = text.partition(" Context: ")
    if (separator and len(material) >= MIN_MATERIAL_CHARS and len(head) <= MAX_INSTRUCTION_CHARS
            and re.match(r"^(?:rewrite|rephrase|proofread|simplify|shorten|summari[sz]e|explain\s+this\s+text)\b", head, re.I)
            and _REFERS_TO_MATERIAL.search(head)):
        return head.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return None
    for instruction, rest in ((lines[-1], lines[:-1]), (lines[0], lines[1:])):
        if (len(instruction) <= MAX_INSTRUCTION_CHARS
                and len("\n".join(rest)) >= MIN_MATERIAL_CHARS
                and _INSTRUCTION.search(instruction)
                and _REFERS_TO_MATERIAL.search(instruction)):
            return instruction
    return None
