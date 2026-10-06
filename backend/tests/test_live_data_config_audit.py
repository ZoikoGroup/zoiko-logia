"""Regression tests for the 10-country live-data configuration audit.

Every test here corresponds to a real, verified problem found during the audit,
or to an invariant whose breakage would silently reintroduce one. None of them
read, print or require a real secret: provider keys are supplied through
monkeypatch as literals, and backend/.env is inspected for STRUCTURE (variable
names and line numbers) only — never for values.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.domains.market_data.identity import resolve_index
from app.domains.market_data.providers.base import BaseStockProvider
from app.domains.market_data.providers.companies_house import CompaniesHouseProvider
from app.domains.market_data.providers.finnhub import FinnhubProvider
from app.domains.market_data.providers.index_quote import IndexQuoteProvider
from app.domains.market_data.providers.polygon import PolygonProvider
from app.domains.market_data.providers.alpha_vantage import AlphaVantageProvider
from app.domains.market_data.registry import (
    INTENT_INDEX, INTENT_QUOTE, all_providers, providers_for,
)
from app.domains.market_data.schemas import (
    FRESHNESS_DELAYED, FRESHNESS_HISTORICAL, FRESHNESS_REALTIME,
    EntityRef, ProviderBadResponse,
)
from app.orchestration import dbnomics
from app.orchestration.fred import _definition_for_query, _fred_base

BACKEND = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND / ".env"
# These audit a developer's local backend/.env against the tracked template.
# CI has no .env (and must not), so there is nothing to audit there.
requires_local_env = pytest.mark.skipif(not ENV_FILE.exists(), reason="no local backend/.env to audit (CI)")
EXAMPLE_FILE = BACKEND / ".env.example"


# ── helpers ──────────────────────────────────────────────────────────────────

def _active_assignments(path: Path) -> list[tuple[int, str]]:
    """(lineno, VAR_NAME) for every non-comment assignment. Values discarded."""
    rows: list[tuple[int, str]] = []
    if not path.exists():
        return rows
    for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            rows.append((lineno, m.group(1)))
    return rows


def _line_for(path: Path, name: str) -> int | None:
    for lineno, var in _active_assignments(path):
        if var == name:
            return lineno
    return None


def _duplicates(path: Path) -> dict[str, list[int]]:
    seen: dict[str, list[int]] = {}
    for lineno, name in _active_assignments(path):
        seen.setdefault(name, []).append(lineno)
    return {k: v for k, v in seen.items() if len(v) > 1}


# ═══════════════════════════════════════════════════════════════════════════
# 1. Configuration hygiene — the duplicates this audit removed
# ═══════════════════════════════════════════════════════════════════════════

def test_backend_env_has_no_duplicate_variable():
    """backend/.env previously defined 19 variables twice (FRED, DBNOMICS,
    FRANKFURTER, SEC_USER_AGENT, the four market keys, the four LLM keys and
    the storage/Celery block). python-dotenv resolves duplicates by last-wins,
    so an edit to the wrong copy would be silently ignored."""
    dups = _duplicates(ENV_FILE)
    assert dups == {}, f"duplicate variable(s) in backend/.env: {dups}"


def test_env_example_has_no_duplicate_variable():
    """GROQ_MODEL was declared twice in .env.example with two DIFFERENT model
    ids (llama-3.1-70b-versatile and openai/gpt-oss-120b)."""
    dups = _duplicates(EXAMPLE_FILE)
    assert dups == {}, f"duplicate variable(s) in backend/.env.example: {dups}"


@requires_local_env
def test_fred_is_configured_exactly_once():
    rows = [n for _, n in _active_assignments(ENV_FILE) if n.startswith("FRED_")]
    assert sorted(rows) == ["FRED_API_BASE_URL", "FRED_API_KEY"]


@requires_local_env
def test_removed_twelve_data_config_is_absent():
    """The Twelve Data adapter was reverted (commit 4be63d6) but its key and
    realtime flag stayed in backend/.env. No code read either one, so a live
    credential was sitting in the file for a provider that cannot run."""
    names = {n for _, n in _active_assignments(ENV_FILE)}
    assert "TWELVE_DATA_API_KEY" not in names
    assert "TWELVE_DATA_REALTIME" not in names


def test_no_provider_module_reference_removed_config():
    """Guards the decision to delete Twelve Data config: if an adapter ever
    returns, this test fails and the operator is told to re-add the key."""
    from app.domains.market_data import registry

    assert not hasattr(registry, "TwelveDataProvider")
    assert all(p.name != "twelve_data" for p in all_providers())


# ═══════════════════════════════════════════════════════════════════════════
# 2. .env / .env.example drift
# ═══════════════════════════════════════════════════════════════════════════

def test_fred_is_documented_in_env_example_with_a_placeholder():
    """FRED was absent from .env.example entirely, so a fresh clone had no way
    to discover it. The documented value must be a placeholder, never a key."""
    assert _line_for(EXAMPLE_FILE, "FRED_API_KEY") is not None
    assert _line_for(EXAMPLE_FILE, "FRED_API_BASE_URL") is not None


@requires_local_env
def test_env_example_contains_no_live_secret():
    """backend/.env.example must never carry a real credential. Compared by
    VALUE against backend/.env and reported only as a boolean."""
    env_values: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", s)
        if m:
            env_values[m.group(1)] = m.group(2).strip()

    secretish = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|SERVICE_ROLE|CREDENTIAL)$")
    offenders: list[str] = []
    for raw in EXAMPLE_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", s)
        if not m:
            continue
        name, val = m.group(1), m.group(2).strip()
        if not secretish.search(name) or not val:
            continue
        if name in env_values and env_values[name] == val:
            offenders.append(name)
    assert offenders == [], f"live secret copied into .env.example: {offenders}"


def test_every_live_data_url_var_is_documented_in_env_example():
    """The 10-country live-data base URLs are the whole live-data surface, so
    each must appear in the example file. Keys are checked by name only."""
    url_names = {
        name for _, name in _active_assignments(ENV_FILE)
        if name.endswith(("_API_BASE_URL", "_BASE_URL", "_CSV_URL")) and name != "DATABASE_URL"
    }
    example_names = {n for _, n in _active_assignments(EXAMPLE_FILE)}
    missing = sorted(url_names - example_names)
    assert missing == [], f"live-data URL(s) missing from .env.example: {missing}"


@requires_local_env
def test_env_and_env_example_declare_the_same_variable_names():
    """The two files are meant to carry the same variable NAMES and to differ
    only in values (real credential vs placeholder/blank).

    This was drift-prone: a variable added to .env alone is invisible to anyone
    reading the tracked template, and a variable documented in .env.example with
    no .env counterpart is a claim the operator's local config does not make.
    Ordering is deliberately NOT compared - the two files group related settings
    differently on purpose."""
    env_names = {n for _, n in _active_assignments(ENV_FILE)}
    example_names = {n for _, n in _active_assignments(EXAMPLE_FILE)}

    assert env_names - example_names == set(), (
        "declared in .env but absent from .env.example, so a fresh clone has no "
        f"way to discover them: {sorted(env_names - example_names)}"
    )
    assert example_names - env_names == set(), (
        "documented in .env.example but absent from .env: "
        f"{sorted(example_names - env_names)}"
    )


def test_every_env_var_read_by_production_is_discoverable_in_env_example():
    """An env var read by production code but present in neither file cannot be
    tuned by an operator, and looks indistinguishable from a typo. Every
    non-comment assignment in .env.example is therefore checked against the
    names production actually reads.

    Variables read only through a pydantic Settings field or an indirect
    ``API_KEY_ENV``/``BASE_URL_ENV`` module constant are resolved through
    ``get_settings()``/``BaseProvider.base_url()`` rather than read literally, so
    they are covered by their sibling base-URL tests instead."""
    production_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (BACKEND / "app").rglob("*.py")
    )
    read_names = set(
        re.findall(r"os\.(?:getenv|environ\.get|environ\[)\(\s*\"([A-Z0-9_]+)\"", production_text)
    )
    assert read_names, "scanner matched no production env reads; the check itself is broken"

    documented = {n for _, n in _active_assignments(EXAMPLE_FILE)}
    # Variables intentionally left commented out in the template so they do not
    # silently take effect, but which must still be discoverable there.
    commented = set(
        re.findall(r"^#\s*([A-Z0-9_]+)\s*=", EXAMPLE_FILE.read_text(encoding="utf-8", errors="replace"), re.M)
    )
    undiscoverable = read_names - documented - commented
    assert undiscoverable == set(), (
        "read by production code but present in .env.example as neither an active "
        f"nor a commented assignment: {sorted(undiscoverable)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3. env value must take precedence over the code default
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "provider_cls,env_name,default",
    [
        (FinnhubProvider, "FINNHUB_API_BASE_URL", "https://finnhub.io/api/v1"),
        (PolygonProvider, "POLYGON_API_BASE_URL", "https://api.polygon.io"),
        (AlphaVantageProvider, "ALPHA_VANTAGE_API_BASE_URL", "https://www.alphavantage.co"),
        (
            CompaniesHouseProvider,
            "COMPANIES_HOUSE_API_BASE_URL",
            "https://api.company-information.service.gov.uk",
        ),
    ],
)
def test_provider_env_url_overrides_code_default(monkeypatch, provider_cls, env_name, default):
    monkeypatch.setenv(env_name, "https://proxy.example.invalid/base")
    assert provider_cls().base_url() == "https://proxy.example.invalid/base"

    monkeypatch.delenv(env_name, raising=False)
    assert provider_cls().base_url() == default


@pytest.mark.parametrize(
    "env_name,expected",
    [
        ("DBNOMICS_API_BASE_URL", "https://api.db.nomics.world/v22"),
        ("WORLD_BANK_API_BASE_URL", "https://api.worldbank.org/v2"),
        ("FRANKFURTER_API_BASE_URL", "https://api.frankfurter.dev/v1"),
        ("FRED_API_BASE_URL", "https://api.stlouisfed.org/fred"),
        ("YAHOO_INDEX_API_BASE_URL", "https://query1.finance.yahoo.com/v8/finance"),
    ],
)
def test_economic_connector_base_url_is_env_driven(monkeypatch, env_name, expected):
    """Each connector must resolve its base URL from the environment and fall
    back to exactly this default, so a .env value is never ignored."""
    monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv(env_name, expected + "/v22-check")
    probes = {
        "DBNOMICS_API_BASE_URL": dbnomics._dbnomics_base,
        "WORLD_BANK_API_BASE_URL": dbnomics._world_bank_base,
        "FRANKFURTER_API_BASE_URL": lambda: __import__(
            "app.orchestration.frankfurter", fromlist=["_frankfurter_base"]
        )._frankfurter_base(),
        "FRED_API_BASE_URL": _fred_base,
        "YAHOO_INDEX_API_BASE_URL": IndexQuoteProvider().base_url,
    }
    assert probes[env_name]() == expected + "/v22-check"


def test_trailing_slash_is_stripped_from_every_configured_base_url(monkeypatch):
    """A trailing slash in .env would produce '//endpoint' once the provider
    appends its own path."""
    monkeypatch.setenv("FRED_API_BASE_URL", "https://api.stlouisfed.org/fred/")
    assert _fred_base() == "https://api.stlouisfed.org/fred"

    monkeypatch.setenv("FINNHUB_API_BASE_URL", "https://finnhub.io/api/v1/")
    assert FinnhubProvider().base_url() == "https://finnhub.io/api/v1"


@pytest.mark.parametrize(
    "bad",
    [
        "https://api.stlouisfed.org/fredFRED_API_KEY=pasted-on-the-end",
        "not-a-url",
        "ftp://api.stlouisfed.org/fred",
    ],
)
def test_malformed_fred_base_url_falls_back_to_safe_default(monkeypatch, bad):
    monkeypatch.setenv("FRED_API_BASE_URL", bad)
    assert _fred_base() == "https://api.stlouisfed.org/fred"


# ═══════════════════════════════════════════════════════════════════════════
# 4. key-gated providers
# ═══════════════════════════════════════════════════════════════════════════

KEY_GATED = {
    "finnhub": "FINNHUB_API_KEY",
    "polygon": "POLYGON_API_KEY",
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
    "companies_house": "COMPANIES_HOUSE_API_KEY",
}


@pytest.mark.parametrize("provider_name,env_name", sorted(KEY_GATED.items()))
def test_key_gated_provider_uses_the_documented_variable(provider_name, env_name):
    provider = next(p for p in all_providers() if p.name == provider_name)
    assert provider.API_KEY_ENV == env_name
    assert provider.BASE_URL_ENV == env_name.replace("_API_KEY", "_API_BASE_URL")
    assert provider.DEFAULT_BASE_URL, "a safe code default must survive an unset env var"


@pytest.mark.parametrize("provider_name,env_name", sorted(KEY_GATED.items()))
def test_unconfigured_provider_is_skipped_silently_not_raised(monkeypatch, provider_name, env_name):
    monkeypatch.delenv(env_name, raising=False)
    provider = next(p for p in all_providers() if p.name == provider_name)
    assert provider.configured() is False
    with pytest.raises(Exception) as excinfo:
        provider.require_configured()
    assert env_name in str(excinfo.value), "the error must name the variable, never its value"


def test_index_provider_is_enabled_without_a_key_and_refuses_non_indices():
    """Index levels had no source at all before this adapter, so it is on by
    design — but it must still refuse an ordinary ticker."""
    assert IndexQuoteProvider().configured() is True

    async def refuse(symbol):
        provider = IndexQuoteProvider()
        with pytest.raises(ProviderBadResponse):
            # _chart checks the symbol before it ever touches the client, so
            # passing a dummy client is safe: reaching the client at all would
            # raise AttributeError instead.
            await provider._chart(object(), symbol, "5d")

    # The documented promise is the caret PREFIX, plus one carve-out. "^" alone
    # satisfies the prefix, so it is not something the guard claims to refuse.
    for bad in ("AAPL", "7203.T", "EURUSD=X", "600519.SS", "SSE Composite"):
        asyncio.run(refuse(bad))


def test_sse_composite_caret_less_code_is_the_one_documented_exception():
    """Yahoo retired ^SSEC (HTTP 404) and serves the SSE Composite only as
    000001.SS, so that single caret-less code must survive the guard."""
    resolved = resolve_index("SSE Composite")
    assert resolved[0] == "000001.SS"

    seen: list[str] = []

    async def spy(client, provider, base_url, symbol, **kwargs):
        seen.append(symbol)
        return {"meta": {"regularMarketPrice": 1.0}}

    from app.domains.market_data.providers import index_quote as iq

    original = iq.fetch_chart
    iq.fetch_chart = spy
    try:
        asyncio.run(iq.IndexQuoteProvider()._chart(object(), "000001.SS", "5d"))
    finally:
        iq.fetch_chart = original
    assert seen == ["000001.SS"]


def test_fred_is_inert_without_a_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert _definition_for_query("US GDP") is None


# ═══════════════════════════════════════════════════════════════════════════
# 5. wrong-statistic protection (the two bugs fixed by this audit)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "query",
    [
        "US GDP per capita",
        "US GDP per head",
        "US nominal GDP per capita",
        "gross domestic product per capita in the US",
    ],
)
def test_fred_never_answers_a_per_capita_question_with_total_gdp(monkeypatch, query):
    """'GDP' as a pattern alternative matched 'US GDP per capita', so the
    connector reported total nominal GDP (~$30tn, billions of USD) as a
    per-capita figure — wrong by three orders of magnitude, with a real FRED
    URL attached. FRED must decline and let NGDPDPC answer instead."""
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    definition = _definition_for_query(query)
    assert definition is None or definition.series_id not in {"GDP", "GDPC1"}


@pytest.mark.parametrize(
    "query,expected",
    [
        ("US GDP", "GDP"),
        ("What is the US GDP", "GDP"),
        ("US nominal GDP", "GDP"),
        ("US real GDP", "GDPC1"),
        ("US GDP growth", "A191RL1Q225SBEA"),
        ("US GDP in 2024", "GDP"),
    ],
)
def test_fred_still_answers_plain_gdp_phrasings(monkeypatch, query, expected):
    """The per-capita guard must not narrow ordinary GDP questions."""
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    assert _definition_for_query(query).series_id == expected


def test_australia_cpi_reports_a_gap_instead_of_raising():
    """Australia is deliberately in _CPI_COUNTRIES (to stop generic full-text
    search returning ABS *energy* inflation) and deliberately out of
    _CPI_COUNTRY_CODES (IMF publishes no AU series). Indexing that second dict
    raised KeyError, which the live_data fan-out swallowed — so Australia was
    only answered correctly by accident. It must now return None, which is what
    abs_australia.py then fills from the statistical agency."""
    assert "Australia" in set(dbnomics._CPI_COUNTRIES.values())
    assert "Australia" not in dbnomics._CPI_COUNTRY_CODES

    for query in ("Australia CPI inflation", "Australia CPI", "Australia inflation rate"):
        assert asyncio.run(dbnomics._find_cpi_series(query)) is None


@pytest.mark.parametrize(
    "query",
    [
        "Australia CPI inflation",
        "Australia consumer price index",
        "Australia inflation",
    ],
)
def test_australia_cpi_never_falls_back_to_a_foreign_series(query, monkeypatch):
    """The honest gap must stay a gap. If a future edit lets this reach generic
    ranking, a neighbour country's CPI would answer an Australian question."""
    calls: list[str] = []

    async def spy(text):
        calls.append(text)
        return None

    monkeypatch.setattr(dbnomics, "_find_generic_series", spy)
    assert asyncio.run(dbnomics._find_best_series(query)) is None
    assert calls == [], f"generic fallback was used for {query!r}"


