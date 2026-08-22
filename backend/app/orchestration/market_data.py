"""Market and company data grounding for Ask Kriton™.

The bridge between app/domains/market_data/ and the answer pipeline, and
deliberately thin: it self-gates, calls the domain service, and renders the
normalized result into the same WebSource shape SearXNG, DBnomics and
Frankfurter return. No provider-specific code lives here — adding a fifth
provider must not require editing this file.

Same contract as the other exact-figure connectors (dbnomics.py,
frankfurter.py, sec_edgar.py):
  - self-gating: returns [] unless the question is actually about market or
    company data, so a question about depreciation never gets a share price
    attached as provenance
  - fail-soft: any error yields [], and the bot falls back to its normal
    web-grounded answer

Freshness is carried through to the citation rather than flattened away. A
previous close and a realtime tick are different claims, and an answer that
blurs them is the specific failure this product exists to avoid — so the
snippet states it in words and WebSource.freshness states it in a field the UI
can badge.

Streaming is NOT handled here. A continuous price feed has no query to
classify, no answer to validate and nothing to audit before returning, so it
cannot travel this path — see the market_data package docstring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domains.market_data import registry, service
from app.domains.market_data.http import make_client
from app.domains.market_data.identity import company_name_hint, resolve_local
from app.domains.market_data.providers.companies_house import CompaniesHouseProvider
from app.domains.market_data.schemas import (
    CompanyProfile,
    EntityRef,
    FilingRecord,
    FinancialMetric,
    OHLCVBar,
    ProviderBadResponse,
    ProviderError,
    StockQuote,
)
from app.orchestration.websearch import WebSource

# How each freshness value should read to a human. The reader must never have
# to infer whether a figure is live.
_FRESHNESS_WORDS = {
    "realtime": "real-time",
    "delayed": "delayed (not real-time)",
    "historical": "historical / end-of-day (not real-time)",
    "filing": "as filed with the registrar",
}


def _money(value: float | None, currency: str = "") -> str:
    if value is None:
        return "n/a"
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{value:,.2f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{prefix}{value:,.0f}"


def _quote_source(quote: StockQuote) -> WebSource:
    # Only name the company separately when we actually have a name — the
    # provider quote endpoints often return none, and "AAPL (AAPL)" reads as a
    # bug rather than as data.
    label = f"{quote.company_name} ({quote.symbol})" if quote.company_name else quote.symbol
    bits = [f"{label}: {_money(quote.price, quote.currency)}"]
    if quote.change is not None and quote.change_percent is not None:
        bits.append(f"change {quote.change:+,.2f} ({quote.change_percent:+.2f}%)")
    for label, value in (("open", quote.open), ("high", quote.high), ("low", quote.low),
                         ("previous close", quote.previous_close)):
        if value is not None:
            bits.append(f"{label} {_money(value, quote.currency)}")
    if quote.volume is not None:
        bits.append(f"volume {quote.volume:,.0f}")

    freshness_words = _FRESHNESS_WORDS.get(quote.freshness, quote.freshness)
    stamp = quote.provider_timestamp or quote.fetched_at
    snippet = (
        f"{'; '.join(bits)}. "
        f"Data is {freshness_words}, from {quote.provider} as at {stamp}."
        + (f" Market state: {quote.market_status}." if quote.market_status else "")
    )
    return WebSource(
        title=f"{quote.provider} — {quote.symbol} quote ({quote.freshness})"[:200],
        url=quote.source_url,
        snippet=snippet,
        provider=quote.provider,
        fetched_at=quote.fetched_at,
        freshness=quote.freshness,
    )


def _history_source(bars: list[OHLCVBar]) -> WebSource:
    first, last = bars[0], bars[-1]
    tail = bars[-8:]
    series = ", ".join(f"{b.timestamp[:10]}: {b.close:,.2f}" for b in tail)
    return WebSource(
        title=f"{last.provider} — {last.symbol} price history ({first.timestamp[:10]} to {last.timestamp[:10]})"[:200],
        url=f"https://www.google.com/finance/quote/{last.symbol}",
        snippet=(
            f"{last.symbol} {last.interval or 'daily'} closes, {len(bars)} bars from "
            f"{first.timestamp[:10]} to {last.timestamp[:10]}. Most recent — {series}. "
            f"Historical end-of-day data from {last.provider}; not real-time."
        ),
        provider=last.provider,
        freshness="historical",
    )


def _metric_value(metric: FinancialMetric) -> str:
    """A figure a reader can take in at a glance.

    Plain %g turned a 1.3-trillion market cap into "1.307e+06" — technically
    correct, useless in an answer, and the kind of thing that gets misread by
    three orders of magnitude. Large currency amounts get a scale word
    alongside the separated digits; ratios and percentages stay compact.
    """
    value, unit = metric.value, metric.unit
    if unit == "%":
        return f"{value:,.2f}%"
    if unit in ("ratio", ""):
        return f"{value:,.4g}" if abs(value) < 1000 else f"{value:,.2f}"
    if unit == "per share":
        return f"{value:,.2f} per share"

    # Currency amount.
    for threshold, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(value) >= threshold:
            return f"{unit} {value:,.0f} ({value / threshold:,.2f} {word})".strip()
    return f"{unit} {value:,.2f}".strip()


def _fundamentals_source(metrics: list[FinancialMetric]) -> WebSource:
    head = metrics[0]
    lines = "; ".join(f"{m.metric}: {_metric_value(m)}" for m in metrics)
    return WebSource(
        title=f"{head.provider} — {head.company or head.symbol} key figures"[:200],
        url=head.source_url,
        snippet=(
            f"Reported figures for {head.company or head.symbol}"
            f"{f' ({head.symbol})' if head.symbol else ''}: {lines}. "
            f"Source: {head.provider}"
            f"{f', fiscal period {head.fiscal_period}' if head.fiscal_period else ''}. "
            "These are provider-computed metrics, not audited statements."
        ),
        provider=head.provider,
        freshness="historical",
    )


def _filings_source(filings: list[FilingRecord]) -> WebSource:
    head = filings[0]
    lines = "; ".join(
        f"{f.filing_date}: {f.filing_type} — {f.description}".strip().rstrip("—").strip() for f in filings[:8]
    )
    return WebSource(
        title=f"Companies House — {head.company_name} filing history"[:200],
        url=head.source_url,
        snippet=(
            f"{head.company_name} (company number {head.company_number}), most recent statutory "
            f"filings as recorded at Companies House: {lines}. "
            f"As filed with the registrar; filing dates are the dates received."
        ),
        provider=head.provider,
        freshness="filing",
    )


def _profile_source(profile: CompanyProfile) -> WebSource:
    facts = [f"{k.replace('_', ' ')}: {v}" for k, v in (profile.identifiers or {}).items() if v]
    for label, value in (("exchange", profile.exchange), ("country", profile.country),
                         ("sector", profile.sector), ("industry", profile.industry)):
        if value:
            facts.append(f"{label}: {value}")
    if profile.market_cap is not None:
        facts.append(f"market capitalisation: {profile.market_cap:,.0f} {profile.currency}".strip())

    return WebSource(
        title=f"{profile.provider} — {profile.company_name} company profile"[:200],
        url=profile.source_url,
        snippet=f"{profile.company_name}"
        f"{f' ({profile.symbol})' if profile.symbol else ''}. "
        + ". ".join(facts)
        + f". Source: {profile.provider}.",
        provider=profile.provider,
        freshness="filing" if profile.provider == "companies_house" else "historical",
    )


# ── Ownership (persons with significant control) ─────────────────────────
# A dedicated, self-gating connector — same contract as dbnomics.py's
# _find_best_series / frankfurter.py's _find_rate, NOT routed through
# service.fetch_market_data()'s generic multi-provider dispatch above: PSC
# data only exists at Companies House (no fallback-provider chain is
# possible for it), so going through the shared dispatcher would buy nothing
# and risks a second, wasted network fetch if a caller also calls
# fetch_market_sources() for the same query. Fetched exactly once; that one
# result builds BOTH the grounding WebSource and the composition evidence
# fetch_live_data() populates (see evidence.py's "never two independent
# fetches for the same fact" rule).
_OWNERSHIP_HINTS = re.compile(
    r"\b(persons? with significant control|significant control|\bpsc\b|"
    r"shareholders?|shareholding|major shareholders?|cap table|who owns|"
    r"ownership (breakdown|split|percentage|stake|composition)|beneficial owners?)\b",
    re.I,
)

# "Ownership structure" alone is deliberately EXCLUDED from _OWNERSHIP_HINTS
# above — it's owned by RELATIONSHIP's user-supplied-entity-graph reading
# (intent_classifier.py's _RELATIONSHIP_HINTS). But when the user ALSO names
# a pie/donut-chart rendering in the same request ("ownership structure ...
# as a pie chart"), that combination unambiguously asks for this company's
# REAL, fetched shareholding — not a graph the user is about to supply
# themselves. Matched in EITHER order, bounded to a short same-clause window
# (stops at . ; :) so a bare "ownership structure" or a bare "pie chart"
# elsewhere in a longer, multi-clause query never satisfies this alone.
# Deliberately a SEPARATE regex from _OWNERSHIP_HINTS (never widen that
# pattern itself) — test_ownership_hints_match_shareholder_phrasing /
# test_ownership_hints_do_not_match_unrelated_query assert its exact match
# surface directly, and test_user_supplied_ownership_structure_stays_relationship
# depends on a bare "ownership structure" (no chart word) staying RELATIONSHIP.
_OWNERSHIP_STRUCTURE_CHART_HINT = re.compile(
    r"\bownership structures?\b(?=(?:(?![.;:]).){0,80}\b(?:pie|donut) charts?\b)|"
    r"\b(?:pie|donut) charts?\b(?=(?:(?![.;:]).){0,80}\bownership structures?\b)",
    re.I,
)
# Stripper for the two trigger phrases above. Uses lookahead in the pattern
# above (not literal span-consumption), so this is safe to apply
# unconditionally — it only ever removes the two short phrases themselves,
# never the company name (or anything else) sitting between them.
_OWNERSHIP_STRUCTURE_CHART_PHRASES = re.compile(
    r"\bownership structures?\b|\b(?:pie|donut) charts?\b", re.I,
)


@dataclass
class OwnershipMatch:
    company_name: str
    company_number: str
    # (holder label, percent) — percent is always a declared PSC BAND's
    # midpoint, never an exact filed figure; the last slice, when present, is
    # the synthesized "Other shareholders" gap (100% minus known midpoints) —
    # a real arithmetic consequence of the known slices, not fabricated data.
    slices: list[tuple[str, float]]
    url: str
    caveat: str


def _best_company_match(term: str, candidates: list[EntityRef]) -> EntityRef | None:
    """Companies House's free-text company search ranks by an internal
    relevance signal that is NOT reliably a name-prefix match — searching
    "HSBC" once ranked two unrelated companies (neither containing "HSBC"
    anywhere in its name) above every real HSBC entity. Blindly trusting the
    top result risks silently attaching a stranger's real PSC data to the
    query, which is worse than finding nothing. Candidates must contain all
    requested name tokens; active public/group parents are preferred and
    shell-like corporate-director/nominee entities are penalized."""
    needle = (term or "").strip().casefold()
    if not needle:
        return None
    words = tuple(re.findall(r"[a-z0-9]+", needle))
    if not words:
        return None

    shell_words = {"corporate", "director", "nominee", "nominees", "pension", "trustee", "services"}

    def score(candidate: EntityRef) -> tuple[int, int]:
        name = candidate.name.strip().casefold()
        name_words = set(re.findall(r"[a-z0-9]+", name))
        if not all(word in name_words for word in words):
            return (-10_000, 0)
        value = 20 * len(words)
        if name.startswith(needle):
            value += 20
        if name_words & {"group", "holdings"}:
            value += 12
        value -= 12 * len(name_words & shell_words)
        if candidate.company_status.casefold() == "active":
            value += 8
        if candidate.company_type.casefold() in {"plc", "public-limited-company"}:
            value += 10
        # Prefer the concise parent-like registered name when all other
        # signals tie, rather than whichever search result arrived first.
        return (value, -len(name_words))

    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0])[0] > 0 else None


async def _find_ownership(query: str) -> OwnershipMatch | None:
    q = query or ""
    if not (_OWNERSHIP_HINTS.search(q) or _OWNERSHIP_STRUCTURE_CHART_HINT.search(q)):
        return None

    provider = CompaniesHouseProvider()
    if not provider.configured():
        return None

    ref = resolve_local(query)
    # The ownership-trigger phrase itself ("persons with significant
    # control", "shareholders", "PSC", "cap table", ...) must never reach
    # Companies House's search endpoint as part of the company name — it
    # isn't part of any real company's name and can coincidentally match an
    # unrelated one whose actual registered name contains one of those words
    # (e.g. "significant" matched a real company called "Life's Significant
    # Moments With Anne Limited" instead of Barclays). A confirmed name from
    # resolve_local()'s well-known-name table is preferred outright; failing
    # that, the hint is derived from the query with the ownership phrase
    # stripped out first, never from the raw query text.
    hint = ref.name or company_name_hint(
        _OWNERSHIP_STRUCTURE_CHART_PHRASES.sub(" ", _OWNERSHIP_HINTS.sub(" ", query))
    )
    if not ref.company_number and not hint:
        return None

    try:
        async with make_client() as client:
            if not ref.company_number:
                candidates = await provider.search(client, hint, limit=10)
                best = _best_company_match(hint, candidates)
                if best is None or not best.company_number:
                    return None
                ref = best
            try:
                stakes = await provider.get_ownership(client, ref)
            except ProviderBadResponse as exc:
                if "no persons with significant control" not in str(exc).casefold():
                    raise
                return OwnershipMatch(
                    company_name=ref.name or hint,
                    company_number=ref.company_number,
                    slices=[],
                    url=(
                        "https://find-and-update.company-information.service.gov.uk/company/"
                        f"{ref.company_number}/persons-with-significant-control"
                    ),
                    caveat=(
                        "Companies House returned no persons with significant control for this exact entity. "
                        "PSC filings disclose statutory control (generally over 25%); they are not a complete "
                        "shareholder register and commonly do not identify the owners of widely held listed companies."
                    ),
                )
    except ProviderError:
        return None
    except Exception:  # noqa: BLE001 — connector boundary must fail soft
        return None

    # Only PSCs with a real ownership-of-shares band count toward a "share of
    # the whole" figure — voting-rights-only/appointment-only/influence-only
    # control is a real fact but not a percentage of shares (see
    # companies_house.py's get_ownership docstring). Ceased PSCs are historic,
    # not current ownership.
    active = [s for s in stakes if not s.ceased and s.min_percent is not None and s.max_percent is not None]
    if not active:
        return OwnershipMatch(
            company_name=ref.name or hint,
            company_number=ref.company_number,
            slices=[],
            url=(
                "https://find-and-update.company-information.service.gov.uk/company/"
                f"{ref.company_number}/persons-with-significant-control"
            ),
            caveat=(
                "Companies House returned no active PSC with an ownership-of-shares band for this exact entity. "
                "PSC data records statutory control, not a complete shareholder register."
            ),
        )

    slices: list[tuple[str, float]] = [(s.name, (s.min_percent + s.max_percent) / 2.0) for s in active]
    known_total = sum(v for _, v in slices)
    if known_total < 99.5:
        slices.append(("Other shareholders (below statutory disclosure threshold)", 100.0 - known_total))

    caveat = (
        "Ownership bands as filed with Companies House (persons with significant control). "
        "Values are the midpoint of each holder's declared band (e.g. \"25-50%\" → ~38%), not "
        "an exact filed percentage, and only holders the register requires to be disclosed "
        "(generally over 25% control) are listed."
    )
    return OwnershipMatch(
        company_name=active[0].company_name, company_number=active[0].company_number,
        slices=slices, url=active[0].source_url, caveat=caveat,
    )


def _build_ownership_source(match: OwnershipMatch) -> WebSource:
    lines = "; ".join(
        f"{label}: ~{value:.0f}%" for label, value in match.slices
        if not label.startswith("Other shareholders")
    )
    if not match.slices:
        return WebSource(
            title=f"Companies House — {match.company_name} PSC register"[:200],
            url=match.url,
            snippet=(
                f"Companies House lookup for {match.company_name} (company number {match.company_number}) "
                f"found no reportable ownership-of-shares PSC entries. {match.caveat}"
            ),
            provider="companies_house",
            freshness="filing",
        )
    return WebSource(
        title=f"Companies House — {match.company_name} persons with significant control"[:200],
        url=match.url,
        snippet=(
            f"{match.company_name} (company number {match.company_number}) persons with significant "
            f"control, as filed with Companies House: {lines}. {match.caveat} Other, smaller "
            "shareholders may exist and are not shown."
        ),
        provider="companies_house",
        freshness="filing",
    )


@dataclass
class MarketSourceResult:
    sources: list[WebSource] = field(default_factory=list)
    # Real OHLC bars — populated ONLY when the resolved intent is
    # INTENT_HISTORY, else None. Every other market-data intent (quote,
    # fundamentals, filings, profile, lookup) still returns sources only;
    # this is additive, not a behavior change for them.
    ohlc: list[OHLCVBar] | None = None
    symbol: str = ""


async def fetch_market_sources(query: str) -> MarketSourceResult:
    """Return grounding sources (and, for a history-shaped question, the
    real OHLC bars behind them) for a market/company question, else an
    empty result. Fetched exactly once — the SAME result builds both the
    WebSource citation and (for history) the chart-ready evidence, never two
    independent fetches for the same fact (see evidence.py's docstring)."""
    outcome = await service.fetch_market_data(query)
    if outcome is None:
        return MarketSourceResult()

    result, _provider, intent = outcome
    try:
        if intent == registry.INTENT_QUOTE and isinstance(result, StockQuote):
            return MarketSourceResult(sources=[_quote_source(result)])
        if intent == registry.INTENT_HISTORY and isinstance(result, list) and result:
            bars: list[OHLCVBar] = result  # type: ignore[assignment]
            return MarketSourceResult(sources=[_history_source(bars)], ohlc=bars, symbol=bars[-1].symbol)
        if intent == registry.INTENT_FUNDAMENTALS and isinstance(result, list) and result:
            return MarketSourceResult(sources=[_fundamentals_source(result)])  # type: ignore[arg-type]
        if intent == registry.INTENT_FILINGS and isinstance(result, list) and result:
            return MarketSourceResult(sources=[_filings_source(result)])  # type: ignore[arg-type]
        if isinstance(result, CompanyProfile):
            return MarketSourceResult(sources=[_profile_source(result)])
    except Exception:  # noqa: BLE001 — rendering must never break the request
        return MarketSourceResult()
    return MarketSourceResult()
