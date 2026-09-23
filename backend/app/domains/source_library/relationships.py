"""Validated source relationship vocabulary used by the source registry."""

RELATIONSHIP_TYPES = frozenset({
    "supersedes", "clarifies", "references", "complements", "conflicts", "historical_only",
})