def test_cpi_countries_without_an_imf_code_do_not_raise():
    """Every country _CPI_COUNTRIES recognises must resolve without raising,
    whether or not it has an IMF series code."""
    recognised = set(dbnomics._CPI_COUNTRIES.values())
    missing_code = recognised - set(dbnomics._CPI_COUNTRY_CODES)
    for country in missing_code:
        assert country == "Australia", (
            f"unexpected country without an IMF CPI code: {country}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6. India policy rate stays a gap — the stale IMF IFS series must not return
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "query",
    [
        "India policy rate",
        "India interest rate",
        "India repo rate",
        "India bank rate",
        "India MCLR",
        "India base rate",
    ],
)
def test_india_policy_rate_has_no_structured_series(query):
    """India's IMF IFS policy rate has been frozen at 6.25% since 2017. It is
    deliberately excluded from _POLICY_RATE_SOURCES and _find_best_series
    returns that None directly, so the question falls through to the ordinary
    web-grounded path. Any future edit that re-admits it turns a stale 2017
    figure into a claimed current rate."""
    assert asyncio.run(dbnomics._find_policy_rate_series(query)) is None


def test_india_is_absent_from_every_policy_rate_source():
    assert "India" not in dbnomics._POLICY_RATE_SOURCES
    assert dbnomics._POLICY_RATE_SOURCES, "the other countries must still be configured"


