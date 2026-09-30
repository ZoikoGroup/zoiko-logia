"""
Live structured-data grounding for Ask Kriton™.

SearXNG is great for text (rules, procedures, explanations) but not for exact
numbers. This module adds precise-figure sources that answer the question when
one applies, and stays out of the way otherwise:
  - Frankfurter → live currency exchange rates (frankfurter.py), with a
                  market-rate fallback for the currencies the ECB does not
                  publish (fx_fallback.py)
  - FRED        → official US economic statistics (fred.py)
  - DBnomics    → official economic statistics (dbnomics.py)
  - SEC EDGAR   → US registrants' own filed financials (sec_edgar.py), their
                  filing text via full-text search and cross-company XBRL peer
                  ranking (sec_search.py)
  - Bank of England → the UK policy rate (bank_of_england.py)
  - GOV.UK      → UK tax rates and thresholds, within an expiry (govuk.py)
  - OECD Tax Database → statutory corporate income tax rates for any of the
                  ten countries, on both the central-government and combined
                  measures (oecd_tax.py)
  - Market data → quotes, price history, fundamentals, company profiles and UK
                  statutory filings, via Companies House / Finnhub / Polygon /
                  Alpha Vantage (market_data.py)

Every connector self-gates (each returns [] unless the question matches its kind)
and fails soft, so this is safe to always call. Results are WebSource objects,
identical in shape to SearXNG hits, so they merge into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.

Each connector's match is fetched exactly ONCE (via its private `_find_*`
finder) and used to build BOTH the WebSource text and the structured
EvidenceModel below — never two independent fetches for the same fact, so the
narrative text and any visualization built from `evidence` can never disagree
about the underlying numbers (see evidence.py's module docstring).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence
from app.orchestration.country_scope import display_name
from app.orchestration.websearch import WebSource, wants_visual
from app.orchestration.sec_edgar import fetch_sec_facts
from app.orchestration.legislation import fetch_legislation
from app.orchestration.market_data import (
    fetch_market_sources, _find_ownership, _build_ownership_source,
)
from app.orchestration.evidence import EvidenceModel, Observation, OHLCBar
from app.orchestration.frankfurter import (
    _find_rate, _build_source as _build_fx_source, unsupported_currency_note,
)
from app.orchestration.fred import _find_fred_series, _build_source as _build_fred_source
from app.orchestration.fx_fallback import (
    _find_fallback_rate, _build_source as _build_fx_fallback_source,
)
from app.orchestration.bank_of_england import (
    _find_bank_rate, _build_source as _build_bank_rate_source,
)
from app.orchestration.govuk import (
    _find_uk_tax_rate, _build_source as _build_govuk_source,
)
from app.orchestration.sec_search import fetch_sec_fulltext, fetch_sec_peer_rank
from app.orchestration.dbnomics import (
    _find_best_series, _build_source as _build_stats_source,
    _find_two_series, _build_pair_source,
)
from app.orchestration.bank_of_canada import (
    _find_policy_rate, _build_source as _build_ca_rate_source,
)
from app.orchestration.rba import _find_cash_rate, _build_source as _build_rba_source
from app.orchestration.abs_australia import (
    _find_abs_series, _build_source as _build_abs_source, PROVIDER as ABS_PROVIDER,
)
from app.orchestration.cso_ireland import (
    _find_cso_series, _build_source as _build_cso_source, PROVIDER as CSO_PROVIDER,
)
from app.orchestration.us_treasury import (
    _find_treasury_figure, _build_source as _build_treasury_source,
    PROVIDER as TREASURY_PROVIDER,
)
from app.orchestration.oecd_tax import (
    _find_oecd_tax_rate, _build_source as _build_oecd_tax_source,
    PROVIDER as OECD_TAX_PROVIDER,
)

settings = get_settings()


@dataclass
class LiveDataResult:
    sources: list[WebSource] = field(default_factory=list)
    evidence: EvidenceModel = field(default_factory=EvidenceModel)
    deterministic_answer: str | None = None


async def fetch_live_data(query: str) -> LiveDataResult:
    """Run the exact-figure connectors concurrently. Never raises — a failing
    connector contributes nothing to either the sources or the evidence.

    _find_best_series self-guards against correlation-shaped queries (defers
    entirely to _find_two_series — see dbnomics.py), so all three connectors
    can run concurrently without one path double-populating evidence for the
    same query. One total deadline bounds the whole fan-out: every connector
    that has not finished within it is cancelled, and everything that did
    finish is still kept."""
    connectors = (
        _find_rate(query), _find_fred_series(query), _find_best_series(query),
        _find_two_series(query), _find_ownership(query), fetch_sec_facts(query),
        fetch_market_sources(query), fetch_legislation(query),
        _find_fallback_rate(query), _find_bank_rate(query), _find_uk_tax_rate(query),
        fetch_sec_fulltext(query), fetch_sec_peer_rank(query),
        _find_policy_rate(query), _find_cash_rate(query), _find_abs_series(query),
        _find_cso_series(query), _find_treasury_figure(query),
        _find_oecd_tax_rate(query),
    )
    tasks = [asyncio.ensure_future(connector) for connector in connectors]
    pending: set[asyncio.Future] = set(tasks)
    try:
        done, pending = await asyncio.wait(
            tasks, timeout=settings.LIVE_DATA_TIMEOUT_SECONDS
        )
    finally:
        # A total deadline or parent-request cancellation must stop every
        # unfinished connector, including provider retries and backoff sleeps.
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    results: list[object | None] = [None] * len(tasks)
    for index, task in enumerate(tasks):
        if task.cancelled() or task.exception() is not None:
            continue
        results[index] = task.result()

    fx_primary_match, fred_match, series_match, pair_match = results[0:4]
    ownership_match, sec_sources, market_sources, legislation_sources = results[4:8]
    fx_fallback_match = results[8]
    bank_rate_match, govuk_match = results[9:11]
    fulltext_sources, peer_sources = results[11:13]
    ca_rate_match, rba_rate_match, abs_series_match, cso_series_match, treasury_match = results[13:18]
    oecd_tax_match = results[18]
    sources: list[WebSource] = []
    evidence = EvidenceModel()

    # The ECB reference rate is authoritative and always wins. The market-rate
    # fallback runs concurrently but self-gates on exactly the condition
    # "Frankfurter could not serve this pair", so it is already None here
    # whenever the primary answered — it never competes, it only fills.
    fx_match = fx_primary_match or fx_fallback_match

    if not fx_match:
        # Neither source can serve the pair. Say so as a source rather than
        # leaving the gap for the model to fill from memory (frankfurter.py's
        # docstring records the fabrication this prevents).
        fx_gap = unsupported_currency_note(query)
        if fx_gap:
            sources.append(fx_gap)

    if fx_match:
        sources.append(
            _build_fx_source(fx_match) if fx_primary_match
            else _build_fx_fallback_source(fx_match)
        )
        evidence.subject = evidence.subject or f"{fx_match.base_cur}/{fx_match.quote_cur} exchange rate"
        evidence.observations.append(Observation(dimension=fx_match.date, value=fx_match.rate, measure="rate"))
        evidence.dimensions.append("date")
        evidence.measures.append("rate")
        evidence.units.append(fx_match.quote_cur)
        evidence.sources.append(fx_match.url)

    # FRED is authoritative for the curated US series it recognizes.  When it
    # succeeds, suppress the concurrently-fetched DBnomics alternative so one
    # answer never mixes two differently-defined series under one chart.
    #
    # US Treasury's dollar figures outrank FRED for the non-ratio fiscal
    # questions both match ("how much is the US debt" hits even Treasury's
    # debt_to_penny and FRED's GFDEBTN), so a matched Treasury figure also
    # suppresses FRED: the quarterly, restated FRED level and the daily,
    # primary-publisher level are different quantities, and showing both as
    # one series would be a category error. The ratio questions stay with FRED
    # because Treasury's dollar connector refuses any phrasing that mentions
    # GDP/percent/share (see us_treasury._definition_for_query).
    if fred_match and not treasury_match:
        sources.append(_build_fred_source(fred_match))
        evidence.subject = evidence.subject or fred_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=fred_match.series_name)
            for period, value in fred_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(fred_match.series_name)
        evidence.units.append(fred_match.unit)
        evidence.sources.append(fred_match.url)
        evidence.provider = "Federal Reserve Bank of St. Louis (FRED)"
        evidence.series_id = fred_match.series_id
        evidence.requested_start = fred_match.requested_start
        evidence.requested_end = fred_match.requested_end
        evidence.retrieved_start = fred_match.points[0][0]
        evidence.retrieved_end = fred_match.points[-1][0]
        evidence.coverage_complete = fred_match.coverage_complete
        if fred_match.warning:
            evidence.warnings.append(fred_match.warning)

    # A country specialist has the final word on its own figures. DBnomics and
    # FRED both mirror what the national statistical agency publishes, so when
    # the agency itself answered ("Ireland CPI" → CSO, "Australian
    # unemployment" → ABS), the mirror must not be shown alongside it — it is
    # the same category from a secondary source, and the user wouldn't know
    # which of two numbers to trust. Each specialist self-scopes to its country,
    # so none of them can shadow a cross-country series_match; pair_match
    # (two countries, explicit comparison) is left alone entirely.
    specialist_matched = any(
        match is not None
        for match in (treasury_match, ca_rate_match, rba_rate_match,
                      abs_series_match, cso_series_match)
    )
    if series_match and not fred_match and not specialist_matched:
        sources.append(_build_stats_source(series_match))
        evidence.subject = evidence.subject or series_match.series_name
        evidence.observations.extend(
            Observation(dimension=p, value=v, measure=series_match.series_name)
            for p, v in series_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(series_match.series_name)
        evidence.sources.append(series_match.url)

    if pair_match:
        match_a, match_b = pair_match
        sources.append(_build_pair_source(match_a, match_b))
        evidence.subject = evidence.subject or match_a.series_name
        evidence.secondary_subject = match_b.series_name
        evidence.observations.extend(
            Observation(dimension=p, value=v, measure=match_a.series_name) for p, v in match_a.points
        )
        evidence.secondary_observations.extend(
            Observation(dimension=p, value=v, measure=match_b.series_name) for p, v in match_b.points
        )
        evidence.dimensions.append("period")
        evidence.measures.extend([match_a.series_name, match_b.series_name])
        evidence.sources.extend([match_a.url, match_b.url])

    if ownership_match:
        sources.append(_build_ownership_source(ownership_match))
        evidence.composition_subject = f"{ownership_match.company_name} — shareholding"
        evidence.composition.extend(
            Observation(dimension=label, value=value, measure="ownership_percent")
            for label, value in ownership_match.slices
        )
        evidence.composition_caveat = ownership_match.caveat
        evidence.sources.append(ownership_match.url)

    # SEC EDGAR currently exposes grounded WebSources but not chart-ready
    # EvidenceModel observations — preserve its source output only.
    if isinstance(sec_sources, list):
        sources.extend(sec_sources)
        deterministic_answer = (
            "\n\n".join(source.snippet for source in sec_sources[:3])
            if sec_sources else None
        )
    else:
        deterministic_answer = None
    if isinstance(legislation_sources, list):
        sources.extend(legislation_sources)

    # UK policy rate. A real dated series, so it charts like FRED does. Note
    # the Bank Rate is a step function — it holds a value for months at a time
    # and then moves in quarter-point steps — so the daily observations are
    # mostly repeats; the source snippet carries the latest value and the date
    # of the most recent change, which is the part a question is actually for.
    if bank_rate_match is not None:
        sources.append(_build_bank_rate_source(bank_rate_match))
        evidence.subject = evidence.subject or bank_rate_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=bank_rate_match.series_name)
            for period, value in bank_rate_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(bank_rate_match.series_name)
        evidence.units.append(bank_rate_match.unit)
        evidence.sources.append(bank_rate_match.url)
        evidence.provider = "Bank of England"
        evidence.series_id = bank_rate_match.series_id
        evidence.retrieved_start = bank_rate_match.points[0][0]
        evidence.retrieved_end = bank_rate_match.points[-1][0]

    # GOV.UK tax guidance is prose, not a numeric series, so it contributes a
    # source only — never evidence.observations, which are (period, value)
    # pairs and would be meaningless here.
    if govuk_match is not None:
        sources.append(_build_govuk_source(govuk_match))

    # Country specialists, in the same shape as the Bank Rate above: Bank of
    # Canada policy rate and RBA cash rate are step-function policy series, and
    # ABS/CSO/Treasury are ordinary (period, value) statistical series. The
    # source already carries .series, so the narrative and any chart built from
    # evidence agree with the cited snippet by construction.
    if ca_rate_match is not None:
        sources.append(_build_ca_rate_source(ca_rate_match))
        evidence.subject = evidence.subject or ca_rate_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=ca_rate_match.series_name)
            for period, value in ca_rate_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(ca_rate_match.series_name)
        evidence.units.append(ca_rate_match.unit)
        evidence.sources.append(ca_rate_match.url)
        evidence.provider = "Bank of Canada"
        evidence.series_id = ca_rate_match.series_id
        evidence.retrieved_start = ca_rate_match.points[0][0]
        evidence.retrieved_end = ca_rate_match.points[-1][0]

    if rba_rate_match is not None:
        sources.append(_build_rba_source(rba_rate_match))
        evidence.subject = evidence.subject or rba_rate_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=rba_rate_match.series_name)
            for period, value in rba_rate_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(rba_rate_match.series_name)
        evidence.units.append(rba_rate_match.unit)
        evidence.sources.append(rba_rate_match.url)
        evidence.provider = "Reserve Bank of Australia"
        evidence.retrieved_start = rba_rate_match.points[0][0]
        evidence.retrieved_end = rba_rate_match.points[-1][0]

    if abs_series_match is not None:
        sources.append(_build_abs_source(abs_series_match))
        evidence.subject = evidence.subject or abs_series_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=abs_series_match.series_name)
            for period, value in abs_series_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(abs_series_match.series_name)
        evidence.units.append(abs_series_match.unit)
        evidence.sources.append(abs_series_match.url)
        evidence.provider = ABS_PROVIDER
        evidence.retrieved_start = abs_series_match.points[0][0]
        evidence.retrieved_end = abs_series_match.points[-1][0]

    if cso_series_match is not None:
        sources.append(_build_cso_source(cso_series_match))
        evidence.subject = evidence.subject or cso_series_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=cso_series_match.series_name)
            for period, value in cso_series_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(cso_series_match.series_name)
        evidence.units.append(cso_series_match.unit)
        evidence.sources.append(cso_series_match.url)
        evidence.provider = CSO_PROVIDER
        evidence.retrieved_start = cso_series_match.points[0][0]
        evidence.retrieved_end = cso_series_match.points[-1][0]

    if treasury_match is not None:
        sources.append(_build_treasury_source(treasury_match))
        evidence.subject = evidence.subject or treasury_match.name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=treasury_match.name)
            for period, value in treasury_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(treasury_match.name)
        evidence.units.append(treasury_match.unit)
        evidence.sources.append(treasury_match.url)
        evidence.provider = TREASURY_PROVIDER
        evidence.retrieved_start = treasury_match.points[0][0]
        evidence.retrieved_end = treasury_match.points[-1][0]
        # Not "== ''": series_id defaults to None, so that comparison never
        # matched and a treasury-only result carried no series id at all.
        if not evidence.series_id:
            evidence.series_id = treasury_match.name

    # Statutory corporate income tax rates, for any of the ten countries, from
    # the OECD Tax Database. It is an annual series, so the year travels with
    # the value: a rate for 2026 is not a live reading and must not be quoted as
    # one. Both measures (central government and combined) are charted off the
    # headline one only — they are different quantities for the same country, not
    # two lines of one series.
    if oecd_tax_match is not None:
        sources.append(_build_oecd_tax_source(oecd_tax_match))
        evidence.subject = evidence.subject or (
            f"{display_name(oecd_tax_match.country)} corporate income tax rate"
        )
        evidence.observations.extend(
            Observation(dimension=period, value=value,
                        measure="statutory corporate income tax rate (%)")
            for period, value in oecd_tax_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append("statutory corporate income tax rate (%)")
        evidence.units.append("percent")
        evidence.sources.append(oecd_tax_match.url)
        evidence.provider = OECD_TAX_PROVIDER
        if not evidence.series_id:
            evidence.series_id = f"oecd_cit_{oecd_tax_match.country.lower()}"
        evidence.retrieved_start = oecd_tax_match.points[0][0]
        evidence.retrieved_end = oecd_tax_match.points[-1][0]

    # SEC full-text and XBRL peer ranking both contribute sources only. A
    # full-text hit is a location inside a filing, not a figure, and a peer
    # table is a ranking of differently-dated windows — neither is a single
    # (period, value) series, so neither populates evidence.observations.
    if isinstance(fulltext_sources, list):
        sources.extend(fulltext_sources)
    if isinstance(peer_sources, list):
        sources.extend(peer_sources)

    # market_data.py's fetch_market_sources() populates BOTH sources and (for
    # a history-shaped question) real OHLC bars from the SAME single fetch —
    # every other market-data intent (quote/fundamentals/filings/profile)
    # still contributes sources only, unchanged.
    if market_sources is not None:
        sources.extend(market_sources.sources)
        if market_sources.ohlc:
            evidence.ohlc_subject = market_sources.symbol or evidence.ohlc_subject
            evidence.ohlc.extend(
                OHLCBar(
                    dimension=bar.timestamp, open=bar.open, high=bar.high,
                    low=bar.low, close=bar.close, volume=bar.volume,
                )
                for bar in market_sources.ohlc
            )

        if market_sources.sources and deterministic_answer is None:
            deterministic_answer = market_sources.sources[0].snippet

    return LiveDataResult(
        sources=sources,
        evidence=evidence,
        deterministic_answer=deterministic_answer,
    )


# "last 3 years", "past 5 years", "previous 10 quarters" — how much history the
# question actually asked for. dbnomics.py's connector always returns up to its
# own MAX_POINTS (20) regardless of what was asked, so without this a "last 3
# years" request silently charts two decades of data instead.
_REQUESTED_PERIOD_COUNT = re.compile(r"\b(?:last|past|previous)\s+(\d+)\s*(?:years?|yrs?|quarters?)\b", re.I)


def _requested_period_count(query: str) -> int | None:
    match = _REQUESTED_PERIOD_COUNT.search(query)
    return int(match.group(1)) if match else None


def build_forced_chart(query: str, sources: list[WebSource]) -> str | None:
    """Build a ```chart fence directly from a connector's own fetched numeric
    series, when the question asked for a visual and the data supports one.

    This exists because chart correctness cannot depend solely on the model
    choosing to draw one: "Compare GDP growth for the UK, US and Germany" is
    exactly the shape dbnomics.fetch_stats() answers with real per-country
    time series, but nothing forced the model to turn that into a chart
    rather than a prose table (or a table it wrote in markdown) — the
    render_chart tool (chart_tool.py) fixes a model-*chosen* chart's
    correctness, not whether a chart gets made at all. The caller only uses
    this fence when composed_text has none already, so a chart the model (or
    tool) already produced is never overridden.
    """
    if not wants_visual(query):
        return None
    stat_sources = [s for s in sources if s.series and len(s.series) >= 2]
    if not stat_sources:
        return None
    period_count = _requested_period_count(query)
    if period_count and period_count >= 2:
        stat_sources = [dataclasses.replace(s, series=s.series[-period_count:]) for s in stat_sources]

    if len(stat_sources) == 1:
        source = stat_sources[0]
        args = {
            "type": "line",
            "title": source.title,
            "categories": [period for period, _ in source.series],
            "series": [{"name": source.title, "data": [value for _, value in source.series]}],
        }
    else:
        # A comparison: chart only the periods every source actually has, so
        # a country with a shorter reporting lag doesn't get padded with a
        # value it never reported.
        common_periods = set(period for period, _ in stat_sources[0].series)
        for source in stat_sources[1:]:
            common_periods &= set(period for period, _ in source.series)
        ordered_periods = sorted(common_periods)
        if len(ordered_periods) < 1:
            return None
        series = []
        for source in stat_sources:
            values_by_period = dict(source.series)
            label = source.title.rsplit("—", 1)[-1].strip() if "—" in source.title else source.title
            series.append({"name": label, "data": [values_by_period[period] for period in ordered_periods]})
        args = {
            "type": "bar",
            "title": stat_sources[0].title.rsplit("—", 1)[0].strip() if "—" in stat_sources[0].title else "Comparison",
            "categories": ordered_periods,
            "series": series,
        }

    try:
        return build_chart_fence(json.dumps(args))
    except ChartToolError:
        return None
