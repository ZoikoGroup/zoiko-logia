"""Agent mode: the existing fixed official pages for the parts the Task
Contract says need an official figure or rule (Stage C-2b).

In agent mode nothing was pre-fetched: an official page (IRAS for Singapore
GST, HMRC's "When to register for VAT", CBIC for Indian GST registration) was
read only when the model's own search happened to contain the words that
select it. The standard path reads them on every such question
(websearch.web_search_each). Here they are read up front when, and only when,
the contract records an official part those pages cover. No page, connector
or source is added: the pages are official_evidence.official_pages and the
HMRC registration page, exactly as the standard path reads them.
"""
from __future__ import annotations

import asyncio
import dataclasses
import re


def official_prefetch_plan(contract) -> tuple[list[str], bool]:
    """(texts to select official pages by, whether to read HMRC's VAT
    registration page): from the contract's official parts only."""
    if contract is None:
        return [], False
    official = [r for r in getattr(contract, "retrieval", []) or [] if r.needs_official]
    texts = [" ".join([r.part, *(key.replace("_", " ").lower() for key in r.jurisdictions)])
             for r in official if r.official_pages]
    return list(dict.fromkeys(texts)), any(r.connector == "hmrc_vat_registration" for r in official)


async def official_prefetch(contract) -> list:
    """The pages, merged as web_search_each merges them (one source per URL,
    each distinct passage kept). [] when the contract needs none."""
    from app.orchestration.official_evidence import official_sources
    from app.orchestration.websearch import _uk_vat_rules_source
    texts, hmrc_registration = official_prefetch_plan(contract)
    reads = [official_sources(text) for text in texts]
    if hmrc_registration:
        reads.insert(0, _uk_vat_rules_source())
    if not reads:
        return []
    merged: list = []
    positions: dict[str, int] = {}
    for group in await asyncio.gather(*reads, return_exceptions=True):
        if isinstance(group, BaseException):
            continue
        for source in group or []:
            key = source.url or source.source_id or source.title
            if key not in positions:
                positions[key] = len(merged)
                merged.append(source)
            elif source.snippet and source.snippet not in (merged[positions[key]].snippet or ""):
                previous = merged[positions[key]]
                merged[positions[key]] = dataclasses.replace(previous, snippet="\n\n".join(
                    snippet for snippet in (previous.snippet, source.snippet) if snippet))
    return merged


# HMRC's interest rates are set relative to Bank Rate ("Bank Rate plus 4%").
# In agent mode Bank Rate was pre-fetched only for "bank/base/policy rate"
# wording, and the agent has no Bank of England tool: "What interest rate does
# HMRC charge on late VAT payments?" read the rule but could not state the
# current rate (30 Oct 2026).
_INTEREST_ON_TAX = re.compile(
    r"\b(?:late[- ]payment|repayment|overdue|under-?paid|under-?payment|unpaid)\b[^.?!]{0,60}\binterest\b"
    r"|\binterest\b[^.?!]{0,60}\b(?:late|overdue|under-?paid|under-?payment|unpaid|repay\w*)\b", re.I)
_TAX_AUTHORITY_UK = re.compile(r"\b(?:hmrc|vat|paye|corporation\s+tax|self\s+assessment|income\s+tax)\b", re.I)


def bank_rate_prefetch(contract) -> bool:
    """Whether the contract records a UK official rate HMRC sets relative to
    Bank Rate, so agent mode should have Bank Rate before composing."""
    if contract is None:
        return False
    return any(r.needs_official and r.fact_type == "rate" and "UK" in r.jurisdictions
               and _INTEREST_ON_TAX.search(r.part) and _TAX_AUTHORITY_UK.search(r.part)
               for r in getattr(contract, "retrieval", []) or [])
