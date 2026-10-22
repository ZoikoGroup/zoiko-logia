"""Fit explicitly identified context sections, never arbitrary prompt text."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ContextSection:
    start: int
    end: int
    render: Callable[[float], str]


def pack_context(prompt: str, sections: list[ContextSection], estimate: Callable[[str], int],
                 max_input_tokens: int) -> tuple[str, int, int]:
    before = estimate(prompt)
    if max_input_tokens <= 0 or before <= max_input_tokens:
        return prompt, before, before
    ordered = sorted(sections, key=lambda item: item.start)
    previous = 0
    for section in ordered:
        if not previous <= section.start <= section.end <= len(prompt):
            raise ValueError('Invalid context section boundaries')
        previous = section.end
    candidate = prompt
    for factor in (0.75, 0.5, 0.35, 0.2, 0.1, 0.05, 0.0):
        parts, previous = [], 0
        for section in ordered:
            parts.extend((prompt[previous:section.start], section.render(factor)))
            previous = section.end
        parts.append(prompt[previous:])
        candidate = ''.join(parts)
        if estimate(candidate) <= max_input_tokens:
            break
    # If fixed instructions or the user's query alone are too large, retain
    # them intact. The gateway must still reject rather than silently change
    # the request or transmit an oversized payload.
    return candidate, before, estimate(candidate)


def governed_context(query: str, passages, references, char_budget: int) -> str:
    from app.orchestration.websearch import _focused_excerpt
    header = (
        '\n\n=== Governed registered evidence ===\n'
        'Use these approved passages for material professional claims, citing their exact [REF-N] IDs. '
        'Never cite INTERNAL-GOV text or present it as displayable evidence. '
        'If they conflict or do not support the requested conclusion, say so.\n'
    )
    if not passages:
        return ''
    allowance = max(0, char_budget // len(passages))
    blocks = []
    for passage_id, locator, content in passages:
        excerpt = _focused_excerpt(content, query, allowance) if allowance else ''
        if len(content) > allowance:
            excerpt += '\n[Source shortened; omitted content is not evidence for this answer.]'
        blocks.append(f"[{references.get(passage_id, 'INTERNAL-GOV')}] {locator} (passage_id={passage_id})\n{excerpt}")
    return header + '\n\n'.join(blocks)
