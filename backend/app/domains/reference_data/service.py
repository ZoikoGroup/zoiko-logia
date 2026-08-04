"""
Reference-data service layer — caching + audit trail for external reference
sources. Everything (Kriton's retrieval layer included) goes through this
module rather than calling adapters/treasury_adapter.py directly, so every
external call is logged per the audit doctrine: never answer
ungoverned/unlogged.
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.reference_data.adapters.treasury_adapter import get_exchange_rates
from app.domains.reference_data.adapters.payroll_tax_adapter import get_payroll_tax_rates
from app.domains.reference_data.adapters.census_adapter import get_state_income_poverty
from app.domains.reference_data.adapters.bls_adapter import get_cpi_series, CPI_U_SERIES_ID
from app.domains.reference_data.adapters.bea_adapter import (
    get_gdp_data, GDP_TABLE_NAME, REAL_GDP_CHANGE_TABLE_NAME,
)
from app.domains.reference_data.adapters.fred_adapter import get_series_observations
from app.domains.reference_data.adapters.govinfo_adapter import get_cfr_section
from app.domains.reference_data.adapters.federal_register_adapter import get_document as get_federal_register_document
from app.domains.reference_data.adapters.ecfr_adapter import get_cfr_section as get_ecfr_section
from app.domains.reference_data.adapters.congress_adapter import get_bill as get_congress_bill
from app.domains.reference_data.adapters.professional_search_adapter import search_tavily, search_serpapi
from app.domains.reference_data.models import ReferenceSourceBundle

T = TypeVar("T")


async def _retry_external(call: Callable[[], Awaitable[T]], *, attempts: int = 2) -> T:
    """Retry transient transport/server failures at the governed boundary."""
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return await call()
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            transient = any(token in message for token in (
                "timed out", "timeout", "request failed", "getaddrinfo",
                "connection", "returned 500", "returned 502", "returned 503", "returned 504",
            ))
            if not transient or attempt + 1 >= attempts:
                raise
            await asyncio.sleep(0.25 * (attempt + 1))
    assert last_error is not None
    raise last_error

# The governed Source row Kriton's retrieval layer cites for this data (see
# scripts/seed_dev_user.py) — an explicit fixed id rather than the DB's uuid
# default, so it can be referenced here without an extra query per request.
TREASURY_GOVERNED_SOURCE_ID = "src-treasury-fiscal-data-exchange-rates"
PAYROLL_TAX_GOVERNED_SOURCE_ID = "src-payroll-tax-api-rate-lookup"
CENSUS_GOVERNED_SOURCE_ID = "src-census-acs-income-poverty"
BLS_CPI_GOVERNED_SOURCE_ID = "src-bls-cpi-inflation"
BEA_GDP_GOVERNED_SOURCE_ID = "src-bea-nipa-gdp"
FRED_INTEREST_RATES_GOVERNED_SOURCE_ID = "src-fred-interest-rates"
CFR_TITLE26_GOVERNED_SOURCE_ID = "src-govinfo-cfr-title26"
FEDERAL_REGISTER_GOVERNED_SOURCE_ID = "src-federal-register-lookup"
ECFR_TITLE26_GOVERNED_SOURCE_ID = "src-ecfr-title26"
CONGRESS_GOVERNED_SOURCE_ID = "src-congress-gov-bill-lookup"
TAVILY_GOVERNED_SOURCE_ID = "src-tavily-authority-search"
SERPAPI_GOVERNED_SOURCE_ID = "src-serpapi-authority-search"

# Single source of truth for the node_id prefixes orchestration/service.py
# checks to guarantee an injected live-data chunk survives the cross-encoder
# reranker (which ranks on prose similarity alone and can otherwise drop a
# terse rate-listing chunk in favor of a document that merely discusses the
# same topic in prose).
TREASURY_NODE_PREFIX = "treasury-live-"
PAYROLL_TAX_NODE_PREFIX = "payroll-tax-live-"
CENSUS_NODE_PREFIX = "census-live-"
BLS_CPI_NODE_PREFIX = "bls-cpi-live-"
BEA_GDP_NODE_PREFIX = "bea-gdp-live-"
FRED_NODE_PREFIX = "fred-rates-live-"
CFR_NODE_PREFIX = "govinfo-cfr-live-"
FEDERAL_REGISTER_NODE_PREFIX = "fedreg-live-"
ECFR_NODE_PREFIX = "ecfr-live-"
CONGRESS_NODE_PREFIX = "congress-live-"
PROFESSIONAL_SEARCH_NODE_PREFIX = "professional-search-live-"


async def get_professional_search_bundle(
    db: AsyncSession, *, query: str, tenant_id: str, actor_id: str | None,
) -> tuple[ReferenceSourceBundle, str]:
    """Use Tavily first and SerpAPI only when Tavily yields no usable page."""
    provider = "tavily"
    try:
        results = await _retry_external(lambda: search_tavily(query))
        status = "200"
    except Exception as exc:
        results, status = [], f"error: {exc}"
    await record_event_async(
        db, tenant_id=tenant_id, event_name="external_reference_data_call",
        emitting_service="reference_data", subject_type="external_source",
        subject_id="tavily.authority_search", actor_id=actor_id,
        payload={"params": {"allowed_domain_search": True}, "status": status, "record_count": len(results)},
    )
    if not results:
        provider = "serpapi"
        try:
            results = await _retry_external(lambda: search_serpapi(query))
            status = "200"
        except Exception as exc:
            results, status = [], f"error: {exc}"
        await record_event_async(
            db, tenant_id=tenant_id, event_name="external_reference_data_call",
            emitting_service="reference_data", subject_type="external_source",
            subject_id="serpapi.authority_search", actor_id=actor_id,
            payload={"params": {"allowed_domain_search": True}, "status": status, "record_count": len(results)},
        )
    return ReferenceSourceBundle(
        source_name=f"{provider.title()} — Approved Authority Search",
        source_url=results[0]["url"] if results else "",
        data=results, licence_status="public_web",
    ), provider


def to_professional_search_chunks(bundle: ReferenceSourceBundle, *, source_id: str) -> list[dict]:
    chunks = []
    for item in bundle.data[:3]:
        content = item.get("content", "")[:_MAX_CONTEXT_CHARS]
        if not content:
            continue
        chunks.append({
            "text": content,
            "metadata": {"source_id": source_id, "title": item.get("title", bundle.source_name),
                         "version": bundle.retrieved_at.isoformat(), "jurisdiction": "US",
                         "file_path": item.get("url"), "source_type": "live_api"},
            "score": 0.45,
            "node_id": f"{PROFESSIONAL_SEARCH_NODE_PREFIX}{uuid4().hex[:8]}",
        })
    return chunks

# A small lookup table, not an NLP system — only currencies actually present
# in Treasury's Rates of Exchange dataset (verified against the live API;
# notably this dataset does NOT cover several major freely-convertible
# currencies — no GBP, CHF, SGD, SEK, NOK, ZAR, MXN, or NZD entries exist at
# all — so those aren't mapped here; a query about one of them falls
# through to the full-list fetch below, which correctly contains no
# fabricated row for them).
_CURRENCY_KEYWORDS: dict[str, str] = {
    "euro": "Euro Zone-Euro",
    "yen": "Japan-Yen",
    "yuan": "China-Renminbi",
    "renminbi": "China-Renminbi",
    "canadian dollar": "Canada-Dollar",
    "australian dollar": "Australia-Dollar",
    "indian rupee": "India-Rupee",
    "korean won": "Korea-Won",
    "brazilian real": "Brazil-Real",
    "hong kong dollar": "Hong Kong-Dollar",
    "danish krone": "Denmark-Krone",
    "icelandic krona": "Iceland-Krona",
}

# Keeps our injected chunk from consuming rag/context_fit.py's whole
# max_chars=8000 budget by itself — that function hard-breaks (drops the
# rest of the context entirely, not just this chunk) the moment one chunk
# would exceed the budget, so leaving headroom for other real document
# chunks matters.
_MAX_CONTEXT_CHARS = 3000

# Slow-moving reference data (daily Treasury rates), not live market data —
# a 6 hour cache avoids re-fetching on every request without going stale
# within a business day.
_CACHE_TTL_SECONDS = 6 * 60 * 60

# In-memory only: this backend runs as a single process (no Redis in the
# stack today — see docker-compose.yml). A cache miss just means one extra
# upstream call after a restart, which is an acceptable tradeoff for
# reference data this size.
_cache: dict[tuple[str | None, str], tuple[ReferenceSourceBundle, float]] = {}


async def get_exchange_rate_bundle(
    db: AsyncSession,
    *,
    currency: str | None,
    since: str,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = (currency, since)
    now = time.monotonic()
    cached = _cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_call(
            db, tenant_id=tenant_id, actor_id=actor_id, currency=currency, since=since,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_exchange_rates(currency=currency, since=since))
    except Exception as exc:
        await _log_call(
            db, tenant_id=tenant_id, actor_id=actor_id, currency=currency, since=since,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="US Treasury Fiscal Data",
        source_url=f"{get_settings().TREASURY_FISCAL_DATA_BASE_URL}/accounting/od/rates_of_exchange",
        data=data,
    )
    _cache[cache_key] = (bundle, now + _CACHE_TTL_SECONDS)

    await _log_call(
        db, tenant_id=tenant_id, actor_id=actor_id, currency=currency, since=since,
        status="200", record_count=len(data),
    )
    return bundle


async def _log_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    currency: str | None,
    since: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="treasury_fiscal_data.rates_of_exchange",
        actor_id=actor_id,
        payload={
            "params": {"currency": currency, "since": since},
            "status": status,
            "record_count": record_count,
        },
    )


def match_currency_keyword(query: str) -> str | None:
    """Returns the exact Treasury country_currency_desc for a currency named
    in the query, or None if none of the known keywords match.

    None does NOT mean "no exchange-rate question was asked" — that
    decision belongs to infer_category. It means the query didn't say which
    currency. orchestration/service.py's caller treats that the same way
    match_work_state's callers already treat a missing state: skip the live
    fetch rather than guess. get_exchange_rate_bundle(currency=None) still
    works and still returns every tracked country in one bundle — useful if
    a future caller genuinely wants the full list (e.g. "what currencies
    does Treasury track?") — but nothing today calls it that way, precisely
    because presenting one arbitrary row out of that bundle as *the* answer
    to an ambiguous single-currency question is the bug this docstring used
    to sanction."""
    lowered = query.lower()
    for keyword, description in _CURRENCY_KEYWORDS.items():
        if keyword in lowered:
            return description
    return None


def to_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats a ReferenceSourceBundle into a dict shaped exactly like a real
    RAG chunk (text/metadata/score/node_id — see app/domains/rag/reranker.py
    and app/domains/rag/context_fit.py), so it flows through Kriton's
    retrieval/reranking/citation pipeline identically to a real vector hit."""
    seen: set[str] = set()
    lines: list[str] = []
    total_chars = 0
    for row in bundle.data:
        name = row.get("country_currency_desc")
        if not name or name in seen:
            continue
        seen.add(name)
        line = f"{name}: {row.get('exchange_rate')} (as of {row.get('record_date')})"
        if total_chars + len(line) + 1 > _MAX_CONTEXT_CHARS:
            break
        lines.append(line)
        total_chars += len(line) + 1

    text = (
        "US Treasury Fiscal Data — foreign currency exchange rates relative to "
        "1 USD, as published quarterly by the U.S. Bureau of the Fiscal Service:\n"
        + "\n".join(lines)
    )

    return {
        "text": text,
        "metadata": {
            "source_id": source_id,
            # Matches the governed Source's own title exactly (see
            # scripts/seed_dev_user.py) — bundle.source_name is the shorter
            # generic label used for the raw adapter's own audit logging.
            "title": "US Treasury Fiscal Data — Rates of Exchange",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{TREASURY_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── PayrollTax API (payrolltaxapi.com) ───────────────────────────────────
# Keyed, metered (free tier: 1,000 req/month, 20/min) — unlike Treasury,
# caching here matters for quota conservation, not just freshness.

# Fixed, well-known data (all 50 states + DC) — not an NLP system. Full
# names are matched as lowercase substrings; bare 2-letter codes are matched
# separately below via a word-boundary regex against the ORIGINAL casing,
# since lowercasing first would make common English words ("in", "or", "me",
# "hi", "ok", "pa", "de", "ma", "id", "al") false-positive as state codes.
_US_STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}
_US_STATE_CODES: frozenset[str] = frozenset(_US_STATE_NAMES.values())
_STATE_CODE_PATTERN = re.compile(r"\b([A-Z]{2})\b")


def match_work_state(query: str) -> str | None:
    """Returns a 2-letter USPS state code if the query names a US state, or
    None if it doesn't. Unlike match_currency_keyword, callers MUST treat
    None as "do not call the live API" — workState is a required identity
    param (no "fetch everything" fallback is possible for a per-state rate
    lookup), and defaulting/guessing a state would be fabricated data."""
    lowered = query.lower()
    for name, code in _US_STATE_NAMES.items():
        if name in lowered:
            return code
    for match in _STATE_CODE_PATTERN.finditer(query):
        if match.group(1) in _US_STATE_CODES:
            return match.group(1)
    return None


_ISO_DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def extract_pay_date(query: str) -> str:
    """Only an explicit YYYY-MM-DD in the query is honored — no natural-
    language date parsing library (none in requirements.txt, none should be
    added just for this). Anything else, including "today" or no date at
    all, falls back to today's UTC date. Unlike match_work_state, defaulting
    here is safe: a wrong/defaulted state answers a different jurisdiction
    entirely, while a wrong/defaulted date just answers "today" — usually
    what was implicitly meant anyway."""
    match = _ISO_DATE_PATTERN.search(query)
    if match:
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
            return match.group(1)
        except ValueError:
            pass  # malformed date-shaped text (e.g. "2026-13-40") — fall through
    return datetime.now(timezone.utc).date().isoformat()


# Quota conservation, not freshness, drives this number — 1,000 req/month is
# easy to exhaust on a short cache during any real testing/demo burst, and
# payroll tax rates are set at fixed calendar boundaries (new year,
# occasional mid-year state law changes), never intraday-volatile.
_PAYROLL_TAX_CACHE_TTL_SECONDS = 24 * 60 * 60

_payroll_cache: dict[tuple[str, str], tuple[ReferenceSourceBundle, float]] = {}


async def get_payroll_tax_bundle(
    db: AsyncSession,
    *,
    work_state: str,
    pay_date: str,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = (work_state, pay_date)
    now = time.monotonic()
    cached = _payroll_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_payroll_call(
            db, tenant_id=tenant_id, actor_id=actor_id, work_state=work_state, pay_date=pay_date,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_payroll_tax_rates(work_state=work_state, pay_date=pay_date))
    except Exception as exc:
        await _log_payroll_call(
            db, tenant_id=tenant_id, actor_id=actor_id, work_state=work_state, pay_date=pay_date,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="PayrollTax API",
        source_url=f"{get_settings().PAYROLL_TAX_API_BASE_URL}/rates/lookup",
        data=[data],
        # The model's default ("public_no_auth") is wrong here — this is a
        # keyed, licensed commercial data provider, not a public no-auth feed.
        licence_status="licensed_api_key",
    )
    _payroll_cache[cache_key] = (bundle, now + _PAYROLL_TAX_CACHE_TTL_SECONDS)

    await _log_payroll_call(
        db, tenant_id=tenant_id, actor_id=actor_id, work_state=work_state, pay_date=pay_date,
        status="200", record_count=1,
    )
    return bundle


async def _log_payroll_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    work_state: str,
    pay_date: str,
    status: str,
    record_count: int,
) -> None:
    # Never include the API key or request headers here — this payload is
    # stored verbatim in the audit ledger with no redaction layer.
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="payroll_tax_api.rates_lookup",
        actor_id=actor_id,
        payload={
            "params": {"work_state": work_state, "pay_date": pay_date},
            "status": status,
            "record_count": record_count,
        },
    )


def to_payroll_tax_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats a ReferenceSourceBundle wrapping a PayrollTax API response
    into a dict shaped like a real RAG chunk. The `taxes` array's entries are
    heterogeneous and only partially documented (flat rate+wage_base vs.
    rate_structure+brackets; SUTA/SDI/local entries may have other shapes
    entirely) — this iterates whatever keys are actually present per entry
    rather than hardcoding an assumed shape, so an undocumented shape
    degrades to an uglier line instead of crashing or silently dropping data."""
    payload = bundle.data[0] if bundle.data else {}
    pay_date = payload.get("pay_date", "unknown date")
    work_state = payload.get("work_state", "unknown state")

    lines: list[str] = []
    header = f"PayrollTax API — payroll tax rates for {work_state}, pay date {pay_date}:"
    total_chars = len(header) + 1

    for entry in payload.get("taxes", []):
        if not isinstance(entry, dict):
            continue
        label = entry.get("name") or entry.get("tax_type_code") or "Unknown tax"
        parts = [f"{k}={v}" for k, v in entry.items() if k not in ("name", "tax_type_code")]
        line = f"- {label}: {', '.join(parts)}" if parts else f"- {label}"
        if total_chars + len(line) + 1 > _MAX_CONTEXT_CHARS:
            break
        lines.append(line)
        total_chars += len(line) + 1

    text = header + "\n" + "\n".join(lines)

    return {
        "text": text,
        "metadata": {
            "source_id": source_id,
            "title": "PayrollTax API — Rate Lookup",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": work_state if work_state in _US_STATE_CODES else "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{PAYROLL_TAX_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── US Census Bureau ACS (income & poverty by state) ────────────────────
# Free with registration, keyed via query param (see census_adapter.py).
# Quota-light in practice (ACS is a low-cardinality dataset — 50 states +
# DC, one row each), so no aggressive caching pressure like PayrollTax's
# free tier, but still cached to avoid re-fetching identical state/year
# lookups within the TTL window.

# Census's API takes numeric FIPS state codes, not the USPS 2-letter codes
# PayrollTax uses — a different identifier space entirely. Full names are
# matched the same way as _US_STATE_NAMES above; bare 2-letter codes are
# cross-referenced through that same map rather than duplicating a second
# name list.
_US_STATE_FIPS: dict[str, str] = {
    "alabama": "01", "alaska": "02", "arizona": "04", "arkansas": "05", "california": "06",
    "colorado": "08", "connecticut": "09", "delaware": "10", "florida": "12", "georgia": "13",
    "hawaii": "15", "idaho": "16", "illinois": "17", "indiana": "18", "iowa": "19",
    "kansas": "20", "kentucky": "21", "louisiana": "22", "maine": "23", "maryland": "24",
    "massachusetts": "25", "michigan": "26", "minnesota": "27", "mississippi": "28",
    "missouri": "29", "montana": "30", "nebraska": "31", "nevada": "32",
    "new hampshire": "33", "new jersey": "34", "new mexico": "35", "new york": "36",
    "north carolina": "37", "north dakota": "38", "ohio": "39", "oklahoma": "40",
    "oregon": "41", "pennsylvania": "42", "rhode island": "44", "south carolina": "45",
    "south dakota": "46", "tennessee": "47", "texas": "48", "utah": "49", "vermont": "50",
    "virginia": "51", "washington": "53", "west virginia": "54", "wisconsin": "55",
    "wyoming": "56", "district of columbia": "11",
}
# USPS code -> FIPS, derived from the two name maps above sharing the same
# state set (_US_STATE_NAMES from the PayrollTax section, defined earlier
# in this file) rather than hand-maintaining a third parallel list.
_US_STATE_CODE_TO_FIPS: dict[str, str] = {
    code: _US_STATE_FIPS[name] for name, code in _US_STATE_NAMES.items() if name in _US_STATE_FIPS
}


def match_state_fips(query: str) -> str | None:
    """Returns a 2-digit Census FIPS state code if the query names a US
    state, or None if it doesn't — same fail-closed contract as
    match_work_state (no state named -> skip the live fetch, never guess)."""
    lowered = query.lower()
    for name, fips in _US_STATE_FIPS.items():
        if name in lowered:
            return fips
    for match in _STATE_CODE_PATTERN.finditer(query):
        if match.group(1) in _US_STATE_CODE_TO_FIPS:
            return _US_STATE_CODE_TO_FIPS[match.group(1)]
    return None


_CENSUS_CACHE_TTL_SECONDS = 24 * 60 * 60  # ACS 1-year estimates update annually
_ACS_YEAR = "2024"  # most recent 1-year ACS release confirmed available

_census_cache: dict[tuple[str, str], tuple[ReferenceSourceBundle, float]] = {}


async def get_census_income_poverty_bundle(
    db: AsyncSession,
    *,
    state_fips: str,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = (state_fips, _ACS_YEAR)
    now = time.monotonic()
    cached = _census_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_census_call(
            db, tenant_id=tenant_id, actor_id=actor_id, state_fips=state_fips,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_state_income_poverty(state_fips=state_fips, year=_ACS_YEAR))
    except Exception as exc:
        await _log_census_call(
            db, tenant_id=tenant_id, actor_id=actor_id, state_fips=state_fips,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="US Census Bureau (ACS)",
        source_url=f"{get_settings().CENSUS_API_BASE_URL}/{_ACS_YEAR}/acs/acs1",
        data=[data],
        licence_status="public_no_auth",
    )
    _census_cache[cache_key] = (bundle, now + _CENSUS_CACHE_TTL_SECONDS)

    await _log_census_call(
        db, tenant_id=tenant_id, actor_id=actor_id, state_fips=state_fips,
        status="200", record_count=1,
    )
    return bundle


async def _log_census_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    state_fips: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="census_acs.income_poverty",
        actor_id=actor_id,
        payload={
            "params": {"state_fips": state_fips, "year": _ACS_YEAR},
            "status": status,
            "record_count": record_count,
        },
    )


def to_census_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats a Census ACS income/poverty bundle into a dict shaped like a
    real RAG chunk. The raw response is a flat dict of Census variable
    codes (B19013_001E, etc.) — translated into plain-English labels here
    since those codes mean nothing without the Census data dictionary."""
    payload = bundle.data[0] if bundle.data else {}
    state_name = payload.get("NAME", "unknown state")
    median_income = payload.get("B19013_001E")
    poverty_count = payload.get("B17001_002E")
    poverty_universe = payload.get("B17001_001E")

    lines = [f"US Census Bureau American Community Survey (1-year estimates, {_ACS_YEAR}) — {state_name}:"]
    if median_income not in (None, "-666666666"):  # Census's null-value sentinel
        lines.append(f"- Median household income (past 12 months): ${int(median_income):,}")
    if poverty_count not in (None, "-666666666") and poverty_universe not in (None, "-666666666", "0"):
        rate = int(poverty_count) / int(poverty_universe) * 100
        lines.append(
            f"- Poverty rate: {rate:.1f}% ({int(poverty_count):,} of {int(poverty_universe):,} "
            "people for whom poverty status is determined)"
        )

    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "US Census Bureau — Income & Poverty by State (ACS)",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": state_name,
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{CENSUS_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── US Bureau of Labor Statistics (CPI / inflation) ──────────────────────
# Free API (registration raises rate limits but isn't required — see
# bls_adapter.py). National data, no state/entity extraction needed, unlike
# PayrollTax/Census — always fetches the same CPI-U series when the
# category matches.
_INFLATION_KEYWORDS = ("inflation", "consumer price index", "cpi", "cost of living")


def is_inflation_query(query: str) -> bool:
    """"economic-data" covers both Census income/poverty (state-specific)
    and BLS CPI (national, no state) — this distinguishes the two so a
    plain "median income in California" question doesn't also get
    irrelevant CPI data injected alongside the actually-relevant Census
    chunk (both would survive reranking via node-prefix reinstatement,
    which is exactly why the noise would be guaranteed to show up, not
    just a possibility)."""
    lowered = query.lower()
    return any(keyword in lowered for keyword in _INFLATION_KEYWORDS)


_BLS_CACHE_TTL_SECONDS = 24 * 60 * 60  # CPI-U publishes monthly, once a day is plenty
_bls_cache: dict[str, tuple[ReferenceSourceBundle, float]] = {}


async def get_cpi_bundle(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    current_year = datetime.now(timezone.utc).year
    # 3 calendar years of monthly data — enough to always have a same-month
    # year-ago comparison for a proper 12-month inflation rate, regardless
    # of which month it currently is.
    start_year, end_year = str(current_year - 2), str(current_year)
    cache_key = f"{start_year}-{end_year}"
    now = time.monotonic()
    cached = _bls_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_bls_call(
            db, tenant_id=tenant_id, actor_id=actor_id, start_year=start_year, end_year=end_year,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_cpi_series(start_year=start_year, end_year=end_year))
    except Exception as exc:
        await _log_bls_call(
            db, tenant_id=tenant_id, actor_id=actor_id, start_year=start_year, end_year=end_year,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="US Bureau of Labor Statistics (CPI-U)",
        source_url=f"{get_settings().BLS_API_BASE_URL}{_timeseries_series_url(CPI_U_SERIES_ID)}",
        data=data,
        licence_status="public_no_auth",
    )
    _bls_cache[cache_key] = (bundle, now + _BLS_CACHE_TTL_SECONDS)

    await _log_bls_call(
        db, tenant_id=tenant_id, actor_id=actor_id, start_year=start_year, end_year=end_year,
        status="200", record_count=len(data),
    )
    return bundle


def _timeseries_series_url(series_id: str) -> str:
    return f"/timeseries/data/{series_id}"


async def _log_bls_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    start_year: str,
    end_year: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="bls.cpi_u",
        actor_id=actor_id,
        payload={
            "params": {"series_id": CPI_U_SERIES_ID, "start_year": start_year, "end_year": end_year},
            "status": status,
            "record_count": record_count,
        },
    )


def to_cpi_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats BLS CPI-U data into a RAG-shaped chunk. Computes a real,
    transparent 12-month (year-over-year) inflation rate from two actual
    published index values — same pattern as the Census poverty-rate
    calculation (a derived figure with an inspectable source), not an
    invented metric."""
    entries = [e for e in bundle.data if e.get("value") not in (None, "-")]
    # BLS returns most-recent-first; find the latest entry and the entry
    # exactly 12 months earlier (same period, prior year) for a same-month
    # year-over-year comparison rather than an arbitrary two points.
    latest = entries[0] if entries else None
    yoy_rate = None
    yoy_prior = None
    if latest:
        prior_year = str(int(latest["year"]) - 1)
        yoy_prior = next(
            (e for e in entries if e["year"] == prior_year and e["period"] == latest["period"]), None
        )
        if yoy_prior:
            latest_val, prior_val = float(latest["value"]), float(yoy_prior["value"])
            yoy_rate = (latest_val - prior_val) / prior_val * 100

    lines = ["US Bureau of Labor Statistics — Consumer Price Index for All Urban Consumers (CPI-U, US city average, not seasonally adjusted):"]
    if latest:
        lines.append(f"- Latest index value: {latest['value']} ({latest['periodName']} {latest['year']})")
    if yoy_rate is not None:
        lines.append(
            f"- 12-month (year-over-year) inflation rate: {yoy_rate:.1f}% "
            f"(from {yoy_prior['value']} in {yoy_prior['periodName']} {yoy_prior['year']} "
            f"to {latest['value']} in {latest['periodName']} {latest['year']})"
        )
    lines.append("Recent monthly index values:")
    for e in entries[:6]:
        lines.append(f"  {e['periodName']} {e['year']}: {e['value']}")

    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "US Bureau of Labor Statistics — CPI-U (Inflation)",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{BLS_CPI_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── US Bureau of Economic Analysis (GDP / NIPA) ──────────────────────────
# Free with registration, keyed via query param like Census. National data,
# no state/entity extraction needed — same posture as BLS CPI above, always
# fetches the same NIPA GDP table when the category/keyword match.
_GDP_KEYWORDS = ("gdp", "gross domestic product")


def is_gdp_query(query: str) -> bool:
    """"economic-data" also covers Census income/poverty and BLS CPI — this
    distinguishes GDP questions from those so an unrelated income/inflation
    question doesn't also get an irrelevant GDP chunk injected (same
    precedent as is_inflation_query)."""
    lowered = query.lower()
    return any(keyword in lowered for keyword in _GDP_KEYWORDS)


# NIPA Table 1.1.5's top-level demand-side breakdown of GDP — deliberately
# excludes the table's indented sub-components (Durable/Nondurable goods,
# Structures/Equipment, Federal/State-and-local, etc.) to keep the injected
# chunk to the "core NIPA aggregates" scope rather than the full ~26-row
# table. Each string is unique among the table's LineDescription values, so
# an exact-match filter (not a LineNumber position, which could shift on a
# BEA table revision) reliably picks out just these five rows.
_GDP_LINE_DESCRIPTIONS = (
    "Gross domestic product",
    "Personal consumption expenditures",
    "Gross private domestic investment",
    "Net exports of goods and services",
    "Government consumption expenditures and gross investment",
)

_GDP_CACHE_TTL_SECONDS = 24 * 60 * 60  # NIPA GDP publishes quarterly, once a day is plenty
_gdp_cache: dict[str, tuple[ReferenceSourceBundle, float]] = {}


async def get_gdp_bundle(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    current_year = datetime.now(timezone.utc).year
    # Six calendar years ensure a request for the latest five years still has
    # five complete annual observations even early in the current year.
    years = ",".join(str(year) for year in range(current_year - 5, current_year + 1))
    cache_key = years
    now = time.monotonic()
    cached = _gdp_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_gdp_call(
            db, tenant_id=tenant_id, actor_id=actor_id, years=years,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        current_dollar_rows, real_change_rows, annual_real_change_rows = await asyncio.gather(
            _retry_external(lambda: get_gdp_data(years=years, table_name=GDP_TABLE_NAME)),
            _retry_external(lambda: get_gdp_data(years=years, table_name=REAL_GDP_CHANGE_TABLE_NAME)),
            _retry_external(lambda: get_gdp_data(years=years, table_name=REAL_GDP_CHANGE_TABLE_NAME, frequency="A")),
        )
        data = [dict(row, _table=GDP_TABLE_NAME) for row in current_dollar_rows]
        data.extend(dict(row, _table=REAL_GDP_CHANGE_TABLE_NAME, _frequency="Q") for row in real_change_rows)
        data.extend(dict(row, _table=REAL_GDP_CHANGE_TABLE_NAME, _frequency="A") for row in annual_real_change_rows)
    except Exception as exc:
        await _log_gdp_call(
            db, tenant_id=tenant_id, actor_id=actor_id, years=years,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="US Bureau of Economic Analysis (NIPA GDP)",
        source_url=f"{get_settings().BEA_API_BASE_URL}/?method=GetData&DataSetName=NIPA&TableName={REAL_GDP_CHANGE_TABLE_NAME}",
        data=data,
        licence_status="public_no_auth",
    )
    _gdp_cache[cache_key] = (bundle, now + _GDP_CACHE_TTL_SECONDS)

    await _log_gdp_call(
        db, tenant_id=tenant_id, actor_id=actor_id, years=years,
        status="200", record_count=len(data),
    )
    return bundle


async def _log_gdp_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    years: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="bea_nipa.gdp",
        actor_id=actor_id,
        payload={
            "params": {"table": GDP_TABLE_NAME, "years": years},
            "status": status,
            "record_count": record_count,
        },
    )


def _parse_bea_millions(value_str: str) -> float:
    return float(value_str.replace(",", ""))


def _format_bea_trillions(value_millions: float) -> str:
    return f"${value_millions / 1_000_000:.2f} trillion"


def to_gdp_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats BEA NIPA GDP data into a RAG-shaped chunk. Computes a real,
    transparent year-over-year GDP growth rate (current dollars) from two
    actual published quarterly levels — same derived-figure pattern as the
    Census poverty-rate and BLS CPI YoY calculations, not an invented
    metric."""
    entries = [e for e in bundle.data if e.get("_table", GDP_TABLE_NAME) == GDP_TABLE_NAME]
    real_change_entries = [
        e for e in bundle.data
        if e.get("_table") == REAL_GDP_CHANGE_TABLE_NAME and e.get("_frequency", "Q") == "Q"
    ]
    annual_real_change_entries = [
        e for e in bundle.data
        if e.get("_table") == REAL_GDP_CHANGE_TABLE_NAME and e.get("_frequency") == "A"
    ]
    periods = sorted({e["TimePeriod"] for e in entries})
    latest_period = periods[-1] if periods else None
    prior_period = None
    if latest_period:
        prior_period = f"{int(latest_period[:4]) - 1}{latest_period[4:]}"

    def _line(period: str, description: str) -> dict | None:
        return next(
            (e for e in entries if e["TimePeriod"] == period and e["LineDescription"] == description),
            None,
        )

    lines = [
        "US Bureau of Economic Analysis — National Income and Product Accounts "
        f"(NIPA), Table 1.1.5 Gross Domestic Product (current dollars, quarterly), {latest_period}:"
    ]
    for description in _GDP_LINE_DESCRIPTIONS:
        row = _line(latest_period, description) if latest_period else None
        if row:
            lines.append(f"- {description}: {_format_bea_trillions(_parse_bea_millions(row['DataValue']))}")

    gdp_latest = _line(latest_period, "Gross domestic product") if latest_period else None
    gdp_prior = _line(prior_period, "Gross domestic product") if prior_period else None
    if gdp_latest and gdp_prior:
        latest_val = _parse_bea_millions(gdp_latest["DataValue"])
        prior_val = _parse_bea_millions(gdp_prior["DataValue"])
        yoy_rate = (latest_val - prior_val) / prior_val * 100
        lines.append(
            f"- Year-over-year GDP growth (current dollars, {prior_period} to {latest_period}): {yoy_rate:.1f}%"
        )

    real_gdp_change = next(
        (
            e for e in real_change_entries
            if e.get("TimePeriod") == latest_period
            and e.get("LineDescription") == "Gross domestic product"
        ),
        None,
    )
    if real_gdp_change and real_gdp_change.get("DataValue") not in (None, ""):
        lines.append(
            "- Real GDP percent change from the preceding quarter at an annual rate "
            f"({latest_period}): {real_gdp_change['DataValue']}%"
        )

    annual_real_changes: list[tuple[str, str]] = []
    for row in sorted(annual_real_change_entries, key=lambda item: item.get("TimePeriod", "")):
        period = str(row.get("TimePeriod", ""))
        if (
            re.fullmatch(r"\d{4}", period)
            and row.get("LineDescription") == "Gross domestic product"
            and row.get("DataValue") not in (None, "")
        ):
            annual_real_changes.append((period, str(row["DataValue"])))
    annual_real_changes = annual_real_changes[-5:]
    if annual_real_changes:
        lines.append("Recent annual real GDP growth rates:")
        for year, value in annual_real_changes:
            lines.append(f"- {year}: {value}%")

    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "US Bureau of Economic Analysis — NIPA GDP (Tables 1.1.1 and 1.1.5)",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{BEA_GDP_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── Federal Reserve Economic Data (FRED, St. Louis Fed) — interest rates ─
# Free with registration, keyed via query param like Census/BEA. National
# data, no state/entity extraction needed — same posture as BLS CPI/BEA
# GDP. Unlike those, "interest-rates" is its own dedicated category (not
# shared with Census/CPI/GDP) since none of its keywords overlap with
# theirs, so the category match alone is sufficient gating — no separate
# is_*_query() helper needed the way economic-data required one per
# sub-source.
#
# Real, verified series IDs (fred_adapter.py fetches each independently —
# FRED only returns one series per request):
#   DFF           = Federal Funds Effective Rate (daily)
#   MPRIME        = Bank Prime Loan Rate (monthly)
#   DGS10         = 10-Year Treasury Constant Maturity Rate (daily)
#   DGS30         = 30-Year Treasury Constant Maturity Rate (daily)
#   MORTGAGE30US  = 30-Year Fixed Rate Mortgage Average (weekly)
_FRED_SERIES: dict[str, str] = {
    "DFF": "Federal Funds Effective Rate",
    "MPRIME": "Bank Prime Loan Rate",
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "DGS30": "30-Year Treasury Constant Maturity Rate",
    "MORTGAGE30US": "30-Year Fixed Rate Mortgage Average",
}

_FRED_CACHE_TTL_SECONDS = 24 * 60 * 60
_fred_cache: dict[str, tuple[ReferenceSourceBundle, float]] = {}


async def get_interest_rates_bundle(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = "interest_rates"
    now = time.monotonic()
    cached = _fred_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_fred_call(
            db, tenant_id=tenant_id, actor_id=actor_id,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        # One request per series (FRED has no multi-series observations
        # endpoint) — fetched concurrently rather than sequentially so one
        # user query doesn't pay for 5 round-trips back to back.
        observation_start = (datetime.now(timezone.utc) - timedelta(days=370)).date().isoformat()
        results = await asyncio.gather(
            *(
                _retry_external(lambda series_id=series_id: get_series_observations(
                    series_id, limit=400, observation_start=observation_start,
                ))
                for series_id in _FRED_SERIES
            )
        )
    except Exception as exc:
        await _log_fred_call(
            db, tenant_id=tenant_id, actor_id=actor_id,
            status=f"error: {exc}", record_count=0,
        )
        raise

    data = [
        {"series_id": series_id, "title": title, "date": obs["date"], "value": obs["value"]}
        for (series_id, title), observations in zip(_FRED_SERIES.items(), results)
        for obs in observations
    ]

    bundle = ReferenceSourceBundle(
        source_name="Federal Reserve Economic Data (FRED)",
        source_url=f"{get_settings().FRED_API_BASE_URL}/series/observations",
        data=data,
        licence_status="public_no_auth",
    )
    _fred_cache[cache_key] = (bundle, now + _FRED_CACHE_TTL_SECONDS)

    await _log_fred_call(
        db, tenant_id=tenant_id, actor_id=actor_id,
        status="200", record_count=len(data),
    )
    return bundle


async def _log_fred_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="fred.interest_rates",
        actor_id=actor_id,
        payload={
            "params": {"series_ids": list(_FRED_SERIES.keys())},
            "status": status,
            "record_count": record_count,
        },
    )


def to_fred_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats FRED interest-rate data into a RAG-shaped chunk. Unlike the
    CPI/GDP formatters, no derived year-over-year calculation — the latest
    published value already IS the metric these questions ask for (e.g.
    "what is the current federal funds rate"), not a rate of change."""
    by_series: dict[str, list[dict]] = {}
    for row in bundle.data:
        by_series.setdefault(row["series_id"], []).append(row)

    lines = ["Federal Reserve Economic Data (FRED) — key US interest rates:"]
    for series_id, title in _FRED_SERIES.items():
        # "." is FRED's missing-value sentinel for a not-yet-published period.
        rows = [r for r in by_series.get(series_id, []) if r.get("value") not in (None, ".")]
        if not rows:
            continue
        latest = rows[0]  # fetched with sort_order=desc, so index 0 is latest
        lines.append(f"- {title} ({series_id}): {latest['value']}% (as of {latest['date']})")
        if len(rows) > 1:
            earliest = rows[-1]
            change = float(latest["value"]) - float(earliest["value"])
            lines.append(
                f"  One-year window: {earliest['value']}% on {earliest['date']} to "
                f"{latest['value']}% on {latest['date']} ({change:+.2f} percentage points)"
            )

    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "Federal Reserve Economic Data (FRED) — Interest Rates",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{FRED_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── GovInfo (US Government Publishing Office) — 26 CFR section lookup ───
# Free with registration, keyed via query param. Unlike every other source
# in this file, this isn't a numeric series — it's an on-demand fetch of
# the actual regulatory text for one named 26 CFR (Internal Revenue)
# section, triggered only when the query explicitly cites a section
# number. No free-text fallback: an unnamed-section CFR question (e.g.
# "what does the CFR say about retirement plans") skips the live fetch
# entirely rather than guessing which of thousands of sections is meant —
# same fail-closed contract as match_work_state/match_state_fips.
_CFR_SECTION_PATTERN = re.compile(r"\b(\d+\.\d+(?:\([a-zA-Z0-9]+\))*(?:-\d+)?)\b")


def extract_cfr_section(query: str) -> str | None:
    """Returns a 26 CFR section number (e.g. "1.401(k)-1") if the query
    names one, or None if it doesn't. Callers MUST treat None as "do not
    call the live API" — there is no honest fallback for "fetch the whole
    of Title 26" the way there is for currency/date defaults."""
    match = _CFR_SECTION_PATTERN.search(query)
    return match.group(1) if match else None


_CFR_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # annual CFR edition — changes rarely
_cfr_cache: dict[str, tuple[ReferenceSourceBundle, float]] = {}


async def get_cfr_section_bundle(
    db: AsyncSession,
    *,
    section_number: str,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = section_number
    now = time.monotonic()
    cached = _cfr_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_cfr_call(
            db, tenant_id=tenant_id, actor_id=actor_id, section_number=section_number,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_cfr_section(section_number))
    except Exception as exc:
        await _log_cfr_call(
            db, tenant_id=tenant_id, actor_id=actor_id, section_number=section_number,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="GovInfo — 26 CFR (Internal Revenue)",
        source_url=data["details_url"],
        data=[data],
        licence_status="public_no_auth",
    )
    _cfr_cache[cache_key] = (bundle, now + _CFR_CACHE_TTL_SECONDS)

    await _log_cfr_call(
        db, tenant_id=tenant_id, actor_id=actor_id, section_number=section_number,
        status="200", record_count=1,
    )
    return bundle


async def _log_cfr_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    section_number: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="govinfo.cfr_title26",
        actor_id=actor_id,
        payload={
            "params": {"section_number": section_number},
            "status": status,
            "record_count": record_count,
        },
    )


def to_cfr_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats a 26 CFR section lookup into a RAG-shaped chunk. Unlike the
    other formatters, this wraps real regulatory prose (not a data table),
    so it's capped at _MAX_CONTEXT_CHARS the same way but with a truncation
    note appended — some CFR sections run several pages long."""
    payload = bundle.data[0] if bundle.data else {}
    section_number = payload.get("section_number", "unknown section")
    subject = payload.get("subject", "")
    text = payload.get("text", "")

    header = f"26 CFR § {section_number}"
    if subject:
        header += f" — {subject}"
    header += ":\n"

    budget = _MAX_CONTEXT_CHARS - len(header)
    truncated = len(text) > budget
    body = text[:budget] + ("... [truncated]" if truncated else "")

    return {
        "text": header + body,
        "metadata": {
            "source_id": source_id,
            "title": "GovInfo — 26 CFR (Internal Revenue Regulations)",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{CFR_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── Federal Register — single-document lookup ────────────────────────────
# Fully public, no API key. Same fail-closed, on-demand posture as the
# GovInfo CFR lookup above: only fetched when the query names a specific
# document number (there is no honest fallback for "which Federal Register
# document out of hundreds of thousands was meant").
_FR_DOCUMENT_NUMBER_PATTERN = re.compile(r"\b(20\d{2}-\d{4,6})\b")


def extract_federal_register_document_number(query: str) -> str | None:
    """Returns a Federal Register document number (e.g. "2026-13925") if
    the query names one, or None if it doesn't. Callers MUST treat None as
    "do not call the live API" — same contract as extract_cfr_section."""
    match = _FR_DOCUMENT_NUMBER_PATTERN.search(query)
    return match.group(1) if match else None


# Published Federal Register documents are a permanent historical record —
# once issued, a document's content never changes. A long cache costs
# nothing in freshness; 7 days matches the other document-lookup sources
# in this file for consistency.
_FR_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_fr_doc_cache: dict[str, tuple[ReferenceSourceBundle, float]] = {}


async def get_federal_register_document_bundle(
    db: AsyncSession,
    *,
    document_number: str,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = document_number
    now = time.monotonic()
    cached = _fr_doc_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_federal_register_call(
            db, tenant_id=tenant_id, actor_id=actor_id, document_number=document_number,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_federal_register_document(document_number))
    except Exception as exc:
        await _log_federal_register_call(
            db, tenant_id=tenant_id, actor_id=actor_id, document_number=document_number,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="Federal Register",
        source_url=data.get("html_url", ""),
        data=[data],
        licence_status="public_no_auth",
    )
    _fr_doc_cache[cache_key] = (bundle, now + _FR_CACHE_TTL_SECONDS)

    await _log_federal_register_call(
        db, tenant_id=tenant_id, actor_id=actor_id, document_number=document_number,
        status="200", record_count=1,
    )
    return bundle


async def _log_federal_register_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    document_number: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="federal_register.document",
        actor_id=actor_id,
        payload={
            "params": {"document_number": document_number},
            "status": status,
            "record_count": record_count,
        },
    )


def to_federal_register_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats a single Federal Register document lookup into a RAG-shaped
    chunk — metadata + abstract, not the full document body (Federal
    Register documents don't expose full text via this JSON endpoint the
    way GovInfo's CFR granules do; the abstract plus citation/effective
    date is the governed, structured data actually available here)."""
    payload = bundle.data[0] if bundle.data else {}
    agencies = ", ".join(a.get("name", "") for a in payload.get("agencies", []) if a.get("name"))

    # Includes both identifiers — the model is instructed to answer only
    # from the literal provided context, so if a query names the document
    # number ("2026-13925") but the chunk only showed the citation
    # ("91 FR 42659"), it has no grounded way to confirm they're the same
    # document and may correctly refuse rather than connect them itself
    # (verified: this exact gap caused a real refusal in testing).
    document_number = payload.get("document_number", "unknown")
    citation = payload.get("citation")
    header = f"Federal Register — Document {document_number}"
    if citation:
        header += f" ({citation})"
    lines = [header + ":"]
    if payload.get("title"):
        lines.append(f"- Title: {payload['title']}")
    if agencies:
        lines.append(f"- Agency: {agencies}")
    if payload.get("action"):
        lines.append(f"- Action: {payload['action']}")
    if payload.get("publication_date"):
        lines.append(f"- Published: {payload['publication_date']}")
    if payload.get("effective_on"):
        lines.append(f"- Effective: {payload['effective_on']}")
    if payload.get("abstract"):
        lines.append(f"- Abstract: {payload['abstract']}")

    return {
        "text": "\n".join(lines),
        "metadata": {
            "source_id": source_id,
            "title": "Federal Register — Document Lookup",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{FEDERAL_REGISTER_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── eCFR — 26 CFR section lookup (current amended text) ──────────────────
# Fully public, no API key. Does the same conceptual job as the GovInfo CFR
# lookup above — kept alongside it rather than replacing it, since
# comprehensive collection of US tax data is the explicit goal, and eCFR's
# continuously-updated text is complementary evidence to GovInfo's static
# annual edition, not a strict duplicate. Triggered by the same
# extract_cfr_section() used for GovInfo — one section-number extraction,
# two independent live sources.
_ECFR_CACHE_TTL_SECONDS = 24 * 60 * 60  # continuously updated — shorter TTL than GovInfo's annual-edition cache
_ecfr_cache: dict[str, tuple[ReferenceSourceBundle, float]] = {}


async def get_ecfr_section_bundle(
    db: AsyncSession,
    *,
    section_number: str,
    tenant_id: str,
    actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = section_number
    now = time.monotonic()
    cached = _ecfr_cache.get(cache_key)

    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_ecfr_call(
            db, tenant_id=tenant_id, actor_id=actor_id, section_number=section_number,
            status="cache_hit", record_count=len(bundle.data),
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_ecfr_section(section_number))
    except Exception as exc:
        await _log_ecfr_call(
            db, tenant_id=tenant_id, actor_id=actor_id, section_number=section_number,
            status=f"error: {exc}", record_count=0,
        )
        raise

    bundle = ReferenceSourceBundle(
        source_name="eCFR — Title 26 (Internal Revenue)",
        source_url=data["details_url"],
        data=[data],
        licence_status="public_no_auth",
    )
    _ecfr_cache[cache_key] = (bundle, now + _ECFR_CACHE_TTL_SECONDS)

    await _log_ecfr_call(
        db, tenant_id=tenant_id, actor_id=actor_id, section_number=section_number,
        status="200", record_count=1,
    )
    return bundle


async def _log_ecfr_call(
    db: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    section_number: str,
    status: str,
    record_count: int,
) -> None:
    await record_event_async(
        db,
        tenant_id=tenant_id,
        event_name="external_reference_data_call",
        emitting_service="reference_data",
        subject_type="external_source",
        subject_id="ecfr.cfr_title26",
        actor_id=actor_id,
        payload={
            "params": {"section_number": section_number},
            "status": status,
            "record_count": record_count,
        },
    )


def to_ecfr_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    """Formats an eCFR section lookup into a RAG-shaped chunk — same
    truncation posture as to_cfr_rag_chunk (real prose, can run long)."""
    payload = bundle.data[0] if bundle.data else {}
    heading = payload.get("heading", "")
    text = payload.get("text", "")
    date = payload.get("date", "")

    header = heading or f"26 CFR § {payload.get('section_number', 'unknown section')}"
    if date:
        header += f" (as amended, current as of {date})"
    header += ":\n"

    budget = _MAX_CONTEXT_CHARS - len(header)
    truncated = len(text) > budget
    body = text[:budget] + ("... [truncated]" if truncated else "")

    return {
        "text": header + body,
        "metadata": {
            "source_id": source_id,
            "title": "eCFR — Title 26 (Internal Revenue, Current)",
            "version": bundle.retrieved_at.isoformat(),
            "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{ECFR_NODE_PREFIX}{uuid4().hex[:8]}",
    }


# ── Congress.gov — explicit bill lookup ─────────────────────────────────
_CONGRESS_NUMBER_PATTERN = re.compile(r"\b(\d{1,3})(?:st|nd|rd|th)\s+congress\b", re.IGNORECASE)
_BILL_PATTERN = re.compile(
    r"\b(H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|H\.?\s*Con\.?\s*Res\.?|"
    r"S\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?|S\.?\s*Res\.?|H\.?\s*R\.?|S\.?)\s*(\d+)\b",
    re.IGNORECASE,
)
_BILL_TYPE_MAP = {
    "hjres": "hjres", "sjres": "sjres", "hconres": "hconres", "sconres": "sconres",
    "hres": "hres", "sres": "sres", "hr": "hr", "s": "s",
}


def extract_congress_bill_identifier(query: str) -> tuple[int, str, int] | None:
    """Extract a complete bill identifier; never guess the Congress number."""
    congress_match = _CONGRESS_NUMBER_PATTERN.search(query)
    bill_match = _BILL_PATTERN.search(query)
    if not congress_match or not bill_match:
        return None
    bill_type = re.sub(r"[^a-z]", "", bill_match.group(1).lower())
    normalized_type = _BILL_TYPE_MAP.get(bill_type)
    if normalized_type is None:
        return None
    return int(congress_match.group(1)), normalized_type, int(bill_match.group(2))


_CONGRESS_CACHE_TTL_SECONDS = 6 * 60 * 60
_congress_bill_cache: dict[tuple[int, str, int], tuple[ReferenceSourceBundle, float]] = {}


async def get_congress_bill_bundle(
    db: AsyncSession, *, congress: int, bill_type: str, bill_number: int,
    tenant_id: str, actor_id: str | None,
) -> ReferenceSourceBundle:
    cache_key = (congress, bill_type, bill_number)
    now = time.monotonic()
    cached = _congress_bill_cache.get(cache_key)
    if cached is not None and cached[1] > now:
        bundle = cached[0]
        await _log_congress_call(
            db, tenant_id=tenant_id, actor_id=actor_id, identifier=cache_key,
            status="cache_hit", record_count=1,
        )
        return bundle

    try:
        data = await _retry_external(lambda: get_congress_bill(congress, bill_type, bill_number))
    except Exception as exc:
        await _log_congress_call(
            db, tenant_id=tenant_id, actor_id=actor_id, identifier=cache_key,
            status=f"error: {exc}", record_count=0,
        )
        raise

    official_url = data.get("official_url") or (
        f"{get_settings().CONGRESS_API_BASE_URL}/bill/{congress}/{bill_type}/{bill_number}"
    )
    bundle = ReferenceSourceBundle(
        source_name="Congress.gov — Bill Lookup", source_url=official_url,
        data=[data], licence_status="public_api_key",
    )
    _congress_bill_cache[cache_key] = (bundle, now + _CONGRESS_CACHE_TTL_SECONDS)
    await _log_congress_call(
        db, tenant_id=tenant_id, actor_id=actor_id, identifier=cache_key,
        status="200", record_count=1,
    )
    return bundle


async def _log_congress_call(
    db: AsyncSession, *, tenant_id: str, actor_id: str | None,
    identifier: tuple[int, str, int], status: str, record_count: int,
) -> None:
    congress, bill_type, bill_number = identifier
    await record_event_async(
        db, tenant_id=tenant_id, event_name="external_reference_data_call",
        emitting_service="reference_data", subject_type="external_source",
        subject_id="congress.gov.bill", actor_id=actor_id,
        payload={
            "params": {"congress": congress, "bill_type": bill_type, "bill_number": bill_number},
            "status": status, "record_count": record_count,
        },
    )


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def to_congress_rag_chunk(bundle: ReferenceSourceBundle, *, source_id: str) -> dict:
    payload = bundle.data[0] if bundle.data else {}
    identifier = f"{payload.get('bill_type', '')} {payload.get('bill_number', '')}"
    lines = [f"Congress.gov — {identifier.strip()}, {payload.get('congress', '')}th Congress:"]
    if payload.get("title"):
        lines.append(f"- Title: {payload['title']}")
    if payload.get("introduced_date"):
        lines.append(f"- Introduced: {payload['introduced_date']}")
    if payload.get("policy_area"):
        lines.append(f"- Policy area: {payload['policy_area']}")
    latest_action = payload.get("latest_action") or {}
    if latest_action.get("text"):
        lines.append(f"- Latest action ({latest_action.get('actionDate', 'date unavailable')}): {latest_action['text']}")
    if payload.get("summary"):
        lines.append(f"- Latest CRS summary: {_plain_text(payload['summary'])}")
    if payload.get("laws"):
        law_labels = [
            f"{law.get('type', 'Law')} {law.get('number', '')}".strip()
            for law in payload["laws"] if isinstance(law, dict)
        ]
        if law_labels:
            lines.append(f"- Enacted as: {', '.join(law_labels)}")
    text = "\n".join(lines)[:_MAX_CONTEXT_CHARS]
    return {
        "text": text,
        "metadata": {
            "source_id": source_id, "title": "Congress.gov — Bill Lookup",
            "version": bundle.retrieved_at.isoformat(), "jurisdiction": "US",
            "file_path": bundle.source_url,
            # 2026-07-29 real incident: every reference_data chunk was
            # missing this key entirely, so orchestration/service.py's
            # citation-building code (`chunk["metadata"].get("source_type",
            # "document")`) silently defaulted every one of these dynamic,
            # live-fetched sources (Treasury/Census/BLS/BEA/FRED/eCFR/CFR/
            # Federal Register/Congress) to "document" — the actual URL
            # still resolved correctly (resolve_source_url doesn't key off
            # this field), but the citation's own type was simply wrong.
            # Matches the "live_api" value live_sources/service.py's
            # to_synthetic_chunk() already uses for the same real-world kind
            # of source, so both domains are consistent.
            "source_type": "live_api",
        },
        "score": 0.5,
        "node_id": f"{CONGRESS_NODE_PREFIX}{uuid4().hex[:8]}",
    }
