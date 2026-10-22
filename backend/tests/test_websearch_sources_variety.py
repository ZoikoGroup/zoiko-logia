"""Web results: an abbreviation the page spells out is relevant, and the
same page under several addresses fills only one slot."""
from unittest.mock import AsyncMock

import pytest

from app.orchestration import websearch as w
from app.orchestration.websearch import WebSource


def test_an_abbreviation_spelled_out_on_the_page_is_relevant():
    page = WebSource(title="NATIONAL INTELLECTUAL PROPERTY RIGHTS STRATEGY", url="https://stip.oecd.org/x", snippet="")
    assert w._is_relevant("what is ipr", page)
    ppe = WebSource(title="Property, Plant and Equipment", url="https://www.ifrs.org/x", snippet="")
    assert w._is_relevant("explain ppe", ppe)
    unrelated = WebSource(title="Garment sector employment survey", url="https://www.ilo.org/x", snippet="")
    assert not w._is_relevant("what is ipr", unrelated)


async def test_one_page_under_several_addresses_counts_once(monkeypatch):
    base = "https://www.ifrs.org/issued-standards/list-of-standards/ias-16-property-plant-and-equipment"
    raw = [{"url": u, "title": "IFRS - IAS 16 Property, Plant and Equipment", "content": "IAS 16 property plant equipment"}
           for u in (base, base + "#news", base + "?mod=article_inline", base + "#standard",
                     "http://www.ifrs.org/content/ifrs/home/issued-standards/list-of-standards/ias-16-property-plant-and-equipment.html")]
    raw.append({"url": "https://www.ifrs.org/content/dam/ifrs/publications/html-standards/english/2026/issued/ias16.html",
                "title": "IAS 16 Property, Plant and Equipment (standard)", "content": "IAS 16 property plant equipment"})
    monkeypatch.setattr(w, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(w, "_cache_put", AsyncMock())
    monkeypatch.setattr(w, "_tavily_results", AsyncMock(return_value=raw))
    monkeypatch.setattr(w, "_with_page_extracts", AsyncMock(side_effect=lambda selected, *a, **k: selected))
    results = await w.web_search("what is IAS 16")
    assert len({r.url for r in results}) == len(results) == 2
