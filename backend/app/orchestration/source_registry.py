"""The Global Source Registry (backend/registry/global_source_registry.json):
loading, subject terms, and the fixed official pages it selects.

Stage S4b (3 Nov 2026). The fixed pages' selection rules moved from
official_evidence.official_pages into the registry's own data: a page is
selected when one of its countries is detected in the text (or one of its
place terms matches) and every one of its "all" patterns matches. With
KRITON_REGISTRY_RETRIEVAL on, official_pages reads them from here, so adding
a country's page is a registry entry, not new matching code. The selection is
the same as the coded rules (tests/test_source_registry.py checks every eval
and gold question). Page-specific excerpting stays in official_evidence.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("kriton.source_registry")
REGISTRY_FILE = Path(__file__).resolve().parents[2] / "registry" / "global_source_registry.json"


def retrieval_enabled() -> bool:
    return os.getenv("KRITON_REGISTRY_RETRIEVAL", "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(REGISTRY_FILE.read_text())
    except Exception:  # noqa: BLE001
        logger.warning("source_registry_load_failed")
        return {}


def entries() -> tuple[dict, ...]:
    return tuple(_data().get("entries") or ())


@lru_cache(maxsize=1)
def _subject_patterns() -> tuple[tuple[str, re.Pattern], ...]:
    return tuple((name, re.compile(pattern, re.I)) for name, pattern in (_data().get("subject_terms") or {}).items())


def subjects_of(text: str) -> list[str]:
    """The registry subjects the text names (VAT, corporation tax, Bank Rate…)."""
    return [name for name, pattern in _subject_patterns() if pattern.search(text or "")]


@lru_cache(maxsize=1)
def _page_rules() -> tuple[tuple[dict, set[str], tuple[re.Pattern, ...], tuple[re.Pattern, ...]], ...]:
    rules = []
    for entry in entries():
        rule = entry.get("selection")
        if entry.get("kind") != "fixed_page" or not rule or entry.get("status") != "in_use":
            continue
        rules.append((entry, set(entry.get("countries") or ()),
                      tuple(re.compile(p, re.I) for p in rule.get("all") or ()),
                      tuple(re.compile(p, re.I) for p in rule.get("place_terms") or ())))
    return tuple(rules)


def registry_pages(question: str) -> list[tuple[str, str]]:
    """The fixed official pages the registry selects for the text, as
    (title, url), in registry order."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    question = question or ""
    markets = set(detect_jurisdictions(question))
    pages = []
    for entry, countries, required, places in _page_rules():
        if not (countries & markets or any(p.search(question) for p in places)):
            continue
        if all(p.search(question) for p in required) and in_force_for(entry, question):
            pages.append((entry["title"], entry["url"]))
    return pages


_TAX_YEAR = re.compile(r"\b((?:19|20)\d{2})\s*(?:to|-|–|/)\s*(?:(?:19|20)?\d{2})\b")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def in_force_for(entry: dict, question: str, *, today=None) -> bool:
    """A page with an effective period (the HMRC employers page for one tax
    year) is read for the tax year the question names, else only while it is
    in force; a page without one is not limited (3 Nov 2026)."""
    from datetime import date
    period = entry.get("period") or {}
    start, end = period.get("effective_from"), period.get("effective_to")
    if not (start and end):
        return True
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    named = _TAX_YEAR.search(question or "")
    if named:
        return start.year == int(named.group(1))
    year = _YEAR.search(question or "")
    if year:
        return start.year <= int(year.group(1)) <= end.year
    day = today or date.today()
    return start <= day <= end


def excerpt_anchor(url: str) -> str | None:
    """The registry's excerpt anchor (a pattern) for a fixed page's URL: the
    passage official_evidence reads starts there."""
    for entry in entries():
        if entry.get("kind") == "fixed_page" and entry.get("url") == url and entry.get("excerpt_anchor"):
            return entry["excerpt_anchor"]
    return None