def test_stale_india_series_id_is_not_referenced_anywhere():
    source = (BACKEND / "app" / "orchestration" / "dbnomics.py").read_text(encoding="utf-8")
    code_only = [
        ln for ln in source.splitlines()
        if "M.IN.FPOLM_PA" in ln and not ln.strip().startswith("#")
    ]
    assert code_only == [], "the frozen India IFS series id must not appear in code"


@pytest.mark.parametrize("country", ["Germany", "France", "Japan", "China"])
def test_policy_rate_source_table_is_intact(country):
    assert country in dbnomics._POLICY_RATE_SOURCES
    assert country not in {"India", "United States"}


# ═══════════════════════════════════════════════════════════════════════════
# 7. country routing / cross-contamination
# ═══════════════════════════════════════════════════════════════════════════

TEN_COUNTRIES = {
    "US": "United States", "GB": "United Kingdom", "IE": "Ireland",
    "CA": "Canada", "AU": "Australia", "DE": "Germany", "FR": "France",
    "JP": "Japan", "IN": "India", "CN": "China",
}


@pytest.mark.parametrize("iso2,label", sorted(TEN_COUNTRIES.items()))
def test_country_alias_table_covers_every_supported_country(iso2, label):
    """dbnomics anchors every lookup on a country, so each of the ten supported
    countries must be resolvable, and _country_in_query must agree."""
    label_l = label.lower()
    assert label_l in set(dbnomics._COUNTRY_ALIASES.values()), (
        f"{label} is missing from the DBnomics country alias table"
    )
    # The table is keyed by country words/adjectives, not ISO2 codes.
    assert dbnomics._COUNTRY_ALIASES.get(iso2.lower()) in (None, label_l)
    assert dbnomics._country_in_query(f"{label} GDP") == label


