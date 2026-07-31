"""Read-only external-source health check.

Run from ``backend`` with ``python scripts/check_external_sources.py``.
It prints no credentials and exits non-zero when any configured provider
cannot return a minimally valid response.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.domains.live_sources.connectors.bank_of_england import BankOfEnglandConnector
from app.domains.live_sources.connectors.companies_house import CompaniesHouseConnector
from app.domains.live_sources.connectors.frankfurter import FrankfurterConnector
from app.domains.live_sources.connectors.fred import FREDConnector
from app.domains.live_sources.connectors.gleif import GLEIFConnector
from app.domains.live_sources.connectors.oecd import OECDConnector
from app.domains.live_sources.connectors.ons import ONSConnector
from app.domains.live_sources.connectors.sec_edgar import SECEdgarConnector
from app.domains.live_sources.connectors.world_bank import WorldBankConnector
from app.domains.live_sources.connectors.cellar import CellarConnector
from app.domains.live_sources.connectors.legislation_gov_uk import LegislationGovUKConnector
from app.domains.live_sources.connectors.ted import TEDConnector
from app.domains.live_sources.connectors.sam_gov import SAMGovConnector
from app.domains.live_sources.sanctions_service import get_snapshot
from app.domains.live_sources.connectors.ecb import ECBConnector
from app.domains.live_sources.connectors.imf import IMFConnector
from app.domains.live_sources.connectors.vies import VIESConnector
from app.domains.live_sources.connectors.regulations_gov import RegulationsGovConnector
from app.domains.live_sources.evidence_schemas import EvidenceSearchIntent
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
_health_limit: asyncio.Semaphore | None = None


async def _check(name: str, call, *, configured: bool = True) -> dict:
    global _health_limit
    if not configured:
        return {"provider": name, "status": "unconfigured"}
    if _health_limit is None:
        # This workstation's resolver intermittently returns WSAHOST_NOT_FOUND
        # when many unrelated hosts are resolved concurrently. A health check
        # values an accurate result over speed, so probe providers serially.
        _health_limit = asyncio.Semaphore(1)
    async with _health_limit:
        started = asyncio.get_running_loop().time()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                value = await asyncio.wait_for(call(), timeout=45)
                if value in (None, [], {}):
                    raise ValueError("empty response")
                return {
                    "provider": name,
                    "status": "live",
                    "latency_ms": round((asyncio.get_running_loop().time() - started) * 1000),
                    "attempts": attempt + 1,
                }
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.25)
        assert last_error is not None
        return {
            "provider": name,
            "status": "failed",
            "error": f"{type(last_error).__name__}: {str(last_error)[:240]}",
        }


def _intent(provider: str, code: str, label: str, country: str, country_label: str, company: str | None = None):
    return LiveDataIntent(
        provider_key=provider,
        indicator_code=code,
        indicator_label=label,
        country_code=country,
        country_label=country_label,
        company_query=company,
    )


async def main() -> int:
    timeout = settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS
    checks = [
        _check("world_bank", lambda: WorldBankConnector(settings.WORLD_BANK_API_BASE_URL).fetch(
            _intent("world_bank", "NY.GDP.MKTP.CD", "GDP", "IN", "India"), timeout=timeout)),
        _check("ons", lambda: ONSConnector(settings.ONS_API_BASE_URL).fetch(
            _intent("ons", "CP00", "CPIH", "GB", "United Kingdom"), timeout=timeout)),
        _check("bank_of_england", lambda: BankOfEnglandConnector(settings.BANK_OF_ENGLAND_API_BASE_URL).fetch(
            _intent("bank_of_england", "IUDBEDR", "Bank Rate", "GB", "United Kingdom"), timeout=timeout)),
        _check("frankfurter", lambda: FrankfurterConnector(settings.FRANKFURTER_API_BASE_URL).fetch(
            _intent("frankfurter", "USD_GBP", "USD/GBP", "FX", "Global"), timeout=timeout)),
        _check("fred_live", lambda: FREDConnector(settings.FRED_API_BASE_URL, settings.FRED_API_KEY).fetch(
            _intent("fred", "FEDFUNDS", "Federal Funds Rate", "US", "United States"), timeout=timeout),
            configured=bool(settings.FRED_API_KEY)),
        _check("sec_edgar", lambda: SECEdgarConnector(settings.SEC_EDGAR_API_BASE_URL, settings.SEC_EDGAR_USER_AGENT).fetch(
            _intent("sec_edgar", "Assets", "Total Assets", "US", "United States", "Apple"), timeout=timeout),
            configured=bool(settings.SEC_EDGAR_USER_AGENT)),
        _check("companies_house", lambda: CompaniesHouseConnector(settings.COMPANIES_HOUSE_API_BASE_URL, settings.COMPANIES_HOUSE_API_KEY).fetch(
            _intent("companies_house", "profile", "Company Profile", "GB", "United Kingdom", "Tesco"), timeout=timeout),
            configured=bool(settings.COMPANIES_HOUSE_API_KEY)),
        _check("oecd", lambda: OECDConnector(settings.OECD_API_BASE_URL).fetch(
            _intent("oecd", "GBR:CIT_C", "Corporate Tax Rate", "GB", "United Kingdom"), timeout=timeout)),
        _check("gleif", lambda: GLEIFConnector(settings.GLEIF_API_BASE_URL).fetch(
            _intent("gleif", "profile", "Company Profile", "IN", "India", "Tata Motors"), timeout=timeout)),
        _check("ecb", lambda: ECBConnector(settings.ECB_API_BASE_URL).fetch(
            _intent("ecb", "FM:D.U2.EUR.4F.KR.DFR.LEV", "ECB Deposit Facility Rate", "EURO_AREA", "Euro area"), timeout=timeout)),
        _check("imf", lambda: IMFConnector(settings.IMF_API_BASE_URL).fetch(
            _intent("imf", "NGDP_RPCH:IND", "Real GDP Growth", "IN", "India"), timeout=timeout)),
        _check("vies", lambda: VIESConnector(settings.VIES_API_BASE_URL).fetch(
            _intent("vies", "vat_validation", "EU VAT Validation", "DE", "Germany", "DE123456789"), timeout=timeout)),
        _check("regulations_gov", lambda: RegulationsGovConnector(
            settings.REGULATIONS_GOV_API_BASE_URL, settings.REGULATIONS_GOV_API_KEY,
        ).search(EvidenceSearchIntent(provider_key="regulations_gov", query="tax reporting", page_size=1), timeout=timeout),
            configured=bool(settings.REGULATIONS_GOV_API_KEY)),
        _check("cellar", lambda: CellarConnector(settings.CELLAR_SPARQL_URL).search(
            EvidenceSearchIntent(provider_key="cellar", query="Artificial Intelligence Act", page_size=1), timeout=timeout)),
        _check("legislation_gov_uk", lambda: LegislationGovUKConnector(settings.LEGISLATION_GOV_UK_BASE_URL).search(
            EvidenceSearchIntent(provider_key="legislation_gov_uk", query="Companies Act", page_size=1), timeout=timeout)),
        _check("ted", lambda: TEDConnector(settings.TED_API_BASE_URL).search(
            EvidenceSearchIntent(provider_key="ted", query="audit services", page_size=1), timeout=timeout)),
        _check("sam_gov", lambda: SAMGovConnector(settings.SAM_GOV_OPPORTUNITIES_URL, settings.SAM_GOV_API_KEY).search(
            EvidenceSearchIntent(provider_key="sam_gov", query="audit services", page_size=1), timeout=timeout),
            configured=bool(settings.SAM_GOV_API_KEY)),
        _check("ofac_snapshot", lambda: get_snapshot("ofac")),
        _check("un_sanctions_snapshot", lambda: get_snapshot("un_sanctions")),
        _check("uk_sanctions_snapshot", lambda: get_snapshot("uk_sanctions")),
        _check("eu_sanctions_snapshot", lambda: get_snapshot("eu_sanctions")),
        _check("treasury", lambda: get_exchange_rates(since="2025-01-01")),
        _check("payroll_tax", lambda: get_payroll_tax_rates("CA", date.today().isoformat()), configured=bool(settings.PAYROLL_TAX_API_KEY)),
        _check("census", lambda: get_state_income_poverty("06", "2024"), configured=bool(settings.CENSUS_API_KEY)),
        _check("bls", lambda: get_cpi_series("2025", "2025")),
        _check("bea", lambda: get_gdp_data("2025"), configured=bool(settings.BEA_API_KEY)),
        _check("fred_reference", lambda: get_series_observations("FEDFUNDS", limit=1), configured=bool(settings.FRED_API_KEY)),
        _check("govinfo", lambda: get_govinfo_section("1.61-1"), configured=bool(settings.GOVINFO_API_KEY)),
        _check("federal_register", lambda: get_document("2026-13925")),
        _check("ecfr", lambda: get_ecfr_section("1.61-1")),
        _check("congress", lambda: get_bill(119, "hr", 1), configured=bool(settings.CONGRESS_API_KEY)),
        _check("tavily", lambda: search_tavily("site:irs.gov standard deduction 2026"), configured=bool(settings.TAVILY_API_KEY)),
        _check("serpapi", lambda: search_serpapi("site:irs.gov standard deduction 2026"), configured=bool(settings.SERP_API_KEY)),
    ]
    results = await asyncio.gather(*checks)
    print(json.dumps(results, indent=2))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
