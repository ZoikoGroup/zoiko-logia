"""Countries implied by country-specific tax terms (30 Oct 2026, experiment).

Reads backend/registry/country_terms.json: forms, returns, schemes, charges and
identifiers, each mapped to one country with the authority that issues it and
the official source it is listed on. "Explain the purpose of the taxable
payments annual report" names no country, but the report is the ATO's. Terms
shared by several countries ("PAYE", "FBT") are listed as ambiguous in the
registry and never map. Whole-word matching; acronyms marked case_sensitive
match only as written ("BAS", not "bas"). Used only by the classifier shadow.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2] / "registry" / "country_terms.json"


@lru_cache(maxsize=1)
def _patterns() -> tuple[tuple[re.Pattern, str, str], ...]:
    data = json.loads(REGISTRY.read_text())
    out = []
    for entry in data["entries"]:
        for phrase in entry["phrases"]:
            # Only an acronym written in capitals is case-sensitive; an entry's
            # spelled-out phrases ("local property tax") match in any case.
            flags = 0 if entry["case_sensitive"] and phrase != phrase.lower() else re.I
            status = (entry.get("phrase_verification") or {}).get(phrase, {}).get("status", "unverified")
            out.append((re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", flags), entry["country"], entry["id"], status))
    return tuple(out)


def implied_terms_with_status(text: str) -> list[tuple[str, str, str, str]]:
    """(country, entry id, matched text, "verified" | "unverified") for each
    registry term in the text, in the order they appear."""
    found = []
    for pattern, country, entry_id, status in _patterns():
        for match in pattern.finditer(text or ""):
            found.append((match.start(), country, entry_id, match.group(0), status))
    return [(country, entry_id, matched, status) for _, country, entry_id, matched, status in sorted(found)]


def implied_terms(text: str) -> list[tuple[str, str, str]]:
    """(country, entry id, matched text) for each registry term in the text,
    in the order they appear."""
    return [(country, entry_id, matched) for country, entry_id, matched, _ in implied_terms_with_status(text)]


def implied_countries(text: str) -> list[str]:
    return list(dict.fromkeys(country for country, _, _ in implied_terms(text)))