@pytest.mark.parametrize(
    "query,iso2",
    [
        ("Germany GDP", "DE"),
        ("German GDP", "DE"),
        ("France GDP", "FR"),
        ("French GDP", "FR"),
        ("Japan GDP", "JP"),
        ("Japanese GDP", "JP"),
        ("China GDP", "CN"),
        ("Chinese GDP", "CN"),
        ("India GDP", "IN"),
        ("Canadian GDP", "CA"),
        ("Irish GDP", "IE"),
        ("Australian GDP", "AU"),
    ],
)
def test_country_wording_resolves_to_exactly_one_country(query, iso2):
    """No country name/adjective pair may resolve to another country."""
    assert dbnomics._country_in_query(query) == TEN_COUNTRIES[iso2]


@pytest.mark.parametrize("word", ["Austria", "New Zealand", "Luxembourg", "Chile", "Georgia"])
def test_unsupported_countries_are_never_resolved_as_supported(word):
    assert dbnomics._country_in_query(f"{word} GDP") != TEN_COUNTRIES["AU"]


@pytest.mark.parametrize(
    "index_name,expected_country",
    [
        ("S&P 500", "US"), ("FTSE 100", "GB"), ("TSX Composite", "CA"),
        ("ASX 200", "AU"), ("ISEQ", "IE"), ("DAX", "DE"), ("CAC 40", "FR"),
        ("Nikkei 225", "JP"), ("NIFTY 50", "IN"), ("SENSEX", "IN"),
        ("SSE Composite", "CN"),
    ],
)
def test_market_index_identity(index_name, expected_country):
    """Each benchmark must resolve to its own symbol and its own country —
    a market benchmark quoted at the wrong country's exchange is exactly the
    wrong-data failure this product exists to avoid."""
    resolved = resolve_index(index_name)
    assert resolved is not None, f"{index_name} resolved to no index"
    _, display, country = resolved
    assert country == expected_country, f"{index_name} -> {country}, expected {expected_country}"


