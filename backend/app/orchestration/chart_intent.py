"""Conservative guard for automatic charts, not model-selected charts."""
import re


def allows_automatic_chart(query: str) -> bool:
    query = re.sub(r'\bif (?:chart )?rendering is unavailable,? say so explicitly[.!]?', '', query, flags=re.I)
    if re.search(r"\b(?:only|just)\s+(?:(?:a|any|the)\s+)?(?:tables?|text)\b|\b(?:tables?|text)\s+only\b", query, re.I):
        return False
    # Conditions require a decision based on retrieved evidence. Keyword-based
    # reminders and fallbacks cannot resolve them and must defer to the agent.
    if re.search(r"\b(if|unless|otherwise|only when|provided that)\b", query, re.I):
        return False
    return not re.search(
        r"\b(no|without|skip|omit)\s+(?:a\s+|any\s+|the\s+)?(?:charts?|graphs?|plots?)\b"
        r"|\b(?:do not|don't|don’t|never)\s+(?:(?:draw|show|make|include|create)\s+(?:(?:a|any|the)\s+)?)?"
        r"(?:charts?|graphs?|plots?)\b",
        query, re.I,
    )
