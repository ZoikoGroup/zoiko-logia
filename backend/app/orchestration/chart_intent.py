"""Conservative guard for automatic charts, not model-selected charts."""
import re


def allows_automatic_chart(query: str) -> bool:
    # Conditions require a decision based on retrieved evidence. Keyword-based
    # reminders and fallbacks cannot resolve them and must defer to the agent.
    if re.search(r"\b(if|unless|otherwise|only when|provided that)\b", query, re.I):
        return False
    return not re.search(
        r"\b(no|without|skip|omit)\s+(?:a\s+|any\s+|the\s+)?(?:charts?|graphs?|plots?)\b"
        r"|\b(?:do not|don't|don’t|never)\s+(?:(?:draw|show|make|include|create)\s+(?:a\s+)?)?"
        r"(?:chart|graph|plot)\b",
        query, re.I,
    )