@pytest.mark.parametrize(
    "query,expected_symbol",
    [
        ("S&P 500", "^GSPC"),
        ("S&P500", "^GSPC"),
        ("FTSE 100", "^FTSE"),
        ("footsie", "^FTSE"),
        ("TSX Composite", "^GSPTSE"),
        ("ASX 200", "^AXJO"),
        ("ISEQ", "^ISEQ"),
        ("DAX", "^GDAXI"),
        ("CAC 40", "^FCHI"),
        ("Nikkei 225", "^N225"),
        ("NIFTY 50", "^NSEI"),
        ("nifty", "^NSEI"),
        ("SENSEX", "^BSESN"),
        ("SSE Composite", "000001.SS"),
        ("Shanghai composite", "000001.SS"),
    ],
)
def test_market_index_symbol_is_stable(query, expected_symbol):
    """A market benchmark quoted under another index's symbol is the wrong-data
    failure this product exists to avoid, so the name->symbol map is pinned."""
    resolved = resolve_index(query)
    assert resolved is not None, f"{query!r} resolved to no index"
    assert resolved[0] == expected_symbol


def test_index_intent_never_routes_to_a_company_provider():
    """The key-gated providers cannot quote indices, so INTENT_INDEX belongs to
    the keyless index adapter alone."""
    selected = [p.name for p in providers_for(INTENT_INDEX)]
    assert selected == ["index_quote"]


