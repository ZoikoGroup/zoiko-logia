"""Upstream canary — probes every configured official source for real.

Run from ``backend``::

    python scripts/check_external_sources.py                  # serial, local default
    python scripts/check_external_sources.py --concurrency 6  # CI
    python scripts/check_external_sources.py --json report.json

This is deliberately NOT a test. The test suite mocks every upstream, which
is correct — a merge must not fail because a government web server is slow.
The consequence is that nothing in the repository ever talks to a real
authority, so the failure that actually happens is invisible to it: the
upstream changes its contract, the connector keeps returning HTTP 200, the
parser silently yields nothing, and Kriton's answer path degrades in silence
(live_sources.service.fetch_live_data() never raises, and falls back to a
stale cache entry that is audited as an ordinary cache hit).

Three rules follow from that, and they are what this script is built around:

1. A response is only ``live`` if it carries usable CONTENT. A 200 with zero
   records is the signature of contract drift, and reporting it as healthy
   defeats the entire purpose of running this.
2. Probes target the CURRENT period wherever the source has one. A probe
   pinned to a past year keeps succeeding forever while current data quietly
   stops flowing — a false negative that gets worse with age.
3. Nothing here downloads a bulk feed. Sanctions lists are checked for
   reachability with a ranged request; the real ~50 MB sync stays on its own
   schedule (app/jobs/live_sources_tasks.py).

Exit codes: 0 = nothing failed, 1 = at least one configured source failed.
Wire it into CI as a scheduled, non-blocking job — an upstream outage is not
a broken commit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.core.config import get_settings
from app.domains.live_sources.connectors.bank_of_england import BankOfEnglandConnector
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.companies_house import CompaniesHouseConnector
from app.domains.live_sources.connectors.ecb import ECBConnector
from app.domains.live_sources.connectors.frankfurter import FrankfurterConnector
from app.domains.live_sources.connectors.fred import FREDConnector
from app.domains.live_sources.connectors.gleif import GLEIFConnector
from app.domains.live_sources.connectors.imf import IMFConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.oecd import OECDConnector
from app.domains.live_sources.connectors.ons import ONSConnector
from app.domains.live_sources.connectors.regulations_gov import RegulationsGovConnector
from app.domains.live_sources.connectors.sam_gov import SAMGovConnector
from app.domains.live_sources.connectors.sanctions_feeds import _candidate_urls, _feed_headers
from app.domains.live_sources.connectors.sec_edgar import SECEdgarConnector
from app.domains.live_sources.connectors.ted import TEDConnector
from app.domains.live_sources.connectors.vies import VIESConnector
from app.domains.live_sources.connectors.world_bank import WorldBankConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
from app.domains.live_sources.http_client import close_shared_http_client
from app.domains.live_sources.retry import is_retryable
from app.domains.live_sources.schemas import LiveDataIntent
from app.domains.reference_data.adapters.bea_adapter import get_gdp_data
from app.domains.reference_data.adapters.bls_adapter import get_cpi_series
from app.domains.reference_data.adapters.census_adapter import get_state_income_poverty
from app.domains.reference_data.adapters.congress_adapter import get_bill
from app.domains.reference_data.adapters.ecfr_adapter import get_cfr_section as get_ecfr_section
from app.domains.reference_data.adapters.federal_register_adapter import get_document
from app.domains.reference_data.adapters.fred_adapter import get_series_observations
from app.domains.reference_data.adapters.govinfo_adapter import get_cfr_section as get_govinfo_section
from app.domains.reference_data.adapters.payroll_tax_adapter import get_payroll_tax_rates
from app.domains.reference_data.adapters.professional_search_adapter import search_serpapi, search_tavily
from app.domains.reference_data.adapters.treasury_adapter import get_exchange_rates

settings = get_settings()

# Ceiling for any single probe. Must exceed the slowest connector's own
# configured budget, or the canary kills a request the runtime would have
# allowed and reports a timeout the runtime would never have seen — Cellar
# is the current worst case at CELLAR_SPARQL_TIMEOUT_SECONDS.
_PROBE_TIMEOUT_CEILING = max(
    90.0,
    settings.CELLAR_SPARQL_TIMEOUT_SECONDS + 15.0,
    settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS + 15.0,
)

_TODAY = datetime.now(timezone.utc).date()
_CURRENT_YEAR = str(_TODAY.year)
# The US Congress numbering is arithmetic, not a constant to be re-pinned
# every two years: the 1st Congress convened in 1789 and each runs two years.
_CURRENT_CONGRESS = (_TODAY.year - 1789) // 2 + 1


# Query parameters that carry a credential. httpx puts the full request URL
# into HTTPStatusError's message, so an upstream 4xx from any key-in-query
# API reproduces the key verbatim in this report — which is printed to CI
# logs and uploaded as a retained artifact. connectors/sam_gov.py already
# avoids raise_for_status() for exactly this reason; the canary calls a
# dozen adapters that do not, so it has to redact at the reporting boundary.
_SECRET_QUERY_KEYS = ("api_key", "apikey", "key", "registrationkey", "userid", "subscription-key", "token")


def _redact(message: str) -> str:
    redacted = message
    for name in _SECRET_QUERY_KEYS:
        redacted = re.sub(
            rf"([?&]{re.escape(name)}=)[^&\s'\"]+", r"\1[REDACTED]", redacted, flags=re.IGNORECASE,
        )
    return redacted


class EmptyResponse(RuntimeError):
    """A source answered successfully but returned nothing usable.

    Kept distinct from a transport or status failure because it means
    something different and is acted on differently: the host is up, the
    request was accepted, and the contract moved underneath us.
    """


def _require(value, *, at_least: int = 1, description: str = "records"):
    """Assert a probe returned real content.

    The previous implementation tested ``value in (None, [], {})``, which a
    response object carrying an empty ``records`` list passes — so a renamed
    upstream field was reported as ``live``. Emptiness has to be judged on
    the payload, not on the wrapper around it.
    """
    if value is None:
        raise EmptyResponse("source returned no response")
    for attribute in ("records", "entries", "observations"):
        collection = getattr(value, attribute, None)
        if collection is not None:
            if len(collection) < at_least:
                raise EmptyResponse(
                    f"source returned {len(collection)} {attribute}, expected at least {at_least}"
                )
            return value
    if isinstance(value, (list, tuple, dict, str)):
        if len(value) < at_least:
            raise EmptyResponse(f"source returned {len(value)} {description}, expected at least {at_least}")
        return value
    # A metric connector returns a single NormalizedResponse; "usable" for
    # one of those means it actually carries a value and a period.
    observed = getattr(value, "value", None)
    if observed is None or observed == "":
        raise EmptyResponse("source returned an observation with no value")
    if hasattr(value, "observation_period") and not value.observation_period:
        raise EmptyResponse("source returned a value with no observation period")
    return value


def _recent_period(value, *, max_age_days: int, label: str):
    """Flag an observation that parses as a date older than the source's own
    publication rhythm. Returns the value either way — a lagging series is
    reported as ``stale``, not ``failed``, because the distinction between
    "this source is broken" and "this source has not published lately" is
    the one an operator needs to act on."""
    period = str(getattr(value, "observation_period", "") or "")
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            observed = datetime.strptime(period, pattern).date()
        except ValueError:
            continue
        if (_TODAY - observed).days > max_age_days:
            raise StaleObservation(f"{label} last published {period}, over {max_age_days} days ago")
        return value
    # Unparseable period (index codes, request dates) — nothing to judge.
    return value


class StaleObservation(RuntimeError):
    """Reachable and well-formed, but the newest data is older than the
    source's own stated cadence."""


