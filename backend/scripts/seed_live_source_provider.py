"""
Seed the LiveSourceProvider registry rows — required once per environment
before ENABLE_LIVE_SOURCES=1 queries will find an ACTIVE provider record
(see app/domains/massarius/license_gate.py's _fetch_live_provider_fields()).

Idempotent, and safe to re-run after the catalogue changes: an existing row
has its catalogue metadata refreshed in place rather than being skipped, so
correcting an authority rank or a licence URL is a re-run, not a manual
UPDATE. Operational columns the runtime owns (status, last_successful_sync,
last_content_hash) are never overwritten from here.

Run:
    python backend/scripts/seed_live_source_provider.py
"""
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, async_engine
from app.db.base import Base
from app.domains.live_sources.models import LiveSourceProvider

settings = get_settings()

_HOUR = 3600
_DAY = 24 * _HOUR


@dataclass(frozen=True)
class ProviderSeed:
    """One row of docs/Kriton_Authoritative_Sources_Catalog.md, in the form
    the runtime can actually enforce.

    authority_rank follows the catalogue's default authority hierarchy:
      1 enacted legislation, official regulations, binding decisions
      2 regulator, tax authority, or accounting/auditing standard setter
      3 official company registry or government filing system
      4 official international organisation
      5 recognised professional-body guidance
      6 commercial or secondary discovery source
    """
    provider_key: str
    display_name: str
    base_url: str
    category: str
    auth_mode: str
    api_key_env_var: str | None
    authority_rank: int
    jurisdiction: str
    integration_type: str
    official_url: str
    licence_terms_url: str
    pricing_model: str
    freshness_sla_seconds: int | None
    export_permission: str


PROVIDERS: tuple[ProviderSeed, ...] = (
    ProviderSeed(
        "world_bank", "World Bank Open Data", settings.WORLD_BANK_API_BASE_URL,
        "macro-economic-data", "none", None, 4, "INTL", "LIVE_API",
        "https://data.worldbank.org/",
        "https://datacatalog.worldbank.org/public-licenses",
        "free", 90 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "ons", "ONS (Office for National Statistics)", settings.ONS_API_BASE_URL,
        "macro-economic-data", "none", None, 2, "GB", "LIVE_API",
        "https://developer.ons.gov.uk/",
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "free", 45 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "bank_of_england", "Bank of England IADB", settings.BANK_OF_ENGLAND_API_BASE_URL,
        "macro-economic-data", "none", None, 2, "GB", "LIVE_API",
        "https://www.bankofengland.co.uk/boeapps/database/",
        "https://www.bankofengland.co.uk/legal/terms-and-conditions",
        "free", 45 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        # A redistribution of ECB reference rates, not the ECB itself —
        # rank 6, so the ECB connector outranks it wherever both could
        # answer the same euro-area question.
        "frankfurter", "Frankfurter (ECB exchange rates)", settings.FRANKFURTER_API_BASE_URL,
        "fx-rates", "none", None, 6, "INTL", "LIVE_API",
        "https://frankfurter.dev/",
        "https://frankfurter.dev/",
        "free", 2 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "fred", "FRED (Federal Reserve Economic Data)", settings.FRED_API_BASE_URL,
        "macro-economic-data", "api_key", "FRED_API_KEY", 2, "US", "LIVE_API",
        "https://fred.stlouisfed.org/",
        "https://fred.stlouisfed.org/legal/",
        "free", 7 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "sec_edgar", "SEC EDGAR Company Facts", settings.SEC_EDGAR_API_BASE_URL,
        "company-financials", "none", None, 3, "US", "LIVE_API",
        "https://www.sec.gov/edgar",
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "free", 7 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "companies_house", "Companies House", settings.COMPANIES_HOUSE_API_BASE_URL,
        "company-financials", "api_key", "COMPANIES_HOUSE_API_KEY", 3, "GB", "LIVE_API",
        "https://developer.company-information.service.gov.uk/",
        "https://developer.company-information.service.gov.uk/terms-and-conditions",
        "free", 7 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "oecd", "OECD (Corporate Tax Rates)", settings.OECD_API_BASE_URL,
        "macro-economic-data", "none", None, 4, "INTL", "LIVE_API",
        "https://www.oecd.org/en/data.html",
        "https://www.oecd.org/en/about/terms-conditions.html",
        "free", 180 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "gleif", "GLEIF (Legal Entity Identifier Registry)", settings.GLEIF_API_BASE_URL,
        "company-financials", "none", None, 4, "INTL", "LIVE_API",
        "https://www.gleif.org/en/lei-data/gleif-api/",
        "https://www.gleif.org/en/meta/lei-data-terms-of-use",
        "free", 7 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "ecb", "European Central Bank Data Portal", settings.ECB_API_BASE_URL,
        "macro-economic-data", "none", None, 2, "EU", "LIVE_API",
        "https://data.ecb.europa.eu/",
        "https://www.ecb.europa.eu/services/using-our-site/html/index.en.html",
        "free", 7 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        "imf", "International Monetary Fund DataMapper", settings.IMF_API_BASE_URL,
        "macro-economic-data", "none", None, 4, "INTL", "LIVE_API",
        "https://www.imf.org/external/datamapper/",
        "https://www.imf.org/external/terms.htm",
        "free", 180 * _DAY, "attribution_required",
    ),
    ProviderSeed(
        # A VAT validation is true as of the moment it is made and has no
        # useful shelf life; a stale one must never be reused as current.
        "vies", "European Commission VIES", settings.VIES_API_BASE_URL,
        "tax-compliance", "none", None, 2, "EU", "LIVE_API",
        "https://ec.europa.eu/taxation_customs/vies/",
        "https://ec.europa.eu/taxation_customs/vies/#/help",
        "free", _HOUR, "attribution_required",
    ),
    ProviderSeed(
        "regulations_gov", "Regulations.gov", settings.REGULATIONS_GOV_API_BASE_URL,
        "us-regulations", "api_key", "REGULATIONS_GOV_API_KEY", 1, "US", "LIVE_API",
        "https://www.regulations.gov/",
        "https://open.gsa.gov/api/regulationsgov/",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "cellar", "EU Publications Office Cellar", settings.CELLAR_SPARQL_URL,
        "eu-legislation", "none", None, 1, "EU", "LIVE_API",
        "https://eur-lex.europa.eu/",
        "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "legislation_gov_uk", "legislation.gov.uk", settings.LEGISLATION_GOV_UK_BASE_URL,
        "uk-legislation", "none", None, 1, "GB", "LIVE_API",
        "https://www.legislation.gov.uk/",
        "https://www.legislation.gov.uk/help#usingLegislation",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "ted", "Tenders Electronic Daily", settings.TED_API_BASE_URL,
        "public-procurement", "none", None, 4, "EU", "LIVE_API",
        "https://ted.europa.eu/",
        "https://ted.europa.eu/en/simap/legal-notice",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "sam_gov", "SAM.gov Contract Opportunities", settings.SAM_GOV_OPPORTUNITIES_URL,
        "public-procurement", "api_key", "SAM_GOV_API_KEY", 3, "US", "LIVE_API",
        "https://sam.gov/",
        "https://open.gsa.gov/api/get-opportunities-public-api/",
        "free", _DAY, "attribution_required",
    ),
    # Sanctions feeds are SCHEDULED_FEED. Their freshness SLA is a contract
    # sanctions_service.get_snapshot() already enforces by failing closed on
    # a stale snapshot rather than answering from one.
    ProviderSeed(
        "ofac", "OFAC Sanctions List Service", settings.OFAC_SDN_XML_URL,
        "financial-crime", "none", None, 1, "US", "SCHEDULED_FEED",
        "https://ofac.treasury.gov/sanctions-list-service",
        "https://ofac.treasury.gov/",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "un_sanctions", "UN Security Council Consolidated List", settings.UN_SANCTIONS_XML_URL,
        "financial-crime", "none", None, 1, "UN", "SCHEDULED_FEED",
        "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
        "https://www.un.org/en/about-us/terms-of-use",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "uk_sanctions", "UK Sanctions List", settings.UK_SANCTIONS_CSV_URL,
        "financial-crime", "none", None, 1, "GB", "SCHEDULED_FEED",
        "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "free", _DAY, "attribution_required",
    ),
    ProviderSeed(
        "eu_sanctions", "EU Consolidated Financial Sanctions List",
        settings.EU_SANCTIONS_CSV_URL or "https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures_en",
        "financial-crime", "none", None, 1, "EU", "SCHEDULED_FEED",
        "https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures_en",
        "https://ec.europa.eu/info/legal-notice_en",
        "free", _DAY, "attribution_required",
    ),
)