def test_company_quote_intent_never_routes_to_the_index_provider():
    assert "index_quote" not in [p.name for p in providers_for(INTENT_QUOTE)]


# ═══════════════════════════════════════════════════════════════════════════
# 8. freshness labelling
# ═══════════════════════════════════════════════════════════════════════════

def test_yahoo_quotes_are_always_labelled_delayed():
    """Yahoo's chart endpoint states no entitlement, so realtime cannot be
    claimed. Verified by behaviour, not by reading the constant."""
    from app.domains.market_data.providers import yahoo_chart

    meta = {
        "regularMarketPrice": 100.0, "previousClose": 99.0,
        "regularMarketTime": 1_700_000_000,
    }
    quote = yahoo_chart.quote_from_meta(meta, "index_quote", EntityRef(ticker="^GSPC"))
    assert quote.freshness == FRESHNESS_DELAYED
    assert quote.freshness != "realtime"


def test_market_status_reports_yahoos_own_delay_minutes():
    from app.domains.market_data.providers.yahoo_chart import market_status

    assert market_status({"marketState": "REGULAR", "exchangeDataDelayedBy": 15}) == (
        "open, delayed 15 min"
    )
    assert market_status({"marketState": "CLOSED"}) == "closed"


def test_key_gated_providers_default_to_a_conservative_freshness(monkeypatch):
    """Finnhub's feed is delayed and Polygon's free tier only reaches the
    previous close, so their defaults must be 'delayed' and 'historical'
    respectively — never 'realtime'. Realtime is operator-declared only."""
    monkeypatch.delenv("FINNHUB_REALTIME", raising=False)
    monkeypatch.delenv("POLYGON_REALTIME", raising=False)
    assert FinnhubProvider().freshness() == FRESHNESS_DELAYED
    assert PolygonProvider().freshness() == FRESHNESS_HISTORICAL


