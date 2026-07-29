"""Deterministic answers for Kriton UI navigation requests.

Navigation is product metadata, not accounting content. Sending it through
retrieval and an LLM adds latency and can hallucinate a location that is
already known by the application. Keep matching deliberately narrow so a real
accounting question that happens to mention a page still follows the governed
content pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_WRAPPING_QUOTES = "\"'‘’“”"


@dataclass(frozen=True)
class NavigationAnswer:
    destination: str
    path: str
    text: str


_DESTINATIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Saved Answers", "/saved-answers", ("saved answers", "saved answer")),
    ("Ask Kriton", "/ask-kriton", ("ask kriton", "kriton chat")),
    ("My Workspace", "/my-workspace", ("my workspace", "workspace")),
    ("Source Library", "/source-library", ("source library", "sources")),
    ("Escalation Queue", "/escalation-queue", ("escalation queue", "escalations")),
    ("Audit Logs", "/audit-logs", ("audit logs", "audit log")),
)

_NAVIGATION_SHAPE = re.compile(
    r"^\s*(?:(?:where|how)\s+(?:can|do)\s+i\s+|how\s+do\s+i\s+)"
    r"(?:find|open|access|go\s+to|view)\s+(?:my\s+|the\s+)?(?P<destination>.+?)\s*[?.!]*\s*$",
    re.I,
)


def resolve_navigation_answer(query: str) -> NavigationAnswer | None:
    normalized = query.strip().strip(_WRAPPING_QUOTES).strip()
    match = _NAVIGATION_SHAPE.fullmatch(normalized)
    if not match:
        return None

    requested = re.sub(r"\s+", " ", match.group("destination").strip()).lower()
    for destination, path, aliases in _DESTINATIONS:
        if requested in aliases:
            return NavigationAnswer(
                destination=destination,
                path=path,
                text=(
                    f"Open [{destination}]({path}) from the left navigation menu. "
                    f"You can also use that link to go there now."
                ),
            )
    return None