async def _probe_feed_reachable(url: str, fallback_urls: str) -> dict:
    """Reachability probe for a bulk feed, WITHOUT downloading it.

    The previous check called sanctions_service.get_snapshot(), which reads
    the local snapshot file and only touches the network when inline refresh
    is enabled — so it reported "live" for a list nobody had been able to
    download in weeks. It asked "is there a file on this machine", which is
    a real question, but not this one.

    A ranged GET is used rather than HEAD: several of these hosts answer HEAD
    with 405 while serving GET perfectly well.
    """
    candidates = _candidate_urls(url, fallback_urls)
    if not candidates:
        raise EmptyResponse("no feed URL configured")
    failures = []
    headers = {**_feed_headers(), "Range": "bytes=0-1023"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for candidate in candidates:
            try:
                response = await client.get(candidate, headers=headers)
                response.raise_for_status()
                if not response.content:
                    raise EmptyResponse("feed returned an empty body")
                return {"reachable_url": candidate, "bytes_sampled": len(response.content)}
            except Exception as exc:
                failures.append(_redact(f"{candidate} -> {type(exc).__name__}: {str(exc)[:120]}"))
    raise RuntimeError("; ".join(failures))


def _intent(provider: str, code: str, label: str, country: str, country_label: str, company: str | None = None):
    return LiveDataIntent(
        provider_key=provider, indicator_code=code, indicator_label=label,
        country_code=country, country_label=country_label, company_query=company,
    )


def _evidence(provider: str, query: str, page_size: int = 1) -> EvidenceSearchIntent:
    return EvidenceSearchIntent(provider_key=provider, query=query, page_size=page_size)


# ── Probe registry ────────────────────────────────────────────────────────
#
# Each entry: (name, provider_key or None, coroutine factory, configured).
# `provider_key` links a probe back to its LiveSourceProvider row so a
# successful contact can stamp last_successful_sync; reference-data adapters
# have no registry row and pass None.
#
# Recency budgets come from each source's own publication rhythm, not one
# global number: World Bank publishing an annual figure 400 days ago is
# normal, Frankfurter doing the same is broken.


def _build_probes() -> list[tuple[str, str | None, object, bool]]:
    timeout = settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS

    async def world_bank():
        result = await WorldBankConnector(settings.WORLD_BANK_API_BASE_URL).fetch(
            _intent("world_bank", "NY.GDP.MKTP.CD", "GDP", "IN", "India"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=900, label="World Bank GDP")

    async def ons():
        result = await ONSConnector(settings.ONS_API_BASE_URL).fetch(
            _intent("ons", "CP00", "CPIH", "GB", "United Kingdom"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=120, label="ONS CPIH")

    async def bank_of_england():
        result = await BankOfEnglandConnector(settings.BANK_OF_ENGLAND_API_BASE_URL).fetch(
            _intent("bank_of_england", "IUDBEDR", "Bank Rate", "GB", "United Kingdom"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=60, label="Bank Rate")

    async def frankfurter():
        result = await FrankfurterConnector(settings.FRANKFURTER_API_BASE_URL).fetch(
            _intent("frankfurter", "USD_GBP", "USD/GBP", "FX", "Global"), timeout=timeout)
        # Reference rates publish every working day; a week of silence is a fault.
        return _recent_period(_require(result), max_age_days=7, label="USD/GBP reference rate")

    async def fred_live():
        result = await FREDConnector(settings.FRED_API_BASE_URL, settings.FRED_API_KEY).fetch(
            _intent("fred", "FEDFUNDS", "Federal Funds Rate", "US", "United States"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=120, label="Fed funds rate")

    async def sec_edgar():
        # Company facts carry a fiscal period, not a calendar one, so no
        # recency budget applies without knowing the filer's year end.
        return _require(await SECEdgarConnector(
            settings.SEC_EDGAR_API_BASE_URL, settings.SEC_EDGAR_USER_AGENT).fetch(
            _intent("sec_edgar", "Assets", "Total Assets", "US", "United States", "Apple"), timeout=timeout))

    async def companies_house():
        return _require(await CompaniesHouseConnector(
            settings.COMPANIES_HOUSE_API_BASE_URL, settings.COMPANIES_HOUSE_API_KEY).fetch(
            _intent("companies_house", "profile", "Company Profile", "GB", "United Kingdom", "Tesco"), timeout=timeout))

    async def oecd():
        result = await OECDConnector(settings.OECD_API_BASE_URL).fetch(
            _intent("oecd", "GBR:CIT_C", "Corporate Tax Rate", "GB", "United Kingdom"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=900, label="OECD corporate tax rate")

    async def gleif():
        return _require(await GLEIFConnector(settings.GLEIF_API_BASE_URL).fetch(
            _intent("gleif", "profile", "Company Profile", "IN", "India", "Tata Motors"), timeout=timeout))

    async def ecb():
        result = await ECBConnector(settings.ECB_API_BASE_URL).fetch(
            _intent("ecb", "FM:D.U2.EUR.4F.KR.DFR.LEV", "ECB Deposit Facility Rate", "EURO_AREA", "Euro area"),
            timeout=timeout)
        return _recent_period(_require(result), max_age_days=60, label="ECB deposit facility rate")

    async def imf():
        result = await IMFConnector(settings.IMF_API_BASE_URL).fetch(
            _intent("imf", "NGDP_RPCH:IND", "Real GDP Growth", "IN", "India"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=800, label="IMF WEO real GDP growth")

    async def vies():
        # A syntactically valid but unassigned number: this probes that VIES
        # returns a validation verdict at all, not that any given trader is
        # registered. Its requestDate should always be today.
        result = await VIESConnector(settings.VIES_API_BASE_URL).fetch(
            _intent("vies", "vat_validation", "EU VAT Validation", "DE", "Germany", "DE123456789"), timeout=timeout)
        return _recent_period(_require(result), max_age_days=5, label="VIES validation date")

    async def regulations_gov():
        return _require(await RegulationsGovConnector(
            settings.REGULATIONS_GOV_API_BASE_URL, settings.REGULATIONS_GOV_API_KEY,
        ).search(_evidence("regulations_gov", "tax reporting"), timeout=timeout))

    async def cellar():
        # Given the connector's own budget, not the shared one — that is the
        # whole point of CELLAR_SPARQL_TIMEOUT_SECONDS existing.
        return _require(await CellarConnector(settings.CELLAR_SPARQL_URL).search(
            _evidence("cellar", "Artificial Intelligence Act"),
            timeout=settings.CELLAR_SPARQL_TIMEOUT_SECONDS))

    async def legislation_gov_uk():
        return _require(await LegislationGovUKConnector(settings.LEGISLATION_GOV_UK_BASE_URL).search(
            _evidence("legislation_gov_uk", "Companies Act"), timeout=timeout))

    async def ted():
        return _require(await TEDConnector(settings.TED_API_BASE_URL).search(
            _evidence("ted", "audit services"), timeout=timeout))

    async def sam_gov():
        return _require(await SAMGovConnector(
            settings.SAM_GOV_OPPORTUNITIES_URL, settings.SAM_GOV_API_KEY).search(
            _evidence("sam_gov", "audit services"), timeout=timeout))

    probes: list[tuple[str, str | None, object, bool]] = [
        ("world_bank", "world_bank", world_bank, True),
        ("ons", "ons", ons, True),
        ("bank_of_england", "bank_of_england", bank_of_england, True),
        ("frankfurter", "frankfurter", frankfurter, True),
        ("fred_live", "fred", fred_live, bool(settings.FRED_API_KEY)),
        ("sec_edgar", "sec_edgar", sec_edgar, bool(settings.SEC_EDGAR_USER_AGENT)),
        ("companies_house", "companies_house", companies_house, bool(settings.COMPANIES_HOUSE_API_KEY)),
        ("oecd", "oecd", oecd, True),
        ("gleif", "gleif", gleif, True),
        ("ecb", "ecb", ecb, True),
        ("imf", "imf", imf, True),
        ("vies", "vies", vies, True),
        ("regulations_gov", "regulations_gov", regulations_gov, bool(settings.REGULATIONS_GOV_API_KEY)),
        ("cellar", "cellar", cellar, True),
        ("legislation_gov_uk", "legislation_gov_uk", legislation_gov_uk, True),
        ("ted", "ted", ted, True),
        ("sam_gov", "sam_gov", sam_gov, bool(settings.SAM_GOV_API_KEY)),
    ]

    # Sanctions: reachability only. The bulk download belongs to the
    # scheduled sync and must never run from a health check.
    for name, url, fallbacks in (
        ("ofac", settings.OFAC_SDN_XML_URL, settings.OFAC_SDN_XML_FALLBACK_URLS),
        ("un_sanctions", settings.UN_SANCTIONS_XML_URL, settings.UN_SANCTIONS_XML_FALLBACK_URLS),
        ("uk_sanctions", settings.UK_SANCTIONS_CSV_URL, settings.UK_SANCTIONS_CSV_FALLBACK_URLS),
        ("eu_sanctions", settings.EU_SANCTIONS_CSV_URL, settings.EU_SANCTIONS_CSV_FALLBACK_URLS),
    ):
        probes.append((
            f"{name}_feed", name,
            (lambda u=url, f=fallbacks: _probe_feed_reachable(u, f)), bool(url),
        ))

    # Reference-data adapters. Period-bearing probes are computed from today
    # so they keep testing current data instead of ageing into a source that
    # answers forever out of an archive.
    probes.extend([
        ("treasury", None, lambda: get_exchange_rates(since=(_TODAY - timedelta(days=365)).isoformat()), True),
        ("payroll_tax", None, lambda: get_payroll_tax_rates("CA", _TODAY.isoformat()),
         bool(settings.PAYROLL_TAX_API_KEY)),
        # ACS releases run one to two years behind; year-2 rolls forward
        # without raising a false alarm every January.
        ("census", None, lambda: get_state_income_poverty("06", str(_TODAY.year - 2)),
         bool(settings.CENSUS_API_KEY)),
        ("bls", None, lambda: get_cpi_series(str(_TODAY.year - 1), _CURRENT_YEAR), True),
        # "X" is BEA's own most-recent-year token — current by construction.
        ("bea", None, lambda: get_gdp_data("X"), bool(settings.BEA_API_KEY)),
        ("fred_reference", None, lambda: get_series_observations("FEDFUNDS", limit=1),
         bool(settings.FRED_API_KEY)),
        ("govinfo", None, lambda: get_govinfo_section("1.61-1"), bool(settings.GOVINFO_API_KEY)),
        # A fixed document number: this probes the adapter's response
        # contract, which is what production depends on. Currency of the
        # Federal Register itself is covered by the regulations_gov probe.
        ("federal_register", None, lambda: get_document("2026-13925"), True),
        ("ecfr", None, lambda: get_ecfr_section("1.61-1"), True),
        ("congress", None, lambda: get_bill(_CURRENT_CONGRESS, "hr", 1), bool(settings.CONGRESS_API_KEY)),
        ("tavily", None, lambda: search_tavily("site:irs.gov standard deduction"), bool(settings.TAVILY_API_KEY)),
        ("serpapi", None, lambda: search_serpapi("site:irs.gov standard deduction"), bool(settings.SERP_API_KEY)),
    ])
    return probes


# ── Runner ────────────────────────────────────────────────────────────────


async def _run_probe(name: str, provider_key: str | None, factory, configured: bool,
                     limit: asyncio.Semaphore) -> dict:
    if not configured:
        # Not a pass. A source nobody can reach for want of a key is not a
        # healthy source, and the summary counts these separately so a run
        # that checked almost nothing cannot read as all-clear.
        return {"provider": name, "provider_key": provider_key, "status": "unconfigured"}

    async with limit:
        started = asyncio.get_running_loop().time()
        last_error: BaseException | None = None
        # Two attempts, and only for genuinely transient conditions. The
        # previous version retried everything, including a 403 from an
        # authority refusing this egress — pointless, and rude to a
        # government host.
        for attempt in range(2):
            try:
                value = await asyncio.wait_for(factory(), timeout=_PROBE_TIMEOUT_CEILING)
                elapsed = round((asyncio.get_running_loop().time() - started) * 1000)
                result = {"provider": name, "provider_key": provider_key, "status": "live",
                          "latency_ms": elapsed, "attempts": attempt + 1}
                if isinstance(value, dict) and "reachable_url" in value:
                    result["reachable_url"] = value["reachable_url"]
                return result
            except StaleObservation as exc:
                # Reachable and parseable, but behind its own cadence. Not a
                # failure — an operator needs these told apart.
                return {"provider": name, "provider_key": provider_key, "status": "stale",
                        "latency_ms": round((asyncio.get_running_loop().time() - started) * 1000),
                        "detail": _redact(str(exc))[:240]}
            except Exception as exc:
                last_error = exc
                if attempt == 0 and is_retryable(exc):
                    await asyncio.sleep(0.25)
                    continue
                break

        assert last_error is not None
        return {
            "provider": name, "provider_key": provider_key, "status": "failed",
            "error": _redact(f"{type(last_error).__name__}: {str(last_error)}")[:240],
            # Contract drift and an outage need different responses, and
            # they are indistinguishable in a bare error string.
            "kind": "contract" if isinstance(last_error, EmptyResponse) else "transport",
        }


async def _check_registry(expected_keys: set[str]) -> dict:
    """Every connector needs an ACTIVE registry row, or a real query is
    rejected by the licence gate before the connector is ever reached — a
    failure no amount of upstream health would reveal.

    Skips cleanly when no database is reachable: the canary runs in CI where
    one may not exist, and failing the run over an absent database would be
    an alarm about the wrong thing.
    """
    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.domains.live_sources.models import LiveSourceProvider

        async with AsyncSessionLocal() as db:
            rows = await db.execute(select(LiveSourceProvider.provider_key, LiveSourceProvider.status))
            registry = {key: status for key, status in rows.all()}
    except Exception as exc:
        return {"provider": "provider_registry", "status": "skipped",
                "detail": f"no database reachable: {type(exc).__name__}"}

    missing = sorted(expected_keys - set(registry))
    disabled = sorted(key for key in expected_keys & set(registry) if registry[key] != "ACTIVE")
    if missing or disabled:
        return {"provider": "provider_registry", "status": "failed",
                "error": f"missing rows: {missing or 'none'}; not ACTIVE: {disabled or 'none'}",
                "kind": "configuration"}
    return {"provider": "provider_registry", "status": "live", "rows": len(expected_keys)}


async def _stamp_successful_contacts(results: list[dict]) -> None:
    """Record last_successful_sync for every provider the canary reached.

    Written here rather than in fetch_live_data() on purpose: stamping from
    the request path would put a database write into a user's latency budget
    to record something the canary already knows. Only sanctions syncs write
    this from the job side; this covers the live APIs.
    """
    reached = [item["provider_key"] for item in results
               if item.get("status") == "live" and item.get("provider_key")]
    if not reached:
        return
    try:
        from sqlalchemy import update

        from app.core.database import AsyncSessionLocal
        from app.domains.live_sources.models import LiveSourceProvider

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(LiveSourceProvider)
                .where(LiveSourceProvider.provider_key.in_(reached))
                .values(last_successful_sync=datetime.now(timezone.utc))
            )
            await db.commit()
    except Exception as exc:
        # Bookkeeping must never decide the exit code of a health check.
        print(f"note: could not record last_successful_sync ({type(exc).__name__})", file=sys.stderr)


def _summarise(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "failed": sorted(item["provider"] for item in results if item["status"] == "failed"),
        "stale": sorted(item["provider"] for item in results if item["status"] == "stale"),
        "unconfigured": sorted(item["provider"] for item in results if item["status"] == "unconfigured"),
    }


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--concurrency", type=int, default=1,
        # Default 1 because this workstation's resolver intermittently
        # returns WSAHOST_NOT_FOUND when many unrelated hosts are resolved at
        # once, and a health check values an accurate answer over a fast one.
        # CI has no such problem and should raise it — serial probing of ~35
        # sources against a 90s ceiling is a long job.
        help="parallel probes (default 1; raise in CI)",
    )
    parser.add_argument("--json", type=Path, default=None, help="also write the report to this path")
    parser.add_argument("--skip-registry", action="store_true", help="do not check the provider registry")
    args = parser.parse_args(argv)

    probes = _build_probes()
    limit = asyncio.Semaphore(max(1, args.concurrency))
    try:
        results = list(await asyncio.gather(*(
            _run_probe(name, provider_key, factory, configured, limit)
            for name, provider_key, factory, configured in probes
        )))
        if not args.skip_registry:
            results.append(await _check_registry({key for _, key, _, _ in probes if key}))
        await _stamp_successful_contacts(results)
    finally:
        await close_shared_http_client()

    report = {"summary": _summarise(results), "providers": results}
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