def test_realtime_is_only_ever_reachable_by_explicit_operator_declaration(monkeypatch):
    monkeypatch.setenv("FINNHUB_REALTIME", "1")
    monkeypatch.setenv("POLYGON_REALTIME", "true")
    assert FinnhubProvider().freshness() == FRESHNESS_REALTIME
    assert PolygonProvider().freshness() == FRESHNESS_REALTIME


def test_base_provider_health_never_echoes_the_key(monkeypatch):
    """health_check feeds a status endpoint, so it must not leak a credential
    even truncated — including through the failure path."""
    from app.domains.market_data.schemas import ProviderHealth

    class _Leaky(BaseStockProvider):
        name = "leaky"
        API_KEY_ENV = "AUDIT_TEST_KEY"

        async def _probe(self, client):
            raise RuntimeError("probe exploded while holding the key")

    monkeypatch.setenv("AUDIT_TEST_KEY", "super-secret-value")
    provider = _Leaky()
    assert provider.configured() is True

    async def go():
        return await provider.health_check(None)

    health = asyncio.run(go())
    assert isinstance(health, ProviderHealth)
    assert health.configured is True
    assert "super-secret-value" not in (health.detail or "")
    assert "super-secret-value" not in repr(health)


def test_unconfigured_provider_error_names_the_variable_but_not_its_value(monkeypatch):
    monkeypatch.delenv("AUDIT_TEST_KEY", raising=False)
    provider = BaseStockProvider()
    provider.API_KEY_ENV = "AUDIT_TEST_KEY"
    with pytest.raises(Exception) as excinfo:
        provider.require_configured()
    assert "AUDIT_TEST_KEY" in str(excinfo.value)


def test_zero_or_missing_price_is_never_reported_as_a_quote():
    """Finnhub answers 200 with every field zeroed for an unknown symbol."""
    from app.domains.market_data.providers.yahoo_chart import quote_from_meta

    with pytest.raises(ProviderBadResponse):
        quote_from_meta({"regularMarketPrice": 0.0}, "index_quote", EntityRef(ticker="^X"))


def test_fred_declines_a_country_it_cannot_serve(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    for query in ("India GDP", "Germany policy rate", "Canada inflation"):
        assert _definition_for_query(query) is None


def test_every_provider_declares_a_name_and_capabilities():
    for provider in all_providers():
        assert provider.name and provider.name != "base"
        assert provider.CAPABILITIES, f"{provider.name} declares no capabilities"