def _apply_catalogue_fields(row: LiveSourceProvider, seed: ProviderSeed) -> bool:
    """Copy catalogue-owned fields onto a row. Returns True if anything
    changed, so a re-run reports real updates instead of claiming work it
    did not do."""
    catalogue_fields = {
        "display_name": seed.display_name,
        "category": seed.category,
        "base_url": seed.base_url,
        "auth_mode": seed.auth_mode,
        "api_key_env_var": seed.api_key_env_var,
        "authority_rank": seed.authority_rank,
        "jurisdiction": seed.jurisdiction,
        "integration_type": seed.integration_type,
        "official_url": seed.official_url,
        "licence_terms_url": seed.licence_terms_url,
        "pricing_model": seed.pricing_model,
        "freshness_sla_seconds": seed.freshness_sla_seconds,
        "export_permission": seed.export_permission,
    }
    changed = False
    for field, value in catalogue_fields.items():
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    return changed


async def seed_provider(db, seed: ProviderSeed) -> None:
    existing = await db.execute(
        select(LiveSourceProvider).where(LiveSourceProvider.provider_key == seed.provider_key)
    )
    row = existing.scalar_one_or_none()

    if row is not None:
        if _apply_catalogue_fields(row, seed):
            await db.commit()
            print(f"Updated LiveSourceProvider '{seed.provider_key}' from the catalogue.")
        else:
            print(f"LiveSourceProvider '{seed.provider_key}' already current, skipping.")
        return

    row = LiveSourceProvider(
        provider_key=seed.provider_key,
        licence_state="permitted",
        # authority_level stays the licence gate's coarse three-value
        # vocabulary; authority_rank carries the catalogue's 1-6 hierarchy.
        authority_level="primary",
        is_tenant_private=False,
        status="ACTIVE",
    )
    _apply_catalogue_fields(row, seed)
    db.add(row)
    await db.commit()
    print(f"Seeded LiveSourceProvider '{seed.provider_key}'.")


async def seed() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for provider in PROVIDERS:
            await seed_provider(db, provider)


if __name__ == "__main__":
    asyncio.run(seed())
